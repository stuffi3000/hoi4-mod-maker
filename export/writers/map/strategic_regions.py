"""strategicregions/*.txt + weatherpositions.txt."""
import os
from math import isfinite as _isfinite

import numpy as np
from data.constants import TILE_LAND, TILE_SEA
# Note: do not import MAP_WIDTH/HEIGHT from data.constants — from import binding values,
# It will not be updated after set_map_size. The actual size will always be taken from province_map.shape.


def write_strategic_regions(province_map, tile_map, output_dir,
                             grid_cols=6, grid_rows=4, states_dict=None):
    """Generate strategic areas. Two modes:
    - Do not pass states_dict: pure grid splitting (old behavior, used by TestMOD)
    - Pass states_dict {sid: [pids]}: state-aware mode - each state occupies an independent region,
      sea/unallocated provinces are replenished by grid. This ensures that all provinces in each state are in the same region
      (Otherwise MAP_ERROR "State has provinces belonging to different strategic areas" is triggered)"""
    d = os.path.join(output_dir, "map", "strategicregions")
    os.makedirs(d, exist_ok=True)

    province_count = int(province_map.max())
    if province_count == 0:
        return []

    # Vectorized calculation of centroids of all provinces (dimensions are taken from province_map, following the actual map)
    H, W = province_map.shape
    flat_pm = province_map.ravel()
    n = province_count + 1
    pid_count = np.bincount(flat_pm, minlength=n)
    ys_grid, xs_grid = np.mgrid[0:H, 0:W]
    sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
    sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)

    centroids = {}
    for pid in range(1, province_count + 1):
        if pid_count[pid] > 0:
            centroids[pid] = (sum_y[pid] / pid_count[pid], sum_x[pid] / pid_count[pid])

    regions: dict[int, list[int]] = {}

    if states_dict:
        # === state-aware mode: one region per state ===
        # First package all provinces of state into regions
        next_rid = 1
        state_in_region = set()
        for sid in sorted(states_dict.keys()):
            provs = states_dict[sid]
            if not provs:
                continue
            regions[next_rid] = list(provs)
            state_in_region.update(provs)
            next_rid += 1

        # The remaining provinces (oceans/lakes/orphans) are added to several regions according to the grid
        cell_h = H / max(1, grid_rows)
        cell_w = W / max(1, grid_cols)
        sea_grid_regions: dict[int, list[int]] = {}
        for pid, (cy, cx) in centroids.items():
            if pid in state_in_region:
                continue
            row = min(int(cy / cell_h), grid_rows - 1)
            col = min(int(cx / cell_w), grid_cols - 1)
            cell_id = row * grid_cols + col
            sea_grid_regions.setdefault(cell_id, []).append(pid)
        for cell_id in sorted(sea_grid_regions.keys()):
            regions[next_rid] = sea_grid_regions[cell_id]
            next_rid += 1
    else:
        # === Old behavior: pure mesh splitting ===
        cell_h = H / grid_rows
        cell_w = W / grid_cols
        for pid, (cy, cx) in centroids.items():
            row = min(int(cy / cell_h), grid_rows - 1)
            col = min(int(cx / cell_w), grid_cols - 1)
            rid = row * grid_cols + col + 1
            regions.setdefault(rid, []).append(pid)

    # Handling provinces without centroids (should not happen in theory)
    all_assigned = set()
    for provs in regions.values():
        all_assigned.update(provs)
    for pid in range(1, province_count + 1):
        if pid not in all_assigned:
            first_rid = min(regions.keys()) if regions else 1
            regions.setdefault(first_rid, []).append(pid)

    # Renumber (continuously starting from 1)
    sorted_rids = sorted(regions.keys())
    region_list = []
    for new_id, old_rid in enumerate(sorted_rids, start=1):
        provs = regions[old_rid]
        if not provs:
            continue
        region_list.append((new_id, provs))

        with open(os.path.join(d, f"{new_id}-strategic_region.txt"), "w", encoding="utf-8") as f:
            f.write("strategic_region={\n")
            f.write(f"\tid={new_id}\n")
            f.write(f'\tname="STRATEGICREGION_WT_{new_id}"\n')
            f.write("\tprovinces={\n\t\t")
            f.write(" ".join(str(p) for p in provs))
            f.write("\n\t}\n")
            f.write("\tweather={\n\t\tperiod={\n")
            # between={ DAY.MONTH DAY.MONTH } — must cover the entire year (0.0 to 30.11)
            # Otherwise HOI4 warning "Region temperature doesn't cover the whole year"
            f.write("\t\t\tbetween={ 0.0 30.11 }\n")
            f.write("\t\t\ttemperature={ -5.0 25.0 }\n")
            f.write("\t\t\tno_phenomenon=0.500\n")
            f.write("\t\t\train_light=0.200\n")
            f.write("\t\t\train_heavy=0.100\n")
            f.write("\t\t\tmud=0.050\n")
            f.write("\t\t\tblizzard=0.050\n")
            f.write("\t\t\tsandstorm=0.000\n")
            f.write("\t\t\tsnow=0.100\n")
            f.write("\t\t}\n\t}\n}\n")

    return region_list


