"""buildings.txt writer with profile aware placement support."""
import os
import numpy as np
from data.constants import (
    TILE_LAND, TILE_SEA,
    VALID_3D_BUILDING_TYPES,
)
from domain.validators.province import get_coastal_provinces, build_coastal_land_to_sea
from export.writers.map._coords import safe_coord as _safe_coord
_REVIEWED = ("reviewed", "accepted")
_COMPAT_PROFILES = ("acceptance", "scaffold", "legacy_full")
_COMPAT_MARKER = "# generated placeholders for {profile} compatibility; reviewed manager records appended where reviewed"
def _resolve_mgr(placement_manager, map_placement_mgr):
    if placement_manager is not None:
        return placement_manager
    return map_placement_mgr
def _pid_to_state(states):
    mapping = {}
    try:
        items = states.items()
    except Exception:
        return mapping
    for sid, provs in items:
        try:
            sid_int = int(sid)
        except Exception:
            continue
        try:
            iterable = list(provs)
        except Exception:
            continue
        for p in iterable:
            try:
                mapping[int(p)] = sid_int
            except Exception:
                continue
    return mapping
def _reviewed_building_lines(mgr, pid_to_state, map_h):
    lines = []
    try:
        records = mgr.list_buildings()
    except Exception:
        return []
    if not records:
        return []
    for rec in records:
        try:
            status = getattr(rec, "review_status", None)
        except Exception:
            continue
        if status not in _REVIEWED:
            continue
        try:
            prov = int(getattr(rec, "province_id"))
            btype = str(getattr(rec, "building_type"))
            x = float(getattr(rec, "x"))
            y = float(getattr(rec, "y"))
            rot = float(getattr(rec, "rotation", 0.0))
            h = float(getattr(rec, "height", 0.0))
            sid_raw = getattr(rec, "state_id", None)
        except Exception:
            continue
        if not btype:
            continue
        if prov <= 0:
            continue
        if sid_raw is None:
            sid = pid_to_state.get(prov)
        else:
            try:
                sid = int(sid_raw)
            except Exception:
                continue
        if sid is None:
            continue
        hoi4_z = float(map_h) - y
        lines.append(f"{int(sid)};{btype};{x:.2f};{h:.2f};{hoi4_z:.2f};{rot:.2f};{prov}")
    return lines
def _reviewed_port_lines(mgr, pid_to_state, map_h):
    lines = []
    try:
        records = mgr.list_ports()
    except Exception:
        return []
    if not records:
        return []
    for rec in records:
        try:
            status = getattr(rec, "review_status", None)
        except Exception:
            continue
        if status not in _REVIEWED:
            continue
        try:
            prov = int(getattr(rec, "province_id"))
            sea_raw = getattr(rec, "sea_province", None)
            x = float(getattr(rec, "x"))
            y = float(getattr(rec, "y"))
            rot = float(getattr(rec, "rotation", 0.0))
            h = float(getattr(rec, "height", 0.0))
        except Exception:
            continue
        if prov <= 0:
            continue
        if sea_raw is None:
            continue
        try:
            sea = int(sea_raw)
        except Exception:
            continue
        sid = pid_to_state.get(prov)
        if sid is None:
            continue
        hoi4_z = float(map_h) - y
        lines.append(f"{int(sid)};naval_base_spawn;{x:.2f};{h:.2f};{hoi4_z:.2f};{rot:.2f};{sea}")
    return lines
