# Improve the terrain system Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supports all vanilla graphical terrain variants (22 types). When changing the terrain, the height is linked. Ocean/lake provinces cannot change the terrain. The definition.csv is written to the correct provincial terrain.

**Architecture:** Extends `data/terrain_types.py` to add the `GRAPHICAL_TERRAINS` full table (map from the `terrain = {}` block of vanilla `00_terrain.txt`), the UI displays all variants grouped by provincial terrain type, terrain_map + height_map is updated synchronously when canvas is clicked, and definition.csv checks provincial terrain type from terrain_map when exporting.

**Tech Stack:** Python 3.10+, PyQt5, NumPy

---

## File Structure

| Documentation | Responsibilities | Changes |
|------|------|------|
| `data/terrain_types.py` | Terrain data definition| New`GraphicalTerrain` + `GRAPHICAL_TERRAINS` Full table+ `PALETTE_TO_TYPE` Lookup table|
| `features/map/terrain/page.py` | Terrain Editor UI | Override: Show all variant buttons grouped by type |
| `ui/canvas_widget.py` | Canvas interaction| Terrain click plus ocean protection+ linkage height;LUT Expand to all indexes|
| `export/csv_writer.py` | definition.csv export | `_default_terrain()` Change to check the actual type from terrain_map |
| `services/terrain_service.py` | Automatically generate service | No changes |
| `export/bmp_writer.py` | terrain.bmp export | No changes (written directly by palette index) |

---

### Task 1: Extend terrain data definition

**Files:**
- Modify: `data/terrain_types.py`

- [ ] **Step 1: Add `GraphicalTerrain` and the full table at the end of `data/terrain_types.py`**

```python
class GraphicalTerrain(NamedTuple):
    """terrain.bmp ofgraphical terrain entry(from00_terrain.txt terrain={} block)"""
    id: str                # Original entry name: "terrain_0", "desert_mountain" Wait
    type: str              # provincial terrain Type: plains/forest/mountain Wait
    palette_index: int     # terrain.bmp palette index
    texture: int           # atlas0.dds Texture number(0-15)
    name_en: str           # English display name
    perm_snow: bool        # forever covered in snow
    spawn_city: bool       # Automatically generate city models


# Original00_terrain.txt terrain={} block all entries
# Each item corresponds toterrain.bmp a palette index→ an in-game appearance
GRAPHICAL_TERRAINS: list[GraphicalTerrain] = [
    GraphicalTerrain("terrain_0",             "plains",   0,  1,  "plain",           False, False),
    GraphicalTerrain("terrain_1",             "forest",   1,  4,  "forest",           False, False),
    GraphicalTerrain("desert_mountain",       "hills",    2,  3,  "desert hills",       False, False),
    GraphicalTerrain("desert",                "desert",   3,  9,  "desert",           False, False),
    GraphicalTerrain("terrain_4",             "forest",   4,  5,  "forest(Variants)",     False, False),
    GraphicalTerrain("terrain_5",             "plains",   5,  0,  "plain(Variants)",     False, False),
    GraphicalTerrain("terrain_6",             "mountain", 6,  11, "Mountain",           False, False),
    GraphicalTerrain("terrain_7",             "desert",   7,  12, "desert(Variants)",     False, False),
    GraphicalTerrain("desert_hills",          "desert",   8,  14, "desert hills",       False, False),
    GraphicalTerrain("terrain_9",             "marsh",    9,  6,  "swamp",           False, False),
    GraphicalTerrain("terrain_10",            "mountain", 10, 13, "Mountain(Variants)",     False, False),
    GraphicalTerrain("desert_mountain_11",    "mountain", 11, 11, "desert mountains",       False, False),
    GraphicalTerrain("desert_12",             "desert",   12, 8,  "desert(rocky ground)",     False, False),
    GraphicalTerrain("forest_13",             "urban",    13, 10, "city",           False, True),
    GraphicalTerrain("forest_14",             "lakes",    14, 255, "lake",          False, False),
    GraphicalTerrain("ocean_15",              "ocean",    15, 9,  "ocean",           False, False),
    GraphicalTerrain("snow_16",               "mountain", 16, 11, "snow mountain",           True,  False),
    GraphicalTerrain("hills_blend",           "hills",    17, 2,  "hills",           False, False),
    GraphicalTerrain("mountain_variation_sand","mountain", 18, 7,  "sandy mountains",      False, False),
    GraphicalTerrain("plains_snow",           "plains",   19, 0,  "snowfield",           True,  False),
    GraphicalTerrain("mountain_variation_grass","mountain",20, 7,  "grassy mountains",      False, False),
    GraphicalTerrain("jungle_18",             "jungle",   21, 4,  "jungle",           False, False),
    GraphicalTerrain("jungle_blend_18",       "jungle",   22, 5,  "jungle(Variants)",     False, False),
    GraphicalTerrain("jungle_mountain",       "mountain", 27, 7,  "jungle mountains",       False, False),
    GraphicalTerrain("desert_mountain_tops",  "mountain", 31, 15, "desert mountaintop",       False, False),
]

# palette index→ GraphicalTerrain Quick search
GRAPHICAL_TERRAIN_BY_INDEX: dict[int, GraphicalTerrain] = {
    gt.palette_index: gt for gt in GRAPHICAL_TERRAINS
}

# palette index→ provincial terrain type Name(used fordefinition.csv)
PALETTE_TO_TYPE: dict[int, str] = {
    gt.palette_index: gt.type for gt in GRAPHICAL_TERRAINS
}

# pressprovincial terrain type Grouped drawable variants(excludeocean/lakes)
PAINTABLE_GROUPS: dict[str, list[GraphicalTerrain]] = {}
for _gt in GRAPHICAL_TERRAINS:
    if _gt.type not in ("ocean", "lakes"):
        PAINTABLE_GROUPS.setdefault(_gt.type, []).append(_gt)
```

