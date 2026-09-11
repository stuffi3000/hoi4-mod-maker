"""default.map configuration.

HOI4 uses map/default.map to tell the engine where to find various map files + tree palette and other configurations.
Reference Reference/Map modding.txt §Default.map (lines 56-83).

Our tool automatically generates BMP/CSV files with vanilla standard filenames, without changing the path.
But users can customize:
- tree_palette_indices: which trees.bmp palette indices count as "trees"
- river_max_level: river maximum width level (default 5)
- max_provinces automatically = actual number of provinces + 1 (required for HOI4)"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DefaultMapSettings:
    """default.map configuration."""

    # Tree palette indices: trees.bmp These indices are counted as trees (default vanilla values)
    # Refer to Map modding.txt §Trees: 0=no tree, 1-13 are different densities/types
    tree_palette_indices: list[int] = field(default_factory=lambda: [3, 4, 7, 10])

    # Maximum river width (1-5, vanilla default 5)
    river_max_level: int = 5

    # These fields cannot be edited, and the vanilla file name is hard-coded (changed and cannot be found in HOI4)
    # But it is exposed in settings to facilitate future expansion.
    definitions: str = "definition.csv"
    provinces: str = "provinces.bmp"
    positions: str = "positions.txt"
    terrain: str = "terrain.bmp"
    rivers: str = "rivers.bmp"
    heightmap: str = "heightmap.bmp"
    tree_definition: str = "trees.bmp"
    continent: str = "continent.txt"
    adjacency_rules: str = "adjacency_rules.txt"
    adjacencies: str = "adjacencies.csv"
    ambient_object: str = "ambient_object.txt"
    seasons: str = "seasons.txt"

    @classmethod
    def default(cls) -> "DefaultMapSettings":
        return cls()

    def to_dict(self) -> dict:
        return {
            "tree_palette_indices": list(self.tree_palette_indices),
            "river_max_level": int(self.river_max_level),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DefaultMapSettings":
        return cls(
            tree_palette_indices=list(data.get("tree_palette_indices", [3, 4, 7, 10])),
            river_max_level=int(data.get("river_max_level", 5)),
        )
