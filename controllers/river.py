"""RiverController — 河流编辑模式控制器。

处理河流画笔绘制。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController
from commands.map.paint_river import PaintRiverCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class RiverController(BaseController):
    """河流编辑模式：画笔绘制河流。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_river_type: int = 3  # 默认河流类型
        self.brush_size: int = 1
        self._stroke_changes: dict[tuple[int, int], int] = {}
        self._is_painting: bool = False

    def activate(self) -> None:
        """进入河流模式。"""
        self._stroke_changes.clear()
        self._is_painting = False
        self._emit_status("河流编辑模式", "River editing mode")

    def deactivate(self) -> None:
        """离开河流模式，结束未完成笔触。"""
        if self._is_painting:
            self._commit_stroke()

    def on_press(self, x: int, y: int, pid: int, button: str, modifiers: set) -> bool:
        """鼠标按下开始绘制。"""
        if button != "left":
            return False
        self._is_painting = True
        self._stroke_changes.clear()
        self._apply_brush(x, y)
        return True

    def on_drag(self, x: int, y: int) -> bool:
        """鼠标拖拽继续绘制。"""
        if not self._is_painting:
            return False
        self._apply_brush(x, y)
        return True

    def on_release(self, x: int, y: int) -> bool:
        """鼠标释放结束笔触。"""
        if not self._is_painting:
            return False
        self._commit_stroke()
        return True

    def _apply_brush(self, x: int, y: int) -> None:
        """在 (x, y) 处应用河流画笔。"""
        river_map = self.project.map_data.river_map
        h, w = river_map.shape
        r = self.brush_size // 2

        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w:
                    if int(river_map[ny, nx]) != self.current_river_type:
                        self._stroke_changes[(ny, nx)] = self.current_river_type

    def _commit_stroke(self) -> None:
        """提交河流笔触。"""
        self._is_painting = False
        if self._stroke_changes:
            cmd = PaintRiverCommand(self.project.map_data, self._stroke_changes)
            self.history.execute(cmd)
            self._stroke_changes = {}
            self.project.mark_dirty()
            self._emit_render(full=True)
