"""Deterministic assisted engine-acceptance contracts (M7.1 through M7.4).

This module is intentionally dependency-free and performs no filesystem or
subprocess access. It defines the stable automation boundaries, the required
in-game checklist, deterministic log-error classification, checklist gating,
final-status decisions, and the deterministic run-identity scheme shared by
the service layer and the command-line harness.

Automation boundaries: the harness automates artifact preparation records,
launch-configuration records, fresh-log capture, log classification,
save-file detection, and result recording. It never performs GUI or mouse
automation, and launching the closed-source game is strictly opt-in. The
default mode is always a dry run that records what would happen.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


ENGINE_ACCEPTANCE_SCHEMA = "engine-acceptance/1"

RESULT_STATUSES = ("dry_run", "passed", "failed", "blocked", "incomplete")

RUN_MODES = ("dry_run", "assisted")

LOG_CATEGORIES = ("map", "asset", "script", "country_tag", "audio_unrelated", "unknown")

BLOCKER_CATEGORIES = ("map", "asset", "script", "country_tag", "unknown")

FINDING_SEVERITIES = ("error", "warning")

REQUIRED_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("main_menu", "Reach the main menu", "Reach the main menu without map initialization failure."),
    ("bookmark_map", "Start the bookmark", "Start the intended bookmark and enter the map."),
    ("selection", "Select map objects", "Select provinces, states, countries, and strategic regions."),
    ("map_modes", "Inspect map modes", "Inspect terrain, political, supply, railway, air, and naval map modes."),
    ("land_movement", "Move a land unit", "Move a land unit across ordinary and special adjacencies."),
    ("naval_route", "Test naval route", "Test a port and naval route where applicable."),
    ("air_weather", "Check air and weather", "Select air regions and verify weather positions."),
    ("tick_30_days", "Tick 30 days", "Tick at least 30 in-game days."),
    ("save_reload", "Save and reload", "Create a save, reload it, and tick again."),
    ("rendering", "Inspect rendering", "Inspect representative tree, city, terrain, water, FOW, normal, border, and building rendering."),
)

SHORT_CHECKLIST_LINES: tuple[str, ...] = tuple(
    "%s: %s" % (check_id, title) for check_id, title, _detail in REQUIRED_CHECKS
)

REQUIRED_CHECK_IDS: tuple[str, ...] = tuple(check_id for check_id, _title, _detail in REQUIRED_CHECKS)

BOUNDARIES_TEXT = (
    "Assisted engine acceptance automates artifact records, launch configuration, "
    "fresh-log capture, log classification, save detection, and result recording. "
    "It does not perform GUI or mouse automation. Launching the game is opt-in "
    "and never happens during tests; dry-run mode is the default and records "
    "the planned command without executing it."
)

_ERROR_PATTERN_TEXTS = (
    r"\[error\]",
    r"\berror\b",
    r"failed",
    r"failure",
    r"\binvalid\b",
    r"\bmissing\b",
    r"not found",
    r"could not",
    r"couldn.t",
    r"exception",
    r"crash",
    r"fatal",
    r"undefined",
    r"duplicate",
    r"out of range",
    r"overflow",
    r"unable to",
)

_WARNING_PATTERN_TEXTS = (
    r"\[warn",
    r"\bwarning\b",
    r"\bwarn\b",
    r"deprecated",
    r"fallback",
)

_CATEGORY_PATTERN_TEXTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("country_tag", (
        r"invalid.*tag",
        r"unknown.*tag",
        r"duplicate.*tag",
        r"\btag\b",
        r"\bcountry\b",
        r"\boob\b",
        r"country_tags",
        r"history/countries",
        r"history/units",
    )),
    ("asset", (
        r"\.dds\b",
        r"\.tga\b",
        r"\.mesh\b",
        r"gfx/",
        r"sprite",
        r"texture",
        r"\bmesh\b",
        r"\bmodel\b",
        r"\bflag\b",
        r"colormap",
        r"world_normal",
        r"\bfow\b",
        r"shader",
        r"material",
    )),
    ("map", (
        r"province",
        r"definition\.csv",
        r"adjacen",
        r"strategic.?region",
        r"supply",
        r"railway",
        r"heightmap",
        r"terrain\.bmp",
        r"\brivers?\b",
        r"continent",
        r"state.*\bid\b",
        r"\bid\b.*state",
        r"weatherposition",
        r"ambient_object",
        r"buildings\.txt",
        r"positions\.txt",
        r"unitstacks",
        r"default\.map",
        r"seasons\.txt",
        r"\bmap\b",
    )),
    ("script", (
        r"history/",
        r"common/bookmarks",
        r"common/",
        r"bookmark",
        r"focus",
        r"\bevent\b",
        r"decision",
        r"script",
        r"unexpected token",
        r"localis",
        r"trigger",
        r"\beffect\b",
    )),
    ("audio_unrelated", (
        r"\bsound\b",
        r"\bmusic\b",
        r"\baudio\b",
        r"fmod",
        r"wwise",
        r"\.bank\b",
        r"\.ogg\b",
        r"\.wav\b",
        r"\.mp3\b",
    )),
)

_ERROR_PATTERNS = tuple(re.compile(text, re.IGNORECASE) for text in _ERROR_PATTERN_TEXTS)
_WARNING_PATTERNS = tuple(re.compile(text, re.IGNORECASE) for text in _WARNING_PATTERN_TEXTS)
_CATEGORY_RULES = tuple(
    (category, tuple(re.compile(text, re.IGNORECASE) for text in texts))
    for category, texts in _CATEGORY_PATTERN_TEXTS
)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string for observational metadata."""
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    """Serialize a value to stable canonical JSON for hashing and comparisons."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def deterministic_hash(value: Any) -> str:
    """Return the hex SHA-256 digest of the canonical JSON form of a value."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_identity_core(
    artifact_fingerprint: str = "",
    manifest_identity: str = "",
    lock_identity: str = "",
    target: str = "",
    profile: str = "",
    game_version: str = "",
    launch_identity: Mapping[str, Any] | None = None,
    expected_identity_hash: str = "",
) -> dict[str, Any]:
    """Build the timestamp-free identity core that identifies one acceptance run."""
    return {
        "schema": ENGINE_ACCEPTANCE_SCHEMA,
        "artifact_fingerprint": str(artifact_fingerprint or ""),
        "manifest_identity": str(manifest_identity or ""),
        "lock_identity": str(lock_identity or ""),
        "target": str(target or ""),
        "profile": str(profile or ""),
        "game_version": str(game_version or ""),
        "launch": dict(launch_identity or {}),
        "expected_identity_hash": str(expected_identity_hash or ""),
    }


