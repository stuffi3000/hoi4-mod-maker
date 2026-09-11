"""ProvinceController — Province edit mode controller.

Handle province merging, expansion, and cutting operations."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.province.merge import MergeProvincesCommand
from commands.province.split import SplitProvinceCommand
from commands.province.delete import DeleteProvincesCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class ProvinceController(BaseController):
    """Province editing modes: merge/expand/cut."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.merge_mode: bool = False
        self.merge_first_pid: int = 0
        self.expand_mode: bool = False
        self.selected_province_id: int = 0

    def activate(self) -> None:
        """Enter province mode."""
        self.merge_mode = False
        self.merge_first_pid = 0
        self.expand_mode = False
        self._emit_status("Province editing mode")

    def deactivate(self) -> None:
        """Exit province mode and clean up the state."""
        self.merge_mode = False
        self.merge_first_pid = 0
        self.expand_mode = False

    def on_province_clicked(self, pid: int) -> None:
        """Left click on provinces: select or merge."""
        if pid <= 0:
            return

        if self.merge_mode:
            self._handle_merge_click(pid)
            return

        # normal choice
        self.selected_province_id = pid

    def set_merge_mode(self, on: bool) -> None:
        """Toggle merge mode on and off."""
        self.merge_mode = on
        self.merge_first_pid = 0
        if on:
            self.expand_mode = False
            self._emit_status("Merge mode: click the first province, then the second")
        else:
            self._emit_status("Back to view mode")

    def set_expand_mode(self, on: bool) -> None:
        """Switch expansion mode."""
        self.expand_mode = on
        if on:
            self.merge_mode = False
            self.merge_first_pid = 0
            self._emit_status("Expand mode: click a province, then drag to expand it")
        else:
            self._emit_status("Back to view mode")

    def delete_provinces(self, province_ids) -> set[int]:
        """Delete existing province IDs and all references as one undo step."""
        province_map = self.project.map_data.province_map
        requested = {int(pid) for pid in province_ids if int(pid) > 0}
        existing = set(int(pid) for pid in np.unique(province_map)) - {0}
        selected = requested & existing
        if not selected:
            return set()

        cmd = DeleteProvincesCommand(self.project, selected)
        self.history.execute(cmd)
        self.project.mark_dirty()

        max_id = int(province_map.max())
        remaining = set(int(pid) for pid in np.unique(province_map)) - {0}
        gaps = sorted(set(range(1, max_id + 1)) - remaining)
        self.event_bus.emit("province_count_changed", count=max_id)
        self.event_bus.emit("province_gaps_changed", gap_ids=gaps)
        self.event_bus.emit("state_changed", state_id=0, action="refresh")
        self.event_bus.emit("country_changed", tag="", action="refresh")
        self.event_bus.emit("continent_changed", action="refresh")
        self.event_bus.emit("sr_colors_dirty")
        self.event_bus.emit("railway_changed")
        self._emit_render(full=True)
        return selected

    def split_selected(self, axis: str = "horizontal") -> bool:
        """Cut the currently selected province.
        axis: "horizontal" (cut up and down) / "vertical" (cut left and right)
        Return whether successful."""
        import numpy as np
        from scipy.ndimage import label as _label

        pid = self.selected_province_id
        if pid <= 0:
            self._emit_status("Click a province to select it first")
            return False

        map_data = self.project.map_data
        province_map = map_data.province_map

        mask = province_map == pid
        pixels = int(np.sum(mask))
        if pixels < 16:
            self._emit_status("Split failed (province is too small; at least 16 pixels required)")
            return False

        ys, xs = np.where(mask)

        # Priority is given to using the hole ID. If there is no hole, use max+1.
        max_id = int(province_map.max())
        existing = set(np.unique(province_map)) - {0}
        gap_ids = sorted(set(range(1, max_id + 1)) - existing)
        new_pid = gap_ids[0] if gap_ids else max_id + 1

        # Cut by axis
        if axis == "vertical":
            mid = int(np.median(xs))
            split_sel = xs <= mid
        else:
            mid = int(np.median(ys))
            split_sel = ys <= mid

        split_mask = np.zeros_like(province_map, dtype=bool)
        split_mask[ys[split_sel], xs[split_sel]] = True

        # Executed via Command (connectivity fixes included)
        cmd = SplitProvinceCommand(map_data, pid, new_pid, split_mask)
        self.history.execute(cmd)

        self.project.mark_dirty()
        self._emit_status(f"Province {pid} split; new province ID: {new_pid}")
        self._emit_render(full=True)

        max_id = int(province_map.max())
        self.event_bus.emit("province_count_changed", count=max_id)

        # Update hole list
        existing = set(np.unique(province_map)) - {0}
        remaining_gaps = sorted(set(range(1, max_id + 1)) - existing)
        self.event_bus.emit("province_gaps_changed", gap_ids=remaining_gaps)
        return True


    def split_by_line(self, pid: int, line_points: list[tuple[int, int]]) -> bool:
        """Cut provinces with angle lines.
        line_points = [(cy, cx), (direction point), (mouse click position)].
        The side clicked by the mouse is cut out into a new province."""
        import numpy as np

        map_data = self.project.map_data
        province_map = map_data.province_map

        mask = province_map == pid
        pixels = int(np.sum(mask))
        if pixels < 16:
            self._emit_status("Split failed (province is too small)")
            return False

        # Prefer empty IDs
        max_id = int(province_map.max())
        existing = set(np.unique(province_map)) - {0}
        gap_ids = sorted(set(range(1, max_id + 1)) - existing)
        new_pid = gap_ids[0] if gap_ids else max_id + 1

        # Analytical line: center of mass + direction + mouse position
        cy, cx = line_points[0]
        dir_y, dir_x = float(line_points[1][0] - cy), float(line_points[1][1] - cx)

        # Cross product determines which side of the line each pixel is on
        # cross = (px-cx)*dir_y - (py-cy)*dir_x
        ys, xs = np.where(mask)
        cross = (xs - cx).astype(np.float64) * dir_y - (ys - cy).astype(np.float64) * dir_x

        # Determine which side the mouse click is on
        if len(line_points) >= 3:
            mouse_y, mouse_x = line_points[2]
            mouse_cross = float((mouse_x - cx) * dir_y - (mouse_y - cy) * dir_x)
        else:
            mouse_cross = 1.0

        # The side of the mouse → cut out to create a new province
        if mouse_cross > 0:
            split_sel = cross > 0
        else:
            split_sel = cross <= 0

        count_split = int(np.sum(split_sel))
        count_keep = len(ys) - count_split

        if count_split < 4 or count_keep < 4:
            self._emit_status("The split line did not divide the province into two valid parts")
            return False

        split_mask_arr = np.zeros_like(province_map, dtype=bool)
        split_mask_arr[ys[split_sel], xs[split_sel]] = True

        # Execute via Command
        cmd = SplitProvinceCommand(map_data, pid, new_pid, split_mask_arr)
        self.history.execute(cmd)

        self.project.mark_dirty()
        self._emit_status(f"Province {pid} split; new province ID: {new_pid}")
        self._emit_render(full=True)

        max_id = int(province_map.max())
        self.event_bus.emit("province_count_changed", count=max_id)
        existing = set(np.unique(province_map)) - {0}
        remaining_gaps = sorted(set(range(1, max_id + 1)) - existing)
        self.event_bus.emit("province_gaps_changed", gap_ids=remaining_gaps)
        return True

    def _handle_merge_click(self, pid: int) -> None:
        """Click on a province in merge mode."""
        if self.merge_first_pid == 0:
            self.merge_first_pid = pid
            self._emit_status(f"Province {pid} selected; click the province to merge into it")
        elif self.merge_first_pid == pid:
            self.merge_first_pid = 0
            self._emit_status("Selection cleared; merge mode remains active")
        else:
            # Perform merge
            cmd = MergeProvincesCommand(
                self.project.map_data,
                pid_keep=self.merge_first_pid,
                pid_remove=pid,
                state_mgr=self.project.state_mgr,
                country_mgr=self.project.country_mgr,
                strategic_region_mgr=self.project.strategic_region_mgr,
            )
            self.history.execute(cmd)
            self.project.mark_dirty()

            province_map = self.project.map_data.province_map
            max_id = int(province_map.max())

            # Send gaps and count (UI updates) first, and then trigger rendering
            existing = set(np.unique(province_map)) - {0}
            gap_ids = sorted(set(range(1, max_id + 1)) - existing)
            print(f"[merge] {pid} → {self.merge_first_pid} | max_id={max_id} actual={len(existing)} gaps={gap_ids[:10]}")
            self.event_bus.emit("province_gaps_changed", gap_ids=gap_ids)
            self.event_bus.emit("province_count_changed", count=max_id)
            if gap_ids:
                self._emit_status(f"Merged {pid} → {self.merge_first_pid}; missing IDs: {gap_ids[:5]}...")
            else:
                self._emit_status(f"Merged {pid} → {self.merge_first_pid} (no ID gaps)")
            self._emit_render(full=True)

            # Does not exit merge mode, resets and waits for next pair
