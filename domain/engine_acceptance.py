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

LOG_CATEGORIES = (
    "map",
    "asset",
    "script",
    "country_tag",
    "audio_unrelated",
    "dlc_unrelated",
    "environment_unrelated",
    "unknown",
)

BLOCKER_CATEGORIES = ("map", "asset", "script", "country_tag", "unknown")

FINDING_SEVERITIES = ("error", "warning")

REQUIRED_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("main_menu", "Reach the main menu", "Reach the main menu without map initialization failure."),
    ("bookmark_map", "Start the bookmark", "Start the intended bookmark and enter the map."),
    ("selection", "Select map objects", "Select provinces, states, countries, and strategic regions."),
    ("map_modes", "Inspect map modes", "Inspect terrain, political, supply, railway, air, and naval map modes."),
    ("land_movement", "Move a land unit", "Move a land unit across ordinary and special adjacencies."),
    (
        "naval_route",
        "Test naval route",
        "Create a convoy-backed naval-invasion route with the generated land division.",
    ),
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
    # Blocker-bearing categories must win over unrelated-noise signatures when
    # a line contains evidence for both (for example, a map error mentioning
    # a sound asset).
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
        r"(?<!sound )\beffect\b",
    )),
    ("audio_unrelated", (
        r"\bsound\s+effect\b",
        r"\bsoundeffect\b",
        r"\bpdx_audio(?:_|\b)",
        r"\bassetfactory_audio\b",
        r"(?:^|[\\/])audio(?:[\\/]|$)",
        r"fmod",
        r"wwise",
        r"\.bank\b",
        r"\.ogg\b",
        r"\.wav\b",
        r"\.mp3\b",
    )),
    ("dlc_unrelated", (
        r"\b(?:missing|unavailable|not installed|not owned|not available)\s+(?:the\s+)?DLC\b",
        r"\bDLC\b.{0,80}\b(?:missing|unavailable|not installed|not owned|not available)\b",
        r"\bdownloadable content\b",
        r"\bexpansion\b.{0,80}\b(?:not installed|not owned|unavailable|missing)\b",
    )),
    ("environment_unrelated", (
        r"\boperating system\b",
        r"\b(?:graphics?|video)\s+driver\b",
        r"\b(?:graphics?|video)\s+card\b",
        r"\bGPU\b",
        r"\b(?:DirectX|OpenGL|Vulkan)\b",
        r"\bSteam API\b",
        r"\bParadox Launcher\b",
        r"\bsystem locale\b",
        r"\bdisplay resolution\b",
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
    foundation_source_identity: str = "",
    checklist_entries: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the timestamp-free identity core for run and checklist attestations."""
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
        "foundation_source_identity": str(foundation_source_identity or ""),
        "checklist_attestation": canonical_checklist_attestation(checklist_entries or ()),
    }


def compute_identity_hash(identity_core: Mapping[str, Any]) -> str:
    """Return the full deterministic identity hash for an identity core mapping."""
    return deterministic_hash(dict(identity_core))


def compute_run_id(identity_core: Mapping[str, Any]) -> str:
    """Return the short deterministic run identifier for an identity core mapping."""
    return compute_identity_hash(identity_core)[:16]


def canonical_checklist_attestation(
    entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return checklist answers in required order for stable run identity."""
    by_id: dict[str, Mapping[str, Any]] = {}
    for entry in entries or ():
        if isinstance(entry, Mapping):
            check_id = str(entry.get("check_id", "") or "")
            if check_id:
                by_id[check_id] = entry
    return [
        {
            "check_id": check_id,
            "checked": bool(by_id.get(check_id, {}).get("checked", False)),
            "waived": bool(by_id.get(check_id, {}).get("waived", False)),
            "waiver_reason": str(by_id.get(check_id, {}).get("waiver_reason", "") or "").strip(),
            "notes": str(by_id.get(check_id, {}).get("notes", "") or ""),
        }
        for check_id in REQUIRED_CHECK_IDS
    ]


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


def _is_error_log_source(source: str) -> bool:
    """Return whether a log source is named error.log on either path convention."""
    normalized = str(source or "").replace("\\", "/").rstrip("/").casefold()
    return normalized.rsplit("/", 1)[-1] == "error.log"


def classify_line(line: str, source: str = "") -> tuple[str, str]:
    """Classify one log line, treating every nonblank error.log line as error evidence."""
    if is_error_line(line):
        return ("error", classify_error_line(line))
    if _is_error_log_source(source) and str(line or "").strip():
        return ("error", classify_error_line(line))
    if is_warning_line(line):
        return ("warning", classify_error_line(line))
    return ("info", "unknown")


def is_blocker_finding(category: str, severity: str) -> bool:
    """Return True when a finding blocks foundation acceptance."""
    return str(severity) == "error" and str(category) in BLOCKER_CATEGORIES


def missing_required_checks(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return the ordered required check ids that are neither checked nor waived."""
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
                waived = bool(entry.get("waived", False))
            except AttributeError:
                checked = False
                waived = False
            if not checked and not waived:
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


def required_error_log_failure_reason(evidence, execute=False):
    """Return a failure reason when an assisted run lacks fresh ``error.log`` evidence."""
    if not execute:
        return ""
    if not isinstance(evidence, Mapping):
        return "Required error.log evidence was not recorded."
    if not bool(evidence.get("required", True)):
        return ""
    status = str(evidence.get("status", "") or "")
    if status == "generated":
        return ""
    messages = {
        "not_configured": "Required error.log was not configured; provide a log path named error.log.",
        "missing": "Required error.log is missing after the assisted run.",
        "unreadable": "Required error.log is unreadable after the assisted run.",
        "stale": "Required error.log was not generated or modified after the pre-run snapshot.",
    }
    if status in messages:
        return messages[status]
    return "Required error.log could not be verified after the assisted run (status: %s)." % (status or "unknown")


def _save_evidence_reasons(
    save_evidence: Sequence[Mapping[str, Any]] | None,
    missing_saves: Sequence[str] | None,
    stale_saves: Sequence[str] | None,
) -> list[str]:
    """Describe every expected save whose evidence is not fresh."""
    by_status: dict[str, list[str]] = {}

    def add(status: str, name: str) -> None:
        bucket = by_status.setdefault(status, [])
        if name not in bucket:
            bucket.append(name)

    for name in missing_saves or ():
        add("missing", str(name))
    for name in stale_saves or ():
        add("stale", str(name))
    for record in save_evidence or ():
        if not isinstance(record, Mapping):
            continue
        status = str(record.get("status", "unknown") or "unknown")
        if status != "fresh":
            add(status, str(record.get("name", "unnamed save") or "unnamed save"))

    messages = {
        "missing": "Expected save file(s) missing: %s.",
        "stale": "Expected save file(s) predate the snapshot: %s.",
        "unreadable": "Expected save file(s) are unreadable: %s.",
        "not_configured": "Expected save file(s) were not checked because the save directory is not configured: %s.",
    }
    reasons: list[str] = []
    for status in ("missing", "stale", "unreadable", "not_configured"):
        names = by_status.pop(status, [])
        if names:
            reasons.append(messages[status] % ", ".join(names))
    for status in sorted(by_status):
        reasons.append(
            "Expected save file(s) do not have fresh evidence (status %s): %s."
            % (status, ", ".join(by_status[status]))
        )
    return reasons


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
    required_log_failure: str = "",
    required_active_mod_failure: str = "",
    save_evidence: Sequence[Mapping[str, Any]] | None = None,
    waived_required: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[str, list[str]]:
    """Decide the final acceptance status without inventing passing results.

    A dry run never reports a pass. Unchecked required checks always prevent
    an accepted or passing result. A failed assisted launch never passes.
    """
    unchecked = list(unchecked_required or [])
    waiver_reasons = []
    for entry in waived_required or ():
        if not isinstance(entry, Mapping):
            continue
        check_id = str(entry.get("check_id", "") or "").strip()
        reason = str(entry.get("reason", entry.get("waiver_reason", "")) or "").strip()
        if check_id and reason:
            waiver_reasons.append(
                "Required checklist check %s was explicitly waived: %s." % (check_id, reason)
            )
    save_reasons = _save_evidence_reasons(save_evidence, missing_saves, stale_saves)
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
        reasons.extend(waiver_reasons)
        reasons.extend(save_reasons)
        return ("dry_run", reasons)
    if not artifact_ok:
        return ("blocked", ["Artifact directory is missing or unreadable; no acceptance claim is possible."])
    if artifact_mismatch:
        return ("blocked", ["Artifact identity does not match the expected identity."])
    failure_reasons: list[str] = []
    if str(mode) != "dry_run" and launch_ok is False:
        reason = str(launch_reason or "").strip()
        if not reason:
            reason = "Assisted execution did not complete successfully."
        failure_reasons.append(reason)
    required_log_reason = str(required_log_failure or "").strip()
    if str(mode) != "dry_run" and required_log_reason:
        failure_reasons.append(required_log_reason)
    required_active_mod_reason = str(required_active_mod_failure or "").strip()
    if str(mode) != "dry_run" and required_active_mod_reason:
        failure_reasons.append(required_active_mod_reason)
    if blocker_count > 0:
        failure_reasons.append(
            "%d blocker-class log error(s) were found in fresh post-snapshot ranges."
            % blocker_count
        )
    incomplete_reasons: list[str] = []
    if unchecked:
        incomplete_reasons.append(
            "Required checklist checks remain unchecked: %s." % ", ".join(unchecked)
        )
    incomplete_reasons.extend(save_reasons)
    if failure_reasons:
        return ("failed", failure_reasons + incomplete_reasons + waiver_reasons)
    if incomplete_reasons:
        return ("incomplete", incomplete_reasons + waiver_reasons)
    return (
        "passed",
        [
            "Fresh logs show no blocker errors, saves are fresh, and every required check is checked or explicitly waived."
        ] + waiver_reasons,
    )


@dataclass(frozen=True)
class LaunchConfig:
    """Documented game-launcher command configuration without shell interpolation."""

    executable: str = ""
    args: tuple[str, ...] = ()
    cwd: str = ""
    env_names: tuple[str, ...] = ()
    timeout_seconds: float = 0.0
    wait_for_process: str = ""
    startup_timeout_seconds: float = 30.0
    launcher_process: str = ""

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
            "wait_for_process": str(self.wait_for_process or ""),
            "startup_timeout_seconds": float(self.startup_timeout_seconds or 0.0),
            "launcher_process": str(self.launcher_process or ""),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the launch configuration as JSON-safe plain data."""
        return {
            "executable": str(self.executable),
            "args": [str(item) for item in self.args],
            "cwd": str(self.cwd or ""),
            "env_names": [str(item) for item in self.env_names],
            "timeout_seconds": float(self.timeout_seconds or 0.0),
            "wait_for_process": str(self.wait_for_process or ""),
            "startup_timeout_seconds": float(self.startup_timeout_seconds or 0.0),
            "launcher_process": str(self.launcher_process or ""),
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
        try:
            startup_timeout = float(source.get("startup_timeout_seconds", 30.0) or 0.0)
        except (TypeError, ValueError):
            startup_timeout = 30.0
        return cls(
            executable=str(source.get("executable", "") or ""),
            args=parsed_args,
            cwd=str(source.get("cwd", "") or ""),
            env_names=parsed_names,
            timeout_seconds=timeout,
            wait_for_process=str(source.get("wait_for_process", "") or ""),
            startup_timeout_seconds=startup_timeout,
            launcher_process=str(source.get("launcher_process", "") or ""),
        )


@dataclass(frozen=True)
class ChecklistEntry:
    """One stable named human check with its recorded answer."""

    check_id: str = ""
    title: str = ""
    detail: str = ""
    required: bool = True
    checked: bool = False
    waived: bool = False
    waiver_reason: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the checklist entry as JSON-safe plain data."""
        return {
            "check_id": str(self.check_id),
            "title": str(self.title),
            "detail": str(self.detail),
            "required": bool(self.required),
            "checked": bool(self.checked),
            "waived": bool(self.waived),
            "waiver_reason": str(self.waiver_reason or ""),
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
            waived=bool(source.get("waived", False)),
            waiver_reason=str(source.get("waiver_reason", "") or ""),
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
