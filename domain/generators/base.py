"""Generator unified protocol — the standard model for "auto-generated base + manual refinement" (Route C).

Convention (commonly followed by all layer generators, terrain/height/trees/city/tone are all implemented accordingly):

1. **Purely functional**: generate() read-only map_data, returns a new array of full size,
   Project data is never modified directly - writes are handled by the command layer and are guaranteed to be reversible.
2. **Parameterization + Seed**: The parameter is frozen dataclass, which comes with seed;
   The results can be reproduced with the same parameters and the same seed. "Change a batch" = change the seed and generate again.
3. **Optional mask**: When a bool mask is passed in, the pixels outside the mask remain unchanged on the original layer.
   (Partial regeneration/protection of manually refined areas).

Standard path to access the UI:
    generator.generate(map_data, params) → write command (such as
    commands/map/generate_terrain.GenerateTerrainCommand) →
    cmd_history.execute() → Undoable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class GeneratorParams:
    """Generator parameter base class — at least with seeds."""
    seed: int = 0


class Generator(Protocol):
    """Layer Builder Protocol."""

    id: str             # Globally unique, such as "terrain_detail"
    target_layer: str   # Which array attribute of MapData is written to, such as "terrain_map"

    def default_params(self) -> GeneratorParams:
        """Return default parameters (UI initial values)."""
        ...

    def generate(
        self,
        map_data,
        params: GeneratorParams,
        mask: np.ndarray | None = None,
    ) -> np.ndarray:
        """Produce a new layer array of full size, without modifying map_data."""
        ...