- [ ] **Step 2: Verify that the data has no duplicate indexes**

Run the Python interactive check:
```bash
cd C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker && python -c "
from data.terrain_types import GRAPHICAL_TERRAINS
indices = [gt.palette_index for gt in GRAPHICAL_TERRAINS]
assert len(indices) == len(set(indices)), f'Duplicate index: {[i for i in indices if indices.count(i) > 1]}'
print(f'OK: {len(GRAPHICAL_TERRAINS)} speciesgraphical terrain, No duplication in index')
"
```
Expected: `OK: 25 speciesgraphical terrain, No duplication in index`

- [ ] **Step 3: Commit**

```bash
git add data/terrain_types.py
git commit -m "feat: Expandgraphical terrain Full table(25 speciesvanilla Variants)"
```

---

### Task 2: Extend canvas color LUT

**Files:**
- Modify: `ui/canvas_widget.py:37-46`

- [ ] **Step 1: Replace LUT build code**

Change the LUT build of `canvas_widget.py` lines 37-46 from the old `TERRAIN_PALETTE_INDEX` to the new `GRAPHICAL_TERRAINS`:

```python
# buildterrain Index→ BGRA color lookup table(Cover allgraphical terrain)
from data.terrain_types import GRAPHICAL_TERRAINS, TERRAIN_TYPES

# buildterrain colorLUT (numpyarray, 256 entries, BGRA)
_TERRAIN_COLOR_LUT = np.zeros((256, 4), dtype=np.uint8)
for _gt in GRAPHICAL_TERRAINS:
    # useprovincial terrain type color as base color
    _base = TERRAIN_TYPES[_gt.type].color  # (R, G, B)
    _r, _g, _b = _base
    # Variants differentiated with brightness tweaks(palette_index low offset of)
    _shift = ((_gt.palette_index * 7) % 30) - 15  # -15 ~ +14
    _r = max(0, min(255, _r + _shift))
    _g = max(0, min(255, _g + _shift))
    _b = max(0, min(255, _b + _shift))
    # Yongxue variant superimposed with blue and white tones
    if _gt.perm_snow:
        _r = min(255, _r + 40)
        _g = min(255, _g + 40)
        _b = min(255, _b + 60)
    _TERRAIN_COLOR_LUT[_gt.palette_index] = (_b, _g, _r, 255)
```

