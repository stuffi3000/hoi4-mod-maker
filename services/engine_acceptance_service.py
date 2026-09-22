"""Local assisted engine-acceptance harness (M7.3).

This service implements the local, opt-in acceptance workflow: artifact
verification, safe log snapshots with fresh-range inspection, deterministic
log classification, fresh save detection, opt-in launch configuration with a
dry-run default, stable human-checklist recording, and deterministic
engine_acceptance.json result documents.

The harness never performs GUI or mouse automation. It never launches the
game unless the caller explicitly requests execution, and the command-line
entry point defaults to dry-run mode. Old log content is never treated as
current evidence: every log is snapshotted before the run and only bytes
observed after the snapshot offset are classified.
"""
from __future__ import annotations

import csv
import copy
import hashlib
import json
import os
import re
import stat as stat_module
import subprocess
import time
import uuid
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain import engine_acceptance as contract


RESULT_FILENAME = "engine_acceptance.json"
MANIFEST_FILENAME = "foundation_manifest.json"
LOCK_FILENAME = "foundation.lock.json"

DEFAULT_LOG_NAMES = ("error.log", "exceptions.log", "setup.log", "system.log")

MAX_FINDINGS = 1000
MAX_FINDING_TEXT_CHARS = 500
MAX_FRESH_BYTES = 4 * 1024 * 1024
LOG_FULL_FINGERPRINT_LIMIT_BYTES = 1024 * 1024
LOG_FINGERPRINT_SAMPLE_BYTES = 4096
MAX_OUTPUT_CHARS = 65536
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_NOTE_CHARS = 500
SAVE_HASH_LIMIT_BYTES = 256 * 1024 * 1024
MANAGED_DESCRIPTOR_FILENAME = "hoi4_map_maker_acceptance.mod"
MAX_MANAGED_DESCRIPTOR_BYTES = 128 * 1024
MAX_DLC_LOAD_BYTES = 1024 * 1024
_ACTIVE_MOD_COUNT_RE = re.compile(r"\bActive Mod Count:\s*(\d+)\s*$", re.IGNORECASE)
_ACTIVE_MOD_RE = re.compile(r"\bActive Mod:\s*(.*?)\s*$", re.IGNORECASE)
_ACTIVE_DLC_COUNT_RE = re.compile(r"\bActive DLC Count:\s*(\d+)\s*$", re.IGNORECASE)
_ACTIVE_DLC_RE = re.compile(r"\bActive DLC:\s*(.*?)\s*$", re.IGNORECASE)
_DLC_CHECKSUM_ERROR_RE = re.compile(
    r"\[dlc\.cpp:142\]:\s*incorrect checksum for DLC\b",
    re.IGNORECASE,
)
_MISSING_OPTIONAL_DLC_ENTITY_RE = re.compile(
    r"\[equipment_graphic_database\.cpp:72\].*?"
    r"Entity referenced in equipment graphic database does not exist:\s*"
    r"[\"']?(GER_super_heavy_armor_entity|SOV_super_heavy_armor_entity)[\"']?(?![A-Za-z0-9_])"
)
_MISSING_OPTIONAL_DLC_RULE_RE = re.compile(
    r"\[triggerimplementation\.cpp:9803\].*?"
    r"common[/\\]scripted_effects[/\\]BLT_scripted_effects\.txt:"
    r"(?P<line>77|83|213|219):.*?"
    r"has_game_rule:\s*game rule\s*[\"']?(?P<rule>LIT_ai_behavior|EST_ai_behavior)[\"']?\s+does not exist\b"
)
_DESCRIPTOR_NAME_RE = re.compile(r'^\s*name\s*=\s*"([^"\r\n]*)"\s*(?:#.*)?$', re.IGNORECASE)
_DESCRIPTOR_PATH_RE = re.compile(r"^\s*path\s*=.*$", re.IGNORECASE)

_OPTIONAL_DLC_ENTITY_OWNERS = {
    "GER_super_heavy_armor_entity": "German Tanks Unit Pack",
    "SOV_super_heavy_armor_entity": "Soviet Tanks Unit Pack",
}
_OPTIONAL_DLC_RULE_LINES = {
    ("LIT_ai_behavior", "77"),
    ("LIT_ai_behavior", "83"),
    ("EST_ai_behavior", "213"),
    ("EST_ai_behavior", "219"),
}
_OPTIONAL_DLC_RULE_OWNER = "No Step Back"


def _utc_iso_from_ns(moment_ns: int) -> str:
    """Format a nanosecond timestamp as UTC ISO-8601 observational metadata."""
    try:
        moment = float(moment_ns) / 1_000_000_000.0
    except (TypeError, ValueError):
        moment = 0.0
    return datetime.fromtimestamp(moment, tz=timezone.utc).isoformat()


def _sha256_file(path: Path, limit_bytes: int = SAVE_HASH_LIMIT_BYTES) -> tuple[str, int, bool]:
    """Hash a file with streaming reads and return digest, bytes read, and truncated flag."""
    digest = hashlib.sha256()
    total = 0
    truncated = False
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            if total + len(chunk) > limit_bytes:
                digest.update(chunk[: limit_bytes - total])
                total = limit_bytes
                truncated = True
                break
            digest.update(chunk)
            total += len(chunk)
    return (digest.hexdigest(), total, truncated)


def _posix_rel(path: Path, root: Path) -> str:
    """Return the POSIX-style relative path of a file below a root directory."""
    return path.relative_to(root).as_posix()


def _sanitize_archive_name(value: str) -> str:
    """Map an arbitrary log label to a safe flat archive file stem."""
    cleaned = "".join(item if item.isalnum() or item in ("-", "_") else "_" for item in str(value))
    return cleaned.strip("_") or "log"


def _bounded_text(value: str, limit: int = MAX_FINDING_TEXT_CHARS) -> str:
    """Truncate evidence text to a stable bound without raising on bad input."""
    text = str(value or "")
    if len(text) > limit:
        return text[:limit]
    return text


def _manifest_identity(manifest: Any) -> str:
    """Extract the manifest identity hash without inventing one when absent."""
    if not isinstance(manifest, Mapping):
        return ""
    identity = manifest.get("identity", {})
    if not isinstance(identity, Mapping):
        return ""
    digest = identity.get("identity_hash", "")
    return str(digest) if isinstance(digest, str) else ""


def _manifest_profile(manifest: Any) -> str:
    """Extract the manifest profile name without inventing one when absent."""
    if not isinstance(manifest, Mapping):
        return ""
    profile = manifest.get("profile", "")
    return str(profile) if isinstance(profile, str) else ""


def _manifest_target(manifest: Any) -> dict[str, Any]:
    """Extract the portable manifest target identity as plain data."""
    if not isinstance(manifest, Mapping):
        return {}
    target = manifest.get("target", {})
    if not isinstance(target, Mapping):
        return {}
    identity = target.get("identity", {})
    if isinstance(identity, Mapping):
        return {str(key): value for key, value in identity.items()}
    return {}


def _manifest_foundation_source_identity(manifest: Any) -> dict[str, str]:
    """Derive the profile-agnostic foundation source identity from a manifest."""
    if not isinstance(manifest, Mapping):
        return {"identity_hash": "", "algorithm": ""}
    try:
        from services.export_manifest import foundation_source_identity
        record = foundation_source_identity(dict(manifest))
    except Exception:
        return {"identity_hash": "", "algorithm": ""}
    return {
        "identity_hash": str(record.get("identity_hash", "") or ""),
        "algorithm": str(record.get("algorithm", "") or ""),
    }


def verify_artifact(
    artifact_dir: str | os.PathLike[str],
    expected_identity_hash: str = "",
    expected_profile: str = "",
) -> dict[str, Any]:
    """Verify an acceptance artifact directory and record its exact inventory.

    Every regular file below the directory is hashed with SHA-256 and listed
    by POSIX relative path. The result file itself is excluded so writing the
    harness output never changes the recorded fingerprint. Manifest and lock
    documents are read when present and never required.
    """
    root = Path(artifact_dir)
    record: dict[str, Any] = {
        "path": str(artifact_dir),
        "exists": root.exists(),
        "is_dir": root.is_dir(),
        "status": "ok",
        "files": [],
        "file_count": 0,
        "fingerprint": "",
        "manifest": {
            "present": False,
            "identity_hash": "",
            "foundation_source_identity": {"identity_hash": "", "algorithm": ""},
            "profile": "",
            "target": {},
            "status": "absent",
        },
        "lock": {"present": False, "identity_hash": "", "status": "absent"},
        "mismatch": [],
    }
    if not root.exists():
        record["status"] = "missing"
        return record
    if not root.is_dir():
        record["status"] = "not_a_directory"
        return record
    entries: list[dict[str, Any]] = []
    candidates = sorted(root.rglob("*"))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            relative = _posix_rel(candidate, root)
        except ValueError:
            continue
        if relative == RESULT_FILENAME:
            continue
        try:
            digest, _total, _truncated = _sha256_file(candidate)
            size = candidate.stat().st_size
        except OSError:
            continue
        entries.append({"rel_path": relative, "size": int(size), "sha256": digest})
    entries.sort(key=lambda item: item["rel_path"])
    record["files"] = entries
    record["file_count"] = len(entries)
    record["fingerprint"] = contract.deterministic_hash(entries)
    manifest_path = root / MANIFEST_FILENAME
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            manifest_status = "ok"
        except (OSError, ValueError):
            manifest = {}
            manifest_status = "unreadable"
        source_identity = _manifest_foundation_source_identity(manifest)
        record["manifest"] = {
            "present": True,
            "identity_hash": _manifest_identity(manifest),
            "foundation_source_identity": source_identity,
            "profile": _manifest_profile(manifest),
            "target": _manifest_target(manifest),
            "status": manifest_status,
        }
        stored_source_identity = manifest.get("foundation_source_identity") if isinstance(manifest, Mapping) else None
        if isinstance(stored_source_identity, Mapping):
            stored_hash = str(stored_source_identity.get("identity_hash", "") or "")
            stored_algorithm = str(stored_source_identity.get("algorithm", "") or "")
            if stored_hash != source_identity["identity_hash"]:
                record["mismatch"].append({
                    "field": "foundation_source_identity",
                    "expected": source_identity["identity_hash"],
                    "actual": stored_hash,
                })
            if stored_algorithm != source_identity["algorithm"]:
                record["mismatch"].append({
                    "field": "foundation_source_identity_algorithm",
                    "expected": source_identity["algorithm"],
                    "actual": stored_algorithm,
                })
        elif stored_source_identity is not None:
            record["mismatch"].append({
                "field": "foundation_source_identity",
                "expected": source_identity["identity_hash"],
                "actual": "<malformed>",
            })
    lock_path = root / LOCK_FILENAME
    if lock_path.is_file():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
            lock_status = "ok"
        except (OSError, ValueError):
            lock = {}
            lock_status = "unreadable"
        lock_identity = ""
        if isinstance(lock, Mapping):
            candidate_lock = lock.get("identity", {})
            if isinstance(candidate_lock, Mapping):
                raw_lock = candidate_lock.get("identity_hash", "")
                lock_identity = str(raw_lock) if isinstance(raw_lock, str) else ""
            if not lock_identity:
                raw_direct = lock.get("identity_hash", "")
                lock_identity = str(raw_direct) if isinstance(raw_direct, str) else ""
        record["lock"] = {"present": True, "identity_hash": lock_identity, "status": lock_status}
    manifest_identity = str(record["manifest"].get("identity_hash", "") or "")
    lock_identity_value = str(record["lock"].get("identity_hash", "") or "")
    if record["manifest"]["present"] and record["lock"]["present"]:
        if manifest_identity and lock_identity_value and manifest_identity != lock_identity_value:
            record["mismatch"].append({
                "field": "manifest_vs_lock_identity",
                "expected": manifest_identity,
                "actual": lock_identity_value,
            })
    if expected_identity_hash and manifest_identity and manifest_identity != str(expected_identity_hash):
        record["mismatch"].append({
            "field": "manifest_identity",
            "expected": str(expected_identity_hash),
            "actual": manifest_identity,
        })
    if expected_profile and record["manifest"].get("profile") and record["manifest"]["profile"] != str(expected_profile):
        record["mismatch"].append({
            "field": "manifest_profile",
            "expected": str(expected_profile),
            "actual": str(record["manifest"]["profile"]),
        })
    return record


