"""
省份验证器 — 检测 HOI4 省份地图中的各种问题
"""
import numpy as np
from collections import deque
from scipy import ndimage

from ui.i18n import tr_pair

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
    """
    验证省份地图，检测所有可能导致 HOI4 崩溃的问题。

    返回:
        {
            "x_crossings": int,          # X型交叉数量
            "x_crossing_positions": list, # 交叉位置列表 [(y, x), ...]
            "too_small": int,             # 过小省份数量
            "too_small_ids": list,        # 过小省份ID列表
            "not_contiguous": int,        # 不连续省份数量
            "not_contiguous_ids": list,   # 不连续省份ID列表
            "coastal_mismatch": int,      # 沿海状态不一致数量
            "coastal_mismatch_ids": list, # 不一致的省份ID列表
        }
    """
    results = {
        "x_crossings": 0,
        "x_crossing_positions": [],
        "too_small": 0,
        "too_small_ids": [],
        "not_contiguous": 0,
        "not_contiguous_ids": [],
        "coastal_mismatch": 0,
        "coastal_mismatch_ids": [],
        # 新增：HOI4 文档明确的硬规则
        "too_large": 0,           # 单省宽/高 > 地图 1/8 (TOO LARGE BOX 错误)
        "too_large_ids": [],
        "id_gaps": [],            # ID 不连续的位置（应在 1..N 之间无空洞）
        "total_provinces": 0,
        "count_warning": "",      # 总数预警字符串
    }

    if province_map.max() == 0:
        return results

    # 1. X型交叉检测
    x_positions = detect_x_crossings(province_map)
    results["x_crossings"] = len(x_positions)
    results["x_crossing_positions"] = x_positions

    # 2. 过小省份检测
    small_ids = detect_small_provinces(province_map, min_pixels=min_pixels)
    results["too_small"] = len(small_ids)
    results["too_small_ids"] = small_ids

    # 3. 连续性检测
    non_contiguous = detect_non_contiguous(province_map)
    results["not_contiguous"] = len(non_contiguous)
    results["not_contiguous_ids"] = non_contiguous

    # 4. 沿海一致性检测
    coastal_issues = detect_coastal_mismatch(tile_map, province_map)
    results["coastal_mismatch"] = len(coastal_issues)
    results["coastal_mismatch_ids"] = coastal_issues

    # 5. TOO LARGE BOX 检测（单省宽/高超过地图 1/8）
    too_large_ids = detect_too_large_provinces(province_map)
    results["too_large"] = len(too_large_ids)
    results["too_large_ids"] = too_large_ids

    # 6. ID gap 检测（应连续 1..N，否则 csv 串位）
    results["id_gaps"] = detect_id_gaps(province_map)

    # 7. 总数预警
    total = int(province_map.max())
    results["total_provinces"] = total
    if total > 21000:
        results["count_warning"] = tr_pair(f"危险：{total} > 21000，超过 HOI4 边界硬上限，必崩", f"Danger: {total} > 21000, exceeding HOI4's hard limit and guaranteed to crash")
    elif total > 14000:
        results["count_warning"] = tr_pair(f"警告：{total} > 14000，HOI4 文档建议上限", f"Warning: {total} > 14000, the limit recommended by HOI4 documentation")
    elif total > 13000:
        results["count_warning"] = tr_pair(f"提示：{total} 接近 vanilla 13000-14000 推荐区间", f"Note: {total} is close to the recommended vanilla range of 13000–14000")

    return results


def detect_x_crossings(province_map: np.ndarray) -> list[tuple[int, int]]:
    """
    检测 X 型交叉：2×2 像素块中出现4种不同省份ID。
    HOI4 不允许这种情况，会导致崩溃。

    返回交叉位置列表 [(y, x), ...]，坐标是2×2块的左上角。
    """
    positions = []

    # 取2×2窗口的四个角
    tl = province_map[:-1, :-1]  # 左上
    tr_ = province_map[:-1, 1:]  # 右上
    bl = province_map[1:, :-1]   # 左下
    br = province_map[1:, 1:]    # 右下

    # 四个值互不相同的位置就是 X 型交叉
    # 用集合大小判断：如果4个值全不同，说明有交叉
    # 优化：先找出至少有3种不同值的位置，再精确判断
    diff1 = tl != tr_
    diff2 = tl != bl
    diff3 = tl != br
    diff4 = tr_ != bl
    diff5 = tr_ != br
    diff6 = bl != br

    # 6个两两比较都不同 → 4个值互不相同
    all_different = diff1 & diff2 & diff3 & diff4 & diff5 & diff6

    ys, xs = np.where(all_different)
    positions = [(int(y), int(x)) for y, x in zip(ys, xs)]

    # === 横向 wrap 边缘检测 ===
    # HOI4 文档明确：地图横向循环，X-crossing 可能正好出现在
    # 最右列与最左列之间的"接缝"上。普通切片会漏掉。
    # 取最右列和最左列组成的虚拟 2×2：
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
    # 只在全图尺寸时检测 wrap 边缘（子数组不做 wrap）
    h, w = province_map.shape
    if w == MAP_WIDTH:
        ys_w = np.where(diff_w)[0]
        for y in ys_w:
            positions.append((int(y), w - 1))

    return positions


