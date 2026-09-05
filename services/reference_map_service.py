"""Create editable map layers from color-coded reference images.

The routines in this module are deliberately UI-free so they can be tested with
small synthetic images as well as full 5632x2048 QGIS exports.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

from data.constants import TILE_LAKE, TILE_LAND, TILE_SEA
from domain.managers.river import (
    RIVER_BG_LAND,
    RIVER_BG_SEA,
    RIVER_SOURCE,
    RIVER_WIDTH_1,
)


_CROSS = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)


def load_reference_rgb(path: str | Path, target_shape: tuple[int, int]) -> np.ndarray:
    """Load *path* as RGB and resize it to ``(height, width)`` when needed."""
    with Image.open(path) as source:
        image = source.convert("RGB")
        height, width = target_shape
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.BILINEAR)
        return np.asarray(image, dtype=np.uint8)


def _neutral_sea_mask(rgb: np.ndarray) -> np.ndarray:
    """Detect the white/light-neutral sea used by common GIS print layouts."""
    work = rgb.astype(np.int16, copy=False)
    chroma = work.max(axis=2) - work.min(axis=2)
    return (work.min(axis=2) >= 180) & (chroma <= 15)


def generate_land_water_from_rgb(rgb: np.ndarray) -> np.ndarray:
    """Infer a TILE_LAND/TILE_SEA map from a colored land-on-white image."""
    sea = _neutral_sea_mask(rgb)
    result = np.full(sea.shape, TILE_LAND, dtype=np.uint8)
    result[sea] = TILE_SEA
    return result


def _dominant_rgb(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return the exact most frequent RGB color under *mask*."""
    values = rgb[mask].astype(np.int64, copy=False)
    if values.size == 0:
        raise ValueError("The reference image contains no land-colored pixels")
    packed = (values[:, 0] << 16) | (values[:, 1] << 8) | values[:, 2]
    key = int(np.bincount(packed).argmax())
    return np.array([(key >> 16) & 255, (key >> 8) & 255, key & 255], dtype=np.int16)


def generate_provinces_from_rgb(
    rgb: np.ndarray,
    tile_map: np.ndarray | None = None,
    *,
    boundary_threshold: float = 20.0,
    min_region_pixels: int = 9,
) -> tuple[np.ndarray, int]:
    """Turn dark outlines on a mostly uniform land fill into province IDs.

    Boundary pixels are assigned to their nearest enclosed region, so the
    returned map has no cracks. Sea remains ID 0 because a reference without
    sea outlines contains no evidence from which to infer sea provinces.
    Existing lake components are each assigned a separate province.
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Reference image must be an RGB array")

    image_land = ~_neutral_sea_mask(rgb)
    dominant = _dominant_rgb(rgb, image_land)
    delta = rgb.astype(np.int16) - dominant
    distance = np.sqrt(np.sum(delta.astype(np.float32) ** 2, axis=2))
    boundary = image_land & (distance >= float(boundary_threshold))

    if tile_map is None:
        usable_land = image_land
        lakes = np.zeros(image_land.shape, dtype=bool)
    else:
        if tile_map.shape != image_land.shape:
            raise ValueError("tile_map and reference image must have the same size")
        usable_land = image_land & (tile_map == TILE_LAND)
        lakes = image_land & (tile_map == TILE_LAKE)

    interiors, _ = ndimage.label(usable_land & ~boundary, structure=_CROSS)
    sizes = np.bincount(interiors.ravel())
    valid_ids = np.flatnonzero(sizes >= max(1, int(min_region_pixels)))
    valid_ids = valid_ids[valid_ids != 0]
    if valid_ids.size == 0:
        raise ValueError("No enclosed province regions were found in the reference image")

    keep = np.isin(interiors, valid_ids)
    compact_lut = np.zeros(len(sizes), dtype=np.int32)
    compact_lut[valid_ids] = np.arange(1, len(valid_ids) + 1, dtype=np.int32)
    seeds = compact_lut[interiors]

    # Assign outline pixels and discarded specks to the nearest valid interior.
    nearest = ndimage.distance_transform_edt(~keep, return_distances=False, return_indices=True)
    province_map = seeds[nearest[0], nearest[1]].astype(np.int32, copy=False)
    province_map[~usable_land] = 0
    count = int(len(valid_ids))

    if lakes.any():
        lake_labels, lake_count = ndimage.label(lakes, structure=_CROSS)
        if lake_count:
            lake_pixels = lake_labels > 0
            province_map[lake_pixels] = lake_labels[lake_pixels].astype(np.int32) + count
            count += int(lake_count)

    return province_map, count


def _remove_small_components(mask: np.ndarray, min_pixels: int) -> np.ndarray:
    labels, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    if count == 0:
        return np.zeros_like(mask)
    sizes = np.bincount(labels.ravel())
    valid = sizes >= max(1, int(min_pixels))
    valid[0] = False
    return valid[labels]


def _morphological_skeleton(mask: np.ndarray) -> np.ndarray:
    """Return a thin, connected skeleton using OpenCV's cross morphology."""
    work = mask.astype(np.uint8) * 255
    skeleton = np.zeros_like(work)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(work):
        opened = cv2.morphologyEx(work, cv2.MORPH_OPEN, element)
        skeleton = cv2.bitwise_or(skeleton, cv2.subtract(work, opened))
        work = cv2.erode(work, element)
    return skeleton != 0


