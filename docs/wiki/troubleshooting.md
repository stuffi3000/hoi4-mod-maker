# HOI4 MOD troubleshooting

When a MOD fails to load, start with the first useful error rather than the last message in the log. Parser errors often produce several secondary failures.

## Log files

The game normally writes logs under:

```text
Documents/Paradox Interactive/Hearts of Iron IV/logs/
```

| File | Use |
| --- | --- |
| `error.log` | Parser, asset, definition, and runtime errors |
| `setup.log` | Map and database setup progress |
| `game.log` | In-game triggers, effects, and country behavior |
| `text.log` | Localisation key and text-parser diagnostics |
| `memory.log` | Memory and loading diagnostics |
| `exceptions.log` | Exception information; corroborate it with the other logs |
| `time.log` | Timing information for loading and processing steps |

Enable the game's crash-data logging option when a crash report with a `LastRead` field is needed. `LastRead` identifies the last item successfully read; the actual invalid entry may be the next item, so inspect the surrounding files as well.

## Common map failures

| Symptom | First checks |
| --- | --- |
| Crash while loading the main menu | BMP dimensions, bit depth, palette, DIB header, and `default.map` references |
| Provinces have wrong terrain or ownership | `definition.csv` colors, row order, province IDs, and state lists |
| Coastal state or port failure | Province coastline, naval-base position, adjacent sea province, and building data |
| Supply or railway crash | Valid exported province IDs, state membership, route order, and network levels |
| Map reaches the menu but gameplay fails | State owners, capitals, strategic-region coverage, OOB references, and scripted scopes |
| Text appears as a raw key | `l_english:` header, UTF-8 BOM, file path, exact key spelling, and `text.log` |

## Export validation

Before launching the game, check that the export contains:

- `map/provinces.bmp`, `definition.csv`, `terrain.bmp`, `heightmap.bmp`, and `default.map`;
- valid `rivers.bmp`, `trees.bmp`, normal-map, colormap, and positions data when the target version requires them;
- state, country, strategic-region, supply, railway, and adjacency references that use the final exported IDs;
- `localisation/english/*_l_english.yml` files with a valid header and BOM;
- a descriptor whose paths and supported version match the installation.

The project's export verifier checks file presence and structural invariants, but it cannot replace a game launch test. Always test the generated MOD with the exact HOI4 version it targets.

## Useful console checks

The following commands are useful while diagnosing a loaded game:

| Command | Purpose |
| --- | --- |
| `tdebug` | Show state, province, and other debug IDs |
| `ai` | Toggle AI while isolating AI-triggered failures |
| `reloadfx all` | Reload visual effects |
| `reload localization` | Reload localisation files |
| `tag TAG` | Switch the active country |
| `Focus.NoChecks` | Ignore focus prerequisites during testing |
| `Focus.AutoComplete` | Complete focuses immediately during testing |

## Sources

- [HOI4 Troubleshooting](https://hoi4.paradoxwikis.com/Troubleshooting)
- [HOI4 Map modding](https://hoi4.paradoxwikis.com/Map_modding)
- [HOI4 Localisation](https://hoi4.paradoxwikis.com/Localisation)
