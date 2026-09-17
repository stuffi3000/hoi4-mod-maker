"""Descriptor stage: mod descriptor files (M2.4)."""
from __future__ import annotations

from export.stages.base import record_written, snapshot_output_files


NAME = "descriptor"
OWNED_FILES = (
    "descriptor.mod",
    ".mod",
)
PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REQUIRES = ()
PROVIDES = ()


def run(ctx):
    from domain.export_contract import StageResult
    before = snapshot_output_files(ctx.output_dir)
    notes: list = []
    if ctx.enabled("descriptor"):
        from export.mod_exporter import _write_descriptor
        _write_descriptor(ctx.mod_name, ctx.output_dir, game_target=ctx.game_target,
                          profile=ctx.game_profile, write_outer=False)
        notes.append("descriptor written for target %s"
                     % getattr(ctx.game_target, "supported_version", "?"))
    else:
        notes.append("descriptor layer disabled by scope")
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written, notes=notes)