def artifact_ok(record: Mapping[str, Any]) -> bool:
    """Return True only for an artifact with a usable foundation identity.

    Engine acceptance must be tied to an exact exported artifact.  A directory
    alone is therefore insufficient: the foundation manifest must be present,
    readable, and carry its identity hash.  A lock is optional for acceptance
    artifacts, but when one is present it must also be readable and identified.
    """
    try:
        if not (
            bool(record.get("exists"))
            and bool(record.get("is_dir"))
            and record.get("status") == "ok"
        ):
            return False
        manifest = record.get("manifest", {})
        if not (
            isinstance(manifest, Mapping)
            and bool(manifest.get("present"))
            and manifest.get("status") == "ok"
            and str(manifest.get("identity_hash", "") or "")
        ):
            return False
        lock = record.get("lock", {})
        if isinstance(lock, Mapping) and bool(lock.get("present")):
            if (
                lock.get("status") != "ok"
                or not str(lock.get("identity_hash", "") or "")
            ):
                return False
        return True
    except AttributeError:
        return False


def resolve_log_paths(
    explicit_logs: Sequence[str | os.PathLike[str]] = (),
    log_dir: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Resolve the log watch list from explicit files plus default names in a directory."""
    resolved: list[str] = []
    for candidate in explicit_logs or ():
        text = str(candidate or "")
        if text and text not in resolved:
            resolved.append(text)
    if log_dir:
        base = Path(log_dir)
        for name in DEFAULT_LOG_NAMES:
            text = str(base / name)
            if text not in resolved:
                resolved.append(text)
    return resolved


def _file_identity(stat: os.stat_result) -> str:
    """Return the available stable device/inode pair for one open file."""
    device = int(getattr(stat, "st_dev", 0) or 0)
    inode = int(getattr(stat, "st_ino", 0) or 0)
    return "%d:%d" % (device, inode)


def _lstat_optional(path: Path) -> os.stat_result | None:
    """Return lstat data without following links, or None when absent."""
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _require_regular_path(path: Path, label: str, required: bool = True) -> os.stat_result | None:
    """Reject links and special files at a transaction-owned path."""
    info = _lstat_optional(path)
    if info is None:
        if required:
            raise ValueError("%s does not exist: %s" % (label, path))
        return None
    if stat_module.S_ISLNK(info.st_mode) or not stat_module.S_ISREG(info.st_mode):
        raise ValueError("%s must be a regular non-symlink file: %s" % (label, path))
    return info


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build JSON objects while refusing duplicate keys that hide settings."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("dlc_load.json contains duplicate JSON key %r" % key)
        result[key] = value
    return result


def _descriptor_with_artifact_path(artifact_dir: Path) -> tuple[bytes, str]:
    """Copy descriptor metadata while replacing only its root path directive."""
    source = artifact_dir / "descriptor.mod"
    info = _require_regular_path(source, "artifact descriptor")
    assert info is not None
    if int(info.st_size) > MAX_MANAGED_DESCRIPTOR_BYTES:
        raise ValueError("artifact descriptor exceeds the safe size limit")
    try:
        text = source.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("artifact descriptor is unreadable UTF-8: %s" % source) from exc
    if "\x00" in text:
        raise ValueError("artifact descriptor contains a NUL byte")

    lines = text.splitlines()
    names: list[str] = []
    path_indexes: list[int] = []
    for index, line in enumerate(lines):
        name_match = _DESCRIPTOR_NAME_RE.fullmatch(line)
        if name_match is not None:
            names.append(name_match.group(1))
        if _DESCRIPTOR_PATH_RE.fullmatch(line) is not None:
            path_indexes.append(index)
    if len(names) != 1 or not names[0].strip():
        raise ValueError("artifact descriptor must contain exactly one non-empty quoted name")
    if len(path_indexes) > 1:
        raise ValueError("artifact descriptor contains ambiguous duplicate path directives")

    artifact_path = artifact_dir.as_posix()
    if any(character in artifact_path for character in ('"', "\r", "\n")):
        raise ValueError("artifact directory cannot be represented safely in a descriptor path")
    path_line = 'path="%s"' % artifact_path
    if path_indexes:
        lines[path_indexes[0]] = path_line
    else:
        lines.append(path_line)
    return (("\n".join(lines) + "\n").encode("utf-8"), names[0])


def _read_regular_file_bytes(path: Path, label: str, max_bytes: int) -> bytes:
    """Read a bounded regular file while detecting replacement during the read."""
    before = _require_regular_path(path, label)
    assert before is not None
    if int(before.st_size) > max_bytes:
        raise OSError("%s exceeds the safe size limit: %s" % (label, path))
    with open(path, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat_module.S_ISREG(opened.st_mode) or _file_identity(opened) != _file_identity(before):
            raise OSError("%s changed while it was being opened: %s" % (label, path))
        content = handle.read(max_bytes + 1)
    after = _require_regular_path(path, label)
    assert after is not None
    if (
        len(content) > max_bytes
        or len(content) != int(before.st_size)
        or _file_identity(after) != _file_identity(before)
        or int(after.st_size) != int(before.st_size)
        or int(after.st_mtime_ns) != int(before.st_mtime_ns)
    ):
        raise OSError("%s changed while it was being read: %s" % (label, path))
    return content


def _atomic_replace_bytes(
    path: Path,
    content: bytes,
    expected_current_bytes: bytes | None = None,
) -> None:
    """Atomically replace a regular file using a unique same-directory temp."""
    temporary = path.with_name(path.name + ".codex-" + uuid.uuid4().hex + ".tmp")
    try:
        with open(temporary, "xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        current = _lstat_optional(path)
        if current is not None and (stat_module.S_ISLNK(current.st_mode) or not stat_module.S_ISREG(current.st_mode)):
            raise OSError("refusing to replace a non-regular dlc_load.json path: %s" % path)
        if expected_current_bytes is not None:
            current_bytes = _read_regular_file_bytes(path, "dlc_load.json", MAX_DLC_LOAD_BYTES)
            if current_bytes != expected_current_bytes:
                raise OSError("dlc_load.json changed concurrently; refusing to overwrite: %s" % path)
        os.replace(str(temporary), str(path))
    finally:
        temporary_info = _lstat_optional(temporary)
        if temporary_info is not None:
            if stat_module.S_ISLNK(temporary_info.st_mode) or not stat_module.S_ISREG(temporary_info.st_mode):
                raise OSError("temporary activation file changed type before cleanup: %s" % temporary)
            temporary.unlink()


def _remove_owned_regular_file(
    path: Path,
    expected_identity: str,
    label: str,
    expected_bytes: bytes | None = None,
) -> None:
    """Remove a staged file only if its filesystem identity is still ours."""
    info = _lstat_optional(path)
    if info is None:
        return
    if stat_module.S_ISLNK(info.st_mode) or not stat_module.S_ISREG(info.st_mode):
        raise OSError("refusing to remove a replaced or non-regular %s: %s" % (label, path))
    if not expected_identity or _file_identity(info) != expected_identity:
        raise OSError("refusing to remove a %s that no longer matches the staged file: %s" % (label, path))
    if expected_bytes is not None and _read_regular_file_bytes(path, label, MAX_DLC_LOAD_BYTES) != expected_bytes:
        raise OSError("%s changed concurrently; refusing to remove it: %s" % (label, path))
    path.unlink()


@contextmanager
def managed_artifact_activation(
    artifact_dir: str | os.PathLike[str],
    hoi4_user_dir: str | os.PathLike[str],
):
    """Temporarily activate one artifact through HOI4's user ``dlc_load.json``.

    The fixed staged descriptor name is collision-checked and created
    exclusively beneath the existing user ``mod`` directory.  Only the
    ``enabled_mods`` JSON value is changed.  The previous config bytes are
    restored exactly in all ordinary exit paths, and only this invocation's
    descriptor is eligible for cleanup.
    """
    supplied_user_dir = Path(hoi4_user_dir).expanduser()
    if not supplied_user_dir.is_absolute():
        raise ValueError("--hoi4-user-dir must be an absolute, unambiguous path")
    if supplied_user_dir.is_symlink():
        raise ValueError("--hoi4-user-dir must not be a symlink")
    try:
        user_dir = supplied_user_dir.resolve(strict=True)
    except OSError as exc:
        raise ValueError("HOI4 user-data directory does not exist: %s" % supplied_user_dir) from exc
    if not user_dir.is_dir():
        raise ValueError("HOI4 user-data path is not a directory: %s" % user_dir)

    mod_dir = user_dir / "mod"
    mod_info = _lstat_optional(mod_dir)
    if mod_info is None or stat_module.S_ISLNK(mod_info.st_mode) or not stat_module.S_ISDIR(mod_info.st_mode):
        raise ValueError("HOI4 user-data directory must contain a real mod directory: %s" % mod_dir)
    resolved_mod_dir = mod_dir.resolve(strict=True)
    if resolved_mod_dir.parent != user_dir:
        raise ValueError("HOI4 mod directory resolves outside the supplied user-data directory")

    supplied_artifact = Path(artifact_dir).expanduser()
    if supplied_artifact.is_symlink():
        raise ValueError("artifact directory must not be a symlink")
    try:
        resolved_artifact = supplied_artifact.resolve(strict=True)
    except OSError as exc:
        raise ValueError("artifact directory does not exist: %s" % supplied_artifact) from exc
    if not resolved_artifact.is_dir():
        raise ValueError("artifact path is not a directory: %s" % resolved_artifact)
    if resolved_artifact in (user_dir, resolved_mod_dir):
        raise ValueError("artifact directory cannot be the HOI4 user-data or mod root")

    descriptor_bytes, descriptor_name = _descriptor_with_artifact_path(resolved_artifact)
    staged_descriptor = resolved_mod_dir / MANAGED_DESCRIPTOR_FILENAME
    if _lstat_optional(staged_descriptor) is not None:
        raise ValueError("managed activation descriptor already exists; refusing to overwrite: %s" % staged_descriptor)

    dlc_load_path = user_dir / "dlc_load.json"
    old_info = _require_regular_path(dlc_load_path, "dlc_load.json", required=False)
    old_bytes: bytes | None = None
    if old_info is not None:
        if int(old_info.st_size) > MAX_DLC_LOAD_BYTES:
            raise ValueError("dlc_load.json exceeds the safe size limit")
        try:
            old_bytes = _read_regular_file_bytes(dlc_load_path, "dlc_load.json", MAX_DLC_LOAD_BYTES)
        except OSError as exc:
            raise ValueError("dlc_load.json is unreadable or changed while being inspected") from exc
        check_info = _require_regular_path(dlc_load_path, "dlc_load.json")
        assert check_info is not None
        if (
            _file_identity(check_info) != _file_identity(old_info)
            or int(check_info.st_size) != int(old_info.st_size)
            or int(check_info.st_mtime_ns) != int(old_info.st_mtime_ns)
        ):
            raise ValueError("dlc_load.json changed while it was being inspected")
        try:
            settings = json.loads(old_bytes.decode("utf-8-sig"), object_pairs_hook=_reject_duplicate_json_keys)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("dlc_load.json is not valid UTF-8 JSON") from exc
        if not isinstance(settings, dict):
            raise ValueError("dlc_load.json must contain a JSON object")
    else:
        settings = {}

    descriptor_reference = "mod/" + MANAGED_DESCRIPTOR_FILENAME
    settings["enabled_mods"] = [descriptor_reference]
    activation_json = (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    activation_hash = hashlib.sha256(activation_json).hexdigest()

    descriptor_identity = ""
    dlc_created_identity = ""
    activation_installed = False
    try:
        with open(staged_descriptor, "xb") as handle:
            descriptor_identity = _file_identity(os.fstat(handle.fileno()))
            if descriptor_identity == "0:0":
                raise OSError("filesystem does not provide a stable identity for the staged descriptor")
            handle.write(descriptor_bytes)
            handle.flush()
            os.fsync(handle.fileno())

        if old_bytes is not None:
            _atomic_replace_bytes(dlc_load_path, activation_json, expected_current_bytes=old_bytes)
            activation_installed = True
        else:
            with open(dlc_load_path, "xb") as handle:
                dlc_created_identity = _file_identity(os.fstat(handle.fileno()))
                if dlc_created_identity == "0:0":
                    raise OSError("filesystem does not provide a stable identity for created dlc_load.json")
                handle.write(activation_json)
                handle.flush()
                os.fsync(handle.fileno())
            activation_installed = True

        yield {
            "expected_mod_name": descriptor_name,
            "descriptor_reference": descriptor_reference,
            "descriptor_path": str(staged_descriptor),
            "dlc_load_path": str(dlc_load_path),
        }
    finally:
        try:
            if old_bytes is not None and activation_installed:
                current_bytes = _read_regular_file_bytes(dlc_load_path, "dlc_load.json", MAX_DLC_LOAD_BYTES)
                if current_bytes != activation_json or hashlib.sha256(current_bytes).hexdigest() != activation_hash:
                    raise OSError(
                        "dlc_load.json changed concurrently; original bytes were left untouched: %s" % dlc_load_path
                    )
                _atomic_replace_bytes(dlc_load_path, old_bytes, expected_current_bytes=activation_json)
            elif old_bytes is None and dlc_created_identity:
                if activation_installed:
                    current_bytes = _read_regular_file_bytes(dlc_load_path, "dlc_load.json", MAX_DLC_LOAD_BYTES)
                    if current_bytes != activation_json or hashlib.sha256(current_bytes).hexdigest() != activation_hash:
                        raise OSError(
                            "dlc_load.json changed concurrently; created file was left untouched: %s" % dlc_load_path
                        )
                    _remove_owned_regular_file(
                        dlc_load_path,
                        dlc_created_identity,
                        "created dlc_load.json",
                        expected_bytes=activation_json,
                    )
                else:
                    _remove_owned_regular_file(dlc_load_path, dlc_created_identity, "created dlc_load.json")
        finally:
            if descriptor_identity:
                _remove_owned_regular_file(staged_descriptor, descriptor_identity, "staged activation descriptor")


def _log_fingerprint_samples(size: int) -> list[dict[str, int]]:
    """Choose a bounded full fingerprint for small logs or samples for large logs."""
    total = max(0, int(size))
    if total == 0:
        return []
    if total <= LOG_FULL_FINGERPRINT_LIMIT_BYTES:
        return [{"offset": 0, "length": total}]
    width = min(LOG_FINGERPRINT_SAMPLE_BYTES, total)
    offsets = {0}
    if total > width:
        offsets.add((total - width) // 2)
        offsets.add(total - width)
    return [
        {"offset": offset, "length": min(width, total - offset)}
        for offset in sorted(offsets)
    ]


def _log_content_fingerprint(handle, samples: Sequence[Mapping[str, Any]]) -> str:
    """Hash selected fixed byte ranges without reading the entire log file."""
    digest = hashlib.sha256()
    for sample in samples:
        offset = int(sample.get("offset", 0) or 0)
        length = int(sample.get("length", 0) or 0)
        if offset < 0 or length < 0:
            raise OSError("invalid log fingerprint range")
        handle.seek(offset)
        content = handle.read(length)
        if len(content) != length:
            raise OSError("log changed while checking its fingerprint")
        digest.update(offset.to_bytes(8, "big", signed=False))
        digest.update(length.to_bytes(8, "big", signed=False))
        digest.update(content)
    return digest.hexdigest()


def snapshot_log_file(
    path: str | os.PathLike[str],
    archive_dir: str | os.PathLike[str] | None = None,
    snapshot_ns: int | None = None,
) -> dict[str, Any]:
    """Snapshot one log file by recording its size offset without modifying it.

    The original file is never truncated, rotated, or deleted. When an archive
    directory is supplied, the pre-run bytes are copied aside under a
    collision-safe name so fresh ranges stay provable after the fact.
    """
    moment_ns = int(snapshot_ns) if snapshot_ns is not None else time.time_ns()
    record: dict[str, Any] = {
        "path": str(path),
        "exists": False,
        "size": 0,
        "offset": 0,
        "mtime_ns": 0,
        "mtime_iso": "",
        "ctime_ns": 0,
        "file_identity": "",
        "fingerprint_samples": [],
        "fingerprint": "",
        "snapshot_ns": moment_ns,
        "snapshot_iso": _utc_iso_from_ns(moment_ns),
        "status": "missing",
        "archived_to": "",
        "archive_truncated": False,
    }
    candidate = Path(path)
    try:
        present = candidate.is_file()
    except OSError:
        present = False
    if not present:
        return record
    record["exists"] = True
    try:
        with open(candidate, "rb") as handle:
            stat = os.fstat(handle.fileno())
            size = int(stat.st_size)
            samples = _log_fingerprint_samples(size)
            fingerprint = _log_content_fingerprint(handle, samples)
    except OSError:
        record["status"] = "unreadable"
        return record
    record["size"] = size
    record["offset"] = size
    record["mtime_ns"] = int(stat.st_mtime_ns)
    record["mtime_iso"] = _utc_iso_from_ns(int(stat.st_mtime_ns))
    record["ctime_ns"] = int(getattr(stat, "st_ctime_ns", 0) or 0)
    record["file_identity"] = _file_identity(stat)
    record["fingerprint_samples"] = samples
    record["fingerprint"] = fingerprint
    record["status"] = "snapshotted"
    if archive_dir:
        try:
            target_dir = Path(archive_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            stem = _sanitize_archive_name(candidate.stem or "log")
            archived = target_dir / ("%s.pre_%d.log" % (stem, moment_ns))
            with open(candidate, "rb") as source, open(archived, "wb") as destination:
                remaining = MAX_ARCHIVE_BYTES
                while remaining > 0:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    destination.write(chunk)
                    remaining -= len(chunk)
                extra = source.read(1)
                if extra:
                    record["archive_truncated"] = True
            record["archived_to"] = str(archived)
        except OSError:
            record["status"] = "archive_failed"
    return record


def read_fresh_lines(snapshot: Mapping[str, Any], max_bytes: int = MAX_FRESH_BYTES) -> dict[str, Any]:
    """Read post-snapshot log bytes, restarting at zero when the file was rewritten."""
    try:
        path = str(snapshot.get("path", ""))
        offset = int(snapshot.get("offset", 0) or 0)
        existed_before = bool(snapshot.get("exists", False))
        snapshot_status = str(snapshot.get("status", "") or "")
    except (AttributeError, TypeError, ValueError):
        return {"path": "", "status": "invalid_snapshot", "text": "", "lines": [], "byte_count": 0, "new_offset": 0, "truncated": False, "generated": False, "rewritten": False, "read_offset": 0}
    outcome: dict[str, Any] = {
        "path": path,
        "status": "ok",
        "text": "",
        "lines": [],
        "byte_count": 0,
        "new_offset": offset,
        "truncated": False,
        "generated": False,
        "rewritten": False,
        "read_offset": offset,
    }
    candidate = Path(path)
    if existed_before and snapshot_status not in ("snapshotted", "archive_failed"):
        outcome["status"] = "unreadable"
        return outcome
    if not candidate.is_file():
        outcome["status"] = "missing"
        return outcome
    try:
        with open(candidate, "rb") as handle:
            stat = os.fstat(handle.fileno())
            size = int(stat.st_size)
            if existed_before:
                if "fingerprint" not in snapshot or "fingerprint_samples" not in snapshot:
                    outcome["status"] = "unreadable"
                    return outcome
                baseline_fingerprint = str(snapshot.get("fingerprint", "") or "")
                baseline_samples = snapshot.get("fingerprint_samples", ())
                if size < offset:
                    current_fingerprint = ""
                else:
                    current_fingerprint = _log_content_fingerprint(handle, baseline_samples)
                current_identity = _file_identity(stat)
                identity_changed = current_identity != str(snapshot.get("file_identity", "") or "")
                fingerprint_changed = size < offset or current_fingerprint != baseline_fingerprint
                rewritten = size < offset or identity_changed or fingerprint_changed
                baseline_size = int(snapshot.get("size", offset) or 0)
                baseline_mtime_ns = int(snapshot.get("mtime_ns", 0) or 0)
                baseline_ctime_ns = int(snapshot.get("ctime_ns", 0) or 0)
                outcome["generated"] = bool(
                    rewritten
                    or size != baseline_size
                    or int(stat.st_mtime_ns) != baseline_mtime_ns
                    or int(getattr(stat, "st_ctime_ns", 0) or 0) != baseline_ctime_ns
                )
                outcome["rewritten"] = bool(rewritten)
                if rewritten:
                    offset = 0
            else:
                if snapshot_status not in ("", "missing"):
                    outcome["status"] = "unreadable"
                    return outcome
                offset = 0
                outcome["generated"] = True
            outcome["read_offset"] = offset
            outcome["new_offset"] = offset
            handle.seek(offset)
            raw = handle.read(max_bytes + 1)
    except FileNotFoundError:
        outcome["status"] = "missing"
        return outcome
    except OSError:
        outcome["status"] = "unreadable"
        return outcome
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
        outcome["truncated"] = True
    outcome["byte_count"] = len(raw)
    outcome["new_offset"] = offset + len(raw)
    text = raw.decode("utf-8", errors="replace")
    outcome["text"] = text
    outcome["lines"] = text.splitlines()
    return outcome


def _is_system_log_path(path: str | os.PathLike[str]) -> bool:
    """Return whether a path names system.log under either path convention."""
    normalized = str(path or "").replace("\\", "/").rstrip("/").casefold()
    return normalized.rsplit("/", 1)[-1] == "system.log"


def _active_mod_evidence(
    sources: Sequence[Mapping[str, Any]],
    expected_name: str = "",
    required: bool = False,
) -> dict[str, Any]:
    """Prove managed activation from fresh system.log lines only."""
    expected = str(expected_name or "")
    evidence: dict[str, Any] = {
        "required": bool(required),
        "expected_name": expected,
        "count": None,
        "observed_names": [],
        "status": "not_configured" if required else "not_required",
        "source": "",
        "fresh_lines": 0,
        "truncated": False,
    }
    if not required or not sources:
        return evidence
    if len(sources) != 1:
        evidence["status"] = "ambiguous"
        evidence["sources"] = [str(source.get("path", "") or "") for source in sources]
        return evidence

    source = sources[0]
    evidence["source"] = str(source.get("path", "") or "")
    evidence["fresh_lines"] = int(source.get("fresh_lines", 0) or 0)
    evidence["truncated"] = bool(source.get("truncated", False))
    source_status = str(source.get("status", "") or "")
    if source_status == "missing":
        evidence["status"] = "missing"
        return evidence
    if source_status != "ok" or evidence["truncated"]:
        evidence["status"] = "unreadable"
        return evidence

    count_records: list[tuple[int, int]] = []
    mod_records: list[tuple[int, str]] = []
    for line_number, line in enumerate(source.get("lines", ()) or (), start=1):
        text = str(line)
        count_match = _ACTIVE_MOD_COUNT_RE.search(text)
        if count_match is not None:
            count_records.append((line_number, int(count_match.group(1))))
        mod_match = _ACTIVE_MOD_RE.search(text)
        if mod_match is not None:
            name = mod_match.group(1).strip()
            if name:
                mod_records.append((line_number, name))

    if count_records:
        count_line, active_count = count_records[-1]
        mod_records = [record for record in mod_records if record[0] > count_line]
        evidence["count"] = active_count
    evidence["observed_names"] = [name for _line, name in mod_records]
    if evidence["count"] is None or not mod_records:
        evidence["status"] = "missing"
    elif (
        evidence["count"] != 1
        or len(mod_records) != 1
        or evidence["observed_names"] != [expected]
    ):
        evidence["status"] = "mismatch"
    else:
        evidence["status"] = "matched"
    return evidence


def _active_dlc_evidence(sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Prove the fresh active-DLC list is complete before using it for correlation."""
    evidence: dict[str, Any] = {
        "count": None,
        "observed_names": [],
        "status": "not_observed",
        "source": "",
        "fresh_lines": 0,
        "truncated": False,
    }
    if not sources:
        return evidence
    if len(sources) != 1:
        evidence["status"] = "ambiguous"
        evidence["sources"] = [str(source.get("path", "") or "") for source in sources]
        return evidence

    source = sources[0]
    evidence["source"] = str(source.get("path", "") or "")
    evidence["fresh_lines"] = int(source.get("fresh_lines", 0) or 0)
    evidence["truncated"] = bool(source.get("truncated", False))
    source_status = str(source.get("status", "") or "")
    if source_status == "missing":
        evidence["status"] = "missing"
        return evidence
    if source_status != "ok" or evidence["truncated"]:
        evidence["status"] = "unreadable"
        return evidence

    count_records: list[tuple[int, int]] = []
    dlc_records: list[tuple[int, str, bool]] = []
    for line_number, line in enumerate(source.get("lines", ()) or (), start=1):
        text = str(line)
        count_match = _ACTIVE_DLC_COUNT_RE.search(text)
        if count_match is not None:
            count_records.append((line_number, int(count_match.group(1))))
        dlc_match = _ACTIVE_DLC_RE.search(text)
        if dlc_match is not None:
            name = dlc_match.group(1).strip()
            dlc_records.append((line_number, name, not bool(name)))

    if count_records:
        count_line, active_count = count_records[-1]
        dlc_records = [record for record in dlc_records if record[0] > count_line]
        evidence["count"] = active_count
    malformed_name = any(malformed for _line, _name, malformed in dlc_records)
    names = [name for _line, name, _malformed in dlc_records]
    evidence["observed_names"] = names
    if evidence["count"] is None:
        evidence["status"] = "incomplete"
    elif (
        malformed_name
        or evidence["count"] != len(names)
        or len({name.casefold() for name in names}) != len(names)
    ):
        evidence["status"] = "incomplete"
    else:
        evidence["status"] = "complete"
    return evidence


def _optional_dlc_owner_for_line(line: str, source: str) -> str:
    """Return an owner only for the exact known HOI4 missing-entity/rule signatures."""
    if not _is_error_log_path(source):
        return ""
    text = str(line or "")
    entity_match = _MISSING_OPTIONAL_DLC_ENTITY_RE.search(text)
    if entity_match is not None:
        return _OPTIONAL_DLC_ENTITY_OWNERS[entity_match.group(1)]

    rule_match = _MISSING_OPTIONAL_DLC_RULE_RE.search(text)
    if rule_match is not None and (rule_match.group("rule"), rule_match.group("line")) in _OPTIONAL_DLC_RULE_LINES:
        return _OPTIONAL_DLC_RULE_OWNER
    return ""


def _owner_dlc_proven_inactive(owner: str, evidence: Mapping[str, Any]) -> bool:
    """Treat an owner as inactive only when a complete fresh DLC list omits it."""
    if str(evidence.get("status", "") or "") != "complete":
        return False
    observed = {
        str(name).strip().casefold()
        for name in evidence.get("observed_names", ()) or ()
        if str(name).strip()
    }
    return str(owner or "").strip().casefold() not in observed


def collect_fresh_findings(
    snapshots: Sequence[Mapping[str, Any]],
    expected_active_mod_name: str = "",
    require_active_mod: bool = False,
) -> dict[str, Any]:
    """Classify only fresh post-snapshot log ranges into structured findings."""
    findings: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    system_log_sources: list[dict[str, Any]] = []
    fresh_records: list[tuple[str, Sequence[str]]] = []
    dropped = 0
    for snapshot in snapshots or ():
        try:
            label = str(snapshot.get("path", ""))
        except AttributeError:
            continue
        fresh = read_fresh_lines(snapshot)
        if _is_system_log_path(label):
            system_log_sources.append({
                "path": label,
                "status": fresh.get("status", "unreadable"),
                "fresh_lines": len(fresh.get("lines", ()) or ()),
                "truncated": bool(fresh.get("truncated", False)),
                "lines": fresh.get("lines", ()) or (),
            })
        if fresh["status"] != "ok":
            files.append({
                "path": label,
                "status": fresh["status"],
                "fresh_bytes": 0,
                "fresh_lines": 0,
                "new_offset": int(fresh.get("new_offset", 0) or 0),
                "truncated": False,
                "generated": bool(fresh.get("generated", False)),
                "rewritten": bool(fresh.get("rewritten", False)),
            })
            continue
        files.append({
            "path": label,
            "status": "ok",
            "fresh_bytes": int(fresh["byte_count"]),
            "fresh_lines": len(fresh["lines"]),
            "new_offset": int(fresh["new_offset"]),
            "truncated": bool(fresh["truncated"]),
            "generated": bool(fresh["generated"]),
            "rewritten": bool(fresh["rewritten"]),
        })
        fresh_records.append((label, fresh["lines"]))

    active_dlc = _active_dlc_evidence(system_log_sources)
    for label, lines in fresh_records:
        for index, line in enumerate(lines, start=1):
            kind, category = contract.classify_line(line, source=label)
            if kind == "info":
                continue
            if kind == "error":
                owner = _optional_dlc_owner_for_line(line, label)
                if owner and _owner_dlc_proven_inactive(owner, active_dlc):
                    category = "dlc_unrelated"
                elif (
                    _is_error_log_path(label)
                    and _DLC_CHECKSUM_ERROR_RE.search(line) is not None
                    and active_dlc.get("status") == "complete"
                ):
                    category = "dlc_unrelated"
            if len(findings) >= MAX_FINDINGS:
                dropped += 1
                continue
            findings.append(contract.LogFinding(
                source=label,
                line_number=index,
                category=category,
                severity=kind,
                text=_bounded_text(line),
            ).to_dict())
    return {
        "findings": findings,
        "files": files,
        "dropped_findings": dropped,
        "active_dlc": active_dlc,
        "active_mod": _active_mod_evidence(
            system_log_sources,
            expected_name=expected_active_mod_name,
            required=require_active_mod,
        ),
    }


def summarize_findings(findings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize classified findings with per-category counts and blocker verdict."""
    by_category: dict[str, int] = {category: 0 for category in contract.LOG_CATEGORIES}
    errors = 0
    warnings = 0
    blockers = 0
    blocker_categories: list[str] = []
    for finding in findings or ():
        try:
            category = str(finding.get("category", "unknown"))
            severity = str(finding.get("severity", "error"))
        except AttributeError:
            continue
        if category not in by_category:
            category = "unknown"
        by_category[category] += 1
        if severity == "warning":
            warnings += 1
        else:
            errors += 1
        if contract.is_blocker_finding(category, severity):
            blockers += 1
            if category not in blocker_categories:
                blocker_categories.append(category)
    blocker_categories.sort()
    return {
        "total": errors + warnings,
        "errors": errors,
        "warnings": warnings,
        "by_category": by_category,
        "blocker_count": blockers,
        "blocker_categories": blocker_categories,
        "verdict": "failed" if blockers > 0 else "clean",
    }


def detect_expected_saves(
    save_dir: str | os.PathLike[str] | None,
    save_names: Sequence[str] = (),
    snapshot_ns: int | None = None,
) -> list[dict[str, Any]]:
    """Detect expected save files created at or after the snapshot instant.

    Files older than the snapshot are reported as stale, never as current
    evidence. Nothing is deleted or moved.
    """
    moment_ns = int(snapshot_ns) if snapshot_ns is not None else time.time_ns()
    evidence: list[dict[str, Any]] = []
    names = [str(item) for item in (save_names or ()) if str(item)]
    if not names:
        return evidence
    if not save_dir:
        for name in names:
            evidence.append({"name": name, "status": "not_configured", "path": "", "size": 0, "sha256": "", "mtime_ns": 0, "mtime_iso": ""})
        return evidence
    base = Path(save_dir)
    for name in names:
        candidate = base / name
        entry: dict[str, Any] = {
            "name": name,
            "status": "missing",
            "path": str(candidate),
            "size": 0,
            "sha256": "",
            "mtime_ns": 0,
            "mtime_iso": "",
        }
        try:
            stat = candidate.stat()
        except FileNotFoundError:
            evidence.append(entry)
            continue
        except OSError:
            entry["status"] = "unreadable"
            evidence.append(entry)
            continue
        if not stat_module.S_ISREG(stat.st_mode):
            evidence.append(entry)
            continue
        entry["mtime_ns"] = int(stat.st_mtime_ns)
        entry["mtime_iso"] = _utc_iso_from_ns(int(stat.st_mtime_ns))
        entry["size"] = int(stat.st_size)
        if int(stat.st_mtime_ns) < moment_ns:
            entry["status"] = "stale"
            evidence.append(entry)
            continue
        try:
            digest, _total, _truncated = _sha256_file(candidate)
        except OSError:
            entry["status"] = "unreadable"
            evidence.append(entry)
            continue
        entry["sha256"] = digest
        entry["status"] = "fresh"
        evidence.append(entry)
    return evidence


def build_launch_config(
    executable: str | os.PathLike[str] = "",
    args: Sequence[str] = (),
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | Sequence[str] | None = None,
    timeout_seconds: float = 0.0,
    wait_for_process: str = "",
    startup_timeout_seconds: float = 30.0,
    launcher_process: str = "",
) -> contract.LaunchConfig:
    """Build a launch configuration from an argument list without shell strings.

    ``wait_for_process`` is useful for Steam and Paradox launcher commands:
    those commands can return after handing off to the game, so a successful
    helper-process exit is not evidence that HOI4 actually started.
    """
    parsed_args = [str(item) for item in (args or ())]
    for item in parsed_args:
        if not isinstance(item, str):
            raise ValueError("launch arguments must be strings")
    if isinstance(env, Mapping):
        env_names = tuple(str(key) for key in env.keys())
    elif env is None:
        env_names = ()
    else:
        env_names = tuple(str(item) for item in env)
    try:
        timeout = float(timeout_seconds or 0.0)
    except (TypeError, ValueError):
        raise ValueError("launch timeout must be a number")
    if timeout < 0.0:
        raise ValueError("launch timeout must not be negative")
    try:
        startup_timeout = float(startup_timeout_seconds or 0.0)
    except (TypeError, ValueError):
        raise ValueError("startup timeout must be a number")
    if startup_timeout < 0.0:
        raise ValueError("startup timeout must not be negative")
    location = "" if cwd is None else str(cwd)
    return contract.LaunchConfig(
        executable=str(executable or ""),
        args=tuple(parsed_args),
        cwd=location,
        env_names=env_names,
        timeout_seconds=timeout,
        wait_for_process=str(wait_for_process or ""),
        startup_timeout_seconds=startup_timeout,
        launcher_process=str(launcher_process or ""),
    )


def discover_steam_executable(
    target: str | os.PathLike[str] | None = None,
) -> str:
    """Find a local Steam executable without requiring a hard-coded install path."""
    candidates: list[Path] = []
    raw_target = str(target or "").strip()
    if raw_target:
        target_path = Path(raw_target)
        for parent in (target_path, *target_path.parents):
            candidates.append(parent / "steam.exe")
            if parent.name.lower() == "steamapps":
                candidates.append(parent.parent / "steam.exe")

    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        root = os.environ.get(variable, "")
        if root:
            candidates.append(Path(root) / "Steam" / "steam.exe")

    if os.name == "nt":
        try:
            import winreg

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for key_name in (
                    r"Software\Valve\Steam",
                    r"Software\WOW6432Node\Valve\Steam",
                ):
                    try:
                        with winreg.OpenKey(hive, key_name) as key:
                            value, _kind = winreg.QueryValueEx(key, "SteamExe")
                    except (OSError, FileNotFoundError):
                        continue
                    if value:
                        candidates.append(Path(str(value)))
        except ImportError:
            pass

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(str(candidate)))
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return ""


def discover_game_executable(
    target: str | os.PathLike[str] | None = None,
    executable_name: str = "hoi4.exe",
) -> str:
    """Find a game executable below a selected installation directory."""
    raw_target = str(target or "").strip()
    if not raw_target:
        return ""
    candidate = Path(raw_target) / str(executable_name or "hoi4.exe")
    try:
        return str(candidate) if candidate.is_file() else ""
    except OSError:
        return ""


def build_steam_launch_config(
    app_id: str | int = "394360",
    game_args: Sequence[str] = (),
    steam_executable: str | os.PathLike[str] = "",
    target: str | os.PathLike[str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | Sequence[str] | None = None,
    timeout_seconds: float = 0.0,
    wait_for_process: str = "hoi4.exe",
    startup_timeout_seconds: float = 60.0,
) -> contract.LaunchConfig:
    """Build a Steam AppID launch that observes the real HOI4 process.

    Steam's ``-applaunch`` helper may exit immediately after forwarding the
    request to the already-running Steam client.  The returned configuration
    therefore waits for a new ``hoi4.exe`` process before accepting the launch.
    """
    app_text = str(app_id or "").strip()
    if not app_text:
        raise ValueError("a Steam app id is required")
    if not app_text.isdigit():
        raise ValueError("Steam app id must contain only digits")
    executable = str(steam_executable or "") or discover_steam_executable(target)
    if not executable:
        raise ValueError("could not find steam.exe; pass --steam-executable")
    location = cwd
    if location is None:
        location = str(Path(executable).parent)
    return build_launch_config(
        executable=executable,
        args=("-applaunch", app_text, *(str(item) for item in (game_args or ()))),
        cwd=location,
        env=env,
        timeout_seconds=timeout_seconds,
        wait_for_process=wait_for_process,
        startup_timeout_seconds=startup_timeout_seconds,
        launcher_process="Paradox Launcher.exe",
    )


def describe_launch(config: contract.LaunchConfig) -> dict[str, Any]:
    """Record the planned launch command without executing anything."""
    payload = config.to_dict()
    payload["mode"] = "dry_run"
    payload["argv"] = config.argv()
    payload["executed"] = False
    payload["note"] = "Dry-run default: the command is recorded and never executed."
    return payload


def _process_image_name(value: str) -> str:
    """Return a Windows process image name from a path or bare image name."""
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


def _list_process_ids(image_name: str) -> set[int]:
    """List process IDs for an image using Windows' built-in tasklist command."""
    image = _process_image_name(image_name)
    if not image or os.name != "nt":
        return set()
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq %s" % image, "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    result: set[int] = set()
    for row in csv.reader((completed.stdout or "").splitlines()):
        if len(row) < 2 or row[0].strip().lower() != image.lower():
            continue
        try:
            result.add(int(row[1].strip()))
        except (TypeError, ValueError):
            continue
    return result


def _process_observation_error() -> str:
    """Explain why Windows process observation is unavailable, when applicable."""
    if os.name != "nt":
        return "process observation requires Windows tasklist support"
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "could not run tasklist: %s" % str(exc)
    combined = "%s\n%s" % (completed.stdout or "", completed.stderr or "")
    lowered = combined.lower()
    if completed.returncode != 0 or "access denied" in lowered or "zugriff verweigert" in lowered or "fehler:" in lowered:
        first_line = next((line.strip() for line in combined.splitlines() if line.strip()), "unknown tasklist error")
        return "tasklist cannot inspect desktop processes: %s" % first_line
    return ""


def _terminate_helper(process: subprocess.Popen[Any]) -> None:
    """Stop only the helper process that the harness started, when possible."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5.0)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


def _execute_observed_launch(
    config: contract.LaunchConfig,
    env_values: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Run a helper/launcher and wait for its newly created game process."""
    image = _process_image_name(config.wait_for_process)
    launcher_image = _process_image_name(config.launcher_process)
    observation_error = _process_observation_error()
    baseline = _list_process_ids(image)
    launcher_baseline = _list_process_ids(launcher_image)
    argv = config.argv()
    workdir = str(config.cwd) if str(config.cwd) else None
    if config.env_names:
        source = dict(env_values or {})
        if not source:
            source = dict(os.environ)
        child_env = {name: str(source[name]) for name in config.env_names if name in source}
    else:
        child_env = None
    outcome: dict[str, Any] = config.to_dict()
    outcome.update({
        "mode": "executed",
        "argv": argv,
        "executed": True,
        "observed_process": image,
        "observed_pids": [],
        "launcher_process": launcher_image,
        "launcher_pids": sorted(launcher_baseline),
        "launcher_detected": bool(launcher_baseline),
        "process_observation_error": observation_error,
        "helper_returncode": None,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
    })
    if observation_error:
        outcome.update({
            "status": "launch_failed",
            "returncode": None,
            "error": observation_error,
        })
        return outcome
    try:
        helper = subprocess.Popen(
            argv,
            cwd=workdir,
            env=child_env,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError) as exc:
        outcome.update({"status": "launch_failed", "returncode": None, "error": str(exc)})
        return outcome

    started_at = time.monotonic()
    startup_timeout = float(config.startup_timeout_seconds or 0.0)
    startup_deadline = started_at + startup_timeout if startup_timeout > 0.0 else None
    observed: set[int] = set()
    while True:
        observed = _list_process_ids(image) - baseline
        if observed:
            break
        launcher_observed = _list_process_ids(launcher_image) - launcher_baseline
        if launcher_observed:
            outcome["launcher_detected"] = True
            outcome["launcher_pids"] = sorted(launcher_observed)
        helper_returncode = helper.poll()
        if startup_deadline is not None and time.monotonic() >= startup_deadline:
            _terminate_helper(helper)
            outcome.update({
                "status": "timeout",
                "returncode": None,
                "helper_returncode": helper_returncode,
                "error": "timed out waiting for %s to appear after %s seconds" % (image, str(startup_timeout)),
            })
            if outcome["launcher_detected"]:
                outcome["error"] = (
                    "timed out waiting for %s; %s is open, so the launcher has not started the game"
                    % (image, launcher_image or "the game launcher")
                )
            return outcome
        time.sleep(0.25)

    observed_list = sorted(observed)
    outcome["observed_pids"] = observed_list
    session_timeout = float(config.timeout_seconds or 0.0)
    session_deadline = time.monotonic() + session_timeout if session_timeout > 0.0 else None
    while _list_process_ids(image).intersection(observed):
        if session_deadline is not None and time.monotonic() >= session_deadline:
            outcome.update({
                "status": "timeout",
                "returncode": None,
                "helper_returncode": helper.poll(),
                "error": "timed out waiting for %s to exit after %s seconds" % (image, str(session_timeout)),
            })
            return outcome
        time.sleep(0.5)

    helper_returncode = helper.poll()
    if helper_returncode is None:
        try:
            helper_returncode = helper.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            helper_returncode = None
    outcome.update({
        "status": "exited",
        "returncode": int(helper_returncode) if helper_returncode is not None else 0,
        "helper_returncode": int(helper_returncode) if helper_returncode is not None else None,
        "error": "",
    })
    return outcome


def execute_launch(
    config: contract.LaunchConfig,
    env_values: Mapping[str, str] | None = None,
    capture_limit: int = MAX_OUTPUT_CHARS,
) -> dict[str, Any]:
    """Execute a configured launch command without shell interpolation.

    This function must only be called when execution was explicitly requested.
    Standard output and error streams are captured with stable bounds.
    """
    if not str(config.executable):
        raise ValueError("a game executable is required for assisted execution")
    try:
        limit = int(capture_limit)
    except (TypeError, ValueError):
        raise ValueError("capture limit must be an integer")
    if limit <= 0:
        raise ValueError("capture limit must be positive")
    capture_limit = limit
    if str(config.wait_for_process or "").strip():
        return _execute_observed_launch(config, env_values=env_values)
    argv = config.argv()
    workdir = str(config.cwd) if str(config.cwd) else None
    if config.env_names:
        source = dict(env_values or {})
        if not source:
            source = dict(os.environ)
        child_env = {name: str(source[name]) for name in config.env_names if name in source}
    else:
        child_env = None
    timeout = float(config.timeout_seconds or 0.0)
    outcome: dict[str, Any] = config.to_dict()
    outcome["mode"] = "executed"
    outcome["argv"] = argv
    outcome["executed"] = True
    try:
        completed = subprocess.run(
            argv,
            cwd=workdir,
            env=child_env,
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout if timeout > 0.0 else None,
        )
    except FileNotFoundError as exc:
        outcome["status"] = "launch_failed"
        outcome["returncode"] = None
        outcome["error"] = str(exc)
        outcome["stdout"] = ""
        outcome["stderr"] = ""
        outcome["stdout_truncated"] = False
        outcome["stderr_truncated"] = False
        return outcome
    except subprocess.TimeoutExpired as exc:
        outcome["status"] = "timeout"
        outcome["returncode"] = None
        outcome["error"] = "launch timed out after %s seconds" % str(timeout)
        raw_out = exc.stdout if isinstance(exc.stdout, str) else ""
        raw_err = exc.stderr if isinstance(exc.stderr, str) else ""
        outcome["stdout"] = raw_out[:capture_limit]
        outcome["stderr"] = raw_err[:capture_limit]
        outcome["stdout_truncated"] = len(raw_out) > capture_limit
        outcome["stderr_truncated"] = len(raw_err) > capture_limit
        return outcome
    except OSError as exc:
        outcome["status"] = "launch_failed"
        outcome["returncode"] = None
        outcome["error"] = str(exc)
        outcome["stdout"] = ""
        outcome["stderr"] = ""
        outcome["stdout_truncated"] = False
        outcome["stderr_truncated"] = False
        return outcome
    raw_stdout = completed.stdout or ""
    raw_stderr = completed.stderr or ""
    outcome["status"] = "exited"
    outcome["returncode"] = int(completed.returncode)
    outcome["error"] = ""
    outcome["stdout"] = raw_stdout[:capture_limit]
    outcome["stderr"] = raw_stderr[:capture_limit]
    outcome["stdout_truncated"] = len(raw_stdout) > capture_limit
    outcome["stderr_truncated"] = len(raw_stderr) > capture_limit
    return outcome


def normalize_checklist(
    checked: Sequence[str] = (),
    notes: Mapping[str, str] | None = None,
    waived_checks: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Record checked and explicitly waived answers against the required ids."""
    known = set(contract.REQUIRED_CHECK_IDS)
    raw_checked = (checked,) if isinstance(checked, (str, bytes)) else (checked or ())
    wanted: set[str] = set()
    for item in raw_checked:
        check_id = str(item or "").strip()
        if not check_id:
            raise ValueError("Checklist check id cannot be empty.")
        if check_id not in known:
            raise ValueError("Unknown checklist check id: %s" % check_id)
        if check_id in wanted:
            raise ValueError("Checklist check id was provided more than once: %s" % check_id)
        wanted.add(check_id)

    def normalize_mapping(source: Mapping[str, Any] | None, label: str) -> dict[str, Any]:
        if source is None:
            return {}
        if not isinstance(source, Mapping):
            raise ValueError("Checklist %s must be a mapping keyed by check id." % label)
        normalized: dict[str, Any] = {}
        for raw_id, value in source.items():
            check_id = str(raw_id or "").strip()
            if not check_id:
                raise ValueError("Checklist %s check id cannot be empty." % label)
            if check_id not in known:
                raise ValueError("Unknown checklist check id: %s" % check_id)
            if check_id in normalized:
                raise ValueError("Checklist check id was provided more than once: %s" % check_id)
            normalized[check_id] = value
        return normalized

    provided_notes = normalize_mapping(notes, "notes")
    provided_waivers = normalize_mapping(waived_checks, "waivers")
    conflicts = sorted(wanted.intersection(provided_waivers))
    if conflicts:
        raise ValueError("A checklist check cannot be both checked and waived: %s" % ", ".join(conflicts))

    waiver_reasons: dict[str, str] = {}
    for check_id, raw_reason in provided_waivers.items():
        reason = _bounded_text(raw_reason, MAX_NOTE_CHARS).strip()
        if not reason:
            raise ValueError("Checklist waiver reason cannot be empty: %s" % check_id)
        waiver_reasons[check_id] = reason

    entries: list[dict[str, Any]] = []
    for check_id, title, detail in contract.REQUIRED_CHECKS:
        raw_note = provided_notes.get(check_id, "")
        entries.append(contract.ChecklistEntry(
            check_id=check_id,
            title=title,
            detail=detail,
            required=True,
            checked=check_id in wanted,
            waived=check_id in waiver_reasons,
            waiver_reason=waiver_reasons.get(check_id, ""),
            notes=_bounded_text(raw_note, MAX_NOTE_CHARS),
        ).to_dict())
    return entries


def summarize_checklist(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize checked, waived, and missing required checklist answers."""
    missing = contract.missing_required_checks(entries)
    by_id = {
        str(entry.get("check_id", "")): entry
        for entry in entries or ()
        if isinstance(entry, Mapping)
    }
    checked_count = sum(bool(by_id.get(check_id, {}).get("checked", False)) for check_id in contract.REQUIRED_CHECK_IDS)
    waived = [
        {
            "check_id": check_id,
            "reason": str(by_id.get(check_id, {}).get("waiver_reason", "") or ""),
        }
        for check_id in contract.REQUIRED_CHECK_IDS
        if bool(by_id.get(check_id, {}).get("waived", False))
    ]
    return {
        "required": len(contract.REQUIRED_CHECKS),
        "checked": checked_count,
        "waived": len(waived),
        "waived_checks": waived,
        "missing": missing,
        "all_checked": checked_count == len(contract.REQUIRED_CHECKS),
        "all_complete": len(missing) == 0,
    }


def _expected_captured_finding_classification(
    finding: Mapping[str, Any],
    active_dlc: Mapping[str, Any],
) -> tuple[str, str]:
    """Reclassify one stored finding using the same evidence-gated rules as collection."""
    source = str(finding.get("source", "") or "")
    text = str(finding.get("text", "") or "")
    severity, category = contract.classify_line(text, source=source)
    if severity == "error":
        owner = _optional_dlc_owner_for_line(text, source)
        if owner and _owner_dlc_proven_inactive(owner, active_dlc):
            category = "dlc_unrelated"
        elif (
            _is_error_log_path(source)
            and _DLC_CHECKSUM_ERROR_RE.search(text) is not None
            and active_dlc.get("status") == "complete"
        ):
            category = "dlc_unrelated"
    return severity, category


def _validate_fresh_system_log_evidence(
    evidence: Mapping[str, Any],
    log_files: Sequence[Mapping[str, Any]],
    label: str,
) -> None:
    """Require a complete proof record to match one captured fresh system.log."""
    source = str(evidence.get("source", "") or "")
    if not _is_system_log_path(source):
        raise ValueError("Acceptance report %s evidence has no system.log source." % label)
    try:
        fresh_lines = int(evidence.get("fresh_lines", -1))
    except (TypeError, ValueError):
        raise ValueError("Acceptance report %s evidence has an invalid fresh-line count." % label) from None
    if fresh_lines <= 0 or bool(evidence.get("truncated", False)):
        raise ValueError("Acceptance report %s evidence is not complete fresh system.log evidence." % label)
    system_logs = [
        item
        for item in log_files
        if _is_system_log_path(str(item.get("path", "") or ""))
    ]
    if len(system_logs) != 1 or str(system_logs[0].get("path", "") or "") != source:
        raise ValueError("Acceptance report %s evidence does not match one unambiguous captured system.log." % label)
    captured = system_logs[0]
    try:
        captured_lines = int(captured.get("fresh_lines", -1))
    except (TypeError, ValueError):
        captured_lines = -1
    if (
        str(captured.get("status", "") or "") != "ok"
        or not bool(captured.get("generated", False))
        or bool(captured.get("truncated", False))
        or captured_lines != fresh_lines
    ):
        raise ValueError("Acceptance report %s evidence conflicts with captured system.log metadata." % label)


def _is_error_log_path(path: str | os.PathLike[str]) -> bool:
    """Match error.log by basename across POSIX and Windows path separators."""
    normalized = str(path or "").replace("\\", "/").rstrip("/").casefold()
    return normalized.rsplit("/", 1)[-1] == "error.log"


def _required_error_log_evidence(
    files: Sequence[Mapping[str, Any]],
    required: bool,
    execute: bool,
) -> dict[str, Any]:
    """Summarize whether each configured error.log was freshly generated or touched."""
    if not required:
        return {"required": False, "status": "not_required", "paths": []}
    if not execute:
        return {"required": True, "status": "not_checked", "paths": []}
    candidates: list[dict[str, Any]] = []
    for record in files or ():
        path = str(record.get("path", "") or "")
        if not _is_error_log_path(path):
            continue
        file_status = str(record.get("status", "") or "unknown")
        generated = bool(record.get("generated", False))
        status = "generated" if file_status == "ok" and generated else file_status
        if file_status == "ok" and not generated:
            status = "stale"
        candidates.append({
            "path": path,
            "status": status,
            "fresh_bytes": int(record.get("fresh_bytes", 0) or 0),
            "rewritten": bool(record.get("rewritten", False)),
        })
    if not candidates:
        return {"required": True, "status": "not_configured", "paths": []}
    overall = "generated"
    for candidate in candidates:
        if candidate["status"] != "generated":
            overall = str(candidate["status"])
            break
    return {"required": True, "status": overall, "paths": candidates}


def _required_active_mod_failure_reason(evidence: Mapping[str, Any]) -> str:
    """Describe why fresh system.log evidence does not prove the staged mod."""
    expected = str(evidence.get("expected_name", "") or "")
    status = str(evidence.get("status", "") or "")
    if status == "matched":
        return ""
    if status == "missing":
        return (
            "Managed activation could not be proven: fresh system.log lacks a complete "
            "Active Mod Count/Active Mod record for expected mod %r." % expected
        )
    if status == "unreadable":
        return "Managed activation could not verify expected mod %r because fresh system.log is unreadable or truncated." % expected
    if status == "ambiguous":
        return "Managed activation could not verify expected mod %r because multiple system.log paths were watched." % expected
    if status == "not_configured":
        return "Managed activation requires fresh system.log evidence for expected mod %r, but no system.log path was watched." % expected
    return (
        "Managed activation expected exactly one active mod named %r, but fresh system.log reported "
        "count=%r and names=%r." % (expected, evidence.get("count"), evidence.get("observed_names", []))
    )


def run_harness(
    artifact_dir: str | os.PathLike[str],
    target: str = "",
    profile: str = "acceptance",
    game_version: str = "",
    log_paths: Sequence[str | os.PathLike[str]] = (),
    archive_dir: str | os.PathLike[str] | None = None,
    save_dir: str | os.PathLike[str] | None = None,
    save_names: Sequence[str] = (),
    launch_config: contract.LaunchConfig | None = None,
    launch_env: Mapping[str, str] | None = None,
    execute: bool = False,
    checked: Sequence[str] = (),
    check_notes: Mapping[str, str] | None = None,
    waived_checks: Mapping[str, str] | None = None,
    expected_identity_hash: str = "",
    expected_profile: str = "",
    snapshot_ns: int | None = None,
    created_at: str = "",
    capture_limit: int = MAX_OUTPUT_CHARS,
    require_error_log: bool = True,
    managed_activation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the assisted acceptance workflow and return the result document.

    Execution of the configured game command happens only when execute is
    explicitly True. Every other path records the dry-run plan. Executed runs
    require a readable, observably generated or modified ``error.log`` by
    default. Disabling that requirement needs a non-empty explicit log set
    whose paths are not named ``error.log``.
    """
    selected_log_paths = tuple(log_paths or ())
    entries = normalize_checklist(
        checked=checked,
        notes=check_notes,
        waived_checks=waived_checks,
    )
    checklist_summary = summarize_checklist(entries)
    if managed_activation and not execute:
        raise ValueError("managed activation requires an executed run")
    expected_active_mod_name = ""
    if managed_activation:
        expected_active_mod_name = str(managed_activation.get("descriptor_name", "") or "")
        if not expected_active_mod_name:
            raise ValueError("managed activation requires the staged descriptor name")
    if execute and not require_error_log:
        explicit_paths = [str(item or "").strip() for item in selected_log_paths if str(item or "").strip()]
        if not explicit_paths or any(_is_error_log_path(item) for item in explicit_paths):
            raise ValueError("Disabling the error.log requirement needs an explicit non-error log set.")
    moment_ns = int(snapshot_ns) if snapshot_ns is not None else time.time_ns()
    artifact = verify_artifact(
        artifact_dir,
        expected_identity_hash=expected_identity_hash,
        expected_profile=expected_profile,
    )
    snapshots = [snapshot_log_file(item, archive_dir=archive_dir, snapshot_ns=moment_ns) for item in selected_log_paths]
    if launch_config is None:
        if execute:
            launch_record: dict[str, Any] = {"mode": "not_configured", "executed": False, "argv": [], "status": "missing_command", "error": "Assisted execution was requested but no game command was configured.", "note": "No game command was configured."}
        else:
            launch_record: dict[str, Any] = {"mode": "not_configured", "executed": False, "argv": [], "note": "No game command was configured."}
        launch_identity: dict[str, Any] = {"executable_name": "", "args": [], "timeout_seconds": 0.0}
    elif execute:
        try:
            launch_record = execute_launch(launch_config, env_values=launch_env, capture_limit=capture_limit)
        except (OSError, ValueError) as exc:
            launch_record = {"mode": "executed", "executed": False, "argv": launch_config.argv(), "status": "launch_failed", "returncode": None, "error": str(exc), "stdout": "", "stderr": "", "stdout_truncated": False, "stderr_truncated": False}
        launch_identity = launch_config.identity()
    else:
        launch_record = describe_launch(launch_config)
        launch_identity = launch_config.identity()
    launch_identity = dict(launch_identity)
    launch_identity["require_error_log"] = bool(require_error_log)
    activation_record: dict[str, Any] = {}
    if managed_activation:
        activation_record = {
            "enabled": True,
            "descriptor_name": str(managed_activation.get("descriptor_name", "") or ""),
            "descriptor_reference": str(managed_activation.get("descriptor_reference", "") or ""),
        }
        launch_identity["managed_activation"] = dict(activation_record)
        launch_record = dict(launch_record)
        launch_record["managed_activation"] = dict(activation_record)
    fresh = collect_fresh_findings(
        snapshots,
        expected_active_mod_name=expected_active_mod_name,
        require_active_mod=bool(managed_activation),
    )
    summary = summarize_findings(fresh["findings"])
    active_mod_evidence = fresh["active_mod"]
    required_error_log = _required_error_log_evidence(
        fresh["files"],
        required=bool(require_error_log),
        execute=bool(execute),
    )
    required_log_failure = contract.required_error_log_failure_reason(required_error_log, execute=bool(execute))
    required_active_mod_failure = (
        _required_active_mod_failure_reason(active_mod_evidence) if managed_activation else ""
    )
    saves = detect_expected_saves(save_dir, save_names, snapshot_ns=moment_ns)
    nonfresh_saves = [item for item in saves if item.get("status") != "fresh"]
    mode = "assisted" if execute else "dry_run"
    launch_reason = contract.launch_failure_reason(launch_record, execute=bool(execute))
    launch_ok = not bool(launch_reason)
    status, reasons = contract.decide_status(
        mode=mode,
        artifact_ok=artifact_ok(artifact),
        artifact_mismatch=len(artifact.get("mismatch", [])) > 0,
        blocker_errors=int(summary.get("blocker_count", 0) or 0),
        unchecked_required=checklist_summary.get("missing", []),
        launch_ok=launch_ok,
        launch_reason=launch_reason,
        required_log_failure=required_log_failure,
        required_active_mod_failure=required_active_mod_failure,
        save_evidence=nonfresh_saves,
        waived_required=[
            {"check_id": item["check_id"], "reason": item["waiver_reason"]}
            for item in entries
            if item.get("waived")
        ],
    )
    identity_core = contract.build_identity_core(
        artifact_fingerprint=str(artifact.get("fingerprint", "") or ""),
        manifest_identity=str(artifact.get("manifest", {}).get("identity_hash", "") or ""),
        lock_identity=str(artifact.get("lock", {}).get("identity_hash", "") or ""),
        target=str(target or ""),
        profile=str(profile or ""),
        game_version=str(game_version or ""),
        launch_identity=launch_identity,
        expected_identity_hash=str(expected_identity_hash or ""),
        foundation_source_identity=str(
            artifact.get("manifest", {})
            .get("foundation_source_identity", {})
            .get("identity_hash", "")
            or ""
        ),
        checklist_entries=entries,
    )
    identity_hash = contract.compute_identity_hash(identity_core)
    run_id = contract.compute_run_id(identity_core)
    observed_at = str(created_at or contract.utc_now_iso())
    return contract.assemble_result(
        run_id=run_id,
        identity_hash=identity_hash,
        identity_core=identity_core,
        created_at=observed_at,
        mode=mode,
        status=status,
        reasons=reasons,
        target={"target": str(target or ""), "profile": str(profile or ""), "game_version": str(game_version or "")},
        artifact=artifact,
        launch=launch_record,
        logs={
            "snapshots": snapshots,
            "files": fresh["files"],
            "findings": fresh["findings"],
            "summary": summary,
            "dropped_findings": int(fresh["dropped_findings"]),
            "required_error_log": required_error_log,
            "active_dlc": fresh["active_dlc"],
            "active_mod": active_mod_evidence,
        },
        saves=saves,
        checklist=entries,
        checklist_summary=checklist_summary,
    )


def _canonicalize_existing_checklist(
    raw_entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate and order a saved report checklist without losing its notes."""
    known = {check_id: (title, detail) for check_id, title, detail in contract.REQUIRED_CHECKS}
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(raw_entries, (str, bytes)) or not isinstance(raw_entries, Sequence):
        raise ValueError("Existing acceptance report has no valid checklist.")
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise ValueError("Existing acceptance report contains a malformed checklist entry.")
        check_id = str(raw.get("check_id", "") or "").strip()
        if not check_id or check_id not in known:
            raise ValueError("Existing acceptance report contains an unknown checklist id: %s" % (check_id or "<empty>"))
        if check_id in by_id:
            raise ValueError("Existing acceptance report repeats checklist id: %s" % check_id)
        for field in ("checked", "waived"):
            if field in raw and not isinstance(raw[field], bool):
                raise ValueError("Existing checklist %s value must be boolean: %s" % (field, check_id))
        checked = raw.get("checked", False)
        waived = raw.get("waived", False)
        raw_reason = raw.get("waiver_reason", "")
        if not isinstance(raw_reason, str):
            raise ValueError("Existing checklist waiver reason must be text: %s" % check_id)
        waiver_reason = raw_reason.strip()
        if checked and waived:
            raise ValueError("Existing checklist check cannot be both checked and waived: %s" % check_id)
        if waived and not waiver_reason:
            raise ValueError("Existing waived checklist check has no reason: %s" % check_id)
        if not waived and waiver_reason:
            raise ValueError("Existing unchecked checklist entry has a stray waiver reason: %s" % check_id)
        raw_notes = raw.get("notes", "")
        if not isinstance(raw_notes, str):
            raise ValueError("Existing checklist note must be text: %s" % check_id)
        entry = copy.deepcopy(dict(raw))
        title, detail = known[check_id]
        entry.update({
            "check_id": check_id,
            "title": str(raw.get("title", "") or title),
            "detail": str(raw.get("detail", "") or detail),
            "required": True,
            "checked": checked,
            "waived": waived,
            "waiver_reason": waiver_reason,
            "notes": raw_notes,
        })
        by_id[check_id] = entry
    missing = [check_id for check_id in contract.REQUIRED_CHECK_IDS if check_id not in by_id]
    if missing:
        raise ValueError("Existing acceptance report is missing required checklist entries: %s" % ", ".join(missing))
    entries: list[dict[str, Any]] = []
    for check_id, title, detail in contract.REQUIRED_CHECKS:
        entries.append(by_id[check_id])
    return entries


def _status_from_captured_result(
    result: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
) -> tuple[str, list[str]]:
    """Recompute status using only evidence already stored in a report."""
    artifact = result["artifact"]
    logs = result["logs"]
    launch = result["launch"]
    summary = logs["summary"]
    required_error_log = logs["required_error_log"]
    active_mod = logs.get("active_mod", {})
    nonfresh_saves = [item for item in result["saves"] if item.get("status") != "fresh"]
    try:
        blocker_count = int(summary.get("blocker_count", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("Acceptance report has an invalid blocker count.") from None
    if blocker_count < 0:
        raise ValueError("Acceptance report blocker count cannot be negative.")
    launch_reason = contract.launch_failure_reason(launch, execute=True)
    required_active_mod_failure = (
        _required_active_mod_failure_reason(active_mod)
        if isinstance(active_mod, Mapping) and bool(active_mod.get("required"))
        else ""
    )
    checklist_summary = summarize_checklist(entries)
    return contract.decide_status(
        mode="assisted",
        artifact_ok=artifact_ok(artifact),
        artifact_mismatch=bool(artifact.get("mismatch", [])),
        blocker_errors=blocker_count,
        unchecked_required=checklist_summary["missing"],
        launch_ok=not bool(launch_reason),
        launch_reason=launch_reason,
        required_log_failure=contract.required_error_log_failure_reason(required_error_log, execute=True),
        required_active_mod_failure=required_active_mod_failure,
        save_evidence=nonfresh_saves,
        waived_required=[
            {"check_id": item["check_id"], "reason": item["waiver_reason"]}
            for item in entries
            if item.get("waived")
        ],
    )


def validate_result_integrity(
    source_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Validate the internal evidence links of a completed assisted report.

    The JSON report is intentionally portable and is not a signed document,
    but consumers must never trust a hand-edited top-level ``passed`` value.
    This check recomputes every derived value that is available from the
    captured evidence before a report may be amended or attached to a freeze.
    The returned checklist is canonicalized in required-check order.
    """
    if not isinstance(source_result, Mapping):
        raise ValueError("Acceptance report must be a JSON object.")
    if str(source_result.get("schema", "")) != contract.ENGINE_ACCEPTANCE_SCHEMA:
        raise ValueError("Acceptance report schema is unsupported.")
    if str(source_result.get("mode", "")) != "assisted":
        raise ValueError("Only a completed assisted acceptance report is valid evidence.")
    if str(source_result.get("status", "")) not in contract.RESULT_STATUSES:
        raise ValueError("Acceptance report has an invalid status.")

    target = source_result.get("target")
    artifact = source_result.get("artifact")
    logs = source_result.get("logs")
    saves = source_result.get("saves")
    created_at = source_result.get("created_at")
    if not isinstance(target, Mapping) or not isinstance(artifact, Mapping) or not isinstance(logs, Mapping):
        raise ValueError("Acceptance report is missing structured target, artifact, or log evidence.")
    if not isinstance(saves, Sequence) or isinstance(saves, (str, bytes)):
        raise ValueError("Acceptance report has malformed save evidence.")
    if any(not isinstance(item, Mapping) for item in saves):
        raise ValueError("Acceptance report contains malformed save evidence.")
    if not isinstance(created_at, str) or not created_at.strip():
        raise ValueError("Acceptance report has no creation timestamp.")

    manifest = artifact.get("manifest")
    lock = artifact.get("lock", {})
    if not isinstance(manifest, Mapping) or not isinstance(lock, Mapping):
        raise ValueError("Acceptance report has malformed manifest or lock evidence.")
    stored_log_summary = logs.get("summary")
    required_error_log = logs.get("required_error_log")
    findings = logs.get("findings")
    log_files = logs.get("files")
    if not isinstance(stored_log_summary, Mapping) or not isinstance(required_error_log, Mapping):
        raise ValueError("Acceptance report has malformed log summary or error.log evidence.")
    if not isinstance(findings, Sequence) or isinstance(findings, (str, bytes)):
        raise ValueError("Acceptance report has malformed log findings.")
    if any(not isinstance(item, Mapping) for item in findings):
        raise ValueError("Acceptance report contains malformed log findings.")
    if not isinstance(log_files, Sequence) or isinstance(log_files, (str, bytes)):
        raise ValueError("Acceptance report has malformed log-file evidence.")
    if any(not isinstance(item, Mapping) for item in log_files):
        raise ValueError("Acceptance report contains malformed log-file evidence.")
    active_dlc = logs.get("active_dlc", {})
    if not isinstance(active_dlc, Mapping):
        raise ValueError("Acceptance report has malformed active-DLC evidence.")
    if str(active_dlc.get("status", "") or "") == "complete":
        observed_dlc_names = active_dlc.get("observed_names")
        if not isinstance(observed_dlc_names, list) or any(
            not isinstance(name, str) or not name.strip()
            for name in observed_dlc_names
        ):
            raise ValueError("Acceptance report has malformed active-DLC names.")
        try:
            observed_dlc_count = int(active_dlc.get("count", -1))
        except (TypeError, ValueError):
            raise ValueError("Acceptance report has an invalid active-DLC count.") from None
        if observed_dlc_count != len(observed_dlc_names):
            raise ValueError("Acceptance report active-DLC count conflicts with its observed names.")
        normalized_dlc_names = [name.strip().casefold() for name in observed_dlc_names]
        if len(set(normalized_dlc_names)) != len(normalized_dlc_names):
            raise ValueError("Acceptance report active-DLC names contain duplicates.")
        _validate_fresh_system_log_evidence(active_dlc, log_files, "active-DLC")
    for finding in findings:
        expected_severity, expected_category = _expected_captured_finding_classification(
            finding,
            active_dlc,
        )
        if str(finding.get("severity", "") or "") != expected_severity:
            raise ValueError("Acceptance report finding severity conflicts with its captured text.")
        if str(finding.get("category", "") or "") != expected_category:
            raise ValueError("Acceptance report finding category conflicts with its captured text.")
    derived_log_summary = summarize_findings(findings)
    for key in (
        "total", "errors", "warnings", "by_category", "blocker_count",
        "blocker_categories", "verdict",
    ):
        if stored_log_summary.get(key) != derived_log_summary[key]:
            raise ValueError("Acceptance report log summary conflicts with its findings (%s)." % key)
    derived_error_log = _required_error_log_evidence(
        log_files,
        required=bool(required_error_log.get("required", True)),
        execute=True,
    )
    if dict(required_error_log) != derived_error_log:
        raise ValueError("Acceptance report error.log summary conflicts with its file evidence.")

    active_mod = logs.get("active_mod", {})
    if active_mod and not isinstance(active_mod, Mapping):
        raise ValueError("Acceptance report has malformed active-mod evidence.")
    if isinstance(active_mod, Mapping) and bool(active_mod.get("required")):
        expected_name = str(active_mod.get("expected_name", "") or "")
        observed_names = active_mod.get("observed_names", [])
        try:
            observed_count = int(active_mod.get("count", -1))
        except (TypeError, ValueError):
            raise ValueError("Acceptance report has an invalid active-mod count.") from None
        if not isinstance(observed_names, list) or any(not isinstance(name, str) for name in observed_names):
            raise ValueError("Acceptance report has malformed active-mod names.")
        if str(active_mod.get("status", "") or "") == "matched" and (
            not expected_name
            or observed_count != 1
            or observed_names != [expected_name]
        ):
            raise ValueError("Acceptance report active-mod match conflicts with its observed names.")
        if str(active_mod.get("status", "") or "") == "matched":
            _validate_fresh_system_log_evidence(active_mod, log_files, "active-mod")

    if not isinstance(source_result.get("checklist_summary"), Mapping):
        raise ValueError("Acceptance report has no valid checklist summary.")
    launch = source_result.get("launch", {})
    if not isinstance(launch, Mapping) or not bool(launch.get("executed")):
        raise ValueError("Acceptance report does not contain an executed game launch.")
    if str(launch.get("status", "")) != "exited":
        raise ValueError("Acceptance report game process did not finish normally.")
    try:
        returncode = int(launch.get("returncode", 0))
    except (TypeError, ValueError):
        raise ValueError("Acceptance report has an invalid launch return code.") from None
    if returncode != 0:
        raise ValueError("Acceptance report game process exited with a non-zero return code.")

    source_identity_core = source_result.get("identity_core")
    if not isinstance(source_identity_core, Mapping):
        raise ValueError("Acceptance report has no identity core to verify.")
    identity_links = (
        ("artifact_fingerprint", str(artifact.get("fingerprint", "") or "")),
        ("manifest_identity", str(manifest.get("identity_hash", "") or "")),
        ("lock_identity", str(lock.get("identity_hash", "") or "")),
        ("target", str(target.get("target", "") or "")),
        ("profile", str(target.get("profile", "") or "")),
        ("game_version", str(target.get("game_version", "") or "")),
    )
    for identity_key, captured_value in identity_links:
        if str(source_identity_core.get(identity_key, "") or "") != captured_value:
            raise ValueError("Acceptance report identity core conflicts with captured %s evidence." % identity_key)
    if "foundation_source_identity" in source_identity_core:
        captured_source = manifest.get("foundation_source_identity", {})
        captured_source_hash = (
            str(captured_source.get("identity_hash", "") or "")
            if isinstance(captured_source, Mapping)
            else ""
        )
        if str(source_identity_core.get("foundation_source_identity", "") or "") != captured_source_hash:
            raise ValueError(
                "Acceptance report identity core conflicts with captured foundation_source_identity evidence."
            )
    original_identity_hash = contract.compute_identity_hash(source_identity_core)
    original_run_id = contract.compute_run_id(source_identity_core)
    if str(source_result.get("identity_hash", "")) != original_identity_hash:
        raise ValueError("Acceptance report identity hash does not match its captured identity core.")
    if str(source_result.get("run_id", "")) != original_run_id:
        raise ValueError("Acceptance report run id does not match its captured identity core.")

    entries = _canonicalize_existing_checklist(source_result.get("checklist", ()))
    attestation = source_identity_core.get("checklist_attestation")
    if attestation is not None and attestation != contract.canonical_checklist_attestation(entries):
        raise ValueError("Acceptance report checklist conflicts with its identity attestation.")
    stored_checklist_summary = source_result["checklist_summary"]
    derived_checklist_summary = summarize_checklist(entries)
    for summary_key in ("required", "checked", "missing"):
        if stored_checklist_summary.get(summary_key) != derived_checklist_summary[summary_key]:
            raise ValueError("Acceptance report checklist summary conflicts with its checklist (%s)." % summary_key)
    for summary_key in ("all_checked", "waived", "all_complete"):
        if summary_key in stored_checklist_summary and stored_checklist_summary[summary_key] != derived_checklist_summary[summary_key]:
            raise ValueError("Acceptance report checklist summary conflicts with its checklist (%s)." % summary_key)
    original_status, _original_reasons = _status_from_captured_result(source_result, entries)
    if str(source_result.get("status", "")) != original_status:
        raise ValueError("Acceptance report status conflicts with its captured evidence.")
    return entries


def amend_checklist_result(
    source_result: Mapping[str, Any],
    checked: Sequence[str] = (),
    waived_checks: Mapping[str, str] | None = None,
    check_notes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Amend only checklist attestations in a completed, internally consistent run.

    Captured launch, artifact, log, save, and target evidence is copied verbatim.
    Status/reasons and the deterministic run identity are recomputed from that
    existing evidence plus the updated checklist; no game process is launched.
    """
    entries = validate_result_integrity(source_result)
    source_identity_core = source_result["identity_core"]

    normalized = normalize_checklist(
        checked=checked,
        notes=check_notes,
        waived_checks=waived_checks,
    )
    selected = {item["check_id"]: item for item in normalized}
    normalized_notes = {
        str(check_id).strip(): _bounded_text(note, MAX_NOTE_CHARS)
        for check_id, note in (check_notes or {}).items()
    }
    for entry in entries:
        update = selected[entry["check_id"]]
        if update["checked"]:
            entry["checked"] = True
            entry["waived"] = False
            entry["waiver_reason"] = ""
        elif update["waived"]:
            entry["checked"] = False
            entry["waived"] = True
            entry["waiver_reason"] = update["waiver_reason"]
            # A prior checked-note can contradict a later explicit waiver.
            entry["notes"] = ""
        if entry["check_id"] in normalized_notes:
            entry["notes"] = normalized_notes[entry["check_id"]]

    amended = copy.deepcopy(dict(source_result))
    amended["checklist"] = entries
    checklist_summary = summarize_checklist(entries)
    amended["checklist_summary"] = checklist_summary

    status, reasons = _status_from_captured_result(amended, entries)
    identity_core = copy.deepcopy(dict(source_identity_core))
    identity_core["checklist_attestation"] = contract.canonical_checklist_attestation(entries)
    amended["identity_core"] = identity_core
    amended["identity_hash"] = contract.compute_identity_hash(identity_core)
    amended["run_id"] = contract.compute_run_id(identity_core)
    amended["status"] = status
    amended["reasons"] = reasons
    return amended


def amended_result_path(source_path: str | os.PathLike[str]) -> Path:
    """Return a sibling path that cannot overwrite the source report by default."""
    source = Path(source_path)
    return source.with_name(source.stem + "-amended" + source.suffix)


def write_result(output_path: str | os.PathLike[str], result: Mapping[str, Any]) -> str:
    """Write an engine_acceptance.json document deterministically."""
    destination = Path(output_path)
    if destination.parent and str(destination.parent):
        destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contract.result_to_json(dict(result)), encoding="utf-8")
    return str(destination)


def write_result_exclusive(output_path: str | os.PathLike[str], result: Mapping[str, Any]) -> str:
    """Create a result file only if absent, never replacing existing evidence."""
    destination = Path(output_path)
    if destination.parent and str(destination.parent):
        destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(contract.result_to_json(dict(result)))
    return str(destination)


def load_result(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load an engine_acceptance.json document back into plain data."""
    return contract.result_from_json(Path(path).read_text(encoding="utf-8-sig"))
