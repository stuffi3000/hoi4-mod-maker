"""Undoable command for applying generated visual and provincial terrain."""

from __future__ import annotations

import numpy as np

from commands.base import Command
from domain.map_data import MapData


class GenerateTerrainCommand(Command):
    """Apply generated terrain while preserving complete undo information."""

    label = "Generate terrain"

    def __init__(
        self,
        map_data: MapData,
        new_terrain: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> None:
        """Capture either a masked update or a replacement of the whole terrain layer."""
        self._map_data = map_data
        self._mask = mask

        if mask is not None:
            # Store only the selected coordinates when generation is masked.
            coords = np.argwhere(mask)
            self._coords = coords
            self._new_values = new_terrain[mask].copy()
            self._old_values = map_data.terrain_map[mask].copy()
        else:
            # Keep full snapshots when the entire terrain layer is replaced.
            self._coords = None
            self._new_terrain = new_terrain.copy()
            self._old_terrain = map_data.terrain_map.copy()

        # Provincial terrain is inferred from the new visual terrain on execution.
        self._old_provincial = dict(map_data.provincial_terrain)
        self._new_provincial = self._compute_merged_provincial(
            map_data, new_terrain
        )

    def _compute_merged_provincial(
        self, map_data: MapData, new_terrain: np.ndarray,
    ) -> dict[int, str]:
        """Infer missing provincial terrain values from the generated bitmap."""
        try:
            from services.terrain_service import compute_provincial_terrain_from_bmp

            inferred = compute_provincial_terrain_from_bmp(
                new_terrain, map_data.province_map, map_data.tile_map,
            )
        except Exception:
            return dict(map_data.provincial_terrain)

        merged = dict(map_data.provincial_terrain)
        # Do not overwrite provincial terrain that the user already selected.
        for pid, terr in inferred.items():
            if pid not in merged:
                merged[pid] = terr
        return merged

    def execute(self) -> None:
        """Apply the generated terrain and its inferred provincial assignments."""
        if self._coords is not None:
            # Apply only pixels selected by the generation mask.
            for i, (y, x) in enumerate(self._coords):
                self._map_data.terrain_map[y, x] = self._new_values[i]
        else:
            # Replace the complete terrain layer from the saved snapshot.
            self._map_data.terrain_map[:] = self._new_terrain

        self._map_data.provincial_terrain.clear()
        self._map_data.provincial_terrain.update(self._new_provincial)

    def undo(self) -> None:
        """Restore the previous visual and provincial terrain layers."""
        if self._coords is not None:
            for i, (y, x) in enumerate(self._coords):
                self._map_data.terrain_map[y, x] = self._old_values[i]
        else:
            self._map_data.terrain_map[:] = self._old_terrain

        self._map_data.provincial_terrain.clear()
        self._map_data.provincial_terrain.update(self._old_provincial)
