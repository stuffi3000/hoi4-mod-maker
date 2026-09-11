"""TerrainController — Terrain editing mode controller.

Handles province-level terrain assignment and brush mode terrain drawing."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.map.paint_terrain import PaintTerrainCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class TerrainController(BaseController):
    """Terrain editing mode: province designation/brush drawing."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_terrain_index: int = 0
        self.brush_mode: bool = False
        self.brush_size: int = 20
        self.soft_edge: bool = False
        self._stroke_changes: dict[tuple[int, int], int] = {}
        self._is_painting: bool = False

    def activate(self) -> None:
        """Enter terrain mode."""
        self._stroke_changes.clear()
        self._is_painting = False
        self._emit_status("Terrain editing mode")

    def deactivate(self) -> None:
        """Exit terrain mode to end unfinished strokes."""
        if self._is_painting:
            self._commit_stroke()

    def on_province_clicked(self, pid: int) -> None:
        """In province mode, click on the province to set the terrain."""
        if self.brush_mode or pid <= 0:
            return

        map_data = self.project.map_data
        province_map = map_data.province_map
        tile_map = map_data.tile_map
        mask = province_map == pid
        ys, xs = np.where(mask)
        if len(ys) == 0:
            return

        # The terrain of ocean/lake provinces cannot be changed
        from data.constants import TILE_SEA, TILE_LAKE
        tile_val = int(tile_map[ys[0], xs[0]])
        if tile_val in (TILE_SEA, TILE_LAKE):
            return

        # Collect terrain changes
        terrain_map = map_data.terrain_map
        terrain_changes = {}
        for i in range(len(ys)):
            y, x = int(ys[i]), int(xs[i])
            if int(terrain_map[y, x]) != self.current_terrain_index:
                terrain_changes[(y, x)] = self.current_terrain_index

        if not terrain_changes:
            return

        # Provincial_terrain is no longer automatically changed (province attributes are carefully selected by the user and should not be overwritten by visual painting).
        # Height is no longer linked - height is independent of terrain vision, and users use a dedicated "reverse height from terrain" function.
        # Want to change province attributes → switch to provincial_terrain mode and specify manually.
        cmd = PaintTerrainCommand(
            map_data, terrain_changes,
            provincial_terrain_changes=None,
            height_changes=None,
        )
        self.history.execute(cmd)
        self.project.mark_dirty()
        # Visually changed → colormap needs to be reborn; changing height also triggers normal
        self._invalidate_art_assets(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/world_normal.bmp",
        )
        self._emit_render(full=True)
        from data.terrain_types import PALETTE_TO_TYPE, TERRAIN_TYPES
        tkey = PALETTE_TO_TYPE.get(self.current_terrain_index)
        terrain = TERRAIN_TYPES.get(tkey)
        terrain_name = terrain.name_en if terrain else "Unknown"
        self._emit_status(f"Province {pid} terrain set to {terrain_name}")

    def on_press(self, x: int, y: int, pid: int, button: str, modifiers: set) -> bool:
        """Mouse down in brush mode."""
        if not self.brush_mode or button != "left":
            return False
        self._is_painting = True
        self._stroke_changes.clear()
        self._apply_brush(x, y)
        return True

    def on_drag(self, x: int, y: int) -> bool:
        """Mouse drag in brush mode."""
        if not self._is_painting:
            return False
        self._apply_brush(x, y)
        return True

    def on_release(self, x: int, y: int) -> bool:
        """Mouse release in brush mode."""
        if not self._is_painting:
            return False
        self._commit_stroke()
        return True

    def _apply_brush(self, x: int, y: int) -> None:
        """Applies a circular terrain brush at (x, y) (NumPy vectorized)."""
        map_data = self.project.map_data
        terrain_map = map_data.terrain_map
        tile_map = map_data.tile_map
        h, w = terrain_map.shape
        r = self.brush_size // 2
        if r < 1:
            r = 1

        # Calculate influence area boundaries
        y0 = max(0, y - r)
        y1 = min(h, y + r + 1)
        x0 = max(0, x - r)
        x1 = min(w, x + r + 1)

        # Construct sub-region coordinate grid
        ys = np.arange(y0, y1)
        xs = np.arange(x0, x1)
        yy, xx = np.meshgrid(ys, xs, indexing='ij')

        # Circular judgment
        dist_sq = (yy - y) ** 2 + (xx - x) ** 2
        r_sq = r * r
        circle = dist_sq <= r_sq

        # Soft edge: The outer 30% area is randomly discarded
        if self.soft_edge and r > 3:
            inner_r = r * 0.7
            inner_r_sq = inner_r * inner_r
            in_ring = dist_sq > inner_r_sq
            # The farther the distance, the lower the probability
            dist = np.sqrt(dist_sq.astype(np.float32))
            prob = 1.0 - (dist - inner_r) / (r - inner_r + 1e-6)
            prob = np.clip(prob, 0, 1)
            random_mask = np.random.random(dist_sq.shape) < prob
            circle = circle & (~in_ring | random_mask)

        # Sea/Lake Protection
        from data.constants import TILE_SEA, TILE_LAKE
        sub_tile = tile_map[y0:y1, x0:x1]
        circle = circle & (sub_tile != TILE_SEA) & (sub_tile != TILE_LAKE)

        # Only change different pixels
        sub_terrain = terrain_map[y0:y1, x0:x1]
        changed = circle & (sub_terrain != self.current_terrain_index)

        # Collect changes
        coords = np.argwhere(changed)
        for cy, cx in coords:
            self._stroke_changes[(y0 + int(cy), x0 + int(cx))] = self.current_terrain_index

    def _commit_stroke(self) -> None:
        """Submit terrain strokes + one-way sync: painted province majority terrain → provincial_terrain dict.

        After the brush paints a stroke, count the majority of graphical representations of each painted province on the terrain_map
        terrain → infer provincial type → update dict. In this way, vision is the main one, and attributes automatically follow."""
        self._is_painting = False
        if not self._stroke_changes:
            return

        # Count the most painted terrains for each province → provincial_terrain
        from data.terrain_types import PALETTE_TO_TYPE
        from collections import Counter

        map_data = self.project.map_data
        province_map = map_data.province_map
        terrain_map = map_data.terrain_map

        # Collect all province pixels that are painted
        province_changes: dict[int, Counter] = {}
        for (y, x), new_terr_idx in self._stroke_changes.items():
            pid = int(province_map[y, x])
            if pid <= 0:
                continue
            if pid not in province_changes:
                province_changes[pid] = Counter()
            province_changes[pid][new_terr_idx] += 1

        # Provincial_terrain is no longer automatically changed based on the pixels painted by the brush
        # (The user's province attributes are carefully selected and should not be overwritten by the visual brush).
        # Want to change province attributes → switch to provincial_terrain mode and specify manually.
        cmd = PaintTerrainCommand(
            map_data, self._stroke_changes,
            provincial_terrain_changes=None,
        )
        self.history.execute(cmd)
        self._stroke_changes = {}
        self.project.mark_dirty()
        self._invalidate_art_assets(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        self._emit_render(full=True)
