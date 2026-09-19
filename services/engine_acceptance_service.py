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
import hashlib
import json
import os
import subprocess
import time
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
MAX_OUTPUT_CHARS = 65536
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_NOTE_CHARS = 500
SAVE_HASH_LIMIT_BYTES = 256 * 1024 * 1024


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
        "manifest": {"present": False, "identity_hash": "", "profile": "", "target": {}, "status": "absent"},
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
        record["manifest"] = {
            "present": True,
            "identity_hash": _manifest_identity(manifest),
            "profile": _manifest_profile(manifest),
            "target": _manifest_target(manifest),
            "status": manifest_status,
        }
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
    try:
        stat = candidate.stat()
    except OSError:
        record["status"] = "unreadable"
        return record
    record["exists"] = True
    record["size"] = int(stat.st_size)
    record["offset"] = int(stat.st_size)
    record["mtime_ns"] = int(stat.st_mtime_ns)
    record["mtime_iso"] = _utc_iso_from_ns(int(stat.st_mtime_ns))
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
    """Read only the bytes appended after a log snapshot offset."""
    try:
        path = str(snapshot.get("path", ""))
        offset = int(snapshot.get("offset", 0) or 0)
    except (AttributeError, TypeError, ValueError):
        return {"path": "", "status": "invalid_snapshot", "text": "", "lines": [], "byte_count": 0, "new_offset": 0, "truncated": False}
    outcome: dict[str, Any] = {
        "path": path,
        "status": "ok",
        "text": "",
        "lines": [],
        "byte_count": 0,
        "new_offset": offset,
        "truncated": False,
    }
    candidate = Path(path)
    if not candidate.is_file():
        outcome["status"] = "missing"
        return outcome
    try:
        size = candidate.stat().st_size
    except OSError:
        outcome["status"] = "unreadable"
        return outcome
    if size < offset:
        offset = 0
    try:
        with open(candidate, "rb") as handle:
            handle.seek(offset)
            raw = handle.read(max_bytes + 1)
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


def collect_fresh_findings(snapshots: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Classify only fresh post-snapshot log ranges into structured findings."""
    findings: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    dropped = 0
    for snapshot in snapshots or ():
        try:
            label = str(snapshot.get("path", ""))
            exists = bool(snapshot.get("exists", False))
            status = str(snapshot.get("status", ""))
        except AttributeError:
            continue
        if not exists:
            files.append({"path": label, "status": "missing", "fresh_bytes": 0, "fresh_lines": 0, "new_offset": 0, "truncated": False})
            continue
        if status not in ("snapshotted", "archive_failed"):
            files.append({"path": label, "status": status, "fresh_bytes": 0, "fresh_lines": 0, "new_offset": 0, "truncated": False})
            continue
        fresh = read_fresh_lines(snapshot)
        if fresh["status"] != "ok":
            files.append({"path": label, "status": fresh["status"], "fresh_bytes": 0, "fresh_lines": 0, "new_offset": 0, "truncated": False})
            continue
        files.append({
            "path": label,
            "status": "ok",
            "fresh_bytes": int(fresh["byte_count"]),
            "fresh_lines": len(fresh["lines"]),
            "new_offset": int(fresh["new_offset"]),
            "truncated": bool(fresh["truncated"]),
        })
        for index, line in enumerate(fresh["lines"], start=1):
            kind, category = contract.classify_line(line)
            if kind == "info":
                continue
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
    return {"findings": findings, "files": files, "dropped_findings": dropped}


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
            present = candidate.is_file()
        except OSError:
            present = False
        if not present:
            evidence.append(entry)
            continue
        try:
            stat = candidate.stat()
        except OSError:
            entry["status"] = "unreadable"
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
) -> list[dict[str, Any]]:
    """Record checklist answers against the stable ordered M7.4 check ids."""
    wanted = {str(item) for item in (checked or ()) if str(item)}
    provided_notes = dict(notes or {})
    entries: list[dict[str, Any]] = []
    for check_id, title, detail in contract.REQUIRED_CHECKS:
        raw_note = provided_notes.get(check_id, "")
        entries.append(contract.ChecklistEntry(
            check_id=check_id,
            title=title,
            detail=detail,
            required=True,
            checked=check_id in wanted,
            notes=_bounded_text(raw_note, MAX_NOTE_CHARS),
        ).to_dict())
    return entries


def summarize_checklist(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize recorded checklist answers with the missing required ids."""
    missing = contract.missing_required_checks(entries)
    try:
        total = len(list(entries or ()))
    except TypeError:
        total = 0
    checked_count = max(0, total - len(missing))
    return {
        "required": len(contract.REQUIRED_CHECKS),
        "checked": checked_count,
        "missing": missing,
        "all_checked": len(missing) == 0,
    }


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
    expected_identity_hash: str = "",
    expected_profile: str = "",
    snapshot_ns: int | None = None,
    created_at: str = "",
    capture_limit: int = MAX_OUTPUT_CHARS,
) -> dict[str, Any]:
    """Run the assisted acceptance workflow and return the result document.

    Execution of the configured game command happens only when execute is
    explicitly True. Every other path records the dry-run plan.
    """
    moment_ns = int(snapshot_ns) if snapshot_ns is not None else time.time_ns()
    artifact = verify_artifact(
        artifact_dir,
        expected_identity_hash=expected_identity_hash,
        expected_profile=expected_profile,
    )
    snapshots = [snapshot_log_file(item, archive_dir=archive_dir, snapshot_ns=moment_ns) for item in (log_paths or ())]
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
    fresh = collect_fresh_findings(snapshots)
    summary = summarize_findings(fresh["findings"])
    entries = normalize_checklist(checked=checked, notes=check_notes)
    checklist_summary = summarize_checklist(entries)
    saves = detect_expected_saves(save_dir, save_names, snapshot_ns=moment_ns)
    missing_saves = [str(item.get("name", "")) for item in saves if item.get("status") == "missing"]
    stale_saves = [str(item.get("name", "")) for item in saves if item.get("status") == "stale"]
    mode = "assisted" if execute else "dry_run"
    launch_reason = contract.launch_failure_reason(launch_record, execute=bool(execute))
    launch_ok = not bool(launch_reason)
    status, reasons = contract.decide_status(
        mode=mode,
        artifact_ok=artifact_ok(artifact),
        artifact_mismatch=len(artifact.get("mismatch", [])) > 0,
        blocker_errors=int(summary.get("blocker_count", 0) or 0),
        unchecked_required=checklist_summary.get("missing", []),
        missing_saves=missing_saves,
        stale_saves=stale_saves,
        launch_ok=launch_ok,
        launch_reason=launch_reason,
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
        logs={"snapshots": snapshots, "findings": fresh["findings"], "summary": summary, "dropped_findings": int(fresh["dropped_findings"])},
        saves=saves,
        checklist=entries,
        checklist_summary=checklist_summary,
    )


def write_result(output_path: str | os.PathLike[str], result: Mapping[str, Any]) -> str:
    """Write an engine_acceptance.json document deterministically."""
    destination = Path(output_path)
    if destination.parent and str(destination.parent):
        destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contract.result_to_json(dict(result)), encoding="utf-8")
    return str(destination)


def load_result(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load an engine_acceptance.json document back into plain data."""
    return contract.result_from_json(Path(path).read_text(encoding="utf-8-sig"))
