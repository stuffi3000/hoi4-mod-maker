"""ProvincialTerrainController — Only changes the province's gameplay terrain (no visual/height changes).

Reuse PaintTerrainCommand (supported passing only provincial_terrain_changes)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.map.paint_terrain import PaintTerrainCommand
from ui.i18n import tr

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class ProvincialTerrainController(BaseController):
    """Click province → change its provincial_terrain dict (do not change terrain.bmp / height_map).

    The default is viewing mode: click province to only display information (go to app_controller's province query).
    After turning on the allocation mode: click province to change the terrain."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_type: str = "plains"
        self.assign_mode: bool = False  # Default viewing mode

    def activate(self) -> None:
        self._emit_status(tr("status_pterrain_view"))

    def deactivate(self) -> None:
        pass

    def set_type(self, type_name: str) -> None:
        self.current_type = type_name
        if self.assign_mode:
            self._emit_status(tr("status_pterrain_selected", type_name))
        else:
            self._emit_status(tr("status_pterrain_selected_view", type_name))

    def set_assign_mode(self, enabled: bool) -> None:
        self.assign_mode = enabled
        if enabled:
            self._emit_status(tr("status_pterrain_assign_on", self.current_type))
        else:
            self._emit_status(tr("status_pterrain_view_on"))

    def on_province_clicked(self, pid: int) -> None:
        if pid <= 0:
            return
        # View mode: Do not change the data, just let the province information of app_controller be displayed and processed
        if not self.assign_mode:
            return

        map_data = self.project.map_data
        province_map = map_data.province_map
        tile_map = map_data.tile_map

        # Ocean/lake provinces cannot be changed
        from data.constants import TILE_SEA, TILE_LAKE
        ys, xs = np.where(province_map == pid)
        if len(ys) == 0:
            return
        tile_val = int(tile_map[ys[0], xs[0]])
        if tile_val in (TILE_SEA, TILE_LAKE):
            self._emit_status(tr("status_pterrain_sea_skip", pid))
            return

        # Reuse PaintTerrainCommand and only pass provincial_terrain_changes
        cmd = PaintTerrainCommand(
            map_data,
            terrain_changes={},
            height_changes=None,
            provincial_terrain_changes={pid: self.current_type},
        )
        self.history.execute(cmd)
        self.project.mark_dirty()
        self._emit_render(full=True)
        self._emit_status(tr("status_pterrain_applied", pid, self.current_type))

    def sync_from_visual(self) -> None:
        """Re-infer attribute terrain for all land provinces from visual terrain (terrain.bmp).

        Effect: Each land province's attributes = its majority terrain on terrain_map, overriding manual settings.
        Applicable: After automatically generating/redrawing the visual terrain, you want the attribute layer to keep up with the full volume.
        Call: the synchronization button of the attribute terrain page (the page has been played twice for confirmation before clicking); can be revoked."""
        from services.terrain_service import compute_provincial_terrain_from_bmp

        map_data = self.project.map_data
        inferred = compute_provincial_terrain_from_bmp(
            map_data.terrain_map, map_data.province_map, map_data.tile_map,
        )
        changes = {
            pid: terr for pid, terr in inferred.items()
            if map_data.provincial_terrain.get(pid) != terr
        }
        if not changes:
            self._emit_status(tr("status_pterrain_sync_nochange"))
            return

        cmd = PaintTerrainCommand(
            map_data,
            terrain_changes={},
            height_changes=None,
            provincial_terrain_changes=changes,
        )
        cmd.label = "Sync provincial terrain"
        self.history.execute(cmd)
        self.project.mark_dirty()
        self._emit_render(full=True)
        self._emit_status(tr("status_pterrain_synced", len(changes)))
