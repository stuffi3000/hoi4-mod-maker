# Map foundation readiness audit

**Audit date:** 17 September 2026  
**Project:** `projects/Belgium_Map_v1_1.hoi4proj`  
**Target game:** Hearts of Iron IV `1.19.3.0` (`Operation Postern`, revision `c01a3d507f10bd8c713e88234de69ca110618138`)  
**Question:** Is the tool's generated map a sufficiently complete and reliable foundation for proper mod and content development?

## Executive verdict

No—not if “ready” means that the map can now be frozen and treated as a production-quality, feature-complete foundation for all subsequent content. The current export is a good technical scaffold: its province raster, definitions, states, strategic regions, and basic references are internally coherent, and the built-in verifier passes. It is suitable for a focused map-hardening and engine-acceptance phase.

It is not yet suitable as the immutable base for a serious content pipeline. Before content authors build large amounts of history, events, focuses, units, and balance on top of it, the tool or its export contract should address:

- a clean, current-game launch/tick/save/reload acceptance test;
- duplicate vanilla country tags and the separation of a test scenario from a neutral map foundation;
- explicit special-adjacency and chokepoint support, even when the answer for a particular map is “none intended”;
- supply and railway graph semantics, not just endpoint validity;
- version-aware map dimensions, palettes, terrain definitions, and art formats;
- positions/building placement that is more than repeated province centroids;
- complete handling or explicit handoff of terrain and map graphics;
- reporting of every automatic export repair or mutation.

The practical recommendation is therefore:

> Use the current artifact as a prototype and as a pinned test snapshot. Do not yet declare the map foundation complete or begin irreversible, high-volume content development against it. Complete the P0 hardening gates below first. Manual graphical polishing and ordinary scenario/content work can then proceed in parallel only after the province IDs, dimensions, and map topology have been frozen.

This conclusion distinguishes two questions that are easy to conflate:

1. **Can the game parse some of the generated map?** Current evidence says yes, at least far enough to calculate land masses and load a map-like province set.
2. **Is the generated map a complete, version-correct, maintainable production foundation?** Not yet. Passing `verify_mod.py` proves only a subset of that contract.

## Scope and method

The audit compared the generated artifact with:

- the installed base game at `C:\Program Files (x86)\Steam\steamapps\common\Hearts of Iron IV`;
- the project archive `projects/Belgium_Map_v1_1.hoi4proj`;
- map-bearing Workshop mods under `C:\Program Files (x86)\Steam\steamapps\workshop\content\394360`;
- the exporter, importer, domain validators, and documentation in this repository.

There is no repository-local `basegame/` directory in this checkout, so “base game” in this audit means the installed 1.19.3.0 game files. The Workshop comparison intentionally includes both complete total-conversion maps and partial overlays. A file being present in vanilla does not automatically mean that every mod must generate it: many mods inherit it from the base game or a dependency. The important question is whether the tool makes that inheritance explicit and preserves or validates the files that the selected map actually depends on.

The generated artifact was exported to:

`C:\Users\stuff\AppData\Local\Temp\hoi4-map-maker-audit-output`

The following checks were performed:

- the built-in exporter verification and `python -m export.verify_mod ...`;
- independent BMP header, palette, dimension, ID, and raster round-trip checks;
- independent province geometry, state/region, country-capital, railway, and supply-node checks;
- the domain province and river validators;
- direct comparison of vanilla and generated terrain DDS headers and map asset inventories;
- inspection of the existing game logs and the existing `Fantasy World` mod artifact;
- focused repository tests under `tests/export`, `tests/domain`, `tests/test_smoke.py`, and `tests/test_game_assets.py`.

The full test suite could not be collected because this environment lacks the optional `cv2` dependency used by three test modules. The focused suite passed with one skipped test. No clean, current full-game start/tick/save/reload run was available; the existing logs are stale and are treated only as partial evidence.

## What the current export gets right

### Raster and province identity

For the current 5,632 × 2,048 target, the core raster is structurally strong:

| Check | Result |
|---|---|
| Province raster dimensions | 5,632 × 2,048, matching vanilla 1.19.3.0 |
| Definition rows | 12,522 including ID 0; province IDs 1–12,521 |
| Land/sea/lake definitions | 12,100 land, 161 sea, 261 lake |
| Province geometry | 0 X-crossings, 0 non-contiguous provinces, 0 too-small provinces in the domain check |
| Raster-to-definition color round trip | 0 pixel mismatches in the independent check |
| Unknown province colors | 0 |
| Height/rivers/terrain dimensions | All match the province raster |
| Coastal land provinces | 294; the exported coastal spawn count also resolves to 294 |

