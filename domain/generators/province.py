"""Province generator — Poisson disk + Lloyd relaxation, fully vectorized implementation

Algorithm:
1. Poisson disk sampling (seeds evenly spaced)
2. KDTree nearest neighbor allocates pixels
3. Lloyd relaxation for 2 rounds (the seeds are moved to the centroid and redistributed)
4. Post-processing: X-crossing repair + connectivity repair + ID compaction"""
import numpy as np
from scipy.spatial import KDTree

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_SEA, TILE_LAKE,
    FORBIDDEN_COLOR, MIN_PROVINCE_PIXELS,
)


def generate_provinces(
    tile_map: np.ndarray,
    target_count: int = 12000,
    land_density_ratio: float = 15.0,
    sea_scale: float = 0.15,
    lake_scale: float = 0.3,
    lloyd_iterations: int = 2,
    density_map: np.ndarray | None = None,
) -> tuple[np.ndarray, int]:
    """Generate provinces based on Poisson disk + Lloyd relaxation.

    Parameters:
        tile_map: (H, W) uint8, TILE_LAND/SEA/LAKE
        target_count: total number of target provinces
        land_density_ratio: land density weight (vs ocean 1.0)
        sea_scale: Ocean province density coefficient (0.15 = ocean only generates 15% of province density)
        lake_scale: lake province density coefficient (0.3 = lakes are 30% of the density of land)
        lloyd_iterations: Number of Lloyd relaxation iterations (0=no relaxation, 2=recommended)
        density_map: (H, W) float32, 0.0~1.0 density map (1=dense, 0=sparse), None=uniform"""
    land_mask = tile_map == TILE_LAND
    sea_mask = tile_map == TILE_SEA
    lake_mask = tile_map == TILE_LAKE

    land_pixels = int(np.sum(land_mask))
    sea_pixels = int(np.sum(sea_mask))
    lake_pixels = int(np.sum(lake_mask))
    total_pixels = land_pixels + sea_pixels + lake_pixels

    if total_pixels == 0:
        raise ValueError("The map contains no valid tiles (land, sea, or lake)")

    # Calculate the number of provinces in each region - use sea_scale to reduce the ocean
    land_weight = land_pixels * land_density_ratio
    sea_weight = sea_pixels * sea_scale
    lake_weight = lake_pixels * lake_scale
    total_weight = land_weight + sea_weight + lake_weight or 1

    land_count = max(1, int(target_count * land_weight / total_weight)) if land_pixels > 0 else 0
    sea_count = max(1, int(target_count * sea_weight / total_weight)) if sea_pixels > 0 else 0
    lake_count = max(1, int(target_count * lake_weight / total_weight)) if lake_pixels > 0 else 0

    # Sow seeds and distribute - handle them separately according to connected areas to prevent provinces from crossing the sea
    from scipy.ndimage import label as _label

    h, w = tile_map.shape
    province_map = np.zeros((h, w), dtype=np.int32)
    next_id = 1

    tile_types = [
        (land_mask, land_count, lloyd_iterations),   # Land Run Lloyd
        (sea_mask, sea_count, 0),                    # The ocean does not run Lloyd (less seeds, good speed)
        (lake_mask, lake_count, 0),                  # The lake does not run Lloyd
    ]
    for mask, count, region_lloyd in tile_types:
        if count <= 0 or not np.any(mask):
            continue

        # Split regions of the same type into connected components
        labeled, num_regions = _label(mask)
        if num_regions > 1:
            labeled = _merge_wrap_regions(labeled, mask)
            num_regions = int(labeled.max())
        total_type_pixels = int(np.sum(mask))

        for region_id in range(1, num_regions + 1):
            region_mask = labeled == region_id
            pixel_ys, pixel_xs = np.where(region_mask)
            n_pixels = len(pixel_ys)
            if n_pixels == 0:
                continue

            # Distribute the number of provinces according to area proportion
            region_count = max(1, int(count * n_pixels / total_type_pixels))
            region_count = min(region_count, n_pixels)

            # Check if wrap boundary is crossed
            crosses_wrap = (pixel_xs.min() == 0 and pixel_xs.max() >= w - 1)

            # Poisson disk sampling seeds (supports density plots)
            seed_ys, seed_xs = _poisson_disk_sample(
                pixel_ys, pixel_xs, region_count, n_pixels,
                density_map=density_map,
            )
            actual_count = len(seed_ys)

            # KDTree allocation + Lloyd relaxation
            for lloyd_iter in range(region_lloyd + 1):
                if crosses_wrap:
                    seed_coords = np.column_stack([
                        np.tile(seed_ys, 3),
                        np.concatenate([seed_xs, seed_xs - w, seed_xs + w]),
                    ])
                    tree = KDTree(seed_coords)
                    pixel_coords = np.column_stack([pixel_ys, pixel_xs])
                    _, nearest = tree.query(pixel_coords)
                    nearest = nearest % actual_count
                else:
                    seed_coords = np.column_stack([seed_ys, seed_xs])
                    tree = KDTree(seed_coords)
                    pixel_coords = np.column_stack([pixel_ys, pixel_xs])
                    _, nearest = tree.query(pixel_coords)

                # Lloyd relaxation: move seeds to the centroid of their respective regions (vectorization)
                if lloyd_iter < region_lloyd:
                    # bincount finds the sum of the number of pixels and coordinates of each seed
                    counts = np.bincount(nearest, minlength=actual_count).astype(np.float64)
                    sum_y = np.bincount(nearest, weights=pixel_ys.astype(np.float64), minlength=actual_count)
                    sum_x = np.bincount(nearest, weights=pixel_xs.astype(np.float64), minlength=actual_count)
                    # avoid division by zero
                    safe_counts = np.maximum(counts, 1.0)
                    new_sy = np.where(counts > 0, sum_y / safe_counts, seed_ys.astype(np.float64))
                    new_sx = np.where(counts > 0, sum_x / safe_counts, seed_xs.astype(np.float64))
                    seed_ys = new_sy.astype(np.int32)
                    seed_xs = new_sx.astype(np.int32)

            # Vectorized ID assignment
            global_ids = np.arange(next_id, next_id + actual_count, dtype=np.int32)
            province_map[pixel_ys, pixel_xs] = global_ids[nearest]
            next_id += actual_count

    # Post-Processing: Repairing the X-Cross
    from domain.validators.province import fix_x_crossings
    for _ in range(5):
        if fix_x_crossings(province_map) == 0:
            break

    # Post-processing: Repair discontinuous provinces
    _fix_non_contiguous_fast(province_map)

    # Another round of X-crossings
    for _ in range(5):
        if fix_x_crossings(province_map) == 0:
            break

    # Cleaned small provinces (< 8 pixels) → merge to largest neighbor, loop until all cleared
    for _ in range(10):
        merged = _merge_tiny_provinces(province_map, min_pixels=MIN_PROVINCE_PIXELS)
        if merged == 0:
            break

    # Compaction ID
    province_count = compact_province_ids(province_map)
    return province_map, province_count