- [ ] **Step 2: Delete old import**

Remove the no longer needed `TERRAIN_PALETTE_INDEX` import (line 23) and replace it with:
```python
from data.terrain_types import TERRAIN_TYPES, GRAPHICAL_TERRAINS
```

- [ ] **Step 3: Verify that rendering does not crash**

```bash
cd C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker && python -c "
from ui.canvas_widget import _TERRAIN_COLOR_LUT
import numpy as np
assert _TERRAIN_COLOR_LUT.shape == (256, 4)
non_zero = np.any(_TERRAIN_COLOR_LUT != 0, axis=1).sum()
print(f'OK: LUT Yes{non_zero} non-zero entries')
"
```
Expected: `OK: LUT Yes25 non-zero entries`

- [ ] **Step 4: Commit**

```bash
git add ui/canvas_widget.py
git commit -m "feat: terrain LUT Expand to all25 speciesgraphical terrain"
```

---

### Task 3: Rewrite the terrain UI page

**Files:**
- Modify: `features/map/terrain/page.py`

- [ ] **Step 1: Rewrite `build_page()` — Show all variants grouped by type**

```python
"""terrain feature Page— pressprovincial terrain type Show all in groupsgraphical terrain Variants."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QScrollArea,
)

from data.terrain_types import (
    TERRAIN_TYPES, PAINTABLE_GROUPS, GRAPHICAL_TERRAINS,
)

from ui.styles import (
    _BG, _DIM, _SECTION_STYLE, _PRIMARY_BTN_STYLE,
)


# Group display order
_GROUP_ORDER = ["plains", "forest", "hills", "mountain", "desert", "marsh", "jungle", "urban"]

# Group display name
_GROUP_CN = {
    "plains": "plain", "forest": "forest", "hills": "hills", "mountain": "Mountain",
    "desert": "desert", "marsh": "swamp", "jungle": "jungle", "urban": "city",
}


def build_page(panel) -> QWidget:
    """buildterrain page. panel YesToolPanel Example."""
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(4)

    # Tips
    hint = QLabel("Select the terrain variant and click Province Allocation")
    hint.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 8px;")
    hint.setWordWrap(True)
    outer.addWidget(hint)

    # scrollable area
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea { border: none; }")
    scroll_content = QWidget()
    lay = QVBoxLayout(scroll_content)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)

    for group_type in _GROUP_ORDER:
        variants = PAINTABLE_GROUPS.get(group_type, [])
        if not variants:
            continue

        tt = TERRAIN_TYPES[group_type]
        group_name = _GROUP_CN.get(group_type, group_type)
        box = panel._make_section(f"{group_name} ({len(variants)})")
        grid = QGridLayout()
        grid.setSpacing(3)

        for i, gt in enumerate(variants):
            label = gt.name_en
            if gt.perm_snow:
                label += " *"
            btn = QPushButton(label)
            btn.setToolTip(
                f"Index: {gt.palette_index}  stickers: {gt.texture}\n"
                f"Type: {gt.type}  ID: {gt.id}"
            )

            r, g, b = tt.color
            # Variants fine-tune brightness to differentiate
            shift = ((gt.palette_index * 7) % 30) - 15
            r = max(0, min(255, r + shift))
            g = max(0, min(255, g + shift))
            b = max(0, min(255, b + shift))
            if gt.perm_snow:
                r = min(255, r + 40)
                g = min(255, g + 40)
                b = min(255, b + 60)

            brightness = r * 0.299 + g * 0.587 + b * 0.114
            fg = "#000000" if brightness > 140 else "#ffffff"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgb({r},{g},{b});
                    border: 2px solid transparent;
                    color: {fg};
                    padding: 4px 2px;
                    font-size: 10px;
                    font-weight: 600;
                    border-radius: 3px;
                    min-width: 50px;
                }}
                QPushButton:hover {{
                    border-color: white;
                }}
            """)
            btn.clicked.connect(
                lambda _, idx=gt.palette_index: panel.terrain_index_changed.emit(idx)
            )
            grid.addWidget(btn, i // 2, i % 2)

        box.layout().addLayout(grid)
        lay.addWidget(box)

    lay.addStretch()
    scroll.setWidget(scroll_content)
    outer.addWidget(scroll)

    # Automatically generated
    auto_btn = QPushButton("Automatically generated from land")
    auto_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
    auto_btn.clicked.connect(panel.auto_terrain_requested.emit)
    outer.addWidget(auto_btn)

    return page
```

