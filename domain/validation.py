"""Shared validation findings, registry, and gate policy (M3.1).

This module defines the typed contract used by every map-foundation
validator, a small deterministic validator registry, and explicit
gate-policy evaluation for the five release contexts.

The API is intentionally small and dependency-free so project checks,
pre-write export gates, artifact validation, UI panels, and CLI reports
can share rule definitions and finding codes without duplicating logic.
"""
from __future__ import annotations

import ntpath
import posixpath
import re
from collections.abc import Callable, Container, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Union


FINDING_SEVERITIES: tuple[str, ...] = ("info", "warning", "error", "blocker")

SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "error": 2,
    "blocker": 3,
}

GATE_CONTEXTS: tuple[str, ...] = (
    "draft_preview",
    "foundation_candidate",
    "freeze",
    "acceptance",
    "accepted_lock",
)

GateContext = str

ValidatorFunc = Callable[..., Iterable["ValidationFinding"]]

AcceptedInput = Union[str, Mapping[str, Any], Iterable[Any], None]

_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")


def _is_relative_finding_path(value: str) -> bool:
    """Return True when a finding file path is safe to store in manifests.

    Only repository-relative or mod-relative paths are accepted. Absolute,
    drive-anchored, home-anchored, UNC, URI, or parent-escaping paths are
    treated as machine-specific and rejected.
    """
    if not value:
        return True
    text = str(value)
    if "\x00" in text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("~"):
        return False
    if "://" in stripped:
        return False
    if posixpath.isabs(stripped.replace("\\", "/")):
        return False
    if ntpath.isabs(stripped):
        return False
    if _DRIVE_PATTERN.match(stripped):
        return False
    if stripped.startswith("\\\\"):
        return False
    normalized = posixpath.normpath(stripped.replace("\\", "/"))
    if normalized == ".." or normalized.startswith("../"):
        return False
    return True


def _normalize_affected_ids(values: Any) -> tuple:
    """Normalize affected IDs to a tuple without mutating the input."""
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        return (values,)
    try:
        items = tuple(values)
    except TypeError:
        return (values,)
    return items


def _normalize_coordinates(values: Any) -> tuple[tuple[int, int], ...]:
    """Normalize coordinates to a tuple of integer pairs."""
    if values is None:
        return ()
    items = list(values)
    normalized: list[tuple[int, int]] = []
    for item in items:
        pair = tuple(item)
        if len(pair) != 2:
            raise ValueError("coordinates must be (x, y) pairs")
        normalized.append((int(pair[0]), int(pair[1])))
    return tuple(normalized)


