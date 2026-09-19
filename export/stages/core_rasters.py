"""Core raster stage: BMP layers, terrain sync, and DDS overviews (M2.4)."""
from __future__ import annotations

import numpy as np

from export.stages.base import build_export_states, classify_current, compute_centroids, record_written, snapshot_output_files


NAME = "core_rasters"
OWNED_FILES = (
    "map/provinces.bmp",
    "map/heightmap.bmp",
    "map/terrain.bmp",
    "map/rivers.bmp",
    "map/trees.bmp",
    "map/cities.bmp",
    "map/world_normal.bmp",
    "map/terrain/colormap_rgb_cityemissivemask_a.dds",
    "map/terrain/colormap_water_0.dds",
    "map/terrain/colormap_water_1.dds",
    "map/terrain/colormap_water_2.dds",
    "map/terrain/fow_rgb_waterspec_a.dds",
)
PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REQUIRES = ("tile_map", "province_map")
PROVIDES = ("land_ids", "sea_ids", "lake_ids", "province_count", "terrain_for_export")


def _prepare_legacy_working_copy(ctx) -> None:
    from export.mod_exporter import (
        _merge_tiny_provinces,
        _repair_too_large_provinces,
    )
    ctx.province_map = _merge_tiny_provinces(np.asarray(ctx.province_map).copy(), min_pixels=8)
    _repair_too_large_provinces(ctx.province_map, np.asarray(ctx.tile_map))
    if ctx.enabled("compact_ids"):
        from domain.map_data import MapData
        provinces = np.asarray(ctx.province_map).copy()
        shim = MapData.__new__(MapData)
        shim.province_map = provinces
        shim.tile_map = np.asarray(ctx.tile_map).copy()
        shim.provincial_terrain = dict(ctx.provincial_terrain or {})
        shim.compact_with_references(
            state_mgr=ctx.state_mgr,
            country_mgr=ctx.country_mgr,
            strategic_region_mgr=ctx.strategic_region_mgr,
            continent_mgr=ctx.continent_mgr,
            adjacency_mgr=ctx.adjacency_mgr,
            railway_mgr=ctx.railway_mgr,
            supply_mgr=ctx.supply_mgr,
            adjacency_rule_mgr=ctx.adjacency_rule_mgr,
        )
        ctx.province_map = shim.province_map
        ctx.tile_map = shim.tile_map
        ctx.provincial_terrain = dict(shim.provincial_terrain or {})


