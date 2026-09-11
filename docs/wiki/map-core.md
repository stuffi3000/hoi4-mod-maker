# HOI4 map modding: core assets

This page is a project-oriented summary of the current Hearts of Iron IV map-modding reference. Keep the game version in mind when validating limits and deprecated files.

## Map directory

The core map files are normally placed under `map/` in the mod root.

| File | Purpose | Important constraint |
| --- | --- | --- |
| `provinces.bmp` | Province-color raster | 24-bit RGB; dimensions must follow the engine's map-size rules |
| `definition.csv` | Province metadata | One row per province; the province color must match `provinces.bmp` |
| `terrain.bmp` | Graphical terrain raster | 8-bit indexed image whose palette indices map to terrain definitions |
| `heightmap.bmp` | Terrain elevation | 8-bit grayscale height data |
| `rivers.bmp` | River raster | Uses the river palette and one-pixel raster paths |
| `trees.bmp` | Tree coverage | 8-bit indexed image with the tree palette |
| `world_normal.bmp` | Normal map for lighting | 24-bit RGB normal-map data |
| `colormap_rgb_cityemissivemask_a.dds` | Province color and city-light mask | DDS dimensions follow the map's half-resolution colormap format |
| `buildings.txt` | Initial building positions | Coordinates must be valid for the referenced province or state |
| `positions.txt` | Unit, city, and map-object positions | Coordinates use the map coordinate system |
| `supply_nodes.txt` | Initial supply hubs | References valid provinces |
| `railways.txt` | Initial railway network | Every referenced province must exist |
| `adjacencies.csv` | Special province connections | Include the required terminator row |
| `adjacency_rules.txt` | Custom adjacency rules | Rule names must match the definitions used by the map |
| `ambient_object.txt` | Ambient objects | Object definitions must reference valid assets |
| `cities.txt` | City metadata | City province and position data must be valid |

`default.map` connects these assets and defines additional map-level settings. The exact file set changes between game versions; consult the wiki before adding deprecated files such as the old airport or rocket-site maps.

## `definition.csv`

The standard row format is:

```text
Province ID;R;G;B;Province type;Coastal;Terrain;Continent
```

Example:

```text
1;40;15;15;land;false;plains;1
2;170;235;235;land;true;urban;1
3;0;0;255;sea;false;ocean;0
```

The RGB triplet is the province identity. It must be unique, opaque, and identical to the corresponding province color in `provinces.bmp`. Province type, coastal status, terrain type, and continent values are metadata; they do not replace correct raster geometry.

## Raster conventions

- `provinces.bmp` is a hard-edged province map. Do not use anti-aliasing or indexed-color conversion.
- `terrain.bmp` uses palette indices, not merely visually similar RGB colors. The indices must agree with the game's terrain definitions.
- `heightmap.bmp` maps grayscale values to elevation. In the standard map convention, value `0` is height `0` and `255` is height `25.5`; the default sea-level value is approximately `95`.
- `world_normal.bmp` stores surface normals for lighting and should be generated or edited as a normal map rather than as ordinary color art.
- River and tree rasters are indexed images. Preserve their palette and dimensions when editing them.
- The horizontal map edge wraps in the game. A coastline or province touching the left edge may therefore also touch the right edge.

## Province and adjacency checks

Before exporting, verify that:

1. every province color has exactly one `definition.csv` row;
2. every non-ocean province is assigned to a continent;
3. province dimensions and all map rasters agree;
4. no province has accidental anti-aliased colors or isolated invalid pixels;
5. special adjacencies reference existing provinces and include the terminator row;
6. supply hubs, railway endpoints, buildings, and city positions point to valid map data.

## Sources

- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
- [HOI4 Hearts of Iron 4 Wiki](https://hoi4.paradoxwikis.com/Hearts_of_Iron_4_Wiki)
- [Map modding reference mirror](https://github.com/cpntodd/HOI4-MCP/blob/main/paradox_wiki/Map%20modding%20-%20Hearts%20of%20Iron%204%20Wiki.md)
