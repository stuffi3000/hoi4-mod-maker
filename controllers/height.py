"""HeightController — Height edit mode controller.

Handles setting height values ​​by province."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.map.set_height import SetHeightCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class HeightController(BaseController):
    """Height editing mode: Click on the province to set the height."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_height_value: int = 100

    def activate(self) -> None:
        """Enter altitude mode."""
        self._emit_status("Height editing mode")

    def on_province_clicked(self, pid: int) -> None:
        """Click on the province to set the height value."""
        if pid <= 0:
            return

        map_data = self.project.map_data
        province_map = map_data.province_map
        mask = province_map == pid

        if not np.any(mask):
            return

        cmd = SetHeightCommand(map_data, mask, self.current_height_value)
        self.history.execute(cmd)
        self.project.mark_dirty()
        # The height has changed → world_normal must be reborn (normals are calculated from the height map); colormap/fow is also slightly affected
        self._invalidate_art_assets(
            "map/world_normal.bmp",
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/terrain/fow_rgb_waterspec_a.dds",
        )
        self._emit_render(full=True)
        self._emit_status(f"Province {pid} height set to {self.current_height_value}")
