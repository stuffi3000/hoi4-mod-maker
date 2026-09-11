"""CSV/Text file writer — generates definition.csv and other map configuration files"""
import os
import numpy as np

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_SEA, TILE_LAKE,
    TILE_TYPE_NAMES,
    DEFAULT_MOD_NAME, DEFAULT_MOD_VERSION,
)
from data.terrain_types import DEFAULT_TERRAIN_FOR_TILE
from domain.validators.province import get_coastal_provinces
from domain.generators.province import generate_province_colors

_FALLBACK_SEASONS = """
winter = { start_date=00.12.01 end_date=00.02.10
    hsv_north={ 0 0.1 1 } colorbalance_north={ 0.9 0.9 1 }
    hsv_center={ 0.0 1.0 1.0 } colorbalance_center={ 1.0 1.0 1.0 }
    hsv_south={ 0.0 1.0 1.0 } colorbalance_south={ 1.0 1.0 1.0 }
}
spring = { start_date=00.03.10 end_date=00.04.22
    hsv_north={ 0 0.1 1 } colorbalance_north={ 0.9 0.9 1 }
    hsv_center={ 0.0 1.0 1.0 } colorbalance_center={ 1.0 1.0 1.0 }
    hsv_south={ 0.0 1.0 1.0 } colorbalance_south={ 1.0 1.0 1.0 }
}
summer = { start_date=00.05.20 end_date=00.09.10
    hsv_north={ 0 0.1 1 } colorbalance_north={ 0.9 0.9 1 }
    hsv_center={ 0.0 1.0 1.0 } colorbalance_center={ 1.0 1.0 1.0 }
    hsv_south={ 0.0 1.0 1.0 } colorbalance_south={ 1.0 1.0 1.0 }
}
autumn = { start_date=00.10.10 end_date=00.10.31
    hsv_north={ 0 0.1 1 } colorbalance_north={ 0.9 0.9 1 }
    hsv_center={ 0.0 1.0 1.0 } colorbalance_center={ 1.0 1.0 1.0 }
    hsv_south={ 0.0 1.0 1.0 } colorbalance_south={ 1.0 1.0 1.0 }
}
"""


def write_definition_csv(
    province_map: np.ndarray,
    tile_map: np.ndarray,
    output_dir: str,
    colors: dict[int, tuple[int, int, int]] | None = None,
    continent_mgr=None,
    terrain_map: np.ndarray | None = None,
) -> None:
    """Generate definition.csv file.

    Format: Province ID; R; G; B; Type; Coastal; Terrain; Continent ID"""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    province_count = int(province_map.max())

    if colors is None:
        colors = generate_province_colors(province_count)

    # Get the collection of coastal provinces
    coastal_set = get_coastal_provinces(tile_map, province_map)

    # Determine the type of each province
    province_types = _get_province_types(province_map, tile_map)

    file_path = os.path.join(map_dir, "definition.csv")
    with open(file_path, "w", encoding="utf-8") as f:
        # The first line: ID=0 special line (HOI4 requirement, no header)
        f.write("0;0;0;0;sea;false;ocean;0\n")

        for pid in range(1, province_count + 1):
            r, g, b = colors.get(pid, (1, 1, 1))
            ptype = province_types.get(pid, "land")

            # coastal state
            is_coastal = "true" if pid in coastal_set else "false"
            # Ocean and lake provinces are not marked as coastal
            if ptype in ("sea", "lake"):
                is_coastal = "false"

            # Terrain: First check the actual graphical terrain type from terrain_map
            terrain = _resolve_terrain(ptype, pid, province_map, terrain_map)

            # Continent ID: ocean/lake=0, land is assigned according to continent_mgr (if not assigned, it returns to continent No. 1)
            is_land = ptype not in ("sea", "lake")
            if continent_mgr is not None:
                continent = continent_mgr.get_province_continent_hoi4_id(pid, is_land)
            else:
                continent = 0 if not is_land else 1

            f.write(f"{pid};{r};{g};{b};{ptype};{is_coastal};{terrain};{continent}\n")


