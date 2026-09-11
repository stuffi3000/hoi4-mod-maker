"""Province Validator — detects various issues in HOI4 province maps"""
import numpy as np
from collections import deque
from scipy import ndimage

from data.constants import (
    MAP_WIDTH,
    TILE_LAND, TILE_SEA, TILE_LAKE,
    MIN_PROVINCE_PIXELS,
)


_CROSS = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)


def validate_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    *,
    min_pixels: int = MIN_PROVINCE_PIXELS,
) -> dict:
    """Validate the province map and detect any issues that may cause HOI4 to crash.

    Return:
        {
            "x_crossings": int, # Number of X-shaped crossings
            "x_crossing_positions": list, # Crossing position list [(y, x), ...]
            "too_small": int, # Number of provinces that are too small
            "too_small_ids": list, # Too small province ID list
            "not_contiguous": int, # Number of discontinuous provinces
            "not_contiguous_ids": list, # Discontinuous province ID list
            "coastal_mismatch": int, # Number of coastal status inconsistencies
            "coastal_mismatch_ids": list, # List of inconsistent province IDs
        }"""
    results = {
        "x_crossings": 0,
        "x_crossing_positions": [],
        "too_small": 0,
        "too_small_ids": [],
        "not_contiguous": 0,
        "not_contiguous_ids": [],
        "coastal_mismatch": 0,
        "coastal_mismatch_ids": [],
        # New: HOI4 documentation clear hard rules
        "too_large": 0,           # Single Dart Width/Height > Map 1/8 (TOO LARGE BOX Error)
        "too_large_ids": [],
        "id_gaps": [],            # ID is a discontinuous position (there should be no holes between 1..N)
        "total_provinces": 0,
        "count_warning": "",      # Total warning string
    }

    if province_map.max() == 0:
        return results

    # 1. X-shaped cross detection
    x_positions = detect_x_crossings(province_map)
    results["x_crossings"] = len(x_positions)
    results["x_crossing_positions"] = x_positions

    # 2. Detection of provinces that are too small
    small_ids = detect_small_provinces(province_map, min_pixels=min_pixels)
    results["too_small"] = len(small_ids)
    results["too_small_ids"] = small_ids

    # 3. Continuity detection
    non_contiguous = detect_non_contiguous(province_map)
    results["not_contiguous"] = len(non_contiguous)
    results["not_contiguous_ids"] = non_contiguous

    # 4. Coastal consistency testing
    coastal_issues = detect_coastal_mismatch(tile_map, province_map)
    results["coastal_mismatch"] = len(coastal_issues)
    results["coastal_mismatch_ids"] = coastal_issues

    # 5. TOO LARGE BOX detection (the width/height of a single province exceeds 1/8 of the map)
    too_large_ids = detect_too_large_provinces(province_map)
    results["too_large"] = len(too_large_ids)
    results["too_large_ids"] = too_large_ids

    # 6. ID gap detection (should be continuous 1..N, otherwise csv string bits)
    results["id_gaps"] = detect_id_gaps(province_map)

    # 7. Total warning
    total = int(province_map.max())
    results["total_provinces"] = total
    if total > 21000:
        results["count_warning"] = f"Danger: {total} > 21000, exceeding HOI4's hard limit and guaranteed to crash"
    elif total > 14000:
        results["count_warning"] = f"Warning: {total} > 14000, the limit recommended by HOI4 documentation"
    elif total > 13000:
        results["count_warning"] = f"Note: {total} is close to the recommended vanilla range of 13000–14000"

    return results


def detect_x_crossings(province_map: np.ndarray) -> list[tuple[int, int]]:
    """Detect X-shaped intersection: 4 different province IDs appear in a 2×2 pixel block.
    HOI4 does not allow this and will cause a crash.

    Returns a list of intersection positions [(y, x), ...], with the coordinates being the upper left corner of the 2×2 block."""
    positions = []

    # Take the four corners of the 2×2 window
    tl = province_map[:-1, :-1]  # upper left
    tr_ = province_map[:-1, 1:]  # upper right
    bl = province_map[1:, :-1]   # lower left
    br = province_map[1:, 1:]    # lower right

    # The positions where the four values are different from each other are X-shaped intersections.
    # Use the set size to judge: if the four values ​​are all different, it means there is crossover
    # Optimization: First find the positions with at least 3 different values, and then judge accurately
    diff1 = tl != tr_
    diff2 = tl != bl
    diff3 = tl != br
    diff4 = tr_ != bl
    diff5 = tr_ != br
    diff6 = bl != br

    # 6 pairwise comparisons are all different → 4 values are different from each other
    all_different = diff1 & diff2 & diff3 & diff4 & diff5 & diff6

    ys, xs = np.where(all_different)
    positions = [(int(y), int(x)) for y, x in zip(ys, xs)]

    # === Horizontal wrap edge detection ===
    # The HOI4 documentation is clear: the map loops horizontally, and X-crossing may appear exactly at
    # On the "seam" between the rightmost column and the leftmost column. Regular slices will miss it.
    # Take a virtual 2×2 consisting of the rightmost and leftmost columns:
    #   [last_col[y],    first_col[y]   ]
    #   [last_col[y+1],  first_col[y+1] ]
    last_col = province_map[:, -1]
    first_col = province_map[:, 0]
    tl_w = last_col[:-1]
    tr_w = first_col[:-1]
    bl_w = last_col[1:]
    br_w = first_col[1:]
    diff_w = (
        (tl_w != tr_w) & (tl_w != bl_w) & (tl_w != br_w)
        & (tr_w != bl_w) & (tr_w != br_w) & (bl_w != br_w)
    )
    # Only wrap edges are detected at full image size (subarrays are not wrapped)
    h, w = province_map.shape
    if w == MAP_WIDTH:
        ys_w = np.where(diff_w)[0]
        for y in ys_w:
            positions.append((int(y), w - 1))

    return positions