def write_strategic_regions_from_mgr(region_mgr, output_dir):
    """Write strategicregions/*.txt from StrategicRegionManager.

    Use the weather_preset + naval_terrain data in the manager instead of hard-coded placeholders.
    Return region_list for weatherpositions."""
    from domain.managers.strategic_region import WEATHER_PRESETS

    d = os.path.join(output_dir, "map", "strategicregions")
    os.makedirs(d, exist_ok=True)

    region_list = []
    # Renumbering (consecutively from 1, HOI4 required)
    sorted_regions = sorted(region_mgr.regions.values(), key=lambda r: r.id)
    for new_id, region in enumerate(sorted_regions, start=1):
        provs = region.province_ids
        if not provs:
            continue
        region_list.append((new_id, provs))

        preset = region.weather_preset or "temperate"
        periods = WEATHER_PRESETS.get(preset, WEATHER_PRESETS["temperate"])

        with open(os.path.join(d, f"{new_id}-strategic_region.txt"), "w", encoding="utf-8") as f:
            f.write("strategic_region={\n")
            f.write(f"\tid={new_id}\n")
            # Always write the generated key, never region.name: user-entered text may be non-ASCII and
            # To non-ASCII, the game will crash directly. Display name goes localization yml.
            f.write(f'\tname="STRATEGICREGION_WT_{new_id}"\n')
            if region.naval_terrain:
                f.write(f"\tnaval_terrain={region.naval_terrain}\n")
            f.write("\tprovinces={\n\t\t")
            f.write(" ".join(str(p) for p in provs))
            f.write("\n\t}\n")
            f.write("\tweather={\n")
            for period in periods:
                f.write("\t\tperiod={\n")
                f.write(f"\t\t\tbetween={{ {period['between']} }}\n")
                f.write(f"\t\t\ttemperature={{ {period['temp']} }}\n")
                f.write(f"\t\t\tno_phenomenon={period['no']:.3f}\n")
                f.write(f"\t\t\train_light={period['rain_light']:.3f}\n")
                f.write(f"\t\t\train_heavy={period['rain_heavy']:.3f}\n")
                f.write(f"\t\t\tsnow={period['snow']:.3f}\n")
                f.write(f"\t\t\tblizzard={period['blizzard']:.3f}\n")
                f.write(f"\t\t\tmud={period['mud']:.3f}\n")
                f.write(f"\t\t\tsandstorm={period['sandstorm']:.3f}\n")
                if period.get("min_snow", 0) > 0:
                    f.write(f"\t\t\tmin_snow_level={period['min_snow']:.2f}\n")
                f.write("\t\t}\n")
            f.write("\t}\n}\n")

    return region_list


_REVIEWED_WEATHER = ("reviewed", "accepted")
_COMPAT_WEATHER_PROFILES = ("acceptance", "scaffold", "legacy_full")
_VALID_WEATHER_SIZES = ("small", "medium", "large", "huge")


def _normalize_weather_size(value):
    try:
        text = str(value).strip().lower()
    except Exception:
        return "small"
    if text in _VALID_WEATHER_SIZES:
        return text
    return "small"


def _emitted_region_mapping(strategic_region_mgr):
    if strategic_region_mgr is None:
        return None
    try:
        regions_obj = strategic_region_mgr.regions
        if callable(regions_obj):
            regions_obj = regions_obj()
        if isinstance(regions_obj, dict):
            items = list(regions_obj.values())
        else:
            items = list(regions_obj)
    except Exception:
        return {}
    try:
        ordered = sorted(items, key=lambda r: int(getattr(r, "id")))
    except Exception:
        return {}
    mapping = {}
    for new_id, region in enumerate(ordered, start=1):
        try:
            orig = int(getattr(region, "id"))
        except Exception:
            continue
        try:
            provs = getattr(region, "province_ids")
        except Exception:
            continue
        try:
            if not provs:
                continue
        except Exception:
            continue
        if orig not in mapping:
            mapping[orig] = new_id
    return mapping


def _weather_centroid_line(rid, provs, pid_count, sum_x, sum_y, H, W, n):
    total_pix = 0
    sx = 0.0
    sy = 0.0
    try:
        iterable = list(provs)
    except Exception:
        iterable = []
    for item in iterable:
        try:
            pi = int(item)
        except Exception:
            continue
        if 0 <= pi < n and pid_count[pi] > 0:
            sx += float(sum_x[pi])
            sy += float(sum_y[pi])
            total_pix += int(pid_count[pi])
    if total_pix == 0:
        cx, cy = W / 2, H / 2
    else:
        cx = sx / total_pix
        cy = sy / total_pix
    hoi4_z = H - cy
    return f"{rid};{cx:.2f};10.00;{hoi4_z:.2f};small"


