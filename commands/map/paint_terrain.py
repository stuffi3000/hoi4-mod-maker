"""PaintTerrainCommand — Brushes for painting terrain + optional height automatic linkage.

Two modes are supported:
1. Brush mode: directly modify terrain_map pixels
2. Provincial mode: update the provincial_terrain dictionary at the same time"""

from __future__ import annotations

from commands.base import Command
from domain.map_data import MapData


class PaintTerrainCommand(Command):
    """The brush draws terrain_map pixels and can be linked to height_map."""

    label = "Paint terrain"

    def __init__(
        self,
        map_data: MapData,
        terrain_changes: dict[tuple[int, int], int],
        height_changes: dict[tuple[int, int], int] | None = None,
        provincial_terrain_changes: dict[int, str] | None = None,
    ) -> None:
        """Parameters:
            map_data: map data object
            terrain_changes: {(y, x): new_terrain_index}
            height_changes: {(y, x): new_height_value} Height linkage (optional)
            provincial_terrain_changes: {province_id: new_terrain_type} Provincial terrain (optional)"""
        self._map_data = map_data
        self._terrain_changes = dict(terrain_changes)
        self._height_changes = dict(height_changes) if height_changes else {}
        self._prov_terrain_changes = (
            dict(provincial_terrain_changes) if provincial_terrain_changes else {}
        )
        # old value storage
        self._old_terrain: dict[tuple[int, int], int] = {}
        self._old_height: dict[tuple[int, int], int] = {}
        self._old_prov_terrain: dict[int, str | None] = {}

    def execute(self) -> None:
        """Save old values and write new terrain/altitude."""
        terrain_map = self._map_data.terrain_map
        height_map = self._map_data.height_map

        for (y, x), new_val in self._terrain_changes.items():
            self._old_terrain[(y, x)] = int(terrain_map[y, x])
            terrain_map[y, x] = new_val

        for (y, x), new_val in self._height_changes.items():
            self._old_height[(y, x)] = int(height_map[y, x])
            height_map[y, x] = new_val

        prov_terrain = self._map_data.provincial_terrain
        for pid, new_type in self._prov_terrain_changes.items():
            self._old_prov_terrain[pid] = prov_terrain.get(pid)
            prov_terrain[pid] = new_type

    def undo(self) -> None:
        """Restore old terrain/elevation."""
        terrain_map = self._map_data.terrain_map
        height_map = self._map_data.height_map

        for (y, x), old_val in self._old_terrain.items():
            terrain_map[y, x] = old_val

        for (y, x), old_val in self._old_height.items():
            height_map[y, x] = old_val

        prov_terrain = self._map_data.provincial_terrain
        for pid, old_type in self._old_prov_terrain.items():
            if old_type is None:
                prov_terrain.pop(pid, None)
            else:
                prov_terrain[pid] = old_type
