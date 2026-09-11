"""CompositeCommand — Pack multiple subcommands into an atomic undo unit.

Usage: One operation affects multiple data sources (such as partial regeneration of province_map + state_mgr + sr_mgr + country_mgr),
Load respective child Commands into a CompositeCommand. When undoing, undo in reverse order, and when redoing, execute in forward order."""

from __future__ import annotations

from commands.base import Command


class CompositeCommand(Command):
    """Compound command — execute subcommands in order and undo in reverse order."""

    def __init__(self, children: list[Command], label: str = "Composite operation") -> None:
        if not children:
            raise ValueError("CompositeCommand requires at least one child command")
        self.label = label
        self._children = list(children)

    def execute(self) -> None:
        for cmd in self._children:
            cmd.execute()

    def undo(self) -> None:
        for cmd in reversed(self._children):
            cmd.undo()

    @property
    def children(self) -> list[Command]:
        return self._children
