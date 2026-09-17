# HOI4 wiki reference for HOI4 Map Maker

**Review date:** 17 September 2026
**Primary target profile:** Hearts of Iron IV 1.19.3.0 (Operation Postern)

These files are an engineering reference for the exporter and map editor. They
summarize the relevant parts of the [official HOI4 Modding
section](https://hoi4.paradoxwikis.com/Modding) and its linked articles; they
are not a verbatim mirror of the wiki. Examples and checklists are adapted to
this repository and should be re-checked against the selected game version
before changing an exporter writer.

## Start here

1. [Modding overview](modding-overview.md) explains how the launcher, mod
   descriptors, load order, file merging, and `replace_path` interact.
2. [Map core](map-core.md) defines the province, map, state, region, and
   `default.map` contracts.
3. [Map visual assets](map-visual-assets.md) covers BMP palettes, height,
   rivers, terrain atlases, colormaps, trees, and city meshes.
4. [States and strategic regions](states-regions.md) explains the gameplay
   ownership layer and weather/air/naval grouping layer.
5. [Buildings and supply](buildings-supply.md) plus [logistics and
   adjacencies](logistics-and-adjacency.md) cover starting buildings, ports,
   supply nodes, railways, straits, canals, and impassable borders.
6. [Tool export contract](tool-export-contract.md) records what this project
   currently generates, inherits, or leaves for a later content workflow.

## Reference map

| Repository reference | Canonical wiki pages | Use it when |
| --- | --- | --- |
| [modding-overview.md](modding-overview.md) | [Modding](https://hoi4.paradoxwikis.com/Modding) | Changing descriptors, load order, file layout, or debug workflow |
| [map-core.md](map-core.md) | [Map modding](https://hoi4.paradoxwikis.com/Map_modding) | Adding or validating map files, IDs, dimensions, or coordinates |
| [map-visual-assets.md](map-visual-assets.md) | [Map modding](https://hoi4.paradoxwikis.com/Map_modding), [Graphical asset modding](https://hoi4.paradoxwikis.com/Graphical_asset_modding) | Editing BMP/DDS assets, palettes, or map art |
| [states-regions.md](states-regions.md) | [State modding](https://hoi4.paradoxwikis.com/State_modding), [Strategic region modding](https://hoi4.paradoxwikis.com/Strategic_region_modding) | Changing state membership, state history, weather, or region IDs |
| [buildings-supply.md](buildings-supply.md) | [Building modding](https://hoi4.paradoxwikis.com/Building_modding), [Map modding](https://hoi4.paradoxwikis.com/Map_modding) | Changing building definitions, starting buildings, ports, or map placement |
| [logistics-and-adjacency.md](logistics-and-adjacency.md) | [Map modding](https://hoi4.paradoxwikis.com/Map_modding), [Supply areas modding](https://hoi4.paradoxwikis.com/Supply_areas_modding) | Changing supply/railway graphs or special province connections |
| [country-ideology.md](country-ideology.md) | [Country creation](https://hoi4.paradoxwikis.com/Country_creation), [Ideology modding](https://hoi4.paradoxwikis.com/Ideology_modding) | Creating country scaffolding, tags, leaders, flags, or ideologies |
| [localisation-and-mod-structure.md](localisation-and-mod-structure.md) | [Localisation](https://hoi4.paradoxwikis.com/Localisation), [Modding](https://hoi4.paradoxwikis.com/Modding) | Writing names, tooltips, descriptors, or translated strings |
| [scripting-systems.md](scripting-systems.md) | [Event modding](https://hoi4.paradoxwikis.com/Event_modding), [National focus modding](https://hoi4.paradoxwikis.com/National_focus_modding), [Decision modding](https://hoi4.paradoxwikis.com/Decision_modding), [Idea modding](https://hoi4.paradoxwikis.com/Idea_modding), [On actions](https://hoi4.paradoxwikis.com/On_actions) | Planning the future content editors and validating generated script |
| [troubleshooting.md](troubleshooting.md) | [Troubleshooting](https://hoi4.paradoxwikis.com/Troubleshooting) | Interpreting logs, crash data, `MAP_ERROR`, or a failed launch |
| [tool-export-contract.md](tool-export-contract.md) | The pages above plus [Defines](https://hoi4.paradoxwikis.com/Defines) | Deciding whether a proposed writer change belongs in the map foundation |

## Facts that must be re-checked after a game update

- The initial supply system is `map/supply_nodes.txt` plus
  `map/railways.txt`. The old `map/supplyareas/` system is deprecated from
  patch 1.11 onward.
- Old airport and rocket-site map files were deprecated/removed in patch 1.15.
  Do not add them to a new map profile merely because an older mod contains
  them.
- Province, state, and strategic-region IDs are effectively dense sequential
  arrays. Deleting an ID requires a coordinated reference migration.
- Bitmap dimensions, palettes, DIB headers, DDS compression, mipmaps, terrain
  indices, building limits, and defines are engine/version contracts, not
  permanent constants in this repository.
- A static verifier can prove references and file shape, but only a clean game
  run can prove that the selected version accepts the map.

## Maintenance rule

When a writer changes, update the relevant reference page and the
repository-specific [export contract](tool-export-contract.md) in the same
change. Keep these questions separate:

1. What the HOI4 engine expects.
2. What the selected vanilla installation currently contains.
3. What this tool currently emits or preserves.
4. What is intentionally handed off to a content or art workflow.

Last checked against the current wiki material and the installed 1.19.3.0 map
layout on the review date above. The wiki remains authoritative for later
patches.
