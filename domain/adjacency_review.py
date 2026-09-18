"""Deterministic adjacency-layer review state and freeze policy (M4.1).

The project metadata records whether special adjacencies were reviewed. This
module owns the portable representation used by metadata, planners, and
validators so an empty layer cannot silently look like an intentional review.
It deliberately accepts manager-like objects instead of importing Qt or the
project aggregate.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from domain.validation import ValidationFinding


REVIEW_STATES = ("unreviewed", "none_intended", "defined")
LEGACY_REVIEW_STATES = {"reviewed": "defined"}


def normalize_review_state(value: Any) -> str:
    """Return an explicit review state, migrating the pre-M4 ``reviewed`` value."""
    text = str(value or "unreviewed").strip().lower()
    text = LEGACY_REVIEW_STATES.get(text, text)
    return text if text in REVIEW_STATES else "unreviewed"


def _read(entry: Any, name: str, default: Any = None) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(name, default)
    return getattr(entry, name, default)


def _canonical(value: Any) -> Any:
    """Convert manager data to JSON-safe deterministic values without mutation."""
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item) for item in value), key=lambda item: repr(item))
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _entries(manager: Any) -> list[Any]:
    if manager is None:
        return []
    getter = getattr(manager, "get_all", None)
    if not callable(getter):
        return []
    try:
        return list(getter() or [])
    except Exception:
        return []


def _entry_payload(entry: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _canonical(_read(entry, field, None)) for field in fields}


def canonical_adjacency_layer(
    adjacency_mgr: Any = None,
    adjacency_rule_mgr: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return sorted, portable adjacency and rule data for hashing/review."""
    adjacency_fields = (
        "from_id", "to_id", "type", "through_id", "start_x", "start_y",
        "stop_x", "stop_y", "rule_name", "comment",
    )
    rule_fields = (
        "name", "contested", "enemy", "friend", "neutral",
        "required_provinces", "icon_province",
    )
    adjacencies = [_entry_payload(entry, adjacency_fields) for entry in _entries(adjacency_mgr)]
    rules = [_entry_payload(entry, rule_fields) for entry in _entries(adjacency_rule_mgr)]
    adjacencies.sort(key=lambda item: tuple(repr(item[field]) for field in adjacency_fields))
    rules.sort(key=lambda item: tuple(repr(item[field]) for field in rule_fields))
    return {"adjacencies": adjacencies, "rules": rules}


def adjacency_layer_hash(adjacency_mgr: Any = None, adjacency_rule_mgr: Any = None) -> str:
    """Hash only stable adjacency/rule content, never paths or timestamps."""
    payload = canonical_adjacency_layer(adjacency_mgr, adjacency_rule_mgr)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def adjacency_layer_count(adjacency_mgr: Any = None, adjacency_rule_mgr: Any = None) -> int:
    return len(_entries(adjacency_mgr)) + len(_entries(adjacency_rule_mgr))


@dataclass(frozen=True)
class AdjacencyReviewDecision:
    """Portable review decision used by planners and UI/readiness adapters."""

    state: str
    note: str
    current_hash: str
    accepted: bool
    finding: ValidationFinding | None = None


def evaluate_adjacency_review(
    adjacency_mgr: Any = None,
    adjacency_rule_mgr: Any = None,
    *,
    state: Any = "unreviewed",
    note: str = "",
    review_hash: str | None = None,
    context: str = "foundation_candidate",
) -> AdjacencyReviewDecision:
    """Evaluate a review record against current manager content.

    ``unreviewed`` is a visible warning during candidate work and a blocker at
    freeze/accepted-lock time. ``none_intended`` requires a note and an empty
    layer. ``defined`` requires at least one entry/rule and a matching hash.
    """
    normalized = normalize_review_state(state)
    note_text = str(note or "").strip()
    current_hash = adjacency_layer_hash(adjacency_mgr, adjacency_rule_mgr)
    count = adjacency_layer_count(adjacency_mgr, adjacency_rule_mgr)
    freeze_context = context in ("freeze", "accepted_lock")
    finding: ValidationFinding | None = None

    def make_finding(code: str, severity: str, message: str, *, affected=()):
        return ValidationFinding(
            code=code,
            severity=severity,
            message=message,
            layer="adjacency",
            affected_ids=tuple(affected),
            evidence="state=%s; entries=%d; hash=%s" % (normalized, count, current_hash),
        )

    if normalized == "unreviewed":
        severity = "blocker" if freeze_context else "warning"
        finding = make_finding(
            "adjacency.review.unreviewed",
            severity,
            "special adjacencies are unreviewed; mark none_intended or define the layer",
        )
    elif normalized == "none_intended":
        if not note_text:
            finding = make_finding(
                "adjacency.review.note_missing",
                "blocker" if freeze_context else "error",
                "none_intended adjacency review requires a geographic review note",
            )
        elif count:
            finding = make_finding(
                "adjacency.review.contradiction",
                "blocker" if freeze_context else "error",
                "none_intended adjacency review contradicts the non-empty adjacency layer",
            )
    elif normalized == "defined":
        if count == 0:
            finding = make_finding(
                "adjacency.review.defined_empty",
                "blocker" if freeze_context else "error",
                "defined adjacency review requires at least one adjacency or rule",
            )
        elif not str(review_hash or "").strip():
            finding = make_finding(
                "adjacency.review.hash_missing",
                "blocker" if freeze_context else "error",
                "defined adjacency review is missing its layer hash",
            )
        elif str(review_hash).strip() != current_hash:
            finding = make_finding(
                "adjacency.review.hash_stale",
                "blocker" if freeze_context else "error",
                "adjacency data changed since the last defined review",
            )

    return AdjacencyReviewDecision(
        state=normalized,
        note=note_text,
        current_hash=current_hash,
        accepted=finding is None,
        finding=finding,
    )


__all__ = [
    "AdjacencyReviewDecision",
    "LEGACY_REVIEW_STATES",
    "REVIEW_STATES",
    "adjacency_layer_count",
    "adjacency_layer_hash",
    "canonical_adjacency_layer",
    "evaluate_adjacency_review",
    "normalize_review_state",
]
