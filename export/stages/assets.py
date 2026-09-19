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
    from services.export_manifest import PRESERVED_CAPABLE_PATHS, STRUCTURAL_OPTIONAL_PATHS
    before = snapshot_output_files(ctx.output_dir)
    notes: list = []
    import os
    resolutions = list(getattr(ctx, "asset_resolutions", None) or [])
    if resolutions:
        def _rel(r):
            try:
                if isinstance(r, dict):
                    return str(r.get("rel_path", ""))
                return str(getattr(r, "rel_path", ""))
            except (AttributeError, TypeError, ValueError):
                return ""
        def _disp(r):
            try:
                if isinstance(r, dict):
                    return str(r.get("disposition", ""))
                return str(getattr(r, "disposition", ""))
            except (AttributeError, TypeError, ValueError):
                return ""
        def _src(r):
            try:
                if isinstance(r, dict):
                    return str(r.get("source", "") or r.get("provenance", ""))
                return str(getattr(r, "source", "") or getattr(r, "provenance", ""))
            except (AttributeError, TypeError, ValueError):
                return ""
        def _reason(r):
            try:
                if isinstance(r, dict):
                    return str(r.get("reason", ""))
                return str(getattr(r, "reason", ""))
            except (AttributeError, TypeError, ValueError):
                return ""
        def _owner(r):
            try:
                if isinstance(r, dict):
                    return str(r.get("output_owner", ""))
                return str(getattr(r, "output_owner", ""))
            except (AttributeError, TypeError, ValueError):
                return ""
        for entry in sorted(resolutions, key=_rel):
            rel_path = _rel(entry)
            if not rel_path:
                continue
            disp = _disp(entry) or "unknown"
            src = _src(entry) or "unknown"
            reason = _reason(entry) or ""
            owner = _owner(entry) or ""
            full = os.path.join(str(ctx.output_dir), rel_path.replace("/", os.sep))
            exists = os.path.isfile(full)
            suffix = (" owner=%s" % owner) if owner else ""
            detail = ("%s via %s" % (disp, src)) + suffix
            if reason:
                detail += " (%s)" % reason
            if disp in ("generated", "preserved") and not exists:
                notes.append("%s: %s but file is absent" % (rel_path, detail))
            elif disp == "blocked":
                if exists:
                    notes.append("%s: %s; on-disk preview bytes do not satisfy the contract" % (rel_path, detail))
                else:
                    notes.append("%s: %s; no file written" % (rel_path, detail))
            elif disp in ("omitted", "unsupported", "unknown"):
                notes.append("%s: %s" % (rel_path, detail))
            else:
                if rel_path in (ctx.assets or {}) and rel_path not in (ctx.dirty_assets or set()):
                    notes.append("%s: preserved clean imported bytes via %s%s" % (rel_path, src, suffix) if exists else "%s: clean asset registered but writer did not emit it (%s)" % (rel_path, detail))
                elif exists:
                    notes.append("%s: generated via %s%s" % (rel_path, src, suffix))
                else:
                    notes.append("%s: %s but file is absent" % (rel_path, detail))
        # Ensure structural optionals are always visible even when the plan
        # predates M6.1 and carries no resolution for them.
        try:
            have = {_rel(r) for r in resolutions if _rel(r)}
        except (AttributeError, TypeError, ValueError):
            have = set()
        for rel_path in STRUCTURAL_OPTIONAL_PATHS:
            if rel_path in have:
                continue
            full = os.path.join(str(ctx.output_dir), rel_path.replace("/", os.sep))
            exists = os.path.isfile(full)
            if rel_path in (ctx.assets or {}) and rel_path not in (ctx.dirty_assets or set()):
                notes.append("%s: preserved clean imported bytes via project-assets" % rel_path if exists else "%s: clean asset registered but writer did not emit it" % rel_path)
            elif exists:
                notes.append("%s: generated" % rel_path)
            else:
                notes.append("%s: not emitted (no resolution; omitted by default)" % rel_path)
    else:
        for rel_path in PRESERVED_CAPABLE_PATHS:
            full = ctx.output_dir + "/" + rel_path
            exists = os.path.isfile(full)
            if rel_path in (ctx.assets or {}) and rel_path not in (ctx.dirty_assets or set()):
                notes.append("%s: preserved clean imported bytes" % rel_path if exists else "%s: clean asset registered but writer did not emit it" % rel_path)
            elif exists:
                notes.append("%s: generated" % rel_path)
            else:
                notes.append("%s: not emitted" % rel_path)
        try:
            for rel_path in STRUCTURAL_OPTIONAL_PATHS:
                full = ctx.output_dir + "/" + rel_path
                exists = os.path.isfile(full)
                if rel_path in (ctx.assets or {}) and rel_path not in (ctx.dirty_assets or set()):
                    notes.append("%s: preserved clean imported bytes" % rel_path if exists else "%s: clean asset registered but writer did not emit it" % rel_path)
                elif exists:
                    notes.append("%s: generated" % rel_path)
                else:
                    notes.append("%s: not emitted" % rel_path)
        except (AttributeError, TypeError, ValueError):
            pass
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written, notes=notes)
