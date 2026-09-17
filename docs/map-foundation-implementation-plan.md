# Map foundation implementation plan

**Status:** Proposed implementation roadmap

**Date:** 17 September 2026

**Source audit:** [Map foundation readiness audit](map-foundation-readiness-audit.md)
**Primary target:** Hearts of Iron IV 1.19.3.0 and `projects/Belgium_Map_v1_1.hoi4proj`

**Reference set:** [HOI4 wiki reference index](wiki/README.md) and the
[tool export contract](wiki/tool-export-contract.md)

## 1. Objective

Turn the current exporter from a successful map/scenario generator into a deterministic, version-aware foundation pipeline that can safely be frozen before conventional mod development begins.

The finished tool must be able to answer all of these questions from one export result:

1. What exact project data and game version produced this foundation?
2. Which files were generated, preserved, inherited, omitted, or unsupported?
3. Did export change any province IDs, pixels, classifications, states, or references?
4. Which static checks passed, failed, or were accepted as intentional exceptions?
5. Did this exact artifact pass a clean in-game start, tick, save, and reload test?
6. Is the foundation frozen, and what would a new project change invalidate?
7. Which remaining files and values belong to ordinary content development rather than map generation?

The implementation is complete when the Belgium project can produce a reproducible foundation package and a separate playable acceptance mod, both tied to the same manifest, and the package passes the release gates in section 15.

## 2. Scope and boundaries

### In scope for this plan

- target-game detection and map-profile contracts;
- project schema/version migration;
- immutable export snapshots and explicit repair plans;
- foundation, acceptance, and scaffold export profiles;
- map raster, topology, reference, asset, and graph validation;
- special adjacencies and adjacency-rule review;
- railways, supply nodes, and disconnected-network exceptions;
- map-object, unit-slot, port, building, and weather positions;
- terrain registries, indexed BMP palettes, tree maps, DDS formats, and asset inheritance;
- export manifests, hashes, foundation locks, and breaking-change reports;
- assisted local engine acceptance and log analysis;
- export/readiness user interface and CLI support;
- tests, migration compatibility, and documentation.

### Explicitly outside the foundation

The tool may generate disposable examples for testing, but these remain conventional mod content and are not authoritative foundation data:

- historical ownership, controllers, cores, claims, manpower, resources, and balance;
- final state categories, starting industry, forts, and victory-point values;
- country tags, names, colors, flags, portraits, leaders, ideologies, and OOBs;
- focuses, events, decisions, technologies, equipment, AI, diplomacy, and narrative;
- final hand-painted colormaps, terrain atlases, normal maps, city lights, and other artistic polish.

The tool must support preserving, validating, and handing off manually created map art. It does not need to replace a graphics editor or automate creative content production to be considered complete.

## 3. Definition of done

The map-foundation capability is production-ready only when all of the following are true:

- export never mutates the live project as an unreported side effect;
- every proposed repair is identified before writing and appears in the manifest;
- province IDs and dependent references can be frozen and compared with a lock file;
- the selected game install/version controls dimensions, terrain definitions, palettes, assets, descriptor version, and validation rules;
- foundation export does not inject randomized gameplay values;
- a separately generated acceptance mod uses collision-free test tags and content;
- the full static validation suite has no unaccepted errors;
- special adjacencies are either defined and valid or explicitly reviewed as unnecessary;
- disconnected logistics components are explained or fixed;
- authored/fallback positions are visibly distinguishable and validated;
- generated or preserved map graphics meet the selected profile's format contract;
- the exact artifact has a fresh successful engine-acceptance record;
- a lock comparison reports any later breaking map change before content export;
- old projects load without data loss and old export callers receive a documented migration path.

## 4. Current architecture to retain

The repository already has most of the right architectural seams. This plan extends them rather than replacing the application:

- `model/project.py` is the aggregate root for map data and managers.
- `domain/managers/` already owns states, countries, continents, adjacencies, adjacency rules, railways, supply nodes, strategic regions, and export settings.
- `commands/` and `controllers/` provide undoable editing and UI orchestration.
- `features/map/logistics/` already exposes adjacency, rule, railway, and supply editing surfaces.
- `services/export_service.py` is the natural application-service boundary for export orchestration.
- `export/writers/` already provides file-focused writers.
- `services/readiness_service.py` is the shared readiness entry point for the UI.
- `services/game_assets.py` already discovers the configured installation and reads game assets.
- `project.assets` and `dirty_assets` already distinguish preserved from regenerated art.

The main architectural defects to remove are:

- `export_mod()` mutates managers and fills gameplay data before export;
- `export_full_mod()` combines planning, repair, writing, fallback generation, content generation, and verification;
- the `scope` dictionary is a file toggle list rather than a semantic export profile;
- validators are split between readiness, pre-export repair, post-export checks, domain helpers, and `verify_mod.py`;
- automatic fixes do not have a typed, reviewable change set;
- game target and asset contracts remain partly hard-coded;
- map placements do not have an authored project model;
- the current art sidecar manifest records only clean/dirty state, not provenance or compatibility;
- engine testing is external to the export result.

## 5. Target architecture

### 5.1 Export flow

```text
Project
  |
  v
immutable FoundationSnapshot + selected GameTarget
  |
  v
ExportPlanner -----> ValidationReport + proposed RepairActions
  |                                      |
  |                              user/policy decision
  |                                      |
  +-------------------------------> accepted export snapshot
                                             |
                                             v
                                  staged file writers
                                             |
                                             v
                           artifact validators + hash inventory
                                             |
                         +-------------------+-------------------+
                         |                                       |
                         v                                       v
                FoundationPackage                    AcceptanceMod overlay
                         |                                       |
                         v                                       v
                 FoundationManifest                     game run + log scan
                         |                                       |
                         +-------------------+-------------------+
                                             |
                                             v
                                     FoundationLock
```

Writers should receive an already approved immutable snapshot and a resolved asset plan. They should not decide whether to repair project data, invent content, or discover the game installation while writing a file.

### 5.2 Core data contracts

The following are suggested modules and types. Exact names may change, but the boundaries should remain.

