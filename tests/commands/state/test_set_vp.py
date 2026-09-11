"""SetVPCommand unit test."""

import pytest

from domain.managers.state import StateManager
from commands.state.set_vp import SetVPCommand


class TestSetVPCommand:
    """SetVPCommand test."""

    def _make_state_mgr(self) -> StateManager:
        """Create a StateManager with a State."""
        mgr = StateManager()
        state = mgr.create_state(provinces=[1, 2, 3])
        return mgr

    def test_execute_sets_vp(self) -> None:
        """execute should set VP."""
        mgr = self._make_state_mgr()
        cmd = SetVPCommand(mgr, pid=1, old_vp=None, new_vp=10)
        cmd.execute()

        state = mgr.get_state(1)
        assert state is not None
        assert state.victory_points[1] == 10

    def test_undo_restores_no_vp(self) -> None:
        """undo should remove a VP that did not exist before."""
        mgr = self._make_state_mgr()
        cmd = SetVPCommand(mgr, pid=1, old_vp=None, new_vp=10)
        cmd.execute()
        cmd.undo()

        state = mgr.get_state(1)
        assert state is not None
        assert 1 not in state.victory_points

    def test_undo_restores_old_vp(self) -> None:
        """undo should restore the old VP value."""
        mgr = self._make_state_mgr()
        # First set an initial VP
        mgr.set_vp(2, 5)

        cmd = SetVPCommand(mgr, pid=2, old_vp=5, new_vp=20)
        cmd.execute()

        state = mgr.get_state(1)
        assert state is not None
        assert state.victory_points[2] == 20

        cmd.undo()
        assert state.victory_points[2] == 5

    def test_execute_remove_vp(self) -> None:
        """execute should remove the VP when new_vp=None."""
        mgr = self._make_state_mgr()
        mgr.set_vp(1, 10)

        cmd = SetVPCommand(mgr, pid=1, old_vp=10, new_vp=None)
        cmd.execute()

        state = mgr.get_state(1)
        assert state is not None
        assert 1 not in state.victory_points
