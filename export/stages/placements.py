"""Placements stage: buildings, positions, and unit stacks (M2.4)."""
from __future__ import annotations
import numpy as np
from export.stages.base import record_written, snapshot_output_files
NAME = "placements"
OWNED_FILES = (
    "map/buildings.txt",
    "map/positions.txt",
    "map/unitstacks.txt",
    "map/airports.txt",
    "map/rocketsites.txt",
    "map/rocket_sites.txt",
    "map/cities.txt",
    "map/colors.txt",
)
PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REQUIRES = ("states", "coastal_set")
PROVIDES = ("coastal_set",)
def run(ctx):
    from domain.export_contract import StageResult
    before = snapshot_output_files(ctx.output_dir)
    notes = []
    states = ctx.scratch.get("states")
    if ctx.enabled("map") and states is not None:
        from export.mod_exporter import (
            _write_buildings,
            _write_empty_unitstacks,
            _write_positions,
        )
        mgr = getattr(ctx, "map_placement_mgr", None)
        profile = getattr(ctx, "profile_name", None)
        scratch = getattr(ctx, "scratch", None) or {}
        if mgr is None and profile == "foundation" and scratch.get("foundation_legacy_compat"):
            writer_profile = None
        else:
            writer_profile = profile
        failed_coastal = _write_buildings(
            states, np.asarray(ctx.province_map), np.asarray(ctx.tile_map), ctx.output_dir,
            sea_ids=list(ctx.scratch.get("sea_ids") or []),
            land_to_sea=dict(ctx.scratch.get("land_to_sea") or {}),
            pid_count=ctx.scratch.get("pid_count"), sum_x=ctx.scratch.get("sum_x"),
            sum_y=ctx.scratch.get("sum_y"), placement_manager=mgr, profile_name=writer_profile)
        if failed_coastal:
            coastal_set = set(ctx.scratch.get("coastal_set") or ())
            coastal_set -= set(failed_coastal)
            land_ids = [int(p) for p in ctx.scratch.get("land_ids") or [] if p not in set(failed_coastal)]
            sea_ids = sorted(set(int(p) for p in ctx.scratch.get("sea_ids") or []) | set(failed_coastal))
            ctx.scratch["coastal_set"] = coastal_set
            ctx.scratch["land_ids"] = land_ids
            ctx.scratch["sea_ids"] = sea_ids
            notes.append("converted %d unreliable coastal provinces to sea" % len(failed_coastal))
        try:
            _unitstack_result = _write_empty_unitstacks(
                ctx.output_dir,
                getattr(ctx, "assets", None),
                getattr(ctx, "dirty_assets", None),
                getattr(ctx, "game_profile", None),
                getattr(ctx, "profile_name", None),
            )
        except TypeError:
            _unitstack_result = _write_empty_unitstacks(ctx.output_dir)
        try:
            _struct_actions = []
            if isinstance(_unitstack_result, dict):
                _struct_actions = list(_unitstack_result.get("actions") or [])
            for _rel, _act in _struct_actions:
                if _act == "preserved":
                    notes.append("%s: preserved clean imported bytes" % _rel)
        except (AttributeError, TypeError, ValueError):
            pass
        _write_positions(np.asarray(ctx.province_map), np.asarray(ctx.tile_map), ctx.output_dir,
                         pid_count=ctx.scratch.get("pid_count"), sum_x=ctx.scratch.get("sum_x"),
                         sum_y=ctx.scratch.get("sum_y"), placement_manager=mgr, profile_name=writer_profile)
        notes.append("placements written for %d states" % len(states))
        if mgr is not None and profile == "foundation":
            notes.append("foundation placements from reviewed manager records (incomplete provinces omitted)")
        elif mgr is not None and profile in ("acceptance", "scaffold", "legacy_full"):
            notes.append("placements include generated placeholders for %s compatibility" % profile)
    else:
        notes.append("map layer disabled or no states; placement files skipped")
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written, notes=notes)
