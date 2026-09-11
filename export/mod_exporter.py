"""MOD Complete Exporter — Generate a complete and usable HOI4 MOD with one click
Reference file structure of KR (Kaiserreich)"""
import os
import struct
import numpy as np

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_SEA, TILE_LAKE,
    OCEAN_HEIGHT, LAND_BASE_HEIGHT, SEA_LEVEL,
    DEFAULT_MOD_NAME,
)
from data.terrain_types import TERRAIN_PALETTE_INDEX, DEFAULT_TERRAIN_FOR_TILE
from domain.generators.province import generate_province_colors
from export.bmp_writer import (
    write_provinces_bmp, write_heightmap_bmp,
    write_terrain_bmp, write_rivers_bmp,
)


def export_full_mod(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    output_dir: str,
    mod_name: str = DEFAULT_MOD_NAME,
    tag: str = "AAA",
    state_mgr=None,
    country_mgr=None,
    river_map: np.ndarray | None = None,
    terrain_map: np.ndarray | None = None,
    height_map: np.ndarray | None = None,
    continent_mgr=None,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    colormap_settings=None,
    default_map_settings=None,
    adjacency_rule_mgr=None,
    strategic_region_mgr=None,
    provincial_terrain: dict[int, str] | None = None,
    scope: dict[str, bool] | None = None,
    assets: dict[str, bytes] | None = None,
    dirty_assets: set[str] | None = None,
) -> None:
    """Export complete MOD in one click. scope controls the export scope, None=export all.

    assets/dirty_assets: Art asset system. The imported MOD original art files are saved in assets.
    Assets that have not been edited and triggered dirty will be directly written back to the original bytes during export (the original art will be retained)."""
    if assets is None:
        assets = {}
    if dirty_assets is None:
        dirty_assets = set()
    if int(province_map.max()) == 0:
        raise ValueError("No province data; generate provinces first")

    # Defensive refresh of global sizes: The user may have loaded a non-default size item but not triggered set_map_size,
    # Or some writers import MAP_* at the top of the file and have bound old values (lazy import ones will refresh)
    from data.constants import set_map_size as _set_map_size
    _set_map_size(province_map.shape[1], province_map.shape[0])

    # scope is all enabled by default
    if scope is None:
        scope = {}
    def _enabled(key: str) -> bool:
        return scope.get(key, True)

    # Clean up detritus provinces < 8 pixels and merge into the largest adjacent province (repair only).
    # Must be done before compaction: the swallowing of debris itself will create new ID cavities
    province_map = _merge_tiny_provinces(province_map, min_pixels=8)

    # The engine rejects a province box that reaches one eighth of the map
    # dimension.  Repair the export copy only, preserving the project and all
    # province IDs referenced by states/regions.  This also catches the
    # exact-boundary case that the older pre-export validator missed.
    repaired_bbox_ids = _repair_too_large_provinces(province_map, tile_map)
    if repaired_bbox_ids:
        print(
            "  [province bbox] Trimmed boundary pixels from "
            f"{len(repaired_bbox_ids)} province(s): "
            + ", ".join(str(pid) for pid in repaired_bbox_ids)
        )

    # Compact province ID (optional, it is recommended to turn it off when importing MOD to retain the original ID).
    # Only applies to exported copies: province_map has been copied in the previous step and refers to the province ID.
    # Manager renumbers after deep copying - the project itself (including undo history) is not affected.
    # Even if the IDs are consecutive, run: mapping and clear dead references to deleted provinces.
    if _enabled("compact_ids"):
        import copy as _copy
        state_mgr = _copy.deepcopy(state_mgr)
        country_mgr = _copy.deepcopy(country_mgr)
        strategic_region_mgr = _copy.deepcopy(strategic_region_mgr)
        continent_mgr = _copy.deepcopy(continent_mgr)
        adjacency_mgr = _copy.deepcopy(adjacency_mgr)
        railway_mgr = _copy.deepcopy(railway_mgr)
        supply_mgr = _copy.deepcopy(supply_mgr)
        adjacency_rule_mgr = _copy.deepcopy(adjacency_rule_mgr)
        from domain.map_data import MapData as _MD
        _tmp = _MD.__new__(_MD)
        _tmp.province_map = province_map
        _tmp.tile_map = tile_map
        _tmp.provincial_terrain = dict(provincial_terrain) if provincial_terrain else {}
        _tmp.compact_with_references(
            state_mgr=state_mgr, country_mgr=country_mgr,
            strategic_region_mgr=strategic_region_mgr,
            continent_mgr=continent_mgr, adjacency_mgr=adjacency_mgr,
            railway_mgr=railway_mgr, supply_mgr=supply_mgr,
            adjacency_rule_mgr=adjacency_rule_mgr,
        )
        provincial_terrain = _tmp.provincial_terrain
    province_count = int(province_map.max())

    colors = generate_province_colors(province_count)

    # Vectorize classified provinces (land/ocean/lake) to avoid scanning the entire map province by province
    land_ids, sea_ids, lake_ids = _classify_provinces_fast(
        province_count, province_map, tile_map
    )

    # === Synchronize tile_map to province category ===
    # _classify_provinces_fast classifies provinces according to "pixel majority voting", there must be a small number of pixels
    # tile ≠ province type (example: 60% LAND+40% SEA province is classified as land, but that
    # 40% SEA pixels in tile_map are still SEA). If not synchronized:
    # - Buildings writer uses tile_map for coordinate verification, and cannot find LAND pixels → Wrong coordinates are written
    # - HOI4 determines coastal by looking at provinces.bmp + type, which is different from tile_map.
    # Guaranteed after synchronization: tile_map[y,x] type = pid_map[y,x] type of the province to which it belongs
    _sync_tile_with_province_class(tile_map, province_map, land_ids, sea_ids, lake_ids)

    # === BMP files ===
    write_provinces_bmp(province_map, output_dir, colors)

    # Height map: User-edited ones are given priority, otherwise they are automatically generated.
    if height_map is not None and int(height_map.max()) != int(height_map.min()):
        heightmap = height_map
    else:
        heightmap = _gen_heightmap(tile_map)
    write_heightmap_bmp(heightmap, output_dir)

    # Topographic maps: user-edited terrain is preferred when it contains data;
    # otherwise derive one map and use that same map for every visual raster.
    # Keeping terrain.bmp, trees.bmp, cities.bmp, and the colormap in sync is
    # important: previously cities.bmp received ``None`` even when terrain.bmp
    # had been generated as a fallback, and an all-zero terrain layer was used
    # for trees/colormap.
    if terrain_map is not None and int(terrain_map.max()) > 0:
        terrain_for_export = terrain_map
        _sync_terrain_with_tile(terrain_for_export, tile_map)
    else:
        terrain_for_export = _gen_terrain(tile_map)
    write_terrain_bmp(terrain_for_export, output_dir)

    write_rivers_bmp(output_dir, river_map, shape=tile_map.shape)
    # trees.bmp: Automatically generate tree distribution from terrain_map (A8)
    from export.writers.map.trees_bmp import (
        write_trees_bmp as _write_trees_new,
        auto_generate_tree_map,
    )
    _tree_map = auto_generate_tree_map(terrain_for_export)
    _write_trees_new(output_dir, tree_map=_tree_map)
    # cities.bmp: Generate city markers from urban terrain (Feature 11)
    from export.writers.map.cities_bmp import write_cities_bmp as _write_cities_new
    _write_cities_new(output_dir, terrain_map=terrain_for_export)
    # world_normal.bmp — normal map, can be replaced by the imported original version
    from export.asset_helper import write_or_restore
    write_or_restore(
        "map/world_normal.bmp", output_dir, assets, dirty_assets,
        lambda: _write_normal_map(heightmap, output_dir),
    )

    # colormap_rgb_cityemissivemask_a.dds strategic perspective overview map
    # (Without coverage you will see the vanilla Earth continent)
    from export.writers.map.colormap_dds import write_colormap_dds
    write_or_restore(
        "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        output_dir, assets, dirty_assets,
        lambda: write_colormap_dds(tile_map, output_dir, settings=colormap_settings,
                                   terrain_map=terrain_for_export, height_map=heightmap),
    )

    # colormap_water_0/1/2.dds Ocean shading map - three MIPs are considered a group
    from export.writers.map.colormap_dds import write_water_colormap_dds

    def _gen_water_colormap():
        write_water_colormap_dds(tile_map, output_dir)

    # As long as one MIP is clean, use the entire set of original bytes; otherwise regenerate three
    water_paths = [
        "map/terrain/colormap_water_0.dds",
        "map/terrain/colormap_water_1.dds",
        "map/terrain/colormap_water_2.dds",
    ]
    all_water_clean = all(
        p in assets and p not in dirty_assets for p in water_paths
    )
    if all_water_clean:
        for p in water_paths:
            write_or_restore(p, output_dir, assets, dirty_assets, lambda: None)
    else:
        _gen_water_colormap()

    # fow_rgb_waterspec_a.dds fog of war light and shade + water reflection
    # (Not covering it will fall back to the vanilla earth shape map → reflection/fog will follow the distribution of the earth's sea and land)
    from export.writers.map.colormap_dds import write_fow_dds
    write_or_restore(
        "map/terrain/fow_rgb_waterspec_a.dds",
        output_dir, assets, dirty_assets,
        lambda: write_fow_dds(tile_map, output_dir, height_map=heightmap),
    )

    # ambient_object.txt — map border (frame_border_top/bottom blocks the top and bottom spaces)
    from export.writers.map.ambient_object import write_ambient_object_txt
    write_ambient_object_txt(output_dir)

    # seasons.txt — Visual definition of seasons (required, otherwise it will crash)
    _write_seasons_txt(output_dir)

    # default.map engine configuration file (A3, users can adjust tree palette / river_max_level through the menu)
    from export.writers.map.default_map import write_default_map
    write_default_map(
        output_dir,
        settings=default_map_settings,
        province_count=int(province_map.max()),
    )

    # Terrain was synchronized before the visual rasters were written above.
    # === Calculate coastline in one go (shared by definition.csv + buildings.txt) ===
    # **Provincial adjacency** determination - exactly the same as HOI4 (determined according to the type field of definition.csv)
    # Cannot use tile_map pixel-level determination, because _classify_provinces_fast votes by pixel majority
    # Classification, not equivalent to tile_map pixel-level adjacency → HOI4 determines coastal but buildings.txt does not
    # Write port → "Province X coastal but no port" → start_game crashes
    coastal_set, land_to_sea = _compute_coastal_once(province_map, land_ids, sea_ids)

    # definition.csv is deferred to be written after states are built (coastal must be aligned with buildings)
    _write_continent(output_dir, continent_mgr=continent_mgr)
    # Adjacencies: If there is user data, use a new writer, otherwise the write only contains header+sentinel
    if adjacency_mgr is not None and adjacency_mgr.count() > 0:
        from export.writers.map.adjacencies import write_adjacencies_csv
        write_adjacencies_csv(output_dir, adjacency_mgr=adjacency_mgr)
    else:
        _write_adjacencies(output_dir)

    # adjacency_rules.txt (A6, Strait Passage Rules)
    from export.writers.map.adjacency_rules import write_adjacency_rules_txt
    write_adjacency_rules_txt(output_dir, rule_mgr=adjacency_rule_mgr)

    # === Precomputed centroid (one-time, shared by all subsequent writers) ===
    flat_pm_g = province_map.ravel()
    n_g = province_count + 1
    pid_count_g = np.bincount(flat_pm_g, minlength=n_g)
    h_g, w_g = province_map.shape
    ys_g, xs_g = np.mgrid[0:h_g, 0:w_g]
    sum_y_g = np.bincount(flat_pm_g, weights=ys_g.ravel().astype(np.float64), minlength=n_g)
    sum_x_g = np.bincount(flat_pm_g, weights=xs_g.ravel().astype(np.float64), minlength=n_g)
    del ys_g, xs_g  # Free ~175MB

    # === First finalize states + orphan land and province for adoption ===
    # HOI4 requires that each land province belongs to a state, otherwise MAP_ERROR "land province has no state"
    land_id_set = set(land_ids)
    if state_mgr and state_mgr.states:
        states = {}
        for sid, s in state_mgr.states.items():
            land_provs = [p for p in s.provinces if p in land_id_set]
            if land_provs:
                states[sid] = land_provs

        # Orphan adoption: treat _classify_provinces_fast as land but not in any state province
        # assigned to the geographically closest state
        all_in_states = set()
        for provs in states.values():
            all_in_states.update(provs)
        orphans = [p for p in land_ids if p not in all_in_states]
        if orphans:
            state_centers = {}
            for sid, provs in states.items():
                tx = ty = tw = 0.0
                for p in provs:
                    if p < n_g and pid_count_g[p] > 0:
                        tx += sum_x_g[p]; ty += sum_y_g[p]; tw += pid_count_g[p]
                if tw > 0:
                    state_centers[sid] = (ty / tw, tx / tw)
            for orphan in orphans:
                if orphan >= n_g or pid_count_g[orphan] == 0:
                    continue
                ocy = sum_y_g[orphan] / pid_count_g[orphan]
                ocx = sum_x_g[orphan] / pid_count_g[orphan]
                best_sid = min(
                    state_centers,
                    key=lambda s: (state_centers[s][0]-ocy)**2 + (state_centers[s][1]-ocx)**2,
                )
                states[best_sid].append(orphan)
                if state_mgr.get_state(best_sid):
                    state_mgr.get_state(best_sid).provinces.append(orphan)
            print(f"  [orphan adoption] Assigned {len(orphans)} orphaned land provinces")
    else:
        states = None  # Use region to split the state later

    # === Filter coastal: Only keep provinces that are indeed in states ===
    # buildings.txt only writes naval_base_spawn for the coastal province in pid_to_state,
    # definition.csv's coastal must be perfectly aligned with it, otherwise HOI4 crashes:
    # "Province X is setup as coastal but has no port building"
    if states is not None:
        all_state_pids = set()
        for provs in states.values():
            all_state_pids.update(provs)
        # **Orphan coastal land provinces are converted to sea** — HOI4’s coastal determination is based on CSV
        # land-adjacent-to-sea, so these land provinces without state must become sea, otherwise
        # HOI4 will recognize them as coastal but buildings.txt has no port → crash
        orphan_coastal = {p for p in coastal_set if p not in all_state_pids}
        if orphan_coastal:
            land_ids = [p for p in land_ids if p not in orphan_coastal]
            sea_ids = sorted(set(sea_ids) | orphan_coastal)
            coastal_set -= orphan_coastal
            print(f"  [coastal] Converted {len(orphan_coastal)} coastal provinces without a state to sea")
        land_to_sea = {p: s for p, s in land_to_sea.items() if p in coastal_set}

    # definition.csv is deferred to be written after buildings (needs the coordinate verification results of buildings)

    # === Strategic Areas ===
    region_list = None
    if _enabled("strategic_regions"):
        if strategic_region_mgr is not None and strategic_region_mgr.count() > 0:
            from export.writers.map.strategic_regions import (
                write_strategic_regions_from_mgr, write_weatherpositions,
            )
            region_list = write_strategic_regions_from_mgr(strategic_region_mgr, output_dir)
            write_weatherpositions(region_list, province_map, output_dir)
        else:
            region_list = _write_strategic_regions(
                province_map, tile_map, output_dir, states_dict=states
            )
            _write_weatherpositions(region_list, province_map, output_dir)

    # === Write state file ===
    if _enabled("states"):
        if state_mgr and state_mgr.states:
            _write_states_from_mgr(state_mgr, country_mgr, province_map, output_dir, tile_map,
                                   land_id_set=land_id_set, coastal_set=coastal_set)
        else:
            if region_list is not None:
                states = _split_states_by_region(region_list, set(land_ids))
            if states is not None:
                _write_states(states, tag, province_map, output_dir)

    # === Supply System ===
    if _enabled("supply") and states is not None:
        if supply_mgr is not None and supply_mgr.count() > 0:
            from export.writers.map.supply_nodes import write_supply_nodes_txt
            write_supply_nodes_txt(output_dir, supply_mgr=supply_mgr)
        else:
            _write_supply_nodes(states, province_map, output_dir)

        if railway_mgr is not None and railway_mgr.count() > 0:
            from export.writers.map.railways import write_railways_txt
            write_railways_txt(output_dir, railway_mgr=railway_mgr, province_map=province_map)
        else:
            _write_railways(states, province_map, output_dir)
        _write_supply_areas(states, output_dir)

    # === map file (BMP has been written, write the remaining map configuration here) ===
    if _enabled("map"):
        failed_coastal = _write_buildings(states, province_map, tile_map, output_dir, sea_ids,
                         land_to_sea=land_to_sea,
                         pid_count=pid_count_g, sum_x=sum_x_g, sum_y=sum_y_g)
        if failed_coastal:
            # These coastal provinces whose coordinates are unreliable must be changed from CSV land to sea,
            # Otherwise HOI4 will re-detect coastal but buildings.txt has no port → crash
            coastal_set -= failed_coastal
            land_ids = [p for p in land_ids if p not in failed_coastal]
            sea_ids = sorted(set(sea_ids) | failed_coastal)
            print(f"  [coastal] Converted {len(failed_coastal)} coastal provinces with unreliable coordinates to sea")

        _write_definition_csv(province_count, colors, province_map, tile_map, output_dir,
                              land_ids, sea_ids, lake_ids, continent_mgr=continent_mgr,
                              terrain_map=terrain_map,
                              provincial_terrain=provincial_terrain,
                              coastal_set=coastal_set)
        _write_empty_unitstacks(output_dir)
        _write_positions(province_map, tile_map, output_dir,
                         pid_count=pid_count_g, sum_x=sum_x_g, sum_y=sum_y_g)

    # === Country ===
    if _enabled("countries"):
        if country_mgr and country_mgr.countries:
            _write_countries_from_mgr(country_mgr, output_dir, states)
        else:
            first_state_id = min(states.keys()) if states else 1
            _write_country(tag, first_state_id, output_dir)

    # === Flag ===
    if _enabled("gfx"):
        all_tags = list(country_mgr.countries.keys()) if country_mgr and country_mgr.countries else [tag]
        _write_country_flags(all_tags, output_dir, country_mgr)

    # === Localization ===
    if _enabled("localisation"):
        region_count = len(region_list) if region_list else 24
        _write_localisation_full(mod_name, state_mgr, country_mgr, states, output_dir,
                                 region_count=region_count,
                                 region_mgr=strategic_region_mgr)

    # === Bookmark ===
    if _enabled("countries"):
        country_tags = list(country_mgr.countries.keys()) if country_mgr and country_mgr.countries else [tag]
        _write_bookmark(mod_name, country_tags, output_dir)

    # === NDefines override (prevents AI divide-by-zero crashes) ===
    from export.writers.common.defines import write_defines_lua
    write_defines_lua(output_dir, province_count=province_count)

    # === descriptor (independent switch - users who already have their own MOD framework can turn it off and only take the content files) ===
    if _enabled("descriptor"):
        _write_descriptor(mod_name, output_dir)

    # === replace_path directory ===
    if _enabled("replace_path"):
        from export.writers.replace_path.scrubber import (
            write_ai_strategy_overrides,
            write_replace_path_dirs,
        )
        write_replace_path_dirs(output_dir)
        write_ai_strategy_overrides(output_dir)

    # === Post-export verification (only checks files with enabled modules) ===
    if _enabled("map"):
        _verify_non_empty(output_dir, scope)