| Contract | Suggested location | Responsibility |
|---|---|---|
| `GameTarget` | `domain/game_profile.py` | Installed path, raw version, revision, supported-version string, platform, and profile ID |
| `MapAssetContract` | `domain/game_profile.py` | Required/optional files, dimensions, bit depth, palettes, DDS encoding, mip rules, and inheritance policy |
| `ExportProfile` | `domain/export_contract.py` | Foundation package, acceptance mod, or full scaffold behavior |
| `FoundationSnapshot` | `domain/export_contract.py` | Deep, immutable copy of arrays, managers, settings, assets, and project metadata |
| `ValidationFinding` | `domain/validation.py` | Stable code, severity, layer, message, references, fixability, and evidence |
| `RepairAction` | `domain/export_contract.py` | Proposed change, affected IDs/pixels, before/after summary, safety class, and dependency remap |
| `AssetResolution` | `domain/assets.py` | Generated, preserved, inherited, omitted, or unsupported asset decision and provenance |
| `ExportPlan` | `domain/export_contract.py` | Approved profile, target, snapshot, layers, repairs, assets, and output policy |
| `ExportResult` | `domain/export_contract.py` | Written files, findings, hashes, mutations, timing, and manifest path |
| `FoundationManifest` | `domain/foundation_manifest.py` | Serializable provenance and validation record for an artifact |
| `FoundationLock` | `domain/foundation_manifest.py` | Frozen identity/topology hashes and accepted exceptions used by later comparisons |

All contracts should be plain Python dataclasses or similarly dependency-free domain objects. Qt objects, widgets, open file handles, and mutable `Project` references must not enter the export domain.

### 5.3 Export profiles

Replace the current “all/map only/checkboxes” mental model with these profiles:

| Profile | Purpose | Content behavior |
|---|---|---|
| `foundation` | Stable package handed to mod developers | Writes map-owned layers, state geography, reviewed placements, manifest, and optional minimal state shells; never randomizes gameplay data |
| `acceptance` | Disposable standalone mod for engine testing | Composes the foundation with uniquely tagged test countries, minimal owners/history/OOB/bookmark, and explicit test-only placeholders |
| `scaffold` | Optional starting point for users who want generated content | Preserves current broad behavior, but labels generated values and keeps them outside the foundation lock |
| `legacy_full` | Temporary compatibility mode | Reproduces the old full exporter for one deprecation cycle |

Advanced layer selection can remain, but incompatible combinations must be rejected by the planner. For example, supply files can use states from the project even if state-history files are not written; writers should not infer that state data is absent just because the `states` output layer is disabled.

### 5.4 Foundation lifecycle

Each project gains an explicit lifecycle:

| State | Meaning | Allowed automatic behavior |
|---|---|---|
| `draft` | Geometry and IDs are still changing | Repairs and compaction may be proposed; all changes are reported |
| `candidate` | Intended final topology undergoing validation | Safe repairs require confirmation; ID/topology changes invalidate prior candidate results |
| `frozen` | IDs, raster, state membership, topology, and asset contract are locked | No implicit compaction or geometry/classification repair; breaking changes require “unfreeze” |
| `accepted` | Frozen artifact passed the selected game acceptance run | Any breaking lock difference returns the project to `candidate` |

This state belongs in project metadata, not in a UI-only preference.

## 6. Milestone overview and dependencies

| Milestone | Outcome | Depends on | Exit gate |
|---|---|---|---|
| M0 | Reproducible baseline and reliable tests/CLI | None | Existing output characterized; full development test environment works |
| M1 | Versioned game/profile and project metadata | M0 | Current and legacy projects resolve an explicit target profile |
| M2 | Immutable export planner, profiles, and staging | M1 | No live-project mutation; foundation and acceptance outputs are separate |
| M3 | Shared validation engine, manifest, and deterministic hashes | M2 | Static gate and manifest describe the complete artifact |
| M4 | Reviewed adjacencies and logistics semantics | M3 | No unexplained adjacency/logistics blocker |
| M5 | Authored placements and non-placeholder building geometry | M3 | Placement fallback is visible; required coordinates validate |
| M6 | Version-aware graphics and asset-resolution pipeline | M1, M3 | Every map asset is generated/preserved/inherited/omitted explicitly and validates |
| M7 | Assisted engine acceptance | M2, M3; final run after M4–M6 | Fresh exact-artifact start/tick/save/reload record passes |
| M8 | Foundation freeze, diff, and content handoff | M4–M7 | Belgium lock created; breaking changes are detectable |
| M9 | Legacy cleanup and release candidate | M8 | Old path deprecated/removed after parity and migration tests |

M4, M5, and most of M6 can proceed in parallel after the M3 contracts are stable. An early M7 vertical slice should validate the acceptance-mod design before investing in every editor; the release acceptance run happens after M4–M6.

## 7. Detailed implementation work

## M0 — baseline reliability and regression evidence

### M0.1 Capture a legal regression baseline

Add metadata-only fixtures for the current Belgium export and installed vanilla profile. Do not commit copyrighted base-game or Workshop binaries.

Suggested files:

- `tests/fixtures/foundation/belgium_v1_1_summary.json`
- `tests/fixtures/game_profiles/hoi4_1_19_3_headers.json`
- `tests/fixtures/assets/dds_contracts.json`
- `tests/foundation/test_belgium_baseline.py`

The Belgium summary should include dimensions, ID range, type counts, state/region/supply counts, graph counts, selected file hashes, BMP headers, and known review findings. Header fixtures may contain dimensions, flags, compression names, mip counts, and hashes, but no copied game image data.

Acceptance criteria:

- a baseline test detects a changed province count, type count, region coverage, or output-file inventory;
- the fixture clearly distinguishes expected current defects from desired final results;
- local opt-in comparison can refresh evidence from a user-selected game install without changing the committed fixture automatically.

### M0.2 Make the test environment complete

`opencv-python` is already declared in `requirements.txt`, but the audit environment lacked `cv2` and could not collect the full suite. Ensure the documented development/CI setup installs all declared test dependencies. If OpenCV is genuinely optional at runtime, use a separate optional dependency group and `pytest.importorskip()` only for tests that are truly optional; otherwise fail setup early with an actionable message.

Add pytest markers:

- `unit` — no Qt, game, or external files;
- `integration` — repository-generated files only;
- `slow` — full-size maps;
- `game_install` — requires a local HOI4 installation;
- `workshop` — optional local compatibility probes;
- `engine` — launches the closed-source game and is never a normal CI requirement.

### M0.3 Fix CLI result reliability

Update `cli_export.py` so Unicode output cannot turn a completed export into exit code 1 under Windows PowerShell. Prefer UTF-8 stream configuration with an ASCII-safe fallback. Export success, validation failure, and command failure must use distinct exit codes.

Add CLI tests that run under an ASCII-compatible mocked stream and verify:

- successful export exits 0;
- validation blockers use a documented non-zero code;
- writer exceptions use a different non-zero code;
- generated output is never reported as successful before final verification.