def fix_x_crossings(province_map: np.ndarray) -> int:
    """Fix X-shaped intersection: Change the bottom right pixel in the 2×2 block to the province ID in the top left corner.

    Returns the number of repairs."""
    _h, w = province_map.shape
    fixed = 0
    positions = detect_x_crossings(province_map)
    for y, x in positions:
        # Special treatment for wrap edges: when x == the rightmost column, the right pixel is [y+1, 0]
        if x == w - 1:
            province_map[y + 1, 0] = province_map[y, x]
        else:
            province_map[y + 1, x + 1] = province_map[y, x]
        fixed += 1
    return fixed


def fix_x_crossings_preserving(
    province_map: np.ndarray,
    protected_mask: np.ndarray,
    tile_map: np.ndarray,
) -> int:
    """Fix X-crossings without changing protected or cross-type pixels.

    Incremental generation uses the pre-existing province pixels as the
    protected region.  A fix is applied only when one of the newly generated
    pixels can copy an ID from another corner with the same land/sea/lake type.
    """
    _h, w = province_map.shape
    fixed = 0
    for y, x in detect_x_crossings(province_map):
        right = 0 if x == w - 1 else x + 1
        coords = [(y, x), (y, right), (y + 1, x), (y + 1, right)]
        changed = False
        for dst_y, dst_x in coords:
            if protected_mask[dst_y, dst_x]:
                continue
            dst_tile = int(tile_map[dst_y, dst_x])
            for src_y, src_x in coords:
                if (src_y, src_x) == (dst_y, dst_x):
                    continue
                if int(tile_map[src_y, src_x]) == dst_tile:
                    province_map[dst_y, dst_x] = province_map[src_y, src_x]
                    fixed += 1
                    changed = True
                    break
            if changed:
                break
    return fixed


def detect_small_provinces(
    province_map: np.ndarray,
    min_pixels: int = MIN_PROVINCE_PIXELS,
) -> list[int]:
    """Detect provinces with fewer than min_pixels pixels.
    Returns a list of province IDs that are too small."""
    if province_map.max() == 0:
        return []

    # Count the number of pixels in each province
    ids, counts = np.unique(province_map, return_counts=True)
    small = []
    for pid, count in zip(ids, counts):
        if pid > 0 and count < min_pixels:
            small.append(int(pid))
    return small


def detect_non_contiguous(province_map: np.ndarray) -> list[int]:
    """Return province IDs whose pixels form multiple 4-connected regions."""
    if province_map.size == 0 or int(province_map.max()) == 0:
        return []

    # Group coordinates by ID once, then label each ID's bounding box. A
    # foreground label over the complete integer map would merge adjacent
    # provinces and cannot detect detached pieces of the same ID.
    _height, width = province_map.shape
    flat = province_map.ravel()
    order = np.argsort(flat, kind="stable")
    sorted_ids = flat[order]
    boundaries = np.flatnonzero(np.diff(sorted_ids) != 0) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(order)]))
    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
    result: list[int] = []

    for start, end in zip(starts.tolist(), ends.tolist()):
        pid = int(sorted_ids[start])
        if pid <= 0:
            continue
        coordinates = order[start:end]
        ys, xs = np.divmod(coordinates, width)
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        if (y1 - y0) * (x1 - x0) == len(coordinates):
            continue
        local_mask = province_map[y0:y1, x0:x1] == pid
        if ndimage.label(local_mask, structure=structure)[1] > 1:
            result.append(pid)
    return result