def _verify_non_empty(output_dir, scope=None):
    """Verify that the key file exists and is not empty. Only files with enabled modules are checked."""
    _s = scope or {}
    def _on(key): return _s.get(key, True)

    critical_files = [
        "map/definition.csv",
        "map/provinces.bmp",
        "map/heightmap.bmp",
        "map/terrain.bmp",
        "map/rivers.bmp",
        "map/trees.bmp",
        "map/continent.txt",
        "map/buildings.txt",
    ]
    if _on("supply"):
        critical_files += ["map/supply_nodes.txt", "map/railways.txt"]
    missing = []
    for rel in critical_files:
        p = os.path.join(output_dir, rel)
        if not os.path.isfile(p) or os.path.getsize(p) == 0:
            missing.append(rel)
    if missing:
        raise RuntimeError(
            "Post-export validation failed: the following critical files are missing or empty (HOI4 may crash):\n  - "
            + "\n  - ".join(missing)
        )

    # At least one strategicregion and one state
    sr_dir = os.path.join(output_dir, "map", "strategicregions")
    if not os.path.isdir(sr_dir) or not any(
        f.endswith(".txt") for f in os.listdir(sr_dir)
    ):
        raise RuntimeError("map/strategicregions/ is empty — at least one strategic region is required")
    st_dir = os.path.join(output_dir, "history", "states")
    if not os.path.isdir(st_dir) or not any(
        f.endswith(".txt") for f in os.listdir(st_dir)
    ):
        raise RuntimeError("history/states/ is empty — at least one state is required")


