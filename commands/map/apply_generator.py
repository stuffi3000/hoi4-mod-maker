"""ApplyGeneratorCommand — Generic undoable writing of generator outputs.

Any generator that conforms to the domain/generators/base.py protocol has its results passed through this command
The target layer to which MapData is written (terrain exception: it is synchronized with provincial_terrain,
Continue GenerateTerrainCommand).

The snapshot strategy is consistent with GenerateTerrainCommand: save the entire old layer in the entire image,
Mask mode only stores pixels within the mask. Write in place ([:] / mask assignment), keep canvas
Alias references to the same array are valid."""

from __future__ import annotations

import numpy as np

from commands.base import Command


class ApplyGeneratorCommand(Command):
    """Writes the generator's new layer array to MapData, undoable."""

    label = "Apply generator"

    def __init__(
        self,
        map_data,
        target_layer: str,
        new_array: np.ndarray,
        mask: np.ndarray | None = None,
        label: str | None = None,
    ) -> None:
        """Parameters:
            map_data: map data object
            target_layer: the name of the layer attribute to be written (such as "height_map");
                          If it does not exist, an AttributeError will be raised directly — intentionally not revealing,
                          Wrong names must be blown up on the spot rather than silently taking effect.
            new_array: the full size new array produced by the generator
            mask: bool mask, only write within the mask (None = full image)
            label: display name in undo history"""
        if label:
            self.label = label
        self._map_data = map_data
        self._target_layer = target_layer
        self._mask = mask

        current = getattr(map_data, target_layer)
        if mask is not None:
            self._new_values = new_array[mask].copy()
            self._old_values = current[mask].copy()
        else:
            self._new_array = new_array.copy()
            self._old_array = current.copy()

    def execute(self) -> None:
        arr = getattr(self._map_data, self._target_layer)
        if self._mask is not None:
            arr[self._mask] = self._new_values
        else:
            arr[:] = self._new_array

    def undo(self) -> None:
        arr = getattr(self._map_data, self._target_layer)
        if self._mask is not None:
            arr[self._mask] = self._old_values
        else:
            arr[:] = self._old_array