@dataclass(frozen=True)
class ValidationFinding:
    """One typed static-check result with a stable code.

    A finding carries severity, layer, an optional repository-relative file,
    affected IDs and coordinates, a concise message plus evidence, optional
    repair or UI-action metadata, and optional accepted-exception metadata.
    Absolute or otherwise machine-specific paths are rejected so manifests
    stay portable across machines.
    """

    code: str
    severity: str
    message: str
    layer: str = ""
    path: str = ""
    affected_ids: tuple = field(default_factory=tuple)
    coordinates: tuple[tuple[int, int], ...] = field(default_factory=tuple)
    evidence: str = ""
    repair_code: str = ""
    action: str = ""
    waivable: bool = False
    exception_id: str = ""
    exception_reason: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""

    def __post_init__(self) -> None:
        code_text = str(self.code).strip() if self.code is not None else ""
        if not code_text:
            raise ValueError("finding code must be a non-empty string")
        if self.severity not in SEVERITY_RANK:
            raise ValueError(
                "unknown severity %r; expected one of %s"
                % (self.severity, ", ".join(FINDING_SEVERITIES))
            )
        message_text = str(self.message).strip() if self.message is not None else ""
        if not message_text:
            raise ValueError("finding message must be a non-empty string")
        path_text = str(self.path) if self.path else ""
        if path_text and not _is_relative_finding_path(path_text):
            raise ValueError(
                "finding path must be repository-relative, got %r" % (self.path,)
            )
        object.__setattr__(self, "code", code_text)
        object.__setattr__(self, "message", message_text)
        object.__setattr__(self, "layer", str(self.layer) if self.layer else "")
        object.__setattr__(self, "path", path_text)
        object.__setattr__(self, "affected_ids", _normalize_affected_ids(self.affected_ids))
        object.__setattr__(self, "coordinates", _normalize_coordinates(self.coordinates))
        object.__setattr__(self, "evidence", str(self.evidence) if self.evidence else "")
        object.__setattr__(self, "repair_code", str(self.repair_code) if self.repair_code else "")
        object.__setattr__(self, "action", str(self.action) if self.action else "")
        object.__setattr__(self, "waivable", bool(self.waivable))
        object.__setattr__(self, "exception_id", str(self.exception_id) if self.exception_id else "")
        object.__setattr__(self, "exception_reason", str(self.exception_reason) if self.exception_reason else "")
        object.__setattr__(self, "reviewed_by", str(self.reviewed_by) if self.reviewed_by else "")
        object.__setattr__(self, "reviewed_at", str(self.reviewed_at) if self.reviewed_at else "")

    @property
    def has_repair(self) -> bool:
        """Return True when the finding names a repair that may resolve it."""
        return bool(self.repair_code)

    @property
    def is_accepted(self) -> bool:
        """Return True when the finding carries accepted-exception metadata."""
        return bool(self.exception_id)

    def with_acceptance(
        self,
        exception_id: str,
        reason: str = "",
        reviewed_by: str = "",
        reviewed_at: str = "",
    ) -> ValidationFinding:
        """Return a copy carrying accepted-exception metadata.

        The original finding is unchanged. A non-empty exception identifier
        is required; reason and reviewer fields document the waiver.
        """
        waiver = str(exception_id).strip() if exception_id is not None else ""
        if not waiver:
            raise ValueError("accepted exception id must be a non-empty string")
        return replace(
            self,
            exception_id=waiver,
            exception_reason=str(reason) if reason else "",
            reviewed_by=str(reviewed_by) if reviewed_by else "",
            reviewed_at=str(reviewed_at) if reviewed_at else "",
        )

    @property
    def file(self) -> str:
        """Repository-relative file alias for path compatibility."""
        return self.path

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible mapping without absolute paths."""
        return {
            "code": self.code,
            "severity": self.severity,
            "layer": self.layer,
            "path": self.path,
            "file": self.path,
            "affected_ids": list(self.affected_ids),
            "coordinates": [list(pair) for pair in self.coordinates],
            "message": self.message,
            "evidence": self.evidence,
            "repair_code": self.repair_code,
            "action": self.action,
            "waivable": bool(self.waivable),
            "exception_id": self.exception_id,
            "exception_reason": self.exception_reason,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ValidationFinding:
        """Build a finding from a plain mapping produced by to_dict."""
        if not isinstance(data, Mapping):
            raise ValueError("finding payload must be a mapping")
        try:
            code_value = data["code"]
            severity_value = data["severity"]
            message_value = data["message"]
        except KeyError as missing:
            raise ValueError("finding payload is missing %s" % (missing,)) from missing
        return cls(
            code=str(code_value),
            severity=str(severity_value),
            message=str(message_value),
            layer=str(data.get("layer", "") or ""),
            path=str(data.get("path", data.get("file", "")) or ""),
            affected_ids=tuple(data.get("affected_ids", ()) or ()),
            coordinates=tuple(
                tuple(pair) for pair in (data.get("coordinates", ()) or ())
            ),
            evidence=str(data.get("evidence", "") or ""),
            repair_code=str(data.get("repair_code", "") or ""),
            action=str(data.get("action", "") or ""),
            waivable=bool(data.get("waivable", False)),
            exception_id=str(data.get("exception_id", "") or ""),
            exception_reason=str(data.get("exception_reason", "") or ""),
            reviewed_by=str(data.get("reviewed_by", "") or ""),
            reviewed_at=str(data.get("reviewed_at", "") or ""),
        )

    def to_validation_note(self) -> Any:
        """Convert to the legacy ValidationNote contract for compatibility."""
        from domain.export_contract import ValidationNote

        return ValidationNote(
            code=self.code,
            severity=self.severity,
            message=self.message,
            layer=self.layer,
        )

    @classmethod
    def from_validation_note(cls, note: Any) -> ValidationFinding:
        """Build a finding from a legacy ValidationNote without extra metadata."""
        code_value = getattr(note, "code", "")
        severity_value = getattr(note, "severity", "")
        message_value = getattr(note, "message", "")
        layer_value = getattr(note, "layer", "") or ""
        return cls(
            code=str(code_value),
            severity=str(severity_value),
            message=str(message_value),
            layer=str(layer_value),
        )


def coerce_finding(value: Any) -> ValidationFinding:
    """Coerce a finding-like value to ValidationFinding without mutation.

    ValidationFinding instances pass through unchanged. Legacy
    ValidationNote instances convert with default metadata. Plain mappings
    parse through from_dict. Anything else raises ValueError.
    """
    if isinstance(value, ValidationFinding):
        return value
    if isinstance(value, Mapping):
        return ValidationFinding.from_dict(value)
    code_value = getattr(value, "code", None)
    severity_value = getattr(value, "severity", None)
    message_value = getattr(value, "message", None)
    if isinstance(code_value, str) and isinstance(severity_value, str) and isinstance(
        message_value, str
    ):
        return ValidationFinding.from_validation_note(value)
    raise ValueError("cannot coerce %r to ValidationFinding" % (type(value).__name__,))


class ValidatorRegistry:
    """Named validator collection with deterministic execution order.

    Validators are pure callables that accept caller-supplied inputs and
    return an iterable of findings. The registry never prints and never
    mutates caller inputs; it aggregates findings in sorted validator-name
    order so repeated runs with the same registrations produce the same
    sequence regardless of registration order.
    """

    def __init__(self) -> None:
        self._validators: dict[str, ValidatorFunc] = {}

    def register(
        self,
        name: str,
        func: ValidatorFunc | None = None,
        *,
        overwrite: bool = False,
    ) -> Any:
        """Register a validator under a stable name.

        May be used directly or as a decorator. Names must be unique unless
        overwrite is True. Returns the registered function so decorator use
        preserves the original callable.
        """
        label = str(name).strip() if name is not None else ""
        if not label:
            raise ValueError("validator name must be a non-empty string")

        def _store(target: ValidatorFunc) -> ValidatorFunc:
            if not callable(target):
                raise ValueError("validator %r must be callable" % (label,))
            if label in self._validators and not overwrite:
                raise ValueError("validator %r is already registered" % (label,))
            self._validators[label] = target
            return target

        if func is None:
            return _store
        return _store(func)

    def unregister(self, name: str) -> bool:
        """Remove a validator by name, returning True when it existed."""
        return self._validators.pop(str(name), None) is not None

    def __contains__(self, name: object) -> bool:
        return str(name) in self._validators

    def __len__(self) -> int:
        return len(self._validators)

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered validator names in deterministic sorted order."""
        return tuple(sorted(self._validators))

    def run(self, *args: Any, **kwargs: Any) -> list[ValidationFinding]:
        """Run every validator with the same arguments and aggregate findings.

        Validators execute in sorted name order. A validator may return None,
        one finding, or any iterable of findings or finding-like mappings.
        This method performs no printing and does not mutate its inputs.
        """
        aggregated: list[ValidationFinding] = []
        for label in sorted(self._validators):
            validator = self._validators[label]
            produced = validator(*args, **kwargs)
            if produced is None:
                continue
            if isinstance(produced, (ValidationFinding, Mapping)):
                aggregated.append(coerce_finding(produced))
                continue
            if hasattr(produced, "code") and hasattr(produced, "severity"):
                aggregated.append(coerce_finding(produced))
                continue
            for item in produced:
                aggregated.append(coerce_finding(item))
        return aggregated


