# Architecture reconstruction design document

**Date**: 2026-04-12
**Option**: B — Based on existing Project + EventBus + new ApplicationController

## Project goals

This is a map making tool released for the HOI4 MOD community. Users’ core demands:
1. **Stable** — Released for community use, no crashes or lags
2. **Clear structure** — Each function is placed in its place, and only the corresponding file is changed when changing a certain function.
3. **Clear calling relationship** — There is linkage between functions, but the calling chain must be clear and do not cause bugs due to random strings.

Refactoring is not for "looking good", but because the current chaos directly leads to constant bugs.

## Problem background

After v0.20 reconstruction, the architecture still has serious coupling problems:
1. main_window is God Object (1758 lines across 3 files), containing a lot of business logic
2. Feature pages are falsely decoupled through `panel._xxx` private access at 307
3. The Canvas widget is both a View and a Model (all data is hung on it)
4. After the province is regenerated, the downstream data (State/Country/Continent/Strategic Region) will not be automatically cleared.
5. Two undo systems coexist (UndoManager + CommandHistory), neither split_selected() is used

## Design goals

- main_window < 400 lines, only UI assembly and signal routing
- Feature pages do not access any `panel._xxx` private properties
- Data cascade failure automation (province change → State clear → Country clear)
- Unified use of CommandHistory for undoing

## Architecture Overview

```
user events
  ↓
MainWindow (thin shell: menu+ signal routing)
  ↓
ApplicationController (Scheduling: Mode switching/ Province information/ color refresh/ Cancel)
  ↓
Feature Controllers (state / land / province / ...)
  ↓ (PassCommand)
CommandHistory → Project.map_data / Project.*_mgr
  ↓ (PassEventBus)
Cascading failure chain: province_regen → state_clear → country_clear → UI Refresh
  ↓
Canvas (read-only data+ rendering) + ToolPanel (pure container+ Page switching)
```

---

## Phase 1: Fix bug + extract ApplicationController

### 1.1 Bug fix

**split_selected() undo bug**
- File: `controllers/province.py` lines 72-103
- Problem: Directly changing the province_map array, no Command is created
- Fix: Create `commands/province/split.py` → `SplitProvinceCommand`

**The list will not be refreshed after provinces are regenerated**
- File: `views/main_window_actions.py` lines 110-113
- Problem: `_on_generate_done()` only updated province_map, but did not refresh the State/Country list
- Fix: Stage 2 cascading events will be handled automatically

### 1.2 Create a new ApplicationController

**New file**: `controllers/app_controller.py` (~400 lines)

Logic moved out from main_window.py:

| method | original position | function |
|------|--------|------|
| `calculate_province_info(pid)` | main_window.py:517-585 | Province information calculation + cache |
| `refresh_state_colors()` | main_window.py:713-718 | Build state color map |
| `refresh_country_colors()` | main_window.py:731-737 | Build country color map |
| `refresh_vp_data()` | main_window.py:720-726 | Collect VP data |
| `refresh_state_list()` | main_window.py:709-711 | Refresh state list |
| `refresh_country_list()` | main_window.py:728-729 | Refresh country list |
| `on_mode_changed(mode)` | main_window.py:481-498 | Mode switching side effects |
| `on_stroke_started/ended()` | main_window.py:623-676 | Undo management |

**MainWindow reserved**:
- `_init_ui()` — menu bar, toolbar, layout
- `_connect_signals()` — Signal → AppController routing
- `_show_welcome()` / `_show_editor()` — Page switching
- Shortcut key registration

**Key interface**:
```python
class ApplicationController:
    def __init__(self, project, canvas, tool_panel, command_history, event_bus):
        ...
    
    def on_mode_changed(self, mode: str) -> None: ...
    def on_province_clicked(self, pid: int) -> None: ...
    def undo(self) -> None: ...
    def redo(self) -> None: ...
```

### Involved files
- New: `controllers/app_controller.py`
- New: `commands/province/split.py`
- Modification: `views/main_window.py` (delete method of moving)
- Modified: `controllers/province.py` (split_selected using Command)