### M0.4 Record performance and memory baselines

Measure the current full-size Belgium export and the major validator passes. Store the measurements in development documentation, not as brittle timing assertions. New algorithms should operate by full-array passes or cached province statistics rather than rescanning a 5,632 × 2,048 raster for every province.

### M0 implementation tracking

- [x] **M0.1 — regression evidence:** metadata-only Belgium, HOI4 1.19.3.0 header, and DDS contract fixtures; baseline comparison and explicit refresh tooling added.
- [x] **M0.2 — test environment:** declared dependency setup documented, missing required packages fail collection with an actionable message, and all requested pytest markers are registered.
- [x] **M0.3 — CLI reliability:** UTF-8/ASCII-safe output, distinct success/validation/command exit codes, final-verification ordering, and focused mocked-stream tests added.
- [x] **M0.4 — performance evidence:** the full-size Belgium export and major validator stages were measured; methodology and results are recorded in `docs/map-foundation-performance-baseline.md`.
- [x] **M0 verification:** focused M0 tests and the normal non-game suite pass; engine, Workshop, and local-install checks remain opt-in.

## M1 — game target, map profile, and project schema

### M1.1 Create one authoritative game-target service

Extend `services/game_assets.py` into the only supported path for game-install resolution. Remove direct writer imports of `DEFAULT_HOI4_PATH` over the migration period.

`GameTarget` should capture:

- normalized installation directory;
- `rawVersion`, display version, revision/checksum when available;
- descriptor-compatible version string;
- profile ID, for example `hoi4-1.19`;
- source of selection: project, user configuration, auto-detected, or explicit CLI;
- validation timestamp and required-file availability.

Writers receive `GameTarget` or resolved asset bytes through the export plan. They must not rediscover the install path.

### M1.2 Define versioned map/asset profiles

Add a data-driven profile, initially for 1.19.x. It should describe:

- accepted or observed map dimension constraints;
- width/height divisibility rules and wrap behavior;
- province-count guidance and any required define behavior;
- expected ratios/dimensions for height, terrain, rivers, cities, world normals, trees, colormaps, water textures, and FOW;
- BMP bit depth, compression, palette expectations, and orientation;
- DDS pixel format and mip requirements;
- required, optional, deprecated, and inherited map files;
- terrain-definition source and tree-index contract;
- descriptor and replace-path policy.

Do not turn the four current presets into a hard validity allowlist. They remain UI conveniences. Expert/custom profiles may be allowed when basic constraints pass, but they require an engine-acceptance run before freeze. Installed mod dimensions such as 5,632 × 2,304 and 3,328 × 3,840 must at least be representable and testable.

Suggested files:

- `domain/game_profile.py`
- `services/game_profile_service.py`
- `data/game_profiles/hoi4_1_19.json`
- `tests/domain/test_game_profile.py`
- `tests/services/test_game_profile_service.py`

### M1.3 Version the project archive

Add `project_meta.json` to `.hoi4proj` with:

- `schema_version`;
- selected game/profile identifier;
- lifecycle state;
- map dimensions;
- accepted validation exceptions;
- adjacency-review state;
- foundation lock reference/hash when frozen;
- generator/tool version where available.

Update `domain/project_io.py` and `model/project.py` to read/write it. Old projects without metadata migrate in memory to the current schema as `draft`, with an inferred target requiring user confirmation. Preserve all existing manager JSON files unchanged during the first migration.

Migration tests must cover:

- opening an old project and saving it under the new schema;
- opening/saving without losing managers or asset sidecars;
- rejecting a newer unknown schema without overwriting it;
- preserving an original backup before an explicit on-disk migration if the file format becomes incompatible.

### M1.4 Replace global map constraints gradually

Stop using mutable `data.constants.MAP_WIDTH`, `MAP_HEIGHT`, `ENGINE_MAX_PROVINCES`, and path constants as validation truth. Existing UI/generator code can continue using dimensions during migration, but exporters and validators must take dimensions/profile explicitly.

### M1 implementation tracking

- [x] **M1.1 — authoritative game target:** GameTarget resolution now records normalized installs, version/checksum metadata, profile IDs, selection source, validation time, and required-file availability; export writers receive the selected target context.
- [x] **M1.2 — versioned map/asset profile:** the bundled HOI4 1.19.x profile describes dimensions, wrap rules, province guidance, raster/DDS contracts, file dispositions, terrain/tree contracts, descriptor policy, and custom-dimension behavior.
- [x] **M1.3 — project archive schema:** project_meta.json is written/read with legacy in-memory inference, newer-schema protection, migration backup support, manager round-trip coverage, and sidecar preservation.
- [x] **M1.4 — explicit profile migration hooks:** CLI, GUI export, exporters, readiness checks, validators, descriptor generation, and target-aware palettes accept explicit profile/target/dimension context while retaining compatibility fallbacks.
- [x] **M1 verification:** focused M1/CLI tests and the non-game regression suite pass; engine, Workshop, and local-install checks remain opt-in.

## M2 — immutable export planning and profile separation

### M2.1 Introduce the export contracts

Add the types from section 5.2 and a planner in `services/export_planner.py`. The planner should:

1. resolve target and profile;
2. snapshot project arrays, managers, settings, and asset metadata;
3. select profile/layers;
4. run pre-write validation;
5. produce typed proposed repairs and asset resolutions;
6. reject impossible or inconsistent combinations;
7. return an `ExportPlan` without writing files.

The snapshot should deep-copy mutable managers and arrays once. Writers may share read-only array views where safe. Add development assertions that exported arrays are not mutated after snapshot approval.

### M2.2 Convert automatic fixes into repair actions

Refactor `pre_export_check_and_fix()`, `fill_default_state_data()`, ID compaction, tiny-province merge, large-province repair, tile/type synchronization, orphan adoption, state-region alignment, and coastal conversion into pure analysis plus optional application to the export snapshot.

Every `RepairAction` should include:

- stable code such as `province.mixed_type.majority_normalization`;
- safety class: `safe`, `semantic`, or `breaking`;
- affected province/state/reference IDs;
- pixel or record counts;
- before/after summary;
- generated old-to-new mapping when IDs change;
- validations that must be rerun after application.

Default policy:

- `draft`: propose all; optionally auto-apply only explicitly classified safe repairs;
- `candidate`: require confirmation for semantic/breaking repairs;
- `frozen` or `accepted`: reject all breaking repairs and require unfreezing.

State resources, buildings, manpower, owners, and victory points are never foundation repairs.

### M2.3 Implement transactional staging

