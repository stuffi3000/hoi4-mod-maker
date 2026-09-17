# HOI4 country creation, tags, flags, and ideologies

This is the country/content reference for the exporter. It covers the files that identify a country, give it a starting scenario, and connect it to the ideology and localization systems. It does not replace a target-version content test: country history and ideology keys are especially sensitive to the vanilla files loaded by the selected game version.

## File layout

| Path | Responsibility | Identity that must agree |
| --- | --- | --- |
| `common/country_tags/*.txt` | Register a tag and point it at a country definition | The three-character tag |
| `common/countries/<name>.txt` | Graphical culture and map/UI color | The tag registration path |
| `history/countries/<TAG> - <name>.txt` | Capital, politics, research, ideas, characters, and starting OOB | The filename tag and country definition |
| `history/states/*.txt` | State owner, controller, cores, resources, buildings, and victory points | Country tags and state/province IDs |
| `common/ideologies/*.txt` | Main ideology groups and sub-ideologies | Ideology keys used by history and politics |
| `common/characters/*.txt` | Leaders, generals, admirals, advisors, and operatives | Character IDs referenced by history/effects |
| `history/units/*.txt` | Optional starting army, navy, and air OOBs | Country tag and equipment/template IDs |
| `gfx/flags/*.tga` | Country and ideology-specific flags | The tag and ideology suffixes |
| `localisation/english/*_l_english.yml` | Country, party, ideology, character, and state names | Exact localization keys |

## Tags

Register a tag under `common/country_tags/`:

```pdx
ABC = "countries/Aurora.txt"
```

Use a unique three-character uppercase Latin tag. A tag is a global identifier, not merely a display abbreviation: scripts, save data, localization, flags, history, and other countries refer to it. Do not reuse vanilla or DLC tags, dynamic-country slots, or engine-reserved words. In particular, avoid tags such as `NOT`, `AND`, `TAG`, `OOB`, `LOG`, and `NUM`, as well as all-numeric forms.

The country-definition path is relative to `common/countries/`. Register a tag exactly once. A duplicate registration or a tag collision with vanilla can produce duplicate-country messages or silently bind content to the wrong country.

## Country definition and history

The country definition selects graphical assets and the map/UI color:

```pdx
graphical_culture = western_european_gfx
graphical_culture_2d = western_european_2d
color = rgb { 60 130 220 }
```

The country history filename convention is `<TAG> - <name>.txt`; the tag at the beginning is the important part. A minimal scenario history normally includes a state capital and starting political setup:

```pdx
capital = 123
set_research_slots = 3
set_stability = 0.7
set_war_support = 0.5

set_politics = {
    ruling_party = democratic
    last_election = "1932.11.8"
    election_frequency = 48
    elections_allowed = yes
}

set_popularities = {
    democratic = 80
    fascism = 10
    communism = 10
}
```

`capital` is a state ID. A victory point in a state history file is written as `victory_points = { <province_id> <value> }`, so it uses a province ID instead. Keep those ID types distinct. The capital state must exist, contain provinces, and be owned by the country at the start of the scenario.

Starting armies, fleets, air wings, characters, equipment, and templates must be defined before the history or OOB code references them. A country without a coherent OOB can appear in the menu but fail during setup or the first game tick; the exporter should either generate an explicit test OOB or mark the scenario as a content scaffold.

## Ideologies and political parties

Custom ideology groups and sub-ideologies are defined under `common/ideologies/*.txt`. Reuse the vanilla main groups when the tool only needs a normal democratic, fascist, communist, or non-aligned country. Add a custom group only when its rules, color, AI behavior, faction names, and localization are part of the intended content.

The keys used by `ruling_party`, `set_popularities`, leader definitions, and party names must be legal in the target version. Localize every player-facing group, sub-ideology, and party key:

```yaml
l_english:
 ABC_democratic:0 "Auroran Democracy"
 ABC_democratic_party:0 "Auroran Democratic Party"
```

Country history should create or recruit characters before politics or effects assign them to roles. Keep character IDs namespaced by tag or project so that generated content cannot collide with vanilla or another country.

## Flags

The standard flag set is stored below `gfx/flags/`:

```text
gfx/flags/ABC.tga
gfx/flags/ABC_democratic.tga
gfx/flags/ABC_fascism.tga
gfx/flags/ABC_communism.tga
gfx/flags/medium/ABC.tga
gfx/flags/small/ABC.tga
```

Use the dimensions expected by the game for the standard, medium, and small variants (vanilla commonly uses 82x52, 41x26, and 10x7). Write 32-bit TGA files without RLE compression and with the expected bottom-left image origin. If the target game or a supplied vanilla asset uses a different contract, preserve the validated asset and record the profile rather than silently resizing it.

## Localization keys

At minimum, provide the country name and adjective keys expected by the country UI. The common convention is:

```yaml
l_english:
 ABC:0 "Aurora"
 ABC_DEF:0 "Auroran Federation"
 ABC_ADJ:0 "Auroran"
 ABC_democratic:0 "Auroran Democracy"
```

Use the exact keys emitted by the target game's country, party, ideology, character, focus, and event definitions. Missing keys are usually visible as raw identifiers rather than a parser error, so localization belongs in the same validation pass as the country files.

## Dynamic countries

Dynamic country slots and generated tags are a separate system. A tool-generated permanent country should not consume a dynamic slot or imitate a dynamic tag unless it also generates the required dynamic-country rules, localization, flags, and history. Treat dynamic tags as reserved in the project's unique-tag allocator.

## Country export checklist

- tag registration is unique and does not collide with vanilla, DLC, or dynamic tags;
- the country definition path, history filename, and generated references use the same tag;
- the capital is an existing state ID and the state has valid province membership;
- state ownership and cores use country tags, while victory points use province IDs;
- the starting ideology and popularity keys are defined and have intended values;
- characters, equipment, templates, and OOB references exist in the generated tree;
- standard, medium, small, and ideology flags are present in the target format;
- English localization covers country, adjective, ideology, party, character, focus, and event keys;
- the country can reach the main menu, start a new game, tick, save, and reload in an isolated test MOD.

## Sources

- [HOI4 Country creation](https://hoi4.paradoxwikis.com/Country_creation)
- [HOI4 Country modding](https://hoi4.paradoxwikis.com/Country_modding)
- [HOI4 Ideology modding](https://hoi4.paradoxwikis.com/Ideology_modding)
- [HOI4 Character modding](https://hoi4.paradoxwikis.com/Character_modding)
- [HOI4 Localisation](https://hoi4.paradoxwikis.com/Localisation)