---

## Phase 2: Cascading Failure Mechanism

### 2.1 Event definition

Add new events on EventBus (no new files required, existing event_bus will be used):

| Event name | Trigger timing | Carrying data |
|--------|----------|----------|
| `province_map_regenerated` | After fully regenerating provinces | `{incremental: bool}` |
| `province_map_incremental` | After incrementally generating provinces | `{new_ids: list[int]}` |

### 2.2 Cascading subscription chain

```
province_map_regenerated
  → StateController.on_province_regen()     # clear all states
  → CountryController.on_province_regen()   # clear all countries  
  → ContinentController.on_province_regen() # clear continent assignments
  → StrategicRegionController.on_province_regen() # clear regions
  → AppController.on_province_regen()       # RefreshUI list+ color map
```

### 2.3 Subscription timing

Key change: Cascading subscriptions are registered when **Controller is constructed**, not when activate().
Because province regeneration can happen in any mode, not just State mode.

```python
class StateController(BaseController):
    def __init__(self, project, command_history):
        super().__init__(project, command_history)
        # Always listen, no matter what the current mode is
        self.event_bus.subscribe("province_map_regenerated", self._on_province_regen)
    
    def _on_province_regen(self, event):
        if not event.data.get("incremental"):
            self.project.state_mgr.clear()
            self.event_bus.emit("state_changed", state_id=0, action="refresh")
```

### 2.4 Trigger point

Modify `_on_generate_done()` of `views/main_window_actions.py`:
```python
def _on_generate_done(self, province_map, count):
    was_incremental = self._gen_thread._incremental
    self._canvas.province_map = province_map
    self._update_province_count()
    # Send an event and let the cascade process it automatically
    self.event_bus.emit("province_map_regenerated", incremental=was_incremental)
    self._status_info.setText(f"Province generation completed: {count} a")
```

### Involved files
- Modification: `controllers/state.py` (add _on_province_regen)
- Modification: `controllers/country.py` (add _on_province_regen)
- Modification: `controllers/continent.py` (add _on_province_regen)
- Modification: `controllers/strategic_region.py` (add _on_province_regen)
- Modification: `controllers/app_controller.py` (add UI refresh response)
- Modification: `views/main_window_actions.py` (change _on_generate_done)

---

## Stage 3: Feature page is truly decoupled

### 3.1 Goals

Each page.py becomes an independent QWidget subclass:
- Hold the control yourself (`self._brush_slider` instead of `panel._brush_slider`)
- Expose public signals and methods
- No need to know about the existence of ToolPanel

### 3.2 Mode: Take LandPage as an example

**Before** (`features/map/land/page.py`):
```python
def build_page(panel) -> QWidget:
    page = QWidget()
    panel._tool_group = QButtonGroup()
    panel._brush_slider = QSlider(...)
    panel._brush_slider.valueChanged.connect(panel._on_brush_size)
    ...
    return page
```

**After** (`features/map/land/page.py`):
```python
class LandPage(QWidget):
    # public signal
    tool_changed = pyqtSignal(str)
    brush_size_changed = pyqtSignal(int)
    tile_type_changed = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tool_group = QButtonGroup()
        self._brush_slider = QSlider(...)
        self._brush_slider.valueChanged.connect(self.brush_size_changed)
        self._build_ui()
    
    def _build_ui(self):
        # allUI Build here
        ...
```

### 3.3 ToolPanel changes

**Before** (line 568, holding controls for all pages):
```python
class ToolPanel(QWidget):
    def __init__(self):
        self._brush_slider = ...  # Beland/page.py Inject
        self._state_list = ...    # Bestate/page.py Inject
        ...
```

**After** (~200 lines, pure container):
```python
class ToolPanel(QWidget):
    mode_changed = pyqtSignal(str)
    
    def __init__(self):
        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
    
    def add_page(self, mode_id: str, page: QWidget) -> None:
        self._pages[mode_id] = page
        self._stack.addWidget(page)
    
    def get_page(self, mode_id: str) -> QWidget:
        return self._pages[mode_id]
```

