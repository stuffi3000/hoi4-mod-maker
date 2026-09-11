# Height map local refinement (Refine) function design

**Date**: 2026-04-21
**One sentence**: Select an area → retain the height shape drawn by the user → the algorithm superimposes ridges/erosion/noise on it → the boundary feathers into the surroundings.

---

## 1. Question

When users draw the heightmap by hand, they will get the result of "the shape is right, but it looks like a pie":
-The tops of mountains are flat (no peaks)
- No ravines (lack of erosion)
- The whole image is uniform (lack of rocks/texture)

Shortcomings of existing tools:
- "Intelligent generated height" is a **full map** regeneration, which will cover the user's hand-drawn mountain location → fights with the user's intention
- "Draw a mountain range" (ridge tool) is to **draw a line** to generate a new ridge → cannot "touch up the already drawn pie"
- "Height Brush (Raise/Sink/Smooth)" is manual sculpting → users are tired of painting before looking for partial reshaping

**Real needs of users**: Based on what I drew, let the algorithm help me "beautify" the selected piece.

---

## 2. Goal

Design a **Refine Heightmap Region** function to satisfy:

1. **Non-destructive**: The height shape drawn by the user (which is higher and which is lower) is 100% retained.
2. **Selection**: Draw a circle freely with the lasso, and only refine the inside of the circle
3. **Adjustable Strength**: Slider 0% = no movement, 100% = harder
4. **Three types of processing can be selected individually**: Ridge sharpening / Erosion gully / Noise texture
5. **Border Feather**: Gradient outside the circle→inside the circle 20 pixels wide, no hard edges
6. **Preview available**: Check "Real-time preview" and drag the slider to see
7. **Undoable**: Ctrl+Z rollback

---

## 3. UX Process

```
The user is in "height" mode
   ↓
① Click the [Partial Refinement] button (newly added)
   ↓
② Mouse becomes lasso cursor→ Hold down the left button to draw a closed circle
   ↓
③ Release mouse→ The [Refinement Parameters] dialog box pops up:
     ┌─────────────────────────────────┐
     │  Finishing strength:  [▓▓▓▓▓░░░░░] 50%    │
     │                                 │
     │  ☑ add ridge(Make the mountain steeper)            │
     │  ☑ Add erosion(add ravine)              │
     │  ☐ add noise(rock texture)            │
     │                                 │
     │  seeds: [42]  [🎲 random]           │
     │                                 │
     │  ☑ Live preview│
     │                                 │
     │        [Cancel]  [OK]           │
     └─────────────────────────────────┘
   ↓
④ Drag slider/Turn off the switch→ Canvas real-time refresh preview
   ↓
⑤ OK→ writeheightmap（enterundo stack)
   Cancel→ Restore original height
```

**Border Case**:
- The lasso circle is too small (< 20×20 pixels) → the pop-up prompt "Selection is too small"
- Circle the entire ocean area → do nothing (the algorithm only works on land)
- User presses ESC → exit refinement mode

---

## 4. Architecture

### Add new file

| Documentation | Responsibilities |
|---|---|
| `domain/tools/lasso_selection.py` | Universal lasso selection tool (outputs bool mask) |
| `commands/map/refine_height_region.py` | Partial refinement Command (supports undo) |
| `features/map/height/refine_dialog.py` | Refinement parameters dialog box (including real-time preview) |

### Modify files

| Documentation | Changes |
|---|---|
| `services/terrain_service.py` | New `refine_heightmap_region(height, mask, strength, enable_ridge, enable_erosion, enable_noise, seed) -> np.ndarray` |
| `features/map/height/page.py` | Add [Partial Refinement] button+ Start refinement mode+ receive constituency→ Open dialog box|
| `domain/tools/registry.py` | Register new `lasso_selection` tool |
| `ui/i18n/en/height.py` | Add the new English keys |

### Data flow

```
┌─ [local refinement] button──→ activatelasso_selection Tools
│                           │
│                           ↓
│                      The user draws a circle (outputmask : bool[H,W]）
│                           │
│                           ↓
│                      RefineDialog(mask, map_data)
│                           │     ↑
│                           │     └─── Slider/switch change
│                           ↓
│                      real time callrefine_heightmap_region(...)
│                      updatepreview_height_map（temporary array)
│                           │
│                           ↓（User click OK)
│                      RefineHeightRegionCommand.execute()
│                      → map_data.height_map = new_height
│                      → CommandBus.push(undo)
│                      → EventBus.emit("height_changed")
```