Write to a newly created staging directory in the destination's parent. Run all artifact validators there. Publish only after success. If a destination exists, preserve it unless the user explicitly chooses an overwrite/backup policy.

The output transaction should:

- validate destination boundaries;
- avoid deleting an existing mod before a replacement is known-good;
- rename the previous output to a timestamped/recoverable backup when requested;
- promote the staged directory atomically when the platform permits;
- leave failed staging output available only when the user requests diagnostics;
- report the final artifact path unambiguously.

### M2.4 Split the exporter into stages

Keep `export/mod_exporter.py` as a compatibility facade while moving behavior into ordered stages:

```text
export/stages/
  core_rasters.py
  map_metadata.py
  regions.py
  logistics.py
  placements.py
  state_geography.py
  acceptance_content.py
  scaffold_content.py
  assets.py
  descriptor.py
```

Each stage declares:

- required snapshot fields;
- files it owns;
- profile applicability;
- validation dependencies;
- asset disposition behavior.

Stage writers return written-file metadata instead of printing or modifying unrelated managers.

### M2.5 Implement profile outputs

The `foundation` profile must not call `fill_default_state_data()`, write dynamic `D01`–`D75` countries, generate leaders/OOBs, or inject randomized resources/buildings. If minimal parseable state shells are requested, mark every non-geographic placeholder in the manifest and source comments.

The `acceptance` profile should create a sibling artifact from the same approved foundation snapshot. It scans vanilla and project tags, selects deterministic unused test tags, and generates only the content required to exercise the map. It must never reuse `BEL`, `FRA`, `GER`, `HOL`, `LUX`, `ENG`, or any occupied tag unless replacement is an explicit test objective.

The `scaffold` profile can retain generated gameplay helpers but must label their provenance and exclude them from the foundation lock.

### M2.6 Update UI and CLI entry points

Replace the export-dialog presets with profile selection plus an advanced layer view. Show:

- selected game target/version;
- project lifecycle state;
- proposed repairs grouped by severity;
- generated/preserved/inherited asset counts;
- expected output products;
- blockers and accepted exceptions.

Add CLI options similar to:

```text
--profile foundation|acceptance|scaffold|legacy_full
--game-dir PATH
--repair off|propose|apply-safe
--manifest PATH
--compare-lock PATH
--json-report PATH
```

The exact option spelling can follow the existing CLI style, but GUI and CLI must call the same planner/service.

## M3 — shared validation, manifest, and determinism

### M3.1 Define typed findings and gate policy

Create a validator registry using stable finding codes. A finding contains:

- severity: `info`, `warning`, `error`, `blocker`;
- layer and file where applicable;
- affected IDs/coordinates;
- concise message and evidence;
- whether a repair exists;
- link/action target for the UI;
- accepted-exception identifier, reason, and reviewer timestamp if waived.

Gate behavior:

| Context | Blockers/errors | Warnings |
|---|---|---|
| Draft preview | Report; artifact may be generated to staging | Allowed |
| Foundation candidate export | Block publication | Allowed but visible |
| Freeze | Block unless the finding is explicitly designed as waivable | Must be resolved or accepted with reason |
| Acceptance | Block generation/run when relevant | Accepted warnings remain in result |
| Accepted lock | None allowed | Only recorded intentional exceptions |

### M3.2 Consolidate validation entry points

Create layer validators under `domain/validators/` or `services/validators/` and make these clients consume the same report:

- `services/readiness_service.py` for live project readiness;
- `services/export_service.py` for pre-write gates;
- `export/verify_mod.py` for artifact validation;
- export dialog/progress UI;
- CLI JSON and human-readable reports.

Project validation and artifact validation have different inputs but should share rule definitions and finding codes where possible. Remove duplicate “file exists” and reference checks after parity is demonstrated.

### M3.3 Implement validation suites

#### Raster and definition validation

- dimensions/profile ratios, BMP headers, bit depth, compression, row size, orientation, palette length, and header/file-size consistency;
- every nonzero raster color maps to exactly one definition and every definition maps to pixels unless explicitly allowed;
- ID continuity policy and maximum ID/profile guidance;
- forbidden/duplicate colors;
- land/sea/lake majority and mixed-type reporting;
- coastal classification and map-edge wrap behavior;
- 4-connectivity, X-crossings, minimum area, bounding boxes, and oversized provinces;
- exact old/new ID mapping after a proposed repair.

#### Terrain, river, and map-mask validation

- terrain indices exist in the selected terrain registry and agree with province terrain;
- ocean/lake/land masks agree across tile, terrain, city, tree, and height layers;
- river colors/levels are legal, connected, orthogonal where required, and have valid sources/outlets/mouths;
- cities/tree/world-normal/output dimensions match the selected profile;
- palette bytes and index semantics match the selected source contract.

#### State, region, continent, and reference validation

- every required land province belongs to exactly one state;
- state IDs and membership are stable and valid;
- each strategic-region/supply-area coverage rule is satisfied;
- regions are geographically connected where required;
- states do not cross strategic regions unless explicitly supported;
- continent assignments and every province/state/country reference resolve.

#### Adjacency and logistics validation

- every adjacency endpoint, through province, coordinate, and rule exists and has a legal type;
- required provinces and icons in adjacency rules resolve;
- railway routes contain at least two IDs, legal levels, and adjacent consecutive land provinces;
- graph components, supply-node participation/reachability, ports, and intentional island exceptions are reported;
- duplicate routes, self-loops, and invalid fallback data are errors.

#### Position/building validation

- each authored coordinate is in bounds and resolves to its intended province/state/surface;
- ports/naval bases are coastal and use the intended sea connection;
- building type and province/state placement are legal;
- duplicate or near-colliding transforms are reported;
- fallback/repeated-centroid positions are warnings or blockers according to profile/lifecycle;
- weather positions lie in their strategic regions.

#### Asset and mod-integration validation

- every profile-required asset has a generated, preserved, or inherited resolution;
- DDS format, dimensions, mip counts, and payload size validate;
- optional/deprecated files follow profile policy;
- descriptor paths, replace paths, and supported version agree with output ownership;
- country tags do not collide with loaded vanilla/dependency tags;
- no generated content references missing foundation IDs.

### M3.4 Generate the foundation manifest

Write `foundation_manifest.json` into every output and optionally a human-readable `foundation_report.md`. The JSON should include:

- tool/build version and project schema;
- source project path-independent identity hash;
- target game/profile/version/revision;
- map dimensions and counts;
- profile and enabled layers;
- source snapshot hashes for critical arrays/managers;
- all repair actions and ID mappings;
- file inventory, byte sizes, hashes, and ownership stage;
- asset resolutions with source/provenance hashes;
- validation findings and accepted exceptions;
- engine-acceptance result or `not_run`;
- foundation-lock compatibility result;
- timestamp only in a non-deterministic metadata section.

Do not include machine-specific absolute paths in the identity hash. They may appear in a diagnostic section.

### M3.5 Enforce deterministic output

Given the same snapshot, target profile, exporter version, and options, all foundation-owned output bytes should be identical. Seeded procedural art must use recorded seeds. Sort manager entries, IDs, paths, and JSON keys. Keep volatile timestamps out of hashed content.

Add a test that exports the same synthetic project twice and compares the complete file inventory and hashes.

## M4 — special adjacencies and logistics semantics

### M4.1 Add explicit adjacency review state

The existing `AdjacencyManager` and `AdjacencyRuleManager` are usable. Add project metadata with one of:

- `unreviewed`;
- `none_intended`, with review note;
- `defined`, with last review hash.

An empty manager is a freeze blocker while `unreviewed`; it is valid when `none_intended` is deliberate and no profile-specific rule contradicts it.

### M4.2 Complete adjacency import/edit/round trip

Add or harden parsers for `adjacencies.csv` and `adjacency_rules.txt`. Round-trip comments and supported fields. Import must not replace valid custom entries with an empty layer.

Extend `features/map/logistics/` to show:

- from/to/through provinces;
- start/stop coordinates and map-wrap crossing;
- sea, canal/strait, and impassable semantics;
- associated rule and required provinces;
- invalid references directly on the map.

All mutations go through commands so they remain undoable and mark readiness/lock state dirty.

### M4.3 Build adjacency fixtures

Create small original fixtures that model the semantics of:

- a simple strait;
- an impassable border;
- a canal-style access rule;
- a through-sea province;
- a map-edge crossing;
- a broken rule reference.

Use local opt-in tests to parse installed vanilla examples without copying them into the repository.

### M4.4 Add logistics graph analysis

Create a pure `domain/logistics_graph.py` service that returns:

- vertices and edges;
- connected components;
- supply nodes inside/outside railway components;
- nearest valid connection candidates;
- components with ports or designated convoy access;
- duplicate paths and self-loops;
- per-component state/continent/region summary.

The current fallback that can emit a self-loop railway must be removed. Missing logistics should produce a finding or a separately invoked generation proposal.

### M4.5 Model intentional logistics exceptions

Add project-level exceptions keyed by stable component identity or supply-node ID, with reason categories such as `island`, `overseas_convoy`, `intentional_isolation`, or `future_content`. Exceptions must be invalidated when the referenced graph changes.

Update the logistics renderer to color components and highlight the current Belgium findings: 327 components and 48 supply nodes absent from the railway graph. Freeze requires each relevant case to be connected or accepted with a reason.

## M5 — positions, building geometry, and weather placement

### M5.1 Add an authored placement model

Introduce a manager such as `domain/managers/map_placement.py` with explicit records for:

- province position slots and their index/meaning;
- building/map-object transforms;
- port/naval-base spawn coordinates and associated sea province;
- weather positions;
- provenance: imported, authored, generated proposal, or fallback;
- review status.

Use index-preserving transforms until the six `positions.txt` slots are fully named against a verified game contract. Each transform should hold map coordinates, rotation, and height without lossy integer conversion.

Serialize to `placements.json` in the project archive. Add drop/remap behavior for province and state changes, and include it in compact-ID reference tests.

### M5.2 Separate generation from acceptance

The current centroid generator becomes an explicit proposal generator. Improve it to consider:

- province interior distance from borders/coasts;
- local height/slope;
- separation between slots and objects;
- state/province surface type;
- port access to the intended adjacent sea;
- deterministic seed and stable output.

Generated positions remain `unreviewed` until accepted. Frozen foundations may contain reviewed generated positions, but not invisible fallback centroids.

### M5.3 Add a placement editor and overlay

Add `features/map/placement/` or a dedicated placement tab integrated with existing state/logistics pages. It should support selecting, dragging, rotating, and resetting transforms while displaying province borders, coastline, buildings, victory points, and collision warnings.

### M5.4 Stop writing one-of-everything placeholders into the foundation

Refactor `export/writers/map/buildings.py`:

- foundation output writes only authored/reviewed map-object placements required by the foundation;
- acceptance output may write the minimum objects needed for testing;
- scaffold output may propose broader placeholders, clearly tagged as generated;
- state building counts remain content data and do not force map-object placement unless the game requires a corresponding object.

### M5.5 Improve weather positions

Allow one or more authored/generated weather positions per strategic region, with size/type where supported. Validate containment and spacing. A single `small` centroid can remain an initial proposal, not a silently final value.

## M6 — graphics and asset-resolution pipeline

### M6.1 Create an explicit asset inventory

Replace binary clean/dirty reasoning with per-path `AssetResolution`:

```text
generated   — writer owns bytes for this target profile
preserved   — imported bytes are compatible and copied exactly
inherited   — resolved from vanilla or declared dependency at runtime
omitted     — optional and deliberately absent
unsupported — present in source/project but cannot be safely handled
```

Each record includes source, hash, compatibility checks, dirty reason, output owner, and selected profile rule. Keep the existing sidecar compatible, then migrate `_manifest.txt` to a versioned JSON manifest while continuing to read the old text form.

### M6.2 Fix installation and palette resolution

Pass the selected `GameTarget` into the indexed BMP writers. Remove `DEFAULT_HOI4_PATH` lookups from `export/bmp_writer.py` and any other writer. Read the exact source palette/terrain contract once through the target/profile service, then pass validated palette bytes to writers.

Add tests proving that a configured non-default installation is used and that fallback palettes are never silently substituted in a freeze/acceptance export.

### M6.3 Parse the terrain registry

Add a parser/service for the selected `common/terrain/00_terrain.txt` that resolves:

- terrain entry name;
- province terrain type;
- color/palette index;
- texture index;
- spawn-city and snow behavior;
- custom mod terrain entries when dependencies are supplied.

`data/terrain_types.py` may remain the built-in fallback/editor catalog, but validation truth comes from the selected profile/dependency registry. Unknown indices are blockers for foundation freeze.

### M6.4 Resolve tree-map contracts empirically

Do not simply replace 1,408 × 512 with a new hard-coded value. Add profile rules and local compatibility probes for:

- vanilla 5,632 × 2,048 → 1,650 × 600;
- observed 5,632 × 2,304 → 1,650 × 675;
- custom dimensions/profile override;
- tree palette/index compatibility with `default.map` and terrain definitions.

Update `export/writers/map/trees_bmp.py` only after the profile contract and engine test agree. Add header/palette/index tests and an in-game visual checkpoint.

### M6.5 Implement the DDS format strategy

Begin with a short technical spike comparing a redistributable Python/library solution with a packaged or user-provided DirectXTex/`texconv` workflow. The selected encoder must support deterministic BC3/DXT5 output and mip chains on Windows, have acceptable licensing, and be testable in CI.

Then:

- retain uncompressed BGRA8 for assets whose selected profile expects it;
- encode water DDS files with the profile's BC3/DXT5 contract;
- encode FOW with the required mip chain and flags;
- validate payload length, FourCC/DX10 header, mip dimensions, and decodeability;
- preserve compatible imported DDS bytes rather than recompressing them unnecessarily;
- make missing encoder capability a clear blocker only when generation is required.

### M6.6 Cover the complete map-art contract

For every vanilla `map/terrain` category, choose one supported behavior: generate, preserve, inherit, omit, or mark unsupported. This includes atlas/normal data, borders, city lights, reflections, mud, river surfaces, snow/ice, strait textures, underwater shading, and tree tint/season assets.

The first release does not need to procedurally generate every artistic file. It does need to prove that inherited files are compatible with the custom map or require a manual replacement. The manifest must make that dependency visible.

### M6.7 Preserve optional structural files

Handle `map/colors.txt` explicitly in import/export. Version-gate `airports.txt`, `rocketsites.txt`, and naming variants. Do not emit empty legacy files by default. Preserve supported imported files byte-for-byte or report that they will be dropped before export.

### M6.8 Add visual regression workflow

Use generated miniature fixtures for automated image comparisons. For full maps, write local opt-in contact sheets/previews for terrain, trees, cities, normals, water, FOW, and colormap channels. Record human visual approval in the candidate manifest; do not store copyrighted source textures in the repository.

## M7 — assisted engine acceptance

### M7.1 Set realistic automation boundaries

HOI4 and its launcher are closed-source GUI applications and cannot be a normal headless CI dependency. The reliable first implementation should automate artifact preparation, launch configuration where supported, fresh-log capture, log comparison, save-file detection, and result recording. It should guide a human through the short in-game interaction checklist.

Unattended mouse/UI automation can be explored later, but it should not be the foundation gate until it is demonstrably stable across launcher and game updates.

### M7.2 Generate an isolated acceptance mod

The acceptance profile should:

- use the exact foundation files/hashes under test;
- generate deterministic unused test tags after scanning vanilla and dependencies;
- use a unique mod name and directory per run;
- own the correct country/history paths without accidental duplicate tags;
- create minimum viable state owners, capitals, OOB/bookmark, and test units;
- avoid dynamic tags and unrelated generated content;
- mark all acceptance-only files in the manifest.

### M7.3 Build the local harness

Suggested components:

- `services/engine_acceptance_service.py`
- `tools/run_engine_acceptance.py`
- `domain/engine_acceptance.py`
- `tests/services/test_engine_log_parser.py`

Workflow:

1. verify game target and artifact hashes;
2. snapshot/rotate relevant log files safely;
3. install or point the launcher at the isolated acceptance mod;
4. launch the selected game executable/launcher with documented arguments where possible;
5. display the interaction checklist and run identifier;
6. after the game closes or the user marks completion, collect only fresh log ranges;
7. classify errors by map, asset, script, country/tag, audio/unrelated, and unknown categories;
8. verify expected checkpoints and save file;
9. write `engine_acceptance.json` with game version, artifact hashes, checks, log hashes, and result.

The harness must never treat old logs as current evidence.

### M7.4 Required in-game checklist

- reach the main menu without map initialization failure;
- start the intended bookmark and enter the map;
- select provinces, states, countries, and strategic regions;
- inspect terrain, political, supply, railway, air, and naval map modes;
- move a land unit across ordinary and special adjacencies;
- test a port/naval route where applicable;
- select air regions and verify weather positions;
- tick at least 30 in-game days;
- create a save, reload it, and tick again;
- inspect representative tree, city, terrain, water, FOW, normal, border, and building rendering.

Any map/province/terrain/asset/tag error is a failed foundation acceptance unless explicitly proven unrelated.

## M8 — freeze, change detection, and content handoff

### M8.1 Define lock contents

`foundation.lock.json` should hash and summarize:

- map dimensions and selected profile;
- province raster and definition identity/type/coast/terrain data;
- height, river, terrain, tree, city, and normal layers as configured;
- province/state IDs and state province membership;
- continents and strategic regions;
- special adjacencies/rules;
- supply areas, nodes, and railways;
- reviewed placement geometry;
- foundation-owned asset resolutions and hashes;
- accepted findings/exceptions;
- successful engine-acceptance record identity.

Do not lock acceptance-only countries or scaffold gameplay values.

### M8.2 Classify later changes

Add a comparison service that reports:

| Change class | Examples | Effect |
|---|---|---|
| Breaking identity | Province dimensions, colors, IDs, deletions, type changes | Content references require migration; accepted state is lost |
| Breaking topology | State membership/IDs, regions, adjacency, rail/supply topology | Dependent history/gameplay requires review; accepted state is lost |
| Foundation visual | Terrain/tree/city/normal/colormap asset change | Content IDs remain valid; visual validation and usually engine acceptance rerun |
| Placement | Port/building/unit/weather coordinate change | Related gameplay/visual checks rerun |
| Non-foundation content | Owner, resource, focus, leader, localization change | Foundation lock remains valid |

When ID changes are approved before freeze, write a reusable old-to-new mapping for content migration. After freeze, never compact IDs silently.

### M8.3 Add freeze/unfreeze workflow

The UI should provide:

- “Create candidate” after static blockers are resolved;
- “Freeze foundation” after reviewed exceptions and asset resolution;
- “Record engine acceptance” only for exact matching hashes;
- “Unfreeze” with a reason and clear warning about downstream content;
- “Compare with frozen foundation” at any time.

CLI equivalents should support automation and source control.

### M8.4 Generate a handoff package

Alongside the lock, generate `FOUNDATION-HANDOFF.md` containing:

- target version and required dependencies;
- stable ID ranges and map dimensions;
- file ownership/inheritance summary;
- accepted exceptions;
- where state geography ends and content history begins;
- how content authors should reference province/state/region IDs;
- prohibited operations after freeze;
- procedure for requesting a map change and applying an ID migration.

