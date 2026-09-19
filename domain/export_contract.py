"""Typed export contracts (M2.1).

Plain dataclasses for export profiles, immutable snapshots, repair
proposals, asset resolutions, plans, and results. Dependency-free: no Qt,
no file handles, no live Project references.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


EXPORT_PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REPAIR_POLICIES = ("off", "propose", "apply-safe")
REPAIR_SAFETY_LEVELS = ("safe", "semantic", "breaking")
EXPORT_LIFECYCLES = ("draft", "candidate", "frozen", "accepted")
ASSET_DISPOSITIONS = ("generated", "preserved", "inherited", "omitted", "unsupported", "blocked")

RESERVED_ACCEPTANCE_TAGS = ("BEL", "FRA", "GER", "HOL", "LUX", "ENG")

PROFILE_STAGES = {
    "foundation": (
        "core_rasters", "regions", "logistics", "placements",
        "map_metadata", "state_geography", "assets", "descriptor",
    ),
    "acceptance": (
        "core_rasters", "regions", "logistics", "placements",
        "map_metadata", "state_geography", "acceptance_content",
        "assets", "descriptor",
    ),
    "scaffold": (
        "core_rasters", "regions", "logistics", "placements",
        "map_metadata", "state_geography", "scaffold_content",
        "assets", "descriptor",
    ),
    "legacy_full": (
        "core_rasters", "regions", "logistics", "placements",
        "map_metadata", "state_geography", "scaffold_content",
        "assets", "descriptor",
    ),
}

FOUNDATION_FORBIDDEN_SCOPE = ("countries", "localisation", "gfx")

LEGACY_SCOPE_KEYS = (
    "map",
    "states",
    "countries",
    "strategic_regions",
    "localisation",
    "supply",
    "gfx",
    "replace_path",
    "descriptor",
    "compact_ids",
)


def translate_legacy_scope(scope):
    """Translate a legacy scope dict to the owning profile (M9.1)."""
    normalized = dict(scope or {})
    for key in normalized:
        if key not in LEGACY_SCOPE_KEYS:
            raise PlanRejected("unknown export layer: %r" % key)
    resolve_layers("legacy_full", normalized or None)
    return ("legacy_full", normalized)


class PlanRejected(ValueError):
    pass


@dataclass(frozen=True)
class RepairAction:
    code: str
    safety: str
    summary: str
    affected_ids: tuple = ()
    affected_states: tuple = ()
    pixel_count: int = 0
    record_count: int = 0
    before: str = ""
    after: str = ""
    mapping: dict = field(default_factory=dict)
    rerun_validations: tuple = ()
    layer: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "safety": self.safety,
            "summary": self.summary,
            "affected_ids": list(self.affected_ids),
            "affected_states": list(self.affected_states),
            "pixel_count": int(self.pixel_count),
            "record_count": int(self.record_count),
            "before": self.before,
            "after": self.after,
            "mapping": {str(k): v for k, v in self.mapping.items()},
            "rerun_validations": list(self.rerun_validations),
            "layer": self.layer,
        }


@dataclass(frozen=True)
class AssetResolution:
    rel_path: str
    disposition: str
    provenance: str = ""
    reason: str = ""
    size: int = 0
    source: str = ""
    sha256: str = ""
    output_owner: str = ""
    profile_rule: str = ""
    dirty_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "rel_path": self.rel_path,
            "disposition": self.disposition,
            "provenance": self.provenance,
            "reason": self.reason,
            "size": int(self.size),
            "source": self.source,
            "sha256": self.sha256,
            "output_owner": self.output_owner,
            "profile_rule": self.profile_rule,
            "dirty_reason": self.dirty_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssetResolution":
        get = data.get if isinstance(data, dict) else (lambda k, d="": d)
        try:
            _size = int(get("size", 0) or 0)
        except (TypeError, ValueError):
            _size = 0
        return cls(
            rel_path=str(get("rel_path", get("path", get("file", "")))),
            disposition=str(get("disposition", get("status", get("state", "")))),
            provenance=str(get("provenance", get("source", ""))),
            reason=str(get("reason", "")),
            size=_size,
            source=str(get("source", get("provenance", ""))),
            sha256=str(get("sha256", get("source_sha256", get("hash", "")))),
            output_owner=str(get("output_owner", get("owner", get("stage", "")))),
            profile_rule=str(get("profile_rule", get("rule", ""))),
            dirty_reason=str(get("dirty_reason", "")),
        )


@dataclass(frozen=True)
class ValidationNote:
    code: str
    severity: str
    message: str
    layer: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "layer": self.layer,
        }


@dataclass(frozen=True)
class WrittenFile:
    rel_path: str
    size: int = 0
    sha256: str = ""

    def to_dict(self) -> dict:
        return {"rel_path": self.rel_path, "size": int(self.size), "sha256": self.sha256}


@dataclass
class StageResult:
    stage: str
    owned_files: tuple = ()
    written: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "owned_files": list(self.owned_files),
            "written": [w.to_dict() if hasattr(w, "to_dict") else dict(w) for w in self.written],
            "notes": list(self.notes),
        }


@dataclass
class ExportPlan:
    profile_name: str = "legacy_full"
    game_target: object = None
    game_profile: object = None
    lifecycle: str = "draft"
    repair_policy: str = "propose"
    layers: tuple = ()
    scope: dict = field(default_factory=dict)
    snapshot: object = None
    proposed_repairs: list = field(default_factory=list)
    applied_repairs: list = field(default_factory=list)
    asset_resolutions: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    acceptance_tags: tuple = ()
    mod_name: str = "WorldTest"
    tag: str = "AAA"

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    def repairs_by_safety(self, safety: str) -> list:
        return [r for r in self.proposed_repairs if r.safety == safety]

    def to_dict(self) -> dict:
        target = self.game_target
        return {
            "profile": self.profile_name,
            "lifecycle": self.lifecycle,
            "repair_policy": self.repair_policy,
            "layers": list(self.layers),
            "scope": dict(self.scope),
            "mod_name": self.mod_name,
            "tag": self.tag,
            "blocked": self.blocked,
            "blockers": list(self.blockers),
            "acceptance_tags": list(self.acceptance_tags),
            "game_target": target.to_dict() if target is not None and hasattr(target, "to_dict") else None,
            "game_profile": getattr(self.game_profile, "profile_id", None),
            "proposed_repairs": [r.to_dict() for r in self.proposed_repairs],
            "applied_repairs": [r.to_dict() for r in self.applied_repairs],
            "asset_resolutions": [a.to_dict() for a in self.asset_resolutions],
            "findings": [f.to_dict() if hasattr(f, "to_dict") else dict(f) for f in self.findings],
        }


@dataclass
class ExportResult:
    output_dir: str = ""
    profile_name: str = "legacy_full"
    manifest_path: str = ""
    report_path: str = ""
    written_files: list = field(default_factory=list)
    repairs_applied: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    fingerprint: str = ""
    success: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "output_dir": self.output_dir,
            "profile": self.profile_name,
            "manifest_path": self.manifest_path,
            "report_path": self.report_path,
            "written_files": [w.to_dict() if hasattr(w, "to_dict") else dict(w) for w in self.written_files],
            "repairs_applied": list(self.repairs_applied),
            "findings": list(self.findings),
            "fingerprint": self.fingerprint,
            "success": bool(self.success),
            "message": self.message,
        }


def resolve_layers(profile_name: str, scope: dict | None = None) -> tuple:
    if profile_name not in PROFILE_STAGES:
        raise PlanRejected(
            "unknown export profile %r; expected one of %s" % (profile_name, ", ".join(EXPORT_PROFILES))
        )
    layers = PROFILE_STAGES[profile_name]
    if scope:
        for key, enabled in scope.items():
            if not enabled:
                continue
            if key in FOUNDATION_FORBIDDEN_SCOPE and profile_name == "foundation":
                raise PlanRejected(
                    "scope %r is incompatible with the foundation profile" % key
                )
            if key not in layers and key not in LEGACY_SCOPE_KEYS:
                raise PlanRejected("unknown export layer: %r" % key)
    return layers


def select_acceptance_tags(occupied_tags=(), count: int = 2, seed: str = "m2-acceptance") -> tuple:
    excluded = {str(t).upper() for t in list(RESERVED_ACCEPTANCE_TAGS) + [str(t) for t in (occupied_tags or ())]}
    pool = []
    for first in "QTXYZWUV":
        for second in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            for third in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                tag = first + second + third
                if tag not in excluded:
                    pool.append(tag)
    if count > len(pool):
        raise PlanRejected("not enough free acceptance tags for %d countries" % count)
    digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()
    start = int(digest, 16) % len(pool)
    chosen = []
    index = start
    while len(chosen) < count:
        candidate = pool[index % len(pool)]
        if candidate not in chosen:
            chosen.append(candidate)
        index += 1
    return tuple(chosen)