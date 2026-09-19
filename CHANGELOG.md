# Changelog

All notable changes to HOI4 Map Maker are documented here. Version 1.4.0
covers the complete development range after the 1.3.4 release through the
published map-foundation 1.4.0 release on 19 September 2026, including the
foundation-plan implementation commits and their checkpoints.

## [1.4.0] - 2026-09-19

### Map editing and English UI

- Completed the English-only interface cleanup and removed untranslated
  runtime/editor paths.
- Added reference-image role mapping and reference-assisted land, sea, lake,
  province, and river generation.
- Added manual province drawing, incremental generation, merge/split/lasso
  refinement, and validation of reference-generated provinces.
- Completed the Belgium Map v1.1 terrain, hydrology, relief, urban-mask, and
  deterministic province-rework workflows.
- Added terrain-attribute synchronization, victory-point editing, city-map
  generation, preview lighting, political shading, and map-mode diagnostics.
- Regenerated the onboarding and tool-panel screenshots from the current
  English UI and refreshed the tutorial and release documentation.

### M0-M2: safe, staged export foundation

- Added metadata-only regression evidence for the Belgium map, HOI4 1.19.3.0
  headers, and DDS contracts without committing base-game binaries.
- Completed dependency/pytest marker documentation and CLI UTF-8/exit-code
  handling.
- Added game-target and versioned map-profile contracts, project metadata, and
  backward-compatible loading for old archives.
- Added immutable export snapshots, typed export profiles, repair actions,
  validation policy, transactional staging, overwrite/backup behavior, and
  the planner-backed CLI/UI path.
- Separated `foundation`, `acceptance`, `scaffold`, and `legacy_full` output
  responsibilities and kept live project managers unchanged during staged
  export.

### M3: shared validation, manifests, and determinism

- Added shared typed validation findings, gate policy, reports, readiness
  integration, CLI reporting, export-dialog reporting, and artifact verifier
  integration.
- Added raster, province definition, terrain, rivers, geography, logistics,
  placement, asset, and cross-layer validation suites.
- Added deterministic foundation manifests with source fingerprints, output
  ownership, asset hashes, repair/provenance records, accepted exceptions,
  and versioned lock compatibility.
- Added deterministic inventory/hash tests and repeated-export coverage.

### M4: adjacency and logistics semantics

- Added explicit adjacency review states, import/export, undoable editing,
  adjacency-rule validation, and synthetic fixture coverage for straits,
  canals, impassable borders, and map-edge cases.
- Added deterministic railway/supply graph analysis, component reporting,
  disconnected-network exceptions, and logistics rendering/readiness output.
- Preserved legacy supply-area output only as an explicitly documented
  compatibility artifact.

### M5: authored placements

- Added authored placement managers and persistence for province slots, ports,
  buildings, unit stacks, and weather positions.
- Added deterministic slot/port/weather proposals, review and acceptance
  workflows, replacement opt-ins, placement-readiness findings, controller
  boundaries, and editor review pages.
- Added read-only placement overlays, map-context guides, transform contracts,
  undoable transforms, canvas selection/drag intent, and live diagnostics.
- Blocked unreviewed foundation centroid/building fallbacks while retaining
  labeled compatibility proposals for disposable profiles.

### M6: graphics and asset contracts

- Added profile-aware generated/preserved/inherited/omitted/unsupported asset
  resolution and asset inventories.
- Added version-aware terrain registries, indexed BMP palettes, tree-map
  contracts, city/normal/water/FOW/colormap handling, DDS headers, BGRA
  encoding, and deterministic map-art writers.
- Added explicit target-install resolution and validation for palettes and
  optional structural assets, with safe legacy fallbacks only for legacy
  direct callers.

### M7: assisted engine acceptance

- Added deterministic acceptance content with collision-free test tags,
  isolated artifact staging, executable launch configuration, fresh log
  capture, log classification, and acceptance records.
- Added the engine-acceptance service, CLI harness, manifest integration, and
  focused tests for start/tick/save/reload evidence and exact artifact
  identity.

### M8: foundation freeze and content handoff

- Added expanded deterministic foundation locks for dimensions, profile/target
  identity, province/state/region/topology counts, placements, assets,
  exceptions, and engine acceptance identity.
- Added breaking-change classes and stable comparison/rerun guidance for
  identity, topology, foundation visual, placement, and non-foundation content.
- Added candidate, freeze, unfreeze-audit, acceptance-record, compare, and
  handoff operations in the service, CLI, and export-result UI.
- Added deterministic `FOUNDATION-HANDOFF.md` generation describing ownership,
  inheritance, dependencies, exceptions, author rules, prohibited changes,
  and migration procedure.

### M9: migration cleanup and published release

- Kept `export_full_mod()` and legacy bitmap/CSV helpers as compatibility
  facades while the staged writers become the preferred path.
- Added legacy scope translation with deprecation warnings, preserved old
  archive/`_manifest.txt` loading, and kept manager JSON schemas stable.
- Removed hard-coded absolute install discovery from the CSV compatibility
  writer, centralized descriptor replacement-path policy, and routed the
  legacy descriptor helper through the shared writer.
- Made staged scaffold province limits profile-aware; `legacy_full` retains
  its historical 25,000 floor while new scaffold exports use the actual
  province count plus headroom.
- Kept generated logistics and placement compatibility helpers labeled as
  proposals rather than silently treating them as reviewed foundation data.

### Migration notes

- Existing project archives without `project_meta.json` still load as `draft`.
- Existing asset sidecars using `_manifest.txt` remain readable.
- Existing `scope` dictionary callers continue to work through `legacy_full`
  and now receive a `DeprecationWarning`; migrate new callers to the profile
  and planner APIs.
- Existing manager JSON schemas are unchanged.
- The full export byte baseline still has the documented M6 exception for the
  newer terrain bytes and removed legacy airport/rocket-site inventory; it is
  not silently refreshed by this release.

## [1.3.4] - 2026-07-11

- Strategic-region export preflight and disconnected-region repair.
- Cross-region state handling and enclave warnings.
- Provincial-terrain resynchronization with confirmation and undo.
- UTF-8 validation and language-setting reliability improvements.
- World-normal regeneration and post-export strategic-region checks.

[1.4.0]: https://github.com/stuffi3000/hoi4-mod-maker/releases/tag/v1.4.0
[1.3.4]: https://github.com/stuffi3000/hoi4-mod-maker/releases/tag/v1.3.4
