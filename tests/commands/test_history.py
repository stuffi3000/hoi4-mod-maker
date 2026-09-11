"""CommandHistory unit test."""
from commands.base import Command
from commands.history import CommandHistory
from model.events import EventBus


class FakeCommand(Command):
    """Fake command for testing."""

    label = "fake"

    def __init__(self) -> None:
        self.executed = 0
        self.undone = 0

    def execute(self) -> None:
        self.executed += 1

    def undo(self) -> None:
        self.undone += 1


class MergeableCommand(Command):
    """Mergeable false commands."""

    label = "mergeable"

    def __init__(self, value: int = 0) -> None:
        self.value = value
        self.merged_values: list[int] = [value]

    def execute(self) -> None:
        pass

    def undo(self) -> None:
        pass

    def can_merge_with(self, other: Command) -> bool:
        return isinstance(other, MergeableCommand)

    def merge(self, other: Command) -> None:
        if isinstance(other, MergeableCommand):
            self.merged_values.extend(other.merged_values)


class TestCommandHistory:
    """CommandHistory basic functionality."""

    def test_execute_pushes_to_undo_stack(self) -> None:
        """After execute, the command enters the undo stack."""
        history = CommandHistory()
        cmd = FakeCommand()
        history.execute(cmd)
        assert cmd.executed == 1
        assert history.can_undo
        assert not history.can_redo

    def test_undo_pops_and_calls_undo(self) -> None:
        """undo pops the command and calls cmd.undo()."""
        history = CommandHistory()
        cmd = FakeCommand()
        history.execute(cmd)
        result = history.undo()
        assert result is True
        assert cmd.undone == 1
        assert not history.can_undo
        assert history.can_redo

    def test_redo_pops_and_calls_execute(self) -> None:
        """redo pops the command and calls cmd.execute()."""
        history = CommandHistory()
        cmd = FakeCommand()
        history.execute(cmd)
        history.undo()
        result = history.redo()
        assert result is True
        assert cmd.executed == 2  # execute called twice (initial + redo)
        assert history.can_undo
        assert not history.can_redo

    def test_undo_on_empty_returns_false(self) -> None:
        """Empty stack undo returns False."""
        history = CommandHistory()
        assert history.undo() is False

    def test_redo_on_empty_returns_false(self) -> None:
        """Empty stack redo returns False."""
        history = CommandHistory()
        assert history.redo() is False

    def test_new_execute_clears_redo_stack(self) -> None:
        """The redo stack is cleared after the new command is executed."""
        history = CommandHistory()
        history.execute(FakeCommand())
        history.undo()
        assert history.can_redo
        history.execute(FakeCommand())
        assert not history.can_redo

    def test_max_size_enforced(self) -> None:
        """The oldest commands beyond max_size are discarded."""
        history = CommandHistory(max_size=3)
        for _ in range(5):
            history.execute(FakeCommand())
        # Only keep the last 3
        count = 0
        while history.undo():
            count += 1
        assert count == 3

    def test_event_bus_notified(self) -> None:
        """event_bus receives undo_state_changed after each operation."""
        bus = EventBus()
        notifications: list[dict] = []

        def on_state_changed(event) -> None:
            notifications.append({"can_undo": event.can_undo, "can_redo": event.can_redo})

        bus.subscribe("undo_state_changed", on_state_changed)
        history = CommandHistory(event_bus=bus)

        history.execute(FakeCommand())
        assert notifications[-1] == {"can_undo": True, "can_redo": False}

        history.undo()
        assert notifications[-1] == {"can_undo": False, "can_redo": True}

        history.redo()
        assert notifications[-1] == {"can_undo": True, "can_redo": False}

    def test_clear_empties_both_stacks(self) -> None:
        """clear clears the undo and redo stacks."""
        history = CommandHistory()
        history.execute(FakeCommand())
        history.execute(FakeCommand())
        history.undo()
        assert history.can_undo
        assert history.can_redo
        history.clear()
        assert not history.can_undo
        assert not history.can_redo

    def test_merge_commands(self) -> None:
        """Mergeable commands do not increase stack depth."""
        history = CommandHistory()
        history.execute(MergeableCommand(1))
        history.execute(MergeableCommand(2))
        history.execute(MergeableCommand(3))
        # Merge all into first command
        count = 0
        while history.undo():
            count += 1
        assert count == 1  # There is only one command on the stack