The province IDs are compact and the generated province-color mapping is reversible. That is a substantially better position than an export that merely produces files with plausible names. The current project also has a clear land/sea/lake classification and no detected raster geometry defects in the tested image.

One important caveat is that the exporter does not simply serialize the project. It performs repairs and normalization in the export path, including tiny-province merging, large-province repair, majority classification, and tile synchronization. In this project, province `9706` contains both 14 land pixels and 1,402 lake pixels. The exporter classifies it as a lake and rewrites the 14 corresponding tile pixels in the export copy. The resulting exported raster is clean, but this is a hidden semantic change unless the user is shown a before/after mutation report. IDs and geometry should be frozen only after those transformations are intentional and recorded.

### Structural map file coverage

The export contains the expected core map files for a conventional 5,632 × 2,048 map:

`provinces.bmp`, `definition.csv`, `heightmap.bmp`, `terrain.bmp`, `rivers.bmp`, `trees.bmp`, `cities.bmp`, `world_normal.bmp`, `default.map`, `continent.txt`, `adjacencies.csv`, `adjacency_rules.txt`, `ambient_object.txt`, `seasons.txt`, `weatherpositions.txt`, `buildings.txt`, `positions.txt`, `railways.txt`, `supply_nodes.txt`, state files, strategic-region files, and legacy supply-area files.

The exporter produced:

- 290 state files covering the 12,100 land provinces;
- 48 strategic regions covering all 12,521 province IDs;
- 20 legacy supply areas (the current 1.19 supply contract is nodes plus railways);
- 421 supply nodes;
- 3,510 railway records;
- six country definitions used by the scenario scaffold: `BEL`, `FRA`, `GER`, `HOL`, `LUX`, and `ENG`.

The independent state/region checks found no state crossing a region, no state without a region, no overlapping region assignments, and no duplicate assignment among the 12,100 state province IDs. All 421 supply-node IDs resolve to valid land provinces. All railway endpoints resolve, and every consecutive endpoint pair is adjacent in the province raster, including the map-edge wrap check. These are useful structural guarantees.

### Definition and reference consistency

The built-in verifier passes all 16 of its checks:

```text
12521 provinces (12100 land)
290 state files, 12100 provinces assigned
48 regions covering 12521 provinces
6 countries: BEL,FRA,GER,HOL,LUX,ENG
All checks passed
```

The current capitals also resolve to land provinces:

| Country | Capital province |
|---|---:|
| BEL | 1068 |
| FRA | 1459 |
| GER | 931 |
| HOL | 223 |
| LUX | 7595 |
| ENG | 648 |

The river validator reports that the river map passes. These results establish that the tool can produce a coherent internal data package for this map size.

## Findings that prevent a production-ready verdict

### 1. The engine acceptance result is not yet proven

The existing artifact under `C:\Users\stuff\Documents\Paradox Interactive\Hearts of Iron IV\mod\fantasy` has byte-identical hashes to the current export for sampled files including `definition.csv`, `provinces.bmp`, `heightmap.bmp`, `terrain.bmp`, `rivers.bmp`, `buildings.txt`, `positions.txt`, one state, and one strategic region. That makes the old game logs relevant, but not conclusive.

The relevant log files were last modified on 11 September 2026, before the current audit export. They contain:

```text
setup.log: Calculated 5 land masses
game.log: Loaded 9707 provinces
error.log: Duplicate Country Tag - BEL/FRA/GER/HOL/LUX/ENG
```

The `9707` figure does not match the current export's 12,521 definition IDs, so it should not be presented as proof that this exact artifact was successfully loaded. The duplicate-tag messages are a real integration defect: the generated scenario declares vanilla-looking tags while the descriptor does not replace the corresponding vanilla country-tag/country definitions. A proper acceptance test must use a fresh isolated mod directory and a unique tag policy, then run against the current installed executable.

At minimum, the acceptance gate should start the current game, reach the main menu, load a 1936 start, enter the map, tick for 30 days, save, reload, and exercise land movement, naval movement, air-region selection, supply/map modes, and province/state selection. The test should capture and classify `error.log`, `game.log`, `setup.log`, and relevant graphical/map logs. A static verifier cannot substitute for this.

