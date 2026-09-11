"""ColormapController — Overview map settings controller.

Handles colormap color modification and reset."""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class ColormapController(BaseController):
    """Overview map color settings."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)

    def change_color(self, attr: str, r: int, g: int, b: int) -> None:
        """Modify a color attribute of the overview map."""
        from domain.managers.colormap_settings import ColormapColor

        color = ColormapColor(r, g, b)
        setattr(self.project.colormap_settings, attr, color)
        self.project.mark_dirty()
        self._emit_status(f"Colormap {attr} color updated ({r},{g},{b})")

    def reset(self) -> None:
        """Restore the default color of the overview map."""
        from domain.managers.colormap_settings import ColormapSettings

        self.project.colormap_settings = ColormapSettings.default()
        self.project.mark_dirty()
        self._emit_status("Colormap colors restored to defaults")
