"""Tool base class + ToolContext + CleanupLevel enumeration"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from domain.map_data import MapData
    from domain.undo_manager import UndoManager


class CleanupLevel(Enum):
    """The level of cleanup to be done after the tool completes an operation.

    - NONE: No cleaning is done (real-time operation during dragging)
    - FAST: Only make light repairs in the affected bbox (X-crossing partial repair)
    - FULL: Full image cleaning (X-crossing repair + disconnection repair + ID compaction)

    General rules:
    - Dragging → NONE
    - End of single step operation (release) → FAST
    - Before export/manual trigger → FULL"""
    NONE = "none"
    FAST = "fast"
    FULL = "full"


@dataclass
class ToolContext:
    """The shared context in which the tool operates.

    The tool does not directly access canvas/main_window, all required objects are obtained through ctx.
    canvas is constructed and passed in ctx when calling the tool."""
    map_data: "MapData"
    undo_mgr: "UndoManager"

    # Reference to the manager required for update (synchronize the province reference of state/country when compacting the ID)
    state_mgr: object = None
    country_mgr: object = None

    # Currently selected state (shared by multiple tools)
    selected_province_id: int = 0
    selected_state_id: int = 0
    selected_country_tag: str = ""

    # Metadata for the current operation
    brush_size: int = 10
    display_mode: str = "land"

    # Temporary data used by tool state machines (each tool’s own push/pop)
    state: dict[str, Any] = field(default_factory=dict)

    # Mark the bbox affected by this operation (for FAST cleaning)
    dirty_bbox: tuple[int, int, int, int] | None = None  # (x0, y0, x1, y1)

    def expand_dirty(self, x: int, y: int) -> None:
        """Add (x, y) to the affected range."""
        if self.dirty_bbox is None:
            self.dirty_bbox = (x, y, x + 1, y + 1)
        else:
            x0, y0, x1, y1 = self.dirty_bbox
            self.dirty_bbox = (
                min(x0, x), min(y0, y),
                max(x1, x + 1), max(y1, y + 1),
            )


class Tool:
    """Base class for all editing tools.

    Subclasses must set class attributes:
        name: unique identifier ("lasso_province", "land_brush"...)
        display_modes: under which display_modes are activated (["province"])
        cleanup_level: Cleanup level after the operation is completed

    Optional implementation:
        on_press/on_drag/on_release
        get_undo_array_names: which numpy arrays this tool affects"""

    name: str = ""
    display_modes: tuple[str, ...] = ()
    cleanup_level: CleanupLevel = CleanupLevel.NONE
    cursor: str = "cross"
    label: str = ""  # Button display text
    description: str = ""  # Status bar prompt

    def get_undo_array_names(self, ctx: ToolContext) -> list[str]:
        """Which arrays this tool affects. Default empty - must be specified by subclass."""
        return []

    def on_press(self, ctx: ToolContext, x: int, y: int) -> None:
        """Mouse pressed."""
        pass

    def on_drag(self, ctx: ToolContext, x: int, y: int) -> None:
        """Mouse drag (move after pressing)."""
        pass

    def on_release(self, ctx: ToolContext, x: int, y: int) -> None:
        """Release the mouse. Subclasses do not need to adjust the cleanup function - the framework will automatically adjust it based on cleanup_level."""
        pass

    def on_cancel(self, ctx: ToolContext) -> None:
        """The operation was canceled (ESC or tool switch)."""
        ctx.state.clear()
        ctx.dirty_bbox = None

    # ───── Framework helper methods ─────

    def begin_undo(self, ctx: ToolContext) -> None:
        """Start recording undo snapshot. The framework will be called before on_press."""
        names = self.get_undo_array_names(ctx)
        if not names:
            return
        arrays = {n: getattr(ctx.map_data, n) for n in names}
        ctx.undo_mgr.begin_stroke(self.name, arrays)

    def end_undo(self, ctx: ToolContext) -> None:
        """End the undo snapshot and push it onto the stack. The framework will be called after cleanup."""
        names = self.get_undo_array_names(ctx)
        if not names:
            return
        arrays = {n: getattr(ctx.map_data, n) for n in names}
        ctx.undo_mgr.end_stroke(arrays)

    def run_cleanup(self, ctx: ToolContext) -> None:
        """Perform cleanup based on cleanup_level. The framework is automatically adjusted after on_release."""
        if self.cleanup_level == CleanupLevel.NONE:
            return
        if self.cleanup_level == CleanupLevel.FULL:
            from domain.generators.province import _fix_non_contiguous_fast
            from domain.validators.province import fix_x_crossings
            for _ in range(5):
                if fix_x_crossings(ctx.map_data.province_map) == 0:
                    break
            _fix_non_contiguous_fast(ctx.map_data.province_map)
            # No compaction of ID - retain holes for cutting and filling, automatically processed during export
        elif self.cleanup_level == CleanupLevel.FAST:
            # Fix X-crossing only in dirty_bbox
            from domain.validators.province import fix_x_crossings
            if ctx.dirty_bbox is None:
                return
            x0, y0, x1, y1 = ctx.dirty_bbox
            # Leave 2 pixels margin to prevent edge detection
            from data.constants import MAP_WIDTH, MAP_HEIGHT
            x0 = max(0, x0 - 2); y0 = max(0, y0 - 2)
            x1 = min(MAP_WIDTH, x1 + 2); y1 = min(MAP_HEIGHT, y1 + 2)
            sub = ctx.map_data.province_map[y0:y1, x0:x1]
            for _ in range(3):
                if fix_x_crossings(sub) == 0:
                    break