def compute_identity_hash(identity_core: Mapping[str, Any]) -> str:
    """Return the full deterministic identity hash for an identity core mapping."""
    return deterministic_hash(dict(identity_core))


def compute_run_id(identity_core: Mapping[str, Any]) -> str:
    """Return the short deterministic run identifier for an identity core mapping."""
    return compute_identity_hash(identity_core)[:16]


def is_error_line(line: str) -> bool:
    """Return True when a log line carries a deterministic error marker."""
    text = str(line or "")
    if not text.strip():
        return False
    return any(pattern.search(text) is not None for pattern in _ERROR_PATTERNS)


def is_warning_line(line: str) -> bool:
    """Return True when a log line carries a deterministic warning marker."""
    text = str(line or "")
    if not text.strip():
        return False
    return any(pattern.search(text) is not None for pattern in _WARNING_PATTERNS)


def classify_error_line(line: str) -> str:
    """Classify one log line into a stable M7.3 category using fixed rule order."""
    text = str(line or "")
    for category, patterns in _CATEGORY_RULES:
        for pattern in patterns:
            if pattern.search(text) is not None:
                return category
    return "unknown"


def classify_line(line: str) -> tuple[str, str]:
    """Return the stable severity kind and category for one log line."""
    if is_error_line(line):
        return ("error", classify_error_line(line))
    if is_warning_line(line):
        return ("warning", classify_error_line(line))
    return ("info", "unknown")


