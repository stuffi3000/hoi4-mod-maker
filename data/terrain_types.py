"""HOI4 provincial and graphical terrain definitions."""
from typing import NamedTuple


class TerrainType(NamedTuple):
    """A provincial terrain type and its map-generation defaults."""

    name: str
    name_en: str
    color: tuple[int, int, int]
    height_base: int
    tree_density: int


TERRAIN_TYPES = {
    "ocean": TerrainType("ocean", "Ocean", (0, 0, 255), 40, 255),
    "lakes": TerrainType("lakes", "Lakes", (0, 255, 255), 90, 255),
    "plains": TerrainType("plains", "Plains", (255, 129, 66), 120, 230),
    "forest": TerrainType("forest", "Forest", (89, 199, 85), 130, 60),
    "hills": TerrainType("hills", "Hills", (248, 255, 153), 160, 200),
    "mountain": TerrainType("mountain", "Mountain", (124, 135, 125), 220, 240),
    "desert": TerrainType("desert", "Desert", (255, 63, 0), 110, 255),
    "marsh": TerrainType("marsh", "Marsh", (76, 96, 35), 100, 120),
    "jungle": TerrainType("jungle", "Jungle", (127, 191, 0), 125, 30),
    "urban": TerrainType("urban", "Urban", (128, 128, 128), 125, 255),
}


# Palette indices must match the color values in vanilla common/terrain/00_terrain.txt.
TERRAIN_PALETTE_INDEX = {
    "ocean": 15,
    "lakes": 14,
    "plains": 0,
    "forest": 1,
    "hills": 17,
    "mountain": 11,
    "desert": 3,
    "marsh": 9,
    "jungle": 21,
    "urban": 13,
}


DEFAULT_TERRAIN_FOR_TILE = {
    0: "ocean",   # Undefined tile
    1: "plains",  # Land tile
    2: "ocean",   # Sea tile
    3: "lakes",   # Lake tile
}


STATE_CATEGORIES = [
    "wasteland",
    "pastoral",
    "tiny",
    "small",
    "town",
    "large_town",
    "city",
    "large_city",
    "megalopolis",
]


RIVER_COLORS = {
    "source": (255, 0, 0),
    "flow_marker": (0, 255, 0),
    "fork": (255, 252, 0),
    "merge_start": (0, 200, 0),
    "merge_end": (0, 100, 0),
    "background": (255, 255, 255),
}

RIVER_WIDTH_NARROW = 255
RIVER_WIDTH_WIDE = 1


class GraphicalTerrain(NamedTuple):
    """A graphical terrain entry from vanilla ``00_terrain.txt``."""

    id: str
    type: str
    palette_index: int
    texture: int
    name_en: str
    perm_snow: bool
    spawn_city: bool


GRAPHICAL_TERRAINS: list[GraphicalTerrain] = [
    GraphicalTerrain("terrain_0", "plains", 0, 1, "Plains", False, False),
    GraphicalTerrain("terrain_1", "forest", 1, 4, "Forest", False, False),
    GraphicalTerrain("desert_mountain", "hills", 2, 3, "Desert Hills", False, False),
    GraphicalTerrain("desert", "desert", 3, 9, "Desert", False, False),
    GraphicalTerrain("terrain_4", "forest", 4, 5, "Forest (Variant)", False, False),
    GraphicalTerrain("terrain_5", "plains", 5, 0, "Plains (Variant)", False, False),
    GraphicalTerrain("terrain_6", "mountain", 6, 11, "Mountain", False, False),
    GraphicalTerrain("terrain_7", "desert", 7, 12, "Desert (Variant)", False, False),
    GraphicalTerrain("desert_hills", "desert", 8, 14, "Desert Hills", False, False),
    GraphicalTerrain("terrain_9", "marsh", 9, 6, "Marsh", False, False),
    GraphicalTerrain("terrain_10", "mountain", 10, 13, "Mountain (Variant)", False, False),
    GraphicalTerrain("desert_mountain_11", "mountain", 11, 11, "Desert Mountain", False, False),
    GraphicalTerrain("desert_12", "desert", 12, 8, "Desert (Rocky)", False, False),
    GraphicalTerrain("forest_13", "urban", 13, 10, "Urban", False, True),
    GraphicalTerrain("forest_14", "lakes", 14, 255, "Lakes", False, False),
    GraphicalTerrain("ocean_15", "ocean", 15, 9, "Ocean", False, False),
    GraphicalTerrain("snow_16", "mountain", 16, 11, "Snowy Mountain", True, False),
    GraphicalTerrain("hills_blend", "hills", 17, 2, "Hills", False, False),
    GraphicalTerrain("mountain_variation_sand", "mountain", 18, 7, "Sandy Mountain", False, False),
    GraphicalTerrain("plains_snow", "plains", 19, 0, "Snowy Plains", True, False),
    GraphicalTerrain("mountain_variation_grass", "mountain", 20, 7, "Grassy Mountain", False, False),
    GraphicalTerrain("jungle_18", "jungle", 21, 4, "Jungle", False, False),
    GraphicalTerrain("jungle_blend_18", "jungle", 22, 5, "Jungle (Variant)", False, False),
    GraphicalTerrain("jungle_mountain", "mountain", 27, 7, "Jungle Mountain", False, False),
    GraphicalTerrain("desert_mountain_tops", "mountain", 31, 15, "Desert Mountain Tops", False, False),
]


GRAPHICAL_TERRAIN_BY_INDEX: dict[int, GraphicalTerrain] = {
    terrain.palette_index: terrain for terrain in GRAPHICAL_TERRAINS
}

PALETTE_TO_TYPE: dict[int, str] = {
    terrain.palette_index: terrain.type for terrain in GRAPHICAL_TERRAINS
}

PAINTABLE_GROUPS: dict[str, list[GraphicalTerrain]] = {}
for _terrain in GRAPHICAL_TERRAINS:
    if _terrain.type not in ("ocean", "lakes"):
        PAINTABLE_GROUPS.setdefault(_terrain.type, []).append(_terrain)


def terrain_display_name(terrain: TerrainType) -> str:
    """Return the English display name for a provincial terrain type."""
    return terrain.name_en


def graphical_terrain_display_name(terrain: GraphicalTerrain) -> str:
    """Return the translated display name for a graphical terrain entry."""
    from ui.i18n import tr

    return tr(f"gt_{terrain.id}")
