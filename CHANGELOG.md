# Changelog

All notable changes to HOI4 Map Maker are documented here. Entries are
organized by what users can do, rather than by internal implementation
milestones.

## [1.4.3] - 2026-09-22

### Safer, more actionable export preflight

**Export checks now catch more map and logistics problems before anything is
written, and explain where the problem needs attention.**

- Added shared logistics validation for railway and supply references,
  adjacency endpoints and rules, graph topology, ports, duplicate routes, and
  exception coverage.
- Readiness and preflight findings now include affected province IDs and
  logistics evidence, so topology problems can be located from the UI.
- Protected non-empty export destinations, files, and symbolic links by
  default; pre-created empty directories remain safe to use.
- Made preflight previews reusable across profile switches, kept the dialog
  closable without blocking the interface, and clarified readiness warnings
  and dark-theme tooltips.
- Enforced one coherent land/lake surface per province and skipped
  lake-dominant provinces when generating land placement proposals.

### Faster, clearer logistics and placement editing

- Added a Find tool for provinces, states, and strategic regions with exact
  matches, substring search, and conservative suggestions.
- Clarified Logistics and Placements navigation, editing controls, map
  backgrounds, map markers, and victory-point selection.
- Added visible feedback during placement generation and accelerated proposal
  generation, tab validation, and placement rendering through indexed province
  data and cheaper large-map calculations.
- Refreshed continent data when entering the mode so the editor reflects the
  current project immediately.

### Repository maintenance

- Updated release/publication evidence and repository ignore rules alongside
  the feature and stability work.

## [1.4.2] - 2026-09-22

### Faster large-project loading

**Opening a large project is fast again, including the Belgium project used
for regression testing.**

- Deferred hidden placement-overlay work until the overlay is actually shown.
- Cached province centroids and skipped empty placement validation during load.
- Deferred logistics component-color rebuilding until Logistics mode is active,
  then vectorized the component and highlight calculations.
- Reduced the measured Belgium project load from about 51 seconds to about
  1.3 seconds.

## [1.4.1] - 2026-09-22

### Engine testing and safer launches

**Real acceptance runs now prove that HOI4—not only its launcher—actually
started with the intended export.**

- Added a direct launcher-bypass path and clear failure reporting when Steam
  leaves the Paradox launcher open without starting the game.
- Managed activation temporarily enables exactly one exported mod, verifies
  that exact name in fresh game logs, then restores the user's previous
  launcher configuration.
- A passing run now requires a newly generated `error.log`, exact active-DLC
  evidence where relevant, every requested fresh save, and all independent
  failure reasons instead of stopping at the first one.
- Tightened log classification so audio-only and unavailable-DLC noise can be
  reported without concealing map, asset, script, or country errors.

### Playable acceptance scenario

**The disposable test mod now reaches the bookmark and supports a meaningful
map test in HOI4.**

- Corrected bookmark, country-history, unit-order, naming, and current-game
  syntax that previously prevented or weakened the real harness run.
- Added a selectable land division, commander, manpower, technologies, and
  convoys; assigned remaining states safely so moving the division no longer
  makes it disappear.
- Kept the naval-invasion check honest: unavailable scenario interactions can
  be recorded as a named, reasoned waiver instead of being falsely checked.
- Added safe amended checklist reports that preserve the original artifact,
  launch, log, save, and timestamp evidence.

### Foundation identity and freeze integrity

**Foundation locks now reject draft-level or hand-edited evidence.**

- Added a profile-independent source identity so the smaller foundation and
  playable acceptance exports can be tied to the same project snapshot while
  retaining their own artifact identities.
- Freeze ingestion recomputes report identity, run ID, checklist/log
  summaries, and final status before accepting a result.
- Locks and handoffs retain the exact acceptance-report SHA-256, creation
  time, waiver reason, and source-identity algorithm.
- Candidate and freeze commands re-evaluate findings under their own strict
  lifecycle contexts. This correctly leaves a foundation unfrozen when its
  authored placement review is incomplete.
- Corrected a successful river-validation message being emitted as a warning.

### Compatibility note

