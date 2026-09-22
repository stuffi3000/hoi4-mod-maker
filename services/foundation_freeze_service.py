"""Expanded foundation-freeze service (M8)."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
from domain import foundation_freeze as freeze_contract


FOUNDATION_MANAGER_KEYS = (
    "state_mgr",
    "continent_mgr",
    "adjacency_mgr",
    "railway_mgr",
    "supply_mgr",
    "adjacency_rule_mgr",
    "strategic_region_mgr",
)
FOUNDATION_AUXILIARY_KEYS = (
    "provincial_terrain",
    "colormap_settings",
    "default_map_settings",
)
ACCEPTANCE_SUCCESS_STATUSES = frozenset({"passed"})


class FoundationFreezeError(ValueError):
    pass
def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _tool_version() -> str:
    try:
        from version import VERSION
        return str(VERSION)
    except Exception:
        return "unknown"
def _read_json_file(path) -> dict:
    candidate = Path(path)
    if not candidate.is_file():
        raise FoundationFreezeError("file not found: %s" % candidate)
    try:
        text = candidate.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise FoundationFreezeError("cannot read %s: %s" % (candidate, exc)) from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise FoundationFreezeError("malformed JSON in %s: %s" % (candidate, exc)) from exc
    if not isinstance(data, dict):
        raise FoundationFreezeError("malformed document in %s: expected a JSON object" % candidate)
    return data
def _manifest_identity(manifest: dict) -> str:
    try:
        node = manifest.get("identity") if isinstance(manifest, dict) else None
        if isinstance(node, dict):
            digest = node.get("identity_hash")
            if isinstance(digest, str) and digest.strip():
                return digest.strip()
    except Exception:
        pass
    return ""


def _manifest_foundation_source_identity(manifest: dict, source: str = "manifest") -> dict:
    """Derive and, when present, verify a manifest's shared source identity."""
    try:
        from services.export_manifest import foundation_source_identity
        derived = foundation_source_identity(manifest)
    except Exception as exc:
        raise FoundationFreezeError("cannot derive %s foundation source identity: %s" % (source, exc)) from exc
    derived_hash = str(derived.get("identity_hash", "") or "").strip()
    derived_algorithm = str(derived.get("algorithm", "") or "").strip()
    if not derived_hash or not derived_algorithm:
        raise FoundationFreezeError("%s has no derivable foundation source identity" % source)
    stored = manifest.get("foundation_source_identity")
    if stored is not None:
        if not isinstance(stored, dict):
            raise FoundationFreezeError("%s has a malformed foundation_source_identity" % source)
        stored_hash = str(stored.get("identity_hash", "") or "").strip()
        stored_algorithm = str(stored.get("algorithm", "") or "").strip()
        if stored_hash != derived_hash or stored_algorithm != derived_algorithm:
            raise FoundationFreezeError(
                "%s foundation_source_identity does not match its canonical source payload" % source
            )
    return {"identity_hash": derived_hash, "algorithm": derived_algorithm}


def _require_manifest(manifest: dict, source: str = "manifest") -> dict:
    if not isinstance(manifest, dict) or not manifest:
        raise FoundationFreezeError("malformed %s: expected a JSON object" % source)
    digest = _manifest_identity(manifest)
    if not digest:
        raise FoundationFreezeError("%s has no identity.identity_hash" % source)
    profile = manifest.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        raise FoundationFreezeError("%s has no export profile" % source)
    size = manifest.get("map_size")
    if not isinstance(size, dict):
        raise FoundationFreezeError("%s has no map_size section" % source)
    _manifest_foundation_source_identity(manifest, source)
    return manifest
def load_manifest(path) -> dict:
    return _require_manifest(_read_json_file(path), "foundation manifest")
def load_lock(path) -> dict:
    data = _read_json_file(path)
    if not isinstance(data, dict) or not data:
        raise FoundationFreezeError("malformed foundation lock: expected a JSON object")
    digest = _manifest_identity(data)
    if not digest:
        raise FoundationFreezeError("foundation lock has no identity.identity_hash")
    return data
def load_acceptance(path):
    candidate = Path(path)
    if not candidate.exists():
        return None
    return _read_json_file(path)
def _normalize_rel(value) -> str:
    try:
        text = str(value or "").strip().replace("\\", "/")
    except Exception:
        return ""
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip().strip("/")
def _is_acceptance_only_path(rel_path: str) -> bool:
    try:
        from services.export_manifest import CONTENT_ONLY_PATHS, owner_stage_for_path
    except Exception:
        CONTENT_ONLY_PATHS = ("history/countries", "common/", "localisation", "gfx/flags", "history/units")
        def owner_stage_for_path(rel: str) -> str:
            norm = str(rel or "").replace("\\", "/")
            for prefix in ("history/countries", "common/", "localisation", "gfx/flags"):
                if norm == prefix or norm.startswith(prefix):
                    return "acceptance_content"
            return "assets"
    norm = _normalize_rel(rel_path)
    if not norm:
        return True
    for prefix in CONTENT_ONLY_PATHS:
        clean = _normalize_rel(prefix)
        if norm == clean or norm.startswith(clean + "/"):
            return True
    try:
        if owner_stage_for_path(norm) in ("acceptance_content", "scaffold_content"):
            return True
    except Exception:
        pass
    return False
def _foundation_stages() -> tuple:
    try:
        from services.export_manifest import PROFILE_STAGES
        return tuple(PROFILE_STAGES.get("foundation", ()))
    except Exception:
        return ("core_rasters", "regions", "logistics", "placements", "map_metadata", "state_geography", "assets", "descriptor")
def _lock_constants() -> dict:
    try:
        from services import export_manifest as manifest_mod
        return {"lock_schema": str(getattr(manifest_mod, "LOCK_SCHEMA", "foundation-lock/3.4")), "lock_version": str(getattr(manifest_mod, "LOCK_VERSION", "3.4")), "manifest_schema": str(getattr(manifest_mod, "MANIFEST_SCHEMA", "foundation-manifest/3.4")), "manifest_version": str(getattr(manifest_mod, "MANIFEST_VERSION", "3.4")), "generator": str(getattr(manifest_mod, "MANIFEST_GENERATOR", "hoi4-mod-maker/export_manifest"))}
    except Exception:
        return {"lock_schema": "foundation-lock/3.4", "lock_version": "3.4", "manifest_schema": "foundation-manifest/3.4", "manifest_version": "3.4", "generator": "hoi4-mod-maker/export_manifest"}
def _sorted_list(items) -> list:
    try:
        return sorted(items, key=lambda v: json.dumps(v, ensure_ascii=True, sort_keys=True, default=str))
    except Exception:
        return list(items or [])