def _bridge_diagonals(mask: np.ndarray, allowed: np.ndarray) -> np.ndarray:
    """Insert orthogonal bridge pixels for isolated diagonal skeleton steps."""
    result = mask.copy()
    height, width = result.shape

    def block_score(py: int, px: int) -> int:
        """Number of solid 2x2 blocks that adding this pixel would complete."""
        score = 0
        for by in (py - 1, py):
            for bx in (px - 1, px):
                if by < 0 or bx < 0 or by + 1 >= height or bx + 1 >= width:
                    continue
                block = result[by:by + 2, bx:bx + 2].copy()
                block[py - by, px - bx] = True
                score += int(block.all())
        return score

    def choose(candidates: tuple[tuple[int, int], tuple[int, int]]) -> tuple[int, int]:
        return min(candidates, key=lambda p: (block_score(*p), not allowed[p]))

    for _ in range(2):
        changed = False
        ys, xs = np.where(result[:-1, :-1] & result[1:, 1:])
        for y, x in zip(ys.tolist(), xs.tolist()):
            if not result[y + 1, x] and not result[y, x + 1]:
                py, px = choose(((y + 1, x), (y, x + 1)))
                result[py, px] = True
                changed = True
        ys, xs = np.where(result[1:, :-1] & result[:-1, 1:])
        for y, x in zip(ys.tolist(), xs.tolist()):
            if not result[y, x] and not result[y + 1, x + 1]:
                py, px = choose(((y, x), (y + 1, x + 1)))
                result[py, px] = True
                changed = True
        if not changed:
            break
    return result


def _remove_solid_blocks(mask: np.ndarray) -> np.ndarray:
    """Thin any remaining 2x2 blocks without breaking their connectivity."""
    result = mask.copy()
    for _ in range(4):
        blocks = (
            result[:-1, :-1] & result[:-1, 1:]
            & result[1:, :-1] & result[1:, 1:]
        )
        if not blocks.any():
            break
        remove = np.zeros_like(result)
        remove[1:, 1:] = blocks
        result[remove] = False
    return result


def _pure_diagonal_count(mask: np.ndarray) -> int:
    count = 0
    for dx in (1, -1):
        upper = mask[:-1, :-1] if dx == 1 else mask[:-1, 1:]
        lower = mask[1:, 1:] if dx == 1 else mask[1:, :-1]
        side_a = mask[1:, :-1] if dx == 1 else mask[1:, 1:]
        side_b = mask[:-1, 1:] if dx == 1 else mask[:-1, :-1]
        count += int((upper & lower & ~side_a & ~side_b).sum())
    return count


