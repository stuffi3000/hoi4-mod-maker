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

### M2 implementation tracking

- [x] **M2.1 — immutable export contracts and planning:** typed profiles, snapshots, findings, repairs, asset resolutions, lifecycle policy, target/profile resolution, and no-write planning are implemented in `domain/export_contract.py` and `services/export_planner.py`.
- [x] **M2.2 — snapshot repair actions:** automatic map repairs are represented as stable typed actions, policy/lifecycle gated, applied only to deep-copied export state, with nested manager mutation fingerprints and read-only snapshot arrays.
- [x] **M2.3 — transactional staging:** planner exports write below the destination parent, validate staged products, preserve existing destinations by default, support recoverable backup/overwrite promotion, and clean or retain failed staging according to policy.
- [x] **M2.4 — ordered exporter stages:** raster, region, logistics, placement, metadata, geography, acceptance/scaffold content, asset, and descriptor stages share a snapshot context and declare ownership/profile applicability.
- [x] **M2.5 — separated profiles:** foundation omits gameplay ownership/content and records placeholders; acceptance uses deterministic collision-free tags after vanilla/project exclusion; scaffold gameplay helpers carry provenance and stay outside the foundation lock.
- [x] **M2.6 — CLI/GUI integration:** profile, target, repair, manifest, lock, JSON-report, and transaction options are exposed; both entry points call the shared planner/service and advanced scope controls remain profile-valid.
- [x] **M2 verification:** focused M2 tests (22), targeted service/readiness/CLI/export regressions (37), export format regressions (7), and the full non-game suite pass; engine/Workshop acceptance remains an opt-in follow-up.

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

### M3 implementation tracking

- [x] **M3.1a — typed findings and gate policy:** shared `ValidationFinding`, deterministic registry, and lifecycle gate policy are implemented in `domain/validation.py` with focused tests.
- [x] **M3.2a — shared report foundation:** immutable `ValidationReport` and legacy readiness/verifier adapters are implemented in `domain/validation.py` and `services/validation_service.py`.
- [x] **M3.2b — readiness/export-service clients:** make live readiness and pre-write export checks consume the shared report while preserving legacy return compatibility.
- [x] **M3.2c — artifact/CLI/UI clients:** make artifact verification, export progress/dialog, and CLI reports consume the shared report.
  - [x] **M3.2c1 — artifact verifier:** add the quiet single-pass `ValidationReport` adapter while preserving `verify_quiet()` and `verify_all()` compatibility.
  - [x] **M3.2c2 — CLI reports:** route CLI human-readable/JSON validation output through the shared report without changing exit-code behavior.
  - [x] **M3.2c3 — export UI:** route export progress/result verification through the shared report without broadening the UI scope.
- [x] **M3.3 — validation suites:** implement and register the raster, terrain/river/mask, geography/reference, logistics, placement, and asset/integration suites.
  - [x] **M3.3a — raster/definition:** core raster dimensions, definition coverage, IDs, surface classification, connectivity, and bounding-box findings.
  - [x] **M3.3b — terrain/river/mask:** terrain indices/surface agreement plus river and layer-mask shape/value findings.
  - [x] **M3.3c — geography/reference:** state, region, continent, and cross-reference findings, including profile-aware wrap and state/region compatibility checks.
  - [x] **M3.3d — adjacency/logistics:** adjacency, railway, supply-node, port, and graph findings, including profile-aware wrap and duplicate-route checks.
  - [x] **M3.3e — placement:** coordinate, building, port, collision, and weather-position findings.
  - [x] **M3.3f — asset/integration:** asset disposition/format, descriptor, tag-collision, and missing-reference findings.
- [x] **M3.4 — foundation manifest:** extend the manifest with path-independent identity, full inventory/provenance, validation, acceptance, and lock metadata.
  - [x] **M3.4a — deterministic identity:** record path-independent project/target identity, source array/manager/auxiliary hashes, counts, scope, and stable canonical JSON.
  - [x] **M3.4b — inventory/provenance:** record sorted written-file inventory, stage ownership, asset resolutions, source hashes, and output hashes without mutating export inputs.
  - [x] **M3.4c — validation metadata:** serialize shared validation reports, gate decisions, accepted exceptions, engine-acceptance results, and explicit `not_run` defaults outside the identity hash.
  - [x] **M3.4d — foundation lock:** emit a versioned lock with portable compatibility fields and compare modern and legacy locks deterministically.
- [x] **M3.5 — deterministic output:** enforce and test byte-identical foundation content for identical snapshots and options; compare the complete output inventory while normalizing only the explicitly volatile metadata timestamps.
  - [x] **M3.5a — stable artifact production:** preserve sorted writer/stage/file ordering and seeded procedural generation across repeated foundation exports.
  - [x] **M3.5b — deterministic inventory:** hash every emitted file, canonicalize manifest/lock metadata and the report timestamp for comparison, and verify two identical synthetic exports match.

### M3 checkpoint — after M3.2c1

- **Completed:** M3.2c1 artifact verifier client, committed as `3133e72`.
- **Reviewed:** `ModVerifier.verify_report()` is quiet and single-pass, uses the existing artifact adapter, forwards target/profile context, and preserves `verify_quiet()` and `verify_all()` compatibility.
- **Evidence:** 8 new verifier tests plus 19 shared-report regression tests passed; compilation and diff checks passed.
- **Environment note:** the existing M1 target-hook suite still encounters the known Windows temporary-directory ACL failure in five fixture setups; two tests pass.
- **Next controlled slice:** M3.2c2 CLI reports. M3.2c3 export UI and all later M3 work remain pending.