def _filter_foundation_assets(manifest: dict) -> list:
    resolutions = manifest.get("asset_resolutions") or []
    if not isinstance(resolutions, list):
        return []
    kept = []
    for entry in resolutions:
        if not isinstance(entry, dict):
            continue
        rel = _normalize_rel(entry.get("rel_path"))
        owner = str(entry.get("output_owner", entry.get("stage", "")) or "").strip()
        if not rel or _is_acceptance_only_path(rel) or owner in ("acceptance_content", "scaffold_content"):
            continue
        kept.append({"rel_path": rel, "disposition": str(entry.get("disposition", "") or ""), "source_sha256": str(entry.get("source_sha256", "") or ""), "output_sha256": str(entry.get("output_sha256", "") or ""), "output_owner": str(entry.get("output_owner", entry.get("stage", "")) or ""), "profile_rule": str(entry.get("profile_rule", "") or "")})
    kept.sort(key=lambda item: item["rel_path"])
    return kept
def _filter_foundation_outputs(manifest: dict) -> list:
    written = manifest.get("written_files") or []
    if not isinstance(written, list):
        return []
    allowed = set(_foundation_stages())
    kept = []
    for entry in written:
        if not isinstance(entry, dict):
            continue
        rel = _normalize_rel(entry.get("rel_path"))
        if not rel or _is_acceptance_only_path(rel):
            continue
        stage = str(entry.get("stage", "") or "")
        if stage in ("acceptance_content", "scaffold_content"):
            continue
        if stage and stage not in allowed:
            continue
        try:
            size = int(entry.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        kept.append({"rel_path": rel, "size": size, "sha256": str(entry.get("sha256", "") or ""), "stage": stage})
    kept.sort(key=lambda item: item["rel_path"])
    return kept
def _validation_summary(manifest: dict, context: str | None = None) -> dict:
    node = manifest.get("validation")
    if not isinstance(node, dict):
        return {"context": "", "allowed": False, "blocking": [], "accepted_keys": [], "accepted_exceptions": []}
    gate = node.get("gate") if isinstance(node.get("gate"), dict) else {}
    try:
        blocking = gate.get("blocking", []) or []
        codes = []
        for item in blocking:
            if isinstance(item, dict):
                codes.append(str(item.get("code", item.get("exception_id", "?")) or "?"))
            else:
                codes.append(str(item))
        codes = sorted(codes)
    except Exception:
        codes = []
    try:
        keys = node.get("accepted_keys", []) or []
        keys = sorted(str(k) for k in keys)
    except Exception:
        keys = []
    try:
        records = node.get("accepted_exceptions", []) or []
        records = _sorted_list([dict(r) for r in records if isinstance(r, dict)])
    except Exception:
        records = []
    selected_context = str(context or node.get("context", gate.get("context", "")) or "")
    if context:
        try:
            from domain.validation import evaluate_gate
            findings = node.get("findings")
            if not isinstance(findings, list):
                raise ValueError("validation findings must be a list")
            decision = evaluate_gate(
                findings,
                selected_context,
                accepted=records if records else keys,
            )
            gate = decision.to_dict()
            codes = sorted(
                str(item.get("code", item.get("exception_id", "?")) or "?")
                for item in gate.get("blocking", [])
                if isinstance(item, dict)
            )
        except Exception:
            return {
                "context": selected_context,
                "allowed": False,
                "blocking": ["validation.context_recheck_failed"],
                "accepted_keys": keys,
                "accepted_exceptions": records,
            }
    try:
        allowed = bool(gate.get("allowed", False))
    except Exception:
        allowed = False
    return {"context": selected_context, "allowed": allowed, "blocking": codes, "accepted_keys": keys, "accepted_exceptions": records}
def _empty_acceptance() -> dict:
    return {
        "present": False,
        "status": "not_run",
        "identity_hash": "",
        "run_id": "",
        "manifest_identity": "",
        "manifest_profile": "",
        "lock_identity": "",
        "foundation_source_identity": "",
        "foundation_source_identity_algorithm": "",
        "source_identity_conflict": False,
        "acceptance_manifest_evidence": {},
        "report_evidence": {},
        "checklist_summary": {},
    }


def _normalize_acceptance_dict(
    data: dict,
    *,
    report_evidence: dict | None = None,
    checklist_summary: dict | None = None,
) -> dict:
    if not isinstance(data, dict):
        return _empty_acceptance()
    if data.get("present") is False:
        return _empty_acceptance()
    status = str(data.get("status", "unknown") or "unknown")
    identity_hash = str(data.get("identity_hash", "") or "")
    run_id = str(data.get("run_id", "") or "")
    manifest_identity = str(data.get("manifest_identity", "") or "")
    manifest_profile = str(data.get("manifest_profile", "") or "")
    lock_identity = str(data.get("lock_identity", "") or "")
    source_identity = str(data.get("foundation_source_identity", "") or "")
    source_algorithm = str(data.get("foundation_source_identity_algorithm", "") or "")
    source_conflict = bool(data.get("source_identity_conflict", False))
    manifest_evidence = data.get("acceptance_manifest_evidence", {})
    if not isinstance(manifest_evidence, dict):
        manifest_evidence = {}
    stored_report_evidence = data.get("report_evidence", {})
    if not isinstance(stored_report_evidence, dict):
        stored_report_evidence = {}
    stored_checklist_summary = data.get("checklist_summary", {})
    if not isinstance(stored_checklist_summary, dict):
        stored_checklist_summary = {}
    core = data.get("identity_core")
    if isinstance(core, dict):
        core_manifest = str(core.get("manifest_identity", "") or "")
        core_lock = str(core.get("lock_identity", "") or "")
        core_source = str(core.get("foundation_source_identity", "") or "")
        if manifest_identity and core_manifest and manifest_identity != core_manifest:
            source_conflict = True
        if lock_identity and core_lock and lock_identity != core_lock:
            source_conflict = True
        if source_identity and core_source and source_identity != core_source:
            source_conflict = True
        manifest_identity = manifest_identity or core_manifest
        lock_identity = lock_identity or core_lock
        source_identity = source_identity or core_source
    artifact = data.get("artifact")
    if isinstance(artifact, dict):
        inner = artifact.get("manifest")
        if isinstance(inner, dict):
            artifact_manifest = str(inner.get("identity_hash", "") or "")
            artifact_profile = str(inner.get("profile", "") or "")
            artifact_source = inner.get("foundation_source_identity", {})
            artifact_source_hash = (
                str(artifact_source.get("identity_hash", "") or "")
                if isinstance(artifact_source, dict)
                else ""
            )
            artifact_source_algorithm = (
                str(artifact_source.get("algorithm", "") or "")
                if isinstance(artifact_source, dict)
                else ""
            )
            if manifest_identity and artifact_manifest and manifest_identity != artifact_manifest:
                source_conflict = True
            if source_identity and artifact_source_hash and source_identity != artifact_source_hash:
                source_conflict = True
            manifest_identity = manifest_identity or artifact_manifest
            manifest_profile = manifest_profile or artifact_profile
            source_identity = source_identity or artifact_source_hash
            source_algorithm = source_algorithm or artifact_source_algorithm
        lock = artifact.get("lock")
        if isinstance(lock, dict):
            artifact_lock = str(lock.get("identity_hash", "") or "")
            if lock_identity and artifact_lock and lock_identity != artifact_lock:
                source_conflict = True
            lock_identity = lock_identity or artifact_lock
    return {
        "present": True,
        "status": status,
        "identity_hash": identity_hash,
        "run_id": run_id,
        "manifest_identity": manifest_identity,
        "manifest_profile": manifest_profile,
        "lock_identity": lock_identity,
        "foundation_source_identity": source_identity,
        "foundation_source_identity_algorithm": source_algorithm,
        "source_identity_conflict": source_conflict,
        "acceptance_manifest_evidence": _deepcopy(manifest_evidence),
        "report_evidence": _deepcopy(report_evidence or stored_report_evidence),
        "checklist_summary": _deepcopy(checklist_summary or stored_checklist_summary),
    }


def _bridge_legacy_acceptance_source_identity(
    data: dict,
    info: dict,
    acceptance_manifest_path,
) -> dict:
    """Bind a legacy report to its unchanged acceptance manifest inventory entry."""
    if str(info.get("foundation_source_identity", "") or "").strip():
        return info
    if acceptance_manifest_path is None:
        return info
    candidate = Path(acceptance_manifest_path)
    if not candidate.is_file():
        raise FoundationFreezeError("acceptance manifest not found: %s" % candidate)
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise FoundationFreezeError("cannot read acceptance manifest %s: %s" % (candidate, exc)) from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    artifact = data.get("artifact") if isinstance(data, dict) else None
    inventory = artifact.get("files") if isinstance(artifact, dict) else None
    if not isinstance(inventory, list):
        raise FoundationFreezeError(
            "legacy acceptance report has no artifact inventory for foundation_manifest.json"
        )
    matches = [
        entry
        for entry in inventory
        if isinstance(entry, dict)
        and _normalize_rel(entry.get("rel_path")) == "foundation_manifest.json"
    ]
    if len(matches) != 1:
        raise FoundationFreezeError(
            "legacy acceptance report must capture exactly one foundation_manifest.json inventory entry"
        )
    captured = matches[0]
    captured_sha256 = str(captured.get("sha256", "") or "").strip().lower()
    if not captured_sha256 or captured_sha256 != actual_sha256:
        raise FoundationFreezeError(
            "acceptance manifest SHA-256 does not match the legacy report artifact inventory"
        )
    try:
        captured_size = int(captured.get("size", -1))
    except (TypeError, ValueError):
        captured_size = -1
    if captured_size != len(raw):
        raise FoundationFreezeError(
            "acceptance manifest size does not match the legacy report artifact inventory"
        )
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FoundationFreezeError("malformed JSON in acceptance manifest %s" % candidate) from exc
    acceptance_manifest = _require_manifest(parsed, "acceptance manifest")
    if str(acceptance_manifest.get("profile", "") or "") != "acceptance":
        raise FoundationFreezeError("acceptance manifest is not an acceptance export")
    supplied_manifest_identity = _manifest_identity(acceptance_manifest)
    recorded_manifest_identity = str(info.get("manifest_identity", "") or "")
    if not recorded_manifest_identity or supplied_manifest_identity != recorded_manifest_identity:
        raise FoundationFreezeError(
            "acceptance manifest identity %s does not match the legacy report identity %s"
            % (supplied_manifest_identity or "<missing>", recorded_manifest_identity or "<missing>")
        )
    source_identity = _manifest_foundation_source_identity(acceptance_manifest, "acceptance manifest")
    bridged = dict(info)
    bridged["manifest_profile"] = "acceptance"
    bridged["foundation_source_identity"] = source_identity["identity_hash"]
    bridged["foundation_source_identity_algorithm"] = source_identity["algorithm"]
    bridged["acceptance_manifest_evidence"] = {
        "rel_path": "foundation_manifest.json",
        "sha256": actual_sha256,
        "size": len(raw),
        "manifest_identity": supplied_manifest_identity,
        "profile": "acceptance",
    }
    return bridged


def _acceptance_validation_reasons(
    info: dict,
    foundation_source_identity: dict,
    lock_source_identity: dict | None = None,
    lock_identity: str = "",
) -> list[str]:
    """Validate an optional acceptance record when it is supplied for freeze."""
    if not isinstance(info, dict) or not info.get("present"):
        return []
    reasons = []
    status = str(info.get("status", "") or "").strip().lower()
    if status not in ACCEPTANCE_SUCCESS_STATUSES:
        reasons.append("engine acceptance record is not successful (status=%r)" % status)
    if not str(info.get("identity_hash", "") or "").strip():
        reasons.append("engine acceptance record has no identity_hash")
    if bool(info.get("source_identity_conflict", False)):
        reasons.append("engine acceptance record has conflicting identity evidence")
    record_manifest = str(info.get("manifest_identity", "") or "").strip()
    if not record_manifest:
        reasons.append("engine acceptance record has no manifest identity")
    record_profile = str(info.get("manifest_profile", "") or "").strip()
    if record_profile != "acceptance":
        reasons.append("engine acceptance record is not tied to an acceptance-profile manifest")
    expected_source = str(foundation_source_identity.get("identity_hash", "") or "").strip()
    expected_algorithm = str(foundation_source_identity.get("algorithm", "") or "").strip()
    lock_source_identity = lock_source_identity if isinstance(lock_source_identity, dict) else {}
    lock_source = str(lock_source_identity.get("identity_hash", "") or "").strip()
    lock_algorithm = str(lock_source_identity.get("algorithm", "") or "").strip()
    record_source = str(info.get("foundation_source_identity", "") or "").strip()
    record_algorithm = str(info.get("foundation_source_identity_algorithm", "") or "").strip()
    if not record_source:
        reasons.append(
            "engine acceptance record has no foundation source identity; legacy reports require --acceptance-manifest"
        )
    elif record_source != expected_source:
        reasons.append(
            "acceptance foundation source identity %s does not match foundation manifest %s"
            % (record_source, expected_source)
        )
    if not record_algorithm:
        reasons.append("engine acceptance record has no foundation source identity algorithm")
    elif record_algorithm != expected_algorithm:
        reasons.append(
            "acceptance foundation source identity algorithm %s does not match foundation manifest %s"
            % (record_algorithm, expected_algorithm)
        )
    if lock_source and record_source and record_source != lock_source:
        reasons.append(
            "acceptance foundation source identity %s does not match frozen lock %s"
            % (record_source, lock_source)
        )
    if lock_algorithm and record_algorithm and record_algorithm != lock_algorithm:
        reasons.append(
            "acceptance foundation source identity algorithm %s does not match frozen lock %s"
            % (record_algorithm, lock_algorithm)
        )
    record_lock = str(info.get("lock_identity", "") or "").strip()
    if record_lock and record_lock != str(lock_identity or ""):
        reasons.append("acceptance record lock identity %s does not match frozen lock %s" % (record_lock, lock_identity))
    return reasons
def _acceptance_identity_from_manifest(manifest: dict) -> dict:
    """Do not promote an unvalidated manifest summary into acceptance evidence."""
    return _empty_acceptance()
def _acceptance_from_file(path, acceptance_manifest_path=None) -> dict:
    if not path:
        return _empty_acceptance()
    candidate = Path(path)
    if candidate.is_dir():
        candidate = candidate / freeze_contract.ACCEPTANCE_FILENAME
    if not candidate.is_file():
        return _empty_acceptance()
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise FoundationFreezeError("cannot read acceptance record %s: %s" % (candidate, exc)) from exc
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FoundationFreezeError("malformed JSON in acceptance record %s" % candidate) from exc
    if not isinstance(data, dict):
        raise FoundationFreezeError("malformed acceptance record: expected a JSON object")
    try:
        from services.engine_acceptance_service import summarize_checklist, validate_result_integrity
        entries = validate_result_integrity(data)
        checklist_summary = summarize_checklist(entries)
    except (ImportError, ValueError, TypeError) as exc:
        raise FoundationFreezeError("acceptance report integrity check failed: %s" % exc) from exc
    report_evidence = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "created_at": str(data.get("created_at", "") or ""),
        "schema": str(data.get("schema", "") or ""),
    }
    info = _normalize_acceptance_dict(
        data,
        report_evidence=report_evidence,
        checklist_summary=checklist_summary,
    )
    return _bridge_legacy_acceptance_source_identity(data, info, acceptance_manifest_path)