def generate_provinces_for_type(
    tile_map: np.ndarray,
    existing_province_map: np.ndarray,
    tile_type: int,
    target_count: int = 12000,
    *,
    density_map: np.ndarray | None = None,
) -> tuple[np.ndarray, int]:
    """Regenerate one tile type while preserving the other province IDs.

    The selected tile type is temporarily represented as land so the normal
    generator can distribute exactly the requested number of seeds.  Pixels
    belonging to other tile types, and their existing province IDs, are left
    untouched.  New IDs are allocated after the highest preserved ID.
    """
    tile = np.asarray(tile_map)
    existing = np.asarray(existing_province_map)
    if tile.ndim != 2 or existing.ndim != 2 or tile.shape != existing.shape:
        raise ValueError("tile_map and existing_province_map must be matching 2-D arrays")
    if int(tile_type) not in (TILE_LAND, TILE_SEA, TILE_LAKE):
        raise ValueError("tile_type must be TILE_LAND, TILE_SEA, or TILE_LAKE")

    selected = tile == int(tile_type)
    result = existing.astype(np.int32, copy=True)
    result[selected] = 0
    if not np.any(selected):
        return result, 0

    # Generate only the selected pixels.  Treating them as land avoids the
    # sea/lake density multipliers, because this button's count is the target
    # for the selected type rather than the whole-map total.
    scoped_tiles = np.zeros(tile.shape, dtype=np.uint8)
    scoped_tiles[selected] = TILE_LAND
    generated, generated_count = generate_provinces(
        scoped_tiles,
        target_count=max(1, int(target_count)),
        land_density_ratio=1.0,
        sea_scale=1.0,
        lake_scale=1.0,
        lloyd_iterations=2 if int(tile_type) == TILE_LAND else 0,
        density_map=density_map,
    )

    next_id = int(result.max()) + 1
    generated_ids = generated[selected]
    result[selected] = np.where(
        generated_ids > 0,
        generated_ids.astype(np.int32) + next_id - 1,
        0,
    )
    return result, int(generated_count)