### M3 checkpoint — after M3.2c

- **Completed:** M3.2c2 CLI reports (`5fa4408`) and M3.2c3 export UI (`d0838de`).
- **Reviewed:** planner human-readable and JSON outputs now expose shared plan/artifact reports; the export worker carries plan findings and the dialog uses the single-pass artifact report while preserving legacy display behavior and exit codes.
- **Evidence:** 6 CLI tests, 4 UI tests, 22 planner tests, and the shared-report regression suites passed; compilation and diff checks passed.
- **Next controlled slice:** M3.3 validation suites, split by validator family. Manifest and deterministic-output work remain pending.

### M3 checkpoint — after M3.3b

- **Completed:** M3.3a raster/definition and M3.3b terrain/river/mask validators, centrally registered in `1c0dc8d` after standalone commits `b5e7ce7` and `1d7793c`.
- **Reviewed:** both pure validators return typed findings with stable codes, deterministic ordering, useful coordinates/evidence, and no input mutation; `run_foundation_validation()` aggregates both through the shared registry/report contract.
- **Evidence:** 18 raster tests, 20 terrain tests, 11 registry tests, and 32 existing validation/province tests passed; compilation and diff checks passed.
- **Next controlled slice:** M3.3c geography/reference validation. Logistics, placement, asset/integration, manifest, and deterministic-output work remain pending.

### M3 checkpoint — after M3.3d

- **Completed:** M3.3c geography/reference and M3.3d adjacency/logistics validators, centrally registered with the existing raster and terrain suites in `682354f`.
- **Reviewed:** both new suites are pure, deterministic, typed-finding producers with manager-compatible read-only adapters, profile/explicit horizontal-wrap handling, sorted evidence/coordinates, and no input mutation. Geography reports state/region/country/continent references and state/region incompatibility; logistics reports adjacency, railway, supply, port, graph, and duplicate-route errors/warnings.
- **Evidence:** the combined M3.3 registry/geography/logistics/raster/terrain suite passed; shared validation, manager, adjacency, compaction, and province-paint regression tests also passed; diff checks passed. Two independent Muse review workers found and drove the follow-up fixes before acceptance.
- **Next controlled slice:** M3.3e placement validation. Asset/integration validation, the foundation manifest, and deterministic-output enforcement remain pending.

### M3 checkpoint — after M3.3f

- **Completed:** M3.3e placement and M3.3f asset/integration validators, integrated into the six-entry foundation registry in `122bf6b`.
- **Reviewed:** both pure validators use typed, deterministic findings with sorted/capped evidence, no input mutation, profile/explicit wrap or descriptor-kind handling where applicable, and filesystem/Qt-free inputs. Placement covers coordinate/building/port/collision/fallback/weather checks; asset integration covers disposition/policy, BMP/DDS headers and payload size, descriptor ownership, tag collisions, and missing references.
- **Evidence:** 25 placement tests, 29 asset tests, 21 registry tests, and the shared validation/manager/adjacency/compaction/province-paint regressions passed (134 tests total); compilation and diff checks passed. Two independent Muse reviews and two targeted follow-up workers were used before parent acceptance.
- **Next controlled slice:** M3.4 foundation manifest. M3.5 deterministic-output enforcement remains pending.

### M3 checkpoint — after M3.4

- **Completed:** M3.4a-d foundation manifest identity, inventory/provenance, validation/acceptance metadata, and versioned lock compatibility, committed as `bd4b29f`, `2785a59`, `2413edd`, and `6ee20a6`.
- **Reviewed:** manifest identity excludes timestamps, machine paths, inventory, and gate metadata; written files and asset provenance are sorted and stage-owned; shared validation reports and accepted exceptions are normalized without input mutation; modern locks compare identity, target, project, dimensions, counts, and legacy fingerprints while ignoring metadata/diagnostic extras.
- **Evidence:** 58 focused M3.4/M2/verifier tests passed, the full `tests/export` suite passed, and compilation/diff checks passed. Muse Spark workers implemented the bounded slices; parent review accepted the resulting diffs.
- **Next controlled slice:** M3.5 deterministic-output enforcement. M4 remains pending.

### M3 checkpoint — after M3.5

- **Completed:** M3.5a-b deterministic foundation artifact production and complete normalized inventory comparison, committed as `a9d1d42`.
- **Reviewed:** ordinary output files are streamed and hashed byte-for-byte; only manifest/lock metadata and the generated report timestamp are normalized, without modifying files on disk. The repeated-export test confirms all paths, normalized sizes, and hashes match while raw metadata timestamps differ.
- **Evidence:** 51 focused M3.5/M3.4/M2 tests passed, the full `tests/export` suite passed, and compilation/diff checks passed. Muse Spark was attempted for this slice but stalled without edits; the parent completed and reviewed the bounded recovery implementation.
- **Next controlled slice:** M4.1 adjacency review state. M4–M8 remain pending.

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

### M4 implementation tracking