def is_blocker_finding(category: str, severity: str) -> bool:
    """Return True when a finding blocks foundation acceptance."""
    return str(severity) == "error" and str(category) in BLOCKER_CATEGORIES


def missing_required_checks(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return the ordered list of required check ids that are not checked."""
    missing: list[str] = []
    for check_id, _title, _detail in REQUIRED_CHECKS:
        matched = False
        for entry in entries:
            try:
                candidate = str(entry.get("check_id", ""))
            except AttributeError:
                continue
            if candidate != check_id:
                continue
            matched = True
            try:
                checked = bool(entry.get("checked", False))
            except AttributeError:
                checked = False
            if not checked:
                missing.append(check_id)
            break
        if not matched:
            missing.append(check_id)
    return missing


def launch_failure_reason(launch, execute=False):
    if not execute:
        return ""
    if not isinstance(launch, Mapping):
        return "Assisted execution was requested but no game command was configured."
    try:
        mode = str(launch.get("mode", "") or "")
        status = str(launch.get("status", "") or "")
        executed = bool(launch.get("executed", False))
    except AttributeError:
        return "Assisted execution was requested but no game command was configured."
    if mode == "not_configured" or status == "missing_command":
        return "Assisted execution was requested but no game command was configured."
    if status == "timeout":
        error = str(launch.get("error", "") or "")
        if error:
            return "Game launch timed out: %s." % error
        return "Game launch timed out before the process exited."
    if status == "launch_failed":
        error = str(launch.get("error", "") or "")
        if error:
            return "Game launch failed to start: %s." % error
        return "Game launch failed to start."
    if status == "exited":
        try:
            raw_code = launch.get("returncode", None)
            code = int(raw_code) if raw_code is not None else 0
        except (TypeError, ValueError):
            return "Game launch reported an unreadable return code."
        if code != 0:
            return "Game launch exited with non-zero return code %d." % code
        return ""
    if not executed:
        if status:
            return "Assisted execution did not complete (launch status: %s)." % status
        return "Assisted execution was requested but the game command was not executed."
    if status:
        return "Assisted execution did not complete successfully (launch status: %s)." % status
    return ""


def decide_status(
    mode: str = "dry_run",
    artifact_ok: bool = False,
    artifact_mismatch: bool = False,
    blocker_errors: int = 0,
    unchecked_required: Sequence[str] | None = None,
    missing_saves: Sequence[str] | None = None,
    stale_saves: Sequence[str] | None = None,
    launch_ok: bool = True,
    launch_reason: str = "",
) -> tuple[str, list[str]]:
    """Decide the final acceptance status without inventing passing results.

    A dry run never reports a pass. Unchecked required checks always prevent
    an accepted or passing result. A failed assisted launch never passes.
    """
    unchecked = list(unchecked_required or [])
    missing = list(missing_saves or [])
    stale = list(stale_saves or [])
    try:
        blocker_count = int(blocker_errors or 0)
    except (TypeError, ValueError):
        blocker_count = 0
    if str(mode) == "dry_run":
        reasons = ["Dry-run mode records the plan without executing the game."]
        if not artifact_ok:
            reasons.append("Artifact directory is missing or unreadable.")
        if artifact_mismatch:
            reasons.append("Artifact identity does not match the expected identity.")
        if blocker_count > 0:
            reasons.append("%d blocker-class log error(s) already observed in fresh ranges." % blocker_count)
        if unchecked:
            reasons.append("Required checklist checks remain unchecked: %s." % ", ".join(unchecked))
        if missing:
            reasons.append("Expected save file(s) missing: %s." % ", ".join(missing))
        if stale:
            reasons.append("Expected save file(s) predate the snapshot: %s." % ", ".join(stale))
        return ("dry_run", reasons)
    if not artifact_ok:
        return ("blocked", ["Artifact directory is missing or unreadable; no acceptance claim is possible."])
    if artifact_mismatch:
        return ("blocked", ["Artifact identity does not match the expected identity."])
    if str(mode) != "dry_run" and launch_ok is False:
        reason = str(launch_reason or "").strip()
        if not reason:
            reason = "Assisted execution did not complete successfully."
        return ("failed", [reason])
    if blocker_count > 0:
        return ("failed", ["%d blocker-class log error(s) were found in fresh post-snapshot ranges." % blocker_count])
    if unchecked:
        return ("incomplete", ["Required checklist checks remain unchecked: %s." % ", ".join(unchecked)])
    if missing:
        return ("incomplete", ["Expected save file(s) missing: %s." % ", ".join(missing)])
    if stale:
        return ("incomplete", ["Expected save file(s) predate the snapshot: %s." % ", ".join(stale)])
    return ("passed", ["Fresh logs show no blocker errors, saves are fresh, and every required check is recorded."])


@dataclass(frozen=True)
class LaunchConfig:
    """Documented game-launcher command configuration without shell interpolation."""

    executable: str = ""
    args: tuple[str, ...] = ()
    cwd: str = ""
    env_names: tuple[str, ...] = ()
    timeout_seconds: float = 0.0

    def argv(self) -> list[str]:
        """Return the exact argument vector that would be executed without a shell."""
        return [str(self.executable)] + [str(item) for item in self.args]

    def executable_name(self) -> str:
        """Return the portable executable file name without directory parts."""
        return str(self.executable).replace("\\", "/").split("/")[-1]

    def identity(self) -> dict[str, Any]:
        """Return the timestamp-free launch identity used for run identification."""
        return {
            "executable_name": self.executable_name(),
            "args": [str(item) for item in self.args],
            "timeout_seconds": float(self.timeout_seconds or 0.0),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the launch configuration as JSON-safe plain data."""
        return {
            "executable": str(self.executable),
            "args": [str(item) for item in self.args],
            "cwd": str(self.cwd or ""),
            "env_names": [str(item) for item in self.env_names],
            "timeout_seconds": float(self.timeout_seconds or 0.0),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LaunchConfig":
        """Rebuild a launch configuration from plain data without executing anything."""
        source = dict(data) if isinstance(data, Mapping) else {}
        raw_args = source.get("args", ())
        if isinstance(raw_args, (str, bytes)):
            parsed_args: tuple[str, ...] = (str(raw_args),)
        else:
            try:
                parsed_args = tuple(str(item) for item in raw_args)
            except TypeError:
                parsed_args = ()
        raw_names = source.get("env_names", ())
        if isinstance(raw_names, (str, bytes)):
            parsed_names: tuple[str, ...] = (str(raw_names),)
        else:
            try:
                parsed_names = tuple(str(item) for item in raw_names)
            except TypeError:
                parsed_names = ()
        try:
            timeout = float(source.get("timeout_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            timeout = 0.0
        return cls(
            executable=str(source.get("executable", "") or ""),
            args=parsed_args,
            cwd=str(source.get("cwd", "") or ""),
            env_names=parsed_names,
            timeout_seconds=timeout,
        )


@dataclass(frozen=True)
class ChecklistEntry:
    """One stable named human check with its recorded answer."""

    check_id: str = ""
    title: str = ""
    detail: str = ""
    required: bool = True
    checked: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the checklist entry as JSON-safe plain data."""
        return {
            "check_id": str(self.check_id),
            "title": str(self.title),
            "detail": str(self.detail),
            "required": bool(self.required),
            "checked": bool(self.checked),
            "notes": str(self.notes or ""),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChecklistEntry":
        """Rebuild a checklist entry from plain data."""
        source = dict(data) if isinstance(data, Mapping) else {}
        return cls(
            check_id=str(source.get("check_id", "") or ""),
            title=str(source.get("title", "") or ""),
            detail=str(source.get("detail", "") or ""),
            required=bool(source.get("required", True)),
            checked=bool(source.get("checked", False)),
            notes=str(source.get("notes", "") or ""),
        )


@dataclass(frozen=True)
class LogFinding:
    """One classified fresh-log line with bounded evidence text."""

    source: str = ""
    line_number: int = 0
    category: str = "unknown"
    severity: str = "error"
    text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the finding as JSON-safe plain data."""
        category = str(self.category)
        if category not in LOG_CATEGORIES:
            category = "unknown"
        severity = str(self.severity)
        if severity not in FINDING_SEVERITIES:
            severity = "error"
        return {
            "source": str(self.source),
            "line_number": int(self.line_number),
            "category": category,
            "severity": severity,
            "text": str(self.text or ""),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogFinding":
        """Rebuild a log finding from plain data."""
        source = dict(data) if isinstance(data, Mapping) else {}
        try:
            line_number = int(source.get("line_number", 0) or 0)
        except (TypeError, ValueError):
            line_number = 0
        return cls(
            source=str(source.get("source", "") or ""),
            line_number=line_number,
            category=str(source.get("category", "unknown") or "unknown"),
            severity=str(source.get("severity", "error") or "error"),
            text=str(source.get("text", "") or ""),
        )


def assemble_result(
    run_id: str = "",
    identity_hash: str = "",
    identity_core: Mapping[str, Any] | None = None,
    created_at: str = "",
    mode: str = "dry_run",
    status: str = "dry_run",
    reasons: Sequence[str] | None = None,
    target: Mapping[str, Any] | None = None,
    artifact: Mapping[str, Any] | None = None,
    launch: Mapping[str, Any] | None = None,
    logs: Mapping[str, Any] | None = None,
    saves: Sequence[Mapping[str, Any]] | None = None,
    checklist: Sequence[Mapping[str, Any]] | None = None,
    checklist_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the deterministic engine_acceptance.json payload as plain data."""
    normalized_mode = str(mode) if str(mode) in RUN_MODES else "dry_run"
    normalized_status = str(status) if str(status) in RESULT_STATUSES else "dry_run"
    return {
        "schema": ENGINE_ACCEPTANCE_SCHEMA,
        "run_id": str(run_id),
        "identity_hash": str(identity_hash),
        "identity_core": dict(identity_core or {}),
        "created_at": str(created_at or ""),
        "mode": normalized_mode,
        "status": normalized_status,
        "reasons": [str(item) for item in (reasons or [])],
        "boundaries": BOUNDARIES_TEXT,
        "target": dict(target or {}),
        "artifact": dict(artifact or {}),
        "launch": dict(launch or {}),
        "logs": dict(logs or {}),
        "saves": [dict(item) for item in (saves or [])],
        "checklist": [dict(item) for item in (checklist or [])],
        "checklist_summary": dict(checklist_summary or {}),
    }


def result_to_json(result: Mapping[str, Any]) -> str:
    """Serialize an acceptance result deterministically with a trailing newline."""
    return json.dumps(dict(result), ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"


def result_from_json(text: str) -> dict[str, Any]:
    """Parse an acceptance result document back into plain data."""
    parsed = json.loads(str(text))
    if not isinstance(parsed, dict):
        raise ValueError("engine acceptance result must be a JSON object")
    return dict(parsed)


def describe_checklist_short() -> str:
    """Return the short human checklist text used in CLI output and help."""
    return "\n".join("- [ ] %s" % line for line in SHORT_CHECKLIST_LINES)
