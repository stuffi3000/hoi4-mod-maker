"""Base controller shared by the editor modes."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from commands.history import CommandHistory
    from model.project import Project


class BaseController:
    """Common controller behavior for editor modes."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        self.project = project
        self.history = command_history
        self.event_bus = project.event_bus

    def activate(self) -> None:
        """Called when the mode becomes active."""
        pass

    def deactivate(self) -> None:
        """Called when the mode becomes inactive."""
        pass

    def on_press(self, x: int, y: int, pid: int, button: str, modifiers: set) -> bool:
        """Handle a mouse press and return whether it was consumed."""
        return False

    def on_drag(self, x: int, y: int) -> bool:
        """Handle a mouse drag and return whether it was consumed."""
        return False

    def on_release(self, x: int, y: int) -> bool:
        """Handle a mouse release and return whether it was consumed."""
        return False

    def on_province_clicked(self, pid: int) -> None:
        """Handle a primary-click on a province."""
        pass

    def on_province_double_clicked(self, pid: int) -> None:
        """Handle a double-click on a province."""
        pass

    def on_province_right_clicked(self, pid: int, x: int, y: int) -> None:
        """Handle a secondary-click on a province."""
        pass

    def _emit_status(self, text: str) -> None:
        """Publish an English status-bar message."""
        self.event_bus.emit("status_message", text=text)

    def _emit_render(self, full: bool = False, bbox: tuple | None = None) -> None:
        """Request a canvas refresh."""
        self.event_bus.emit("request_render", full=full, bbox=bbox)

    def _invalidate_art_assets(self, *rel_paths: str) -> None:
        """Mark generated art assets for regeneration during export."""
        self.project.mark_assets_dirty(*rel_paths)