def _remove_solid_blocks_topologically(mask: np.ndarray) -> np.ndarray:
    """Remove block corners while minimizing newly exposed diagonal links."""
    result = mask.copy()
    blocks = np.argwhere(
        result[:-1, :-1] & result[:-1, 1:]
        & result[1:, :-1] & result[1:, 1:]
    )
    for y, x in blocks.tolist():
        if not result[y:y + 2, x:x + 2].all():
            continue
        choices = []
        for py, px in ((y, x), (y, x + 1), (y + 1, x), (y + 1, x + 1)):
            result[py, px] = False
            y0, y1 = max(0, py - 2), min(result.shape[0], py + 3)
            x0, x1 = max(0, px - 2), min(result.shape[1], px + 3)
            diagonals = _pure_diagonal_count(result[y0:y1, x0:x1])
            result[py, px] = True
            orthogonal_degree = (
                int(result[max(0, py - 1):py + 2, px].sum())
                + int(result[py, max(0, px - 1):px + 2].sum()) - 2
            )
            choices.append((diagonals, orthogonal_degree, py, px))
        _, _, py, px = min(choices)
        result[py, px] = False
    return result


def _drop_topologically_invalid_components(mask: np.ndarray) -> np.ndarray:
    """Drop rare ambiguous micro-networks that cannot satisfy HOI4 raster rules."""
    invalid = np.zeros_like(mask)
    blocks = mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:]
    by, bx = np.where(blocks)
    for y, x in zip(by.tolist(), bx.tolist()):
        invalid[y:y + 2, x:x + 2] = True
    for dx in (1, -1):
        upper = mask[:-1, :-1] if dx == 1 else mask[:-1, 1:]
        lower = mask[1:, 1:] if dx == 1 else mask[1:, :-1]
        side_a = mask[1:, :-1] if dx == 1 else mask[1:, 1:]
        side_b = mask[:-1, 1:] if dx == 1 else mask[:-1, :-1]
        ys, xs = np.where(upper & lower & ~side_a & ~side_b)
        for y, x in zip(ys.tolist(), xs.tolist()):
            if dx == 1:
                invalid[y, x] = invalid[y + 1, x + 1] = True
            else:
                invalid[y, x + 1] = invalid[y + 1, x] = True
    if not invalid.any():
        return mask
    labels, _ = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    bad_ids = np.unique(labels[invalid])
    bad_ids = bad_ids[bad_ids != 0]
    result = mask.copy()
    result[np.isin(labels, bad_ids)] = False
    return result