def run(ctx, *, profile=None, map_width=None, map_height=None):
    from domain.export_contract import StageResult
    from domain.generators.province import generate_province_colors
    from export.bmp_writer import (
        write_heightmap_bmp,
        write_provinces_bmp,
        write_rivers_bmp,
        write_terrain_bmp,
    )
    from export.mod_exporter import (
        _classify_provinces_fast,
        _sync_terrain_with_tile,
        _sync_tile_with_province_class,
        _gen_heightmap,
        _gen_terrain,
        _write_normal_map,
    )
    before = snapshot_output_files(ctx.output_dir)
    if ctx.profile_name == "legacy_full":
        _prepare_legacy_working_copy(ctx)
        ctx.provenance.append("legacy export-copy normalization applied (tiny merge, bbox trim, compaction)")
    province_map = np.asarray(ctx.province_map)
    tile_map = np.asarray(ctx.tile_map)
    province_count = int(province_map.max())
    land_ids, sea_ids, lake_ids = _classify_provinces_fast(province_count, province_map, tile_map)
    overrides = dict(ctx.scratch.get("province_type_overrides") or {})
    if overrides:
        for pid, forced in overrides.items():
            for bucket in (land_ids, sea_ids, lake_ids):
                if pid in bucket:
                    bucket.remove(pid)
            if forced == "land":
                land_ids.append(pid)
            elif forced == "lake":
                lake_ids.append(pid)
            else:
                sea_ids.append(pid)
        land_ids, sea_ids, lake_ids = sorted(land_ids), sorted(sea_ids), sorted(lake_ids)
    _sync_tile_with_province_class(tile_map, province_map, land_ids, sea_ids, lake_ids)
    ctx.tile_map = tile_map
    colors = generate_province_colors(province_count)
    height_map = np.asarray(ctx.height_map) if ctx.height_map is not None else None
    if height_map is not None and int(height_map.max()) != int(height_map.min()):
        heightmap = height_map
    else:
        heightmap = _gen_heightmap(tile_map)
    terrain_map = np.asarray(ctx.terrain_map) if ctx.terrain_map is not None else None
    if terrain_map is not None and int(terrain_map.max()) > 0:
        terrain_for_export = terrain_map
        _sync_terrain_with_tile(terrain_for_export, tile_map)
        ctx.terrain_map = terrain_for_export
    else:
        terrain_for_export = _gen_terrain(tile_map)
    height, width = tile_map.shape
    if ctx.enabled("map"):
        write_provinces_bmp(province_map, ctx.output_dir, colors)
        write_heightmap_bmp(heightmap, ctx.output_dir)
        write_terrain_bmp(terrain_for_export, ctx.output_dir, game_target=ctx.game_target)
        write_rivers_bmp(ctx.output_dir,
                         np.asarray(ctx.river_map) if ctx.river_map is not None else None,
                         shape=tile_map.shape)
        from export.writers.map.trees_bmp import auto_generate_tree_map, write_trees_bmp
        _tree_profile = profile if profile is not None else getattr(ctx, "game_profile", None)
        try:
            _tree_map_w = int(map_width) if map_width is not None else int(width)
        except (TypeError, ValueError):
            _tree_map_w = int(width)
        try:
            _tree_map_h = int(map_height) if map_height is not None else int(height)
        except (TypeError, ValueError):
            _tree_map_h = int(height)
        _generated_tree = auto_generate_tree_map(
            terrain_for_export,
            profile=_tree_profile,
            map_width=_tree_map_w,
            map_height=_tree_map_h,
        )
        write_trees_bmp(
            ctx.output_dir,
            tree_map=_generated_tree,
            map_width=_tree_map_w,
            map_height=_tree_map_h,
            profile=_tree_profile,
        )
        from export.writers.map.cities_bmp import write_cities_bmp
        write_cities_bmp(ctx.output_dir, terrain_map=terrain_for_export, map_width=int(width),
                         map_height=int(height), game_target=ctx.game_target)
        from export.asset_helper import write_or_restore
        write_or_restore("map/world_normal.bmp", ctx.output_dir, ctx.assets, ctx.dirty_assets,
                         lambda: _write_normal_map(heightmap, ctx.output_dir))
        from export.writers.map.colormap_dds import write_colormap_dds, write_fow_dds, write_water_colormap_dds
        write_or_restore("map/terrain/colormap_rgb_cityemissivemask_a.dds", ctx.output_dir,
                         ctx.assets, ctx.dirty_assets,
                         lambda: write_colormap_dds(tile_map, ctx.output_dir,
                                                    settings=ctx.colormap_settings,
                                                    terrain_map=terrain_for_export, height_map=heightmap))
        water_paths = ["map/terrain/colormap_water_0.dds", "map/terrain/colormap_water_1.dds",
                       "map/terrain/colormap_water_2.dds"]
        if all(p in ctx.assets and p not in ctx.dirty_assets for p in water_paths):
            for rel_path in water_paths:
                full = ctx.output_dir + "/" + rel_path
                import os
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as handle:
                    handle.write(ctx.assets[rel_path])
        else:
            write_water_colormap_dds(tile_map, ctx.output_dir)
        write_or_restore("map/terrain/fow_rgb_waterspec_a.dds", ctx.output_dir, ctx.assets,
                         ctx.dirty_assets, lambda: write_fow_dds(tile_map, ctx.output_dir, height_map=heightmap))
        map_note = "map raster and overview layers written"
    else:
        map_note = "map layer disabled by scope; raster and overview files skipped"
    pid_count, sum_x, sum_y = compute_centroids(province_map)
    ctx.scratch.update({
        "land_ids": list(land_ids),
        "sea_ids": list(sea_ids),
        "lake_ids": list(lake_ids),
        "province_count": province_count,
        "province_colors": dict(colors),
        "terrain_for_export": terrain_for_export,
        "heightmap": heightmap,
        "pid_count": pid_count,
        "sum_x": sum_x,
        "sum_y": sum_y,
    })
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written,
                       notes=["province_count=%d land=%d sea=%d lake=%d; %s"
                              % (province_count, len(land_ids), len(sea_ids), len(lake_ids), map_note)])