- [ ] **Step 2: Start the tool to verify that the UI does not crash**

```bash
cd C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker && python main.py
```

Switch to terrain mode and confirm:
- 8 groups have titles
- Each group has a corresponding number of variant buttons (e.g. 7 in the mountain group)
- No error is reported in the status bar after clicking the button

- [ ] **Step 3: Commit**

```bash
git add features/map/terrain/page.py
git commit -m "feat: terrain UI Show all grouped by type25 speciesgraphical terrain Variants"
```

---

### Task 4: Marine protection + high degree of linkage

**Files:**
- Modify: `ui/canvas_widget.py:879-891`

- [ ] **Step 1: Modify terrain click processing - add ocean/lake protection + high degree of linkage**

Replace `canvas_widget.py` lines 886-891 with:

```python
                        # Terrain Mode: Click on Province→ The entire province fills the current terrain
                        if self._display_mode == "terrain":
                            # ocean/The terrain of lake provinces cannot be changed
                            tile_val = self._tile_map[sy, sx]
                            if tile_val in (TILE_SEA, TILE_LAKE):
                                event.accept()
                                return
                            self.stroke_started.emit()
                            self._terrain_map[mask] = self._current_terrain_index
                            # Linkage height: according tographical terrain oftype Checkheight_base
                            from data.terrain_types import PALETTE_TO_TYPE, TERRAIN_TYPES
                            ptype = PALETTE_TO_TYPE.get(self._current_terrain_index)
                            if ptype and ptype in TERRAIN_TYPES:
                                self._height_map[mask] = TERRAIN_TYPES[ptype].height_base
                            self._full_render()
                            self.stroke_ended.emit()
```

- [ ] **Step 2: Confirm that `TILE_SEA` and `TILE_LAKE` have been imported**

Check the import at the top of the file to make sure there is:
```python
from data.constants import (
    ..., TILE_SEA, TILE_LAKE, ...
)
```
(Existing, no need to change)

- [ ] **Step 3: Manual Test**

```bash
cd C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker && python main.py
```

Test steps:
1. Switch to terrain mode
2. Select the "Mountain" variant and click on a land province → it should turn into a mountain color
3. Switch to altitude mode to view → the altitude of the province should automatically become higher (220)
4. Switch back to terrain mode and click on a maritime province → there should be no response
5. Click on a lake province → There should be no response

- [ ] **Step 4: Commit**

```bash
git add ui/canvas_widget.py
git commit -m "feat: Terrain editing plus ocean protection+ Highly linked"
```

---

### Task 5: Write the correct provincial terrain to definition.csv

**Files:**
- Modify: `export/csv_writer.py:45-93` and `export/csv_writer.py:127-134`

- [ ] **Step 1: Modify `write_definition_csv` signature — receive terrain_map**

Add `terrain_map` parameters to the function signature:

```python
def write_definition_csv(
    province_map: np.ndarray,
    tile_map: np.ndarray,
    output_dir: str,
    colors: dict[int, tuple[int, int, int]] | None = None,
    continent_mgr=None,
    terrain_map: np.ndarray | None = None,
) -> None:
```

- [ ] **Step 2: Modify terrain field logic — check from terrain_map**

Change lines 82-83 of:
```python
            # Default terrain
            terrain = _default_terrain(ptype)
```
Replace with:
```python
            # Terrain: Prioritize fromterrain_map Check the actual situationgraphical terrain oftype
            terrain = _resolve_terrain(ptype, pid, province_map, terrain_map)
```

- [ ] **Step 3: Add `_resolve_terrain` function**

Below `_default_terrain` add:

```python
def _resolve_terrain(
    ptype: str,
    pid: int,
    province_map: np.ndarray,
    terrain_map: np.ndarray | None,
) -> str:
    """fromterrain_map Analyzing provincesprovincial terrain type."""
    # sea/lake force
    if ptype == "sea":
        return "ocean"
    if ptype == "lake":
        return "lakes"

    if terrain_map is None:
        return "plains"

    from data.terrain_types import PALETTE_TO_TYPE

    # Take within the province areaterrain_map mode(The index with the most)
    mask = province_map == pid
    indices = terrain_map[mask]
    if indices.size == 0:
        return "plains"

    counts = np.bincount(indices)
    dominant_index = int(counts.argmax())
    return PALETTE_TO_TYPE.get(dominant_index, "plains")
```

Make sure you have `import numpy as np` (already) at the top of the file.

- [ ] **Step 4: Find the location where mod_exporter calls `write_definition_csv` and pass in terrain_map**

Search for the place where `write_definition_csv` is called in mod_exporter.py, and add the `terrain_map=` parameter:

```bash
cd C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker && grep -n "write_definition_csv" export/mod_exporter.py
```

Add the `terrain_map=terrain_map` parameter at the call site.

- [ ] **Step 5: Verify export**

```bash
cd C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker && python -c "
# mock check_resolve_terrain logic
import numpy as np
from export.csv_writer import _resolve_terrain
pm = np.array([[1,1,2,2],[1,1,2,2]])
tm = np.array([[6,6,0,0],[6,6,0,0]])  # pid=1→Index6(mountain), pid=2→Index0(plains)
assert _resolve_terrain('land', 1, pm, tm) == 'mountain'
assert _resolve_terrain('land', 2, pm, tm) == 'plains'
assert _resolve_terrain('sea', 1, pm, tm) == 'ocean'
assert _resolve_terrain('lake', 1, pm, tm) == 'lakes'
print('OK: _resolve_terrain logically correct')
"
```
Expected: `OK: _resolve_terrain logically correct`

- [ ] **Step 6: Commit**

```bash
git add export/csv_writer.py export/mod_exporter.py
git commit -m "feat: definition.csv fromterrain_map Write the correctprovincial terrain"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Start tool complete process test**

```bash
cd C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker && python main.py
```

Operation steps:
1. Open an existing project or create a new one
2. Switch to terrain mode → Confirm that all 8 sets of variant buttons are displayed
3. Select "Snow Mountain" (index 16) → click on a land province → confirm the color change
4. Select "Jungle" (index 21) → click on another land province → confirm the color change
5. Click on the maritime province → confirm that there is no response
6. Switch to altitude mode → Confirm that the province height in step 3 is 220 (mountain) and that in step 4 is 125 (jungle)
7. Export MOD
8. Check `definition.csv` → The province terrain column in step 3 should be `mountain` and in step 4 it should be `jungle`
9. Check `terrain.bmp` to confirm the pixel value using hex editor

- [ ] **Step 2: Run existing tests to confirm there are no regressions**

```bash
cd C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker && pytest -v
```

Expected: All passed

- [ ] **Step 3: Final Commit**

```bash
git add -A
git commit -m "feat: Complete terrain system— fullvanilla graphical terrain + Highly linked+ marine protection"
```