def detect_coastal_mismatch(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> list[int]:
    """Detect provinces with inconsistent coastal status.
    Rule: If any pixel in a land province is adjacent to a pixel in a sea province,
    then the land province must be marked with coastal=true.

    Returns a list of province IDs that should be marked as coastal but may not currently be marked.
    (Here we only detect which land provinces are coastal, for use when exporting)"""
    coastal_provinces = set()

    # Masks for land and sea provinces
    # Note: Lakes (TILE_LAKE) are not considered coastal - the HOI4 rule is that only land provinces facing the sea are coastal.
    # If the lake is also included, the province will be marked coastal=true in the csv, but the naval_base of buildings.txt
    # It will only be written to the "sea" province (sea_ids does not include lakes). Inconsistency between the two sides will trigger MAP_ERROR or even crash.
    land_mask = tile_map == TILE_LAND
    sea_mask = tile_map == TILE_SEA

    # Check if there is an ocean pixel in the 4 neighbors of each land pixel
    # above
    coastal_up = land_mask[1:, :] & sea_mask[:-1, :]
    # below
    coastal_down = land_mask[:-1, :] & sea_mask[1:, :]
    # left
    coastal_left = land_mask[:, 1:] & sea_mask[:, :-1]
    # right
    coastal_right = land_mask[:, :-1] & sea_mask[:, 1:]

    # HOI4's world map wraps horizontally, so x=0 and x=width-1 are also
    # adjacent.  Treat this seam exactly like the ordinary four-neighbour
    # checks; otherwise definition.csv and buildings.txt disagree at the map
    # edge and the game can crash while loading the map.
    coastal_wrap_left = land_mask[:, 0] & sea_mask[:, -1]
    coastal_wrap_right = land_mask[:, -1] & sea_mask[:, 0]

    # Collect province IDs corresponding to coastal land pixels
    if np.any(coastal_up):
        ys, xs = np.where(coastal_up)
        for pid in np.unique(province_map[ys + 1, xs]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    if np.any(coastal_down):
        ys, xs = np.where(coastal_down)
        for pid in np.unique(province_map[ys, xs]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    if np.any(coastal_left):
        ys, xs = np.where(coastal_left)
        for pid in np.unique(province_map[ys, xs + 1]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    if np.any(coastal_right):
        ys, xs = np.where(coastal_right)
        for pid in np.unique(province_map[ys, xs]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    if np.any(coastal_wrap_left):
        for pid in np.unique(province_map[np.where(coastal_wrap_left)[0], 0]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    if np.any(coastal_wrap_right):
        for pid in np.unique(province_map[np.where(coastal_wrap_right)[0], -1]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    return sorted(coastal_provinces)


def build_coastal_land_to_sea(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> dict[int, int]:
    """Returns {coastal_land_pid: adjacent_sea_pid} mapping (**pixel-level** adjacency).

    Guaranteed to be **exactly consistent** with the results of get_coastal_provinces — anything marked as coastal
    All land provinces can find paired ocean provinces here. Buildings.txt is written using this result
    naval_base_spawn, avoid the crash of "CSV marked coastal but buildings without port"."""
    land_mask = tile_map == TILE_LAND
    sea_mask = tile_map == TILE_SEA
    out: dict[int, int] = {}

    # 4-directional scan: each pixel pair (land, sea) checks whether land is really on side a and sea is on side b
    # Above: (y, x) is land, (y-1, x) is sea → land pid from (y, x), sea pid from (y-1, x)
    m_up = land_mask[1:, :] & sea_mask[:-1, :]
    if np.any(m_up):
        ys, xs = np.where(m_up)
        lp = province_map[ys + 1, xs]
        sp = province_map[ys, xs]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    m_down = land_mask[:-1, :] & sea_mask[1:, :]
    if np.any(m_down):
        ys, xs = np.where(m_down)
        lp = province_map[ys, xs]
        sp = province_map[ys + 1, xs]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    m_left = land_mask[:, 1:] & sea_mask[:, :-1]
    if np.any(m_left):
        ys, xs = np.where(m_left)
        lp = province_map[ys, xs + 1]
        sp = province_map[ys, xs]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    m_right = land_mask[:, :-1] & sea_mask[:, 1:]
    if np.any(m_right):
        ys, xs = np.where(m_right)
        lp = province_map[ys, xs]
        sp = province_map[ys, xs + 1]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    # The world wraps horizontally: land at either bitmap edge is adjacent to
    # sea at the opposite edge.  Keep this mapping in lock-step with
    # detect_coastal_mismatch so every coastal province receives a port spawn.
    m_wrap_left = land_mask[:, 0] & sea_mask[:, -1]
    if np.any(m_wrap_left):
        ys = np.where(m_wrap_left)[0]
        lp = province_map[ys, 0]
        sp = province_map[ys, -1]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    m_wrap_right = land_mask[:, -1] & sea_mask[:, 0]
    if np.any(m_wrap_right):
        ys = np.where(m_wrap_right)[0]
        lp = province_map[ys, -1]
        sp = province_map[ys, 0]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    return out


def detect_too_large_provinces(
    province_map: np.ndarray,
    *,
    include_engine_boundary: bool = False,
) -> list[int]:
    """Check whether the bounding box of a single province exceeds 1/8 of the map width/height.
    Original HOI4 document:
        "Province X has TOO LARGE BOX. Perhaps pixels are spread around the world"
        Trigger condition: width/height > 1/8 of total map width/height

    The engine also rejects the exact one-eighth boundary for some maps
    sizes, so real-map validation keeps one pixel of headroom. Callers that
    need the same rule for small synthetic fixtures can set
    ``include_engine_boundary=True``.

    Note: Provinces that are wrapped horizontally (across the east and west borders of the map) will have false "super width".
    This function does not handle wrap, because the HOI4 engine itself judges based on bbox.
    A province that spans a wrap is indeed "extra-wide" in HOI4's view and needs to be split."""
    # Validate against the actual map dimensions.  The editor supports
    # several map presets, so the fixed vanilla constants are not sufficient
    # for resized projects.
    height, width = province_map.shape
    boundary_is_invalid = include_engine_boundary or (
        width >= 256 and height >= 256
    )
    if province_map.max() == 0:
        return []

    # Vectorize to find the bbox of each ID
    flat = province_map.ravel()
    ys, xs = np.indices(province_map.shape)
    flat_y = ys.ravel()
    flat_x = xs.ravel()

    n = int(province_map.max()) + 1
    # It is too troublesome to use bincount techniques to find min/max; here use np.maximum.at / minimum.at
    min_y = np.full(n, height, dtype=np.int32)
    max_y = np.full(n, -1, dtype=np.int32)
    min_x = np.full(n, width, dtype=np.int32)
    max_x = np.full(n, -1, dtype=np.int32)
    np.minimum.at(min_y, flat, flat_y)
    np.maximum.at(max_y, flat, flat_y)
    np.minimum.at(min_x, flat, flat_x)
    np.maximum.at(max_x, flat, flat_x)

    too_large = []
    for pid in range(1, n):
        if max_y[pid] < 0:
            continue
        h = max_y[pid] - min_y[pid] + 1
        w = max_x[pid] - min_x[pid] + 1
        # The engine treats the 1/8 boundary as invalid on real HOI4 maps
        # (a 2048-pixel-high map therefore needs a province box below 256
        # pixels high).  Keep the validator's historical strict-``>``
        # behaviour for tiny synthetic editor fixtures, which are not valid
        # game map dimensions and are used by the repair unit tests.  Export
        # safety checks can opt in explicitly via ``include_engine_boundary``.
        if (
            w * 8 > width
            or h * 8 > height
            or (
                boundary_is_invalid
                and (w * 8 == width or h * 8 == height)
            )
        ):
            too_large.append(pid)
    return too_large


def detect_id_gaps(province_map: np.ndarray) -> list[int]:
    """Detect ID gap: There should be no missing IDs between 1..max.
    Original HOI4 document:
        "if province 23 doesn't exist, province 24 will take on
         the terrain, type, coastal status, and continent of province 25"
    Returns a list of missing IDs."""
    if province_map.max() == 0:
        return []
    present = set(int(x) for x in np.unique(province_map))
    present.discard(0)
    max_id = int(province_map.max())
    expected = set(range(1, max_id + 1))
    missing = sorted(expected - present)
    return missing


def get_coastal_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> set[int]:
    """Get the ID set of all coastal land provinces.
    Used to set the coastal field when exporting definition.csv."""
    return set(detect_coastal_mismatch(tile_map, province_map))


# ---------------------------------------------------------------------------
# Automatic repair for reference-image imports

_REPAIR_REASON_KEYS = (
    "border_adjusted",
    "too_small_merged",
    "too_small_removed",
    "not_contiguous",
    "too_large_split",
)


def _record_repair(
    reason_ids: dict[str, set[int]],
    reason: str,
    province_ids: object,
) -> None:
    bucket = reason_ids.setdefault(reason, set())
    try:
        values = province_ids if isinstance(province_ids, (list, tuple, set)) else [province_ids]
        for value in values:
            pid = int(value)
            if pid > 0:
                bucket.add(pid)
    except (TypeError, ValueError):
        return


def _province_type(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    pid: int,
    cache: dict[int, int],
) -> int:
    if pid in cache:
        return cache[pid]
    values = tile_map[province_map == pid]
    if values.size == 0:
        cache[pid] = 0
        return 0
    tile_ids, counts = np.unique(values, return_counts=True)
    result = int(tile_ids[int(np.argmax(counts))])
    cache[pid] = result
    return result


def _province_area_cache(province_map: np.ndarray) -> dict[int, int]:
    values, counts = np.unique(province_map, return_counts=True)
    return {
        int(pid): int(count)
        for pid, count in zip(values.tolist(), counts.tolist())
        if int(pid) > 0
    }


def _province_type_lookup(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> dict[int, int]:
    """Return the dominant tile type for every assigned province."""
    max_pid = int(province_map.max())
    if max_pid <= 0:
        return {}
    province_pixels = province_map.ravel()
    tile_pixels = tile_map.ravel()
    valid = province_pixels > 0
    if not np.any(valid):
        return {}
    tile_count = max(4, int(tile_pixels.max()) + 1)
    pairs = province_pixels[valid].astype(np.int64) * tile_count + tile_pixels[valid]
    unique_pairs, pixel_counts = np.unique(pairs, return_counts=True)
    table = np.zeros((max_pid + 1, tile_count), dtype=np.int64)
    table[unique_pairs // tile_count, unique_pairs % tile_count] = pixel_counts
    dominant_types = np.argmax(table, axis=1)
    return {pid: int(tile_type) for pid, tile_type in enumerate(dominant_types) if pid > 0}


def _province_coordinate_groups(province_map: np.ndarray) -> dict[int, np.ndarray]:
    """Group flat pixel coordinates by province ID with one sort."""
    flat = province_map.ravel()
    order = np.argsort(flat, kind="stable")
    sorted_ids = flat[order]
    boundaries = np.flatnonzero(np.diff(sorted_ids) != 0) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(order)]))
    return {
        int(sorted_ids[start]): order[start:end]
        for start, end in zip(starts.tolist(), ends.tolist())
        if int(sorted_ids[start]) > 0
    }


def _neighbor_counts_for_coordinates(
    province_map: np.ndarray,
    ys: np.ndarray,
    xs: np.ndarray,
    source_pid: int,
) -> dict[int, int]:
    """Count contacts for an explicit coordinate list."""
    height, width = province_map.shape
    if len(ys) == 0:
        return {}
    contacts: dict[int, int] = {}
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ny = ys + dy
        valid = (ny >= 0) & (ny < height)
        if not np.any(valid):
            continue
        nx = (xs + dx) % width
        adjacent = province_map[ny[valid], nx[valid]]
        ids, counts = np.unique(adjacent, return_counts=True)
        for value, count in zip(ids.tolist(), counts.tolist()):
            pid = int(value)
            if pid > 0 and pid != source_pid:
                contacts[pid] = contacts.get(pid, 0) + int(count)
    return contacts


def _neighbor_counts_for_mask(
    province_map: np.ndarray,
    mask: np.ndarray,
    source_pid: int,
) -> dict[int, int]:
    """Count 4-connected province contacts, including horizontal map wrapping."""
    ys, xs = np.where(mask)
    return _neighbor_counts_for_coordinates(province_map, ys, xs, source_pid)


def _choose_same_type_neighbor(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    mask: np.ndarray,
    source_pid: int,
    type_cache: dict[int, int],
    area_cache: dict[int, int],
) -> int:
    source_type = _province_type(tile_map, province_map, source_pid, type_cache)
    contacts = _neighbor_counts_for_mask(province_map, mask, source_pid)
    candidates = [
        pid for pid in contacts
        if _province_type(tile_map, province_map, pid, type_cache) == source_type
    ]
    if not candidates:
        return 0
    return max(
        candidates,
        key=lambda pid: (contacts[pid], area_cache.get(pid, 0), -pid),
    )


def _choose_same_type_neighbor_for_coordinates(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    ys: np.ndarray,
    xs: np.ndarray,
    source_pid: int,
    type_cache: dict[int, int],
    area_cache: dict[int, int],
) -> int:
    source_type = _province_type(tile_map, province_map, source_pid, type_cache)
    contacts = _neighbor_counts_for_coordinates(province_map, ys, xs, source_pid)
    candidates = [
        pid for pid in contacts
        if _province_type(tile_map, province_map, pid, type_cache) == source_type
    ]
    if not candidates:
        return 0
    return max(
        candidates,
        key=lambda pid: (contacts[pid], area_cache.get(pid, 0), -pid),
    )


def _repair_x_crossings(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    reason_ids: dict[str, set[int]],
    max_passes: int = 8,
) -> int:
    """Adjust one corner of each X-crossing without crossing tile types."""
    fixed = 0
    height, width = province_map.shape
    for _ in range(max(1, int(max_passes))):
        positions = detect_x_crossings(province_map)
        if not positions:
            break
        changed = False
        for y, x in positions:
            right = 0 if x == width - 1 else x + 1
            coordinates = ((y, x), (y, right), (y + 1, x), (y + 1, right))
            values = [int(province_map[py, px]) for py, px in coordinates]
            if len(set(values)) != 4:
                continue
            # Prefer a replacement with the same tile type as the destination;
            # malformed mixed-type crossings are left for the final report.
            for dst_index, (dy, dx) in enumerate(coordinates):
                destination_type = int(tile_map[dy, dx])
                for src_index, (sy, sx) in enumerate(coordinates):
                    if src_index == dst_index:
                        continue
                    if int(tile_map[sy, sx]) != destination_type:
                        continue
                    old_pid = int(province_map[dy, dx])
                    new_pid = int(province_map[sy, sx])
                    if old_pid == new_pid:
                        continue
                    province_map[dy, dx] = new_pid
                    _record_repair(reason_ids, "border_adjusted", (old_pid, new_pid))
                    fixed += 1
                    changed = True
                    break
                if changed:
                    break
        if not changed:
            break
    return fixed


def _geodesic_two_way_partition(
    mask: np.ndarray,
    seed_a: tuple[int, int],
    seed_b: tuple[int, int],
) -> np.ndarray:
    """Partition a connected mask into two connected regions."""
    labels = np.zeros(mask.shape, dtype=np.int8)
    queue: deque[tuple[int, int]] = deque()
    for label_id, seed in ((1, seed_a), (2, seed_b)):
        if not mask[seed]:
            return labels
        labels[seed] = label_id
        queue.append(seed)
    height, width = mask.shape
    while queue:
        y, x = queue.popleft()
        label_id = labels[y, x]
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if (
                0 <= ny < height
                and 0 <= nx < width
                and mask[ny, nx]
                and labels[ny, nx] == 0
            ):
                labels[ny, nx] = label_id
                queue.append((ny, nx))
    return labels


def _partition_large_mask(mask: np.ndarray, min_pixels: int) -> np.ndarray | None:
    """Find a deterministic two-way split whose pieces stay connected."""
    coordinates = np.argwhere(mask)
    if len(coordinates) < max(2, int(min_pixels) * 2):
        return None
    height, width = mask.shape
    axis = 1 if width >= height else 0
    first = coordinates[int(np.argmin(coordinates[:, axis]))]
    second = coordinates[int(np.argmax(coordinates[:, axis]))]
    if np.array_equal(first, second):
        distances = np.sum((coordinates - first) ** 2, axis=1)
        second = coordinates[int(np.argmax(distances))]
    if np.array_equal(first, second):
        return None

    # Euclidean Voronoi is fast for large maps and normally keeps both pieces
    # connected.  The geodesic fallback guarantees connectivity for narrow or
    # irregular reference outlines.
    seed_a = np.ones(mask.shape, dtype=bool)
    seed_b = np.ones(mask.shape, dtype=bool)
    seed_a[tuple(first)] = False
    seed_b[tuple(second)] = False
    distance_a = ndimage.distance_transform_edt(seed_a)
    distance_b = ndimage.distance_transform_edt(seed_b)
    labels = np.zeros(mask.shape, dtype=np.int8)
    labels[mask] = np.where(distance_a[mask] <= distance_b[mask], 1, 2)
    labels[tuple(first)] = 1
    labels[tuple(second)] = 2

    def connected(label_id: int) -> bool:
        return ndimage.label(labels == label_id, structure=_CROSS)[1] == 1

    if not connected(1) or not connected(2):
        labels = _geodesic_two_way_partition(mask, tuple(first), tuple(second))
    sizes = np.bincount(labels[mask].astype(np.intp), minlength=3)
    if sizes[1] < max(1, int(min_pixels)) or sizes[2] < max(1, int(min_pixels)):
        return None
    if not connected(1) or not connected(2):
        return None
    return labels


def _repair_disconnected_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    reason_ids: dict[str, set[int]],
) -> int:
    """Reassign detached components to touching same-type provinces."""
    repaired = 0
    next_id = int(province_map.max()) + 1
    type_cache = _province_type_lookup(tile_map, province_map)
    for source_pid in detect_non_contiguous(province_map):
        source_mask = province_map == source_pid
        labels, component_count = ndimage.label(source_mask, structure=_CROSS)
        if component_count <= 1:
            continue
        sizes = np.bincount(labels.ravel(), minlength=component_count + 1)
        keep_label = int(np.argmax(sizes[1:]) + 1)
        for component_id in range(1, component_count + 1):
            if component_id == keep_label or sizes[component_id] == 0:
                continue
            component = labels == component_id
            area_cache = _province_area_cache(province_map)
            target = _choose_same_type_neighbor(
                tile_map, province_map, component, source_pid, type_cache, area_cache
            )
            old_pid = source_pid
            if target:
                province_map[component] = target
                _record_repair(reason_ids, "not_contiguous", (old_pid, target))
            else:
                province_map[component] = next_id
                _record_repair(reason_ids, "not_contiguous", (old_pid, next_id))
                next_id += 1
            repaired += 1
    return repaired


def _grow_small_province(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    pid: int,
    min_pixels: int,
) -> int:
    """Use adjacent unassigned same-type pixels for an isolated small region."""
    current = int(np.sum(province_map == pid))
    if current >= min_pixels:
        return 0
    tile_type = _province_type(tile_map, province_map, pid, {})
    height, width = province_map.shape
    ys, xs = np.where(province_map == pid)
    queue: deque[tuple[int, int]] = deque(zip(ys.tolist(), xs.tolist()))
    seen = {(int(y), int(x)) for y, x in zip(ys.tolist(), xs.tolist())}
    grown = 0
    while queue and current < min_pixels:
        y, x = queue.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, (x - 1) % width), (y, (x + 1) % width)):
            if not (0 <= ny < height):
                continue
            if (ny, nx) in seen:
                continue
            seen.add((ny, nx))
            if province_map[ny, nx] == 0 and int(tile_map[ny, nx]) == tile_type:
                province_map[ny, nx] = pid
                current += 1
                grown += 1
                queue.append((ny, nx))
            elif province_map[ny, nx] == pid:
                queue.append((ny, nx))
    return grown


def _merge_small_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    reason_ids: dict[str, set[int]],
    min_pixels: int,
    max_passes: int = 32,
) -> int:
    """Merge small provinces into the strongest same-type neighboring region."""
    merged = 0
    type_cache = _province_type_lookup(tile_map, province_map)
    for _ in range(max(1, int(max_passes))):
        area_cache = _province_area_cache(province_map)
        coordinate_groups = _province_coordinate_groups(province_map)
        flat_map = province_map.ravel()
        small_ids = [
            pid for pid, area in sorted(area_cache.items(), key=lambda pair: (pair[1], pair[0]))
            if area < max(1, int(min_pixels))
        ]
        if not small_ids:
            break
        changed = False
        for source_pid in small_ids:
            if area_cache.get(source_pid, 0) >= min_pixels:
                continue
            coordinates = coordinate_groups.get(source_pid)
            if coordinates is None or len(coordinates) == 0:
                continue
            coordinates = coordinates[flat_map[coordinates] == source_pid]
            if len(coordinates) == 0:
                continue
            ys, xs = np.divmod(coordinates, province_map.shape[1])
            target = _choose_same_type_neighbor_for_coordinates(
                tile_map, province_map, ys, xs, source_pid, type_cache, area_cache
            )
            if target:
                flat_map[coordinates] = target
                coordinate_groups[target] = np.concatenate(
                    (coordinate_groups.get(target, np.empty(0, dtype=np.intp)), coordinates)
                )
                coordinate_groups.pop(source_pid, None)
                moved = len(coordinates)
                area_cache[source_pid] = 0
                area_cache[target] = area_cache.get(target, 0) + moved
                _record_repair(reason_ids, "too_small_merged", (source_pid, target))
                merged += 1
                changed = True
                continue
            grown = _grow_small_province(tile_map, province_map, source_pid, min_pixels)
            if grown:
                _record_repair(reason_ids, "border_adjusted", source_pid)
                changed = True
        if not changed:
            break
    return merged


def _remove_unrepairable_small_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    reason_ids: dict[str, set[int]],
    min_pixels: int,
) -> int:
    """Clear isolated tiny remnants when no same-type province can receive them."""
    removed = 0
    areas = _province_area_cache(province_map)
    type_cache = _province_type_lookup(tile_map, province_map)
    for pid, area in sorted(areas.items(), key=lambda pair: (pair[1], pair[0])):
        if area >= min_pixels:
            continue
        mask = province_map == pid
        if not mask.any():
            continue
        ys, xs = np.where(mask)
        target = _choose_same_type_neighbor_for_coordinates(
            tile_map,
            province_map,
            ys,
            xs,
            pid,
            type_cache,
            areas,
        )
        if target:
            continue
        # Same-type merges were attempted first. If none exists, the safe
        # repair is to leave those pixels unassigned instead of creating a
        # province that crosses land, sea, or lake tile types.
        province_map[mask] = 0
        _record_repair(reason_ids, "too_small_removed", pid)
        removed += 1
    return removed


def _repair_large_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    reason_ids: dict[str, set[int]],
    min_pixels: int,
) -> int:
    """Split oversized provinces along their longest axis."""
    del tile_map  # Kept in the signature for symmetry and future type checks.
    repaired = 0
    next_id = int(province_map.max()) + 1
    for source_pid in detect_too_large_provinces(province_map):
        mask = province_map == source_pid
        ys, xs = np.where(mask)
        if len(ys) == 0:
            continue
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        local_mask = mask[y0:y1, x0:x1]
        if ndimage.label(local_mask, structure=_CROSS)[1] != 1:
            continue
        labels = _partition_large_mask(local_mask, min_pixels)
        if labels is None:
            continue
        local = province_map[y0:y1, x0:x1]
        local[labels == 2] = next_id
        _record_repair(reason_ids, "too_large_split", (source_pid, next_id))
        next_id += 1
        repaired += 1
    return repaired


def _compact_repaired_ids(province_map: np.ndarray) -> int:
    present = sorted(int(pid) for pid in np.unique(province_map) if int(pid) > 0)
    if not present:
        return 0
    gaps = len(set(range(1, present[-1] + 1)) - set(present))
    if gaps == 0 and present == list(range(1, present[-1] + 1)):
        return 0
    lookup = np.zeros(present[-1] + 1, dtype=np.int32)
    for new_id, old_id in enumerate(present, 1):
        lookup[old_id] = new_id
    province_map[:] = lookup[province_map]
    return gaps


def _province_type_counts(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> dict[str, int]:
    names = {TILE_LAND: "land", TILE_SEA: "sea", TILE_LAKE: "lake"}
    counts = {"land": 0, "sea": 0, "lake": 0, "unknown": 0}
    for tile_type in _province_type_lookup(tile_map, province_map).values():
        counts[names.get(int(tile_type), "unknown")] += 1
    return counts


def _province_issue_count(results: dict) -> int:
    return int(
        results.get("x_crossings", 0)
        + results.get("too_small", 0)
        + results.get("not_contiguous", 0)
        + results.get("too_large", 0)
        + len(results.get("id_gaps", []))
    )


def validate_and_repair_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    *,
    min_pixels: int = MIN_PROVINCE_PIXELS,
    max_iterations: int = 8,
) -> tuple[np.ndarray, dict]:
    """Validate and repair a generated province map without mutating input.

    Border crossings and disconnected components are repaired by changing the
    smallest possible set of pixels.  Provinces below ``min_pixels`` are
    merged into a touching province of the same tile type, while oversized
    provinces are split along their longest axis.  The returned report keeps
    the original type counts, per-reason repair counts, and before/after
    validator results so the UI can explain exactly what changed.
    """
    tile = np.asarray(tile_map)
    original = np.asarray(province_map)
    if tile.ndim != 2 or original.ndim != 2 or tile.shape != original.shape:
        raise ValueError("tile_map and province_map must be matching 2-D arrays")
    result = original.astype(np.int32, copy=True)
    threshold = max(1, int(min_pixels))
    before = validate_provinces(tile, result, min_pixels=threshold)
    imported_counts = _province_type_counts(tile, result)
    reason_ids = {reason: set() for reason in _REPAIR_REASON_KEYS}

    for _ in range(max(1, int(max_iterations))):
        changed = False
        if _repair_x_crossings(tile, result, reason_ids):
            changed = True
        if _repair_disconnected_provinces(tile, result, reason_ids):
            changed = True
        if _repair_large_provinces(tile, result, reason_ids, threshold):
            changed = True
        if _merge_small_provinces(tile, result, reason_ids, threshold):
            changed = True
        if _remove_unrepairable_small_provinces(tile, result, reason_ids, threshold):
            changed = True
        if _repair_x_crossings(tile, result, reason_ids):
            changed = True
        if not changed:
            break

    compacted_gaps = _compact_repaired_ids(result)
    after = validate_provinces(tile, result, min_pixels=threshold)
    modified_ids: set[int] = set()
    for values in reason_ids.values():
        modified_ids.update(values)
    reason_counts = {reason: len(values) for reason, values in reason_ids.items()}
    reason_counts["id_gaps"] = int(compacted_gaps)
    unresolved_by_reason = {
        "border_adjusted": int(after.get("x_crossings", 0)),
        "too_small_merged": int(after.get("too_small", 0)),
        "not_contiguous": int(after.get("not_contiguous", 0)),
        "too_large_split": int(after.get("too_large", 0)),
        "id_gaps": len(after.get("id_gaps", [])),
    }
    report = {
        "imported_counts": imported_counts,
        "imported_total": int(sum(imported_counts.values()) - imported_counts.get("unknown", 0)),
        "final_counts": _province_type_counts(tile, result),
        "modified_count": len(modified_ids),
        "modified_province_ids": sorted(modified_ids),
        "repair_counts": reason_counts,
        "validation_before": before,
        "validation_after": after,
        "initial_issue_count": _province_issue_count(before),
        "remaining_issue_count": _province_issue_count(after),
        "remaining_by_reason": unresolved_by_reason,
    }
    return result, report
