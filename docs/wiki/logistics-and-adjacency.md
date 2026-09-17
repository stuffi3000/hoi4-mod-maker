# HOI4 logistics and special province adjacencies

This page covers the graph-like map data that is easy to make syntactically
valid but semantically broken: railways, supply nodes, straits, canals, and
impassable borders.

## Special adjacencies

`map/adjacencies.csv` can add or block a relationship between two provinces.
It supports a strait/canal-style connection between provinces that do not
share a direct border and an impassable marker that blocks a direct border.

The normal ten-column shape is:

```text
From;To;Type;Through;start_x;start_y;stop_x;stop_y;adjacency_rule;Comment
```

For a `sea` connection, `Through` identifies the sea gateway when the two
provinces do not touch. Coordinates define the visible red connection line;
`-1` asks the game to calculate a suitable position. A sea connection must
connect provinces of the same broad type (land-to-land or sea-to-sea) and a
land strait should not also be a direct land border.

For an `impassable` connection, leave the through province, coordinates, and
rule unset using the target format. It blocks movement across an otherwise
direct border.

The final line is a required sentinel. The current writer and wiki convention
use nine `-1` fields:

```text
-1;-1;-1;-1;-1;-1;-1;-1;-1
```

Keep the sentinel even when there are no custom entries. Missing it can cause
the loader to hang while reading the file.

## `adjacency_rules.txt`

`map/adjacency_rules.txt` contains `adjacency_rule = { ... }` blocks referenced
by the ninth CSV field. A rule normally declares access for four relationships
(`contested`, `enemy`, `friend`, `neutral`) and four passage types (`army`,
`navy`, `submarine`, `trade`). It may also require control of provinces and
provide an icon province/offset.

Example shape:

```pdx
adjacency_rule = {
    name = "AURORA_STRAIT"
    contested = { army = no navy = no submarine = no trade = no }
    enemy = { army = no navy = no submarine = no trade = no }
    friend = { army = yes navy = yes submarine = yes trade = yes }
    neutral = { army = no navy = yes submarine = yes trade = yes }
    required_provinces = { 1234 5678 }
    icon = 1234
}
```

Every rule name must be unique, every province reference must survive the
final ID mapping, and every CSV rule reference must have a matching block. A
map with no canals or straits may legitimately have no custom rules, but that
decision should be recorded in the export report rather than inferred from an
empty file.

## Current supply system

Since patch 1.11, initial supply is represented by:

```text
map/supply_nodes.txt
map/railways.txt
```

The old `map/supplyareas/*.txt` files grouped states and supplied a base value
in versions up to 1.10. They are deprecated for current game profiles. The
repository still contains a legacy `write_supply_areas` helper because older
exports and migration work may use it; it must not be treated as a required
1.19 output. A future profile should either omit it or mark it explicitly as
legacy compatibility output.

Static validity is only the first layer. A useful logistics report also shows:

- supply nodes that are not present in any railway component;
- connected railway components and their land/sea/island explanation;
- routes that cross a state boundary or use an invalid province;
- self-loop placeholders and duplicate routes;
- node reachability, intentional convoy/port exceptions, and final network
  levels.

See [buildings-supply.md](buildings-supply.md) for the record formats and
building relationship. Both pages should be updated if the exporter changes
the logistics model.

## ID migration and topology

Province compaction is not a local bitmap operation. An ID mapping must update:

```text
definition.csv
history/states/*.txt
state victory points and province buildings
strategic regions
supply_nodes.txt and railways.txt
adjacencies.csv and adjacency_rules.txt
map/buildings.txt and unit/victory-point positions
```

After remapping, recompute raster adjacency with horizontal wrap, not only
ordinary left/right neighbors. A valid path can still be semantically bad if a
railway jumps over a province, a supply node is placed in a lake, or a strait
references a province that no longer exists.

## Sources

- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
- [HOI4 Supply areas modding](https://hoi4.paradoxwikis.com/Supply_areas_modding)
- [HOI4 Building modding](https://hoi4.paradoxwikis.com/Building_modding)