def _poisson_disk_sample(
    pixel_ys: np.ndarray,
    pixel_xs: np.ndarray,
    target_count: int,
    n_pixels: int,
    density_map: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Poisson disk sampling: placing a seed in a given set of pixels.

    Approximation algorithm: Divide the pixel area into grids, and decide whether to place seeds in each grid based on density.
    Degenerates to uniform sampling when density_map is None.

    density_map: (H, W) float32, 0.0=sparse ~ 1.0=dense"""
    if target_count >= n_pixels:
        return pixel_ys.copy(), pixel_xs.copy()

    if target_count <= 10:
        indices = np.random.choice(n_pixels, size=target_count, replace=False)
        return pixel_ys[indices], pixel_xs[indices]

    # Calculate basic grid spacing (use the densest spacing, density map control skips)
    y_min, y_max = pixel_ys.min(), pixel_ys.max()
    x_min, x_max = pixel_xs.min(), pixel_xs.max()
    area = n_pixels

    if density_map is not None:
        # Use a finer grid (by maximum density), and then skip low-density grids with probability
        # The basic cell_size is estimated according to target_count * 1.5 (spread more and cut later)
        cell_size = max(1, int(np.sqrt(area / (target_count * 1.5))))
    else:
        cell_size = max(1, int(np.sqrt(area / target_count)))

    # Meshing
    grid_rows = max(1, (y_max - y_min + 1) // cell_size)
    grid_cols = max(1, (x_max - x_min + 1) // cell_size)

    # Divide pixels into grids
    cell_y = np.clip((pixel_ys - y_min) // cell_size, 0, grid_rows - 1)
    cell_x = np.clip((pixel_xs - x_min) // cell_size, 0, grid_cols - 1)
    cell_id = cell_y * grid_cols + cell_x

    # Each grid with pixels determines whether to place seeds
    unique_cells = np.unique(cell_id)
    seed_ys_list = []
    seed_xs_list = []

    for cid in unique_cells:
        cell_mask = cell_id == cid
        cell_indices = np.where(cell_mask)[0]
        chosen = np.random.choice(cell_indices)
        cy, cx = pixel_ys[chosen], pixel_xs[chosen]

        if density_map is not None:
            # Sample the density value at this location, and the probability determines whether to place seeds.
            # density=1.0 → 100% release, density=0.0 → basic probability (not completely skipped)
            d = float(density_map[cy, cx])
            prob = 0.1 + 0.9 * d  # Minimum 10% probability, guaranteed not to be completely blank
            if np.random.random() > prob:
                continue

        seed_ys_list.append(cy)
        seed_xs_list.append(cx)

    result_ys = np.array(seed_ys_list, dtype=np.int32)
    result_xs = np.array(seed_xs_list, dtype=np.int32)

    # If there are too many seeds, randomly crop to the target number
    if len(result_ys) > target_count:
        indices = np.random.choice(len(result_ys), size=target_count, replace=False)
        result_ys = result_ys[indices]
        result_xs = result_xs[indices]
    # If too few, add random seeds (prioritize high-density areas)
    elif len(result_ys) < target_count:
        deficit = target_count - len(result_ys)
        if density_map is not None:
            # Weighted random sampling based on density value
            densities = density_map[pixel_ys, pixel_xs].astype(np.float64)
            densities = np.maximum(densities, 0.01)
            probs = densities / densities.sum()
            n_candidates = len(pixel_ys)
            extra = np.random.choice(n_candidates, size=min(deficit, n_candidates),
                                     replace=False, p=probs)
        else:
            extra = np.random.choice(n_pixels, size=min(deficit, n_pixels), replace=False)
        result_ys = np.concatenate([result_ys, pixel_ys[extra[:deficit]]])
        result_xs = np.concatenate([result_xs, pixel_xs[extra[:deficit]]])

    return result_ys, result_xs


def _merge_wrap_regions(labeled: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Merge transversely wrap-connected regions (left edge x=0 and right edge x=W-1 are connected in the same row)."""
    H, W = labeled.shape

    # union-find
    max_label = int(labeled.max())
    parent = list(range(max_label + 1))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Both left and right edges have pixels in the same row → merge their labels
    left_col = labeled[:, 0]
    right_col = labeled[:, -1]
    for y in range(H):
        l, r = int(left_col[y]), int(right_col[y])
        if l > 0 and r > 0:
            union(l, r)

    # Remap to the root label and compact it into 1..N
    root_map = np.array([find(i) for i in range(max_label + 1)], dtype=np.int32)
    unique_roots = np.unique(root_map[1:])  # exclude 0
    compact = np.zeros(max_label + 1, dtype=np.int32)
    for new_id, root in enumerate(unique_roots, 1):
        for old_id in range(1, max_label + 1):
            if root_map[old_id] == root:
                compact[old_id] = new_id

    return compact[labeled]


def _fix_non_contiguous_fast(province_map: np.ndarray) -> None:
    """Fix discontinuous provinces: all non-main body fragments are merged into neighbors.

    Optimization: First use argsort to group at once, bbox+fill rate to quickly skip connected provinces."""
    from scipy.ndimage import label

    H, W = province_map.shape

    unique_ids = np.unique(province_map)
    unique_ids = unique_ids[unique_ids > 0]

    # One-time grouping of coordinates by province ID
    flat = province_map.ravel()
    order = np.argsort(flat, kind='stable')
    sorted_ids = flat[order]
    change = np.where(np.diff(sorted_ids) != 0)[0] + 1
    splits = np.split(order, change)
    split_ids = sorted_ids[np.concatenate([[0], change])]

    pid_to_bbox: dict[int, tuple] = {}
    for sid, group in zip(split_ids, splits):
        if sid <= 0:
            continue
        pys, pxs = np.divmod(group, W)
        pid_to_bbox[int(sid)] = (pys, pxs, int(pys.min()), int(pys.max()) + 1,
                                  int(pxs.min()), int(pxs.max()) + 1, len(group))

    for pid, (ys, xs, y0, y1, x0, x1, pixel_count) in pid_to_bbox.items():
        bbox_area = (y1 - y0) * (x1 - x0)
        # Fill rate > 30% and bbox < 10000 → almost definitely connected, skip
        if bbox_area < 10000 or pixel_count > 0.3 * bbox_area:
            continue

        # Only label suspicious provinces (within the bbox sub-region)
        mask = province_map == pid
        sub_mask = mask[y0:y1, x0:x1]
        labeled, num_features = label(sub_mask)
        if num_features <= 1:
            continue

        comp_counts = np.bincount(labeled.ravel())[1:]
        largest = int(np.argmax(comp_counts)) + 1

        for comp_id in range(1, num_features + 1):
            if comp_id == largest:
                continue

            frag_local = labeled == comp_id
            frag_ys, frag_xs = np.where(frag_local)
            frag_ys = frag_ys + y0
            frag_xs = frag_xs + x0

            all_neighbors = set()
            for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                ny = np.clip(frag_ys + dy, 0, H - 1)
                nx = np.clip(frag_xs + dx, 0, W - 1)
                neighbor_vals = province_map[ny, nx]
                for nid in np.unique(neighbor_vals):
                    if nid > 0 and nid != pid:
                        all_neighbors.add(int(nid))

            if all_neighbors:
                province_map[frag_ys, frag_xs] = min(all_neighbors)


def auto_classify_water(tile_map: np.ndarray) -> int:
    """Automatically convert "sea pixels surrounded by land" to lake.
    The largest connected component is retained as sea, and the rest are converted to lake. Consider horizontal wrap."""
    from scipy.ndimage import label

    sea_mask = tile_map == TILE_SEA
    if not sea_mask.any():
        return 0

    struct = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.int32)
    labeled, n_comps = label(sea_mask, structure=struct)
    if n_comps <= 1:
        return 0

    # Horizontal wrap union-find
    parent = list(range(n_comps + 1))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    left_col = labeled[:, 0]
    right_col = labeled[:, -1]
    for y in range(tile_map.shape[0]):
        l = left_col[y]
        r = right_col[y]
        if l > 0 and r > 0:
            union(int(l), int(r))

    root_map = np.zeros(n_comps + 1, dtype=np.int32)
    for i in range(1, n_comps + 1):
        root_map[i] = find(i)
    merged = root_map[labeled]

    counts = np.bincount(merged.ravel())
    counts[0] = 0
    main_root = int(counts.argmax())

    to_lake = sea_mask & (merged != main_root)
    converted = int(to_lake.sum())
    if converted > 0:
        tile_map[to_lake] = TILE_LAKE
    return converted


