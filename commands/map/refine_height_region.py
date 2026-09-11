"""RefineHeightRegionCommand — Locally refined height map (supports undo)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from commands.base import Command
from domain.map_data import MapData
from services.terrain_service import refine_heightmap_region


@dataclass(frozen=True)
class RefineParams:
    """Refinement parameters (passed into Command after collection in dialog box)."""
    strength: float = 0.5
    enable_ridge: bool = True
    enable_erosion: bool = True
    enable_noise: bool = False
    enable_shrink: bool = False
    shrink_distance: float = 25.0
    seed: int = 42
    # True = Regenerate realistic terrain from scratch in the selection (ignore the refinement switch above)
    regenerate: bool = False


class RefineHeightRegionCommand(Command):
    """Write the result of refine_heightmap_region into map_data, undo is supported."""

    label = "Refine regional height"

    def __init__(
        self,
        map_data: MapData,
        mask: np.ndarray,
        params: RefineParams,
    ) -> None:
        self._map_data = map_data
        self._mask = mask.copy()
        self._params = params
        self._old_heights: np.ndarray | None = None

    def execute(self) -> None:
        hm = self._map_data.height_map
        # Only back up the original value in mask (save memory)
        self._old_heights = hm[self._mask].copy()
        new_hm = refine_heightmap_region(
            height_map=hm,
            mask=self._mask,
            tile_map=self._map_data.tile_map,
            strength=self._params.strength,
            enable_ridge=self._params.enable_ridge,
            enable_erosion=self._params.enable_erosion,
            enable_noise=self._params.enable_noise,
            enable_shrink=self._params.enable_shrink,
            shrink_distance=self._params.shrink_distance,
            seed=self._params.seed,
            regenerate=self._params.regenerate,
        )
        # Write back the new value inside the mask (the outside of the mask is the same as the original image)
        hm[self._mask] = new_hm[self._mask]

    def undo(self) -> None:
        if self._old_heights is not None:
            self._map_data.height_map[self._mask] = self._old_heights