def _geography_section(manifest: dict) -> dict:
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    try:
        province_ids = int(counts.get("province_ids", 0) or 0)
    except (TypeError, ValueError):
        province_ids = 0
    try:
        province_max = int(counts.get("province_max", 0) or 0)
    except (TypeError, ValueError):
        province_max = 0
    try:
        map_pixels = int(counts.get("map_pixels", 0) or 0)
    except (TypeError, ValueError):
        map_pixels = 0
    managers = counts.get("managers") if isinstance(counts.get("managers"), dict) else {}
    filtered = {}
    for key in ("state_mgr", "continent_mgr", "adjacency_mgr", "railway_mgr", "supply_mgr", "adjacency_rule_mgr", "strategic_region_mgr"):
        value = managers.get(key)
        try:
            filtered[key] = None if value is None else int(value)
        except (TypeError, ValueError):
            filtered[key] = value
    return {"province_ids": province_ids, "province_max": province_max, "map_pixels": map_pixels, "stable_id_range": {"min": 1 if province_ids else 0, "max": province_max}, "managers": filtered}
def _deepcopy(value):
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _foundation_source_sections(sources: dict) -> dict:
    """Keep only source identities owned by the foundation contract."""
    if not isinstance(sources, dict):
        sources = {}
    arrays = sources.get("arrays") if isinstance(sources.get("arrays"), dict) else {}
    managers = sources.get("managers") if isinstance(sources.get("managers"), dict) else {}
    auxiliary = sources.get("auxiliary") if isinstance(sources.get("auxiliary"), dict) else {}
    return {
        "arrays": _deepcopy(dict(arrays)),
        "managers": {
            key: _deepcopy(managers[key])
            for key in FOUNDATION_MANAGER_KEYS
            if key in managers
        },
        "auxiliary": {
            key: _deepcopy(auxiliary[key])
            for key in FOUNDATION_AUXILIARY_KEYS
            if key in auxiliary
        },
    }


