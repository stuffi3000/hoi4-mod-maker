# HOI4 states and strategic regions

States and strategic regions are different layers. A state is the territorial
unit used by history, ownership, buildings, resources, and victory points. A
strategic region groups provinces for air operations, naval operations, and
weather. Both layers must agree with the province map.

## State files

State history is stored under:

```text
history/states/*.txt
```

The filename is not the state identity; the contents are. Without a deliberate
`replace_path = "history/states"`, changing the names of existing vanilla
files can leave both the base file and the mod file loaded. A complete map
overhaul normally replaces the folder intentionally and supplies every state
it needs.

Every state is a `state = { ... }` block. A useful minimum is:

```pdx
state = {
    id = 123
    name = STATE_WT_123
    manpower = 50000
    state_category = large_town

    history = {
        owner = AUR
        add_core_of = AUR
        victory_points = { 456 5 }
    }

    provinces = { 456 789 }
}
```

Important fields:

- `id` is an integer and state IDs should be sequential from 1 to the largest
  state. The engine expects the intermediate entries to exist. Deleting a state
  therefore requires moving/referencing another state and updating every
  country, capital, building, and script reference.
- `name` is a localisation key. Use a stable ASCII key and put the visible
  name in a localisation file.
- `manpower` is the starting population of the state.
- `state_category` controls state modifiers and shared building capacity. The
  exact category set and slot limits are version-sensitive; resolve it from
  the target `common/states/*.txt` or installed game data rather than keeping
  a permanent hard-coded list in the UI.
- `provinces` is the complete province membership list. It is not a list of
  state IDs, and it should contain land provinces only for ordinary playable
  states.
- `history` is an effect block. `owner` is optional for the parser but an
  ownerless playable state is unstable: many later effects, AI checks, and air
  missions assume an owner. Set `controller` only when it differs from the
  owner.
- `victory_points = { province_id value }` uses a province ID, not a state ID.
  Use one block per victory-point province and localise it with
  `VICTORY_POINTS_<province_id>`.
- `resources`, state-level buildings, province-level buildings,
  `local_supplies`, cores, claims, and dated history blocks belong in their
  documented scopes. A dated block applies only after its date according to
  the engine's history rules.

Country history uses a different ID type: `capital = 123` points to a state,
while a victory point in that state points to a province. This distinction is
one of the most common causes of a map that reaches the menu but crashes when
the country is selected.

## Strategic regions

Strategic regions are defined under the current path:

```text
map/strategicregions/*.txt
```

The older `common/strategic_regions/` path is not the map definition path.
Each file may contain one or more `strategic_region = { ... }` blocks; the
numeric ID is in the block, not in the filename.

```pdx
strategic_region = {
    id = 12
    name = STRATEGICREGION_WT_12
    naval_terrain = water_shallow_sea

    provinces = { 3 4 5 6 }

    weather = {
        period = {
            between = { 0.0 30.11 }
            temperature = { -5.0 25.0 }
            no_phenomenon = 0.5
            rain_light = 0.2
            rain_heavy = 0.1
            snow = 0.1
            blizzard = 0.05
            mud = 0.05
            sandstorm = 0.0
        }
    }
}
```

Strategic-region IDs should be sequential. Every playable province needs one
region; missing or duplicated assignments can crash before a country can be
selected. A state should normally stay within one strategic region, and a
region should be geographically coherent. Sea regions may set
`naval_terrain` such as shallow sea, deep ocean, or fjords.

Weather periods use `day.month` bounds where the first day and month are zero
based in the wiki convention. The periods must cover the intended year, and
the weather keys/weights must be valid for the selected `common/weather.txt`.
`temperature_day_night` is obsolete in current versions; use `temperature`.

`map/weatherpositions.txt` places weather objects:

```text
strategic_region_id;X;Y;Z;size
```

The installed target game uses tokens such as `small` and `big`. Keep at least
the positions required by the target version, use actual region coordinates,
and do not treat one centroid per region as final visual placement. The Nudge
tool is useful for producing and reviewing these records.

## Relationship contract

The exporter should validate these relationships as one transaction:

| Layer | Reference | Required invariant |
| --- | --- | --- |
| Province raster/CSV | province color and ID | One stable identity per province |
| State membership | `history/states/*.txt` | Every land province in exactly one intended state |
| State history | owners, cores, buildings, VPs | State IDs and province IDs are not mixed |
| Country history | capital, OOB, politics | Capital resolves to a state and OOB references existing data |
| Strategic region | `map/strategicregions/*.txt` | Every playable province assigned once; region IDs dense |
| Weather positions | `map/weatherpositions.txt` | Every referenced region exists and coordinates use X/Y/Z convention |
| Map objects/logistics | buildings, supply, railways, adjacencies | Every reference survives the final province ID mapping |

The current exporter deliberately creates a state-aware region scaffold. That
is useful for a parseable test map, but it is not a substitute for authoring
weather, air/naval boundaries, and visual object placement for a production
map.

## Validation checklist

- state IDs are unique, dense, and present from 1 through the maximum;
- every state province exists, is land, and belongs to one state;
- no state mixes strategic regions unless the selected game profile explicitly
  allows it;
- every province that should be playable belongs to one strategic region;
- region IDs are dense and weather periods cover the required year;
- region names, state names, victory points, and resources have localization
  keys where required;
- owners, controllers, cores, claims, capitals, buildings, supply nodes,
  railways, and victory points resolve using the correct ID type;
- `weatherpositions.txt` has valid region IDs and target-version size values;
- a clean game run confirms that the static report matches engine behavior.

## Sources

- [HOI4 State modding](https://hoi4.paradoxwikis.com/State_modding)
- [HOI4 Strategic region modding](https://hoi4.paradoxwikis.com/Strategic_region_modding)
- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
