# HOI4 map modding: core files and identity

This page turns the wiki's **Map modding** article into the contract used by
the map editor and exporter. Map files are tightly coupled: a valid bitmap can
still fail when its IDs, state membership, strategic regions, positions, or
logistics refer to a different map.

## Map file inventory

The following files are the core map-facing inputs for the current 1.19-style
layout. Optional art and DLC files are deliberately marked as such; a mod may
inherit them from vanilla or a dependency.

| Path | Role | Contract |
| --- | --- | --- |
| `map/provinces.bmp` | Province identity and borders | 24-bit RGB, hard edges, no anti-aliasing; IDs come from colors |
| `map/definition.csv` | Province metadata | One row per province; color and ID must match the bitmap |
| `map/default.map` | Map file/configuration routing | References the filenames the engine should load |
| `map/continent.txt` | Ordered continent names | The integer in `definition.csv` is the ordered lookup used by the file |
| `map/terrain.bmp` | Graphical terrain | 8-bit indexed, normally the same dimensions as `provinces.bmp` |
| `map/heightmap.bmp` | Elevation and water surface | 8-bit grayscale/indexed, same dimensions as the province map |
| `map/rivers.bmp` | River paths and widths | 8-bit indexed, same dimensions; use the target river palette |
| `map/trees.bmp` | Static tree/map-object density | 8-bit indexed; resolution is a density choice and may differ by map profile |
| `map/world_normal.bmp` | Lighting normals | 24-bit RGB normal map, same map profile dimensions |
| `map/terrain/*.dds` | Terrain/material/colormap art | DDS format, dimensions, compression, and mipmaps are profile-specific |
| `map/cities.bmp` / `map/cities.txt` | City-style mask and meshes | Palette indices in the bitmap must match `city_group` entries |
| `map/buildings.txt` | 3D building positions and port sea links | Semicolon records; state ID, not province ID, is the first field |
| `map/positions.txt` | File named by `default.map` for map positions | It is empty in the installed vanilla 1.19.3.0 map; do not assume it replaces `unitstacks.txt`; record the selected profile's decision |
| `map/unitstacks.txt` | Unit models and victory-point icon positions | Province-based semicolon records; generated content must be version-tested |
| `map/supply_nodes.txt` / `map/railways.txt` | Starting supply graph | Every province reference must survive export and point to a valid state/map |
| `map/adjacencies.csv` / `map/adjacency_rules.txt` | Straits, canals, blocked borders | References and the CSV terminator are mandatory when the files are present |
| `map/strategicregions/*.txt` | Air/naval/weather regions | Province lists and sequential region IDs |
| `map/weatherpositions.txt` | Weather-object positions | Region ID plus map coordinates and a target-version size token |
| `map/ambient_object.txt` / `map/seasons.txt` | Persistent map objects and seasons | Keep definitions compatible with the selected graphics/entities set |

Older guides may mention `airports.txt`, `rocketsites.txt`, or
`rocket_sites.txt`. Those map files were deprecated/removed in patch 1.15;
do not add empty legacy files to a new map profile without a specific
compatibility reason.

## Profiles, manifests, and locks

The exporter has four explicit profiles:

- `foundation` owns stable map identity, geography, topology, reviewed
  placements, and map-owned assets. It omits country/scenario content.
- `acceptance` composes the foundation with disposable, collision-free test
  countries and the minimum history needed for a clean engine run.
- `scaffold` retains generated gameplay helpers for prototyping and records
  them outside the foundation lock.
- `legacy_full` is a compatibility profile for callers migrating from the
  pre-staged exporter.

Every staged artifact should contain a `foundation_manifest.json` describing
source and output hashes, target/profile, findings, repairs, asset resolution,
and provenance. A foundation lock selects the stable identity/topology fields
from that manifest. Compare a new manifest with the frozen lock before
content export; a breaking result requires an explicit migration review.

The lifecycle is `draft -> candidate -> frozen -> accepted`. Candidate and
freeze operations are available through `tools/foundation_freeze.py`; the
freeze command also generates `FOUNDATION-HANDOFF.md`. Engine acceptance is
valid only when its record carries the exact manifest and lock identity.

## `default.map` is a routing file

The vanilla shape is similar to:

```text
definitions = "definition.csv"
provinces = "provinces.bmp"
positions = "positions.txt"
terrain = "terrain.bmp"
rivers = "rivers.bmp"
heightmap = "heightmap.bmp"
tree_definition = "trees.bmp"
continent = "continent.txt"
adjacency_rules = "adjacency_rules.txt"
adjacencies = "adjacencies.csv"
ambient_object = "ambient_object.txt"
seasons = "seasons.txt"
tree = { 3 4 7 10 }
```

