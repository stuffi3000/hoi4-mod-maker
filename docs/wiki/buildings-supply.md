# HOI4 buildings, ports, and starting map infrastructure

Buildings have three related but separate representations. The building
definition describes what a building means; state history describes starting
levels; `map/buildings.txt` places the 3D model and tells the engine which sea
province a port uses.

## Building definitions and slot classes

Building definitions live under:

```text
common/buildings/*.txt
```

The target game's definitions decide cost, maximum level, modifiers, icon,
model, and whether the building uses shared, state, or provincial slots.
Typical classes are:

| Class | Examples | Starting data |
| --- | --- | --- |
| Shared state slots | `industrial_complex`, `arms_factory`, `dockyard`, `synthetic_refinery`, `fuel_silo` | State history `history = { buildings = { ... } }` |
| Non-shared state buildings | `infrastructure`, `air_base`, `radar_station`, `anti_air_building` | State history |
| Provincial buildings | `naval_base`, `bunker`, `coastal_bunker`, `supply_node`, `rail_way` | Province block in state history for many buildings; supply/railway starting topology is in `map/` |

Do not hard-code maximum levels or slot counts from an old patch. The wiki's
building table is a useful guide, but the selected `common/buildings` and
`defines` files are authoritative for the export profile.

Railways and supply nodes are technically buildings but have special initial
and construction behavior. Their starting levels are read from
`map/railways.txt` and `map/supply_nodes.txt`; using a generic building effect
to construct a railway during the game can crash or produce invalid state.

## State-history buildings

Initial state-level and province-level buildings are written in a state history
block:

```pdx
history = {
    buildings = {
        infrastructure = 3
        industrial_complex = 1
        1234 = {
            naval_base = 3
            coastal_bunker = 2
        }
    }
}
```

State-level names are building IDs. A numeric child block uses a province ID
and must be inside the same state's `provinces` list. Do not put a naval base or
coastal bunker on a province that is not actually coastal. Check the target
building definitions for shared-slot, state-level, and provincial limits after
any category change.

## `map/buildings.txt`

The map model file uses one semicolon-separated record per positioned object:

```text
State ID;Building type;X;Y;Z;Rotation;Adjacent sea province
```

The first field is always the **state ID**, including for a provincial model.
For provincial buildings, the X/Y/Z coordinate identifies the province. The
coordinate convention is the same as other map files: X is east-west, Y is
height in roughly 0..25.5, and Z is south-to-north.

Rotation is in radians. The last field is needed for naval bases and floating
harbours so the game knows which sea province the port uses; ordinary objects
use the neutral value required by the target version.

Important failure modes:

- An entirely empty `buildings.txt` can make the map crash during loading.
- A coastal province with a naval base but no matching port/model definition
  may appear to work until the AI evaluates a fleet, then hang or crash.
- A coordinate outside the intended province can cause invalid model placement
  or a port to connect to the wrong sea.
- Changing states or province IDs without remapping this file makes later
  gameplay failures look unrelated to the original map edit.

The Nudge tool is usually safer for final placement because it knows the map
surface and object model. An automated writer should at least test the rounded
coordinate's province ownership and sea adjacency.

## Supply hubs and railways

Starting supply data is stored in the map root:

```text
map/supply_nodes.txt
map/railways.txt
```

`supply_nodes.txt` has one whitespace-separated record per node:

```text
Level Province
1 1234
```

The default node maximum is one, but the selected `defines` can change it.
The province must be a valid land province in a state. Do not use an ocean,
lake, deleted, or stateless province as a node.

`railways.txt` has one route per line:

```text
Level ProvinceCount Province1 Province2 ... ProvinceN
4 4 693 1444 12 11
```

The count must equal the number of listed provinces, the IDs must exist, and
consecutive provinces should be adjacent in the final province topology. The
default railway maximum is five; resolve the target value from `defines`.
Disconnected islands can be intentional, but an exporter must report them as
reviewable decisions rather than silently accepting every disconnected graph.
Self-loop placeholders such as `1 2 1234 1234` are parseable scaffolding, not
a production railway.

## Export guidance

Keep these operations separate in the data model:

1. building **definition** (`common/buildings` and installed game assets);
2. building **level** (state history or starting logistics file);
3. building **position** (`map/buildings.txt`);
4. building **network semantics** (railway connectivity, supply reachability,
   and the selected sea province for a port).

The current exporter can generate placeholder factories, ports, supply nodes,
railways, and map positions to make a test fixture parseable. Those generated
values must be labeled as scaffolding until terrain, state ownership, port
access, graph connectivity, and visual placement have been reviewed.

## Safe export checklist

- resolve every building ID against the selected game's definitions;
- enforce state-category shared-slot limits after applying user overrides;
- ensure every province-level building is in the state that owns its province;
- place every naval building on a coastal province and give it a valid sea link;
- validate building coordinates against the final province raster and heightmap;
- validate supply nodes as state-owned land provinces;
- validate railway count, endpoints, consecutive adjacency, level, and graph
  components;
- remap all references after province compaction;
- run a clean target-version start and inspect `error.log`, `setup.log`, and
  later AI/naval behavior.

## Foundation versus scenario content

In the `foundation` profile, `map/buildings.txt`, ports, slots, and weather
positions are map-owned placement data only. State owners, resources,
manpower, victory points, factories, and country history are content-team
inputs and are intentionally omitted. A generated centroid or network pair is
reported as an unreviewed proposal; it is not evidence that the placement is
ready for a frozen map.

The `acceptance` profile may add disposable owners and test history so the
engine can start. The `scaffold` profile may add generated building levels and
other gameplay helpers, but those records are marked as scaffold provenance
and excluded from the foundation lock. `legacy_full` retains the old behavior
only for compatibility during migration.

Before freezing, review the placement and logistics findings together:

1. accept or replace every generated/fallback building and port position;
2. verify every port's adjacent sea province and every building's state ID;
3. review railway components and explain intentional disconnected networks;
4. ensure supply nodes are valid land provinces in the final state graph;
5. rerun static validation, export the exact artifact, and attach the engine
   acceptance record before recording the lock.

## Sources

- [HOI4 Building modding](https://hoi4.paradoxwikis.com/Building_modding)
- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
- [HOI4 Defines](https://hoi4.paradoxwikis.com/Defines)