- [x] **M4.1 — explicit adjacency review state:** project metadata now records `unreviewed`, `none_intended` with a note, or `defined` with a deterministic adjacency-layer hash; freeze/accepted planning blocks unreviewed or contradictory layers. Committed as `3f2a833`.
- [x] **M4.2 — adjacency import/edit/round trip:** CSV and Clausewitz-rule parsers preserve supported fields/comments, optional imports preserve absent custom layers, writers round-trip comments, and the adjacency/rule editors expose geometry, wrap, rule requirements, invalid references, and undoable mutations. Committed as `e8a7588`.
- [x] **M4.3 — original adjacency fixtures:** add focused synthetic strait, impassable, canal-rule, through-sea, map-edge, and broken-reference fixtures with validator coverage; local vanilla parsing remains opt-in. Committed as `b2137cd`.
- [x] **M4.4 — pure logistics graph analysis:** add deterministic component/edge analysis, connection candidates, port/convoy and region metadata, duplicate/self-loop reporting, validator integration, and remove self-loop railway output fallbacks. Committed as `086b97b`.
- [x] **M4.5 — intentional logistics exceptions and renderer:** persist stable graph/supply exceptions with the four approved reason categories, detect stale identities when graph topology changes, color components, highlight disconnected/off-rail findings, and require connected-or-accepted logistics at freeze. Committed as `3d2fa45`.

### M4 checkpoint — complete after M4.5

- **Completed:** M4.1 review policy (`3f2a833`), M4.2 adjacency import/edit/round trip (`e8a7588`), M4.3 synthetic adjacency fixtures (`b2137cd`), M4.4 graph analysis/fallback removal (`086b97b`), and M4.5 intentional logistics exceptions/renderer (`3d2fa45`).
- **Reviewed:** stable component and supply exception keys are persisted through project and service I/O, stale waivers are rejected from coverage after topology changes, shared validation and export planning block unaccepted cases at freeze, and the logistics canvas colors components with red/magenta finding highlights. Muse Spark implemented the pure exception model and performed a read-only integration review after explicit Meta transmission approval; the review findings were fixed before acceptance.
- **Evidence:** the focused M4.5, M3.3d registry/logistics, and exception tests passed; the full repository pytest suite passed; and compilation/diff checks passed. Legacy projects without an exception file load with an empty exception manager so waivers cannot leak between projects.
- **Next controlled slice:** M5 positions, building geometry, and weather placement.

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

### M5 implementation tracking

- [x] **M5.1 — authored placement model:** added deterministic province-slot, building, port, and weather records with float-preserving transforms, provenance/review state, stable serialization, compact-ID remap/drop operations, and focused tests. Project lifecycle and `placements.json` persistence clear legacy/missing placement data safely; export snapshots fork placements and remap the export copy during province compaction. Muse Spark implemented the model and lifecycle wiring in narrow slices; the parent reviewed and corrected generated-proposal review semantics and backward-compatible optional argument placement. Committed as `fd51a63`.
- [x] **M5.2a — pure deterministic proposal core:** replaced the implicit centroid-only calculation with a side-effect-free, seeded candidate scorer that considers province interior distance, coast distance, optional height/slope, land surface, and slot separation. It returns explicit diagnostics for sea/unknown/undersized provinces and emits only `generated`/`unreviewed` records. Committed as `1667518`.
- [x] **M5.2b — port-aware proposal core:** added deterministic port proposals that require the explicitly requested adjacent sea province, validate land/sea surfaces and four-neighbor access, and emit `generated`/`unreviewed` port records with explicit diagnostics. Committed as `092bf93`.
- [x] **M5.2c — explicit proposal acceptance workflow:** added deterministic slot/port ingestion reports that preserve `generated`/`unreviewed` status, protect authored/reviewed records by default, allow replacement only for unreviewed generated records when explicitly requested, and provide a separate selected-record acceptance helper. Malformed pre-reviewed proposals are rejected before manager mutation. Committed as `857d285`.
- [x] **M5.2d — foundation placement review gate:** added manager-backed completeness/review validation that requires all six reviewed/accepted slots for land provinces and blocks frozen/accepted foundations when records would be omitted by the foundation writers, while preserving draft/candidate warnings and legacy callers without a placement manager. Committed as `5a037e0`.
- [x] **M5.2e — headless proposal workflow service:** added deterministic service entry points that compose land/port proposal generation with manager storage, preserve generated/unreviewed status, require explicit land-to-sea mappings, surface generator/store diagnostics, protect existing reviewed/authored records, and accept only explicitly selected records. Committed as `88fa8b9`.
- [x] **M5.2f — controller proposal boundary:** added a headless `PlacementController` that reads project rasters, invokes the proposal service, requires explicit port sea mappings, makes slot/port proposal and selected acceptance operations undoable, emits `placement_changed` only on real mutations, and leaves generated records unreviewed. Committed as `1343c9e`.
- [x] **M5.2g — standalone proposal review surface:** added a Qt placement page with explicit land-to-sea mapping input, deterministic checkable slot/port records, visible diagnostics, and selected-only review/acceptance signals. Unknown placement record types are not misclassified as ports. Committed as `0de9d31`.
- [x] **M5.2h — live editor proposal path:** registered the placement page and controller in the existing logistics navigation, routed explicit generate/accept/refresh signals through `MainWindow`, refreshed records after placement/project changes, and kept the placement canvas on the safe strategic-region render path. Committed as `89a5b35`.
- [x] **M5.2 — proposal generation integration:** connect the proposal core to explicit port-aware placement requests, review/acceptance, and profile-aware export/preflight behavior without silent fallback acceptance. Completed across `3a302b9`, `ba229f2`, and `155a48a`.
- [x] **M5.2i — foundation export contract:** pass persisted placement managers through both CLI export paths, block explicit foundation exports that lack a manager, preserve legacy draft compatibility only behind an explicit stage flag, and keep centroid fallback out of the enforced foundation path. Committed as `3a302b9`.
- [x] **M5.2j — editor replacement opt-in:** expose an unchecked placement-page option that forwards `replace_generated` to slot/port proposal generation while retaining the existing signal ABI and authored/reviewed-record protection. Committed as `ba229f2`.
- [x] **M5.2k — placement readiness preflight:** add non-auto-completable `readiness.placements` findings for incomplete/unreviewed manager records and explicit foundation exports without a manager; draft lifecycles warn, strict lifecycles block, and the export dialog forwards its selected profile. Committed as `155a48a`.
- [x] **M5.3 — placement editor and overlay:** add selection/editing and collision/provenance overlays.
- [x] **M5.3a — deterministic placement overlay model:** pure, sorted, bounds-aware markers now classify slots, ports, buildings, weather, victory points, and `placement.collision` coordinates while preserving provenance/review roles. Committed as `9ef3a0b`.
- [x] **M5.3b — read-only canvas overlay:** the map canvas now renders a hidden-by-default, transparent marker layer with distinct symbols/colors, explicit visibility control, map-size rebinding, and no change to existing VP semantics. Committed as `8301b93`.
- [x] **M5.3c — live overlay diagnostics:** MainWindow now feeds all placement records, VP centroids, and read-only validator findings into the canvas while retaining the slot/port review-page contract; placement mode alone enables the layer. Committed as `507057a`.
- [x] **M5.3d — transform editing:** add selection, dragging, rotation, reset, and undoable controller/manager updates before closing M5.3. Committed across `3b6b3b4`, `14798d2`, `902a245`, `42d993e`, `d3e5e31`, `5a02a02`, `50e106b`, and `69b4d50`.
- [x] **M5.4 — foundation building output:** profile-aware position/building writers now omit incomplete or unreviewed foundation records, preserve reviewed transforms and exact port sea references, and retain clearly marked compatibility placeholders only for acceptance/scaffold/legacy profiles. Legacy direct writer signatures remain positional-compatible. Committed as `ba8a207`.
- [x] **M5.5 — weather positions:** profile-aware weather-position output now preserves reviewed/accepted manager records, remaps manager region IDs to emitted IDs, supports multiple positions and legal sizes, omits foundation centroid fallback, and retains deterministic compatibility fallback; pure containment/coverage/spacing validation is integrated into the registry and planner. Committed as `c3b2f68`.