There is also a CLI usability issue: under the default PowerShell code page, `cli_export.py` can finish writing the export and then exit with code 1 when printing Unicode check-mark/separator characters. Running with `PYTHONIOENCODING=utf-8` avoids it. A foundation pipeline should not report a successful artifact as a failed command, or vice versa.

### 2. Special adjacencies are an empty layer, not a completed feature

The generated `adjacencies.csv` contains only its header and the sentinel row:

```text
-1;-1;;-1;-1;-1;-1;-1;-1;-1
```

The generated `adjacency_rules.txt` contains comments but no rule blocks. Vanilla 1.19.3.0 has 252 non-sentinel adjacency entries and nine named rule blocks for strategic chokepoints such as Suez, Gibraltar, the Danish belts, and Panama. The Workshop maps similarly vary: some carry extensive special-adjacency data, while a compact local map may legitimately need none.

For the Belgium project, an empty special-adjacency layer may be correct if the intended geography has no straits, canals, impassable crossings, or special land links. The tool must nevertheless make that an explicit, reviewed state. For a general-purpose map maker, the absence of an adjacency/rule editor, import-preservation path, and semantic validator is a blocker. A map can have perfect raster adjacency and still have incorrect naval access or missing chokepoints.

Required behavior:

- represent sea crossings, canals, straits, impassable borders, through-province links, and their rule references;
- preserve imported entries unless the user explicitly removes them;
- validate every referenced province, rule, icon, and coordinate;
- show a “no special adjacencies intended” declaration in the export manifest.

### 3. The logistics graph is syntactically valid but not semantically complete

All current railway lines have valid land endpoints and raster-adjacent consecutive provinces. That is the necessary first check, not the final one. The exported railway graph has 3,510 edges, 2,988 vertices, and 327 connected components. Forty-eight of the 421 supply nodes are not present in the railway graph.

Some disconnected components can be intentional—an island, an isolated starting network, or a node supplied by sea—but the exporter currently gives no semantic explanation for them. It also has fallback behavior that can create a self-loop railway record when real network data is absent. A production map foundation needs a graph-level report that distinguishes:

- connected mainland rail networks;
- legitimate island or overseas networks;
- supply nodes that are intentionally port/convoy supplied;
- nodes with no usable route or no reachable port;
- rail segments whose level and capacity are insufficient for the intended scenario.

For this map, the 48 disconnected supply nodes must be reviewed before balance work begins. If they are intentional, record why; if not, fix the network in the map tool.

### 4. Positions and building placement are generated scaffolding

The output `positions.txt` has an entry for each province with six mechanically generated position slots. In the inspected output, the slots are repeated province centers, all rotations are `0.000`, all heights are `0.000`, and the vertical coordinate is the same `9.500`. This is enough to provide parseable coordinates, but not enough for a polished map:

- unit counters can overlap in dense provinces;
- city, victory-point, port, air-base, and naval-base positions can be visually or functionally misplaced;
- repeated rotations and heights ignore terrain and map art;
- there is no clear collision or “position lies on the intended province surface” review screen.

The generated `buildings.txt` contains 3,558 records, including one of each major building type for most of the 290 states, 294 coastal naval-base spawns, and 37 dockyard/coastal-bunker records. These records are useful to make a test scenario playable, but many are placeholders produced by exporter defaults. They should not be treated as the final placement or balance of the map.

The same applies to weather positions: the tool writes one `small` weather position per strategic region, whereas vanilla uses multiple, varied positions in large regions. This is a visual/gameplay tuning issue rather than a province parser issue, but it belongs in the foundation handoff if the tool claims to create a complete map.

### 5. The exporter mixes map foundation with scenario and content scaffolding

The current full export writes much more than the map substrate. It generates country files, country tags, flags, portraits, leaders/characters, histories, OOBs, localization, a bookmark, ideology/category data, and dynamic country placeholders `D01`–`D75`. It also calls `fill_default_state_data()` and filled 167 states with generated terrain-based resources, manpower, and buildings in this run.

The inspected first state illustrates the issue: the project state had no resources, but the export added aluminium; it also emitted manpower, a state category, infrastructure, factories, an air base, and three victory-point entries. Those values are suitable for a smoke-test scenario, not neutral map foundation data. Randomized or inferred values become dangerous once content authors start balancing around them.

The exporter should offer two visibly different products:

1. **Foundation export:** map geometry, map images and their validated formats, province terrain, state province membership, strategic-region membership, supply topology, special adjacencies, and reviewed placement geometry. Any state files needed by the engine should be minimal and clearly marked as technical fixtures.
2. **Playable test scenario:** explicit, disposable owners, cores, resources, manpower, buildings, victory points, country definitions, OOBs, bookmark, and other content needed to exercise the map.

The second product is valuable, but it must not be confused with the first or silently modify the user's project model.

### 6. Graphics output is incomplete and has format mismatches

The map can inherit many art files from vanilla, so a small output directory is not automatically wrong. However, the current result is not an independent, version-complete graphical foundation.

#### Terrain asset inventory

Vanilla 1.19.3.0 contains 64 files under `map/terrain`, covering atlas/normal data, borders, city lights, colormaps, fog of war, ice, lean, mud, reflections, river surfaces, snow, straits, underwater shading, and tree tint/season data. The current export emits only five DDS files:

```text
colormap_rgb_cityemissivemask_a.dds
colormap_water_0.dds
colormap_water_1.dds
colormap_water_2.dds
fow_rgb_waterspec_a.dds
```

This is acceptable only if the mod intentionally inherits the remaining files and those inherited assets are compatible with the new map. A total conversion that expects self-contained map art needs either a complete asset pipeline or an explicit manual-art handoff with validation.

#### DDS headers

The generated main colormap has the same 2,816 × 1,024 dimensions and basic uncompressed format as the vanilla main colormap. The water and FOW outputs do not match the vanilla format contract:

| Asset | Vanilla | Generated output |
|---|---|---|
| `colormap_water_0.dds` | 2,816 × 1,024, DXT5/BC3, no ordinary mip chain | 2,816 × 1,024, uncompressed BGRA8, one mip |
| `colormap_water_1.dds` | 1,408 × 512, DXT5/BC3 | 1,408 × 512, uncompressed BGRA8 |
| `colormap_water_2.dds` | 704 × 256, DXT5/BC3 | 704 × 256, uncompressed BGRA8 |
| `fow_rgb_waterspec_a.dds` | DXT5/BC3, 12 mips | 2,816 × 1,024, uncompressed BGRA8, one mip |

Some decoders may accept these files, but the mismatch affects compatibility, memory use, and visual behavior. The writer should either emit the target game's expected BC3/DXT5 and mip headers or preserve a validated source asset.

#### Trees, terrain palette, and ambient objects

The generated `trees.bmp` is 1,408 × 512. The vanilla map and the observed Kaiserreich, A Very British Civil War, Millennium Dawn, and Road to 56 maps use 1,650 × 600 for the same 5,632 × 2,048 map family; Old World Blues uses 1,650 × 675 for its 5,632 × 2,304 map. The tool's current map-divided-by-four rule therefore does not match the installed baseline. It may be an intentional engine contract for a different asset path, but it must be resolved with a current-game visual test and a version-aware writer.

The generated tree pixels also use only indices 5 and 6, while vanilla uses a wider set of indices. In addition, `default.map` declares tree indices `{ 3 4 7 10 }`, so the relationship between generated pixels, palette entries, and terrain declarations is not self-evidently correct.

The terrain writer looks for the source terrain palette through the hard-coded `DEFAULT_HOI4_PATH` (`G:/SteamLibrary/...`). This machine's configured installation is on `C:` and is found by the newer game-asset discovery service, but the terrain writer falls back to a synthetic palette. The output palette consequently differs from the installed vanilla terrain palette and contains only a small set of synthetic entries. Terrain index semantics—not just the visible RGB colors—must be version-aware.

The base game's `ambient_object.txt` includes wind, water, frame, and DLC-specific ambient objects. The current output contains only the top/bottom/logo frame objects. This may be harmless when inheriting vanilla visual definitions, but it is another sign that the exporter currently produces a minimal scaffold rather than a complete map-art package.

### 7. Version and map-size assumptions are too narrow

The current Belgium export uses a supported 5,632 × 2,048 size, so this limitation does not invalidate this particular raster. It does limit the tool's claim to be a general foundation generator. The verifier and constants currently recognize only four province-map sizes: 2,048 × 1,024, 3,072 × 1,536, 4,096 × 2,048, and 5,632 × 2,048.

The installed Workshop maps demonstrate real variants outside that list:

- Old World Blues and its East Coast Rebirth overlay use 5,632 × 2,304;
- Star Wars: Palpatine's Gamble uses 3,328 × 3,840;
- Old World Blues has 21,832 province IDs, well beyond the tool's current 19,000 engine guidance and 15,000 default constant.

