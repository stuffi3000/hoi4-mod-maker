"""ContinentController — Continental partition editing controller.

Handles continent addition/renaming/deletion/province assignment."""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class ContinentController(BaseController):
    """Mainland Division Editor."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.pick_on: bool = False
        self.pick_index: int = -1
        self.assign_by_state: bool = False
        # Always listen for province regeneration
        self.event_bus.subscribe("province_map_regenerated", self._on_province_regen)

    def _on_province_regen(self, event) -> None:
        """Provinces are regenerated in full → continent allocation is cleared."""
        if not event.data.get("incremental"):
            self.project.continent_mgr.clear()

    def activate(self) -> None:
        """Enter continental mode."""
        self.pick_on = False
        self.pick_index = -1
        self._emit_status("Continent editing mode")

    def deactivate(self) -> None:
        """Leave continental mode."""
        self.pick_on = False
        self.pick_index = -1

    def toggle_pick(self, on: bool, index: int = -1) -> None:
        """Switch continent assignment pickup mode."""
        self.pick_on = on
        self.pick_index = index if on else -1
        if on and index >= 0:
            self._emit_status("Continent assignment: click a land province")
        else:
            self._emit_status("Continent assignment disabled")

    def on_province_clicked(self, pid: int) -> None:
        """Click on a province in pickup mode to assign a continent. Supports state level batch allocation."""
        if not self.pick_on or self.pick_index < 0 or pid <= 0:
            return

        import numpy as np
        from data.constants import TILE_LAND

        map_data = self.project.map_data
        province_map = map_data.province_map
        tile_map = map_data.tile_map

        # Gather a list of provinces to be allocated
        if self.assign_by_state:
            state_mgr = self.project.state_mgr
            sid = state_mgr.get_state_of_province(pid)
            state = state_mgr.get_state(sid) if sid > 0 else None
            pids = list(state.provinces) if state else [pid]
        else:
            pids = [pid]

        continent_mgr = self.project.continent_mgr
        count = 0
        for p in pids:
            ys, xs = np.where(province_map == p)
            if len(ys) == 0:
                continue
            if int(tile_map[ys[0], xs[0]]) != TILE_LAND:
                continue
            continent_mgr.assign_province(p, self.pick_index)
            count += 1

        if count > 0:
            self.project.mark_dirty()
            self._emit_status(f"{count} provinces assigned to continent #{self.pick_index + 1}")
            self.event_bus.emit("continent_changed", action="assigned")

    def add_continent(self, name: str) -> bool:
        """Add continent. Return whether successful."""
        try:
            self.project.continent_mgr.add_continent(name)
            self.project.mark_dirty()
            self.event_bus.emit("continent_changed", action="added")
            return True
        except ValueError as e:
            self._emit_status(f"Failed to add continent: {e}")
            return False

    def rename_continent(self, index: int, name: str) -> bool:
        """Rename the continent."""
        try:
            self.project.continent_mgr.rename_continent(index, name)
            self.project.mark_dirty()
            self.event_bus.emit("continent_changed", action="renamed")
            return True
        except (ValueError, IndexError) as e:
            self._emit_status(f"Rename failed: {e}")
            return False

    def remove_continent(self, index: int) -> bool:
        """Delete continent."""
        try:
            self.project.continent_mgr.remove_continent(index)
            self.project.mark_dirty()
            self.event_bus.emit("continent_changed", action="removed")
            return True
        except (ValueError, IndexError) as e:
            self._emit_status(f"Delete failed: {e}")
            return False
