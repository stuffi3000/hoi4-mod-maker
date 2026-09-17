"""Legacy validation adapters producing shared reports (M3.2a).

This module converts existing legacy validation outputs into the shared
ValidationReport contract without changing their producers. Readiness
check sequences, verifier error/warning string lists, and mixed
finding-like iterables all normalize into deterministic, immutable
reports that share finding codes and gate evaluation.

The adapters are dependency-free, quiet, non-mutating, and
deterministic: equal inputs in equal order always yield equal reports.
They never import Qt. CheckItem, ModVerifier, export, CLI, dialog, and
writer behavior is unchanged; client rewiring, validator suites,
manifests, and determinism enforcement arrive in later M3.2 to M3.5
slices.
"""
from __future__ import annotations

import re
from typing import Any

from domain.validation import ValidationFinding, ValidationReport

READINESS_SOURCE = "readiness"
READINESS_LAYER = "readiness"
READINESS_CODE_PREFIX = "readiness."
READINESS_AUTO_FIX_CODE = "readiness.auto_fix"

ARTIFACT_SOURCE = "artifact"
ARTIFACT_LAYER = "artifact"
ARTIFACT_ERROR_CODE = "artifact.error"
ARTIFACT_WARNING_CODE = "artifact.warning"

_CHECK_OK_STATUSES = frozenset({"ok", "pass", "passed", "success"})
_CHECK_WARNING_STATUSES = frozenset({"warning", "warn"})
_CHECK_ERROR_STATUSES = frozenset({"missing", "error", "blocker", "fail", "failed"})

_DRIVE_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|]*")
_UNC_PATH_RE = re.compile(r"\\\\[^\s\"'<>|]+")
_HOME_PATH_RE = re.compile(r"~[\\/][^\s\"'<>|]*")
_POSIX_ABSOLUTE_RE = re.compile(r"(?<![\w./\\:-])/[A-Za-z0-9._~+%-]+(?:/[A-Za-z0-9._~+%-]+)*")
_RELATIVE_FILE_RE = re.compile(r"[\w.\-]+(?:/[\w.\-]+)+\.\w+")
_BARE_FILE_RE = re.compile(r"[\w.\-]+\.(?:bmp|csv|txt|mod|yaml|yml|json|dds|tga|png)$", re.IGNORECASE)

__all__ = [
    "ARTIFACT_ERROR_CODE",
    "ARTIFACT_LAYER",
    "ARTIFACT_SOURCE",
    "ARTIFACT_WARNING_CODE",
    "READINESS_AUTO_FIX_CODE",
    "READINESS_CODE_PREFIX",
    "READINESS_LAYER",
    "READINESS_SOURCE",
    "check_item_code",
    "finding_from_check_item",
    "finding_from_verifier_message",
    "findings_from_check_items",
    "findings_from_verifier_messages",
    "report_from_check_items",
    "report_from_findings",
    "report_from_verifier_messages",
]


def _basename_of_path(value: str) -> str:
    """Return the final segment of a machine path without directories."""
    cleaned = str(value).strip().strip("\"'()[],;:.!?")
    parts = re.split(r"[\\/]+", cleaned)
    return parts[-1] if parts else cleaned


def _scrub_machine_paths(text: str) -> str:
    """Replace absolute machine paths with their portable file names."""
    cleaned = str(text)
    for pattern in (_DRIVE_PATH_RE, _UNC_PATH_RE, _HOME_PATH_RE, _POSIX_ABSOLUTE_RE):
        cleaned = pattern.sub(lambda match: _basename_of_path(match.group(0)), cleaned)
    return cleaned


def _is_portable_relative_path(value: str) -> bool:
    """Return True for repository-relative paths that are safe to serialize."""
    if not value:
        return False
    text = str(value).strip()
    if not text or "\x00" in text:
        return False
    if text.startswith("~") or "://" in text:
        return False
    if text.startswith("/") or text.startswith("\\"):
        return False
    if re.match(r"^[A-Za-z]:", text):
        return False
    normalized = text.replace("\\", "/")
    if normalized == ".." or normalized.startswith("../"):
        return False
    if "/../" in normalized or normalized.endswith("/.."):
        return False
    return True


def _extract_relative_path(text: str) -> str:
    """Extract the first portable relative file path from free-form text."""
    normalized = str(text).replace("\\", "/")
    for match in _RELATIVE_FILE_RE.finditer(normalized):
        candidate = match.group(0).strip().strip("\"'()[],;:.!?")
        if _is_portable_relative_path(candidate):
            return candidate
    for token in re.split(r"\s+", normalized):
        candidate = token.strip().strip("\"'()[],;:.!?")
        if _BARE_FILE_RE.match(candidate) and _is_portable_relative_path(candidate):
            return candidate
    return ""


def check_item_code(name: Any, explicit_code: Any = None) -> str:
    """Map a readiness check name to a stable report code.

    A client may provide an explicit stable code through a CheckItem-like
    object. The display-name fallback remains for legacy callers that do not
    have one yet.

    The code slugifies the check name deterministically, so identical
    input sequences always yield identical codes. Names that slugify to
    nothing share the stable readiness.check fallback.
    """
    if explicit_code is not None:
        explicit = str(explicit_code).strip().lower()
        explicit = re.sub(r"[^0-9a-z_.-]+", "_", explicit).strip("._-")
        if explicit:
            return explicit if explicit.startswith("readiness.") else READINESS_CODE_PREFIX + explicit
    slug = re.sub(r"[^0-9a-z]+", "_", str(name).lower() if name else "")
    slug = slug.strip("_")
    if not slug:
        slug = "check"
    return READINESS_CODE_PREFIX + slug