### 3.4 Conversion sequence (from easy to difficult)

1. land/page.py (visited by 71 `panel._`, the simplest brush UI)
2. height/page.py
3. terrain/page.py
4. province/page.py
5. state/page.py (with list interaction, slightly complicated)
6. country/page.py
7. river/page.py
8. continent/page.py
9. logistics/page.py
10. strategic_region/page.py
11. colormap/page.py, default_map/page.py

### Involved files
- Modified: all `features/map/*/page.py` (11 files)
- Modification: `ui/tool_panel.py` (reduced from 568 lines to ~200 lines)
- Modification: `views/main_window.py` (change in connection method)
- Modification: `controllers/app_controller.py` (connect page signal)

---

## Phase 4: Unified Undo System

### 4.1 Current situation

- **UndoManager** (`domain/undo_manager.py`): Snapshot, zlib compresses the entire array, main_window is called before and after the brush stroke
- **CommandHistory** (`commands/history.py`): Command mode, each operation is reversible Command, used by controllers
- **split_selected()**: Do not use either, just change the array directly

### 4.2 Unified solution

New `commands/land/brush_stroke.py`:
```python
class BrushStrokeCommand(Command):
    """brush oncestroke all pixel changes."""
    def __init__(self, map_data, layer: str, changes: dict[tuple, tuple]):
        # changes: {(y,x): (old_val, new_val)}
        ...
    def execute(self): ...
    def undo(self): ...
```

- AppController starts collecting changes when stroke_started
- Create BrushStrokeCommand when stroke_ended and push to CommandHistory
- Delete UndoManager

### 4.3 Risks

A brush stroke may involve tens of thousands of pixels, and storing them all in dict is expensive in memory.
**Mitigation**: Only save bbox snapshots of changed areas (numpy slice copy) instead of pixel-by-pixel dict.

### Involved files
- New: `commands/land/brush_stroke.py`
- Delete: `domain/undo_manager.py`
- Modification: `controllers/app_controller.py` (stroke management)
- Modification: `controllers/land.py` (stroke collection)

---

## Verification scheme

After each stage is completed:

1. **Run the program**: `python main.py`, load the archive `2.hoi4proj`
2. **Basic Function Test**:
- Land mode: Brush/Eraser/Fill/Undo
- Province mode: generate provinces (full + incremental), merge/cut
- State mode: automatically group, select State, set VP
- Country mode: Create a country and allocate territory
- Export tests
3. **Cascade Test** (After Phase 2):
- Load the old save → Regenerate the provinces → Confirm that the State/Country list has been cleared
- Switch to State mode → No lagging
4. **Withdraw Test** (After Stage 4):
- Draw a few strokes with the brush → Ctrl+Z Undo → Confirm recovery
- Cut Province → Ctrl+Z → Confirm Restore
5. **Run pytest**: `pytest tests/`

## File list

### Create new file
| File | Purpose | Estimated number of rows |
|------|------|----------|
| `controllers/app_controller.py` | Application Scheduler | ~400 |
| `commands/province/split.py` | Cut Province Command | ~60 |
| `commands/land/brush_stroke.py` | Brush Command | ~80 |

### Mainly modify files
| Documentation | Changes |
|------|------|
| `views/main_window.py` | 836 → ~400 lines, delete business logic |
| `ui/tool_panel.py` | 568 → ~200 lines, pure container |
| `features/map/*/page.py` × 11 | `build_page(panel)` → Independent QWidget class |
| `controllers/state.py` | Add cascade subscription |
| `controllers/country.py` | Add cascade subscription |
| `controllers/province.py` | split Use Command instead |
| `views/main_window_actions.py` | Send province_regen event |

### Delete files
| File | Reason |
|------|------|
| `domain/undo_manager.py` | Replaced by CommandHistory |