def _foundation_counts(counts: dict) -> dict:
    """Keep stable counts without acceptance-only country/gameplay counts."""
    if not isinstance(counts, dict):
        counts = {}
    managers = counts.get("managers") if isinstance(counts.get("managers"), dict) else {}
    return {
        key: _deepcopy(counts[key])
        for key in ("province_ids", "province_max", "map_pixels")
        if key in counts
    } | {
        "managers": {
            key: _deepcopy(managers[key])
            for key in FOUNDATION_MANAGER_KEYS
            if key in managers
        }
    }


def build_expanded_lock(manifest, artifact_dir=None, acceptance=None, acceptance_path=None, lifecycle="candidate", created_at=None, tool_version=None) -> dict:
    manifest = _require_manifest(dict(manifest), "foundation manifest")
    source_identity = _manifest_foundation_source_identity(manifest, "foundation manifest")
    constants = _lock_constants()
    now = str(created_at or _utc_now_iso())
    tool = str(tool_version or _tool_version())
    if lifecycle not in ("draft", "candidate", "frozen"):
        lifecycle = "candidate"
    identity_node = manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
    target_node = manifest.get("target") if isinstance(manifest.get("target"), dict) else {}
    target_identity = target_node.get("identity") if isinstance(target_node.get("identity"), dict) else {}
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    size = manifest.get("map_size") if isinstance(manifest.get("map_size"), dict) else {}
    sources = manifest.get("sources") if isinstance(manifest.get("sources"), dict) else {}
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    if acceptance is not None:
        acceptance_info = _normalize_acceptance_dict(dict(acceptance))
    elif acceptance_path is not None:
        acceptance_info = _acceptance_from_file(acceptance_path)
    elif artifact_dir is not None:
        candidate_file = Path(artifact_dir) / freeze_contract.ACCEPTANCE_FILENAME
        if candidate_file.is_file():
            acceptance_info = _acceptance_from_file(candidate_file)
        else:
            acceptance_info = _acceptance_identity_from_manifest(manifest)
    else:
        acceptance_info = _acceptance_identity_from_manifest(manifest)
    validation_context = {
        "candidate": "foundation_candidate",
        "frozen": "freeze",
    }.get(lifecycle)
    lock = {"lock_schema": constants["lock_schema"], "lock_version": constants["lock_version"], "manifest_schema": constants["manifest_schema"], "manifest_version": constants["manifest_version"], "freeze_schema": freeze_contract.FREEZE_SCHEMA, "freeze_version": freeze_contract.FREEZE_VERSION, "metadata": {"tool_version": tool, "created_at": now, "generator": constants["generator"]}, "tool_version": tool, "lifecycle": lifecycle, "profile": str(manifest.get("profile", "")), "target": {"identity": _deepcopy(dict(target_identity))}, "project": _deepcopy(dict(project)), "game_profile": manifest.get("game_profile"), "game_profile_detail": _deepcopy(manifest.get("game_profile_detail")), "snapshot_fingerprint": str(manifest.get("snapshot_fingerprint", "") or ""), "map_size": _deepcopy(dict(size)), "identity": _deepcopy(dict(identity_node)), "foundation_source_identity": _deepcopy(source_identity), "sources": _foundation_source_sections(sources), "counts": _foundation_counts(counts), "geography": _geography_section(manifest), "assets": _filter_foundation_assets(manifest), "outputs": _filter_foundation_outputs(manifest), "validation": _validation_summary(manifest, validation_context), "engine_acceptance": dict(acceptance_info), "history": []}
    return lock
def freeze_canonical_dict(lock: dict) -> dict:
    if not isinstance(lock, dict):
        return {}
    try:
        data = copy.deepcopy(dict(lock))
    except Exception:
        data = dict(lock)
    data.pop("metadata", None)
    data.pop("created_at", None)
    return data