def write_buildings(states, province_map, tile_map, output_dir, sea_ids=None, land_to_sea=None, pid_count=None, sum_x=None, sum_y=None, placement_manager=None, map_placement_mgr=None, profile_name=None):
    """Write buildings.txt. Trailing placement args keep direct callers valid."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    n = int(province_map.max()) + 1
    map_h, map_w = province_map.shape
    mgr = _resolve_mgr(placement_manager, map_placement_mgr)
    is_foundation = (mgr is not None and profile_name == "foundation")
    is_compat = (mgr is not None and profile_name in _COMPAT_PROFILES)
    if is_foundation:
        pid_to_state = _pid_to_state(states)
        lines = []
        lines.extend(_reviewed_building_lines(mgr, pid_to_state, map_h))
        lines.extend(_reviewed_port_lines(mgr, pid_to_state, map_h))
        with open(os.path.join(d, "buildings.txt"), "wb") as f:
            f.write("\n".join(lines).encode("utf-8"))
        return set()
    if pid_count is None:
        flat_pm = province_map.ravel()
        pid_count = np.bincount(flat_pm, minlength=n)
        ys_grid, xs_grid = np.mgrid[0:map_h, 0:map_w]
        sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)
    if land_to_sea is None:
        land_to_sea = build_coastal_land_to_sea(tile_map, province_map)
    pid_to_state = {}
    for sid, provs in states.items():
        for p in provs:
            pid_to_state[int(p)] = sid
    lines = []
    REQUIRED_STATE_ENTITIES = (
        "arms_factory", "industrial_complex", "air_base",
        "anti_air_building", "bunker", "fuel_silo", "radar_station",
        "nuclear_reactor_spawn", "rocket_site_spawn", "synthetic_refinery",
        "supply_node",
    )
    COASTAL_STATE_ENTITIES = ("dockyard", "coastal_bunker")
    coastal_states = set()
    for land_pid in (land_to_sea or {}):
        s = pid_to_state.get(land_pid)
        if s is not None:
            coastal_states.add(s)
    for sid, provs in states.items():
        if not provs:
            continue
        valid_centroids = []
        for p in provs:
            if p < n and pid_count[p] > 0:
                cx_p, cy_p = _safe_coord(p, province_map, pid_count, sum_x, sum_y)
                iy, ix = int(round(cy_p)), int(round(cx_p))
                if 0 <= iy < map_h and 0 <= ix < map_w and tile_map[iy, ix] == TILE_LAND:
                    valid_centroids.append((ix + 0.5, iy + 0.5))
        if not valid_centroids:
            pid = provs[0]
            if pid >= n or pid_count[pid] == 0:
                continue
            cx, cy = _safe_coord(pid, province_map, pid_count, sum_x, sum_y)
            iy, ix = int(round(cy)), int(round(cx))
            if not (0 <= iy < map_h and 0 <= ix < map_w and tile_map[iy, ix] == TILE_LAND):
                ys, xs = np.where((province_map == pid) & (tile_map == TILE_LAND))
                if len(ys) == 0:
                    continue
                iy, ix = int(ys[0]), int(xs[0])
            valid_centroids = [(ix + 0.5, iy + 0.5)]
        btypes = list(REQUIRED_STATE_ENTITIES)
        if sid in coastal_states:
            btypes.extend(COASTAL_STATE_ENTITIES)
        for i, btype in enumerate(btypes):
            cx_b, cy_b = valid_centroids[i % len(valid_centroids)]
            hoi4_y = map_h - cy_b
            lines.append(
                f"{sid};{btype};{cx_b:.2f};11.00;{hoi4_y:.2f};0.00;0"
            )
    h_map, w_map = province_map.shape
    failed_coastal = set()
    for land_pid, sea_pid in land_to_sea.items():
        sid = pid_to_state.get(land_pid)
        if sid is None:
            continue
        if land_pid >= n or pid_count[land_pid] == 0:
            continue
        valid_ys, valid_xs = np.where(
            (province_map == land_pid) & (tile_map == TILE_LAND)
        )
        if len(valid_ys) == 0:
            failed_coastal.add(land_pid)
            continue
        cx_centroid, cy_centroid = _safe_coord(
            land_pid, province_map, pid_count, sum_x, sum_y)
        dist = (valid_ys.astype(float) - cy_centroid) ** 2 + (valid_xs.astype(float) - cx_centroid) ** 2
        best = int(np.argmin(dist))
        iy, ix = int(valid_ys[best]), int(valid_xs[best])
        cx_out = ix + 0.5
        cy_out = iy + 0.5
        hoi4_y = map_h - cy_out
        lines.append(
            f"{sid};naval_base_spawn;{cx_out:.2f};11.00;{hoi4_y:.2f};0.00;{sea_pid}"
        )
    if not lines:
        lines.append("1;bunker;100.00;11.00;100.00;0.00;0")
    if is_compat:
        pid_to_state_extra = _pid_to_state(states)
        extra = []
        extra.extend(_reviewed_building_lines(mgr, pid_to_state_extra, map_h))
        extra.extend(_reviewed_port_lines(mgr, pid_to_state_extra, map_h))
        if extra:
            existing = set(lines)
            for item in extra:
                if item not in existing:
                    lines.append(item)
                    existing.add(item)
        marker = _COMPAT_MARKER.format(profile=profile_name)
        with open(os.path.join(d, "buildings.txt"), "wb") as f:
            if lines:
                f.write((marker + "\n" + "\n".join(lines)).encode("utf-8"))
            else:
                f.write(marker.encode("utf-8"))
        return failed_coastal
    with open(os.path.join(d, "buildings.txt"), "wb") as f:
        f.write("\n".join(lines).encode("utf-8"))
    return failed_coastal
def write_empty_unitstacks(output_dir):
    """Write safe map entity files and the cosmetic city configuration."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    for name in (
        "unitstacks.txt",
        "airports.txt",
        "rocket_sites.txt",
    ):
        open(os.path.join(d, name), "w").close()
    from export.writers.map.cities_bmp import write_cities_txt
    write_cities_txt(output_dir)
