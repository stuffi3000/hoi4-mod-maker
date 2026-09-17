"""Map metadata stage: definition, continent, adjacencies, and map config (M2.4).

Runs after placements so definition.csv uses the final coastal set.
"""
from __future__ import annotations

import numpy as np

from export.stages.base import record_written, snapshot_output_files


NAME = "map_metadata"
OWNED_FILES = (
    "map/definition.csv",
    "map/continent.txt",
    "map/adjacencies.csv",
    "map/adjacency_rules.txt",
    "map/default.map",
    "map/seasons.txt",
    "map/ambient_object.txt",
)
PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REQUIRES = ("land_ids", "sea_ids", "lake_ids", "province_count", "coastal_set")
PROVIDES = ()


def run(ctx):
    from domain.export_contract import StageResult
    from export.mod_exporter import (
        _write_adjacencies,
        _write_continent,
        _write_definition_csv,
        _write_seasons_txt,
    )
    before = snapshot_output_files(ctx.output_dir)
    province_map = np.asarray(ctx.province_map)
    tile_map = np.asarray(ctx.tile_map)
    land_ids = list(ctx.scratch.get("land_ids") or [])
    sea_ids = list(ctx.scratch.get("sea_ids") or [])
    lake_ids = list(ctx.scratch.get("lake_ids") or [])
    province_count = int(ctx.scratch.get("province_count") or int(province_map.max()))
    colors = ctx.scratch.get("province_colors") or {}
    coastal_set = set(ctx.scratch.get("coastal_set") or ())
    notes = []
    if ctx.enabled("map"):
        from export.writers.map.ambient_object import write_ambient_object_txt
        write_ambient_object_txt(ctx.output_dir)
        _write_seasons_txt(ctx.output_dir)
        from export.writers.map.default_map import write_default_map
        write_default_map(ctx.output_dir, settings=ctx.default_map_settings,
                          province_count=province_count)
        _write_continent(ctx.output_dir, continent_mgr=ctx.continent_mgr)
        if ctx.adjacency_mgr is not None and ctx.adjacency_mgr.count() > 0:
            from export.writers.map.adjacencies import write_adjacencies_csv
            write_adjacencies_csv(ctx.output_dir, adjacency_mgr=ctx.adjacency_mgr)
        else:
            _write_adjacencies(ctx.output_dir)
        from export.writers.map.adjacency_rules import write_adjacency_rules_txt
        write_adjacency_rules_txt(ctx.output_dir, rule_mgr=ctx.adjacency_rule_mgr)
        _write_definition_csv(province_count, colors, province_map, tile_map, ctx.output_dir,
                              land_ids, sea_ids, lake_ids, continent_mgr=ctx.continent_mgr,
                              terrain_map=np.asarray(ctx.terrain_map) if ctx.terrain_map is not None else None,
                              provincial_terrain=ctx.provincial_terrain, coastal_set=coastal_set)
        notes.append("coastal=%d definition rows=%d" % (len(coastal_set), province_count))
    else:
        notes.append("map layer disabled by scope; metadata files skipped")
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written, notes=notes)