"""Undoable manager edits used by the adjacency/logistics editors (M4.2)."""
from __future__ import annotations

import copy
from typing import Any, Callable

from commands.base import Command


def _review_snapshot(project: Any) -> tuple[str, str, str | None] | None:
    meta = getattr(project, "project_meta", None)
    if meta is None:
        return None
    return (
        str(getattr(meta, "adjacency_review", "unreviewed")),
        str(getattr(meta, "adjacency_review_note", "") or ""),
        getattr(meta, "adjacency_review_hash", None),
    )


def _restore_review(project: Any, snapshot: tuple[str, str, str | None] | None) -> None:
    if project is None or snapshot is None:
        return
    meta = getattr(project, "project_meta", None)
    if meta is None:
        return
    meta.adjacency_review, meta.adjacency_review_note, meta.adjacency_review_hash = snapshot


class ManagerStateCommand(Command):
    """Apply a manager's serialized before/after state with undo/redo.

    Adjacency/rule changes invalidate an existing review hash on execute. The
    previous review record is restored on undo so editing remains reversible.
    """

    def __init__(
        self,
        label: str,
        manager: Any,
        before: dict,
        after: dict,
        *,
        project: Any = None,
        invalidate_adjacency_review: bool = False,
    ) -> None:
        self.label = label
        self._manager = manager
        self._before = copy.deepcopy(before)
        self._after = copy.deepcopy(after)
        self._project = project
        self._invalidate_review = bool(invalidate_adjacency_review)
        self._before_review = _review_snapshot(project)

    def _apply(self, payload: dict, *, invalidate: bool) -> None:
        self._manager.from_dict(copy.deepcopy(payload))
        if invalidate and self._project is not None:
            meta = getattr(self._project, "project_meta", None)
            if meta is not None:
                meta.adjacency_review = "unreviewed"
                meta.adjacency_review_note = ""
                meta.adjacency_review_hash = None
        if self._project is not None:
            self._project.mark_dirty()

    def execute(self) -> None:
        self._apply(self._after, invalidate=self._invalidate_review)

    def undo(self) -> None:
        self._apply(self._before, invalidate=False)
        _restore_review(self._project, self._before_review)


def apply_manager_edit(
    manager: Any,
    label: str,
    mutate: Callable[[Any], None],
    *,
    history: Any = None,
    project: Any = None,
    invalidate_adjacency_review: bool = False,
) -> bool:
    """Build and apply an edit without mutating the live manager first."""
    before = manager.to_dict()
    working = copy.deepcopy(manager)
    mutate(working)
    after = working.to_dict()
    if before == after:
        return False
    if history is None:
        manager.from_dict(after)
        if invalidate_adjacency_review and project is not None:
            meta = getattr(project, "project_meta", None)
            if meta is not None:
                meta.adjacency_review = "unreviewed"
                meta.adjacency_review_note = ""
                meta.adjacency_review_hash = None
        if project is not None:
            project.mark_dirty()
        return True
    history.execute(ManagerStateCommand(
        label, manager, before, after, project=project,
        invalidate_adjacency_review=invalidate_adjacency_review,
    ))
    return True


__all__ = ["ManagerStateCommand", "apply_manager_edit"]
