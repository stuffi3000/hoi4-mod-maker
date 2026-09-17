"""Export manifests, reports, and foundation-lock comparison (M2.5/M2.6).

Makes generated, preserved, inherited, and omitted assets visible for every
profile and supports lock comparison for the M3/M8 freeze workflow.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone


PRESERVED_CAPABLE_PATHS = (
    "map/world_normal.bmp",
    "map/terrain/colormap_rgb_cityemissivemask_a.dds",
    "map/terrain/colormap_water_0.dds",
    "map/terrain/colormap_water_1.dds",
    "map/terrain/colormap_water_2.dds",
    "map/terrain/fow_rgb_waterspec_a.dds",
)

WRITER_GENERATED_FILES = (
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
    "map/definition.csv",
    "map/continent.txt",
    "map/adjacencies.csv",
    "map/adjacency_rules.txt",
    "map/default.map",
    "map/seasons.txt",
    "map/ambient_object.txt",
    "map/weatherpositions.txt",
    "map/buildings.txt",
    "map/positions.txt",
    "map/unitstacks.txt",
    "map/supply_nodes.txt",
    "map/railways.txt",
    "descriptor.mod",
)

CONTENT_ONLY_PATHS = (
    "history/countries",
    "common/country_tags",
    "common/countries",
    "common/characters",
    "common/units",
    "common/ideas",
    "common/names",
    "history/units",
    "localisation",
    "gfx/flags",
    "common/bookmarks",
)

DEPRECATED_PATHS_FALLBACK = ("map/colors.txt",)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tool_version() -> str:
    try:
        from version import VERSION
        return str(VERSION)
    except (ImportError, AttributeError):
        return "unknown"


def hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_written_files(output_dir: str) -> list:
    from domain.export_contract import WrittenFile
    written = []
    for root, _dirs, files in os.walk(output_dir):
        for name in sorted(files):
            full = os.path.join(root, name)
            try:
                size = os.path.getsize(full)
                digest = hash_file(full)
            except OSError:
                continue
            written.append(WrittenFile(os.path.relpath(full, output_dir).replace(os.sep, "/"), size, digest))
    return written


def validate_staged_artifacts(output_dir: str, plan) -> list[str]:
    """Validate the profile/layer products before a staged promotion.

    The legacy ``ModVerifier`` intentionally remains a stricter, engine-shaped
    checker and is not yet profile-aware enough for geography-only foundation
    shells.  This M2 gate checks the products promised by the selected stage
    graph without treating omitted profile content as an error.
    """
    errors: list[str] = []
    scope = dict(getattr(plan, "scope", {}) or {})

    def enabled(key: str) -> bool:
        return bool(scope.get(key, True))

    def require_file(rel_path: str) -> None:
        path = os.path.join(output_dir, rel_path.replace("/", os.sep))
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            errors.append("missing or empty staged file: %s" % rel_path)

    def require_dir(rel_path: str) -> None:
        path = os.path.join(output_dir, rel_path.replace("/", os.sep))
        files = []
        if os.path.isdir(path):
            for root, _dirs, names in os.walk(path):
                files.extend(os.path.join(root, name) for name in names)
        if not files:
            errors.append("missing or empty staged directory: %s" % rel_path)

    if enabled("map"):
        for rel_path in (
            "map/provinces.bmp", "map/heightmap.bmp", "map/terrain.bmp",
            "map/rivers.bmp", "map/definition.csv", "map/default.map",
            "map/continent.txt", "map/adjacencies.csv", "map/adjacency_rules.txt",
            "map/seasons.txt", "map/ambient_object.txt", "map/buildings.txt",
            "map/positions.txt",
        ):
            require_file(rel_path)
    if enabled("strategic_regions"):
        require_dir("map/strategicregions")
    if enabled("supply"):
        require_file("map/supply_nodes.txt")
        require_file("map/railways.txt")
    if enabled("states"):
        require_dir("history/states")
    if enabled("countries") and getattr(plan, "profile_name", "") in ("acceptance", "scaffold", "legacy_full"):
        require_dir("history/countries")
        require_dir("history/units")
        require_dir("common/country_tags")
    if enabled("localisation") and getattr(plan, "profile_name", "") != "foundation":
        require_dir("localisation")
    if (enabled("gfx") and getattr(plan, "profile_name", "") in ("scaffold", "legacy_full")):
        require_dir("gfx/flags")
    if enabled("descriptor"):
        require_file("descriptor.mod")
    return errors


def _asset_counts(plan) -> dict:
    counts: dict = {}
    for resolution in getattr(plan, "asset_resolutions", []) or []:
        counts[resolution.disposition] = counts.get(resolution.disposition, 0) + 1
    return counts


def build_manifest_dict(plan, written_files: list, stage_results: list | None = None,
                        placeholders: list | None = None, provenance: list | None = None) -> dict:
    snapshot = getattr(plan, "snapshot", None)
    return {
        "tool_version": _tool_version(),
        "created_at": _utc_now_iso(),
        "profile": getattr(plan, "profile_name", "legacy_full"),
        "lifecycle": getattr(plan, "lifecycle", "draft"),
        "repair_policy": getattr(plan, "repair_policy", "propose"),
        "layers": list(getattr(plan, "layers", []) or []),
        "mod_name": getattr(plan, "mod_name", ""),
        "game_target": (plan.game_target.to_dict()
                        if getattr(plan, "game_target", None) is not None
                        and hasattr(plan.game_target, "to_dict") else None),
        "game_profile": getattr(getattr(plan, "game_profile", None), "profile_id", None),
        "snapshot_fingerprint": getattr(snapshot, "fingerprint", "") if snapshot is not None else "",
        "map_size": {"width": getattr(snapshot, "width", 0), "height": getattr(snapshot, "height", 0)}
        if snapshot is not None else {},
        "proposed_repairs": [r.to_dict() for r in (getattr(plan, "proposed_repairs", []) or [])],
        "applied_repairs": [r.to_dict() for r in (getattr(plan, "applied_repairs", []) or [])],
        "asset_counts": _asset_counts(plan),
        "asset_resolutions": [a.to_dict() for a in (getattr(plan, "asset_resolutions", []) or [])],
        "findings": [f.to_dict() if hasattr(f, "to_dict") else dict(f)
                     for f in (getattr(plan, "findings", []) or [])],
        "blockers": list(getattr(plan, "blockers", []) or []),
        "acceptance_tags": list(getattr(plan, "acceptance_tags", []) or []),
        "placeholders": list(placeholders or []),
        "provenance": list(provenance or []),
        "stages": [s.to_dict() if hasattr(s, "to_dict") else dict(s) for s in (stage_results or [])],
        "written_files": [w.to_dict() if hasattr(w, "to_dict") else dict(w) for w in (written_files or [])],
    }


def write_manifest(output_dir: str, plan, written_files: list, stage_results: list | None = None,
                   placeholders: list | None = None, provenance: list | None = None,
                   manifest_name: str = "foundation_manifest.json") -> str:
    payload = build_manifest_dict(plan, written_files, stage_results, placeholders, provenance)
    path = os.path.join(output_dir, manifest_name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def write_report(output_dir: str, plan, written_files: list, manifest_path: str,
                 report_name: str = "foundation_report.md") -> str:
    counts = _asset_counts(plan)
    lines = [
        "# Export report: %s" % getattr(plan, "mod_name", ""),
        "",
        "Profile: %s | Lifecycle: %s | Repair policy: %s" % (
            getattr(plan, "profile_name", ""), getattr(plan, "lifecycle", ""),
            getattr(plan, "repair_policy", "")),
        "Created: %s | Manifest: %s" % (_utc_now_iso(), os.path.basename(manifest_path)),
        "",
        "## Repairs",
        "",
    ]
    for repair in getattr(plan, "proposed_repairs", []) or []:
        applied = "applied" if repair in (getattr(plan, "applied_repairs", []) or []) else "proposed"
        lines.append("- [%s/%s] %s (%s): %s" % (
            repair.safety, applied, repair.code, repair.layer, repair.summary))
        if repair.mapping:
            lines.append("  mapping entries: %d" % len(repair.mapping))
        if repair.rerun_validations:
            lines.append("  rerun: %s" % ", ".join(repair.rerun_validations))
    lines.extend(["", "## Assets", ""])
    for key in ("generated", "preserved", "inherited", "omitted", "unsupported"):
        lines.append("- %s: %d" % (key, counts.get(key, 0)))
    lines.extend(["", "## Files (%d)" % len(written_files or []), ""])
    for written in sorted(written_files or [], key=lambda w: w.rel_path):
        lines.append("- %s (%d bytes)" % (written.rel_path, written.size))
    if getattr(plan, "blockers", None):
        lines.extend(["", "## Blockers", ""])
        for blocker in plan.blockers:
            lines.append("- %s" % blocker)
    path = os.path.join(output_dir, report_name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def write_lock_file(output_dir: str, plan, lock_name: str = "foundation.lock.json") -> str:
    snapshot = getattr(plan, "snapshot", None)
    payload = {
        "tool_version": _tool_version(),
        "created_at": _utc_now_iso(),
        "profile": getattr(plan, "profile_name", ""),
        "snapshot_fingerprint": getattr(snapshot, "fingerprint", "") if snapshot is not None else "",
        "map_size": {"width": getattr(snapshot, "width", 0), "height": getattr(snapshot, "height", 0)}
        if snapshot is not None else {},
        "game_profile": getattr(getattr(plan, "game_profile", None), "profile_id", None),
    }
    path = os.path.join(output_dir, lock_name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def compare_with_lock(manifest: dict | str, lock: dict | str) -> dict:
    manifest_data = _load_json(manifest) if isinstance(manifest, str) else dict(manifest or {})
    lock_data = _load_json(lock) if isinstance(lock, str) else dict(lock or {})
    differences = []
    for key in ("snapshot_fingerprint", "profile", "game_profile"):
        old, new = lock_data.get(key), manifest_data.get(key)
        if old != new:
            differences.append({"field": key, "lock": old, "manifest": new,
                                "breaking": key in ("snapshot_fingerprint",)})
    old_size = lock_data.get("map_size") or {}
    new_size = manifest_data.get("map_size") or {}
    if old_size != new_size:
        differences.append({"field": "map_size", "lock": old_size, "manifest": new_size, "breaking": True})
    breaking = any(item.get("breaking") for item in differences)
    return {"breaking": breaking, "differences": differences,
            "lock_fingerprint": lock_data.get("snapshot_fingerprint"),
            "manifest_fingerprint": manifest_data.get("snapshot_fingerprint")}