def _normalize_accepted_keys(accepted: AcceptedInput) -> frozenset[str]:
    """Normalize accepted-exception input to a set of string keys.

    Accepts None, a single string, a mapping with validation_exceptions or
    exception identifiers, or an iterable mixing strings and mappings. This
    accepts ProjectMeta.validation_exceptions entries shaped like
    code, id, or exception_id keys without requiring callers to pre-filter.
    """
    if accepted is None:
        return frozenset()
    if isinstance(accepted, str):
        text = accepted.strip()
        return frozenset((text,)) if text else frozenset()
    if isinstance(accepted, Mapping):
        exceptions_value = accepted.get("validation_exceptions", None)
        if isinstance(exceptions_value, (list, tuple, set, frozenset)):
            return _normalize_accepted_keys(exceptions_value)
        for key_name in ("exception_id", "id", "code"):
            candidate = accepted.get(key_name, None)
            if isinstance(candidate, str) and candidate.strip():
                return frozenset((candidate.strip(),))
        return frozenset()
    try:
        iterator = iter(accepted)
    except TypeError:
        return frozenset()
    keys: set[str] = set()
    for entry in iterator:
        if isinstance(entry, str):
            stripped = entry.strip()
            if stripped:
                keys.add(stripped)
        elif isinstance(entry, Mapping):
            for key_name in ("exception_id", "id", "code"):
                candidate = entry.get(key_name, None)
                if isinstance(candidate, str) and candidate.strip():
                    keys.add(candidate.strip())
                    break
    return frozenset(keys)


