# Design document: game-level preview + operation process reconstruction

> 2026-06-12 User Approval. Goal: To enable the tool to be released publicly to unfamiliar users - to solve the two core problems of "the map is a black box" and "the steps cannot be understood". The visual style (color matching/typesetting) will be done separately after the design is completed.

## Root cause diagnosis

1. **Black Box**: The map effect must be exported + open the game to see it. The cycle of "Adjust parameters → Export → Open the game → View the effect" is extremely slow.
2. **Can't understand**: 12 editing modes are tiled, and there are no interface elements to answer the new user's "What should I do now and what should I do next?"
3. The automatic generation capabilities (province/state/strategic area/terrain/height) are scattered inside each mode and in the export pre-check, and new users cannot find them.

## Three changes

### Change 1: The top level is reorganized by "production stage"

12 modes divided into 4 stages, top stage bar:

```
[① Draw the world] → [② Divide provinces] → [③ build a nation] → [④ Generate finished product]
 land/height map provinces/MainlandState(area)    Preview/Check
 terrain/river strategic area country export
```

- Clicking on a stage only displays the mode entry for that stage. New users face 2~3 choices at each step instead of 12.
- **The internal code of 12 modes does not change**, pure organizational layer
- Old users will not lose any functionality

### Change 2: Permanent "Production Progress" panel

Side list, status is calculated in real time from project data (reuse `views/export_dialog.py::check_project_readiness` and move to services layer):

- Each row: status icon + complete human description + [automatic generation] / [manual editing] direct button
- The bottom shows "N steps to export"
- Main path for new users: Draw land outline → Automatically generate list of points → Preview → Export

### Change 3: Game-level preview

Use the game's own files to synthesize the "map seen in the game" (the user does not need to provide files, its HOI4 installation directory is read during runtime):

| Game files | Purpose | Verified existence |
|---|---|---|
| `terrain={}` block of `common/terrain/00_terrain.txt` | terrain.bmp palette index → ​​atlas tile number | ✓ (lines 323-347) |
| `map/terrain/atlas0.dds` | Terrain material atlas 4×4 grid×512px | ✓ |
| `map/terrain/atlas_normal0.dds` | Normal (bump light and shadow) | ✓ |
| `map/terrain/colormap_water_*.dds` | Ocean tone | ✓ |

Compositing pipeline: Terrain map base → Height map light and shadow → Tone layer (use your own data with the colormap function of this tool, the size will match) → Oceans are colored by depth → Rivers → Optional borders.

Honest boundaries: Materials/colors/mappings are 100% original to the game; light and shadow are approximate (the game shader is not public); 3D mountain silhouette/tree models are not included. Positioning: Eliminate 95% of "game opening verification".

### Incidental: Terminology speaks human language

Comprehensive inspection of interface copywriting: complete verb-object phrase + human words first, original terminology brackets retained.
**Explicit request from the user: The text description must be complete and clear, and abbreviations are prohibited - "build a country" rather than "build a country". **
Example: `State → area(State)`, `strategic area→ weather zone(strategic area)`, `VP → victory point(city value)`. Only the display copy is changed, the data structure and code identifier are not changed.

## Implementation Milestones

| Milestone | Content | Acceptance Method |
|---|---|---|
| **M1 Preview** | `services/game_assets.py`（Read game assets)+ `domain/preview/compositor.py`（purenumpy Synthesis)+ `features/map/preview/`（preview mode)| Open the Aurora project(5632×2048)Cut preview and compare with in-game screenshots|
| **M2 process layer** | Stage bar + progress panel (`views/workflow_panel.py`) + automatically generated button return | Simulate new user: can you get to successful export by just following the panel |
| **M3 entrance and copywriting** | Two ways to welcome the page (quickly generate the world/draw it from scratch) + humanize all terminology | The copywriting must be reviewed by users one by one |

### M1 Technical Points

- The first step is to verify whether Pillow can decode the compressed format of atlas0.dds; if not, introduce a decoding library (such as texture2ddecoder)
- Performance strategy: Preview and synthesize a cache, manually refresh after editing; no real-time follow-up
- The game directory is missing: a pop-up window allows the user to select a directory; if the file is missing, it will be downgraded to solid color rendering and prompts without crashing.
- Test: Use text fixtures for mapping table analysis; use small-size fake textures for the compositor; game files do not enter CI

## Risk

- Texture decoding format (the first step of M1 is verification, there are alternative libraries) ✅ Verified and natively supported by Pillow
- M2 is the only part that touches the existing main window layout, ensuring zero changes in the 12 mode functions
- The volume is the largest single transformation of the project, and it will be independently inspected and accepted according to milestones, and will not be merged at one time.

## Final execution sequence (2026-06-12 user approval after architecture planning)

Terrain refinement follows **route C**: automatically generated base (parametric/seeded/regenerable) + manual brush refinement + undoable.

| Steps | Content | Dependencies |
|---|---|---|
| ①Basics | P1 canvas rendering dispatch registration (delete `_render_X_mode` hard code + dead code `merge_provinces`); P2 `check_project_readiness`+`CheckItem` moved to `services/readiness_service.py` | None |
| ② Preview into the software | `features/map/preview/` (page/renderer) + container registration + game directory selection + manual refresh cache policy | P1 |
| ③routeCTerrain refinement| `domain/generators/base.py` Generator Agreement+ `commands/map/apply_generator.py` general commands;terrain_detail first access| ②（You can adjust it only if you can see it)|
| ④M2 process layer| `views/workflow_panel.py` Progress panel (subscription`PROJECT_READINESS_CHANGED`）+ stage bar| P2、③（The automatic button must have something to press)|
| ⑤M3 entrance copywriting | Two paths for the welcome page + humanized terminology | ④ (finalized stage name) |
| Independent | `mod_exporter.py` Split | Unrelated, scheduled separately |

Technical decision: The generator protocol is established immediately (drag it to the fourth generator and then unify it, which is a big migration); the completion check uses the "recalculation after coarse-grained events" strategy, and the actual measurement is slow and then optimized; the preview has no meaningful partial rendering, and the partial will be fully processed.