### M5 checkpoint — M5.1 complete

- **Completed:** `MapPlacementManager` and four explicit record types preserve six index-addressed province slots, building/map-object transforms, port/naval spawn transforms, weather positions, provenance, and review status. Generated/fallback proposals remain visibly generated while explicit review can advance their status. `placements.json` round-trips through `Project`, service, and UI file operations; missing legacy placement files clear the manager. Province compaction remaps export-copy placements without mutating the live project.
- **Evidence:** focused M5.1/model/compact/export tests passed; existing project IO/meta tests passed with a workspace temp root; compilation and diff checks passed.
- **Next controlled slice:** integrate M5.2 proposals with port access and profile-aware placement writers.

### M5 checkpoint — pure M5.2 proposal core

- **Completed:** deterministic land-position proposal scoring now produces separated, float-preserving six-slot candidates with explicit `generated`/`unreviewed` provenance and diagnostics instead of repeated fallback centroids. The generator is pure and uses actual raster dimensions; one-pixel dimensions and non-land provinces are handled explicitly.
- **Evidence:** M5.2 synthetic generator tests passed, including concave interiors, coast avoidance, optional height/slope, deterministic seed/order, sea/lake rejection, insufficient-space diagnostics, and no repeated coordinates. Port proposal tests passed for exact sea mapping, land/sea surface rejection, four-neighbor access, deterministic output, and nonfinite height handling.
- **Next controlled slice:** connect both proposal generators to an explicit manager acceptance path and add the foundation freeze gate before continuing with weather and editor work.

### M5 checkpoint — profile-aware placement writers

- **Completed:** foundation `positions.txt` writes only complete six-slot province records whose slots are reviewed or accepted; foundation `buildings.txt` writes only reviewed/accepted building and exact-sea port records. Acceptance/scaffold/legacy staged exports retain compatibility placeholders with an explicit generated marker and can overlay reviewed manager records without duplicate lines. Legacy exporter and direct writer call paths retain their existing positional signatures.
- **Evidence:** focused M5.4 writer tests passed, including float/rotation/height preservation, bottom-origin conversion, incomplete/unreviewed filtering, reviewed generated records, exact port sea references, compatibility markers, stage forwarding, and legacy direct calls. Existing export safety/planner/determinism and M5.1 placement persistence/remap tests passed as well; compile and diff checks passed.
- **Next controlled slice:** add a foundation placement completeness/review validation gate around the manager contract, then use the accepted-record contract for the editor and weather writer.

### M5 checkpoint — explicit proposal acceptance workflow

- **Completed:** pure land and port proposal results can now be ingested into `MapPlacementManager` without changing their generated/unreviewed status. Existing authored/reviewed records are protected by default; replacing an unreviewed generated record requires an explicit flag. A separate helper accepts only explicitly selected stored keys/ports, and invalid pre-reviewed proposal inputs fail before manager mutation.
- **Evidence:** proposal generator, port proposal, workflow, manager, persistence, M3.3e placement, validator-registry, and export-planner tests passed; the workflow reports are stable and preserve float transforms and exact sea references.
- **Next controlled slice:** add weather-position writing/spacing validation, then expose the accepted placement contract through the editor and overlay.

### M5 checkpoint — foundation placement review gate