This does not prove that every arbitrary dimension or province count is legal in every HOI4 version. It proves that the tool needs a selected-game-version/selected-map-profile contract instead of a single hard-coded set of assumptions. The export should fail early with a targeted explanation when dimensions, province count, tree dimensions, terrain indices, or asset formats do not match the selected game and map profile.

The generated `defines` file also unconditionally sets `NDefines.NGame.MAX_PROVINCES` to at least 25,000. That is an aggressive global override for a 12,521-province map and is not neutral foundation data. It should be generated only when required by the target version/map, with the reason recorded in the manifest.

### 8. Optional, inherited, and deprecated files need an explicit policy

The base game has an empty `positions.txt`, while several complete Workshop maps carry positions and others omit them. Some mods carry `map/colors.txt`; the importer classifies that file as structural but the exporter does not emit it, so importing such a mod can silently drop it. Several older or mod-specific maps also contain `airports.txt` or `rocketsites.txt` variants. The current output writes empty compatibility files, including `rocket_sites.txt`.

The correct behavior is not necessarily “always write every file.” It is:

- identify which files are required by the selected game version;
- identify which files are intentionally inherited from vanilla or a dependency;
- preserve imported files that are in scope, or warn clearly when they are unsupported;
- avoid emitting empty, obsolete, or misspelled compatibility files without a reason;
- include the resolution in an export manifest.

## Vanilla and Workshop comparison

The following inventory is from the installed map roots. `Map files` includes files in the map root and its immediate map subdirectories, not the entire mod. Counts are useful for identifying scope, not as a quality score.

| Map | Province raster | Max province ID | Map files | Notable pattern |
|---|---:|---:|---:|---|
| Vanilla 1.19.3.0 | 5,632 × 2,048 | 13,413 | — | 304 strategic regions, one legacy supply area, extensive special adjacencies, 64 terrain assets |
| Current tool output | 5,632 × 2,048 | 12,521 | 96 | 290 states, 48 regions, 20 legacy supply areas, no special adjacencies/rules |
| Kaiserreich | 5,632 × 2,048 | 13,906 | 295 | Omits some optional map files such as cities/default/positions and inherits them |
| Old World Blues | 5,632 × 2,304 | 21,832 | 601 | Broad custom map with extensive assets and custom-size raster |
| A Very British Civil War | 5,632 × 2,048 | 5,600 | 111 | Includes airports/rocketsites and custom art artifacts |
| Star Wars: Palpatine's Gamble | 3,328 × 3,840 | 12,235 | 553 | Nonstandard dimensions and additional source art files |
| East Coast Rebirth | 5,632 × 2,304 | 21,832 | 32 | Partial overlay; inherits much of the OWB map |
| Millennium Dawn | 5,632 × 2,048 | 13,322 | 911 | Complete custom scenario/map package with optional map files |
| The Road to 56 | 5,632 × 2,048 | 13,534 | 327 | Selective overrides, including colors/default/positions/seasons |
| Rustbelt Rising | inherited/overlay | inherited | 50 | Partial OWB-related overlay |
| OWB: Monarchs and Margaritas | inherited/overlay | inherited | 13 | Very small dependency overlay |

Installed items with no map files—such as Instant War, HOI4 Historical Flag Mod, Player-Led Peace Conferences, Core With Compliance++, Landlord, Enclave Officers+, Enclave Reborn Redux, and OWB: Fountain of Dreams—are content overlays and inherit their map. The downloaded Cold War Iron Curtain item was present as a zip without a usable descriptor/map root in the inspected Workshop directory.

The comparison supports three conclusions:

1. The tool's current core-file set is reasonable for a map that intentionally inherits vanilla art and optional definitions.
2. Complete total conversions commonly carry far more map-specific assets and sometimes use dimensions outside the tool's current assumptions.
3. Dependency overlays are normal and valuable. The tool therefore needs to model inheritance and dependency resolution explicitly rather than treating missing files as either automatically correct or automatically incomplete.

## What belongs to the foundation and what belongs to content development

The handoff boundary should be explicit. Changing a foundation item after content is written can invalidate thousands of references; changing ordinary content should not require regenerating the province raster.

### Foundation owned by the map tool

The tool should own, generate, preserve, and validate:

- target game version, map dimensions, coordinate and wrap conventions;
- province raster, stable IDs, province colors, land/sea/lake/coastal classification, and geometry;
- height, rivers, province terrain, tree/city masks, and the technical format/provenance of their bitmap assets;
- terrain registry/palette compatibility with the selected game version;
- continent assignment;
- state **province membership** and stable state IDs;
- strategic-region membership and weather placement geometry;
- current supply-node positions and railway topology; legacy supply-area membership only as an explicitly versioned compatibility artifact;
- special adjacencies, canals, straits, impassable borders, and rule references;
- province/state/city/port/building spawn coordinates and coordinate QA;
- map-specific graphical assets that are part of the selected foundation, or a manifest of assets intentionally inherited from vanilla/dependencies;
- a reproducible export manifest, source hashes, output hashes, ID mapping, warnings, and all automatic repairs.

State membership is foundational because it is the stable grouping used by history and gameplay. It should not be confused with state history.

### Ordinary mod/content workflow after the foundation is frozen

These should normally be authored in the conventional mod workflow—text editors, content tools, image editors, and source control—on top of the frozen map snapshot:

- state names, localization, state categories, owners, controllers, cores, claims, manpower, resources, starting buildings, and victory-point names/values;
- country tags, country colors/names, flags, portraits, leaders, characters, ideologies, national spirits, and country history;
- focuses, events, decisions, missions, technologies, equipment, units, templates, OOBs, AI, diplomacy, factions, and peace behavior;
- bookmarks, scripted effects, scripted triggers, balance, testing scenarios, and narrative content;
- final visual art direction and manual polish of colormaps, normals, city lights, terrain atlases, trees, water, fog, and ambient objects.

There are legitimate overlaps. A map tool can provide starter victory-point coordinates, building spawn points, or a test state's default owner, but those should be clearly labeled as scaffolding. The content workflow owns their final names, values, history, and balance. A graphic artist can manually produce terrain art after the tool has frozen the raster and supplied the correct dimensions, palette, and asset contract.

## Recommended implementation plan

### P0 — required before declaring the foundation frozen

#### 1. Add explicit export profiles and a manifest

Add a `foundation` profile and a separate `playable-test-scenario` profile. The first should not call `fill_default_state_data()` or silently create randomized gameplay values. The second can create disposable values, but its output should be visibly marked as a test fixture.

Write a machine-readable `foundation_manifest.json` alongside the export. It should record at least:

```json
{
  "game_version": "1.19.3.0",
  "map_dimensions": [5632, 2048],
  "province_id_range": [1, 12521],
  "source_project_hash": "...",
  "output_hashes": {"map/provinces.bmp": "..."},
  "inherited_files": ["map/terrain/atlas0.dds"],
  "automatic_repairs": [],
  "special_adjacencies": {"status": "none_intended", "entries": 0},
  "qa": {"static": "pass", "engine_acceptance": "pass"}
}
```

Do not mutate the live project managers as a side effect of export. Export from a copy, show the before/after ID and pixel changes, and require an explicit confirmation before accepting repairs. Once approved, provide an ID-freeze/mapping file for content authors.

#### 2. Build a real engine acceptance harness

The tool needs a repeatable test that creates an isolated mod using unique test country tags, launches the selected game version, and verifies:

1. main menu and map initialization;
2. new-game setup and a 1936 start;
3. 30 days of ticking;
4. land, naval, air, supply, and map-mode interactions;
5. save, reload, and continued ticking;
6. absence of map, province, terrain, country-tag, asset, and script errors.

Make log parsing part of the result, with a fresh timestamp/run ID so stale logs cannot be mistaken for evidence. The current duplicate `BEL`/`FRA`/`GER`/`HOL`/`LUX`/`ENG` messages should fail the test until the test scenario's replace-path/tag policy is corrected.

#### 3. Expand static QA beyond the current verifier

Keep `export/verify_mod.py`, but add checks for:

- exact BMP dimensions, bit depth, compression, row orientation, palette size/semantics, and file-size/header consistency;
- one-to-one definition/raster coverage and all pixel values;
- 4-connectivity, X-crossings, minimum area, bounding boxes, map-edge wrap behavior, and mixed province types;
- coast flags, ports, naval bases, cities, victory points, and terrain compatibility;
- river source/outlet/width/level continuity;
- all state, region, supply-node, railway, adjacency, building, and position references, plus any intentionally retained legacy supply-area references;
- railway neighbor adjacency, connected components, supply-node reachability, and intentional overseas exceptions;
- position surfaces, province ownership of coordinates, duplicate/collision checks, and building-type legality;
- actual selected-version terrain and map-art asset contracts.

