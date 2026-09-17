"""Assets stage: preserved-asset audit (M2.4)."""
from __future__ import annotations

from export.stages.base import record_written, snapshot_output_files


NAME = "assets"
OWNED_FILES = ()
PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REQUIRES = ()
PROVIDES = ()


def run(ctx):
    from domain.export_contract import StageResult
    from services.export_manifest import PRESERVED_CAPABLE_PATHS
    before = snapshot_output_files(ctx.output_dir)
    notes: list = []
    for rel_path in PRESERVED_CAPABLE_PATHS:
        full = ctx.output_dir + "/" + rel_path
        import os
        exists = os.path.isfile(full)
        if rel_path in (ctx.assets or {}) and rel_path not in (ctx.dirty_assets or set()):
            notes.append("%s: preserved clean imported bytes" % rel_path if exists
                         else "%s: clean asset registered but writer did not emit it" % rel_path)
        elif exists:
            notes.append("%s: generated" % rel_path)
        else:
            notes.append("%s: not emitted" % rel_path)
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written, notes=notes)