def _compute_coastal_province_level(province_map, land_ids, sea_ids):
    """Compute coastal land province sets using province-level adjacency (internally consistent with HOI4).
    Any land province is considered coastal as long as it is adjacent to a sea province pixel on the pixel map."""
    n = int(province_map.max()) + 1
    is_land = np.zeros(n, dtype=bool)
    is_sea = np.zeros(n, dtype=bool)
    for lp in land_ids:
        if lp < n:
            is_land[int(lp)] = True
    for sp in sea_ids:
        if sp < n:
            is_sea[int(sp)] = True

    coastal = set()
    # horizontal adjacency
    left = province_map[:, :-1].ravel()
    right = province_map[:, 1:].ravel()
    m1 = is_land[left] & is_sea[right]
    m2 = is_sea[left] & is_land[right]
    if m1.any():
        coastal.update(int(x) for x in np.unique(left[m1]))
    if m2.any():
        coastal.update(int(x) for x in np.unique(right[m2]))
    # The game wraps horizontally, so the two bitmap edges are neighbours.
    wrap_lr = province_map[:, -1]
    wrap_rl = province_map[:, 0]
    m_wrap_lr = is_land[wrap_lr] & is_sea[wrap_rl]
    m_wrap_rl = is_sea[wrap_lr] & is_land[wrap_rl]
    if m_wrap_lr.any():
        coastal.update(int(x) for x in np.unique(wrap_lr[m_wrap_lr]))
    if m_wrap_rl.any():
        coastal.update(int(x) for x in np.unique(wrap_rl[m_wrap_rl]))
    # vertical adjacency
    up = province_map[:-1, :].ravel()
    down = province_map[1:, :].ravel()
    m3 = is_land[up] & is_sea[down]
    m4 = is_sea[up] & is_land[down]
    if m3.any():
        coastal.update(int(x) for x in np.unique(up[m3]))
    if m4.any():
        coastal.update(int(x) for x in np.unique(down[m4]))
    return coastal