def compact_province_ids(province_map: np.ndarray) -> int:
    """Compact the IDs in province_map into 1..N consecutive integers."""
    unique_ids = np.unique(province_map)
    if unique_ids[0] != 0:
        new_ids = np.arange(1, len(unique_ids) + 1, dtype=np.int32)
        mapping = dict(zip(unique_ids.tolist(), new_ids.tolist()))
    else:
        new_ids = np.zeros(len(unique_ids), dtype=np.int32)
        new_ids[1:] = np.arange(1, len(unique_ids), dtype=np.int32)
        mapping = dict(zip(unique_ids.tolist(), new_ids.tolist()))

    if unique_ids.max() < 1_000_000:
        lut = np.zeros(unique_ids.max() + 1, dtype=np.int32)
        for old, new in mapping.items():
            lut[old] = new
        province_map[:] = lut[province_map]
    else:
        sorted_old = unique_ids
        idx = np.searchsorted(sorted_old, province_map.ravel())
        province_map[:] = new_ids[idx].reshape(province_map.shape)

    return int(province_map.max())


def generate_provinces_incremental(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    target_density: float | None = None,
    lloyd_iterations: int = 2,
    skip_mismatch_clear: bool = False,
) -> tuple[np.ndarray, int]:
    """Incremental province generation: Only generate provinces for new areas that have no provinces allocated, leaving existing provinces unchanged.

    Parameters:
        tile_map: (H, W) uint8, TILE_LAND/SEA/LAKE
        province_map: (H, W) int32, existing province (>0 does not move)
        target_density: average number of pixels per province (default = total pixels / 12000)
        lloyd_iterations: Number of Lloyd relaxation iterations
        skip_mismatch_clear: Skip _clear_type_mismatched_pixels (the caller has been processed with mask)
    Return:
        (updated province_map, total number of provinces)"""
    from scipy.ndimage import label as _label

    H, W = tile_map.shape
    result = province_map.copy()
    next_id = int(result.max()) + 1

    if target_density is None:
        target_density = max(1.0, (H * W) / 12000.0)

    # Find the pixels to which provinces need to be assigned
    if not skip_mismatch_clear:
        _clear_type_mismatched_pixels(result, tile_map)

    unassigned_land = (tile_map == TILE_LAND) & (result == 0)
    unassigned_sea = (tile_map == TILE_SEA) & (result == 0)
    unassigned_lake = (tile_map == TILE_LAKE) & (result == 0)

    # Use KDTree for all types (Ocean/Lake does not run Lloyd)
    incremental_types = [
        (unassigned_land, 1.0, lloyd_iterations),   # Land Run Lloyd
        (unassigned_sea, 4.0, 0),                   # The ocean does not run away Lloyd, the density is low
        (unassigned_lake, 3.0, 0),                  # The lake does not run Lloyd
    ]
    for inc_mask, density_scale, inc_lloyd in incremental_types:
        n_total = int(np.sum(inc_mask))
        if n_total == 0:
            continue
        type_target = max(1, int(n_total / (target_density * density_scale)))

        # Split into connected components
        labeled, num_regions = _label(inc_mask)
        if num_regions > 1:
            labeled = _merge_wrap_regions(labeled, inc_mask)
            num_regions = int(labeled.max())

        for region_id in range(1, num_regions + 1):
            region_mask = labeled == region_id
            pixel_ys, pixel_xs = np.where(region_mask)
            n_pixels = len(pixel_ys)
            if n_pixels == 0:
                continue

            region_count = max(1, int(type_target * n_pixels / n_total))
            region_count = min(region_count, n_pixels)

            crosses_wrap = (pixel_xs.min() == 0 and pixel_xs.max() >= W - 1)

            seed_ys, seed_xs = _poisson_disk_sample(
                pixel_ys, pixel_xs, region_count, n_pixels
            )
            actual_count = len(seed_ys)

            for lloyd_iter in range(inc_lloyd + 1):
                if crosses_wrap:
                    seed_coords = np.column_stack([
                        np.tile(seed_ys, 3),
                        np.concatenate([seed_xs, seed_xs - W, seed_xs + W]),
                    ])
                    tree = KDTree(seed_coords)
                    pixel_coords = np.column_stack([pixel_ys, pixel_xs])
                    _, nearest = tree.query(pixel_coords)
                    nearest = nearest % actual_count
                else:
                    seed_coords = np.column_stack([seed_ys, seed_xs])
                    tree = KDTree(seed_coords)
                    pixel_coords = np.column_stack([pixel_ys, pixel_xs])
                    _, nearest = tree.query(pixel_coords)

                if lloyd_iter < inc_lloyd:
                    counts = np.bincount(nearest, minlength=actual_count).astype(np.float64)
                    sum_y = np.bincount(nearest, weights=pixel_ys.astype(np.float64), minlength=actual_count)
                    sum_x = np.bincount(nearest, weights=pixel_xs.astype(np.float64), minlength=actual_count)
                    safe_counts = np.maximum(counts, 1.0)
                    new_sy = np.where(counts > 0, sum_y / safe_counts, seed_ys.astype(np.float64))
                    new_sx = np.where(counts > 0, sum_x / safe_counts, seed_xs.astype(np.float64))
                    seed_ys = new_sy.astype(np.int32)
                    seed_xs = new_sx.astype(np.int32)

            global_ids = np.arange(next_id, next_id + actual_count, dtype=np.int32)
            result[pixel_ys, pixel_xs] = global_ids[nearest]
            next_id += actual_count

    # Post-processing: Only newly added areas will be repaired, existing provinces will not be affected.
    from domain.validators.province import fix_x_crossings_preserving
    protected_pixels = province_map > 0
    for _ in range(3):
        if fix_x_crossings_preserving(result, protected_pixels, tile_map) == 0:
            break

    # Do not do compact_province_ids — incremental mode leaves old IDs unchanged
    province_count = int(result.max())
    return result, province_count


