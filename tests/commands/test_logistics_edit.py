from __future__ import annotations

from commands.history import CommandHistory
from commands.map.logistics_edit import apply_manager_edit
from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRule, AdjacencyRuleManager
from domain.project_meta import default_meta


class _Project:
    def __init__(self) -> None:
        self.project_meta = default_meta()
        self.dirty = False

    def mark_dirty(self) -> None:
        self.dirty = True


def test_adjacency_edit_is_undoable_and_invalidates_review() -> None:
    manager = AdjacencyManager()
    manager.add(AdjacencyEntry(1, 2, start_x=4, start_y=5))
    project = _Project()
    project.project_meta.adjacency_review = "defined"
    project.project_meta.adjacency_review_note = "reviewed"
    project.project_meta.adjacency_review_hash = "old"
    history = CommandHistory()

    changed = apply_manager_edit(
        manager,
        "edit adjacency",
        lambda value: value.add(AdjacencyEntry(3, 4, comment="new")),
        history=history,
        project=project,
        invalidate_adjacency_review=True,
    )

    assert changed
    assert {(entry.from_id, entry.to_id) for entry in manager.get_all()} == {(1, 2), (3, 4)}
    assert project.project_meta.adjacency_review == "unreviewed"
    assert project.dirty

    assert history.undo()
    assert [(entry.from_id, entry.to_id) for entry in manager.get_all()] == [(1, 2)]
    assert project.project_meta.adjacency_review == "defined"
    assert project.project_meta.adjacency_review_hash == "old"

    assert history.redo()
    assert {(entry.from_id, entry.to_id) for entry in manager.get_all()} == {(1, 2), (3, 4)}
    assert project.project_meta.adjacency_review == "unreviewed"


def test_rule_edit_uses_manager_snapshot_without_live_mutation() -> None:
    manager = AdjacencyRuleManager()
    manager.add(AdjacencyRule(name="CANAL"))
    history = CommandHistory()

    assert apply_manager_edit(
        manager,
        "edit rule",
        lambda value: value.get("CANAL").required_provinces.append(10),
        history=history,
    )
    assert manager.get("CANAL").required_provinces == [10]
    assert history.undo()
    assert manager.get("CANAL").required_provinces == []
