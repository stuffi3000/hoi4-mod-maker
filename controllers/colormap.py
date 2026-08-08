"""ColormapController — 总览贴图设置控制器。

处理 colormap 颜色修改和重置。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class ColormapController(BaseController):
    """总览贴图颜色设置。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)

    def change_color(self, attr: str, r: int, g: int, b: int) -> None:
        """修改总览贴图某个颜色属性。"""
        from domain.managers.colormap_settings import ColormapColor

        color = ColormapColor(r, g, b)
        setattr(self.project.colormap_settings, attr, color)
        self.project.mark_dirty()
        self._emit_status(f"总览贴图 {attr} 颜色已更新 ({r},{g},{b})", f"Colormap {attr} color updated ({r},{g},{b})")

    def reset(self) -> None:
        """恢复总览贴图默认颜色。"""
        from domain.managers.colormap_settings import ColormapSettings

        self.project.colormap_settings = ColormapSettings.default()
        self.project.mark_dirty()
        self._emit_status("总览贴图颜色已恢复默认", "Colormap colors restored to defaults")