def _compute_coastal_once(province_map, land_ids, sea_ids):
    """Calculate coastline data in one go and return (coastal_set, land_to_sea).
    coastal_set: Coastal land province ID set
    land_to_sea: {land_pid: sea_pid} An adjacent sea province corresponding to each coastal land province
    Shared by definition.csv (coastal fields) and buildings.txt (naval_base_spawn)."""
    n = int(province_map.max()) + 1
    is_land = np.zeros(n, dtype=bool)
    is_sea = np.zeros(n, dtype=bool)
    for lp in land_ids:
        if lp < n:
            is_land[int(lp)] = True
    for sp in sea_ids:
        if sp < n:
            is_sea[int(sp)] = True

    coastal_set: set[int] = set()
    land_to_sea: dict[int, int] = {}

    def _scan_dir(land_pm, sea_pm):
        """Scan land-sea adjacencies in one direction, pure numpy without Python loops."""
        land_arr = land_pm.ravel()
        sea_arr = sea_pm.ravel()
        m = is_land[land_arr] & is_sea[sea_arr]
        if not m.any():
            return
        lp_hits = land_arr[m]
        sp_hits = sea_arr[m]
        # Use unique to get only the first sea_pid of each land_pid
        _, first_idx = np.unique(lp_hits, return_index=True)
        for i in first_idx:
            lp = int(lp_hits[i])
            coastal_set.add(lp)
            if lp not in land_to_sea:
                land_to_sea[lp] = int(sp_hits[i])

    # 4 directions
    _scan_dir(province_map[:, :-1], province_map[:, 1:])   # right
    _scan_dir(province_map[:, 1:], province_map[:, :-1])   # left
    # The Clausewitz map wraps horizontally: the left and right bitmap edges
    # are neighbours.  Omitting this pair marks edge provinces coastal in the
    # game but leaves them without a naval_base_spawn, which can crash during
    # map initialisation.
    _scan_dir(province_map[:, -1:], province_map[:, :1])   # right edge -> left edge
    _scan_dir(province_map[:, :1], province_map[:, -1:])   # left edge -> right edge
    _scan_dir(province_map[:-1, :], province_map[1:, :])   # down
    _scan_dir(province_map[1:, :], province_map[:-1, :])   # on

    return coastal_set, land_to_sea


# ────────────────── definition.csv ──────────────────

def _write_definition_csv(count, colors, pm, tm, output_dir,
                          land_ids=None, sea_ids=None, lake_ids=None,
                          continent_mgr=None, terrain_map=None,
                          provincial_terrain=None,
                          coastal_set=None):
    """Write definition.csv."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)

    # Pre-built type lookup table
    type_map = {}
    if land_ids is not None and sea_ids is not None and lake_ids is not None:
        for pid in land_ids:
            type_map[pid] = "land"
        for pid in sea_ids:
            type_map[pid] = "sea"
        for pid in lake_ids:
            type_map[pid] = "lake"

    if coastal_set is None:
        coastal_set = set()

    # Batch precalculate the main terrain types of all provinces (one pass, no province-by-province scanning)
    dominant_terrain = _batch_resolve_terrain(
        count, pm, terrain_map, provincial_terrain)

    with open(os.path.join(d, "definition.csv"), "w", encoding="utf-8") as f:
        f.write("0;0;0;0;sea;false;ocean;0\n")
        for pid in range(1, count + 1):
            r, g, b = colors.get(pid, (1, 1, 1))
            ptype = type_map.get(pid, "sea")
            if ptype == "land":
                terrain = dominant_terrain[pid]
                if continent_mgr is not None:
                    cont = continent_mgr.get_province_continent_hoi4_id(pid, True)
                    if cont <= 0:
                        cont = 1
                else:
                    cont = 1
                coastal = "true" if pid in coastal_set else "false"
            elif ptype == "lake":
                terrain = "lakes"
                cont = 0
                coastal = "false"
            else:
                terrain = "ocean"
                cont = 0
                coastal = "false"
            f.write(f"{pid};{r};{g};{b};{ptype};{coastal};{terrain};{cont}\n")


def _batch_resolve_terrain(province_count, province_map, terrain_map,
                           provincial_terrain=None):
    """Batch calculation of the main terrain types for all provinces.
    Return list, index = province ID, value = terrain string.
    One np.add.at pass, replacing the previous province-by-province full map scan."""
    from data.terrain_types import PALETTE_TO_TYPE

    result = ["plains"] * (province_count + 1)

    # Explicitly set priority
    if provincial_terrain:
        for pid, ttype in provincial_terrain.items():
            if pid <= province_count:
                result[pid] = ttype

    if terrain_map is None:
        return result

    # Histogram of the number of pixels calculated in a single pass (province_id, terrain_index)
    flat_pid = province_map.ravel()
    flat_ter = terrain_map.ravel()
    n_ter = int(terrain_map.max()) + 1
    n_pid = province_count + 1

    # Encoded as pid * n_ter + ter_idx, one bincount
    combined = flat_pid.astype(np.int64) * n_ter + flat_ter.astype(np.int64)
    hist = np.bincount(combined, minlength=n_pid * n_ter).reshape(n_pid, n_ter)

    # Get the most common terrain index for each province
    dominant_idx = hist.argmax(axis=1)  # shape (n_pid,)

    for pid in range(1, n_pid):
        # Skip those already set by provincial_terrain
        if provincial_terrain and pid in provincial_terrain:
            continue
        if hist[pid].sum() == 0:
            continue
        result[pid] = PALETTE_TO_TYPE.get(int(dominant_idx[pid]), "plains")

    return result


# Note: default.map is no longer generated - use the original one (EaW verification method)
# Our BMP/CSV files will automatically overwrite the original corresponding files by file name.


# ────────────────── continent.txt ──────────────────

def _write_continent(output_dir, continent_mgr=None):
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    # Vanilla's portraits/country files/some modifiers are hard-coded to reference these 7 continent names,
    # If MOD is not written, it will trigger "unknown continent" → portraitdatabase empty bucket → divide by zero crash.
    # Even if the user customizes the continent, the vanilla name must be retained, otherwise the vanilla resource loading will crash.
    VANILLA_CONTINENTS = [
        "europe", "north_america", "south_america",
        "australia", "africa", "asia", "middle_east",
    ]
    user_names = list(continent_mgr.names) if continent_mgr is not None and continent_mgr.count() > 0 else []
    # Merge and remove duplicates, vanilla 7 are written first to ensure that their IDs (1..7) are consistent with vanilla
    seen = set()
    names = []
    for n in VANILLA_CONTINENTS + user_names:
        if n not in seen:
            seen.add(n)
            names.append(n)
    with open(os.path.join(d, "continent.txt"), "w", encoding="utf-8") as f:
        f.write("continents = {\n")
        for n in names:
            f.write(f"\t{n}\n")
        f.write("}\n")


# ────────────────── adjacencies ──────────────────

def _write_adjacencies(output_dir):
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "adjacencies.csv"), "w", encoding="utf-8") as f:
        f.write("From;To;Type;Through;start_x;start_y;stop_x;stop_y;adjacency_rule_name;Comment\n")
        # vanilla last line format: -1;-1;;-1;-1;-1;-1;-1;-1
        f.write("-1;-1;;-1;-1;-1;-1;-1;-1\n")


def _write_seasons_txt(output_dir):
    """Write map/seasons.txt — Season visual (color/leaf changes). Use vanilla default."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "seasons.txt"), "w", encoding="utf-8") as f:
        f.write("""winter = {
\tstart_date=00.12.01
\tend_date=00.02.10
\thsv_north= { 0 0.1 1 }
\tcolorbalance_north= { 0.9 0.9 1 }
\thsv_center= { 0.0 1.0 1.0 }
\tcolorbalance_center= { 1.0 1.0 1.0 }
\thsv_south= { 0.0 1.0 1.0 }
\tcolorbalance_south= { 1.0 1.0 1.0 }
}
spring = {
\tstart_date=00.03.10
\tend_date=00.04.22
\thsv_north= { 0 0.1 1 }
\tcolorbalance_north= { 0.9 0.9 1 }
\thsv_center= { 0.0 1.0 1.0 }
\tcolorbalance_center= { 1.0 1.0 1.0 }
\thsv_south= { 0.0 1.0 1.0 }
\tcolorbalance_south= { 1.0 1.0 1.0 }
}
summer = {
\tstart_date=00.05.20
\tend_date=00.09.10
\thsv_north= { 0 0.1 1 }
\tcolorbalance_north= { 0.9 0.9 1 }
\thsv_center= { 0.0 1.0 1.0 }
\tcolorbalance_center= { 1.0 1.0 1.0 }
\thsv_south= { 0.0 1.0 1.0 }
\tcolorbalance_south= { 1.0 1.0 1.0 }
}
autumn = {
\tstart_date=00.10.10
\tend_date=00.10.31
\thsv_north= { 0 0.1 1 }
\tcolorbalance_north= { 0.9 0.9 1 }
\thsv_center= { 0.0 1.0 1.0 }
\tcolorbalance_center= { 1.0 1.0 1.0 }
\thsv_south= { 0.0 1.0 1.0 }
\tcolorbalance_south= { 1.0 1.0 1.0 }
}
tree_winter = { start_date=00.11.15 end_date=00.12.01 }
tree_winter2 = { start_date=00.12.20 end_date=00.01.20 }
tree_spring = { start_date=00.02.20 end_date=00.03.01 }
tree_spring2 = { start_date=00.03.20 end_date=00.04.20 }
tree_summer = { start_date=00.05.20 end_date=00.06.01 }
tree_summer2 = { start_date=00.06.20 end_date=00.09.10 }
tree_autumn = { start_date=00.10.01 end_date=00.10.10 }
tree_autumn2 = { start_date=00.10.25 end_date=00.11.01 }
""")


