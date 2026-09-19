"""Logistics stage: supply nodes, railways, and supply areas (M2.4)."""
from __future__ import annotations

import numpy as np

from export.stages.base import record_written, snapshot_output_files


NAME = "logistics"
OWNED_FILES = (
    "map/supply_nodes.txt",
    "map/railways.txt",
    "map/supplyareas/",
)
PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REQUIRES = ("states",)
PROVIDES = ()


def run(ctx):
    from domain.export_contract import StageResult
    before = snapshot_output_files(ctx.output_dir)
    notes = []
    states = ctx.scratch.get("states")
    is_foundation = getattr(ctx, "profile_name", None) == "foundation"
    if ctx.enabled("supply") and states is not None:
        if ctx.supply_mgr is not None and ctx.supply_mgr.count() > 0:
            from export.writers.map.supply_nodes import write_supply_nodes_txt
            write_supply_nodes_txt(ctx.output_dir, supply_mgr=ctx.supply_mgr)
            notes.append("supply nodes from manager")
        else:
            from export.mod_exporter import _write_supply_nodes
            _write_supply_nodes(states, np.asarray(ctx.province_map), ctx.output_dir)
            if is_foundation:
                notes.append("supply nodes generated as unreviewed proposal; replace with a reviewed manager")
            else:
                notes.append("supply nodes generated")
        if ctx.railway_mgr is not None and ctx.railway_mgr.count() > 0:
            from export.writers.map.railways import write_railways_txt
            write_railways_txt(ctx.output_dir, railway_mgr=ctx.railway_mgr,
                               province_map=np.asarray(ctx.province_map))
            notes.append("railways from manager")
        else:
            from export.mod_exporter import _write_railways
            _write_railways(states, np.asarray(ctx.province_map), ctx.output_dir)
            if is_foundation:
                notes.append("railways generated as unreviewed adjacent-pair proposal; replace with a reviewed manager")
            else:
                notes.append("railways generated")
        from export.mod_exporter import _write_supply_areas
        _write_supply_areas(states, ctx.output_dir)
    else:
        notes.append("supply layer disabled or no states; logistics files skipped")
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written, notes=notes)