def freeze_canonical_json(lock: dict) -> str:
    return json.dumps(freeze_canonical_dict(lock), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def _write_json_atomic(path, payload: dict) -> str:
    destination = Path(path)
    if destination.parent and str(destination.parent):
        destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp_path = destination.with_name(destination.name + ".tmp-%d" % os.getpid())
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(str(tmp_path), str(destination))
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
    return str(destination)
def _manifest_gate_blocked(manifest: dict, context: str):
    summary = _validation_summary(manifest, context)
    if summary.get("allowed") and not summary.get("blocking"):
        return False, []
    reasons = []
    for code in summary.get("blocking", []):
        reasons.append("blocking validation finding: %s" % code)
    if not reasons:
        reasons.append("manifest validation gate is not allowed")
    return True, reasons
def _check_artifact_manifest(artifact_dir, manifest: dict):
    if artifact_dir is None:
        return False, []
    root = Path(artifact_dir)
    if not root.exists() or not root.is_dir():
        return True, ["artifact directory is missing: %s" % root]
    expected = _manifest_identity(manifest)
    disk_path = root / freeze_contract.MANIFEST_FILENAME
    if not disk_path.is_file():
        return True, ["artifact manifest is missing: %s" % disk_path]
    try:
        disk_manifest = _read_json_file(disk_path)
        disk_identity = _manifest_identity(disk_manifest)
    except FoundationFreezeError as exc:
        return True, ["artifact manifest unreadable: %s" % exc]
    if disk_identity != expected:
        return True, ["artifact manifest identity %s does not match expected %s" % (disk_identity or "<missing>", expected)]
    return False, []
def create_candidate(manifest_path, lock_path, artifact_dir=None, created_at=None) -> dict:
    manifest = load_manifest(manifest_path)
    if str(manifest.get("profile", "")) != "foundation":
        return {"ok": False, "reasons": ["artifact is not a foundation export (profile=%r)" % str(manifest.get("profile", ""))], "lock_path": str(lock_path), "identity_hash": _manifest_identity(manifest)}
    blocked, reasons = _manifest_gate_blocked(manifest, "foundation_candidate")
    if blocked:
        return {"ok": False, "reasons": reasons, "lock_path": str(lock_path), "identity_hash": _manifest_identity(manifest)}
    artifact_blocked, artifact_reasons = _check_artifact_manifest(artifact_dir, manifest)
    if artifact_blocked:
        return {"ok": False, "reasons": artifact_reasons, "lock_path": str(lock_path), "identity_hash": _manifest_identity(manifest)}
    lock = build_expanded_lock(manifest, artifact_dir=artifact_dir, lifecycle="candidate", created_at=created_at)
    written = _write_json_atomic(lock_path, lock)
    return {"ok": True, "reasons": [], "lock_path": written, "identity_hash": _manifest_identity(manifest)}
def _load_candidate_lock(lock_path):
    return load_lock(lock_path)
def _lock_foundation_source_identity(lock: dict) -> dict:
    node = lock.get("foundation_source_identity") if isinstance(lock, dict) else None
    if not isinstance(node, dict):
        return {"identity_hash": "", "algorithm": ""}
    return {
        "identity_hash": str(node.get("identity_hash", "") or "").strip(),
        "algorithm": str(node.get("algorithm", "") or "").strip(),
    }


def freeze_foundation(
    manifest_path,
    lock_path,
    artifact_dir=None,
    acceptance_path=None,
    acceptance_manifest_path=None,
    handoff_path=None,
    created_at=None,
) -> dict:
    manifest = load_manifest(manifest_path)
    if str(manifest.get("profile", "")) != "foundation":
        return {"ok": False, "reasons": ["artifact is not a foundation export (profile=%r)" % str(manifest.get("profile", ""))], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": _manifest_identity(manifest)}
    try:
        candidate = _load_candidate_lock(lock_path)
    except FoundationFreezeError as exc:
        return {"ok": False, "reasons": ["candidate lock required before freeze: %s" % exc], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": _manifest_identity(manifest)}
    if str(candidate.get("lifecycle", "")) != "candidate":
        return {"ok": False, "reasons": ["candidate lock required before freeze (lifecycle=%r)" % str(candidate.get("lifecycle", ""))], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": _manifest_identity(manifest)}
    expected_identity = _manifest_identity(candidate)
    current_identity = _manifest_identity(manifest)
    current_source_identity = _manifest_foundation_source_identity(
        manifest, "foundation manifest"
    )
    candidate_source_identity = _lock_foundation_source_identity(candidate)
    if current_identity != expected_identity:
        return {"ok": False, "reasons": ["exact artifact identity mismatch: manifest %s != candidate %s" % (current_identity, expected_identity)], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    if (
        not candidate_source_identity["identity_hash"]
        or current_source_identity != candidate_source_identity
    ):
        return {"ok": False, "reasons": ["exact foundation source identity mismatch between manifest and candidate lock"], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    if str(manifest.get("snapshot_fingerprint", "") or "") != str(candidate.get("snapshot_fingerprint", "") or ""):
        return {"ok": False, "reasons": ["exact artifact identity mismatch: snapshot fingerprint changed since candidate"], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    blocked, reasons = _manifest_gate_blocked(manifest, "freeze")
    if blocked:
        return {"ok": False, "reasons": reasons, "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    artifact_blocked, artifact_reasons = _check_artifact_manifest(artifact_dir, manifest)
    if artifact_blocked:
        return {"ok": False, "reasons": artifact_reasons, "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    acceptance_info = None
    acceptance_source = None
    if acceptance_path is not None:
        candidate_acceptance = Path(acceptance_path)
        if candidate_acceptance.is_dir():
            candidate_acceptance = candidate_acceptance / freeze_contract.ACCEPTANCE_FILENAME
        if candidate_acceptance.is_file():
            acceptance_source = str(candidate_acceptance)
        else:
            return {"ok": False, "reasons": ["acceptance record not found: %s" % acceptance_path], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    elif artifact_dir is not None:
        disk_acceptance = Path(artifact_dir) / freeze_contract.ACCEPTANCE_FILENAME
        if disk_acceptance.is_file():
            acceptance_source = str(disk_acceptance)
    if acceptance_source is not None:
        try:
            acceptance_info = _acceptance_from_file(
                acceptance_source,
                acceptance_manifest_path,
            )
        except FoundationFreezeError as exc:
            return {"ok": False, "reasons": ["acceptance record unreadable: %s" % exc], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    else:
        acceptance_info = _acceptance_identity_from_manifest(manifest)
    acceptance_reasons = _acceptance_validation_reasons(
        acceptance_info,
        current_source_identity,
        candidate_source_identity,
        expected_identity,
    )
    if acceptance_reasons:
        return {"ok": False, "reasons": acceptance_reasons, "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    lock = build_expanded_lock(manifest, artifact_dir=artifact_dir, acceptance=acceptance_info, acceptance_path=acceptance_source, lifecycle="frozen", created_at=created_at)
    written = _write_json_atomic(lock_path, lock)
    if handoff_path is None:
        handoff_path = str(Path(lock_path).parent / freeze_contract.HANDOFF_FILENAME)
    handoff_text = generate_handoff(lock, manifest)
    destination = Path(handoff_path)
    if destination.parent and str(destination.parent):
        destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_handoff = destination.with_name(destination.name + ".tmp-%d" % os.getpid())
    try:
        tmp_handoff.write_text(handoff_text, encoding="utf-8")
        os.replace(str(tmp_handoff), str(destination))
    finally:
        try:
            if tmp_handoff.exists():
                tmp_handoff.unlink()
        except OSError:
            pass
    return {"ok": True, "reasons": [], "lock_path": written, "handoff_path": str(destination), "identity_hash": current_identity}


def record_engine_acceptance(
    lock_path,
    manifest_path,
    acceptance_path,
    acceptance_manifest_path=None,
    handoff_path=None,
    created_at=None,
) -> dict:
    """Attach a successful acceptance run to an exact frozen lock."""
    frozen = load_lock(lock_path)
    manifest = load_manifest(manifest_path)
    if str(frozen.get("profile", "")) != "foundation":
        return {"ok": False, "reasons": ["lock is not a foundation lock"], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": _manifest_identity(manifest)}
    if str(frozen.get("lifecycle", "")) != "frozen":
        return {"ok": False, "reasons": ["engine acceptance can only be recorded for a frozen lock"], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": _manifest_identity(manifest)}
    current_identity = _manifest_identity(manifest)
    lock_identity = _manifest_identity(frozen)
    current_source_identity = _manifest_foundation_source_identity(
        manifest, "foundation manifest"
    )
    lock_source_identity = _lock_foundation_source_identity(frozen)
    if current_identity != lock_identity:
        return {"ok": False, "reasons": ["exact artifact identity mismatch: manifest %s != frozen lock %s" % (current_identity, lock_identity)], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    if (
        not lock_source_identity["identity_hash"]
        or current_source_identity != lock_source_identity
    ):
        return {"ok": False, "reasons": ["exact foundation source identity mismatch between manifest and frozen lock"], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    acceptance_file = Path(acceptance_path)
    if acceptance_file.is_dir():
        acceptance_file = acceptance_file / freeze_contract.ACCEPTANCE_FILENAME
    if not acceptance_file.is_file():
        return {"ok": False, "reasons": ["acceptance record not found: %s" % acceptance_file], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    try:
        acceptance = _acceptance_from_file(
            acceptance_file,
            acceptance_manifest_path,
        )
    except FoundationFreezeError as exc:
        return {"ok": False, "reasons": ["acceptance record unreadable: %s" % exc], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    if not acceptance.get("present"):
        return {"ok": False, "reasons": ["acceptance record is absent"], "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    reasons = _acceptance_validation_reasons(
        acceptance,
        current_source_identity,
        lock_source_identity,
        lock_identity,
    )
    if reasons:
        return {"ok": False, "reasons": reasons, "lock_path": str(lock_path), "handoff_path": str(handoff_path or ""), "identity_hash": current_identity}
    updated = _deepcopy(frozen)
    updated["engine_acceptance"] = acceptance
    history = updated.get("history")
    if not isinstance(history, list):
        history = []
    history.append({
        "event": "record_engine_acceptance",
        "at": str(created_at or _utc_now_iso()),
        "run_id": str(acceptance.get("run_id", "") or ""),
        "identity_hash": str(acceptance.get("identity_hash", "") or ""),
        "manifest_identity": current_identity,
        "foundation_source_identity": current_source_identity["identity_hash"],
    })
    history.sort(key=lambda item: json.dumps(item, ensure_ascii=True, sort_keys=True, default=str))
    updated["history"] = history
    written = _write_json_atomic(lock_path, updated)
    if handoff_path is None:
        handoff_path = str(Path(lock_path).parent / freeze_contract.HANDOFF_FILENAME)
    handoff = Path(handoff_path)
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff_tmp = handoff.with_name(handoff.name + ".tmp-%d" % os.getpid())
    try:
        handoff_tmp.write_text(generate_handoff(updated, manifest), encoding="utf-8")
        os.replace(str(handoff_tmp), str(handoff))
    finally:
        try:
            if handoff_tmp.exists():
                handoff_tmp.unlink()
        except OSError:
            pass
    return {"ok": True, "reasons": [], "lock_path": written, "handoff_path": str(handoff), "identity_hash": current_identity, "run_id": str(acceptance.get("run_id", "") or "")}


def _flatten_dict(node, prefix: str, out: dict) -> None:
    if isinstance(node, dict):
        if not node:
            out[prefix] = {}
            return
        for key in sorted(node, key=lambda k: str(k)):
            child_prefix = ("%s.%s" % (prefix, key)) if prefix else str(key)
            _flatten_dict(node[key], child_prefix, out)
        return
    out[prefix] = node
def _lock_leaf_paths(lock: dict) -> dict:
    leaves = {}
    for section in ("profile", "snapshot_fingerprint", "identity", "foundation_source_identity", "target", "project", "game_profile", "game_profile_detail", "map_size", "sources", "counts", "geography", "validation", "engine_acceptance", "lifecycle"):
        if section in lock:
            if section in ("profile", "snapshot_fingerprint", "lifecycle", "game_profile"):
                leaves[section] = lock.get(section)
            else:
                _flatten_dict(lock.get(section), section, leaves)
    for section in ("assets", "outputs"):
        entries = lock.get(section) or []
        if not isinstance(entries, list):
            leaves[section] = entries
            continue
        if not entries:
            leaves[section] = []
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rel = _normalize_rel(entry.get("rel_path"))
            if not rel:
                continue
            for field_name in sorted(entry, key=lambda k: str(k)):
                if str(field_name) == "rel_path":
                    continue
                leaves["%s.%s.%s" % (section, rel, field_name)] = entry.get(field_name)
        known = sorted(_normalize_rel(e.get("rel_path")) for e in entries if isinstance(e, dict) and _normalize_rel(e.get("rel_path")))
        leaves["%s.__paths__" % section] = known
    return leaves
def _json_equal(first, second) -> bool:
    try:
        return json.dumps(first, ensure_ascii=True, sort_keys=True, default=str) == json.dumps(second, ensure_ascii=True, sort_keys=True, default=str)
    except Exception:
        return first == second
def compare_with_frozen_lock(manifest, lock, artifact_dir=None, acceptance_path=None) -> dict:
    if isinstance(manifest, (str, Path)):
        current_manifest = load_manifest(manifest)
    elif isinstance(manifest, dict):
        current_manifest = _require_manifest(dict(manifest), "foundation manifest")
    else:
        raise FoundationFreezeError("malformed foundation manifest: expected a JSON object")
    if isinstance(lock, (str, Path)):
        frozen = load_lock(lock)
    elif isinstance(lock, dict):
        frozen = dict(lock)
        if not _manifest_identity(frozen):
            raise FoundationFreezeError("foundation lock has no identity.identity_hash")
    else:
        raise FoundationFreezeError("malformed foundation lock: expected a JSON object")
    current = build_expanded_lock(current_manifest, artifact_dir=artifact_dir, acceptance_path=acceptance_path, lifecycle=str(frozen.get("lifecycle", "frozen") or "frozen"))
    if acceptance_path is None and not _acceptance_identity_from_manifest(current_manifest).get("present"):
        # Acceptance is an attached record, not ordinary manifest content. A
        # compare without a new record must not make an otherwise identical
        # frozen foundation look changed merely because the manifest predates
        # the recorded run.
        current["engine_acceptance"] = _deepcopy(frozen.get("engine_acceptance", current.get("engine_acceptance", {})))
    frozen_leaves = _lock_leaf_paths(frozen)
    current_leaves = _lock_leaf_paths(current)
    volatile = {"metadata", "metadata.tool_version", "metadata.created_at", "metadata.generator", "tool_version", "history", "assets.__paths__", "outputs.__paths__"}
    paths = sorted(set(frozen_leaves) | set(current_leaves))
    differences = []
    for path in paths:
        if path in volatile or path.startswith("history."):
            continue
        old = frozen_leaves.get(path, "__missing__")
        new = current_leaves.get(path, "__missing__")
        if old == "__missing__":
            old_value = None
            new_value = new
        elif new == "__missing__":
            old_value = old
            new_value = None
        elif _json_equal(old, new):
            continue
        else:
            old_value = old
            new_value = new
        info = freeze_contract.classify_lock_path(path)
        try:
            old_copy = _deepcopy(old_value)
        except Exception:
            old_copy = old_value
        try:
            new_copy = _deepcopy(new_value)
        except Exception:
            new_copy = new_value
        differences.append({"path": path, "change_class": info["change_class"], "breaking": bool(info["breaking"]), "summary": freeze_contract.explain_difference(path, old_value, new_value), "lock": old_copy, "manifest": new_copy, "rerun": info["rerun"]})
    differences.sort(key=lambda item: str(item.get("path", "")))
    breaking = any(bool(item.get("breaking")) for item in differences)
    if breaking:
        status = "breaking"
    elif differences:
        status = "mismatch"
    else:
        status = "compatible"
    return {"breaking": breaking, "differences": differences, "status": status, "lock_identity": _manifest_identity(frozen), "manifest_identity": _manifest_identity(current_manifest)}
def unfreeze_lock(lock_path, reason, audit_path=None, created_at=None) -> dict:
    text = str(reason or "").strip()
    if not text:
        raise FoundationFreezeError("unfreeze requires a non-empty reason")
    frozen = load_lock(lock_path)
    if str(frozen.get("lifecycle", "")) != "frozen":
        return {"ok": False, "reasons": ["lock is not frozen (lifecycle=%r)" % str(frozen.get("lifecycle", ""))], "lock_path": str(lock_path), "audit_path": str(audit_path or ""), "reason": text}
    now = str(created_at or _utc_now_iso())
    updated = _deepcopy(frozen)
    updated["lifecycle"] = "candidate"
    history = updated.get("history")
    if not isinstance(history, list):
        history = []
    event = {"event": "unfreeze", "at": now, "reason": text, "previous_lifecycle": "frozen", "previous_identity": _manifest_identity(frozen)}
    history = list(history) + [event]
    history.sort(key=lambda item: json.dumps(item, ensure_ascii=True, sort_keys=True, default=str))
    updated["history"] = history
    written = _write_json_atomic(lock_path, updated)
    if audit_path is None:
        audit_path = str(Path(lock_path).parent / freeze_contract.AUDIT_FILENAME)
    audit_file = Path(audit_path)
    if audit_file.parent and str(audit_file.parent):
        audit_file.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if audit_file.is_file():
        try:
            raw = json.loads(audit_file.read_text(encoding="utf-8-sig"))
            if isinstance(raw, list):
                existing = [dict(e) for e in raw if isinstance(e, dict)]
        except (OSError, ValueError):
            existing = []
    record = dict(event)
    record["lock_path"] = str(Path(lock_path).name)
    record["identity_hash"] = _manifest_identity(frozen)
    existing.append(record)
    existing.sort(key=lambda item: json.dumps(item, ensure_ascii=True, sort_keys=True, default=str))
    tmp_audit = audit_file.with_name(audit_file.name + ".tmp-%d" % os.getpid())
    try:
        tmp_audit.write_text(json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(str(tmp_audit), str(audit_file))
    finally:
        try:
            if tmp_audit.exists():
                tmp_audit.unlink()
        except OSError:
            pass
    return {"ok": True, "reasons": [], "lock_path": written, "audit_path": str(audit_file), "reason": text}
def _handoff_line_list(items: list, empty: str = "none") -> str:
    if not items:
        return empty
    return ", ".join(str(v) for v in items)
def generate_handoff(lock: dict, manifest=None) -> str:
    if not isinstance(lock, dict) or not _manifest_identity(lock):
        raise FoundationFreezeError("foundation lock has no identity.identity_hash")
    identity = lock.get("identity") if isinstance(lock.get("identity"), dict) else {}
    size = lock.get("map_size") if isinstance(lock.get("map_size"), dict) else {}
    target = lock.get("target") if isinstance(lock.get("target"), dict) else {}
    target_identity = target.get("identity") if isinstance(target.get("identity"), dict) else {}
    geography = lock.get("geography") if isinstance(lock.get("geography"), dict) else {}
    validation = lock.get("validation") if isinstance(lock.get("validation"), dict) else {}
    acceptance = lock.get("engine_acceptance") if isinstance(lock.get("engine_acceptance"), dict) else {}
    outputs = lock.get("outputs") if isinstance(lock.get("outputs"), list) else []
    assets = lock.get("assets") if isinstance(lock.get("assets"), list) else []
    meta = lock.get("metadata") if isinstance(lock.get("metadata"), dict) else {}
    width = size.get("width", "?")
    height = size.get("height", "?")
    province_ids = geography.get("province_ids", "?")
    province_max = geography.get("province_max", "?")
    id_range = geography.get("stable_id_range", {"min": 1, "max": province_max})
    managers = geography.get("managers", {}) if isinstance(geography.get("managers"), dict) else {}
    accepted_keys = validation.get("accepted_keys", []) or []
    accepted_records = validation.get("accepted_exceptions", []) or []
    by_stage = {}
    for entry in outputs:
        if not isinstance(entry, dict):
            continue
        stage = str(entry.get("stage", "unowned") or "unowned")
        by_stage.setdefault(stage, []).append(str(entry.get("rel_path", "")))
    for stage in by_stage:
        by_stage[stage] = sorted(by_stage[stage])
    lines = []
    lines.append("# Foundation Handoff")
    lines.append("")
    lines.append("Target: %s | Profile: %s | Identity: %s" % (str(target_identity.get("game_profile", lock.get("game_profile", "?")) or "?"), str(lock.get("profile", "?")), str(identity.get("identity_hash", ""))))
    lines.append("Algorithm: %s | Tool: %s | Frozen at: %s" % (str(identity.get("algorithm", "") or ""), str(meta.get("tool_version", lock.get("tool_version", "")) or ""), str(meta.get("created_at", "") or "")))
    lines.append("")
    lines.append("## Target, profile, version, and dependencies")
    lines.append("")
    lines.append("- game profile: %s" % str(lock.get("game_profile", "?")))
    lines.append("- export profile: %s (foundation-only; acceptance content is not part of this lock)" % str(lock.get("profile", "?")))
    lines.append("- snapshot fingerprint: %s" % str(lock.get("snapshot_fingerprint", "")))
    lines.append("- target identity:")
    for key in sorted(target_identity, key=lambda k: str(k)):
        lines.append("  - %s: %s" % (key, target_identity[key]))
    lines.append("- required dependencies: base game install matching the locked target identity; no Workshop payload is part of the foundation")
    lines.append("")
    lines.append("## Dimensions and stable ID ranges")
    lines.append("")
    lines.append("- map size: %s x %s" % (width, height))
    lines.append("- province IDs present: %s; maximum province ID: %s" % (province_ids, province_max))
    if isinstance(id_range, dict):
        lines.append("- stable ID range: %s to %s (never compact IDs silently after freeze)" % (id_range.get("min", 1), id_range.get("max", province_max)))
    else:
        lines.append("- stable ID range: 1 to %s (never compact IDs silently after freeze)" % province_max)
    lines.append("- manager counts:")
    for key in sorted(managers, key=lambda k: str(k)):
        lines.append("  - %s: %s" % (key, managers[key]))
    lines.append("")
    lines.append("## Ownership and inheritance")
    lines.append("")
    if by_stage:
        for stage in sorted(by_stage):
            lines.append("- %s (%d files):" % (stage, len(by_stage[stage])))
            for rel in by_stage[stage][:50]:
                lines.append("  - %s" % rel)
            if len(by_stage[stage]) > 50:
                lines.append("  - ... (%d more)" % (len(by_stage[stage]) - 50))
    else:
        lines.append("- no foundation-owned outputs recorded")
    lines.append("- foundation-owned asset resolutions locked: %d" % len(assets))
    for entry in assets[:50]:
        if isinstance(entry, dict):
            lines.append("  - %s [%s]" % (entry.get("rel_path", "?"), entry.get("disposition", "?")))
    if len(assets) > 50:
        lines.append("  - ... (%d more)" % (len(assets) - 50))
    lines.append("- acceptance-only content (history/countries, common/*, localisation, gfx/flags) is excluded from this lock and stays inheritable downstream")
    lines.append("")
    lines.append("## Accepted exceptions")
    lines.append("")
    lines.append("- validation context: %s; allowed: %s" % (str(validation.get("context", "") or ""), bool(validation.get("allowed", False))))
    lines.append("- accepted keys: %s" % _handoff_line_list(sorted(str(k) for k in accepted_keys)))
    if accepted_records:
        for record in accepted_records:
            if isinstance(record, dict):
                label = str(record.get("exception_id", record.get("id", record.get("code", "?"))))
                lines.append("  - %s: %s" % (label, json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)))
    else:
        lines.append("- no accepted exceptions recorded")
    blocking = validation.get("blocking", []) or []
    lines.append("- blocking findings at freeze: %s" % _handoff_line_list(blocking))
    if isinstance(acceptance, dict) and acceptance.get("present"):
        lines.append("- engine acceptance: status=%s run=%s identity=%s manifest=%s" % (acceptance.get("status", "?"), acceptance.get("run_id", "?"), acceptance.get("identity_hash", "?"), acceptance.get("manifest_identity", "?")))
        report_evidence = acceptance.get("report_evidence", {})
        if isinstance(report_evidence, dict) and report_evidence.get("sha256"):
            lines.append(
                "- acceptance report evidence: sha256=%s size=%s created=%s"
                % (
                    report_evidence.get("sha256", "?"),
                    report_evidence.get("size", "?"),
                    report_evidence.get("created_at", "?"),
                )
            )
        checklist = acceptance.get("checklist_summary", {})
        if isinstance(checklist, dict):
            lines.append(
                "- acceptance checklist: checked=%s waived=%s missing=%s"
                % (
                    checklist.get("checked", 0),
                    checklist.get("waived", 0),
                    _handoff_line_list(checklist.get("missing", []) or []),
                )
            )
            for waiver in checklist.get("waived_checks", []) or []:
                if isinstance(waiver, dict):
                    lines.append(
                        "  - waived %s: %s"
                        % (waiver.get("check_id", "?"), waiver.get("reason", ""))
                    )
    else:
        lines.append("- engine acceptance: not recorded at freeze; record it only for the exact frozen identity")
    lines.append("")
    lines.append("## Geography versus content boundary")
    lines.append("")
    lines.append("- foundation geography ends at: rasters, definition, map metadata, states geography, regions, logistics topology, reviewed placements, and foundation assets")
    lines.append("- content history begins at: country tags, owners, resources, manpower, victory points, units, characters, ideas, focuses, events, decisions, bookmarks, localisation, and flags")
    lines.append("- state resources, buildings output, manpower, owners, and victory points are never foundation repairs")
    lines.append("")
    lines.append("## Author reference rules")
    lines.append("")
    lines.append("- reference provinces by stable numeric ID within the locked range; never invent IDs outside it")
    lines.append("- reference states, strategic regions, supply nodes, and railways by locked ID; keep province membership changes in review")
    lines.append("- read coordinates for ports, buildings, unit stacks, and weather from the frozen placement files; do not hand-edit them downstream")
    lines.append("- keep content files (history/countries, common/*, localisation, gfx/flags) outside the foundation payload so the lock stays valid")
    lines.append("")
    lines.append("## Prohibited post-freeze operations")
    lines.append("")
    lines.append("- do not change province dimensions, colors, IDs, deletions, or types without a migration")
    lines.append("- do not change state membership or IDs, regions, adjacencies, or rail and supply topology silently")
    lines.append("- do not compact province IDs silently after freeze")
    lines.append("- do not edit frozen rasters or placement coordinates downstream; request a map change instead")
    lines.append("- do not record engine acceptance for a different artifact identity")
    lines.append("")
    lines.append("## Change and migration procedure")
    lines.append("")
    lines.append("1. run a compare of the new manifest against this frozen lock")
    lines.append("2. breaking identity changes require content migration with an old-to-new ID mapping; accepted state is lost")
    lines.append("3. breaking topology changes require history and gameplay review; accepted state is lost")
    lines.append("4. visual changes keep content IDs valid; re-run visual validation and usually engine acceptance")
    lines.append("5. placement changes require related gameplay and visual checks")
    lines.append("6. non-foundation content changes keep this lock valid and need no re-freeze")
    lines.append("7. approved ID changes must ship a reusable old-to-new mapping before the next freeze")
    lines.append("8. unfreeze only with a recorded reason; the unfreeze audit names the reason and the previous identity")
    lines.append("")
    return "\n".join(lines) + "\n"
