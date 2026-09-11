"""DefaultMapController — default.map configuration controller.

Handle river class and tree palette index configuration."""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class DefaultMapController(BaseController):
    """default.map configuration editor."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)

    def set_river_level(self, level: int) -> None:
        """Set the maximum level of the river."""
        self.project.default_map_settings.river_max_level = level
        self.project.mark_dirty()

    def add_tree_index(self, index: int) -> bool:
        """Added tree palette index. Return whether successful."""
        settings = self.project.default_map_settings
        if index in settings.tree_palette_indices:
            return False
        settings.tree_palette_indices.append(index)
        settings.tree_palette_indices.sort()
        self.project.mark_dirty()
        return True

    def remove_tree_index(self, position: int) -> bool:
        """Remove tree palette index by position."""
        settings = self.project.default_map_settings
        if 0 <= position < len(settings.tree_palette_indices):
            settings.tree_palette_indices.pop(position)
            self.project.mark_dirty()
            return True
        return False

    def reset_tree_indices(self) -> None:
        """Resets the tree palette index to default."""
        self.project.default_map_settings.tree_palette_indices = [3, 4, 7, 10]
        self.project.mark_dirty()