- **Completed:** `validate_manager_placement_completeness` now checks the placement manager without mutating it, requires six reviewed/accepted slots for every land province, ignores sea-only provinces, and reports unreviewed building/port/weather records that foundation writers would omit. The foundation validator registry and planner use the gate; draft/candidate runs warn, while frozen/accepted runs block.
- **Evidence:** focused M5 gate, M3.3e, registry, and planner tests passed, including malformed duck-typed records, deterministic findings, no input mutation, severity transitions, and manager-less legacy compatibility.
- **Next controlled slice:** implement authored/generated weather positions with explicit review and spacing/containment validation.

### M5 continuation note — resume tomorrow (2026-09-18)

- **Current state:** M5.1, M5.2a–d, and M5.4 are implemented and checked above. The latest implementation commits are `857d285` (proposal ingestion/acceptance) and `5a037e0` (foundation completeness/review gate); the latest plan checkpoint is `ddf84bd`.
- **Stopped work:** a narrowly scoped Muse Spark weather-writer task was launched for M5.5 and stopped at the end of today without a final response or repository diff. The worktree was clean after stopping, so there is no partial weather implementation to preserve or review.
- **First task tomorrow:** relaunch/retry the small M5.5 writer slice. Review `export/writers/map/strategic_regions.py`, `export/stages/regions.py`, and the legacy forwarding wrapper in `export/mod_exporter.py`. Keep all new parameters trailing and preserve old direct-call output. Foundation must write only reviewed/accepted manager weather records, remap original strategic-region IDs to emitted IDs, preserve float coordinates/height/bottom-origin conversion/size, and omit centroid fallback; compatibility profiles may retain deterministic centroid fallback.
- **Second task:** add and integrate a pure weather validator for strategic-region containment and minimum spacing, with warnings in draft/candidate and blockers in frozen/accepted lifecycles. It must cover multiple positions per region and malformed/no-input cases without mutating the manager.
- **Then:** run focused weather, stage, planner, registry, writer, and M5 placement tests; update the M5.5 checkbox/checkpoint only after those pass. Continue with M5.3 editor/overlay integration, then perform the full M5 regression and repository test/compile/diff checks. M5.2 remains unchecked until the proposal/acceptance contract is exposed through the editor/export flow.

### M5 checkpoint — weather positions (2026-09-19)

- **Completed:** `write_weatherpositions` accepts trailing placement/region/profile inputs without breaking legacy direct calls. Foundation output emits only reviewed/accepted manager weather, supports multiple records per region, preserves float coordinates and height, converts to the bottom-origin map axis, normalizes unsupported sizes safely, remaps original strategic-region IDs (including empty-region gaps), and omits centroid fallback. Acceptance/scaffold/legacy output overlays reviewed records and keeps deterministic centroid fallback only where needed. `validate_manager_weather_positions` now reports missing region coverage, malformed/out-of-bounds/wrong-region records, and same-region spacing violations without mutation; draft/candidate lifecycles warn and frozen/accepted lifecycles block. Stage, legacy wrapper, registry, and planner forwarding are covered.
- **Evidence:** `pytest -q tests/domain/test_m5_5_weather_validator.py tests/export/test_m5_5_weather_writer.py tests/domain/test_m5_placement_gate.py tests/domain/test_m3_3e_placement.py tests/export/test_m5_4_placement_writers.py tests/export/test_m2_planner.py tests/domain/test_m3_3_registry.py tests/export/test_m5_1_placement_pipeline.py` passed (100 tests); focused writer rerun passed (12 tests); compile, diff, and worktree checks passed. The implementation is committed as `c3b2f68`.
- **Worker/review note:** two narrow Muse Spark workspace-write attempts were used. The first wrote the weather writer/tests before stalling; the second partially edited the validator export list before stalling. The parent reviewed, repaired, completed, integrated, and tested the resulting diff. No credential or protected `.codex` content was read or stored.
- **Next controlled slice:** expose M5.2 proposal acceptance and M5.3 placement editing/overlay through the UI/export workflow; keep M5.2 unchecked until proposal generation is connected to that acceptance flow. Then run the full M5 regression and repository compile/diff checks.

### M5 checkpoint — headless proposal workflow (2026-09-19)

- **Completed:** `services/placement_proposals.py` now provides a narrow, filesystem-free orchestration layer for generating and storing land-slot and explicitly sea-mapped port proposals. It never accepts generated records implicitly; selected acceptance is a separate call. Replacement remains opt-in and cannot overwrite authored or reviewed records.
- **Evidence:** the worker’s focused service suite and an independent rerun passed (11 tests), including deterministic output, diagnostics, explicit mapping failures, replacement/protection semantics, selected acceptance, and input immutability. Compilation and diff checks passed. The implementation is committed as `88fa8b9`.
- **Worker/review note:** Muse Spark was given only the service and service-test files. The parent independently checked the generator signatures, manager APIs, status/provenance rules, and test behavior before committing. No UI, export, `.codex`, or credential files were touched.
- **Next controlled slice:** connect this service to an explicit placement request/review surface, beginning with a small controller-facing request boundary; keep M5.2 and M5.3 unchecked until users can review and accept proposals through the application flow.

### M5 checkpoint — controller proposal boundary (2026-09-19)