# NOTE: adjacency_rules/ambient_object/weatherpositions/unitstacks/rocket_sites is no longer generated


# ────────────────── State split ──────────────────

def _auto_split_states(land_ids, province_map, per_state=15):
    if not land_ids:
        return {}
    # Vectorized calculation of centroid
    flat_pm = province_map.ravel()
    n = int(province_map.max()) + 1
    pid_count = np.bincount(flat_pm, minlength=n)
    ys_grid, xs_grid = np.mgrid[0:MAP_HEIGHT, 0:MAP_WIDTH]
    sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
    sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)

    centers = {}
    for pid in land_ids:
        if pid_count[pid] > 0:
            centers[pid] = (sum_y[pid] / pid_count[pid], sum_x[pid] / pid_count[pid])
    sorted_ids = sorted(centers.keys(), key=lambda p: (centers[p][0] // 100, centers[p][1]))
    states = {}
    for i in range(0, len(sorted_ids), per_state):
        sid = i // per_state + 1
        states[sid] = sorted_ids[i:i + per_state]
    return states


def _split_states_by_region(region_list, land_id_set, max_per_state=15):
    """Split State by region from region_list.
    The provinces of each state must be completely within the same strategic region (mandatory requirement for HOI4).

    Parameters:
        region_list: [(region_id, [pid...])] list returned by _write_strategic_regions
        land_id_set: The set of all land provinces
        max_per_state: The maximum number of provinces in each state (if too large, split it)

    Return:
        {state_id: [land_pid, ...]}"""
    states = {}
    sid = 1
    for region_id, region_provs in region_list:
        # Only take the land provinces in this region
        region_land = [p for p in region_provs if p in land_id_set]
        if not region_land:
            continue
        # If there are too many, it will be split into multiple states, all in the same region.
        for i in range(0, len(region_land), max_per_state):
            states[sid] = region_land[i:i + max_per_state]
            sid += 1
    return states


def _write_states(states, tag, province_map, output_dir):
    from export.writers.history.states import write_states_fallback
    write_states_fallback(states, tag, province_map, output_dir)


# ───────────────── Supply system ──────────────────

def _write_supply_nodes(states, province_map, output_dir):
    from export.writers.map.supply import write_supply_nodes
    return write_supply_nodes(states, province_map, output_dir)


def _write_railways(states, province_map, output_dir):
    from export.writers.map.supply import write_railways
    return write_railways(states, province_map, output_dir)


def _write_buildings(states, province_map, tile_map, output_dir, sea_ids=None,
                     land_to_sea=None, pid_count=None, sum_x=None, sum_y=None):
    from export.writers.map.buildings import write_buildings
    return write_buildings(states, province_map, tile_map, output_dir, sea_ids,
                           land_to_sea=land_to_sea,
                           pid_count=pid_count, sum_x=sum_x, sum_y=sum_y)


def _write_empty_unitstacks(output_dir):
    from export.writers.map.buildings import write_empty_unitstacks
    return write_empty_unitstacks(output_dir)


def _write_supply_areas(states, output_dir):
    from export.writers.map.supply import write_supply_areas
    return write_supply_areas(states, output_dir)


# ────────────────── Strategic area (automatic splitting of multiple areas) ──────────────────

def _write_weatherpositions(region_list, province_map, output_dir):
    from export.writers.map.strategic_regions import write_weatherpositions
    return write_weatherpositions(region_list, province_map, output_dir)


def _write_strategic_regions(province_map, tile_map, output_dir,
                             grid_cols=6, grid_rows=4, states_dict=None):
    from export.writers.map.strategic_regions import write_strategic_regions
    return write_strategic_regions(province_map, tile_map, output_dir, grid_cols, grid_rows, states_dict)


def _write_positions(province_map, tile_map, output_dir,
                     pid_count=None, sum_x=None, sum_y=None):
    from export.writers.map.positions import write_positions_txt
    return write_positions_txt(province_map, tile_map, output_dir,
                               pid_count=pid_count, sum_x=sum_x, sum_y=sum_y)


# ───────────────── Country ──────────────────

def _write_country_flags(tags, output_dir, country_mgr=None):
    from export.writers.gfx.flags import write_country_flags
    return write_country_flags(tags, output_dir, country_mgr)


def _write_country_portraits(tag, output_dir):
    from export.writers.gfx.portraits import write_country_portraits
    return write_country_portraits(tag, output_dir)


def _write_country_colors(tag, rgb, output_dir):
    from export.writers.common.countries import write_country_colors
    return write_country_colors(tag, rgb, output_dir)


def _write_country_names(tag, output_dir, country_name="Fantasy"):
    from export.writers.common.countries import write_country_names
    return write_country_names(tag, output_dir, country_name)


def _write_country_characters(tag, output_dir, country_name="Fantasy"):
    from export.writers.common.countries import write_country_characters
    return write_country_characters(tag, output_dir, country_name)


def _write_dynamic_countries(output_dir, count=75):
    from export.writers.common.countries import write_dynamic_countries
    return write_dynamic_countries(output_dir, count)


def _write_country(tag, capital_state_id, output_dir):
    from export.writers.common.countries import write_country
    return write_country(tag, capital_state_id, output_dir)


# ───────────────── Localization ──────────────────

def _write_localisation(mod_name, tag, states, output_dir, region_count=24):
    from export.writers.localisation.yml import write_localisation_simple
    return write_localisation_simple(mod_name, tag, states, output_dir, region_count)


# ────────────────── descriptor.mod + empty directory ──────────────────

def _write_descriptor(mod_name, output_dir):
    from export.writers.map.descriptor import write_descriptor
    return write_descriptor(mod_name, output_dir)



def _write_bookmark(mod_name, country_tags, output_dir):
    from export.writers.common.countries import write_bookmark
    return write_bookmark(mod_name, country_tags, output_dir)


# Note: ideologies and state_category are no longer generated - use the original ones (EaW verification practices)
# The original common/ideologies and common/state_category are complete enough


# ─────────────────── Using Manager Data Export ───────────────────

def _write_states_from_mgr(state_mgr, country_mgr, province_map, output_dir, tile_map=None,
                           land_id_set=None, coastal_set=None):
    from export.writers.history.states import write_states_from_mgr
    write_states_from_mgr(state_mgr, country_mgr, province_map, output_dir, tile_map,
                          land_id_set=land_id_set, coastal_set=coastal_set)


def _write_countries_from_mgr(country_mgr, output_dir, states):
    from export.writers.common.countries import write_countries_from_mgr
    return write_countries_from_mgr(country_mgr, output_dir, states)


def _write_dynamic_country_oobs(output_dir, count=75):
    from export.writers.common.countries import write_dynamic_country_oobs
    return write_dynamic_country_oobs(output_dir, count)


def _write_country_ideas(country_mgr, output_dir):
    from export.writers.common.countries import write_country_ideas
    return write_country_ideas(country_mgr, output_dir)


def _write_localisation_full(mod_name, state_mgr, country_mgr, states, output_dir,
                             region_count=24, region_mgr=None):
    from export.writers.localisation.yml import write_localisation_full
    return write_localisation_full(mod_name, state_mgr, country_mgr, states, output_dir,
                                    region_count=region_count, region_mgr=region_mgr)


# ────────────────── Auxiliary functions ──────────────────

def _is_land(pid, pm, tm):
    """Consistent with _classify_provinces_fast: land_n >= sea_n AND land_n >= lake_n"""
    mask = pm == pid
    if not np.any(mask):
        return False
    tiles = tm[mask]
    l = int(np.sum(tiles == TILE_LAND))
    s = int(np.sum(tiles == TILE_SEA))
    k = int(np.sum(tiles == TILE_LAKE))
    return l >= s and l >= k


def _get_province_type(pid, pm, tm):
    """Return province type: 'land', 'sea', 'lake'"""
    mask = pm == pid
    if not np.any(mask):
        return "sea"
    tiles = tm[mask]
    land_n = int(np.sum(tiles == TILE_LAND))
    sea_n = int(np.sum(tiles == TILE_SEA))
    lake_n = int(np.sum(tiles == TILE_LAKE))
    if land_n >= sea_n and land_n >= lake_n:
        return "land"
    elif lake_n > sea_n:
        return "lake"
    return "sea"


def _merge_tiny_provinces(province_map: np.ndarray, min_pixels: int = 8) -> np.ndarray:
    """Merge crumb provinces with area < min_pixels into the largest adjacent province.

    Returns a new array without modifying the original province_map.
    Use numpy vectorization: bincount statistical area, boundary pixel batch extraction neighbors."""
    pm = province_map.copy()
    h, w = pm.shape

    # Count the number of pixels in each province
    max_id = int(pm.max())
    areas = np.bincount(pm.ravel(), minlength=max_id + 1)

    # Find all provinces < min_pixels (skip ID 0 = not assigned)
    tiny_ids = np.where((areas > 0) & (areas < min_pixels))[0]
    tiny_ids = tiny_ids[tiny_ids > 0]
    if len(tiny_ids) == 0:
        return pm

    # Process them in ascending order of area (the smallest ones are merged first to avoid two fragments pointing at each other)
    tiny_ids = tiny_ids[np.argsort(areas[tiny_ids])]

    for pid in tiny_ids:
        # The province may have been wiped out by a previous round of mergers
        mask = (pm == pid)
        if not np.any(mask):
            continue

        # Find the coordinates of the boundary pixel
        ys, xs = np.where(mask)

        # Collect the province IDs of all adjacent pixels (up, down, left, and right)
        neighbor_ids = []
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny = ys + dy
            nx = xs + dx
            valid = (ny >= 0) & (ny < h) & (nx >= 0) & (nx < w)
            if np.any(valid):
                n_vals = pm[ny[valid], nx[valid]]
                # Exclude self and ID 0
                n_vals = n_vals[(n_vals != pid) & (n_vals != 0)]
                if len(n_vals) > 0:
                    neighbor_ids.append(n_vals)

        if not neighbor_ids:
            continue

        all_neighbors = np.concatenate(neighbor_ids)
        # Count the number of occurrences of each neighbor, and then select the largest neighbor based on its area.
        unique_neighbors, counts = np.unique(all_neighbors, return_counts=True)
        # Use neighbor area as primary sort key (select the largest neighbor)
        neighbor_areas = areas[unique_neighbors]
        best_idx = int(np.argmax(neighbor_areas))
        target = unique_neighbors[best_idx]

        # Change fragment pixels to target province
        pm[mask] = target
        # Update area cache
        areas[target] += areas[pid]
        areas[pid] = 0

    return pm


def _repair_too_large_provinces(
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> list[int]:
    """Trim safe boundary pixels from provinces with an oversized box.

    HOI4 treats a province whose bounding-box width or height reaches one
    eighth of the map dimension as invalid.  A project can legitimately have
    a long, narrow lake at exactly that boundary (9301 in the Belgium map),
    so merging or renumbering it would damage references.  Instead, remove
    only a complete outer row/column and assign those pixels to an adjacent
    province.  Same-surface neighbours are preferred; lake edge pixels may
    fall back to adjacent land, which is the expected raster representation of
    an inland lake shoreline.

    ``province_map`` is already the export copy at the call site.  The helper
    mutates that copy and leaves ``tile_map`` untouched; the normal
    classification synchronisation later in :func:`export_full_mod` updates
    surface types for any reassigned pixels.
    """
    from scipy import ndimage
    from domain.validators.province import detect_too_large_provinces

    height, width = province_map.shape
    if height < 2 or width < 2:
        return []

    initial_ids = detect_too_large_provinces(
        province_map, include_engine_boundary=True
    )
    if not initial_ids:
        return []

    # Only make a small, lossless boundary correction here.  A province that
    # is many pixels over the limit needs an intentional split in the editor;
    # trimming a whole strip during export would silently change the map.
    # Leave an additional pixel of headroom on real-sized maps.  The loader
    # expands a province box by one pixel while building its border cache, so
    # a raster box that is merely one pixel below 1/8 can still trip the same
    # diagnostic.  Keep the smaller synthetic fixtures at the normal limit.
    engine_margin = 1 if min(height, width) >= 256 else 0
    safe_height = max(1, (height - 1) // 8 - engine_margin)
    safe_width = max(1, (width - 1) // 8 - engine_margin)
    max_safe_overflow = 4

    cross = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)

    def _bbox(pid: int):
        ys, xs = np.where(province_map == pid)
        if ys.size == 0:
            return None
        return (
            int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max()),
            ys, xs,
        )

    def _neighbours(y: int, x: int, pid: int) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny = y + dy
            if ny < 0 or ny >= height:
                continue
            # HOI4 maps wrap horizontally, so an edge pixel can see the
            # opposite edge.  Vertical wrapping is not supported.
            nx = (x + dx) % width
            candidate = int(province_map[ny, nx])
            if candidate > 0 and candidate != pid:
                result.append((candidate, int(tile_map[ny, nx])))
        return result

    def _target_for(y: int, x: int, pid: int) -> int | None:
        neighbours = _neighbours(y, x, pid)
        if not neighbours:
            return None
        source_surface = int(tile_map[y, x])

        def _best(records: list[tuple[int, int]]) -> int | None:
            if not records:
                return None
            counts: dict[int, int] = {}
            for candidate, _surface in records:
                counts[candidate] = counts.get(candidate, 0) + 1
            return min(counts, key=lambda candidate: (-counts[candidate], candidate))

        same_surface = [
            (candidate, surface)
            for candidate, surface in neighbours
            if surface == source_surface
        ]
        target = _best(same_surface)
        if target is not None:
            return target

        # A lake generally has land on its outer edge rather than another
        # lake province.  Reassigning that tiny shoreline pixel to land is
        # safer than deleting the lake or making a mixed lake/sea province.
        if source_surface == TILE_LAKE:
            return _best([
                (candidate, surface)
                for candidate, surface in neighbours
                if surface == TILE_LAND
            ])
        return None

    def _preserves_connectivity(pid: int) -> bool:
        bbox = _bbox(pid)
        if bbox is None:
            return False
        y0, y1, x0, x1, ys, xs = bbox
        if ys.size < 8:
            return False
        local = province_map[y0:y1 + 1, x0:x1 + 1] == pid
        return int(ndimage.label(local, structure=cross)[1]) == 1

    def _apply_edge(pid: int, axis: str, edge: int) -> bool:
        bbox = _bbox(pid)
        if bbox is None:
            return False
        y0, y1, x0, x1, ys, xs = bbox
        if axis == "y":
            selection = ys == edge
        else:
            selection = xs == edge
        edge_ys = ys[selection]
        edge_xs = xs[selection]
        if edge_ys.size == 0:
            return False

        targets = [
            _target_for(int(y), int(x), pid)
            for y, x in zip(edge_ys, edge_xs)
        ]
        # Reassign a complete outer edge in one operation.  Partial trimming
        # would leave the old bounding box in place and could create a thin
        # detached tail.
        if any(target is None for target in targets):
            return False
        old_values = province_map[edge_ys, edge_xs].copy()
        province_map[edge_ys, edge_xs] = np.asarray(targets, dtype=province_map.dtype)
        if not _preserves_connectivity(pid):
            province_map[edge_ys, edge_xs] = old_values
            return False
        return True

    # Process the candidates found by the single full-map scan above.  Each
    # subsequent check is local to the candidate, avoiding several additional
    # 11-million-pixel scans during a normal export.
    repaired: list[int] = []
    for pid in initial_ids:
        while True:
            bbox = _bbox(int(pid))
            if bbox is None:
                break
            y0, y1, x0, x1, ys, xs = bbox
            box_h = y1 - y0 + 1
            box_w = x1 - x0 + 1
            if (
                box_h - safe_height > max_safe_overflow
                or box_w - safe_width > max_safe_overflow
            ):
                # Do not erase a substantial part of an intentional large
                # province.  The map generator's splitter handles those.
                break
            options: list[tuple[int, str, int]] = []
            if box_h > safe_height:
                options.extend([
                    (int(np.count_nonzero(ys == y0)), "y", y0),
                    (int(np.count_nonzero(ys == y1)), "y", y1),
                ])
            if box_w > safe_width:
                options.extend([
                    (int(np.count_nonzero(xs == x0)), "x", x0),
                    (int(np.count_nonzero(xs == x1)), "x", x1),
                ])
            if not options:
                repaired.append(int(pid))
                break
            options.sort(key=lambda item: (item[0], item[1], item[2]))
            applied = False
            for _count, axis, edge in options:
                if _apply_edge(int(pid), axis, edge):
                    applied = True
                    break
            if not applied:
                break

    return sorted(set(repaired))


def _classify_provinces_fast(province_count, province_map, tile_map):
    """Vectorize batch classification of all provinces to avoid scanning the entire map province by province"""
    flat_pm = province_map.ravel()
    flat_tm = tile_map.ravel()

    # Use bincount to count the number of pixels of each block type in each province at one time
    n = province_count + 1
    land_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND), minlength=n)
    sea_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_SEA), minlength=n)
    lake_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_LAKE), minlength=n)

    land_ids = []
    sea_ids = []
    lake_ids = []
    total_counts = land_counts + sea_counts + lake_counts
    for pid in range(1, province_count + 1):
        if total_counts[pid] == 0:
            # 0 pixel ghost province — classified as ocean (no state/strategic area required)
            sea_ids.append(pid)
            continue
        l, s, k = land_counts[pid], sea_counts[pid], lake_counts[pid]
        if l >= s and l >= k:
            land_ids.append(pid)
        elif k > s:
            lake_ids.append(pid)
        else:
            sea_ids.append(pid)

    return land_ids, sea_ids, lake_ids