def _is_waived(
    finding: ValidationFinding,
    accepted_keys: Container[str],
    context: str,
) -> bool:
    """Return True when recorded acceptance excuses a finding in a context.

    Candidate and acceptance contexts never waive errors or blockers: their
    policy is to block those findings and keep warnings visible. Freeze and
    accepted-lock contexts require full waiver metadata with a reason and
    reviewer timestamp. Freeze requires the finding to be explicitly marked
    waivable; accepted-lock excuses only waivable warnings.
    """
    if not accepted_keys:
        return False
    id_match = bool(finding.exception_id) and finding.exception_id in accepted_keys
    code_match = finding.code in accepted_keys
    if context == "draft_preview":
        return bool(id_match or code_match)
    if context in ("foundation_candidate", "acceptance"):
        return False
    if context == "freeze":
        if not finding.waivable:
            return False
        if not finding.exception_reason or not finding.reviewed_at:
            return False
        if id_match:
            return True
        return bool(code_match and finding.exception_id)
    if context == "accepted_lock":
        if finding.severity != "warning" or not finding.waivable:
            return False
        if not finding.exception_reason or not finding.reviewed_at:
            return False
        if id_match:
            return True
        return bool(code_match and finding.exception_id)
    raise ValueError("unknown gate context %r" % (context,))


@dataclass(frozen=True)
class GateDecision:
    """Outcome of gate-policy evaluation for one validation report.

    blocking holds unexcused findings that prevent publication or progress.
    visible_warnings holds unexcused warnings that must stay visible without
    blocking the current context. waived holds findings excused by recorded
    acceptance metadata so auditors can still review intentional exceptions.
    The three collections are disjoint; info findings never block.
    """

    context: str
    allowed: bool
    blocking: tuple[ValidationFinding, ...] = ()
    visible_warnings: tuple[ValidationFinding, ...] = ()
    waived: tuple[ValidationFinding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible summary without machine-specific paths."""
        return {
            "context": self.context,
            "allowed": bool(self.allowed),
            "blocking": [finding.to_dict() for finding in self.blocking],
            "visible_warnings": [finding.to_dict() for finding in self.visible_warnings],
            "waived": [finding.to_dict() for finding in self.waived],
        }


def evaluate_gate(
    findings: Iterable[Any] | None,
    context: GateContext,
    *,
    accepted: AcceptedInput = (),
) -> GateDecision:
    """Evaluate findings against an explicit gate context.

    draft_preview reports everything without blocking staging.
    foundation_candidate and acceptance block on unexcused errors and
    blockers while keeping warnings visible. freeze blocks on unexcused
    errors, blockers, and warnings, permitting only explicitly waivable
    findings with recorded reasoned acceptance. accepted_lock permits no
    errors or blockers and only recorded warning exceptions.
    """
    if context not in GATE_CONTEXTS:
        raise ValueError(
            "unknown gate context %r; expected one of %s" % (context, ", ".join(GATE_CONTEXTS))
        )
    accepted_keys = _normalize_accepted_keys(accepted)
    normalized: list[ValidationFinding] = []
    if findings:
        for item in findings:
            normalized.append(coerce_finding(item))
    waived: list[ValidationFinding] = []
    pending: list[ValidationFinding] = []
    for finding in normalized:
        if _is_waived(finding, accepted_keys, str(context)):
            waived.append(finding)
        else:
            pending.append(finding)
    blocking: list[ValidationFinding] = []
    visible: list[ValidationFinding] = []
    if context == "draft_preview":
        visible.extend(item for item in pending if item.severity == "warning")
    elif context in ("foundation_candidate", "acceptance"):
        for item in pending:
            if item.severity in ("error", "blocker"):
                blocking.append(item)
            elif item.severity == "warning":
                visible.append(item)
    elif context == "freeze":
        for item in pending:
            if item.severity in ("error", "blocker", "warning"):
                blocking.append(item)
    elif context == "accepted_lock":
        for item in pending:
            if item.severity in ("error", "blocker"):
                blocking.append(item)
            elif item.severity == "warning":
                blocking.append(item)
    else:
        raise ValueError("unknown gate context %r" % (context,))
    return GateDecision(
        context=str(context),
        allowed=not blocking,
        blocking=tuple(blocking),
        visible_warnings=tuple(visible),
        waived=tuple(waived),
    )