def _merge_tiny_provinces(province_map: np.ndarray, min_pixels: int = 8) -> int:
    """Merge provinces with pixel count < min_pixels into the adjacent largest province. Returns the combined quantity."""
    flat = province_map.ravel()
    max_pid = int(province_map.max())
    counts = np.bincount(flat, minlength=max_pid + 1)

    tiny_pids = [pid for pid in range(1, max_pid + 1) if 0 < counts[pid] < min_pixels]
    if not tiny_pids:
        return 0

    H, W = province_map.shape
    merged = 0
    for pid in tiny_pids:
        ys, xs = np.where(province_map == pid)
        if len(ys) == 0:
            continue
        # Find all neighbor provinces
        neighbors: dict[int, int] = {}
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny = np.clip(ys + dy, 0, H - 1)
            nx = np.clip(xs + dx, 0, W - 1)
            adj_ids = province_map[ny, nx]
            for aid in np.unique(adj_ids):
                aid = int(aid)
                if aid != pid and aid > 0:
                    neighbors[aid] = neighbors.get(aid, 0) + int(np.sum(adj_ids == aid))
        if not neighbors:
            continue
        # Merge to neighbor with largest contact area
        best = max(neighbors, key=neighbors.get)
        province_map[ys, xs] = best
        merged += 1

    return merged


