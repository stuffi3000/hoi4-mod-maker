# HOI4 countries, country tags, and ideologies

This is a compact English reference for the files needed to create a country and connect it to the ideology system.

## Country file layout

| Path | Role |
| --- | --- |
| `common/country_tags/*.txt` | Register the country tag and country-definition path |
| `common/countries/<name>.txt` | Graphical culture and map/UI color |
| `history/countries/<TAG> - <name>.txt` | Starting capital, politics, technology, ideas, and OOB |
| `history/states/*.txt` | State ownership, cores, resources, and victory points |
| `localisation/english/*_l_english.yml` | Country, party, leader, and other display names |
| `gfx/flags/<TAG>.tga` | Main flag and ideology variants |
| `common/characters/*.txt` | Leaders, generals, admirals, advisors, and operatives |
| `history/units/*.txt` | Optional starting army, navy, and air OOB |
| `common/names/*.txt` | Optional random name lists |

## Country tags

Register a tag in a file under `common/country_tags/`:

```pdx
ABC = "countries/Aurora.txt"
```

Tags are normally three uppercase Latin letters. Keep tags unique and avoid names that collide with script keywords or reserved engine identifiers. The path is relative to `common/countries/`.

## Country definition

`common/countries/Aurora.txt` selects the graphical culture and color:

```pdx
graphical_culture = western_european_gfx
graphical_culture_2d = western_european_2d
color = rgb { 60 130 220 }
```

The country must also have a valid capital state in its history file. In a state history entry, ownership and cores use country tags; a victory-point entry uses a province ID.

## Country history

`history/countries/ABC - Aurora.txt` commonly contains:

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

The filename tag, country definition, capital, and starting owner must agree. Load an OOB only after creating the characters and defining the equipment/templates it references. Dated blocks apply changes after their date according to the game's history-file rules.

## Ideology definitions

Custom ideology groups are defined under `common/ideologies/*.txt`. A group can contain sub-ideologies, a color, faction names, rules, world-tension modifiers, and AI behavior. Localize the group, sub-ideology, and party keys in English:

```yaml
l_english:
 ABC_democratic:0 "Auroran Democracy"
 ABC_democratic_party:0 "Auroran Democratic Party"
```

Use existing vanilla ideology groups when a custom ruleset is not needed. If an ideology is custom, define its rules and localizations together; missing keys otherwise appear as raw identifiers in the interface.

## Validation checklist

- the tag is registered exactly once;
- the country definition and history filename use the same tag;
- the capital is an existing state ID;
- state ownership, cores, and victory points reference the correct ID type;
- all starting OOB and character references exist;
- flags, sprites, and English localization keys are present;
- ideology popularity values form the intended distribution and use defined ideology keys.

## Sources

- [HOI4 Country creation](https://hoi4.paradoxwikis.com/Country_creation)
- [HOI4 Country modding](https://hoi4.paradoxwikis.com/Country_modding)
- [HOI4 Ideology modding](https://hoi4.paradoxwikis.com/Ideology_modding)
- [HOI4 Localisation](https://hoi4.paradoxwikis.com/Localisation)
