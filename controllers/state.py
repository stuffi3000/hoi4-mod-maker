"""Controller for assigning provinces to states and editing state metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from controllers.base import BaseController
from commands.state.assign import AssignProvinceToStateCommand
from commands.state.delete import DeleteStateCommand
from commands.state.set_property import SetStatePropertyCommand
from commands.state.set_vp import SetVPCommand
from data.constants import TILE_LAND

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class StateController(BaseController):
    """Coordinate state selection, province assignment, and state-level edits."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        """Initialize state selection and listen for province-map regeneration."""
        super().__init__(project, command_history)
        self.selected_state_id: int = 0
        # Map clicks assign provinces to the selected state while this mode is active.
        self.assign_mode: bool = False
        # Regenerating provinces invalidates existing state assignments.
        self.event_bus.subscribe("province_map_regenerated", self._on_province_regen)

    def _is_land_province(self, pid: int) -> bool:
        """Return whether a province contains more land than sea or lake pixels."""
        if pid <= 0:
            return False
        map_data = self.project.map_data
        mask = (map_data.province_map == pid)
        total = int(mask.sum())
        if total == 0:
            return False
        land_count = int(((map_data.tile_map == TILE_LAND) & mask).sum())
        return land_count * 2 > total

    def _on_province_regen(self, event) -> None:
        """Clear state data when a complete province map is regenerated."""
        if not event.data.get("incremental"):
            self.project.state_mgr.clear()
            self.selected_state_id = 0
            self.event_bus.emit("state_changed", state_id=0, action="refresh")

    def activate(self) -> None:
        """Enter state editing mode and refresh the state overlay."""
        self._emit_status("State editing mode")
        self.event_bus.emit("state_changed", state_id=0, action="refresh")

    def deactivate(self) -> None:
        """Leave state editing mode and clear any batch selection."""
        self.assign_mode = False
        self.event_bus.emit("clear_batch_selection")

    def on_province_clicked(self, pid: int) -> None:
        """Select a state or assign the clicked province to the active state."""
        if pid <= 0:
            return

        state_mgr = self.project.state_mgr
        sid = state_mgr.get_state_of_province(pid)

        # Assignment mode moves the clicked land province into the selected state.
        if self.assign_mode and self.selected_state_id > 0:
            if sid == self.selected_state_id:
                return
            if not self._is_land_province(pid):
                self._emit_status(f"Province {pid} is sea/lake and cannot be added to a state (states contain land only)")
                return
            cmd = AssignProvinceToStateCommand(
                state_mgr, pid, sid, self.selected_state_id,
            )
            self.history.execute(cmd)
            self.project.mark_dirty()
            self.event_bus.emit(
                "state_changed",
                state_id=self.selected_state_id,
                action="modified",
                property="assign",
            )
            self._emit_status(f"Province {pid} assigned to State {self.selected_state_id}")
            # Refresh the selected state after the assignment.
            updated = state_mgr.get_state(self.selected_state_id)
            if updated:
                self.event_bus.emit("state_changed", state_id=self.selected_state_id, action="selected")
            return

        # Without assignment mode, a click selects the state containing the province.
        if sid > 0:
            self.selected_state_id = sid
            state = state_mgr.get_state(sid)
            name = state.name if state else f"STATE_{sid}"
            prov_count = len(state.provinces) if state else 0
            self._emit_status(f"State #{sid} \"{name}\" ({prov_count} provinces)")
            self.event_bus.emit(
                "state_changed", state_id=sid, action="selected",
            )
        else:
            self._emit_status(f"Province {pid} is not assigned to any state (red highlighted area)")

    def on_province_double_clicked(self, pid: int) -> None:
        """Open the victory-point editor for the state-owned province."""
        if pid <= 0:
            return

        state_mgr = self.project.state_mgr
        sid = state_mgr.get_state_of_province(pid)
        if sid == 0:
            self._emit_status("This province is not assigned to a state; group provinces first")
            return

        self.event_bus.emit("vp_dialog_requested", pid=pid, state_id=sid)

    def delete_state(self, sid: int) -> None:
        """Delete a state and release its provinces."""
        state_mgr = self.project.state_mgr
        country_mgr = self.project.country_mgr
        if sid <= 0 or state_mgr.get_state(sid) is None:
            self._emit_status(f"State {sid} does not exist")
            return
        cmd = DeleteStateCommand(state_mgr, country_mgr, sid)
        self.history.execute(cmd)
        if self.selected_state_id == sid:
            self.selected_state_id = 0
        self.project.mark_dirty()
        self.event_bus.emit("state_changed", state_id=sid, action="deleted")
        self._emit_status(f"Deleted State {sid}")

    def set_vp(self, pid: int, value: int, name: str = "") -> None:
        """Set or remove victory points and optionally store a city name."""
        state_mgr = self.project.state_mgr

        # Capture the owning state and the previous victory-point value for undo.
        sid = state_mgr.get_state_of_province(pid)
        state = state_mgr.get_state(sid) if sid > 0 else None
        old_vp = state.victory_points.get(pid) if state else None

        new_vp = value if value > 0 else None

        cmd = SetVPCommand(state_mgr, pid, old_vp, new_vp)
        self.history.execute(cmd)

        # Update the optional city name only when victory points are being added.
        if new_vp:
            state_mgr.set_vp(pid, value, name)
            if not name and state is not None:
                state.vp_names[pid] = ""
        self.project.mark_dirty()

        if new_vp:
            label_en = f"Province {pid} set to {value} VP"
            if name:
                label_en += f" ({name})"
            self._emit_status(label_en)
        else:
            self._emit_status(f"Victory points removed from province {pid}")
        self.event_bus.emit("vp_changed", pid=pid, value=value)

    def auto_states(self, per_state: int) -> None:
        """Automatically group provinces into states of the requested size."""
        state_mgr = self.project.state_mgr
        map_data = self.project.map_data

        state_mgr.auto_split(
            map_data.province_map,
            map_data.tile_map,
            per_state,
        )
        self.project.mark_dirty()

        count = len(state_mgr.states)
        self._emit_status(f"State grouping complete: {count} states")
        self.event_bus.emit("state_changed", state_id=0, action="refresh")

    def select_state(self, state_id: int) -> None:
        """Select a state and notify views that its detail panel should refresh."""
        self.selected_state_id = state_id
        state = self.project.state_mgr.get_state(state_id)
        if state:
            self.event_bus.emit(
                "state_changed",
                state_id=state_id,
                action="selected",
            )

    def create_state_from_provinces(self, province_ids: list[int]) -> int:
        """Create a state from selected land provinces and return its ID."""
        if not province_ids:
            return 0

        # Exclude sea and lake provinces because states contain land provinces only.
        land_pids = [p for p in province_ids if self._is_land_province(p)]
        skipped = len(province_ids) - len(land_pids)
        if not land_pids:
            self._emit_status("All selected provinces are sea/lake; no state was created")
            return 0
        if skipped > 0:
            self._emit_status(f"Skipped {skipped} sea/lake provinces")
        province_ids = land_pids

        state_mgr = self.project.state_mgr

        # Detach selected provinces from their current states before creating the new state.
        for pid in province_ids:
            old_sid = state_mgr.get_state_of_province(pid)
            if old_sid > 0:
                old_state = state_mgr.get_state(old_sid)
                if old_state and pid in old_state.provinces:
                    old_state.provinces.remove(pid)
                    state_mgr._province_to_state.pop(pid, None)

        # Create a predictable default name; the state editor can rename it later.
        new_state = state_mgr.create_state(provinces=list(province_ids))
        new_state.name = f"STATE_{new_state.id}"

        self.project.mark_dirty()
        self._emit_status(f"Created State {new_state.id} ({len(province_ids)} provinces)")
        self.event_bus.emit("state_changed", state_id=new_state.id, action="refresh")
        return new_state.id

    def change_property(self, state_id: int, prop: str, value: Any) -> None:
        """Set a state property through the command history."""
        state_mgr = self.project.state_mgr
        state = state_mgr.get_state(state_id)
        if not state:
            return

        old_value = getattr(state, prop, None)
        if old_value == value:
            return

        # Keep numeric manpower numeric while storing other properties as text.
        if prop == "manpower":
            value = int(value)
        else:
            value = str(value)

        cmd = SetStatePropertyCommand(state_mgr, state_id, prop, old_value, value)
        self.history.execute(cmd)
        self.project.mark_dirty()
        self.event_bus.emit(
            "state_changed", state_id=state_id, action="modified",
        )