def generate_province_colors(province_count: int) -> dict[int, tuple[int, int, int]]:
    """Generate unique RGB colors for each province."""
    rng = np.random.default_rng(42)

    max_attempts = province_count * 2
    r = rng.integers(1, 256, size=max_attempts, dtype=np.uint8)
    g = rng.integers(0, 256, size=max_attempts, dtype=np.uint8)
    b = rng.integers(0, 256, size=max_attempts, dtype=np.uint8)

    colors = {}
    used = {(0, 0, 0)}
    idx = 0
    for pid in range(1, province_count + 1):
        while idx < max_attempts:
            color = (int(r[idx]), int(g[idx]), int(b[idx]))
            idx += 1
            if color not in used:
                used.add(color)
                colors[pid] = color
                break
        else:
            while True:
                color = (int(rng.integers(1, 256)), int(rng.integers(0, 256)), int(rng.integers(0, 256)))
                if color not in used:
                    used.add(color)
                    colors[pid] = color
                    break

    return colors


def expand_provinces_to_new_land(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> tuple[np.ndarray, int, list[int]]:
    """Create new provinces for areas where "sea turns to land". Minimalist logic:

    1. Find new land (tile=LAND but province is a maritime province)
    2. Each connected block = a new land province
    3. Maritime provinces lose those pixels (natural reduction)
    4. If a maritime province is completely swallowed → return to warning

    User scenario:
    - Draw land on ocean borders → Sea provinces spit out some pixels for new provinces
    - Swallow the whole province → Report missing
    - The new land spans land and sea → the ocean part is processed as above, and the boundaries of the land part fit naturally

    Return: (updated province_map, number of new provinces, list of annexed province IDs)"""
    from scipy.ndimage import label as _label

    result = province_map.copy()
    max_pid = int(result.max())
    if max_pid == 0:
        return result, 0, []

    # Determine whether each province is land or sea
    flat_pm = result.ravel()
    flat_tm = tile_map.ravel()
    pid_total = np.bincount(flat_pm, minlength=max_pid + 1).astype(np.float64)
    pid_land = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND).astype(np.float64), minlength=max_pid + 1)
    pid_is_land = np.zeros(max_pid + 1, dtype=bool)
    pid_is_land[1:] = (pid_land[1:] / np.maximum(pid_total[1:], 1)) > 0.5

    # New land = tile is LAND but province is not land province
    new_land = (tile_map == TILE_LAND) & ~pid_is_land[result]
    if not np.any(new_land):
        return result, 0, []

    # Each connected block = a new province
    labeled, num_chunks = _label(new_land)
    new_count = 0
    next_id = max_pid + 1
    for cid in range(1, num_chunks + 1):
        result[labeled == cid] = next_id
        next_id += 1
        new_count += 1

    # Check out the completely swallowed sea province
    consumed = []
    new_pid_total = np.bincount(result.ravel(), minlength=max_pid + 1)
    for pid in range(1, max_pid + 1):
        if not pid_is_land[pid] and pid_total[pid] > 0 and new_pid_total[pid] == 0:
            consumed.append(pid)

    return result, new_count, consumed