This gives traditional mod development a clear contract rather than a folder of unexplained generated files.

## M9 — migration cleanup and release candidate

### M9.1 Preserve compatibility during rollout

- Keep `export_full_mod()` as a facade until profile writers reach parity.
- Translate the old `scope` dictionary to `legacy_full` with a deprecation warning.
- Continue reading old project archives and `_manifest.txt` sidecars.
- Keep existing manager JSON schemas unless a versioned migration is necessary.
- Do not remove old bitmap/writer helpers until all active callers and tests use the staged pipeline.

### M9.2 Remove duplicated and contradictory behavior

After parity:

- retire duplicate map writers in `export/csv_writer.py` or `export/bmp_writer.py` where the newer `export/writers/` implementation owns the file;
- remove writer-level game-install discovery;
- remove comments that contradict current generated files;
- centralize descriptor/replace-path policy;
- stop unconditional `MAX_PROVINCES = 25000` generation;
- remove fallback self-loop railways and broad building placeholders from foundation mode;
- make all console output UTF-8-safe and structured through a reporting layer.

### M9.3 Release documentation

Update:

- `README.md` with profile and foundation workflow;
- `docs/TUTORIAL.md` with draft → candidate → frozen → accepted lifecycle;
- `docs/wiki/map-core.md` with profile/manifest rules;
- `docs/wiki/buildings-supply.md` with graph and placement review;
- `docs/wiki/troubleshooting.md` with finding codes and engine harness;
- command-line help and export-dialog explanations.

## 8. Suggested pull-request sequence

Keep changes mergeable and reviewable. The following order avoids a single exporter rewrite:

1. **Baseline and CLI reliability** — fixtures, markers, full dependency setup, encoding/exit-code fix.
2. **Project metadata and target profile** — read-only integration first; no output changes.
3. **Export domain contracts and immutable snapshot** — tests proving no project mutation.
4. **Planner and transactional staging** — existing writers behind a new facade.
5. **Foundation/acceptance/scaffold profiles** — isolate state/content generation and tags.
6. **Validation finding model and shared registry** — adapt readiness and verifier incrementally.
7. **Manifest, deterministic hashes, and repair ledger**.
8. **Adjacency review/import/validation/UI completion**.
9. **Logistics graph analysis, exceptions, and fallback removal**.
10. **Placement model, serialization, validators, and editor**.
11. **Asset inventory, configured-install palette, and terrain registry**.
12. **Tree contract and DDS encoding pipeline**.
13. **Optional-file preservation and complete asset-resolution report**.
14. **Acceptance-mod generator, fresh-log parser, and guided harness**.
15. **Foundation lock, breaking-change comparison, and handoff package**.
16. **Legacy cleanup, end-to-end Belgium run, docs, and release candidate**.

Each pull request should include its own migration note, tests, and a statement of whether it changes artifact bytes. Any output change should update the baseline intentionally.

## 9. Test strategy

### 9.1 Unit tests

Pure tests should cover:

- profile parsing and target resolution;
- snapshot immutability;
- repair analysis/application;
- validator findings and waivers;
- graph components and exceptions;
- position containment/collision;
- asset resolution;
- manifest and lock serialization;
- lock difference classification;
- DDS/BMP header parsing;
- engine-log classification.

### 9.2 Property-style matrix tests

Without adding a property-testing dependency initially, use parameterized generated maps to exercise:

- horizontal wrap/non-wrap borders;
- disconnected and diagonal province shapes;
- mixed type provinces;
- ID gaps/remaps;
- islands and convoy-supplied components;
- adjacency-rule combinations;
- dimensions and asset ratios;
- old/new project schemas.

### 9.3 Golden artifact tests

Export small synthetic projects and compare complete inventories/hashes. Golden output should be authored by this repository and contain no base-game assets.

Maintain goldens for:

- foundation profile;
- acceptance profile;
- scaffold profile;
- imported/preserved asset path;
- custom-size expert profile;
- legacy-project migration.

### 9.4 Full-size regression tests

Use the Belgium project locally or in an approved large-fixture environment to verify:

- no raster/reference regressions;
- acceptable memory use;
- deterministic repeated export;
- manifest counts/hashes;
- current known issue closure.

Avoid making a user-specific absolute project path a normal CI dependency.

### 9.5 Local game and Workshop compatibility tests

These are opt-in and produce reports, not committed binaries. Probe the selected vanilla install and representative installed mods for:

- accepted dimensions and headers;
- import/export round trips;
- dependency inheritance;
- optional file handling;
- terrain registries and DDS/tree contracts.

The compatibility matrix should include at least vanilla, Kaiserreich, Old World Blues, A Very British Civil War, Star Wars: Palpatine's Gamble, Millennium Dawn, Road to 56, and one partial OWB overlay.

## 10. User experience changes

### Export dialog

The dialog should lead with outcome rather than file checkboxes:

```text
Target: HOI4 1.19.3.0 — verified installation
Project: Candidate — not frozen
Profile: Foundation package

Static result: 2 blockers, 5 warnings
Repairs: 1 semantic change requires review
Assets: 5 generated, 17 inherited, 3 preserved, 1 unsupported

[Review findings] [Review repairs] [Export candidate]
```

Advanced users can expand the layer inventory. The normal path should make it difficult to confuse a playable scaffold with the foundation.

### Readiness panel

Extend `services/readiness_service.py` to group results by gate:

- geometry and IDs;
- state/region coverage;
- adjacency review;
- logistics review;
- placements;
- graphical assets;
- static artifact verification;
- engine acceptance;
- foundation lock.

Each finding should navigate to the relevant feature page where practical.

### Project status

Show `Draft`, `Candidate`, `Frozen`, or `Accepted` in the main workflow UI. Any command that changes locked data should warn before execution and produce a lock-difference preview.

## 11. Manifest and report examples

The manifest should be machine-readable and stable. A shortened conceptual example:

```json
{
  "schema_version": 1,
  "profile": "foundation",
  "lifecycle": "candidate",
  "game_target": {
    "profile": "hoi4-1.19",
    "raw_version": "1.19.3.0",
    "revision": "c01a3d507f10bd8c713e88234de69ca110618138"
  },
  "map": {
    "width": 5632,
    "height": 2048,
    "province_ids": 12521,
    "states": 290,
    "strategic_regions": 48
  },
  "repairs": [
    {
      "code": "province.mixed_type.majority_normalization",
      "safety": "semantic",
      "province_ids": [9706],
      "changed_pixels": 14,
      "approved": true
    }
  ],
  "assets": {
    "map/terrain/colormap_water_0.dds": {
      "resolution": "generated",
      "contract": "bc3"
    },
    "map/terrain/atlas0.dds": {
      "resolution": "inherited",
      "source": "vanilla"
    }
  },
  "validation": {
    "errors": 0,
    "warnings": 0,
    "accepted_exceptions": []
  },
  "engine_acceptance": {
    "status": "not_run"
  }
}
```

