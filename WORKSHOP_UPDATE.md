# v1.2.0 Update Notes

This release includes the changes introduced since v1.1.2, including the three-layer state overlay, a full UI audit, export fixes, and crash fixes.

## Localization and UI

- Consolidated the application around its maintained English catalog and removed obsolete translation catalogs.
- Added catalog-audit and key-management tools so missing keys and placeholder mismatches are easy to detect.
- Added keyword arguments to `tr()` and made formatting errors visible instead of silently ignoring them.
- Unified the visual treatment of the 13 map-editing pages: Land, Density, Province, Height, Terrain, River, State, Country, Continent, Strategic Region, Logistics, Colormap, and Default Map.
- Made continent-page manager actions undoable.
- Added province lookup by ID with map highlighting.

## State overlay

The state-editing view now makes ownership easier to read while provinces are being assigned:

- The base color blends state and country colors.
- Three-pixel white borders mark boundaries between assigned countries.
- Selecting a state highlights every state owned by the same country.

## Stability

- Fixed packaged-startup failures caused by missing qdarktheme `.qss` and `.svg` resources.
- Fixed strategic-region, province-merge, and incremental-generation failures.
- Fixed state-owner lookup errors by using the current owner-resolution API.
- Isolated generated content from the vanilla namespace during export.

## Export

- Added an independent descriptor toggle so content can be exported without overwriting an existing `descriptor.mod`.
- Fixed export-size limits, `from`/`import` handling, and transform-copy behavior.

## Verification

The repository now includes English-only localization checks, placeholder checks, and regression coverage for the export pipeline.