---

## 5. Algorithm details: `refine_heightmap_region`

**enter**:
- `height: np.ndarray (H,W) uint8` — original height map
- `mask: np.ndarray (H,W) bool` — finishing area
- `strength: float ∈ [0, 1]` — Refined strength
- `enable_ridge, enable_erosion, enable_noise: bool` — three switches
- `seed: int` — Random seed (controls random pattern of erosion/noise)
- `tile_map: np.ndarray (H,W) uint8` — Used to distinguish land/sea/lake (non-land is not processed)

**Output**: `np.ndarray (H,W) uint8` — New height map (the entire image, the non-selected part is the same as the input)

**Process** (only processed on `mask & (tile_map == LAND)`, other pixels will be returned as they are):

```
1. Boundary feathering weight map
   w = distance_transform_edt(mask)              # Distance from each pixel to the border
   w = clip(w / 20.0, 0, 1)                       # 0..20 linear gradient,>20 full weight
   w *= strength                                  # Multiply the intensity slider

2. Ridge sharpening (optional)
   if enable_ridge:
       # useLaplacian Find local maximum values (ridge features)
       from scipy.ndimage import maximum_filter
       local_max = maximum_filter(height, size=5)
       ridge_mask = (height == local_max) & (height > SEA_LEVEL + 20)
       # Lift the ridge pixel and its neighborhood15 Pixel
       ridge_boost = gaussian_filter(ridge_mask.astype(f32) * 15.0, sigma=2)
       height_work += ridge_boost * w

3. Erosion gully (optional)
   if enable_erosion:
       # Simplify hydraulic erosion: simulate water flow from each high point along the steepest slope30 Step, lower the path
       # Reusescipy gradient+ Random starting point (usingseed）
       erosion = _simulate_erosion(height_work, seed, iterations=30)
       height_work -= erosion * w * 10.0

4. Highly correlated noise (optional)
   if enable_noise:
       # Add more noise high (rocky texture), less low (plain)
       rng = np.random.default_rng(seed)
       noise = rng.standard_normal(height.shape) * 4.0
       noise = gaussian_filter(noise, sigma=1.5)   # Slightly smooth
       height_factor = clip((height - SEA_LEVEL) / 100, 0, 1)
       height_work += noise * height_factor * w

5. Synthetic output
   result = height.copy()
   result[mask & land] = clip(height_work[mask & land], SEA_LEVEL + 1, 255)
   return result.astype(uint8)
```

**Key Design**:
- `w` is the feathering weight, 0→1 transition 20 pixels at the border, **guaranteed no hard edges**
- All processing is **addition and subtraction**, and the height is not recalculated; when `strength=0` is `w=0`, the original image is completely unchanged
- `height[!mask]` will never be modified
- Retain HOI4 sea and land constraints: land ≥ SEA_LEVEL+1, the land will not be cut below sea level

**`_simulate_erosion` simplified algorithm** (no fluid simulation, use ridge to reverse):
```
for random starting pointP (Quantity= Number of pixels in the selection× 0.005):
    for step in range(30):
        inP of3x3 Find the lowest point in the neighborhoodN
        erosion[N] += 0.3
        erosion[P] += 0.1
        P = N  # water flows toN
        if P It's the seaor erosion Reached the upper limit: break
return erosion  # will be in the3 step multiplied byw * 10
```

---

## 6. Command details

```python
# commands/map/refine_height_region.py
class RefineHeightRegionCommand(Command):
    label = "local finishing height"

    def __init__(self, map_data, mask, refine_params):
        self._map_data = map_data
        self._mask = mask.copy()
        self._params = refine_params  # dict: strength, ridge, erosion, noise, seed
        self._old_heights: np.ndarray | None = None

    def execute(self):
        # Save the original height within the selection
        self._old_heights = self._map_data.height_map[self._mask].copy()
        # Run the algorithm
        new_map = refine_heightmap_region(
            height=self._map_data.height_map,
            mask=self._mask,
            tile_map=self._map_data.tile_map,
            **self._params,
        )
        self._map_data.height_map[:] = new_map

    def undo(self):
        if self._old_heights is not None:
            self._map_data.height_map[self._mask] = self._old_heights
```

---

## 7. Dialog behavior

**Real-time preview implementation key points**:
- When opening the dialog **snapshot** current `height_map` → `self._original_height = height_map.copy()`
- Every time the parameters change (slider/switch), map_data is not changed and is only calculated once refine → update the display buffer of the renderer
- Click "Cancel" → Rendering returns to original
- Click "OK" → use the calculated new_height as a parameter to create a Command and push undo stack

