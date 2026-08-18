"""Manual province brush and flood-fill tools.

The province bitmap is represented internally by ``MapData.province_map``.  A
positive integer is the province identity; export assigns its unique RGB value.
This tool therefore paints province IDs directly while keeping every stroke on
one land/sea/lake tile type.
"""
from __future__ import annotations

import numpy as np

from domain.tools.base import CleanupLevel, Tool, ToolContext


class ProvincePaintTool(Tool):
    """Paint a selected (or newly allocated) province into ``province_map``."""

    name = "province_paint"
    display_modes = ("province",)
    cleanup_level = CleanupLevel.NONE
    label = "Manual province drawing"
    description = "Pick or create a province, then draw its pixels"
    cursor = "cross"

    # MainWindow records framework strokes in the shared CommandHistory.  Do
    # not also create a second, legacy UndoManager entry here.
    def get_undo_array_names(self, ctx: ToolContext) -> list[str]:
        return []

    @staticmethod
    def configure(
        ctx: ToolContext,
        *,
        mode: str,
        brush_size: int | None = None,
        pid: int | None = None,
        tile_type: int | None = None,
    ) -> None:
        if mode not in ("brush", "fill"):
            raise ValueError(f"Unsupported province paint mode: {mode}")
        ctx.state["mode"] = mode
        if brush_size is not None:
            ctx.brush_size = max(1, min(100, int(brush_size)))
        if pid is not None:
            ctx.state["pid"] = max(0, int(pid))
            ctx.selected_province_id = max(0, int(pid))
            ctx.state["has_pixels"] = bool(
                int(pid) > 0 and np.any(ctx.map_data.province_map == int(pid))
            )
        if tile_type is not None:
            ctx.state["tile"] = int(tile_type)

    @staticmethod
    def begin_new_province(ctx: ToolContext) -> int:
        """Select the first missing ID, or max+1, without changing pixels yet."""
        pm = ctx.map_data.province_map
        max_pid = int(pm.max())
        existing = set(int(v) for v in np.unique(pm) if int(v) > 0)
        gaps = sorted(set(range(1, max_pid + 1)) - existing)
        pid = gaps[0] if gaps else max_pid + 1
        ctx.state["pid"] = pid
        ctx.state["tile"] = None  # inferred from the first painted pixel
        ctx.state["is_new"] = True
        ctx.state["has_pixels"] = False
        ctx.selected_province_id = pid
        return pid

    def on_press(self, ctx: ToolContext, x: int, y: int) -> None:
        if not self._in_bounds(ctx, x, y):
            return
        pid = int(ctx.state.get("pid", 0) or 0)
        if pid <= 0:
            return

        ctx.state["painting"] = True
        ctx.state["last_pos"] = None
        ctx.state["touched_pids"] = set()
        mode = ctx.state.get("mode", "brush")
        if mode == "fill":
            self._fill_at(ctx, x, y)
            ctx.state["painting"] = False
        else:
            self._paint_line_to(ctx, x, y)

    def on_drag(self, ctx: ToolContext, x: int, y: int) -> None:
        if not ctx.state.get("painting") or not self._in_bounds(ctx, x, y):
            return
        self._paint_line_to(ctx, x, y)

    def on_release(self, ctx: ToolContext, x: int, y: int) -> None:
        ctx.state["painting"] = False
        ctx.state["last_pos"] = None

    def run_cleanup(self, ctx: ToolContext) -> None:
        """Repair donor fragments and X-crossings after a manual stroke."""
        self._repair_touched_provinces(ctx)
        for _ in range(3):
            if self._fix_type_safe_x_crossings(ctx) == 0:
                break
        ctx.map_data.invalidate_centroid_cache()

    @staticmethod
    def _in_bounds(ctx: ToolContext, x: int, y: int) -> bool:
        h, w = ctx.map_data.province_map.shape
        return 0 <= x < w and 0 <= y < h

    def _paint_line_to(self, ctx: ToolContext, x: int, y: int) -> None:
        last = ctx.state.get("last_pos")
        if last is None:
            self._stamp(ctx, x, y)
        else:
            lx, ly = last
            steps = max(abs(x - lx), abs(y - ly))
            if steps == 0:
                self._stamp(ctx, x, y)
            else:
                for i in range(1, steps + 1):
                    t = i / steps
                    self._stamp(
                        ctx,
                        int(round(lx + (x - lx) * t)),
                        int(round(ly + (y - ly) * t)),
                    )
        ctx.state["last_pos"] = (x, y)

    def _stamp(self, ctx: ToolContext, cx: int, cy: int) -> None:
        md = ctx.map_data
        pm = md.province_map
        tm = md.tile_map
        pid = int(ctx.state.get("pid", 0) or 0)
        if pid <= 0:
            return

        target_tile = ctx.state.get("tile")
        if target_tile is None:
            target_tile = int(tm[cy, cx])
            ctx.state["tile"] = target_tile

        radius = max(0, int(ctx.brush_size) // 2)
        h, w = pm.shape
        x0, x1 = max(0, cx - radius), min(w, cx + radius + 1)
        y0, y1 = max(0, cy - radius), min(h, cy + radius + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disk = (yy - cy) ** 2 + (xx - cx) ** 2 <= radius * radius
        if radius < 2:
            disk[:] = True

        sub_pm = pm[y0:y1, x0:x1]
        sub_tm = tm[y0:y1, x0:x1]
        candidate = disk & (sub_tm == target_tile) & (sub_pm != pid)
        if not np.any(candidate):
            return

        # A province ID must remain a single connected shape.  Once the target
        # has pixels, accept only candidate components touching it.  Continuous
        # drag naturally grows the province; a distant click becomes a no-op.
        if ctx.state.get("has_pixels", False):
            from scipy.ndimage import binary_dilation, label

            selected_near = np.zeros_like(candidate)
            expanded_y0, expanded_y1 = max(0, y0 - 1), min(h, y1 + 1)
            expanded_x0, expanded_x1 = max(0, x0 - 1), min(w, x1 + 1)
            nearby = pm[expanded_y0:expanded_y1, expanded_x0:expanded_x1] == pid
            dilated = binary_dilation(nearby)
            oy, ox = y0 - expanded_y0, x0 - expanded_x0
            selected_near[:] = dilated[oy:oy + (y1 - y0), ox:ox + (x1 - x0)]
            if x0 == 0:
                selected_near[:, 0] |= pm[y0:y1, -1] == pid
            if x1 == w:
                selected_near[:, -1] |= pm[y0:y1, 0] == pid

            components, count = label(candidate)
            keep = np.zeros_like(candidate)
            for component in range(1, count + 1):
                part = components == component
                if np.any(part & selected_near):
                    keep |= part
            candidate = keep
            if not np.any(candidate):
                return

        touched = set(int(v) for v in np.unique(sub_pm[candidate]) if int(v) > 0)
        touched.discard(pid)
        ctx.state.setdefault("touched_pids", set()).update(touched)
        sub_pm[candidate] = pid
        ctx.state["is_new"] = False
        ctx.state["has_pixels"] = True
        self._expand_dirty_rect(ctx, x0, y0, x1, y1)

    def _fill_at(self, ctx: ToolContext, x: int, y: int) -> None:
        """Fill a connected unassigned region; merging has its own safe tool."""
        md = ctx.map_data
        pm = md.province_map
        tm = md.tile_map
        if int(pm[y, x]) != 0:
            return

        pid = int(ctx.state.get("pid", 0) or 0)
        target_tile = ctx.state.get("tile")
        clicked_tile = int(tm[y, x])
        if target_tile is None:
            target_tile = clicked_tile
            ctx.state["tile"] = target_tile
        if clicked_tile != target_tile:
            return

        from scipy.ndimage import label

        available = (pm == 0) & (tm == target_tile)
        regions, _ = label(available)
        region_id = int(regions[y, x])
        if region_id <= 0:
            return
        fill_mask = regions == region_id
        if ctx.state.get("has_pixels", False):
            from scipy.ndimage import binary_dilation

            target_mask = pm == pid
            adjacent = bool(np.any(binary_dilation(fill_mask) & target_mask))
            # Horizontal wrap is part of HOI4's map topology.
            adjacent = adjacent or bool(
                np.any(fill_mask[:, 0] & target_mask[:, -1])
                or np.any(fill_mask[:, -1] & target_mask[:, 0])
            )
            if not adjacent:
                return
        pm[fill_mask] = pid
        ctx.state["is_new"] = False
        ctx.state["has_pixels"] = True
        ys, xs = np.where(fill_mask)
        self._expand_dirty_rect(
            ctx, int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        )

    @staticmethod
    def _expand_dirty_rect(
        ctx: ToolContext, x0: int, y0: int, x1: int, y1: int
    ) -> None:
        if ctx.dirty_bbox is None:
            ctx.dirty_bbox = (x0, y0, x1, y1)
            return
        dx0, dy0, dx1, dy1 = ctx.dirty_bbox
        ctx.dirty_bbox = (
            min(dx0, x0), min(dy0, y0), max(dx1, x1), max(dy1, y1)
        )

    @staticmethod
    def _repair_touched_provinces(ctx: ToolContext) -> None:
        """Merge disconnected donor fragments into the target province."""
        from scipy.ndimage import label

        pm = ctx.map_data.province_map
        target = int(ctx.state.get("pid", 0) or 0)
        for pid in ctx.state.get("touched_pids", set()):
            mask = pm == pid
            if not np.any(mask):
                continue
            components, count = label(mask)
            if count <= 1:
                continue
            sizes = np.bincount(components.ravel())
            sizes[0] = 0
            keep = int(sizes.argmax())
            pm[(components > 0) & (components != keep)] = target

    @staticmethod
    def _fix_type_safe_x_crossings(ctx: ToolContext) -> int:
        """Remove four-ID corners without moving an ID across a tile type."""
        from domain.validators.province import detect_x_crossings

        pm = ctx.map_data.province_map
        tm = ctx.map_data.tile_map
        h, w = pm.shape
        if ctx.dirty_bbox is None:
            return 0
        dx0, dy0, dx1, dy1 = ctx.dirty_bbox
        x0, x1 = max(0, dx0 - 1), min(w, dx1 + 1)
        y0, y1 = max(0, dy0 - 1), min(h, dy1 + 1)
        sub_positions = detect_x_crossings(pm[y0:y1, x0:x1])
        positions = [(py + y0, px + x0) for py, px in sub_positions]

        # The map wraps horizontally.  A narrow dirty rectangle at either edge
        # cannot include both seam columns in one slice, so inspect that seam
        # explicitly for the affected rows.
        if (x0 == 0 or x1 == w) and (x1 - x0) < w:
            for py in range(y0, max(y0, y1 - 1)):
                values = (
                    int(pm[py, -1]), int(pm[py, 0]),
                    int(pm[py + 1, -1]), int(pm[py + 1, 0]),
                )
                if len(set(values)) == 4:
                    positions.append((py, w - 1))

        positions = list(dict.fromkeys(positions))
        for y, x in positions:
            right = 0 if x == w - 1 else x + 1
            coords = ((y, x), (y, right), (y + 1, x), (y + 1, right))
            by_type: dict[int, list[tuple[int, int]]] = {}
            for py, px in coords:
                by_type.setdefault(int(tm[py, px]), []).append((py, px))
            # Four pixels but only three tile types means at least one type is
            # repeated. Duplicate an ID within that type, preserving the
            # land/sea/lake contract of every painted province.
            same_type = max(by_type.values(), key=len)
            src_y, src_x = same_type[0]
            dst_y, dst_x = same_type[-1]
            pm[dst_y, dst_x] = pm[src_y, src_x]
        return len(positions)


from domain.tools.registry import register_tool

register_tool(ProvincePaintTool())