def _sync_tile_with_province_class(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    land_ids: list[int],
    sea_ids: list[int],
    lake_ids: list[int],
) -> None:
    """Synchronize tile_map in place so that the tile type of each pixel = the type of the province to which the pixel belongs.

    _classify_provinces_fast Classify province by pixel majority vote: a 60% LAND / 40% SEA
    The province is classified as land, but the 40% SEA pixels are still SEA in the tile_map. These "minorities"
    Pixels will result in:
      - HOI4 determines the province coastal according to definition.csv but the buildings writer is in tile_map
        LAND pixel not found in → naval_base coordinates are written to SEA → HOI4 "not over the land"
        → port ignored → coastal but no port → crash
    After synchronization, ensure that tile_map, provinces.bmp, and definition.csv are consistent."""
    n = int(province_map.max()) + 1
    new_tile = np.zeros(n, dtype=np.uint8)
    for pid in land_ids:
        if 0 < pid < n:
            new_tile[pid] = TILE_LAND
    for pid in sea_ids:
        if 0 < pid < n:
            new_tile[pid] = TILE_SEA
    for pid in lake_ids:
        if 0 < pid < n:
            new_tile[pid] = TILE_LAKE
    # pid==0 is the background, keep the original value
    new_tile[0] = tile_map.ravel()[0] if tile_map.size else TILE_SEA
    np.copyto(tile_map, new_tile[province_map])


