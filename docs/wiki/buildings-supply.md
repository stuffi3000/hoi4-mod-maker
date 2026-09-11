# HOI4 buildings, supply hubs, and railways

This page summarizes the map-side building and logistics files used by the exporter. Building definitions and scripted construction effects belong to other HOI4 data directories; this page covers initial placement and network data.

## `buildings.txt`

Initial map buildings are written to `map/buildings.txt` using this semicolon-separated form:

```text
State ID;Building type;X;Y;Z;Rotation;Adjacent sea province
```

The state ID identifies the state that owns the entry. `X`, `Y`, and `Z` locate the building in the map coordinate system, and rotation is expressed in radians. The final field is used when a naval or floating harbor needs to identify an adjacent sea province; ordinary buildings use the neutral value expected by the game version.

The file must contain valid data for the buildings the map requires. A malformed building entry can stop map loading, and a naval building with an invalid adjacent sea province can cause particularly difficult startup failures. Coordinates should be placed on the intended province and land surface.

## Building scopes

HOI4 buildings are commonly encountered in three scopes:

| Scope | Examples | Storage |
| --- | --- | --- |
| State-level | infrastructure, military factories, civilian factories, dockyards, refineries, fuel silos, radar | state history or state building data |
| Province-level | naval bases, forts, coastal forts, supply hubs, railways | province entries inside state history or map data |
| Map-object positions | ports, air bases, cities, and other visual/gameplay positions | `positions.txt`, `buildings.txt`, or the relevant map file |

The exact maximum level and available building list are defined by the game version and DLC. Do not hard-code an old list when targeting a newer game release.

## Supply hubs and railways

`map/supply_nodes.txt` describes the initial supply-hub level and province. `map/railways.txt` describes an initial railway route using a level, a province count, and the ordered province IDs. A minimal example is:

```text
# supply_nodes.txt
1 1234

# railways.txt
4 4 693 1444 12 11
```

Every province reference must exist in the exported `definition.csv`, and routes must be compatible with the final state and strategic-region layout. Do not leave a route pointing at a removed or remapped province. The exporter remaps these references together with compacted province IDs.

Initial network levels are separate from later scripted construction. Use the documented railway effects for an in-game railway change; a generic building-construction effect is not an interchangeable substitute.

## Safe export checklist

- validate every state and province ID before writing map files;
- place building coordinates on the correct province;
- give naval structures a valid adjacent sea province where required;
- ensure supply hubs and railway routes use exported province IDs;
- check the generated files with the game's `error.log` and `setup.log` after a version upgrade;
- remove obsolete map files only after confirming the target game version's requirements.

## Sources

- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
- [HOI4 Building modding](https://hoi4.paradoxwikis.com/Building_modding)
- [Map modding reference mirror](https://github.com/cpntodd/HOI4-MCP/blob/main/paradox_wiki/Map%20modding%20-%20Hearts%20of%20Iron%204%20Wiki.md)
