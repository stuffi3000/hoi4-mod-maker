"""M4.1 explicit adjacency-review state and freeze-policy tests."""
from __future__ import annotations

import pytest

from domain.adjacency_review import (
    adjacency_layer_hash,
    evaluate_adjacency_review,
)
from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRule, AdjacencyRuleManager
from domain.project_meta import ProjectMeta, default_meta


pytestmark = pytest.mark.unit


def test_default_review_is_unreviewed_with_empty_metadata():
    meta = default_meta(width=4, height=2)
    assert meta.adjacency_review == "unreviewed"
    assert meta.adjacency_review_note == ""
    assert meta.adjacency_review_hash is None


def test_metadata_round_trip_preserves_review_note_and_hash():
    meta = default_meta()
    meta.adjacency_review = "defined"
    meta.adjacency_review_note = "Reviewed the strait candidates against the coast."
    meta.adjacency_review_hash = "a" * 64

    restored = ProjectMeta.from_dict(meta.to_dict())

    assert restored.adjacency_review == "defined"
    assert restored.adjacency_review_note == meta.adjacency_review_note
    assert restored.adjacency_review_hash == meta.adjacency_review_hash


def test_legacy_reviewed_value_migrates_to_defined():
    restored = ProjectMeta.from_dict({"schema_version": 1, "adjacency_review": "reviewed"})
    assert restored.adjacency_review == "defined"


def test_adjacency_hash_is_order_independent_and_changes_with_content():
    first = AdjacencyManager()
    first.add(AdjacencyEntry(2, 3, "sea", comment="B"))
    first.add(AdjacencyEntry(1, 2, "impassable", comment="A"))
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(name="CANAL", required_provinces=[2, 3]))

    second = AdjacencyManager()
    second.add(AdjacencyEntry(1, 2, "impassable", comment="A"))
    second.add(AdjacencyEntry(2, 3, "sea", comment="B"))
    rules_second = AdjacencyRuleManager()
    rules_second.add(AdjacencyRule(name="CANAL", required_provinces=[2, 3]))

    original = adjacency_layer_hash(first, rules)
    assert original == adjacency_layer_hash(second, rules_second)
    second.add(AdjacencyEntry(3, 4, "sea"))
    assert original != adjacency_layer_hash(second, rules_second)


def test_empty_unreviewed_layer_is_a_freeze_blocker():
    decision = evaluate_adjacency_review(context="freeze")
    assert decision.accepted is False
    assert decision.finding is not None
    assert decision.finding.code == "adjacency.review.unreviewed"
    assert decision.finding.severity == "blocker"


def test_none_intended_requires_note_but_accepts_empty_layer():
    missing = evaluate_adjacency_review(state="none_intended", context="freeze")
    assert missing.finding is not None
    assert missing.finding.code == "adjacency.review.note_missing"

    accepted = evaluate_adjacency_review(
        state="none_intended",
        note="Geographic review found no sea crossings or impassable borders.",
        context="freeze",
    )
    assert accepted.accepted is True
    assert accepted.finding is None


def test_defined_review_requires_matching_nonempty_hash():
    manager = AdjacencyManager()
    manager.add(AdjacencyEntry(1, 2, "sea"))
    current = adjacency_layer_hash(manager)

    accepted = evaluate_adjacency_review(
        manager, state="defined", review_hash=current, context="freeze"
    )
    assert accepted.accepted is True

    stale = evaluate_adjacency_review(
        manager, state="defined", review_hash="0" * 64, context="freeze"
    )
    assert stale.finding is not None
    assert stale.finding.code == "adjacency.review.hash_stale"


def test_defined_empty_layer_is_not_accepted():
    decision = evaluate_adjacency_review(
        state="defined", review_hash=adjacency_layer_hash(), context="freeze"
    )
    assert decision.finding is not None
    assert decision.finding.code == "adjacency.review.defined_empty"