def _check_item_severity(status: Any) -> str:
    """Map a legacy check status to a shared finding severity.

    Passing checks become info so gated contexts stay green while the
    report retains full coverage. Missing-style statuses become errors;
    warnings and anything unrecognized stay visible as warnings.
    """
    normalized = str(status).strip().lower() if status else ""
    if normalized in _CHECK_OK_STATUSES:
        return "info"
    if normalized in _CHECK_WARNING_STATUSES:
        return "warning"
    if normalized in _CHECK_ERROR_STATUSES:
        return "error"
    return "warning"


def finding_from_check_item(item: Any) -> ValidationFinding:
    """Convert one CheckItem-like object to a shared finding.

    The object is read through its status, name, detail, count, and
    can_auto attributes without importing the readiness service, so
    translated display names and duck-typed fakes convert identically.
    """
    if item is None:
        raise ValueError("check item must not be None")
    name = str(getattr(item, "name", "") or "")
    status = str(getattr(item, "status", "") or "")
    detail = str(getattr(item, "detail", "") or "")
    count = getattr(item, "count", 0)
    try:
        count_text = str(int(count))
    except (TypeError, ValueError):
        count_text = str(count)
    message = detail.strip() or name.strip() or "Readiness check"
    evidence = "check=%s; status=%s; count=%s" % (
        name.strip() or check_item_code(name),
        status.strip() or "unknown",
        count_text,
    )
    repair_code = READINESS_AUTO_FIX_CODE if bool(getattr(item, "can_auto", False)) else ""
    explicit_code = getattr(item, "code", None) or getattr(item, "rule_code", None)
    return ValidationFinding(
        code=check_item_code(name, explicit_code),
        severity=_check_item_severity(status),
        message=message,
        layer=READINESS_LAYER,
        evidence=evidence,
        repair_code=repair_code,
    )


def findings_from_check_items(items: Any) -> list[ValidationFinding]:
    """Convert CheckItem-like objects to findings in input order."""
    if items is None:
        return []
    if isinstance(items, (str, bytes)):
        raise ValueError("check items must be an iterable of check-like objects")
    try:
        snapshot = list(items)
    except TypeError:
        snapshot = [items]
    return [finding_from_check_item(item) for item in snapshot]


def report_from_check_items(
    items: Any,
    *,
    source: str = READINESS_SOURCE,
    context: str = "draft_preview",
) -> ValidationReport:
    """Build a deterministic report from CheckItem-like objects."""
    return ValidationReport(
        findings=findings_from_check_items(items),
        source=source,
        context=context,
    )


def finding_from_verifier_message(message: Any, severity: str = "error") -> ValidationFinding:
    """Convert one verifier string to a shared artifact finding.

    Absolute machine paths shrink to portable file names before the
    finding is built, so serialized reports never carry absolute paths.
    Error strings share one stable code and warning strings share
    another; granular per-rule codes arrive with the M3.3 suites.
    """
    normalized_severity = str(severity).strip().lower() if severity else ""
    if normalized_severity == "error":
        code = ARTIFACT_ERROR_CODE
    elif normalized_severity == "warning":
        code = ARTIFACT_WARNING_CODE
    else:
        raise ValueError("verifier severity must be 'error' or 'warning', got %r" % (severity,))
    text = str(message).strip() if message is not None else ""
    if not text:
        raise ValueError("verifier message must be a non-empty string")
    scrubbed = _scrub_machine_paths(text)
    if not scrubbed.strip():
        scrubbed = text
    return ValidationFinding(
        code=code,
        severity=normalized_severity,
        message=scrubbed,
        layer=ARTIFACT_LAYER,
        path=_extract_relative_path(scrubbed),
    )


def _snapshot_messages(values: Any) -> list[Any]:
    """Copy message inputs into a list without mutating the caller value."""
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    try:
        return list(values)
    except TypeError:
        return [values]


def findings_from_verifier_messages(
    errors: Any = (),
    warnings: Any = (),
) -> list[ValidationFinding]:
    """Convert verifier string lists to findings with errors first."""
    collected: list[ValidationFinding] = []
    for message in _snapshot_messages(errors):
        collected.append(finding_from_verifier_message(message, "error"))
    for message in _snapshot_messages(warnings):
        collected.append(finding_from_verifier_message(message, "warning"))
    return collected


def report_from_verifier_messages(
    errors: Any = (),
    warnings: Any = (),
    *,
    source: str = ARTIFACT_SOURCE,
    context: str = "draft_preview",
) -> ValidationReport:
    """Build a deterministic report from verifier error/warning strings."""
    return ValidationReport(
        findings=findings_from_verifier_messages(errors, warnings),
        source=source,
        context=context,
    )


def report_from_findings(
    findings: Any = (),
    *,
    source: str = "",
    context: str = "draft_preview",
) -> ValidationReport:
    """Build a report from finding-like values in input order.

    Accepts ValidationFinding instances, legacy ValidationNote values, and
    plain mappings. Normalization is delegated to ValidationReport so
    there is exactly one coercion path.
    """
    if findings is None:
        normalized: Any = ()
    elif isinstance(findings, (str, bytes)):
        raise ValueError("findings must be an iterable of finding-like values")
    else:
        normalized = findings
    return ValidationReport(findings=normalized, source=source, context=context)