def _sync_terrain_with_tile(terrain_map: np.ndarray, tile_map: np.ndarray) -> None:
    """Synchronize terrain_map and tile_map, modify terrain_map in place.

    - terrain==ocean(15) → changed to plains(0) for land pixels
    - terrain!=ocean(15) → changed to ocean(15) on ocean pixels
    - lake pixels on terrain!=lakes(14) → changed to lakes(14)

    Note: The terrain_map (mutation) is modified directly here because it is a one-time correction before exporting.
    It does not affect the data in the user editor (the exporter gets an independent array)."""
    ocean_idx = TERRAIN_PALETTE_INDEX["ocean"]   # 15
    plains_idx = TERRAIN_PALETTE_INDEX["plains"]  # 0
    lakes_idx = TERRAIN_PALETTE_INDEX["lakes"]    # 14

    # There should be no ocean terrain on land
    land_bad = (tile_map == TILE_LAND) & (terrain_map == ocean_idx)
    count_land = int(np.sum(land_bad))
    if count_land > 0:
        terrain_map[land_bad] = plains_idx
        print(f"  [terrain sync] Changed {count_land:,} land pixels from ocean terrain to plains")

    # There should be no landforms on the ocean
    sea_bad = (tile_map == TILE_SEA) & (terrain_map != ocean_idx)
    count_sea = int(np.sum(sea_bad))
    if count_sea > 0:
        terrain_map[sea_bad] = ocean_idx
        print(f"  [terrain sync] Changed {count_sea:,} sea pixels to ocean terrain")

    # The terrain on the lake should be lakes
    lake_bad = (tile_map == TILE_LAKE) & (terrain_map != lakes_idx)
    count_lake = int(np.sum(lake_bad))
    if count_lake > 0:
        terrain_map[lake_bad] = lakes_idx
        print(f"  [terrain sync] Changed {count_lake:,} lake pixels to lakes terrain")