def _clear_type_mismatched_pixels(province_map: np.ndarray, tile_map: np.ndarray) -> int:
    """Clear "type mismatch" pixel province IDs.

    Scenario: The user draws land → tile=LAND on the sea but pm also points to the ocean province.
    Set the pm of these pixels to 0 (unallocated) and let the delta generator assign them new land provinces.
    The same goes for the reverse (land to ocean).

    Only clear **minority** pixels: If 80% of a province's pixels are land, only clear the 20% of ocean pixels.
    This will not destroy existing land provinces."""
    max_pid = int(province_map.max())
    if max_pid == 0:
        return 0

    flat_pm = province_map.ravel()
    flat_tm = tile_map.ravel()

    pid_total = np.bincount(flat_pm, minlength=max_pid + 1)
    pid_land = np.bincount(
        flat_pm,
        weights=(flat_tm == TILE_LAND).astype(np.float64),
        minlength=max_pid + 1,
    )
    safe_total = np.maximum(pid_total, 1)
    land_ratio = pid_land / safe_total

    # "Main Type" for each province: >50% Land → Land Province
    pid_is_land = np.zeros(max_pid + 1, dtype=bool)
    pid_is_land[1:] = land_ratio[1:] > 0.5

    # Check pixel by pixel: tile type != province main type → clear
    pixel_prov_is_land = pid_is_land[province_map]
    pixel_is_land = tile_map == TILE_LAND
    mismatch = (pixel_is_land != pixel_prov_is_land) & (province_map > 0)

    cleared = int(mismatch.sum())
    province_map[mismatch] = 0
    return cleared
