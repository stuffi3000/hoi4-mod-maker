"""StrategicRegionController — Strategic region editing controller.

Handles automatic generation, creation/deletion, province picking of strategic areas."""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class StrategicRegionController(BaseController):
    """Strategic Area Editor."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.pick_on: bool = False
        self.pick_rid: int = 0
        self.assign_mode: bool = False
        # Always listen for province regeneration
        self.event_bus.subscribe("province_map_regenerated", self._on_province_regen)

    def _on_province_regen(self, event) -> None:
        """Provinces are regenerated in full → strategic areas are cleared."""
        if not event.data.get("incremental"):
            self.project.strategic_region_mgr.clear()

    def activate(self) -> None:
        """Enter strategic area mode."""
        self.pick_on = False
        self.pick_rid = 0
        self._emit_status("Strategic region editing mode")

    def deactivate(self) -> None:
        """Exit strategic area mode and clear the highlight."""
        self.pick_on = False
        self.pick_rid = 0
        self.event_bus.emit("clear_batch_selection")

    def on_province_clicked(self, pid: int) -> None:
        """Click on the province: allocation mode → assign to the selected area; view mode → highlight the area."""
        if pid <= 0:
            return

        sr_mgr = self.project.strategic_region_mgr

        # Allocation mode: allocate provinces to the currently selected area
        if self.assign_mode and self.pick_rid > 0:
            sr_mgr.assign_province(pid, self.pick_rid)
            self.project.mark_dirty()
            region = sr_mgr.get(self.pick_rid)
            if region:
                self.event_bus.emit("batch_highlight_pids", pids=list(region.province_ids))
            self.event_bus.emit("sr_colors_dirty")
            self._emit_status(f"Province {pid} → strategic region #{self.pick_rid}")
            return

        if self.assign_mode and self.pick_rid <= 0:
            self._emit_status("Select a region in the list first")
            return

        # View mode: click on the province → highlight the strategic area + select in the list
        rid = sr_mgr.get_region_of_province(pid)
        if rid > 0:
            self.select_region(rid)
            self.event_bus.emit("sr_select_in_list", rid=rid)
        else:
            self._emit_status(f"Province {pid} is not assigned to a strategic region")

    def set_assign_mode(self, on: bool) -> None:
        """Switch assignment mode."""
        self.assign_mode = on
        if on:
            self._emit_status("Assign mode: click provinces to add them to the selected region")
        else:
            self._emit_status("View mode: click a province to inspect its region")

    def toggle_pick(self, on: bool, rid: int = 0) -> None:
        """Switch pickup mode."""
        self.pick_on = on
        self.pick_rid = rid if on else 0
        if on:
            self._emit_status(f"Strategic region picking: click a province → add to Region #{rid}")
        else:
            self._emit_status("Strategic region picking disabled")

    def auto_generate(self) -> None:
        """Automatically generate strategic areas."""
        map_data = self.project.map_data
        province_map = map_data.province_map

        if int(province_map.max()) == 0:
            self._emit_status("Generate provinces first")
            return

        sr_mgr = self.project.strategic_region_mgr
        sr_mgr.auto_generate(
            province_map,
            map_data.tile_map,
            state_mgr=self.project.state_mgr,
        )
        self.project.mark_dirty()
        self._emit_status(f"Generated {sr_mgr.count()} strategic regions")

    def auto_assign_weather(self) -> None:
        """Automatically assign weather presets to all strategic areas by latitude."""
        sr_mgr = self.project.strategic_region_mgr
        if sr_mgr.count() == 0:
            self._emit_status("No strategic regions exist; generate them first")
            return

        province_map = self.project.map_data.province_map
        changed = sr_mgr.auto_assign_weather_by_latitude(province_map)
        self.project.mark_dirty()
        self._emit_status(f"Assigned weather presets to {changed} strategic regions by latitude")

    def select_region(self, rid: int) -> None:
        """Select a strategic area → highlight all its provinces."""
        self.pick_rid = rid
        region = self.project.strategic_region_mgr.get(rid)
        if region:
            self.event_bus.emit("batch_highlight_pids", pids=list(region.province_ids))
            self._emit_status(f"Strategic region #{rid} \"{region.name}\" "
                f"({len(region.province_ids)} provinces, {region.weather_preset})")
        else:
            self.event_bus.emit("batch_highlight_pids", pids=[])

    def create_region(self) -> None:
        """Create new strategic areas."""
        self.project.strategic_region_mgr.create_region()
        self.project.mark_dirty()

    def delete_region(self, rid: int) -> None:
        """Remove strategic areas."""
        if rid > 0:
            self.project.strategic_region_mgr.remove_region(rid)
            self.project.mark_dirty()

    def set_name(self, rid: int, name: str) -> None:
        """Set the strategic area name."""
        r = self.project.strategic_region_mgr.get(rid)
        if r:
            r.name = name.strip() or f"STRATEGICREGION_{rid}"
            self.project.mark_dirty()

    def set_weather(self, rid: int, preset: str) -> None:
        """Set strategic area weather presets."""
        r = self.project.strategic_region_mgr.get(rid)
        if r:
            r.weather_preset = preset
            self.project.mark_dirty()

    def set_naval(self, rid: int, naval: str) -> None:
        """Set strategic area naval terrain."""
        r = self.project.strategic_region_mgr.get(rid)
        if r:
            r.naval_terrain = naval
            self.project.mark_dirty()

    def create_from_states(self, state_ids: list[int]) -> int:
        """Combine selected states into a strategic region. Returns the new region ID."""
        if not state_ids:
            return 0

        sr_mgr = self.project.strategic_region_mgr
        state_mgr = self.project.state_mgr

        # Collect all provinces in selected state
        province_ids: list[int] = []
        for sid in state_ids:
            state = state_mgr.get_state(sid)
            if state:
                province_ids.extend(state.provinces)

        if not province_ids:
            self._emit_status("The selected states contain no provinces")
            return 0

        # Remove these provinces from the old strategic area
        for pid in province_ids:
            old_rid = sr_mgr.get_region_of_province(pid)
            if old_rid > 0:
                old_r = sr_mgr.get(old_rid)
                if old_r and pid in old_r.province_ids:
                    old_r.province_ids.remove(pid)

        # Create new strategic areas
        r = sr_mgr.create_region()
        r.province_ids = province_ids
        self.project.mark_dirty()

        state_names = ", ".join(str(s) for s in state_ids[:5])
        if len(state_ids) > 5:
            state_names += f"... (+{len(state_ids)-5})"
        self._emit_status(f"Created strategic region #{r.id} (states {state_names}, {len(province_ids)} provinces)")
        return r.id