The report should distinguish errors, warnings, and intentional exceptions. “No special adjacencies intended” and “48 isolated supply nodes are intentional islands” are review decisions, not silently ignored failures.

#### 4. Add special-adjacency authoring and validation

Create a data model and editor for the complete adjacency/rule contract. Include a map overlay showing the connection, its direction/type, access rule, movement/naval implications, and every referenced province. Add import/export round-trip tests using vanilla Suez/Gibraltar/Danish/Panama examples and at least one Workshop map.

#### 5. Add a logistics graph review

Show the railway and supply-node graph as an overlay, highlight connected components, and flag supply nodes with no meaningful route. Remove or loudly flag self-loop fallback records. Support intentional island/convoy exceptions rather than treating every disconnected component as equivalent.

#### 6. Add placement editing and collision checks

Provide per-province/state editing for the six unit slots, victory points, ports, naval bases, air bases, radar, railways, and other building objects. Allow rotation and height values, show the actual map surface, and validate that an object belongs to the intended province and does not collide with another object. Repeated centroids should be a visible provisional state, not the final output.

### P1 — required for a robust graphical and version-aware foundation

#### 7. Make game asset discovery consistent

Use the configured installation returned by `services/game_assets.find_hoi4_install()` everywhere. In particular, remove the terrain writer's dependency on the hard-coded `DEFAULT_HOI4_PATH`, which caused a synthetic terrain palette on this machine.

Introduce a versioned terrain registry that reads or verifies `common/terrain/00_terrain.txt`, including terrain colors, texture indices, spawn-city flags, snow/permanent-snow behavior, and custom terrain names. Do not assume that a displayed RGB palette alone defines terrain semantics.

#### 8. Fix DDS format generation or preserve validated assets

For water and FOW, emit the selected game's expected BC3/DXT5 blocks and mipmap/header contract, or copy a validated compatible source asset and record its provenance. Add a DDS header and mip-chain test. Treat generated color/normal art as a preview until it has been visually reviewed in the target game.

#### 9. Resolve tree-map and other dimension contracts

Determine the actual engine contract for `trees.bmp` for each supported map profile and match the observed 1,650 × 600 / 1,650 × 675 assets where appropriate. Align `default.map` tree declarations and tree palette indices with the target version. Add dimension tests for world normals, cities, terrain masks, water levels, FOW, atlas layers, and city lights.

#### 10. Preserve or explicitly resolve optional files

Add an asset inventory with three states: generated, inherited, and intentionally omitted. Handle `map/colors.txt` explicitly. Version-gate airport/rocket-site files and avoid writing empty legacy names unless the selected game actually requires them. Preserve imported art and definitions when the tool does not edit them, or emit an actionable warning.

### P2 — quality and maintainability improvements

- Replace the unconditional `MAX_PROVINCES = 25000` behavior with a target-version and actual-need calculation.
- Support arbitrary validated map profiles instead of four hard-coded dimensions.
- Make `default.map` settings such as `river_max_level` either effective or explicitly unsupported.
- Fix CLI output encoding so a successful export has a reliable exit code in PowerShell and CI.
- Add regression fixtures for vanilla, Kaiserreich, Old World Blues, A Very British Civil War, Star Wars, Millennium Dawn, Road to 56, and partial dependency overlays.
- Keep generated foundation output separate from generated disposable test content in source control.

## Project-specific gate for Belgium Map v1.1

The current Belgium artifact should be considered **“structurally promising, not frozen.”** Before using it as the base for the proper mod:

1. Select and record HOI4 1.19.3.0 as the target profile.
2. Decide whether the 12,521 IDs and current 290-state/48-region partition are final.
3. Review and accept or correct the mixed province `9706` normalization.
4. Explicitly record whether zero special adjacencies is intended for this geography.
5. Resolve the 327 railway components and 48 supply nodes absent from the railway graph.
6. Replace repeated centroid positions and placeholder building/state data with either reviewed foundation geometry or a clearly separated test scaffold.
7. Fix the configured-installation terrain palette path, tree dimensions/index contract, and generated DDS compression/mipmap contract.
8. Create a clean unique-tag test mod and complete the current-game start/tick/save/reload run.
9. Freeze the final raster, IDs, dimensions, topology, and foundation manifest.