def _get_province_types(
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> dict[int, str]:
    """Determine the type of each province (land/sea/lake).
    Determined based on the majority of land types in the province."""
    province_count = int(province_map.max())
    types = {}

    for pid in range(1, province_count + 1):
        mask = province_map == pid
        if not np.any(mask):
            types[pid] = "land"
            continue

        tiles = tile_map[mask]
        land_count = int(np.sum(tiles == TILE_LAND))
        sea_count = int(np.sum(tiles == TILE_SEA))
        lake_count = int(np.sum(tiles == TILE_LAKE))

        if sea_count >= land_count and sea_count >= lake_count:
            types[pid] = "sea"
        elif lake_count >= land_count:
            types[pid] = "lake"
        else:
            types[pid] = "land"

    return types


def _default_terrain(province_type: str) -> str:
    """Get the default terrain corresponding to the province type"""
    if province_type == "sea":
        return "ocean"
    elif province_type == "lake":
        return "lakes"
    else:
        return "plains"


def _resolve_terrain(
    ptype: str,
    pid: int,
    province_map: np.ndarray,
    terrain_map: np.ndarray | None,
) -> str:
    """Parse the province's provincial terrain type from terrain_map."""
    # Sea/Lake Mandatory
    if ptype == "sea":
        return "ocean"
    if ptype == "lake":
        return "lakes"

    if terrain_map is None:
        return "plains"

    from data.terrain_types import PALETTE_TO_TYPE

    # Get the mode of terrain_map in the province area (the index with the largest number)
    mask = province_map == pid
    indices = terrain_map[mask]
    if indices.size == 0:
        return "plains"

    counts = np.bincount(indices)
    dominant_index = int(counts.argmax())
    return PALETTE_TO_TYPE.get(dominant_index, "plains")


def write_adjacencies_csv(output_dir: str) -> None:
    """Generates an empty adjacencies.csv (only header and trailing semicolon lines)"""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    file_path = os.path.join(map_dir, "adjacencies.csv")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("From;To;Type;Through;start_x;start_y;stop_x;stop_y;adjacency_rule_name;Comment\n")
        f.write(";;;;;;;;;\n")


def write_default_map(
    output_dir: str,
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> None:
    """Generate default.map file."""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    province_count = int(province_map.max())

    # Collect ocean province IDs
    sea_ids = []
    lake_ids = []
    province_types = _get_province_types(province_map, tile_map)
    for pid, ptype in province_types.items():
        if ptype == "sea":
            sea_ids.append(pid)
        elif ptype == "lake":
            lake_ids.append(pid)

    file_path = os.path.join(map_dir, "default.map")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write('definitions = "definition.csv"\n')
        f.write('provinces = "provinces.bmp"\n')
        f.write('positions = "positions.txt"\n')
        f.write('terrain = "terrain.bmp"\n')
        f.write('rivers = "rivers.bmp"\n')
        f.write('heightmap = "heightmap.bmp"\n')
        f.write('tree_definition = "trees.bmp"\n')
        f.write('continent = "continent.txt"\n')
        f.write('adjacency_rules = "adjacency_rules.txt"\n')
        f.write('adjacencies = "adjacencies.csv"\n')
        f.write('ambient_object = "ambient_object.txt"\n')
        f.write('seasons = "seasons.txt"\n')
        f.write('\ntree = { 3 4 7 10 }\n')


def write_continent_txt(output_dir: str) -> None:
    """Generate continent.txt"""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    file_path = os.path.join(map_dir, "continent.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("continents = {\n")
        f.write("\tfantasy_continent\n")
        f.write("}\n")


def write_empty_files(output_dir: str) -> None:
    """Generate a file that must exist but can be empty"""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    # positions.txt — empty file
    with open(os.path.join(map_dir, "positions.txt"), "w", encoding="utf-8") as f:
        pass

    # adjacency_rules.txt — empty file
    with open(os.path.join(map_dir, "adjacency_rules.txt"), "w", encoding="utf-8") as f:
        pass

    # ambient_object.txt — generated separately by ambient_object writer, not covered here

    # seasons.txt — copy from the original, or write the minimum available content if not available
    vanilla_seasons = os.path.join(
        "G:/SteamLibrary/steamapps/common/Hearts of Iron IV/map/seasons.txt"
    )
    if os.path.exists(vanilla_seasons):
        import shutil
        shutil.copy2(vanilla_seasons, os.path.join(map_dir, "seasons.txt"))
    else:
        with open(os.path.join(map_dir, "seasons.txt"), "w", encoding="utf-8") as f:
            f.write(_FALLBACK_SEASONS)

    # weatherpositions.txt — empty file
    with open(os.path.join(map_dir, "weatherpositions.txt"), "w", encoding="utf-8") as f:
        pass

    # unitstacks.txt — empty file
    with open(os.path.join(map_dir, "unitstacks.txt"), "w", encoding="utf-8") as f:
        pass

    # rocket_sites.txt — empty file
    with open(os.path.join(map_dir, "rocket_sites.txt"), "w", encoding="utf-8") as f:
        pass


def write_supply_files(output_dir: str, first_land_province: int) -> None:
    """Generate supply_nodes.txt and railways.txt (minimum usable version).
    At least one node and one railway are required, otherwise the game crashes."""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    # supply_nodes.txt — at least one level 1 node
    with open(os.path.join(map_dir, "supply_nodes.txt"), "w", encoding="utf-8") as f:
        f.write(f"1 {first_land_province}\n")

    # railways.txt — at least one class 1 railway
    # Format: Level Number of provinces Province ID1 Province ID2...
    # At least two provinces are required, and the same province is used here (minimum available)
    with open(os.path.join(map_dir, "railways.txt"), "w", encoding="utf-8") as f:
        f.write(f"1 2 {first_land_province} {first_land_province}\n")


def write_buildings_txt(output_dir: str, first_land_province: int) -> None:
    """Generate buildings.txt (minimum usable version)."""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    with open(os.path.join(map_dir, "buildings.txt"), "w", encoding="utf-8") as f:
        # StateID;Building type;X;Y;Z;Rotation;Adjacent sea province ID
        # Note: infrastructure is not a 3D building and cannot appear in buildings.txt; use bunker to occupy the space
        f.write(f"1;bunker;100.0;10.0;100.0;0.0;0\n")


def write_strategic_region(
    output_dir: str,
    province_ids: list[int],
) -> None:
    """Generate a strategic region containing all provinces"""
    sr_dir = os.path.join(output_dir, "map", "strategicregions")
    os.makedirs(sr_dir, exist_ok=True)

    file_path = os.path.join(sr_dir, "1-fantasy_region.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("strategic_region = {\n")
        f.write("    id = 1\n")
        f.write('    name = "STRATEGICREGION_WT_1"\n')
        f.write("    provinces = {\n")
        # Maximum 20 IDs per row
        for i in range(0, len(province_ids), 20):
            chunk = province_ids[i:i + 20]
            f.write("        " + " ".join(str(x) for x in chunk) + "\n")
        f.write("    }\n")
        f.write("    weather = {\n")
        f.write("        period = {\n")
        f.write("            between = { 0.0 30.0 }\n")
        f.write("            temperature = { -5.0 25.0 }\n")
        f.write("            no_phenomenon = 0.500\n")
        f.write("            rain_light = 0.200\n")
        f.write("            rain_heavy = 0.100\n")
        f.write("            mud = 0.050\n")
        f.write("            blizzard = 0.050\n")
        f.write("            sandstorm = 0.000\n")
        f.write("            snow = 0.100\n")
        f.write("        }\n")
        f.write("    }\n")
        f.write("}\n")


def write_state_file(
    output_dir: str,
    state_id: int,
    province_ids: list[int],
    owner_tag: str = "AAA",
    manpower: int = 100000,
) -> None:
    """Generate a State file"""
    states_dir = os.path.join(output_dir, "history", "states")
    os.makedirs(states_dir, exist_ok=True)

    file_path = os.path.join(states_dir, f"{state_id}-STATE_{state_id}.txt")
    first_province = province_ids[0] if province_ids else 1

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("state = {\n")
        f.write(f"    id = {state_id}\n")
        f.write(f'    name = "STATE_WT_{state_id}"\n')
        f.write(f"    manpower = {manpower}\n")
        f.write("    state_category = town\n\n")
        f.write("    history = {\n")
        f.write(f'        owner = {owner_tag}\n')
        f.write("        buildings = {\n")
        f.write("            infrastructure = 1\n")
        f.write("        }\n")
        f.write("        victory_points = {\n")
        f.write(f"            {first_province} 1\n")
        f.write("        }\n")
        f.write("    }\n\n")
        f.write("    provinces = {\n")
        f.write("        " + " ".join(str(x) for x in province_ids) + "\n")
        f.write("    }\n")
        f.write("}\n")


def write_country_files(output_dir: str, tag: str = "AAA") -> None:
    """Generate the smallest usable country definition file"""
    # country_tags
    tags_dir = os.path.join(output_dir, "common", "country_tags")
    os.makedirs(tags_dir, exist_ok=True)
    # Use 02_worldtest_ prefix to avoid overwriting vanilla 00_countries.txt (country_tags no longer replaces)
    with open(os.path.join(tags_dir, "02_worldtest_countries.txt"), "w", encoding="utf-8") as f:
        f.write(f'{tag} = "countries/{tag}.txt"\n')

    # country file
    countries_dir = os.path.join(output_dir, "common", "countries")
    os.makedirs(countries_dir, exist_ok=True)
    with open(os.path.join(countries_dir, f"{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("graphical_culture = western_european_gfx\n")
        f.write("graphical_culture_2d = western_european_2d\n")
        f.write("color = { 100 100 200 }\n")

    # history file
    history_dir = os.path.join(output_dir, "history", "countries")
    os.makedirs(history_dir, exist_ok=True)
    with open(os.path.join(history_dir, f"{tag} - FantasyCountry.txt"), "w", encoding="utf-8") as f:
        f.write("capital = 1\n")
        f.write(f'oob = "{tag}_1936"\n')
        f.write("set_politics = {\n")
        f.write("    ruling_party = neutrality\n")
        f.write('    last_election = "1932.1.1"\n')
        f.write("    election_frequency = 48\n")
        f.write("    elections_allowed = no\n")
        f.write("}\n")
        f.write("set_popularities = {\n")
        f.write("    democratic = 10\n")
        f.write("    fascism = 5\n")
        f.write("    communism = 5\n")
        f.write("    neutrality = 80\n")
        f.write("}\n")

    # OOB (empty organization of troops)
    oob_dir = os.path.join(output_dir, "history", "units")
    os.makedirs(oob_dir, exist_ok=True)
    with open(os.path.join(oob_dir, f"{tag}_1936.txt"), "w", encoding="utf-8") as f:
        f.write("units = { }\n")


def write_descriptor_mod(output_dir: str, mod_name: str = DEFAULT_MOD_NAME) -> None:
    """Generate descriptor.mod"""
    file_path = os.path.join(output_dir, "descriptor.mod")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f'version="{DEFAULT_MOD_VERSION}"\n')
        f.write("tags={\n")
        f.write('    "Alternative History"\n')
        f.write('    "Map"\n')
        f.write('    "Total Conversion"\n')
        f.write("}\n")
        f.write(f'name="{mod_name}"\n')
        from services.game_assets import resolve_supported_version
        f.write(f'supported_version="{resolve_supported_version()}"\n')
        f.write('replace_path="map"\n')
        f.write('replace_path="map/strategicregions"\n')
        f.write('replace_path="map/supplyareas"\n')
        f.write('replace_path="history/countries"\n')
        f.write('replace_path="history/states"\n')
        f.write('replace_path="history/units"\n')
        f.write('replace_path="common/country_tags"\n')
        f.write('replace_path="common/countries"\n')
        f.write('replace_path="common/national_focus"\n')
        f.write('replace_path="common/characters"\n')
