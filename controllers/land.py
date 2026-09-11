"""LandController — Land edit mode controller.

Handles brush/eraser/fill tools for drawing tile_map (land/ocean/lake).
Supports density brush submode: paint province density on density_map."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.map.paint_tile import PaintTileCommand
from commands.map.fill_tile import FillTileCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class LandController(BaseController):
    """Continental editing modes: Brush/Eraser/Fill/Transform + Density Brush."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_tool: str = "brush"  # brush / eraser / fill / transform / new_land
        self.current_tile_type: int = 1  # TILE_LAND=1 default
        self.brush_size: int = 5
        self._stroke_changes: dict[tuple[int, int], int] = {}
        self._is_painting: bool = False
        # Density brush submode
        self.density_mode: bool = False
        self.density_value: float = 1.0  # 0.0~1.0
        # New World Brush: Record which pixels were painted
        h, w = project.map_data.tile_map.shape
        self.new_land_mask: np.ndarray = np.zeros((h, w), dtype=bool)

    def reset_mask_size(self) -> None:
        """Reset the mask after the map size changes."""
        h, w = self.project.map_data.tile_map.shape
        self.new_land_mask = np.zeros((h, w), dtype=bool)

    def activate(self) -> None:
        """Enter continental mode, default brush tool. Alert when there are provinces."""
        self.current_tool = "brush"
        self._stroke_changes.clear()
        self._is_painting = False
        has_provinces = int(self.project.map_data.province_map.max()) > 0
        if has_provinces:
            self._emit_status("⚠ Provinces already exist — after drawing new land, switch to Province mode and click Generate; choose Yes to generate only in new areas")
        else:
            self._emit_status("Land editing mode")

    def deactivate(self) -> None:
        """Exit continent mode and end unfinished strokes."""
        if self._is_painting:
            self._commit_stroke()
        self.density_mode = False

    def on_press(self, x: int, y: int, pid: int, button: str, modifiers: set) -> bool:
        """Mouse press starts brush or fill."""
        if button != "left":
            return False

        # Density brush mode
        if self.density_mode:
            self._is_painting = True
            self._apply_density_brush(x, y)
            return True

        if self.current_tool == "fill":
            self._do_fill(x, y)
            return True

        if self.current_tool in ("brush", "eraser", "new_land"):
            self._is_painting = True
            self._stroke_changes.clear()
            self._apply_brush(x, y)
            return True

        return False

    def on_drag(self, x: int, y: int) -> bool:
        """Drag the mouse to continue the brush."""
        if not self._is_painting:
            return False
        if self.density_mode:
            self._apply_density_brush(x, y)
        else:
            self._apply_brush(x, y)
        return True

    def on_release(self, x: int, y: int) -> bool:
        """Mouse release ends the brush stroke."""
        if not self._is_painting:
            return False
        if self.density_mode:
            self._is_painting = False
            self._emit_render(full=True)
        else:
            self._commit_stroke()
        return True

    # ── New World Paintbrush ──

    @property
    def new_land_pixel_count(self) -> int:
        return int(self.new_land_mask.sum())

    def clear_new_land_mask(self) -> None:
        """After generating provinces, clear the mask and the new continent becomes the old continent."""
        self.new_land_mask[:] = False

    # ── Density Brush ──

    def _apply_density_brush(self, x: int, y: int) -> None:
        """Paint on the density map."""
        map_data = self.project.map_data
        if map_data.density_map is None:
            from data.constants import MAP_WIDTH, MAP_HEIGHT
            map_data.density_map = np.full(
                (MAP_HEIGHT, MAP_WIDTH), 0.5, dtype=np.float32
            )

        dm = map_data.density_map
        h, w = dm.shape
        r = self.brush_size // 2
        y0, y1 = max(0, y - r), min(h, y + r + 1)
        x0, x1 = max(0, x - r), min(w, x + r + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        circle = (yy - y) ** 2 + (xx - x) ** 2 <= r * r
        dm[y0:y1, x0:x1][circle] = self.density_value

    # ── Ordinary brush ──

    def _apply_brush(self, x: int, y: int) -> None:
        """Apply the Circle Brush/Eraser/New World Brush at (x, y)."""
        from data.constants import TILE_SEA, TILE_LAND
        map_data = self.project.map_data
        tile_map = map_data.tile_map
        h, w = tile_map.shape
        r = self.brush_size // 2
        r_sq = r * r

        if self.current_tool == "new_land":
            tile_value = TILE_LAND
        elif self.current_tool == "eraser":
            tile_value = TILE_SEA
        else:
            tile_value = self.current_tile_type

        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if r >= 2 and dy * dy + dx * dx > r_sq:
                    continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w:
                    if int(tile_map[ny, nx]) != tile_value:
                        self._stroke_changes[(ny, nx)] = tile_value
                        # New World Brush: Only record pixels that actually changed from sea/lake to land, old land will not be recorded
                        if self.current_tool == "new_land":
                            self.new_land_mask[ny, nx] = True

    def _commit_stroke(self) -> None:
        """Submit the stroke as a Command."""
        self._is_painting = False
        if self._stroke_changes:
            cmd = PaintTileCommand(self.project.map_data, self._stroke_changes)
            self.history.execute(cmd)
            self._stroke_changes = {}
            self.project.mark_dirty()
            # The division of land and sea has changed → colormap / fow / world_normal / cities need to be reborn
            self._invalidate_art_assets(
                "map/terrain/colormap_rgb_cityemissivemask_a.dds",
                "map/terrain/colormap_water_0.dds",
                "map/terrain/colormap_water_1.dds",
                "map/terrain/colormap_water_2.dds",
                "map/terrain/fow_rgb_waterspec_a.dds",
                "map/world_normal.bmp",
            )
            self._emit_render(full=True)

    def _do_fill(self, x: int, y: int) -> None:
        """Flood fill."""
        from scipy.ndimage import label

        map_data = self.project.map_data
        tile_map = map_data.tile_map
        h, w = tile_map.shape
        if not (0 <= y < h and 0 <= x < w):
            return

        old_val = int(tile_map[y, x])
        new_val = self.current_tile_type
        if old_val == new_val:
            return

        mask = tile_map == old_val
        labeled, _ = label(mask)
        region_id = labeled[y, x]
        fill_mask = labeled == region_id

        cmd = FillTileCommand(map_data, fill_mask, new_val)
        self.history.execute(cmd)
        self.project.mark_dirty()
        self._invalidate_art_assets(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/terrain/colormap_water_0.dds",
            "map/terrain/colormap_water_1.dds",
            "map/terrain/colormap_water_2.dds",
            "map/terrain/fow_rgb_waterspec_a.dds",
            "map/world_normal.bmp",
        )
        self._emit_render(full=True)