- **Completed:** `PlacementController` now provides the application-facing headless boundary for land-slot and explicitly sea-mapped port proposal generation, plus selected acceptance. Proposal and acceptance mutations use the existing `ManagerSnapshotCommand`/`CommandHistory` pattern, mark the project dirty only when records change, and emit a stable `placement_changed` event for future UI consumers.
- **Evidence:** focused controller tests and independent regression passed (66 tests across proposal service, controller, generator workflow, placement manager, and command history); compilation and diff checks passed. The implementation is committed as `1343c9e`.
- **Worker/review note:** Muse Spark was restricted to `controllers/placement.py` and `tests/controllers/test_placement.py`. The parent verified the snapshot/redo semantics and confirmed no-op/error paths leave the manager, dirty flag, event stream, and history unchanged.
- **Next controlled slice:** register the controller in the main-window controller set and add a small placement review panel with generate/review/accept actions; keep M5.2 and M5.3 unchecked until the panel is wired to this boundary.

### M5 checkpoint — standalone placement review page (2026-09-19)

- **Completed:** `features/map/placement/page.py` provides the review-side UI contract for explicit land-to-sea mapping entry, slot/port proposal requests, diagnostics, deterministic checkable records, and selected-only status advancement. It has no manager, filesystem, export, or implicit-acceptance behavior.
- **Evidence:** independent Qt regression passed (40 tests), including strict mapping validation, signal payloads, deterministic record ordering, checked-selection extraction, diagnostics/status rendering, and construction without global map-size state. The implementation is committed as `0de9d31`.
- **Worker/review note:** Muse Spark produced the authorized widget/test/localization files but did not return a final response before the bounded run was stopped. The parent completed the safe classification fix for non-slot/non-port records, reran the full focused suite, and reviewed the signal contract.
- **Next controlled slice:** wire `PlacementController` and `PlacementPage` into `ToolPanel`/`MainWindow`, refresh records on `placement_changed`, and keep the parent M5.2/M5.3 boxes open until the page drives a live application path and map overlay/editing exists.

### M5 checkpoint — live placement proposal path (2026-09-19)

- **Completed:** the placement page is now reachable as a logistics sub-mode, the `PlacementController` is registered in the main editor controller set, and generate-slots, explicit generate-ports, selected acceptance, and refresh actions are routed to the live project manager. Project reload/new/import refreshes the page, and placement mode uses the strategic-region canvas base until a dedicated overlay exists.
- **Evidence:** focused wiring, placement UI, English UI, and logistics tests passed (48 tests); compilation and diff checks passed. The implementation is committed as `89a5b35`.
- **Worker/review note:** the wiring Muse attempt timed out without authorized changes and left only three temporary helper scripts; the parent removed those artifacts and implemented/reviewed the bounded routing patch. No credentials or protected `.codex` files were touched.
- **Next controlled slice:** add the first read-only placement map overlay (provenance/review markers and collision diagnostics) without dragging/editing yet; then add undoable transform editing before closing M5.3.

### M5 checkpoint — proposal generation integration complete (2026-09-19)

- **Completed:** the proposal path is now closed from explicit editor request through manager persistence, selected review/acceptance, and export preflight. Both CLI export branches load and forward `MapPlacementManager`; enforced foundation output refuses manager-less centroid fallback while legacy manager-less draft callers retain compatibility through an explicit stage flag. The placement editor exposes an unchecked replacement opt-in for unreviewed generated records only, and readiness/preflight surfaces incomplete or missing foundation placements without auto-accepting them.
- **Evidence:** the combined M5 placement/weather/export/UI regression passed at 100%; focused foundation-safety, readiness/report/dialog, proposal-service/controller, and placement UI suites passed; touched files compiled and `git diff --check` passed. Implementation commits: `3a302b9`, `ba229f2`, and `155a48a`.
- **Worker/review note:** a read-only Muse Spark gap audit identified the three bounded slices. Two workspace-write workers completed the export-safety and editor slices; a third readiness worker reached the 15-minute bound without a final response but left a complete diff, which the parent reviewed, cleaned of temporary artifacts, repaired for diff hygiene, and independently tested. No credentials or protected `.codex` content were touched.
- **Next controlled slice:** M5.2 is complete; continue with post-M5 integration or the next milestone rather than adding implicit proposal acceptance.

### M5 checkpoint — read-only placement overlay (2026-09-19)

- **Completed:** the first overlay slice is now complete. A pure deterministic model produces stable, bounds-aware slot/port/building/weather/VP/collision markers with provenance/review roles; the canvas renders them in a hidden-by-default transparent layer; and MainWindow supplies all live placement records, VP centroids, and read-only `placement.collision` findings while enabling the layer only in placement mode.
- **Evidence:** focused overlay model, canvas, MainWindow wiring, placement UI, and existing canvas regressions passed independently (17 model tests, 18 canvas/related tests, and 51 wiring/UI tests across the worker and parent reruns); compilation and diff checks passed. The implementation is committed as `9ef3a0b`, `8301b93`, and `507057a`.
- **Worker/review note:** two narrowly scoped Muse Spark workers were used sequentially. The parent independently reviewed both diffs and reran the relevant suites. No controller/manager mutation, credential, or protected `.codex` file was touched.
- **Next controlled slice:** add a small pure transform-update/undo contract for selected placement records, then wire selection and drag/rotation/reset interactions through `PlacementController`; keep M5.3 open until those edits are undoable and tested.

### M5 checkpoint — placement editor and overlay complete (2026-09-19)