Treat every filename and setting as part of a selected map profile. A writer
that creates a file but does not reference it, or changes a setting that the
engine does not read in the selected version, creates false confidence.

## Province identity: bitmap plus CSV

`provinces.bmp` assigns a color to every pixel. `definition.csv` supplies the
metadata for each color:

```text
Province ID;R;G;B;Province type;Coastal;Terrain;Continent
```

Example:

```text
0;0;0;0;land;false;unknown;0
1;40;15;15;land;false;plains;1
2;170;235;235;land;true;urban;1
3;0;0;255;sea;false;ocean;0
```

Rules that matter to the exporter:

- The RGB triplet must be unique, opaque, and identical to the pixels in
  `provinces.bmp`. RGB `(0, 0, 0)` is reserved and should not be used for a
  real province.
- Province IDs should be dense and ordered from 1 through the largest ID.
  The engine treats these as array positions; a gap can shift metadata onto
  the wrong province even when the bitmap still looks correct.
- `land`, `sea`, and `lake` are different engine types. Sea terrain should be
  `ocean`, lake terrain should be `lakes`, and land terrain should be a valid
  land terrain from the selected `common/terrain/*.txt` definitions.
- A land continent is required for land provinces. Sea and lake provinces use
  continent `0` in the normal contract. Continent IDs follow the order in
  `continent.txt`.
- The `coastal` column should agree with the actual land/sea border. The map
  geometry is authoritative in modern versions, but a stale column still
  confuses tools, validators, and downstream writers.
- Removing or compacting a province is a reference migration: state lists,
  victory points, adjacencies, railways, supply nodes, buildings, positions,
  terrain attributes, and any script using the ID must be remapped together.

The wiki describes a current engine pixel-area ceiling of approximately
13,238,272 pixels for the province bitmap and recommends keeping province
counts near the base-game range for stability. The repository's verifier has a
separate, narrower list of supported map sizes. A future profile system should
validate the selected game/version rather than silently treating that list as
the engine's universal law.

## Geometry and coordinate system

The province bitmap width and height must satisfy the selected engine profile;
the current wiki guidance requires dimensions divisible by 256. All full-size
rasters that are defined as map-sized must agree with the province map. The
map wraps horizontally, so the left and right edges are neighbors for
topology checks.

HOI4 uses three-dimensional coordinates in map files:

- `X` is the horizontal bitmap coordinate, west to east, and wraps at the map
  edges.
- `Y` is height. A grayscale height value of 0..255 maps to approximately
  0..25.5; the default water level is about `Y = 9.5`.
- `Z` is the world vertical coordinate, south to north. Image editors usually
  count rows from the top, so a writer normally converts a pixel row using
  `Z = map_height - image_y` (with pixel-center handling where necessary).

Building, weather, unit, and adjacency line coordinates must use the same
convention. A coordinate that is numerically valid but falls into another
province can produce a late naval, building, or visual failure.

## Gameplay terrain is not graphical terrain

There are two terrain layers:

1. **Provincial terrain** in `definition.csv` for land, plus naval terrain in
   strategic-region definitions for sea areas. This controls combat and other
   gameplay modifiers.
2. **Graphical terrain** in `terrain.bmp`, whose palette indices select
   materials from the terrain definitions and atlas. This controls appearance
   and does not, by itself, change the province's gameplay terrain.

An editor may derive one layer from the other as a convenience, but export
must preserve the user's explicit provincial attribute when it exists.

## Cross-layer invariants

Before treating a map as a foundation, verify:

1. every non-black bitmap color has exactly one CSV row and every real CSV row
   has pixels;
2. dimensions, bit depth, palette, and DIB headers match the selected profile;
3. every land province has a continent and exactly one state;
4. every playable province belongs to exactly one strategic region;
5. state membership, state history, country capitals, victory points, and
   owner/controller tags use the correct ID type;
6. buildings, supply nodes, railways, unit/victory-point positions, and
   adjacencies resolve after any ID remapping;
7. `adjacencies.csv` ends with the required sentinel row, even when there are
   no custom adjacencies;
8. the generated mod is tested by the target game's map loader, not only by a
   static file checker.

## Sources

- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
- [HOI4 State modding](https://hoi4.paradoxwikis.com/State_modding)
- [HOI4 Strategic region modding](https://hoi4.paradoxwikis.com/Strategic_region_modding)
- [HOI4 Defines](https://hoi4.paradoxwikis.com/Defines)