def generate_hydrology_from_rgb(
    rgb: np.ndarray,
    base_tile_map: np.ndarray,
    *,
    min_feature_pixels: int = 4,
    lake_radius: float = 3.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """Extract broad lakes and thin rivers from a colored inland-water image.

    The QGIS fixtures use yellow-green for land and grey/brown/blue for inland
    water. The blue-to-green ratio separates those families without requiring
    callers to know an exact source color.
    """
    if base_tile_map.shape != rgb.shape[:2]:
        raise ValueError("base_tile_map and reference image must have the same size")

    work = rgb.astype(np.float32)
    sea = _neutral_sea_mask(rgb)
    features = (~sea) & (work[:, :, 2] >= 0.45 * work[:, :, 1]) & (work[:, :, 1] >= 45)
    # Anti-aliased coast pixels are neutral too; exclude a small coastal halo.
    coastal_halo = ndimage.binary_dilation(sea, structure=np.ones((3, 3), bool), iterations=2)
    features &= ~coastal_halo
    features &= base_tile_map == TILE_LAND
    features = _remove_small_components(features, min_feature_pixels)

    distance = ndimage.distance_transform_edt(features)
    lake_core = distance >= float(lake_radius)
    lake_mask = ndimage.binary_dilation(lake_core, structure=np.ones((3, 3), bool), iterations=2)
    lake_mask &= features
    river_source_mask = features & ~lake_mask

    # OpenCV handles the sparse world-sized mask much faster in one pass than
    # thousands of tiny component calls.
    river_map_mask = _remove_solid_blocks(_morphological_skeleton(river_source_mask))
    river_map_mask = _bridge_diagonals(river_map_mask, river_source_mask)
    for _ in range(3):
        river_map_mask = _remove_solid_blocks_topologically(river_map_mask)
        river_map_mask = _bridge_diagonals(river_map_mask, river_source_mask)
    river_map_mask = _drop_topologically_invalid_components(river_map_mask)

    new_tiles = base_tile_map.copy()
    # This is a full reference import: replace the previous lake set while
    # preserving the existing coastline.
    new_tiles[new_tiles == TILE_LAKE] = TILE_LAND
    new_tiles[lake_mask] = TILE_LAKE

    river_map = np.full(features.shape, RIVER_BG_LAND, dtype=np.uint8)
    river_map[(new_tiles == TILE_SEA) | (new_tiles == TILE_LAKE)] = RIVER_BG_SEA
    river_map[river_map_mask] = RIVER_WIDTH_1

    # Exactly one source per connected network: choose the endpoint farthest
    # from sea/lake (fall back to any network pixel when it has no endpoint).
    networks, network_count = ndimage.label(
        river_map_mask, structure=np.ones((3, 3), dtype=bool)
    )
    water_distance = ndimage.distance_transform_edt(
        (new_tiles != TILE_SEA) & (new_tiles != TILE_LAKE)
    )
    neighbor_count = ndimage.convolve(river_map_mask.astype(np.uint8), _CROSS.astype(np.uint8)) - river_map_mask
    for network_id, obj in enumerate(ndimage.find_objects(networks), 1):
        if obj is None:
            continue
        local_network = networks[obj] == network_id
        local_candidates = local_network & (neighbor_count[obj] <= 1)
        if not local_candidates.any():
            local_candidates = local_network
        local_y, local_x = np.where(local_candidates)
        global_y = local_y + obj[0].start
        global_x = local_x + obj[1].start
        best = int(np.argmax(water_distance[global_y, global_x]))
        river_map[global_y[best], global_x[best]] = RIVER_SOURCE

    stats = {
        "lake_pixels": int(lake_mask.sum()),
        "river_pixels": int(river_map_mask.sum()),
        "river_networks": int(network_count),
    }
    return new_tiles, river_map, stats


def _allocate_piece_counts(areas: list[int], target_count: int) -> list[int]:
    """Allocate at least one output piece per selected province by area."""
    if target_count < len(areas):
        raise ValueError("Target count cannot be smaller than the selection")
    allocation = [1] * len(areas)
    remaining = target_count - len(areas)
    if remaining == 0:
        return allocation
    total = float(sum(areas))
    quotas = [remaining * area / total for area in areas]
    floors = [int(q) for q in quotas]
    allocation = [base + extra for base, extra in zip(allocation, floors)]
    left = target_count - sum(allocation)
    order = sorted(range(len(areas)), key=lambda i: (quotas[i] - floors[i], areas[i]), reverse=True)
    for index in order[:left]:
        allocation[index] += 1
    return allocation


def _spread_seeds(coords: np.ndarray, count: int, rng: np.random.Generator) -> list[tuple[int, int]]:
    """Choose randomized, well-spread seeds from ``(y, x)`` coordinates."""
    first = int(rng.integers(0, len(coords)))
    seeds = [tuple(map(int, coords[first]))]
    min_distance = np.full(len(coords), np.inf, dtype=np.float64)
    min_distance[first] = -1.0
    for _ in range(1, count):
        sy, sx = seeds[-1]
        distance = (coords[:, 0] - sy) ** 2 + (coords[:, 1] - sx) ** 2
        min_distance = np.minimum(min_distance, distance)
        # Randomize among the farthest 10% to make repeated splits visibly differ.
        cutoff = np.quantile(min_distance, 0.90)
        choices = np.flatnonzero(min_distance >= cutoff)
        chosen = int(rng.choice(choices))
        seeds.append(tuple(map(int, coords[chosen])))
        min_distance[chosen] = -1.0
    return seeds


def _geodesic_partition(mask: np.ndarray, seeds: list[tuple[int, int]]) -> np.ndarray:
    """Multi-source flood fill constrained to *mask*; every piece is connected."""
    labels = np.zeros(mask.shape, dtype=np.int32)
    queue: deque[tuple[int, int]] = deque()
    for label_id, (y, x) in enumerate(seeds, 1):
        labels[y, x] = label_id
        queue.append((y, x))
    height, width = mask.shape
    while queue:
        y, x = queue.popleft()
        label_id = labels[y, x]
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and labels[ny, nx] == 0:
                labels[ny, nx] = label_id
                queue.append((ny, nx))
    return labels


def split_selected_provinces_randomly(
    province_map: np.ndarray,
    selected_ids: set[int] | list[int],
    target_count: int,
    *,
    seed: int | None = None,
    min_piece_pixels: int = 4,
) -> tuple[np.ndarray, dict[int, int]]:
    """Split selected provinces into *target_count* connected total pieces.

    Returns the new map and ``{new_id: parent_id}``, which lets the command
    layer inherit state, strategic-region, continent, and terrain metadata.
    """
    selected = sorted({int(pid) for pid in selected_ids if int(pid) > 0})
    selected = [pid for pid in selected if np.any(province_map == pid)]
    if not selected:
        raise ValueError("Select at least one province")
    if target_count < len(selected):
        raise ValueError("Target count cannot be smaller than the selected province count")

    areas = [int(np.sum(province_map == pid)) for pid in selected]
    if any(area < min_piece_pixels for area in areas):
        raise ValueError("A selected province is too small to split")
    allocations = _allocate_piece_counts(areas, int(target_count))
    for area, pieces in zip(areas, allocations):
        if area < pieces * min_piece_pixels:
            raise ValueError("Target count would create pieces that are too small")

    existing = set(int(value) for value in np.unique(province_map)) - {0}
    max_id = int(province_map.max())
    available = [pid for pid in range(1, max_id + 1) if pid not in existing]
    next_id = max_id + 1

    def allocate_id() -> int:
        nonlocal next_id
        if available:
            return available.pop(0)
        value = next_id
        next_id += 1
        return value

    result = province_map.copy()
    parent_by_new_id: dict[int, int] = {}
    rng = np.random.default_rng(seed)
    for pid, piece_count in zip(selected, allocations):
        if piece_count == 1:
            continue
        ys, xs = np.where(province_map == pid)
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        local_mask = province_map[y0:y1, x0:x1] == pid
        _, component_count = ndimage.label(local_mask, structure=_CROSS)
        if component_count != 1:
            raise ValueError(f"Province {pid} is disconnected and cannot be split safely")
        coords = np.argwhere(local_mask)
        pieces = None
        for _ in range(12):
            seeds = _spread_seeds(coords, piece_count, rng)
            candidate = _geodesic_partition(local_mask, seeds)
            sizes = np.bincount(candidate[local_mask], minlength=piece_count + 1)
            if np.all(sizes[1:] >= min_piece_pixels):
                pieces = candidate
                break
        if pieces is None:
            raise ValueError(f"Province {pid} could not be split into sufficiently large pieces")
        piece_ids = [pid] + [allocate_id() for _ in range(piece_count - 1)]
        local_result = result[y0:y1, x0:x1]
        for piece_label, output_id in enumerate(piece_ids, 1):
            local_result[pieces == piece_label] = output_id
            if output_id != pid:
                parent_by_new_id[output_id] = pid

    return result, parent_by_new_id
