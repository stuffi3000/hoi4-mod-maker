"""ExpandProvinceTool — Province expansion tool (two-step activation + brush expansion).

Workflow (2026-04-09 correction: only expand one circle at a time):
1. Click province A for the first time → select (yellow border + translucent allowed area overlay)
2. Click the same province A for the second time → enter expansion mode and start drawing
3. Press and drag → the pixel passed by the cursor is assigned to province A (limited to the current allowed_mask)
4. Release the mouse → **Exit expansion mode**, allowed_mask will no longer take effect
5. Want to continue to expand (eat the next circle of neighbors) → click province A twice again, new allowed_mask
   Will include "eat the second circle of neighbors exposed after the first circle"

Constraints:
- A single stroke can only expand to the **current** direct neighbor (neighborhood mask)
- After releasing, it must be reactivated to expand to the next circle to prevent the entire continent from being eaten up by one drag.
- Can only affect the same tile type (land provinces will not eat ocean pixels)
- The pixels of eaten neighbors are automatically reduced; the complete disappearance of neighbors will trigger ID compaction (when exporting)

For backward compatibility, the tool name is still called lasso_province (registered name)."""
from __future__ import annotations

import numpy as np

from domain.tools.base import Tool, ToolContext, CleanupLevel


# Expand brush radius (pixels). Fixed value, does not rely on global brush_size slider to avoid ambiguity.
EXPAND_RADIUS = 4


class LassoProvinceTool(Tool):
    name = "lasso_province"
    display_modes = ("province",)
    cleanup_level = CleanupLevel.FAST
    label = "Expand province"
    description = "Select a province, select it again to enter expand mode, then drag the brush along its boundary"
    cursor = "cross"

    def get_undo_array_names(self, ctx: ToolContext) -> list[str]:
        return ["province_map"]

    def on_press(self, ctx: ToolContext, x: int, y: int) -> None:
        md = ctx.map_data
        pid_under = int(md.province_map[y, x])
        if pid_under <= 0:
            return

        sel = ctx.state.get("pid", 0)

        # Case 1: Never selected / selected another province → first selection
        if pid_under != sel:
            ctx.state["pid"] = pid_under
            ctx.state["tile"] = md.get_province_tile_type(pid_under)
            ctx.state["allowed_mask"] = md.get_neighborhood_mask(pid_under)
            ctx.state["active"] = False  # Not in expansion mode yet
            ctx.state["painting"] = False
            ctx.selected_province_id = pid_under
            return

        # Case 2: The same province has been selected → enter expansion mode + draw the first stroke immediately
        if not ctx.state.get("active"):
            ctx.state["active"] = True
            ctx.state["painting"] = True
            self._paint_at(ctx, x, y)
            return

        # Case 3: Already in expansion mode → continue drawing
        ctx.state["painting"] = True
        self._paint_at(ctx, x, y)

    def on_drag(self, ctx: ToolContext, x: int, y: int) -> None:
        if not ctx.state.get("painting"):
            return
        self._paint_at(ctx, x, y)
        ctx.expand_dirty(x, y)

    def on_release(self, ctx: ToolContext, x: int, y: int) -> None:
        ctx.state["painting"] = False
        # Release to exit expansion mode (corrected on 2026-04-09):
        # The user must click again to expand to the next circle to avoid eating the entire continent with one drag.
        # The pid is retained, and the next time you click on the same province, go to Case 2 to reactivate, and get a new allowed_mask.
        ctx.state["active"] = False

    def on_cancel(self, ctx: ToolContext) -> None:
        ctx.state.clear()
        ctx.dirty_bbox = None
        ctx.selected_province_id = 0

    def run_cleanup(self, ctx: ToolContext) -> None:
        """Only partial X-crossing repair is performed, and the ID is not compacted (the holes are reserved for cutting and filling)."""
        super().run_cleanup(ctx)

    # ────── Brushes ──────

    def _paint_at(self, ctx: ToolContext, cx: int, cy: int) -> None:
        """Draw a brush seal around (cx, cy) and assign qualified pixels to the selected province."""
        md = ctx.map_data
        sel_pid = ctx.state.get("pid", 0)
        if sel_pid <= 0:
            return
        allowed: np.ndarray = ctx.state.get("allowed_mask")
        sel_tile = ctx.state.get("tile", 0)
        if allowed is None:
            return

        h, w = md.province_map.shape
        x0 = max(0, cx - EXPAND_RADIUS)
        y0 = max(0, cy - EXPAND_RADIUS)
        x1 = min(w, cx + EXPAND_RADIUS + 1)
        y1 = min(h, cy + EXPAND_RADIUS + 1)
        if x0 >= x1 or y0 >= y1:
            return

        sub_pm = md.province_map[y0:y1, x0:x1]
        sub_tm = md.tile_map[y0:y1, x0:x1]
        sub_allowed = allowed[y0:y1, x0:x1]

        mask = (
            sub_allowed
            & (sub_tm == sel_tile)
            & (sub_pm != sel_pid)
            & (sub_pm != 0)
        )
        sub_pm[mask] = sel_pid


from domain.tools.registry import register_tool
register_tool(LassoProvinceTool())