def fix_x_crossings(province_map: np.ndarray) -> int:
    """
    修复 X 型交叉：将2×2块中右下角的像素改为左上角的省份ID。

    返回修复数量。
    """
    _h, w = province_map.shape
    fixed = 0
    positions = detect_x_crossings(province_map)
    for y, x in positions:
        # wrap 边缘特殊处理：x == 最右列时右边像素是 [y+1, 0]
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
    """
    检测像素数少于 min_pixels 的省份。
    返回过小省份ID列表。
    """
    if province_map.max() == 0:
        return []

    # 统计每个省份的像素数
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
    """
    检测沿海状态不一致的省份。
    规则：如果一个 land 省份的任何像素与一个 sea 省份的像素相邻，
    则该 land 省份必须标记为 coastal=true。

    返回应该标记为 coastal 但当前可能未标记的省份ID列表。
    （这里只检测哪些陆地省份是沿海的，供导出时使用）
    """
    coastal_provinces = set()

    # 陆地和海洋省份的 mask
    # 注意：湖泊(TILE_LAKE)不算沿海依据 —— HOI4 规则是只有临海(sea)的陆地省才是 coastal。
    # 若把湖也算进去，csv 里该省会被标 coastal=true，但 buildings.txt 的 naval_base
    # 只会对临"海"省写入（sea_ids 不含湖），两边不一致会触发 MAP_ERROR 甚至崩溃。
    land_mask = tile_map == TILE_LAND
    sea_mask = tile_map == TILE_SEA

    # 检查每个陆地像素的4邻域是否有海洋像素
    # 上方
    coastal_up = land_mask[1:, :] & sea_mask[:-1, :]
    # 下方
    coastal_down = land_mask[:-1, :] & sea_mask[1:, :]
    # 左方
    coastal_left = land_mask[:, 1:] & sea_mask[:, :-1]
    # 右方
    coastal_right = land_mask[:, :-1] & sea_mask[:, 1:]

    # HOI4's world map wraps horizontally, so x=0 and x=width-1 are also
    # adjacent.  Treat this seam exactly like the ordinary four-neighbour
    # checks; otherwise definition.csv and buildings.txt disagree at the map
    # edge and the game can crash while loading the map.
    coastal_wrap_left = land_mask[:, 0] & sea_mask[:, -1]
    coastal_wrap_right = land_mask[:, -1] & sea_mask[:, 0]

    # 收集沿海陆地像素对应的省份ID
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
    """返回 {coastal_land_pid: adjacent_sea_pid} 映射（**像素级**邻接）。

    保证和 get_coastal_provinces 的结果**完全一致** — 任何被标记为 coastal 的
    陆地省都能在这里找到配对的海洋省。buildings.txt 就用这个结果写
    naval_base_spawn，避免"CSV 标 coastal 但 buildings 没 port"的崩溃。
    """
    land_mask = tile_map == TILE_LAND
    sea_mask = tile_map == TILE_SEA
    out: dict[int, int] = {}

    # 4 方向扫描：每个像素对 (land, sea) 检查是否真的是 land 在 a 侧、sea 在 b 侧
    # 上: (y, x) is land, (y-1, x) is sea  → land pid from (y, x), sea pid from (y-1, x)
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


def detect_too_large_provinces(province_map: np.ndarray) -> list[int]:
    """
    检测单个省份的 bounding box 是否超过地图宽/高的 1/8。
    HOI4 文档原文：
        "Province X has TOO LARGE BOX. Perhaps pixels are spread around the world"
        触发条件：width/height > 1/8 of total map width/height

    注意：横向 wrap 的省份（横跨地图东西边界）会有虚假的"超宽"，
    本函数不处理 wrap，因为 HOI4 引擎本身就是按 bbox 判断的，
    一个跨 wrap 的省份在 HOI4 看来确实是"超宽"的，需要拆分。
    """
    # Validate against the actual map dimensions.  The editor supports
    # several map presets, so the fixed vanilla constants are not sufficient
    # for resized projects.
    height, width = province_map.shape
    max_w = max(1, width // 8)
    max_h = max(1, height // 8)

    if province_map.max() == 0:
        return []

    # 向量化求每个 ID 的 bbox
    flat = province_map.ravel()
    ys, xs = np.indices(province_map.shape)
    flat_y = ys.ravel()
    flat_x = xs.ravel()

    n = int(province_map.max()) + 1
    # 用 bincount 类技巧求 min/max 太麻烦；这里用 np.maximum.at / minimum.at
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
        if w > max_w or h > max_h:
            too_large.append(pid)
    return too_large


def detect_id_gaps(province_map: np.ndarray) -> list[int]:
    """
    检测 ID gap：1..max 之间应该没有缺失的 ID。
    HOI4 文档原文：
        "if province 23 doesn't exist, province 24 will take on
         the terrain, type, coastal status, and continent of province 25"
    返回缺失的 ID 列表。
    """
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
    """
    获取所有沿海陆地省份的ID集合。
    用于导出 definition.csv 时设置 coastal 字段。
    """
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
