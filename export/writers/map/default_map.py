"""map/default.map writer.

The HOI4 engine uses this file to load all map configurations. See reference/Map modding.txt lines 56-83.

Format (unquoted fields don't require quotes, but are vanilla safe with quotes):
    definitions = "definition.csv"
    provinces = "provinces.bmp"
    ...
    tree = { 3 4 7 10 } # palette indices considered trees"""

from __future__ import annotations

import os


def write_default_map(
    output_dir: str,
    settings=None,
    province_count: int | None = None,
) -> None:
    """Generate map/default.map.

    settings: DefaultMapSettings instance (None uses default)
    province_count: total number of provinces (None skips max_provinces field)"""
    if settings is None:
        from domain.managers.default_map_settings import DefaultMapSettings
        settings = DefaultMapSettings.default()

    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)
    path = os.path.join(map_dir, "default.map")

    lines: list[str] = []
    lines.append(f'definitions = "{settings.definitions}"')
    lines.append(f'provinces = "{settings.provinces}"')
    lines.append(f'positions = "{settings.positions}"')
    lines.append(f'terrain = "{settings.terrain}"')
    lines.append(f'rivers = "{settings.rivers}"')
    lines.append(f'heightmap = "{settings.heightmap}"')
    lines.append(f'tree_definition = "{settings.tree_definition}"')
    lines.append(f'continent = "{settings.continent}"')
    lines.append(f'adjacency_rules = "{settings.adjacency_rules}"')
    lines.append(f'adjacencies = "{settings.adjacencies}"')
    lines.append(f'ambient_object = "{settings.ambient_object}"')
    lines.append(f'seasons = "{settings.seasons}"')

    # Tree palette index
    tree_indices = " ".join(str(i) for i in settings.tree_palette_indices)
    lines.append(f"tree = {{ {tree_indices} }}")

    content = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