**performance**:
- The selection is generally 200×200 ~ 800×800 pixels, and the algorithm takes 50-200ms each time.
- Use `QTimer.singleShot(100)` debounce for real-time preview to avoid crazy calculations when dragging the slider

---

## 8. Add the new keys to `ui/i18n/en/height.py`

```python
# height.py New
"height_btn_refine": "local refinement" / "Local Refine"
"height_btn_refine_tip": "Select an area and add ridges based on the height you drew./erosion/noise" /
                         "Select an area; enhance your painted heights with ridges/erosion/noise"
"refine_dlg_title": "local finishing height" / "Refine Height Locally"
"refine_dlg_strength": "Finishing strength" / "Refine Strength"
"refine_dlg_ridge": "add ridge(Make the mountain steeper)" / "Add Ridges (Sharpen peaks)"
"refine_dlg_erosion": "Add erosion(add ravine)" / "Add Erosion (Carve valleys)"
"refine_dlg_noise": "add noise(rock texture)" / "Add Noise (Rocky texture)"
"refine_dlg_seed": "seeds" / "Seed"
"refine_dlg_randomize": "random" / "Randomize"
"refine_dlg_preview": "Live preview" / "Live Preview"
"refine_dlg_area_too_small": "The selection is too small (needs at least20×20 pixels)" /
                              "Selection too small (need at least 20x20 pixels)"
"status_refine_mode": "Local refinement mode: draw a circle to enclose the area to be refined" /
                      "Refine mode: draw a loop to select the area"
"status_refine_done": "Partial refinement completed" / "Local refine applied"
```

---

## 9. Test

**Unit Test** `tests/services/test_terrain_refine.py`:
1. `strength=0` → output === input (pixel by pixel)
2. There is no land in `mask` → Output === Input
3. All switches are off → Output === Input
4. Only open ridge, the original image has obvious mountains → the pixel height of mountain ranges increases, while non-mountain ranges remain unchanged
5. Only erosion is enabled, the original image is plain → the height of some pixels decreases.
6. The height of `mask` 20 pixels outside the boundary is **completely unchanged**
7. After finishing the run, the height of the land is still ≥ `SEA_LEVEL + 1` (it will not turn the land into the sea)

**Manual Test**:
1. Draw a "pie mountain" (a disk of uniform height) → refine 100% to open the ridge → see the ridge emerging
2. After refinement, press Ctrl+Z → restore to original state
3. The selection is drawn on the sea → click to make sure it does not collapse
4. Drag the slider in real-time preview → the canvas changes accordingly, and stabilizes at the final value after letting go

---

## 10. Risks and rollbacks

**Potential Risks**:
- Improper preview implementation may cause canvas refresh jitter → Use QTimer debounce 100ms
- The erosion algorithm may be slow in very large selections (>2000×2000) → The first version limits the selection area to ≤ 500000 pixels, prompting the user if exceeded
- Feather width 20 pixels has poor effect in very small selections (<40×40) → automatically shrink to `min(20, min(selection size)/3)`

**rollback**:
- This function is an **added function** and has no conflict with existing code. Turning it off does not affect anything else
- If you find that the algorithm output is abnormal, just `git revert <commit>`
- Existing tools such as SetHeightCommand/SmoothHeight are not affected

---

## 11. Implementation sequence (for writing-plans stage)

1. **Algorithm first**: Write `refine_heightmap_region` + single test first (you can use matplotlib to manually verify the effect with the naked eye first)
2. **Command access**: Connect to `RefineHeightRegionCommand`
3. **Lasso Tool**: `LassoSelectionTool` → Output bool mask
4. **UI access**: page button + RefineDialog (without real-time preview first)
5. **Real-time preview**: add preview snapshot + QTimer debounce
6. **i18n**: Complete translation
7. **Run it manually**: Draw a pie mountain to verify the effect
8. **Single test completion**: Boundary conditions

---

## 12. Things not to do (YAGNI)

- No complete hydraulic erosion fluid simulation (only a simplified version, the performance and effect are sufficient)
- No 3D visualization preview (2D height ribbon is enough for judgment)
- Multi-selection merge and refinement is not supported (only one circle is processed at a time)
- Does not support saving "frequently used presets" (will be added after the user requests it)
- Record each intermediate preview without undo (only undo the final result)