def _gen_heightmap(tm):
    """Generates a naturally gradient heightmap based on a distance field (close to vanilla).

    Old algorithm: fixed value + Gaussian blur + force pullback → coast like cliff (80-110 transition zone is almost 0)
    New algorithm: Use distance field to make the height change smoothly with the distance to the opponent
        - Land: The farther away from the sea, the higher (coast 96 → inland 130+)
        - Ocean: The farther away from the land, the deeper (shallow sea 94 → deep sea 70-83)
    Expected effect: 80-110 transition zone accounts for 70%+, close to vanilla's 85%"""
    from scipy.ndimage import distance_transform_edt, gaussian_filter

    is_land = (tm == TILE_LAND)
    is_sea = (tm == TILE_SEA)
    is_lake = (tm == TILE_LAKE)

    # Distance field: the pixel distance from each pixel to the nearest "other"
    dist_to_land = distance_transform_edt(~is_land)  # Distance from ocean pixel to nearest land
    dist_to_sea = distance_transform_edt(~is_sea)    # Distance from land pixel to nearest ocean

    hm = np.full((MAP_HEIGHT, MAP_WIDTH), SEA_LEVEL, dtype=np.float32)

    # Land height: Coast 96 → Inland up to 160
    # Coefficient 1.5/pixel, capped at +65 (i.e. maximum 95+65=160)
    hm[is_land] = SEA_LEVEL + np.clip(dist_to_sea[is_land] * 1.5, 1, 65)

    # Ocean height: shallow sea 94 → deep sea minimum 70
    # Coefficient 0.8/pixel, capped at -25 (ie the deepest 95-25=70)
    hm[is_sea] = SEA_LEVEL - np.clip(dist_to_land[is_sea] * 0.8, 1, 25)

    # Land plus random undulations makes mountains less flat (±20 range)
    rng = np.random.RandomState(42)
    noise = gaussian_filter(rng.rand(MAP_HEIGHT, MAP_WIDTH), sigma=30) * 40
    hm[is_land] += noise[is_land] - 20

    # Small-scale softening (avoiding jagged steps)
    hm = gaussian_filter(hm, sigma=1.5)

    # Stick to the bottom line (make sure HOI4 sea and land determination is correct)
    hm[is_land] = np.maximum(hm[is_land], SEA_LEVEL + 1)  # Land at least 96
    hm[is_sea] = np.minimum(hm[is_sea], SEA_LEVEL - 1)    # sea at least 94
    hm[is_lake] = SEA_LEVEL - 3

    return np.clip(hm, 30, 255).astype(np.uint8)


def _gen_terrain(tm):
    """Generate terrain.bmp. Land Coast 1-2 pixels use desert (yellow sand color) to simulate a beach.

    The desert terrain rendering color of HOI4 is sandy yellow, and the visual effect is spread on 1-2 pixels on the coast.
    Similar to vanilla beach strips. It only affects the visual (rendering), not the gameplay (because
    The dominant terrain of the province is plains/forest with dozens or hundreds of pixels, which will not turn into a desert)."""
    from scipy.ndimage import distance_transform_edt

    t = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.uint8)
    for tile_type, name in DEFAULT_TERRAIN_FOR_TILE.items():
        t[tm == tile_type] = TERRAIN_PALETTE_INDEX[name]

    # Coastal beaches: land ≤ 2 pixels from the sea uses desert (index 3 = sandy yellow)
    is_land = (tm == TILE_LAND)
    is_sea = (tm == TILE_SEA)
    dist_to_sea = distance_transform_edt(~is_sea)
    beach_mask = is_land & (dist_to_sea <= 2)
    t[beach_mask] = TERRAIN_PALETTE_INDEX["desert"]  # vanilla desert is rendered as sandy yellow

    return t


def _write_normal_map(hm, output_dir):
    """Write world_normal.bmp lighting normal map (half size).
    First reduce to half size and then calculate the normal, saving 4 times the calculation amount, and the visual difference is ignored."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)

    full_h, full_w = hm.shape
    NW, NH = full_w // 2, full_h // 2

    # Shrink to half size first and then calculate the line (instead of calculating and then shrinking)
    h_small = hm.reshape(NH, 2, NW, 2).mean(axis=(1, 3)).astype(np.float32) / 255.0

    # Use scipy.sobel to calculate the gradient (standard practice, smoother than central difference)
    # The new heightmap gradient range is larger, and the strength is reduced to 6 (the old 12 will be too undulating)
    from scipy.ndimage import sobel
    strength = 6.0
    dx = sobel(h_small, axis=1) * strength
    dy = -sobel(h_small, axis=0) * strength

    nx, ny, nz = -dx, -dy, np.ones_like(h_small)
    L = np.sqrt(nx**2 + ny**2 + nz**2)
    L[L == 0] = 1
    nx /= L; ny /= L; nz /= L

    r = ((nx + 1) * 127.5).clip(0, 255).astype(np.uint8)
    g = ((ny + 1) * 127.5).clip(0, 255).astype(np.uint8)
    b = ((nz + 1) * 127.5).clip(0, 255).astype(np.uint8)

    # Whole block write to BMP
    row = NW * 3
    pad = (4 - (row % 4)) % 4
    pix = (row + pad) * NH
    bgr = np.stack([b[::-1], g[::-1], r[::-1]], axis=2)  # (NH, NW, 3) bottom-up
    with open(os.path.join(d, "world_normal.bmp"), "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<I", 54 + pix))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", 54))
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<ii", NW, NH))
        f.write(struct.pack("<HH", 1, 24))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pix))
        f.write(struct.pack("<ii", 2835, 2835))
        f.write(struct.pack("<II", 0, 0))
        if pad == 0:
            f.write(bgr.tobytes())
        else:
            pb = b"\x00" * pad
            for y in range(NH):
                f.write(bgr[y].tobytes())
                f.write(pb)
