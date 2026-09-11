"""entity files such as buildings.txt / unitstacks.txt."""
import os
import numpy as np
from data.constants import (
    TILE_LAND, TILE_SEA,
    VALID_3D_BUILDING_TYPES,
)
# Do not import MAP_WIDTH/HEIGHT — always use province_map.shape to get dynamic dimensions.
from domain.validators.province import get_coastal_provinces, build_coastal_land_to_sea


from export.writers.map._coords import safe_coord as _safe_coord


def write_buildings(states, province_map, tile_map, output_dir, sea_ids=None,
                    land_to_sea=None,
                    pid_count=None, sum_x=None, sum_y=None):
    """Write buildings.txt.
    If the precalculated land_to_sea/pid_count/sum_x/sum_y is passed in, use it directly; otherwise, calculate it yourself."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)

    n = int(province_map.max()) + 1
    # Use actual array shape, cannot use global MAP_WIDTH/HEIGHT (user may choose other sizes)
    map_h, map_w = province_map.shape

    # Use precomputed data, or calculate the centroid yourself
    if pid_count is None:
        flat_pm = province_map.ravel()
        pid_count = np.bincount(flat_pm, minlength=n)
        ys_grid, xs_grid = np.mgrid[0:map_h, 0:map_w]
        sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)

    # Use precomputed land_to_sea, or calculate it yourself
    # **Key**: Must be fully synchronized with the coastal field of definition.csv - anything marked as
    # Provinces with coastal=true must have naval_base_spawn here, otherwise HOI4 will crash when entering the map.
    # (map.cpp:1628 "coastal but has no port building")
    if land_to_sea is None:
        land_to_sea = build_coastal_land_to_sea(tile_map, province_map)

    pid_to_state = {}
    for sid, provs in states.items():
        for p in provs:
            pid_to_state[int(p)] = sid

    # Each state must have 3D positions of all building types, otherwise HOI4 initialization divide-by-zero crashes
    lines = []
    # Building locations required by all states
    REQUIRED_STATE_ENTITIES = (
        "arms_factory", "industrial_complex", "air_base",
        "anti_air_building", "bunker", "fuel_silo", "radar_station",
        "nuclear_reactor_spawn", "rocket_site_spawn", "synthetic_refinery",
        "supply_node",
    )
    # Coastal states additional building locations required
    COASTAL_STATE_ENTITIES = ("dockyard", "coastal_bunker")

    # Collect which states are coastal
    coastal_states = set()
    for land_pid in (land_to_sea or {}):
        s = pid_to_state.get(land_pid)
        if s is not None:
            coastal_states.add(s)

    for sid, provs in states.items():
        if not provs:
            continue

        # BUG-5 fix v2: disperse buildings to different land province centers within state
        # (v1 uses spiral offset to push the building to the adjacent state / sea mile, mapbuildings.cpp:716/679 error → has been rolled back)
        # Collect the security center coordinates of all legal land provinces in the state
        valid_centroids: list[tuple[float, float]] = []
        for p in provs:
            if p < n and pid_count[p] > 0:
                cx_p, cy_p = _safe_coord(p, province_map, pid_count, sum_x, sum_y)
                iy, ix = int(round(cy_p)), int(round(cx_p))
                # Strictly verify that coordinates fall on LAND pixels (avoid mapbuildings.cpp:679 not over land)
                if 0 <= iy < map_h and 0 <= ix < map_w and tile_map[iy, ix] == TILE_LAND:
                    # Write the centre of the validated pixel, not a floating
                    # centroid near a pixel edge.  The engine floors building
                    # coordinates when it checks the terrain below them.
                    valid_centroids.append((ix + 0.5, iy + 0.5))

        # No legal land center: fall back to the old logic (provs[0] center, not dispersed but guaranteed to have coordinates)
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
        # Each building is assigned to the center of a land province in turn (does not cross the state, does not enter the sea)
        for i, btype in enumerate(btypes):
            cx_b, cy_b = valid_centroids[i % len(valid_centroids)]
            hoi4_y = map_h - cy_b
            lines.append(
                f"{sid};{btype};{cx_b:.2f};11.00;{hoi4_y:.2f};0.00;0"
            )

    # Only write naval_base_spawn for truly coastal provinces
    # Key: HOI4 uses the floor method to convert the coordinates back to the pixel index to determine "over the land". If the coordinates are just right
    # falls on a pixel boundary (e.g. x=2778.93 → floor to pixel 2778, while land pixel is 2779),
    # Will be sentenced to neighbor sea pixel → "not over the land" → port ignore → province coastal
    # But no port → HOI4 crash (map.cpp:1628)
    # Countermeasure: Always round **integer pixels + 0.5** (pixel center) to make the rounding direction stable.
    h_map, w_map = province_map.shape
    failed_coastal: set[int] = set()
    for land_pid, sea_pid in land_to_sea.items():
        sid = pid_to_state.get(land_pid)
        if sid is None:
            continue
        if land_pid >= n or pid_count[land_pid] == 0:
            continue
        # First choice: the closest legal land pixel to the center of mass (province_map==pid AND tile_map==LAND)
        # Do not use the center of mass of _safe_coord directly, because the center of mass may be on the sea or boundary
        valid_ys, valid_xs = np.where(
            (province_map == land_pid) & (tile_map == TILE_LAND)
        )
        if len(valid_ys) == 0:
            failed_coastal.add(land_pid)
            continue
        cx_centroid, cy_centroid = _safe_coord(
            land_pid, province_map, pid_count, sum_x, sum_y)
        dist = (valid_ys.astype(float) - cy_centroid) ** 2 + \
               (valid_xs.astype(float) - cx_centroid) ** 2
        best = int(np.argmin(dist))
        iy, ix = int(valid_ys[best]), int(valid_xs[best])
        # Use **pixel center** (integer + 0.5) when writing coordinates to avoid HOI4 rounding falling outside the boundary
        cx_out = ix + 0.5
        cy_out = iy + 0.5
        hoi4_y = map_h - cy_out
        lines.append(
            f"{sid};naval_base_spawn;{cx_out:.2f};11.00;{hoi4_y:.2f};0.00;{sea_pid}"
        )

    if not lines:
        lines.append("1;bunker;100.00;11.00;100.00;0.00;0")

    with open(os.path.join(d, "buildings.txt"), "wb") as f:
        f.write("\n".join(lines).encode("utf-8"))

    return failed_coastal


def write_empty_unitstacks(output_dir):
    """Write safe map entity files and the cosmetic city configuration.

    Unit/airport/rocket files reference vanilla province IDs, so those files
    are intentionally empty for a generated map. ``cities.txt`` is different:
    it describes the meshes used by ``cities.bmp`` and must not be empty.
    """
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    # adjacency_rules.txt is written separately by writers/map/adjacency_rules.py. An empty file is no longer created here.
    for name in (
        "unitstacks.txt",
        "airports.txt",
        "rocket_sites.txt",
    ):
        open(os.path.join(d, name), "w").close()

    # cities.txt: Include the city_group meshes so Urban pixels render models.
    from export.writers.map.cities_bmp import write_cities_txt

    write_cities_txt(output_dir)