Older acceptance reports without embedded source identity can still use the
documented manifest bridge, but the captured manifest bytes and the report's
internal evidence must verify exactly. The Windows executable remains
unsigned; verify the package with the release's `SHA256SUMS.txt`.

## [1.4.0] - 2026-09-19

### At a glance

Version 1.4.0 turns the editor into a more complete map-production workflow:

- Build map layers and provinces from reference images, then refine them by
  hand.
- Prepare gameplay data, placements, logistics, and graphics with clearer
  review states and safer fallbacks.
- Validate an export, reproduce it from a stable source snapshot, and inspect
  exactly what changed.
- Freeze a reviewed foundation and hand it to content authors without losing
  the identity of the approved map.

### Map authoring from reference images

**The biggest change:** a reference image can now be the starting point for
real map data instead of only a visual guide.

- Added a reference-image color-mapping editor and generation of map layers
  from reference colors.
- Distinguished land, sea, and lake imports so each type follows the correct
  province workflow.
- Added manual province drawing, incremental generation, selection/deletion,
  and validation of reference-generated provinces.
- Added practical refinement paths for splitting, merging, lasso editing, and
  deterministic province rework.

### Terrain, rivers, hydrology, and city detail

**Map terrain is now easier to author as a coherent gameplay and visual
system.**

- Added terrain-attribute synchronization from the visual terrain layer,
  including a clear action for resynchronizing existing data.
- Added river and terrain validation coverage and made map-type-specific
  generation safer around coasts and water bodies.
- Added exported urban city models and urban-mask painting, while removing
  artificial city circles that did not represent authored data.

### Provinces, states, countries, and map gameplay data

**The editor now connects visual map work to recognizable HOI4 gameplay
structures.**

- Added victory-point editing and corrected the map-overlay toggle behavior.
- Added strategic-region generation and logistics-readiness indicators so
  missing gameplay structure is visible earlier.
- Preserved deterministic localization precedence so generated names reliably
  override the intended vanilla entries.

### Safer export and project compatibility

**Exports now have a staged, profile-aware path that can be reviewed before it
touches the destination.**

- Added game-target profiles, versioned project metadata, immutable source
  snapshots, typed export profiles, repair actions, and transactional staging.
- Added distinct `foundation`, `acceptance`, `scaffold`, and `legacy_full`
  responsibilities for the CLI and export UI.
- Added safer overwrite/backup behavior, UTF-8 CLI output, useful exit codes,
  and readiness indicators in the application.
- Made the vanilla game path configurable instead of assuming one local
  installation.
- Fixed exported-map startup failures, map-incompatible runtime scripts,
  session-load crashes, AI errors, strict province bounds, and total-conversion
  export crashes.
- Kept old project archives, manager JSON schemas, and `_manifest.txt`
  sidecars readable while the newer planner-based path is adopted.

### Validation and reproducible output

**A finished export now comes with evidence about whether it is safe to use and
whether it is the same artifact that was reviewed.**

- Added shared validation findings, reports, readiness gates, and repair
  policies across geometry, raster data, provinces, terrain, rivers,
  geography, logistics, placements, assets, and cross-layer relationships.
- Routed the same reports through the export UI, CLI, readiness services, and
  artifact verifier instead of maintaining separate summaries.
- Added deterministic foundation manifests containing source identity,
  output ownership, asset hashes, validation metadata, repair provenance, and
  accepted exceptions.
- Added versioned foundation locks, compatibility checks, deterministic
  inventories, and repeated-export tests to make accidental drift visible.

### Adjacency, railways, and supply networks

**Map connections now have an explicit review workflow instead of being
treated as opaque generated text.**

- Added adjacency review states, import/export, undoable editing, and rules
  for straits, canals, impassable borders, and map edges.
- Added deterministic railway and supply-graph analysis with component
  reports, disconnected-network exceptions, rendering, and readiness output.
- Added synthetic fixtures for difficult logistics cases and retained legacy
  supply-area output only as a clearly identified compatibility artifact.

### Placements and starting content

**Starting positions can now be authored, proposed, reviewed, and accepted
without silently becoming part of the foundation.**

- Added persistent placement records for province slots, ports, buildings,
  unit stacks, and weather positions.
