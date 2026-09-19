"""Pure foundation-freeze contracts (M8).

Dependency-free classification of post-freeze changes plus typed result
records for the candidate / freeze / compare / unfreeze workflow. No file
system access, no Qt, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field


FREEZE_SCHEMA = "foundation-freeze/1"
FREEZE_VERSION = "1"

MANIFEST_FILENAME = "foundation_manifest.json"
LOCK_FILENAME = "foundation.lock.json"
HANDOFF_FILENAME = "FOUNDATION-HANDOFF.md"
AUDIT_FILENAME = "foundation-freeze-audit.json"
ACCEPTANCE_FILENAME = "engine_acceptance.json"

CHANGE_CLASSES = (
    "breaking_identity",
    "breaking_topology",
    "foundation_visual",
    "placement",
    "non_foundation_content",
)

BREAKING_CHANGE_CLASSES = frozenset({"breaking_identity", "breaking_topology"})

RERUN_GUIDANCE = {
    "breaking_identity": (
        "Content references require migration; accepted state is lost. "
        "Regenerate dependent history and gameplay, then re-run full "
        "validation plus engine acceptance."
    ),
    "breaking_topology": (
        "Dependent history and gameplay require review; accepted state is "
        "lost. Re-run region and logistics validation plus engine acceptance."
    ),
    "foundation_visual": (
        "Content IDs remain valid. Re-run visual validation and usually "
        "engine acceptance."
    ),
    "placement": "Re-run related gameplay and visual checks.",
    "non_foundation_content": (
        "Foundation lock remains valid. No foundation re-freeze required."
    ),
}

PLACEMENT_OUTPUT_NAMES = frozenset({
    "map/buildings.txt",
    "map/positions.txt",
    "map/unitstacks.txt",
    "map/airports.txt",
    "map/rocket_sites.txt",
    "map/rocketsites.txt",
    "map/cities.txt",
    "map/colors.txt",
    "map/weatherpositions.txt",
    "map/ambient_object.txt",
})

IDENTITY_OUTPUT_PATHS = frozenset({
    "map/definition.csv",
    "map/provinces.bmp",
})

TOPOLOGY_OUTPUT_PATHS = frozenset({
    "map/default.map",
    "map/continent.txt",
    "map/adjacencies.csv",
    "map/adjacency_rules.txt",
    "map/supply_nodes.txt",
    "map/railways.txt",
    "map/seasons.txt",
})

VISUAL_OUTPUT_NAMES = frozenset({
    "map/heightmap.bmp",
    "map/terrain.bmp",
    "map/rivers.bmp",
    "map/trees.bmp",
    "map/cities.bmp",
    "map/world_normal.bmp",
})


def _normalize_path(path: str) -> str:
    try:
        text = str(path or "").strip()
    except Exception:
        return ""
    return text.replace("\\", "/")


def _output_rel_path(lock_path: str) -> str:
    text = _normalize_path(lock_path)
    for prefix in ("outputs.", "assets.", "asset_resolutions."):
        if text.startswith(prefix):
            rest = text[len(prefix):]
            if "." in rest:
                rel, _, _ = rest.rpartition(".")
                return rel
            return rest
    return ""


def _classify_output_rel_path(rel_path: str) -> str:
    norm = _normalize_path(rel_path).lower()
    if not norm:
        return "foundation_visual"
    if norm in IDENTITY_OUTPUT_PATHS:
        return "breaking_identity"
    if norm in PLACEMENT_OUTPUT_NAMES:
        return "placement"
    if norm in TOPOLOGY_OUTPUT_PATHS:
        return "breaking_topology"
    if norm.startswith("history/states/"):
        return "breaking_topology"
    if norm.startswith("map/strategicregions/"):
        return "breaking_topology"
    if norm.startswith("map/supplyareas/"):
        return "breaking_topology"
    if norm in VISUAL_OUTPUT_NAMES:
        return "foundation_visual"
    if norm.startswith("map/terrain/"):
        return "foundation_visual"
    if norm.startswith("history/countries"):
        return "non_foundation_content"
    if norm.startswith("history/units"):
        return "non_foundation_content"
    if norm.startswith("common/"):
        return "non_foundation_content"
    if norm.startswith("localisation"):
        return "non_foundation_content"
    if norm.startswith("gfx/"):
        return "non_foundation_content"
    if norm == "descriptor.mod":
        return "non_foundation_content"
    if norm.startswith("map/"):
        return "foundation_visual"
    return "non_foundation_content"


def classify_lock_path(path: str) -> dict:
    p = _normalize_path(path)
    if not p:
        return {
            "change_class": "non_foundation_content",
            "breaking": False,
            "rerun": RERUN_GUIDANCE["non_foundation_content"],
        }
    if p in ("profile", "snapshot_fingerprint", "identity", "project",
             "target.identity", "game_profile", "game_profile_detail"):
        change = "breaking_identity"
    elif p.startswith("identity."):
        change = "breaking_identity"
    elif p.startswith("project."):
        change = "breaking_identity"
    elif p.startswith("target.identity."):
        change = "breaking_identity"
    elif p.startswith("game_profile_detail."):
        change = "breaking_identity"
    elif p == "map_size" or p.startswith("map_size."):
        change = "breaking_identity"
    elif p.startswith("sources.arrays."):
        leaf = p.rsplit(".", 1)[-1]
        if leaf in ("tile", "province"):
            change = "breaking_identity"
        else:
            change = "foundation_visual"
    elif p.startswith("sources.managers."):
        leaf = p.rsplit(".", 1)[-1]
        if leaf == "country_mgr":
            change = "non_foundation_content"
        else:
            change = "breaking_topology"
    elif p.startswith("sources.auxiliary."):
        change = "foundation_visual"
    elif p.startswith("sources."):
        change = "breaking_topology"
    elif p in ("counts.province_ids", "counts.province_max", "counts.map_pixels",
               "geography.province_ids", "geography.province_max",
               "geography.map_pixels", "geography.stable_id_range"):
        change = "breaking_identity"
    elif p.startswith("counts.managers.country_mgr"):
        change = "non_foundation_content"
    elif p.startswith("counts.managers.") or p.startswith("geography.managers."):
        change = "breaking_topology"
    elif p.startswith("counts.") or p.startswith("geography."):
        change = "breaking_topology"
    elif p.startswith("outputs."):
        change = _classify_output_rel_path(_output_rel_path(p))
    elif p.startswith("assets.") or p.startswith("asset_resolutions."):
        rel = _output_rel_path(p)
        if rel:
            sub = _classify_output_rel_path(rel)
            if sub == "non_foundation_content":
                change = "non_foundation_content"
            elif sub in ("breaking_identity", "breaking_topology"):
                change = sub
            else:
                change = "foundation_visual"
        else:
            change = "foundation_visual"
    elif p.startswith("validation."):
        change = "non_foundation_content"
    elif p.startswith("engine_acceptance."):
        change = "non_foundation_content"
    elif p in ("lifecycle", "freeze_schema", "freeze_version", "lock_schema",
               "lock_version", "manifest_schema", "manifest_version",
               "tool_version"):
        change = "non_foundation_content"
    else:
        change = "non_foundation_content"
    breaking = change in BREAKING_CHANGE_CLASSES
    return {
        "change_class": change,
        "breaking": breaking,
        "rerun": RERUN_GUIDANCE[change],
    }


def explain_difference(path: str, old: object, new: object) -> str:
    info = classify_lock_path(path)
    change = info["change_class"]
    if old is None:
        return "Added %s (%s)." % (path, change)
    if new is None:
        return "Removed %s (%s)." % (path, change)
    return "Changed %s (%s): %r -> %r." % (path, change, old, new)


@dataclass(frozen=True)
class FreezeChange:
    path: str = ""
    change_class: str = "non_foundation_content"
    breaking: bool = False
    summary: str = ""
    old: object = None
    new: object = None
    rerun: str = ""

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "change_class": str(self.change_class),
            "breaking": bool(self.breaking),
            "summary": str(self.summary),
            "lock": self.old,
            "manifest": self.new,
            "rerun": str(self.rerun),
        }


@dataclass(frozen=True)
class FreezeComparison:
    breaking: bool = False
    differences: tuple = ()
    status: str = "compatible"
    lock_identity: str = ""
    manifest_identity: str = ""

    def to_dict(self) -> dict:
        return {
            "breaking": bool(self.breaking),
            "differences": [d.to_dict() if hasattr(d, "to_dict") else dict(d)
                            for d in self.differences],
            "status": str(self.status),
            "lock_identity": str(self.lock_identity),
            "manifest_identity": str(self.manifest_identity),
        }


@dataclass(frozen=True)
class CandidateRecord:
    ok: bool = False
    reasons: tuple = ()
    lock_path: str = ""
    identity_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": bool(self.ok),
            "reasons": [str(r) for r in self.reasons],
            "lock_path": str(self.lock_path),
            "identity_hash": str(self.identity_hash),
        }


@dataclass(frozen=True)
class FreezeRecord:
    ok: bool = False
    reasons: tuple = ()
    lock_path: str = ""
    handoff_path: str = ""
    identity_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": bool(self.ok),
            "reasons": [str(r) for r in self.reasons],
            "lock_path": str(self.lock_path),
            "handoff_path": str(self.handoff_path),
            "identity_hash": str(self.identity_hash),
        }


@dataclass(frozen=True)
class UnfreezeRecord:
    ok: bool = False
    reasons: tuple = ()
    lock_path: str = ""
    audit_path: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": bool(self.ok),
            "reasons": [str(r) for r in self.reasons],
            "lock_path": str(self.lock_path),
            "audit_path": str(self.audit_path),
            "reason": str(self.reason),
        }