- **Completed:** M5.3 now provides a standalone deterministic overlay model, map-sized transparent placement markers with provenance/review roles, explicit province-border/coastline context, VP/collision diagnostics, marker selection, clamped drag previews, x/y-only drag intent routed through the undoable `PlacementController`, and numeric rotation/height editing plus neutral reset through the page editor.
- **Evidence:** the combined M5 placement/weather/export/UI regression passed; focused overlay, interaction, controller, and UI suites passed; all touched files compiled and `git diff --check` passed. Implementation commits: `9ef3a0b`, `8301b93`, `507057a`, `3b6b3b4`, `14798d2`, `902a245`, `42d993e`, `d3e5e31`, `5a02a02`, `50e106b`, and `69b4d50`.
- **Worker/review note:** sequential Muse Spark workers handled narrow pure-model, canvas, service, controller, page, ToolPanel, and MainWindow slices. One canvas-interaction worker was allowed the full 15-minute window, stopped cleanly with no diff, and the parent implemented and reviewed that narrow slice. The parent independently reran the full regression. No credentials or protected `.codex` content were touched.
- **Next controlled slice:** M5.2 proposal-generation integration remains open; do not mark M5 complete until the proposal acceptance/export flow is closed.

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

### M6 implementation checklist (2026-09-19)

- [x] M6.1 — Per-path `AssetResolution` now records disposition, source/provenance, hashes, dirty reason, output owner, and profile rule; legacy manifest records remain readable.
- [x] M6.2 — Indexed terrain/city writers resolve palettes through the selected target, and missing target palettes block frozen/accepted profile-aware exports instead of silently falling back.
- [x] M6.3 — The selected terrain-definition registry parses terrain type, palette indices, texture, spawn-city, snow, and custom/dependency entries; selected registry indices are validation authority.
- [x] M6.4 — Tree dimensions, legal indices, profile overrides, default-map filtering, deterministic generation, and header contracts are implemented for observed and custom map sizes.
- [x] M6.5 — Profile-aware DDS strategy, deterministic dependency-free BC3/DXT5 encoding, mip chains, payload/header validation, compatible-byte preservation, and explicit unsupported-format blockers are implemented.
- [x] M6.6 — Map-art families have explicit generated/preserved/inherited/omitted/blocked behavior with actionable provenance and compatibility reasons in the resolution manifest.
- [x] M6.7 — `map/colors.txt`, airport, rocket-site naming variants, city text, and other optional structural files are preserved, omitted, or reported explicitly without empty legacy output by default.
- [x] M6.8 — The opt-in visual-regression helper creates deterministic miniatures/contact sheets and stable human-approval records without storing copyrighted source art.

### M6 checkpoint — graphics and asset-resolution pipeline (2026-09-19)

- **Completed:** M6 is implemented in three reviewed batches: target-aware asset/palette/structural handling, selected terrain and tree contracts, and the DDS/map-art/visual-regression pipeline. The final DDS path preserves compatible imports, emits BGRA8 where required, emits deterministic BC3/DXT5 water/FOW assets with the selected mip policy, and blocks unsupported contracts at frozen/accepted scope.
- **Evidence:** focused M6A/M6B/M6C tests, existing DDS/profile/asset/manifest tests, the M5 regression slice, compilation, and diff checks passed. The broader domain/services/foundation/export run passed except the pre-existing byte-baseline fixture mismatch that reports intentional M6A/M6B changes to `map/terrain.bmp` and optional structural files. Implementation commits are `7a973b0`, `4619baf`, and the grouped M6 graphics commit recorded with this checkpoint.
- **Worker/review note:** a read-only Muse Spark audit identified the three batches. Grouped workspace-write workers implemented them; the parent independently reviewed, repaired, added regression coverage, optimized the full-map mip path, and ran the broad regression. The follow-up encoder worker was allowed beyond 20 minutes while responsive, per the standing Muse policy. No credentials or protected `.codex` content were touched.
- **Next controlled slice:** begin M7 assisted engine acceptance; refresh the byte-baseline fixture only as a deliberate compatibility-baseline change, not as an implicit graphics workaround.

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

### M7 implementation checklist (2026-09-19)

- [x] **M7.1 - explicit automation boundaries:** added a dependency-free assisted-acceptance contract and dry-run-first CLI; no GUI or mouse automation is attempted, and game execution is opt-in.
- [x] **M7.2 - isolated acceptance artifact:** reused the existing M2.5 acceptance profile, which creates a sibling acceptance artifact with deterministic unused tags, minimum owners/OOB/bookmark content, and manifest provenance; the harness requires and fingerprints the exact supplied artifact.
- [x] **M7.3 - local acceptance harness:** added artifact/manifest/lock verification, deterministic inventory identity, pre-run log snapshots, post-run fresh-range classification, fresh-save evidence, bounded no-shell launch execution, and `engine_acceptance.json` recording.
- [x] **M7.4 - human checklist contract:** added ten stable named in-game checks, CLI help/output rendering, notes, and status gating so an assisted run cannot pass while required checks remain unchecked.

### M7 checkpoint - assisted engine-acceptance harness (2026-09-19)

- **Completed:** the local M7 harness is implemented in `domain/engine_acceptance.py`, `services/engine_acceptance_service.py`, and `tools/run_engine_acceptance.py`. It records exact artifact inventory/identity, supports safe fresh-log and save evidence, classifies findings, launches only with explicit `--execute`, and emits a JSON result with stable run identity and human-checklist state.
- **Evidence:** the focused M7 suite and relevant manifest, determinism, and validation tests pass; compilation and diff checks pass. Parent review caught and fixed post-launch evidence ordering, failed-launch pass-through, and missing/invalid-manifest acceptance. No real HOI4 process was launched during automated tests.
- **Acceptance status:** the implementation checklist is complete, but Gate D is not claimed yet. A real run still needs the exact exported acceptance artifact, a selected local game/launcher, fresh logs, at least 30 in-game days, save/reload, and all ten human checks recorded as complete.
- **Next controlled slice:** run the harness against a real acceptance artifact when a suitable local HOI4 target is available; then begin M8 freeze/change-detection and content handoff work.

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