- Added deterministic slot, port, and weather proposals with explicit review
  and acceptance workflows.
- Added placement-readiness findings, replacement opt-ins, and a boundary that
  blocks unreviewed foundation fallbacks.
- Added placement review pages, read-only map overlays, context guides,
  transform controls, undoable transforms, canvas selection/drag intent, and
  live overlay diagnostics.

### Graphics and packaged assets

**Generated and inherited map art now follows the same target/profile rules as
the rest of the export.**

- Added profile-aware resolution for generated, preserved, inherited, omitted,
  and unsupported assets.
- Added version-aware terrain registries, indexed BMP palettes, tree-map
  contracts, city/normal/water/fog-of-war/colormap handling, and deterministic
  map-art writers.
- Added DDS header and BGRA encoding contracts plus asset inventories and
  validation for optional structural assets.
- Kept safe legacy fallbacks for direct legacy callers while preventing them
  from silently defining reviewed foundation output.

### Acceptance, freeze, and handoff

**A reviewed map can now be tested and handed to the next phase with a clear
identity.**

- Added isolated acceptance content with collision-free test tags, fresh log
  capture, executable launch configuration, log classification, and saved
  acceptance records.
- Added start/tick/save/reload evidence and exact-artifact identity checks to
  the acceptance harness and CLI.
- Added candidate, freeze, unfreeze-audit, acceptance-record, compare, and
  handoff operations in the service, CLI, and export-result UI.
- Added foundation locks for dimensions, profile/target identity,
  province/state/region/topology counts, placements, assets, exceptions, and
  acceptance identity.
- Added deterministic `FOUNDATION-HANDOFF.md` generation with ownership,
  inheritance, dependencies, exceptions, author rules, prohibited changes,
  and migration guidance.

### User experience, documentation, and maintenance

**The workflow is now easier to understand for a new user and easier to
diagnose when something needs attention.**

- Completed the English-only interface cleanup and refreshed onboarding and
  tool-panel screenshots from the current UI.
- Updated the tutorial, map/building/troubleshooting wiki pages, export
  contract, CLI help, and export-dialog guidance around profiles, validation,
  acceptance, and handoff.
- Added targeted tests, synthetic fixtures, metadata-only regression evidence,
  and clearer dependency/pytest guidance without committing base-game
  binaries.
- Added metadata-only compatibility evidence for HOI4 1.19.3
  headers, and DDS contracts without shipping base-game binaries.
- Corrected the release build dependency to installable `PyQtDarkTheme2` and
  published the Windows package with a separate SHA-256 checksum file.

### Migration notes

- Existing project archives without `project_meta.json` still load as `draft`.
- Existing `_manifest.txt` sidecars remain readable.
- Existing callers that pass a `scope` dictionary continue to work through
  `legacy_full` and now receive a `DeprecationWarning`; new callers should use
  profiles and planner APIs.
- Existing manager JSON schemas remain unchanged.
- The executable in the 1.4.0 package is hash-verified but not Authenticode-
  signed. Verify downloads with `SHA256SUMS.txt` from the GitHub release.
- The full export byte baseline retains the documented M6 exception for the
  newer terrain bytes and the removed legacy airport/rocket-site inventory;
  it was not silently refreshed by this release.

## [1.3.4] - 2026-07-11

- Strategic-region export preflight and disconnected-region repair.
- Cross-region state handling and enclave warnings.
- Provincial-terrain resynchronization with confirmation and undo.
- UTF-8 validation and language-setting reliability improvements.
- World-normal regeneration and post-export strategic-region checks.

[1.4.3]: https://github.com/stuffi3000/hoi4-mod-maker/releases/tag/v1.4.3
[1.4.2]: https://github.com/stuffi3000/hoi4-mod-maker/releases/tag/v1.4.2
[1.4.1]: https://github.com/stuffi3000/hoi4-mod-maker/releases/tag/v1.4.1
[1.4.0]: https://github.com/stuffi3000/hoi4-mod-maker/releases/tag/v1.4.0
[1.3.4]: https://github.com/stuffi3000/hoi4-mod-maker/commit/3dda2da6c90e6eec532f35d4a5e919cc135ecd29