The human report should summarize decisions and link finding codes to documentation. It should not duplicate every JSON field.

## 12. Migration strategy

### Existing projects

- Load without metadata as `draft`.
- Infer map dimensions directly from arrays.
- Suggest the detected local game profile, but require confirmation before freeze.
- Preserve existing managers, IDs, assets, and dirty flags.
- Mark empty adjacency data `unreviewed`, not `none_intended`.
- Mark existing generated positions as `fallback/unreviewed` when imported from current behavior.
- Do not retroactively fill content fields during migration.

### Existing export consumers

- Keep current function signatures through an adapter during M2–M9.
- Emit deprecation warnings only after the new profiles can reproduce required use cases.
- Provide a conversion table from old scope flags to new stages/profiles.
- Keep `legacy_full` available for one documented release cycle.

### Existing content built on generated IDs

Before compaction/repair, offer a dry-run mapping and scan known project/output files for province/state references. The tool cannot guarantee migration of arbitrary script semantics, so breaking changes after content exists require explicit user confirmation and a generated migration report.

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Closed-source engine behavior differs from inferred contracts | Static pass but in-game failure | Profile evidence plus exact-artifact local acceptance remains mandatory |
| BC3 encoder is unavailable or unsuitable to redistribute | Generated water/FOW blocked | Technical spike, preservation/inheritance path, user-provided encoder fallback |
| Full-size validation becomes slow or memory-heavy | Poor UX or crashes | Vectorized passes, shared province statistics, cached graph/raster analyses, background worker |
| Project migration loses custom data | Irrecoverable user loss | Versioned metadata, read-before-write migration tests, backup before incompatible save |
| Automatic repair changes IDs after content work | Large downstream breakage | Lifecycle lock, immutable export plan, explicit mappings, no silent post-freeze compaction |
| Imported assets are incompatible with a new map size | Visual corruption/crash | Per-asset compatibility checks and `unsupported` status rather than blind preservation |
| Dependency inheritance changes between mod load orders | Missing/wrong assets | Explicit dependency roots and hashes in asset resolution/acceptance run |
| Acceptance tags collide after a game update | Script conflicts | Scan selected vanilla/dependencies for every run; deterministic unused test namespace |
| Engine harness mistakes stale logs for a pass | False confidence | Rotate/snapshot logs, run ID, timestamps, fresh ranges, artifact hashes |
| Legacy path diverges while new pipeline is built | Double maintenance | Facade over shared stages, short deprecation window, output parity tests |

## 14. Belgium Map v1.1 remediation checklist

This project is the first release candidate and should exercise the complete workflow.

- [ ] Store and confirm the HOI4 1.19.x target profile in project metadata.
- [ ] Export from an immutable snapshot and prove no live manager/array mutation.
- [ ] Review province `9706`; either repair the source project or approve the 14-pixel lake normalization explicitly.
- [ ] Generate and inspect the old-to-new ID report; freeze the 1–12,521 range only after all repairs.
- [ ] Mark special adjacencies as `none_intended` with a geographic review, or author required entries/rules.
- [ ] Review all 327 railway components.
- [ ] Connect, remove, or explain the 48 supply nodes absent from the railway graph.
- [ ] Replace or review repeated centroid position slots.
- [ ] Separate the 3,558 generated building records and randomized state values from foundation output.
- [ ] Resolve terrain palette from the configured `C:` game installation.
- [ ] Resolve and test the tree-map dimensions/index contract.
- [ ] Generate or preserve profile-correct water/FOW DDS assets.
- [ ] Inventory all remaining terrain assets as generated, preserved, inherited, omitted, or unsupported.
- [ ] Preserve or explicitly omit `map/colors.txt` and remove unjustified empty legacy files.
- [ ] Generate an isolated acceptance mod with non-colliding tags.
- [ ] Pass fresh main-menu/start/30-day/save/reload and map-mode checks.
- [ ] Produce `foundation_manifest.json`, `foundation_report.md`, `engine_acceptance.json`, and `foundation.lock.json`.
- [ ] Generate the content-team handoff document and begin conventional content work only after lock acceptance.

## 15. Release gates

### Gate A — deterministic foundation candidate

- project target/profile is explicit;
- export is snapshot-based and transactional;
- no randomized content in foundation profile;
- all repairs are listed and approved;
- two exports produce identical foundation-owned hashes.

### Gate B — topology and gameplay-map semantics

- raster/state/region/reference suites pass;
- adjacency review is complete;
- logistics findings are fixed or accepted with reasons;
- placement provenance and validation are complete.

### Gate C — graphical contract

- selected palette and terrain registry are correct;
- tree, city, normal, water, FOW, and colormap dimensions/formats pass;
- every required asset has an explicit resolution;
- visual review has no known map-breaking defect.

### Gate D — engine acceptance

- acceptance mod has no tag collision;
- fresh logs belong to the exact artifact;
- start, tick, movement/map modes, save, and reload pass;
- no unexplained map/province/terrain/asset error remains.

### Gate E — frozen content handoff

- lock file matches accepted artifact;
- accepted exceptions and dependencies are documented;
- breaking-change comparison is operational;
- state/province/region IDs and ownership boundaries are handed off;
- content developers can work without running the map generator for ordinary content changes.

No release should call the foundation “feature complete” until Gates A–E pass. Content prototyping can use candidate snapshots, but production content should branch from the Gate E lock.

## 16. Immediate next implementation slice

The first development slice should contain M0 plus the smallest vertical part of M1/M2:

1. fix CLI encoding/exit codes and make the complete test environment reproducible;
2. add `GameTarget`, `ExportProfile`, `FoundationSnapshot`, and typed `ValidationFinding` contracts;
3. add project metadata with backward-compatible loading;
4. create a planner that snapshots the project and reports current repairs without applying them;
5. add a `foundation` profile that bypasses `fill_default_state_data()`;
6. export to staging and write a preliminary manifest;
7. verify through tests that the live Belgium project is byte-for-byte unchanged after planning/export.

That slice delivers the most important safety property early: subsequent adjacency, logistics, placement, and graphics work can evolve against a stable export contract without continuing to entangle map foundation with scenario content.