### M8 implementation checklist (2026-09-19)

- [x] **M8.1 - foundation lock contents:** added an expanded, deterministic lock contract with map/profile identity, foundation source hashes, geography/topology counts, placement and asset inventories, accepted validation exceptions, and optional engine-acceptance identity; acceptance-only country/gameplay managers and content paths are excluded.
- [x] **M8.2 - change classification:** added stable path-level comparison with breaking identity, breaking topology, foundation visual, placement, and non-foundation content classes plus rerun guidance.
- [x] **M8.3 - freeze/unfreeze workflow:** added candidate, freeze, exact-identity acceptance recording, compare, unfreeze-audit, and handoff operations through a safe CLI and the Qt export-result workflow; unfreeze requires a reason.
- [x] **M8.4 - handoff package:** added deterministic `FOUNDATION-HANDOFF.md` generation covering dependencies, dimensions and IDs, ownership/inheritance, exceptions, content boundaries, author rules, prohibited operations, and migration procedure.

### M8 checkpoint - foundation freeze and content handoff (2026-09-19)

- **Completed:** M8 lock, comparison, lifecycle, acceptance-record, handoff, CLI, and Qt workflow contracts are implemented. Real foundation exports now emit the expanded lock, while legacy plan-only lock callers remain compatible.
- **Evidence:** focused M8 and UI tests, M2/M3 manifest and determinism tests, M7 acceptance tests, validation tests, export safety/compact-ID tests, compilation, and diff checks pass. The full `tests/export` run has one pre-existing intentional baseline mismatch: `test_byte_diff.py` still expects the older `map/terrain.bmp` bytes and optional `map/airports.txt`/`map/rocket_sites.txt` inventory; this is the documented M6 baseline exception.
- **Acceptance status:** the M8 implementation checklist is complete, but no real Belgium foundation has been frozen or engine-accepted in this automated pass. Operational acceptance still requires the exact exported artifact, reviewed exceptions, a successful M7 acceptance record with matching identity, and a recorded freeze.
- **Next controlled slice:** apply the candidate/freeze/acceptance-record workflow to the exact Belgium artifact, then continue with M9 compatibility cleanup and release-candidate documentation.

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

- `README.md` with profile and foundation workflow, as well as with new English screenshots, updated functionality descriptions, updated links, and overall review;
- `README.md` to add "AmonStreeling", the original developer, into the credits, along with "Stuffi3000", the current developer of the fork.
- `docs/TUTORIAL.md` with draft → candidate → frozen → accepted lifecycle;
- `docs/wiki/map-core.md` with profile/manifest rules;
- `docs/wiki/buildings-supply.md` with graph and placement review;
- `docs/wiki/troubleshooting.md` with finding codes and engine harness;
- command-line help and export-dialog explanations.
- the release/version number to 1.4.0

Add `CHANGELOG.md` with a comprehensive changelog between version 1.3.4 and 1.4.0, spanning all commits made between these to versions

Release a new 1.4.0 release on Github with an updated .exe file.

### M9 implementation checklist (2026-09-19)

- [x] **M9.1 - compatibility rollout:** retained `export_full_mod()` and legacy bitmap/CSV helpers as compatibility facades; translated legacy scope dictionaries to `legacy_full` with deprecation warnings; preserved old project archives, `_manifest.txt` sidecars, and manager JSON schemas.
- [x] **M9.2 - behavior cleanup:** removed hard-coded CSV install discovery, centralized descriptor replacement-path policy, routed the legacy descriptor helper through the shared writer, made staged scaffold `MAX_PROVINCES` profile-aware, and labeled compatibility logistics proposals without reintroducing self-loop railways.
- [x] **M9.3 - release documentation:** updated README, tutorial, map/building/troubleshooting wiki pages, CLI help, export-dialog guidance, credits, version metadata, changelog, and regenerated English screenshots.
- [ ] **M9.3 external release:** build and publish the signed/verified 1.4.0 Windows package and GitHub release after the release artifact is reviewed.

### M9 checkpoint - migration cleanup and release candidate (2026-09-19)

- **Completed:** M9.1 compatibility adapters, M9.2 safe cleanup, and the M9.3 documentation/versioning slice are implemented and reviewed. Legacy callers remain usable while new exports use the staged profile/planner contracts.
- **Evidence:** focused M9 compatibility, planner, manifest/determinism, placement, graphics, validation, and CLI tests pass; English welcome/onboarding/tool-panel screenshots were rendered from the current Qt widgets; compilation and diff checks remain required before commit.
- **Known release boundary:** no GitHub release or Windows executable was published in this source change. The release still requires a clean PyInstaller build, artifact inspection, and an explicit publication step.
- **Next controlled slice:** complete Gate E on the Belgium artifact, run the full M10 test/review pass, then build and publish the reviewed 1.4.0 package.

## M10. Full Testing

- Test each milestone from a code point of view.
- Test the features from each milestone on the Belgium project.
- Specifically use the M7 testing harness in order to test a full export of the Belgium project.
- Review the "final" exported project and address potential shortcomings.
- Potentially release a 1.4.1 hotfix.

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
