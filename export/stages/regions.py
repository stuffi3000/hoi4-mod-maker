"""Regions stage: state finalization, coastal conversion, strategic regions (M2.4)."""
from __future__ import annotations

import numpy as np

from export.stages.base import build_export_states, record_written, snapshot_output_files


NAME = "regions"
OWNED_FILES = (
    "map/strategicregions/",
    "map/weatherpositions.txt",
)
PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REQUIRES = ("land_ids", "sea_ids")
PROVIDES = ("states", "coastal_set", "region_list")


def run(ctx):
    from domain.export_contract import StageResult
    from export.mod_exporter import _compute_coastal_once
    before = snapshot_output_files(ctx.output_dir)
    notes = []
    states = build_export_states(ctx)
    province_map = np.asarray(ctx.province_map)
    land_ids = list(ctx.scratch.get("land_ids") or [])
    sea_ids = list(ctx.scratch.get("sea_ids") or [])
    coastal_set, land_to_sea = _compute_coastal_once(province_map, land_ids, sea_ids)
    if states is not None:
        state_pids: set = set()
        for provs in states.values():
            state_pids.update(provs)
        orphan_coastal = {int(p) for p in coastal_set if p not in state_pids}
        if orphan_coastal:
            land_ids = [int(p) for p in land_ids if p not in orphan_coastal]
            sea_ids = sorted(set(int(p) for p in sea_ids) | orphan_coastal)
            coastal_set -= orphan_coastal
            ctx.scratch["land_ids"] = land_ids
            ctx.scratch["sea_ids"] = sea_ids
            notes.append("converted %d stateless coastal provinces to sea" % len(orphan_coastal))
        land_to_sea = {p: s for p, s in land_to_sea.items() if p in coastal_set}
    ctx.scratch["coastal_set"] = set(coastal_set)
    ctx.scratch["land_to_sea"] = dict(land_to_sea)
    placement_mgr = getattr(ctx, "map_placement_mgr", None)
    profile = getattr(ctx, "profile_name", None)
    scratch = getattr(ctx, "scratch", None) or {}
    if placement_mgr is None and profile == "foundation" and scratch.get("foundation_legacy_compat"):
        writer_profile = None
    else:
        writer_profile = profile
    region_list = None
    if ctx.enabled("strategic_regions"):
        if ctx.strategic_region_mgr is not None and ctx.strategic_region_mgr.count() > 0:
            from export.writers.map.strategic_regions import (
                write_strategic_regions_from_mgr,
                write_weatherpositions,
            )
            region_list = write_strategic_regions_from_mgr(ctx.strategic_region_mgr, ctx.output_dir)
            write_weatherpositions(
                region_list,
                province_map,
                ctx.output_dir,
                map_placement_mgr=getattr(ctx, "map_placement_mgr", None),
                strategic_region_mgr=ctx.strategic_region_mgr,
                profile_name=writer_profile,
            )
        else:
            from export.mod_exporter import _write_strategic_regions, _write_weatherpositions
            region_list = _write_strategic_regions(
                province_map, np.asarray(ctx.tile_map), ctx.output_dir, states_dict=states)
            _write_weatherpositions(
                region_list,
                province_map,
                ctx.output_dir,
                map_placement_mgr=getattr(ctx, "map_placement_mgr", None),
                profile_name=writer_profile,
            )
        notes.append("strategic regions=%d" % (len(region_list) if region_list else 0))
    else:
        notes.append("strategic_regions layer disabled by scope")
    ctx.scratch["region_list"] = region_list
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written, notes=notes)
