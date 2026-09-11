# HOI4 states and strategic regions

States are the main territorial unit used by HOI4 history files. Strategic regions group provinces for weather, air operations, naval operations, and other map systems. The two layers must agree with the province raster.

## State history

State files live in `history/states/*.txt` and use a structure like this:

```pdx
state = {
    id = 123
    name = STATE_123
    manpower = 500000
    state_category = town
    provinces = { 123 456 789 }

    resources = { steel = 10 aluminium = 20 }

    history = {
        owner = POL
        victory_points = { 123 10 }
        add_core_of = POL
        buildings = {
            infrastructure = 3
            123 = { naval_base = 2 }
        }
    }
}
```

The `provinces` block lists province IDs that belong to the state. The history block supplies ownership, cores, victory points, buildings, resources, and dated changes. `capital` in a country history file refers to a state ID, while a victory-point entry refers to a province ID.

## State categories

`state_category` controls the state's building-slot rules. Common vanilla keys include `wasteland`, `enclave`, `tiny_island`, `small_island`, `large_island`, `pastoral`, `rural`, `town`, `large_town`, `city`, `large_city`, `metropolis`, and `megalopolis`. The category list and slot counts can change with the game version, so use the target version's definitions.

## Strategic regions

Strategic-region definitions are stored under `common/strategic_regions/*.txt`. A region contains province IDs and metadata such as its name, weather, and air/naval settings. Every province used by the playable map should belong to a valid strategic region. States should not mix provinces from unrelated strategic regions unless the target game version explicitly supports that layout.

When editing or generating a map, update these relationships together:

1. province colors and rows in `definition.csv`;
2. the province list in each state history file;
3. state ownership, capital, and victory points;
4. strategic-region province lists;
5. supply, railway, building, and adjacency references.

## Validation checklist

- state IDs are unique and all referenced states exist;
- every listed province exists and appears in the intended state;
- each state has a valid category and history owner when gameplay requires one;
- victory points, capitals, buildings, railways, and supply hubs refer to the correct ID type;
- strategic regions contain valid provinces and cover the playable map;
- exported state and region files contain only the English localization keys used by the mod.

## Sources

- [HOI4 State modding](https://hoi4.paradoxwikis.com/State_modding)
- [HOI4 Strategic region modding](https://hoi4.paradoxwikis.com/Strategic_region_modding)
- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