def write_weatherpositions(region_list, province_map, output_dir, map_placement_mgr=None, strategic_region_mgr=None, profile_name=None):
    """Write map/weatherpositions.txt, with one weather position point for each strategic area.
    The original file must be overwritten, otherwise the region ID in the original file will become invalid -> MAP_ERROR "invalid region id".
    Format (vanilla validation): `region_id;x;y;z;size`
        - Semicolon separated, no spaces, no parentheses
        - x/y/z are 3D coordinates (z is map coordinates = MAP_HEIGHT - pixel_y)
        - y is height, fixed ~10
        - size: small / medium / large / huge
    Extended M5.5 behavior (trailing args preserve legacy calls):
        - No placement manager (or non foundation/compat profile): deterministic centroid fallback, one line per region.
        - foundation + manager: only reviewed/accepted manager weather mapped to emitted non-empty regions, no fallback.
        - compat (acceptance/scaffold/legacy_full) + manager: centroid fallback for regions without reviewed manager weather,
          reviewed manager records overlay without duplicate fallback. Deterministic order by emitted region then record id.
    """
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    H, W = province_map.shape
    mgr = map_placement_mgr
    is_foundation = (mgr is not None and profile_name == "foundation")
    is_compat = (mgr is not None and profile_name in _COMPAT_WEATHER_PROFILES)
    try:
        regions_snapshot = list(region_list) if region_list is not None else []
    except Exception:
        regions_snapshot = []
    if mgr is None or (not is_foundation and not is_compat):
        flat_pm = province_map.ravel()
        n = int(province_map.max()) + 1
        pid_count = np.bincount(flat_pm, minlength=n)
        ys_grid, xs_grid = np.mgrid[0:H, 0:W]
        sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)
        with open(os.path.join(d, "weatherpositions.txt"), "w", encoding="utf-8") as f:
            for rid, provs in regions_snapshot:
                total_pix = 0
                sx = 0.0
                sy = 0.0
                for item in provs:
                    pi = int(item)
                    if pi < n and pid_count[pi] > 0:
                        sx += sum_x[pi]
                        sy += sum_y[pi]
                        total_pix += int(pid_count[pi])
                if total_pix == 0:
                    cx, cy = W / 2, H / 2
                else:
                    cx = sx / total_pix
                    cy = sy / total_pix
                hoi4_z = H - cy
                f.write(f"{rid};{cx:.2f};10.00;{hoi4_z:.2f};small\n")
        return
    try:
        region_rids = set()
        for rid, _provs in regions_snapshot:
            region_rids.add(int(rid))
    except Exception:
        region_rids = set()
    orig_to_emitted = _emitted_region_mapping(strategic_region_mgr)
    collected = []
    try:
        records = mgr.list_weather()
    except Exception:
        records = []
    if records:
        for rec in records:
            try:
                status = getattr(rec, "review_status", None)
            except Exception:
                continue
            if status not in _REVIEWED_WEATHER:
                continue
            try:
                orig_rid = int(getattr(rec, "region_id"))
                wid = int(getattr(rec, "id"))
                x = float(getattr(rec, "x"))
                y = float(getattr(rec, "y"))
                h = float(getattr(rec, "height", 0.0))
                size = _normalize_weather_size(getattr(rec, "size", ""))
            except Exception:
                continue
            if not (_isfinite(x) and _isfinite(y) and _isfinite(h)):
                continue
            if orig_to_emitted is not None:
                emitted = orig_to_emitted.get(orig_rid)
                if emitted is None:
                    continue
                if emitted not in region_rids:
                    continue
            else:
                emitted = orig_rid
                if emitted not in region_rids:
                    continue
            hoi4_z = float(H) - y
            if not _isfinite(hoi4_z):
                continue
            collected.append((emitted, wid, f"{emitted};{x:.2f};{h:.2f};{hoi4_z:.2f};{size}"))
    collected.sort(key=lambda item: (item[0], item[1]))
    if is_foundation:
        with open(os.path.join(d, "weatherpositions.txt"), "w", encoding="utf-8") as f:
            for _emitted, _wid, line in collected:
                f.write(line + "\n")
        return
    by_emitted = {}
    for emitted, wid, line in collected:
        by_emitted.setdefault(emitted, []).append((wid, line))
    for key in list(by_emitted.keys()):
        by_emitted[key].sort(key=lambda pair: pair[0])
    flat_pm = province_map.ravel()
    n = int(province_map.max()) + 1
    pid_count = np.bincount(flat_pm, minlength=n)
    ys_grid, xs_grid = np.mgrid[0:H, 0:W]
    sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
    sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)
    try:
        ordered = sorted(regions_snapshot, key=lambda pair: int(pair[0]))
    except Exception:
        ordered = list(regions_snapshot)
    with open(os.path.join(d, "weatherpositions.txt"), "w", encoding="utf-8") as f:
        for rid, provs in ordered:
            try:
                rid_int = int(rid)
            except Exception:
                continue
            if rid_int in by_emitted:
                for _wid, line in by_emitted[rid_int]:
                    f.write(line + "\n")
            else:
                f.write(_weather_centroid_line(rid_int, provs, pid_count, sum_x, sum_y, H, W, n) + "\n")
    return