After step 9, content authors can safely build state history and ordinary mod content. If the raster or IDs change afterward, the content branch should be treated as needing a reference migration rather than a routine content update.

## Readiness matrix

| Capability | Current state | Decision |
|---|---|---|
| Province raster and ID round trip | Strong for 5,632 × 2,048; independent check passed | Pass for prototype; freeze only after mutation review |
| Province geometry | No detected crossings/non-contiguous/too-small provinces | Pass, with broader edge-case tests recommended |
| Terrain/height/river dimensions | Present and dimensionally aligned | Needs version/palette and visual hardening |
| State and strategic-region membership | Internally consistent | Pass structurally; review design before freeze |
| Supply nodes/rail endpoints | References valid; graph is fragmented; legacy supply areas are deprecated | Needs hardening |
| Special adjacencies | Empty output | Conditional for Belgium; blocker for general maps until explicit |
| Positions/buildings/weather | Parseable generated placeholders | Needs manual/tool-assisted placement work |
| Terrain graphics | Partial generated/inherited set | Needs explicit inheritance or art pipeline |
| DDS water/FOW | Dimensions present; compression/mips differ from vanilla | Needs implementation fix or validated preservation |
| Trees | Output dimensions/index usage differ from observed baseline | Needs engine-tested fix |
| Version/map-size support | Current project size works; installed mods expose unsupported profiles | Needs version-aware profile system |
| Scenario/content isolation | Full exporter adds gameplay data and duplicate vanilla tags | Blocker before a clean production handoff |
| Game acceptance | Only stale partial log evidence | Blocker before declaring ready |

## Final answer to the readiness question

The tool has already crossed the threshold from “unusable export” to “credible map prototype.” It has not crossed the threshold from “prototype” to “feature-complete foundation.” The most important remaining work is not adding more country content; it is making the map export deterministic, version-aware, graphically compatible, semantically validated, and demonstrably accepted by a clean current-game run.

The proper workflow should be:

```text
map-tool foundation + QA + engine acceptance
                 |
                 v
freeze IDs/topology/assets/manifest
                 |
                 v
traditional mod workflow: history, countries, scripts, OOBs, balance, narrative, art polish
```

Manual art creation and detailed scenario content do not all need to be automated by this tool. They do need a stable, validated foundation and a clear inherited/generated/handed-off asset contract. Until that contract and the P0 gates are in place, starting the full proper mod risks building content around hidden exporter repairs, duplicate tags, incomplete logistics, placeholder placements, and asset formats that have not been proven in the target game.

## Relevant repository implementation points

- [`export/mod_exporter.py`](../export/mod_exporter.py) — full export flow, automatic province/tile repairs, map layers, states, buildings, positions, and content scaffolding.
- [`export/verify_mod.py`](../export/verify_mod.py) — current static verifier; useful baseline but not a game acceptance test.
- [`services/export_service.py`](../services/export_service.py) — default state-data filling invoked by the current full export path.
- [`export/writers/map/colormap_dds.py`](../export/writers/map/colormap_dds.py) — generated colormap, water, and FOW DDS headers/data.
- [`export/writers/map/trees_bmp.py`](../export/writers/map/trees_bmp.py) — current tree-map dimension and index generation.
- [`export/writers/map/positions.py`](../export/writers/map/positions.py) — current repeated-centroid position generation.
- [`export/writers/map/buildings.py`](../export/writers/map/buildings.py) — current building and naval-base scaffolding.
- [`services/import_service.py`](../services/import_service.py) — structural/art file classification and optional-file preservation behavior.
- [`data/constants.py`](../data/constants.py) and [`services/game_assets.py`](../services/game_assets.py) — map-size, province-count, install-path, and terrain-registry assumptions.
- [`docs/wiki/README.md`](wiki/README.md) — index and maintenance rules for the wiki-derived references.
- [`docs/wiki/map-core.md`](wiki/map-core.md) and [`docs/wiki/map-visual-assets.md`](wiki/map-visual-assets.md) — structural map files and visual asset contracts.
- [`docs/wiki/states-regions.md`](wiki/states-regions.md), [`docs/wiki/buildings-supply.md`](wiki/buildings-supply.md), and [`docs/wiki/logistics-and-adjacency.md`](wiki/logistics-and-adjacency.md) — state, position, building, railway, supply, and adjacency expectations.
- [`docs/wiki/tool-export-contract.md`](wiki/tool-export-contract.md) — generated, preserved, inherited, omitted, and unsupported output policy.
