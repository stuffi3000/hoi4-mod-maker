# Reference base map UX revision implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rearrangement of the "① Basemap" card on the land page (import to top + open original reference button), symmetry control of the original/customized two reference maps (transparency/zoom/drag/overlay), new "Adjust reference map position" mode (disable all drawing during this period).

**Architecture:** `ref_images.py` is refactored into a general "reference layer" structure (RefLayer × 2, the old method name is retained as a thin wrapper); the canvas has a new adjustment mode state + orange dotted box, `input_router.py` top interception; `LandPage` cards are rearranged and new signals are forwarded to `ToolPanel` `MainWindow` wiring.

**Tech Stack:** Python 3.10+ / PyQt5 / pytest (Qt offscreen, mode copy `tests/views/test_render_registry.py`)

**Spec:** `docs/superpowers/specs/2026-07-05-ref-image-ux-design.md`

## Global Constraints

- Each file < 800 lines; English comments; type hints; snake_case method names.
- i18n: Keep all interface copy in the maintained English catalog.
- The old external interface must not be destroyed:`load_reference_image` / `load_vanilla_reference` / `set_vanilla_ref_opacity` / `toggle_vanilla_ref` / `set_ref_opacity` / `set_ref_scale` / `fit_ref_to_map` / `move_ref_image` / `toggle_ref_image`，andToolPanel existingproperty（`_vanilla_ref_opacity_slider` Wait6 ).
- working directory = git repository root: `C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker`.
- To run tests, use: `python -m pytest <path> -v` (Windows PowerShell).

---

### Task 1: Refactor ref_images.py into a dual-layer common structure

**Files:**
- Modify: `views/canvas/ref_images.py` (whole file rewritten)
- Modify: `views/canvas/widget.py:178-188` (layer initialization) + import at the top of the file
- Modify: `views/canvas/input_router.py:636-644` (read `_ref_scale` in Ctrl+wheel branch)
- Test: `tests/views/test_ref_images.py` (new)

**Interfaces:**
- Consumes: `MapCanvas` (combined with `RefImageMixin`), `self.map_w` / `self.map_h` / `self._show_ref_image`
- Produces (subsequent Task dependencies, signature fixed):
- `RefLayer` class: Properties `item: QGraphicsPixmapItem`, `original: QPixmap`, `scale: float`
- `self._ref_layers: dict[str, RefLayer]`, key `"custom"`/`"vanilla"`
  - `load_ref_layer(key: str, file_path: str, fit: bool = False) -> bool`
  - `set_ref_layer_opacity(key: str, opacity: float) -> None`
  - `set_ref_layer_scale(key: str, scale: float) -> None`
  - `move_ref_layer(key: str, dx: float, dy: float) -> None`
  - `fit_ref_layer(key: str) -> None`
  - `toggle_ref_layer(key: str, visible: bool) -> None`

- [ ] **Step 1: Write failing tests**

New `tests/views/test_ref_images.py`:

```python
"""Reference layer double image structure test— RefLayer + Common interface+ Old interface compatible."""

import pytest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPixmap, QColor


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def canvas(qapp):
    """withtests/views/test_render_registry.py Same size alignment routine."""
    import views.canvas.widget as widget_mod
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(widget_mod.MAP_WIDTH, widget_mod.MAP_HEIGHT)
    try:
        yield widget_mod.MapCanvas()
    finally:
        set_map_size(old_w, old_h)


def _make_png(tmp_path, w=64, h=32) -> str:
    px = QPixmap(w, h)
    px.fill(QColor(200, 100, 50))
    path = str(tmp_path / "ref.png")
    px.save(path, "PNG")
    return path


def test_load_custom_centers_at_original_size(canvas, tmp_path):
    path = _make_png(tmp_path, 64, 32)
    assert canvas.load_ref_layer("custom", path)
    layer = canvas._ref_layers["custom"]
    assert layer.scale == 1.0
    assert layer.item.pixmap().width() == 64
    # Centered by default
    assert layer.item.pos().x() == (canvas.map_w - 64) / 2
    assert layer.item.pos().y() == (canvas.map_h - 32) / 2


def test_load_vanilla_fit_fills_map(canvas, tmp_path):
    path = _make_png(tmp_path)
    assert canvas.load_ref_layer("vanilla", path, fit=True)
    layer = canvas._ref_layers["vanilla"]
    assert layer.item.pixmap().width() == canvas.map_w
    assert layer.item.pixmap().height() == canvas.map_h
    assert layer.item.pos().x() == 0


def test_scale_layers_independent(canvas, tmp_path):
    canvas.load_ref_layer("custom", _make_png(tmp_path, 64, 32))
    canvas.load_ref_layer("vanilla", _make_png(tmp_path, 64, 32))
    canvas.set_ref_layer_scale("custom", 2.0)
    assert canvas._ref_layers["custom"].scale == 2.0
    assert canvas._ref_layers["custom"].item.pixmap().width() == 128
    # vanilla not affected
    assert canvas._ref_layers["vanilla"].scale == 1.0


def test_move_and_fit_layer(canvas, tmp_path):
    canvas.load_ref_layer("vanilla", _make_png(tmp_path))
    canvas.move_ref_layer("vanilla", 10, -5)
    pos = canvas._ref_layers["vanilla"].item.pos()
    x0 = (canvas.map_w - 64) / 2
    y0 = (canvas.map_h - 32) / 2
    assert (pos.x(), pos.y()) == (x0 + 10, y0 - 5)
    canvas.fit_ref_layer("vanilla")
    assert canvas._ref_layers["vanilla"].item.pos().x() == 0


def test_legacy_wrappers_route_to_layers(canvas, tmp_path):
    path = _make_png(tmp_path)
    assert canvas.load_reference_image(path)          # → custom
    assert canvas.load_vanilla_reference(path)        # → vanilla + fit
    canvas.set_ref_scale(1.5)                         # → custom
    assert canvas._ref_layers["custom"].scale == 1.5
    canvas.set_vanilla_ref_opacity(0.7)
    assert canvas._ref_layers["vanilla"].item.opacity() == pytest.approx(0.7)
    canvas.toggle_ref_image(False)
    assert not canvas._ref_layers["custom"].item.isVisible()
    canvas.fit_ref_to_map()
    assert canvas._ref_layers["custom"].item.pixmap().width() == canvas.map_w
```

- [ ] **Step 2: Run test to confirm failure**

Run: `python -m pytest tests/views/test_ref_images.py -v`
Expected: FAIL — `AttributeError: 'MapCanvas' object has no attribute '_ref_layers'` (or `load_ref_layer` does not exist)

- [ ] **Step 3: Rewrite views/canvas/ref_images.py**

Replace the entire file with:

```python
"""
Reference drawing managementMixin — User reference map+ Original map reference layer
Two pictures share the same set"Reference layer"structure, independent: Load/Transparency/Zoom/move/Covered/Reveal and conceal.
Old method names remain as thin wrappers, main_window / input_router Existing calls are not affected.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem


class RefLayer:
    """Single reference layer: sceneitem + originalpixmap + The current zoom ratio."""

    def __init__(self, item: QGraphicsPixmapItem):
        self.item = item
        self.original = QPixmap()
        self.scale = 1.0


class RefImageMixin:
    """Reference diagram related methods. hypothesisself own:
    - _ref_layers: dict[str, RefLayer]  (key: REF_CUSTOM / REF_VANILLA)
    - map_w / map_h / _show_ref_image
    """

    REF_CUSTOM = "custom"
    REF_VANILLA = "vanilla"

    # ── Common layer interface──────────────────────────────────

    def load_ref_layer(self, key: str, file_path: str, fit: bool = False) -> bool:
        """Load a reference image.fit=True When the map is stretched directly."""
        layer = self._ref_layers[key]
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            return False
        layer.original = pixmap
        if fit:
            self.fit_ref_layer(key)
        else:
            layer.scale = 1.0
            layer.item.setPixmap(pixmap)
            # Centered by default
            layer.item.setPos(
                (self.map_w - pixmap.width()) / 2,
                (self.map_h - pixmap.height()) / 2,
            )
        layer.item.setVisible(True)
        return True

    def set_ref_layer_opacity(self, key: str, opacity: float) -> None:
        self._ref_layers[key].item.setOpacity(max(0.0, min(1.0, opacity)))

    def set_ref_layer_scale(self, key: str, scale: float) -> None:
        """Zoom reference image(1.0 = original size), with originalpixmap as a benchmark."""
        layer = self._ref_layers[key]
        scale = max(0.1, min(10.0, scale))
        layer.scale = scale
        if not layer.original.isNull():
            scaled = layer.original.scaled(
                int(layer.original.width() * scale),
                int(layer.original.height() * scale),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            layer.item.setPixmap(scaled)

    def move_ref_layer(self, key: str, dx: float, dy: float) -> None:
        item = self._ref_layers[key].item
        pos = item.pos()
        item.setPos(pos.x() + dx, pos.y() + dy)

    def fit_ref_layer(self, key: str) -> None:
        """Stretch to cover the entire map."""
        layer = self._ref_layers[key]
        if layer.original.isNull():
            return
        scaled = layer.original.scaled(
            self.map_w, self.map_h,
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        layer.item.setPixmap(scaled)
        layer.item.setPos(0, 0)
        layer.scale = self.map_w / layer.original.width()

    def toggle_ref_layer(self, key: str, visible: bool) -> None:
        self._ref_layers[key].item.setVisible(visible)

    # ── Compatible with old interfaces(main_window / input_router / old test) ──

    def load_reference_image(self, file_path: str) -> bool:
        ok = self.load_ref_layer(self.REF_CUSTOM, file_path)
        if ok:
            self._ref_layers[self.REF_CUSTOM].item.setVisible(self._show_ref_image)
        return ok

    def load_vanilla_reference(self, file_path: str) -> bool:
        """Load original map reference (independent of user reference map, Default is full)."""
        return self.load_ref_layer(self.REF_VANILLA, file_path, fit=True)

    def set_vanilla_ref_opacity(self, opacity: float) -> None:
        self.set_ref_layer_opacity(self.REF_VANILLA, opacity)

    def toggle_vanilla_ref(self, visible: bool) -> None:
        self.toggle_ref_layer(self.REF_VANILLA, visible)

    def set_ref_opacity(self, opacity: float) -> None:
        self.set_ref_layer_opacity(self.REF_CUSTOM, opacity)

    def set_ref_scale(self, scale: float) -> None:
        self.set_ref_layer_scale(self.REF_CUSTOM, scale)

    def fit_ref_to_map(self) -> None:
        self.fit_ref_layer(self.REF_CUSTOM)

    def move_ref_image(self, dx: int, dy: int) -> None:
        self.move_ref_layer(self.REF_CUSTOM, dx, dy)

    def toggle_ref_image(self, visible: bool) -> None:
        self._show_ref_image = visible
        self.toggle_ref_layer(self.REF_CUSTOM, visible)
```

- [ ] **Step 4: widget.py initialize _ref_layers**

`views/canvas/widget.py` Found reference layer initialization (about lines 178-188):

```python
        # Original map reference layer(Ground floor)
        self._vanilla_ref_item = QGraphicsPixmapItem()
        self._vanilla_ref_item.setOpacity(0.3)
        self._vanilla_ref_item.setZValue(1)
        self._scene.addItem(self._vanilla_ref_item)

        # User-defined reference layer(upper level)
        self._ref_pixmap_item = QGraphicsPixmapItem()
        self._ref_pixmap_item.setOpacity(0.4)
        self._ref_pixmap_item.setZValue(2)
        self._scene.addItem(self._ref_pixmap_item)
```

Append ** after this paragraph (the two old attribute names of `_vanilla_ref_item` / `_ref_pixmap_item` are retained):

```python
        # Unified reference layer registry(ref_images.py Common interface)
        self._ref_layers = {
            RefImageMixin.REF_VANILLA: RefLayer(self._vanilla_ref_item),
            RefImageMixin.REF_CUSTOM: RefLayer(self._ref_pixmap_item),
        }
```

Find `from views.canvas.ref_images import RefImageMixin` at the top of widget.py (at the mixin import of MapCanvas) and change it to:

```python
from views.canvas.ref_images import RefImageMixin, RefLayer
```

- [ ] **Step 5: input_router.py Ctrl+wheel to change the layer scale**

`views/canvas/input_router.py` wheelEvent (about lines 636-644), put:

```python
            new_scale = getattr(self, '_ref_scale', 1.0) + scale_step
```

Change to:

```python
            new_scale = self._ref_layers[self.REF_CUSTOM].scale + scale_step
```

(The old `_ref_scale` / `_ref_original_pixmap` properties have been replaced by RefLayer.scale / RefLayer.original, grep `_ref_scale\b` and `_ref_original_pixmap` to confirm that there are no other references except the slider name.)

- [ ] **Step 6: Run the test to confirm it passed**

Run: `python -m pytest tests/views/test_ref_images.py -v`
Expected: 5 passed

- [ ] **Step 7: Run full test to prevent regression**

Run: `python -m pytest -m "not slow" -q`
Expected: All passed (thin packaging of old interfaces ensures compatibility)

- [ ] **Step 8: Commit**

```powershell
git add views/canvas/ref_images.py views/canvas/widget.py views/canvas/input_router.py tests/views/test_ref_images.py
git commit -m "refactor: The reference image is reconstructed into a dual-layer common structure (original version/Custom symmetry control)"
```

---

### Task 2: Canvas adjustment mode (drag/zoom reference image + disable drawing)

**Files:**
- Modify: `views/canvas/ref_images.py` (additional adjustment mode method)
- Modify: `views/canvas/widget.py` (2 signals + status + orange dotted box item)
- Modify: `views/canvas/input_router.py` (mousePress / mouseMove / mouseRelease / wheel / keyPress five places)
- Test: `tests/views/test_ref_images.py` (additional)

**Interfaces:**
- Consumes: Task 1 of `_ref_layers` / `move_ref_layer` / `set_ref_layer_scale`
- Produces (Task 4 wiring dependency):
- `set_ref_adjust_mode(target: str | None) -> None` — `"custom"`/`"vanilla"` enter, `None` exit
- `self._ref_adjust_target: str | None` — Current adjustment object
- Signal `ref_adjust_exited = pyqtSignal()` — Emitted on ESC exit
- Signal `ref_adjust_scale_changed = pyqtSignal(str, float)` — Launch after wheel zoom (target, scale)

- [ ] **Step 1: Write failing tests**

`tests/views/test_ref_images.py` added:

```python
from PyQt5.QtCore import Qt, QEvent, QPointF, QPoint
from PyQt5.QtGui import QMouseEvent, QKeyEvent, QWheelEvent


def _left_press(x=50.0, y=50.0) -> QMouseEvent:
    return QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def test_adjust_mode_blocks_drawing(canvas, tmp_path):
    canvas.load_ref_layer("custom", _make_png(tmp_path))
    canvas.set_ref_adjust_mode("custom")
    canvas.mousePressEvent(_left_press())
    assert canvas._is_drawing is False          # Paintbrush is not starting
    assert canvas._ref_dragging is True         # Turn into drag reference image
    assert canvas._ref_adjust_border.isVisible()


def test_adjust_mode_off_restores_drawing(canvas, tmp_path):
    canvas.load_ref_layer("custom", _make_png(tmp_path))
    canvas.set_ref_adjust_mode("custom")
    canvas.set_ref_adjust_mode(None)
    assert not canvas._ref_adjust_border.isVisible()
    canvas.mousePressEvent(_left_press())
    assert canvas._is_drawing is True           # Brush recovery


def test_esc_exits_adjust_and_emits(canvas, tmp_path):
    canvas.load_ref_layer("vanilla", _make_png(tmp_path))
    canvas.set_ref_adjust_mode("vanilla")
    fired = []
    canvas.ref_adjust_exited.connect(lambda: fired.append(1))
    esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    canvas.keyPressEvent(esc)
    assert canvas._ref_adjust_target is None
    assert fired == [1]


def test_wheel_scales_adjust_target(canvas, tmp_path):
    canvas.load_ref_layer("vanilla", _make_png(tmp_path))
    canvas.set_ref_adjust_mode("vanilla")
    canvas.set_ref_layer_scale("vanilla", 1.0)
    got = []
    canvas.ref_adjust_scale_changed.connect(lambda t, s: got.append((t, s)))
    ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0),
                     QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    canvas.wheelEvent(ev)
    assert canvas._ref_layers["vanilla"].scale == pytest.approx(1.1)
    assert got == [("vanilla", pytest.approx(1.1))]
    # Custom graphics don't move
    assert canvas._ref_layers["custom"].scale == 1.0
```

- [ ] **Step 2: Run test to confirm failure**

Run: `python -m pytest tests/views/test_ref_images.py -v -k "adjust or esc or wheel_scales"`
Expected: FAIL — `AttributeError: set_ref_adjust_mode`

- [ ] **Step 3: widget.py add signal + status + dotted box**

Add the following to the widget.py MapCanvas signal definition area (next to the pyqtSignal declaration such as `zoom_changed`):

```python
    # Adjust reference image mode
    ref_adjust_exited = pyqtSignal()                    # ESC Exit (uncheck page button synchronization)
    ref_adjust_scale_changed = pyqtSignal(str, float)   # scroll wheel zoom(target, scale)
```

In `__init__`, add `_ref_layers` after initialization:

```python
        # Adjust reference image mode: None=close, "custom"/"vanilla"=Which one is being adjusted?
        self._ref_adjust_target: str | None = None
```

Scene item creation area (near `_selection_rect_item`) is added:

```python
        # Adjust the orange dotted frame of the reference image mode (marking the reference image being dragged)
        self._ref_adjust_border = QGraphicsRectItem()
        self._ref_adjust_border.setPen(QPen(QColor(249, 115, 22), 2, Qt.DashLine))
        self._ref_adjust_border.setBrush(QBrush(Qt.NoBrush))
        self._ref_adjust_border.setZValue(103)
        self._ref_adjust_border.setVisible(False)
        self._scene.addItem(self._ref_adjust_border)
```

- [ ] **Step 4: ref_images.py Add adjustment mode method**

Append `RefImageMixin` at the end, and add the same dashed line frame to the end of each of the three methods `move_ref_layer` / `set_ref_layer_scale` / `fit_ref_layer`:

```python
    # ── Adjust reference image mode────────────────────────────────

    def set_ref_adjust_mode(self, target: str | None) -> None:
        """enter/Exit the adjustment reference image mode.target=None Exit and resume drawing."""
        self._ref_adjust_target = target
        if target is None:
            self._ref_adjust_border.setVisible(False)
            self.setCursor(Qt.CrossCursor if self._current_tool != "pan"
                           else Qt.OpenHandCursor)
        else:
            self._update_ref_adjust_border()
            self._ref_adjust_border.setVisible(True)
            self.setCursor(Qt.SizeAllCursor)

    def _update_ref_adjust_border(self) -> None:
        """The dotted frame affixes the currently adjusted reference image."""
        if self._ref_adjust_target is None:
            return
        item = self._ref_layers[self._ref_adjust_target].item
        self._ref_adjust_border.setRect(item.sceneBoundingRect())
```

The following code appended at the end of the three methods (the same line, plus three places):

```python
        if getattr(self, '_ref_adjust_target', None) == key:
            self._update_ref_adjust_border()
```

- [ ] **Step 5: input_router.py five interceptions**

(a) `mousePressEvent` — Insert **after** the middle-click panning branch (about line 49-55) and **before** the box selection mode interception:

```python
        # Adjust reference image mode: left click= Drag reference image, All other drawing interactions are intercepted
        if (self._ref_adjust_target is not None
                and event.button() == Qt.MouseButton.LeftButton):
            if self._space_pressed:
                self._is_panning = True
                self._pan_start = event.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:
                self._ref_dragging = True
                self._ref_drag_start = event.pos()
            event.accept()
            return
```

(b) `mouseMoveEvent` - In the existing `_ref_dragging` branch (about lines 374-383), change `self.move_ref_image(scene_dx, scene_dy)` to be distributed by target:

```python
        # Drag and drop reference image(Ctrl+drag= Custom graph; Adjustment mode= Current adjustment object)
        if getattr(self, '_ref_dragging', False):
            delta = event.pos() - self._ref_drag_start
            self._ref_drag_start = event.pos()
            # Screen pixels to scene pixels (consider scaling)
            scene_dx = delta.x() / self._zoom
            scene_dy = delta.y() / self._zoom
            target = self._ref_adjust_target or self.REF_CUSTOM
            self.move_ref_layer(target, scene_dx, scene_dy)
            event.accept()
            return
```

(c) `mouseReleaseEvent` - Existing "end reference picture dragging" branch (about 501-506 lines), the cursor is restored according to the mode:

```python
        # End reference image dragging
        if getattr(self, '_ref_dragging', False):
            self._ref_dragging = False
            self.setCursor(Qt.CursorShape.SizeAllCursor
                           if self._ref_adjust_target is not None
                           else Qt.CursorShape.CrossCursor)
            event.accept()
            return
```

(d) `wheelEvent` — Method **Top** (before Ctrl+Scroller branch) inserts:

```python
        # Adjust reference image mode: roller= Zoom adjusted reference image
        if self._ref_adjust_target is not None:
            delta = event.angleDelta().y()
            step = 0.1 if delta > 0 else -0.1
            target = self._ref_adjust_target
            self.set_ref_layer_scale(target, self._ref_layers[target].scale + step)
            self.ref_adjust_scale_changed.emit(target, self._ref_layers[target].scale)
            event.accept()
            return
```

(e) `keyPressEvent` - Find the `elif event.key() == Qt.Key.Key_Escape:` branch (about 667 lines), insert these 5 lines into the **first line** of the branch (before `if self._transform_active:`), and the rest of the original code in the branch will remain unchanged:

```python
            # ESC Exit adjustment reference image mode
            if self._ref_adjust_target is not None:
                self.set_ref_adjust_mode(None)
                self.ref_adjust_exited.emit()
                return
```

- [ ] **Step 6: Run the test to confirm it passed**

Run: `python -m pytest tests/views/test_ref_images.py -v`
Expected: 9 passed

- [ ] **Step 7: Run full test to prevent regression**

Run: `python -m pytest -m "not slow" -q`
Expected: All passed

- [ ] **Step 8: Commit**

```powershell
git add views/canvas/ref_images.py views/canvas/widget.py views/canvas/input_router.py tests/views/test_ref_images.py
git commit -m "feat: Adjust the reference image mode (left click and drag/scroll wheel zoom, Disable drawing during, ESC exit)"
```

---

### Task 3: LandPage card rearrangement + new controls/signals + English copy

**Files:**
- Modify: `features/map/land/page.py:52-146` (rewrite the entire section of the "① Reference Underlay" card) + new signal + new method
- Modify: `ui/i18n/en/land.py` (add the new keys and update one existing value)
- Test: `tests/views/test_land_page_ref_card.py` (new)

**Interfaces:**
- Consumes: `ui.styles` of`_SECONDARY_BTN_STYLE` / `_SLIDER_STYLE` / `_LABEL_STYLE` / `_DIM_LABEL_STYLE` / `make_card` / `make_hint`（Ready-made)
- Produces (Task 4 dependency, fixed name):
- Signal `open_vanilla_requested = pyqtSignal()`
- Signal `ref_adjust_toggled = pyqtSignal(bool)`
- Signal `ref_adjust_target_changed = pyqtSignal(str)` (`"custom"` / `"vanilla"`, only sent when selected)
- Control `_vanilla_ref_scale_slider: QSlider` (10-500 initial value 100), `_vanilla_ref_fit_btn: QPushButton`
- Method `current_adjust_target() -> str`
- Method `set_ref_adjust_checked(on: bool) -> None`
- Method `set_ref_scale_percent(target: str, percent: int) -> None` (blockSignals anti-loopback)
  - The existing control names remain unchanged:`_vanilla_ref_opacity_slider` `_vanilla_ref_toggle` `_ref_opacity_slider` `_ref_toggle` `_ref_scale_slider` `_ref_scale_label` `_ref_fit_btn`

- [ ] **Step 1: Write failing tests**

New `tests/views/test_land_page_ref_card.py`:

```python
"""LandPage Reference base map card revision— New controls and new signals."""

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def page(qapp):
    from features.map.land.page import LandPage
    return LandPage()


def test_open_vanilla_signal(page):
    fired = []
    page.open_vanilla_requested.connect(lambda: fired.append(1))
    page._open_vanilla_btn.click()
    assert fired == [1]


def test_vanilla_has_scale_and_fit(page):
    assert page._vanilla_ref_scale_slider.minimum() == 10
    assert page._vanilla_ref_scale_slider.maximum() == 500
    assert page._vanilla_ref_scale_slider.value() == 100
    assert page._vanilla_ref_fit_btn is not None


def test_adjust_toggle_emits_and_enables_radios(page):
    got = []
    page.ref_adjust_toggled.connect(got.append)
    assert not page._adjust_custom_radio.isEnabled()   # Normally put into ashes
    page._ref_adjust_btn.setChecked(True)
    assert got == [True]
    assert page._adjust_custom_radio.isEnabled()
    page._ref_adjust_btn.setChecked(False)
    assert got == [True, False]
    assert not page._adjust_custom_radio.isEnabled()


def test_adjust_target_radio_emits_only_selected(page):
    page._ref_adjust_btn.setChecked(True)
    got = []
    page.ref_adjust_target_changed.connect(got.append)
    page._adjust_vanilla_radio.setChecked(True)
    assert got == ["vanilla"]                          # custom oftoggled(False) Not sent
    assert page.current_adjust_target() == "vanilla"


def test_set_ref_scale_percent_no_signal_loop(page):
    fired = []
    page._vanilla_ref_scale_slider.valueChanged.connect(fired.append)
    page.set_ref_scale_percent("vanilla", 150)
    assert page._vanilla_ref_scale_slider.value() == 150
    assert fired == []                                 # blockSignals Take effect
    assert page._vanilla_ref_scale_label.text() == "150%"


def test_set_ref_adjust_checked_syncs_button(page):
    page._ref_adjust_btn.setChecked(True)
    page.set_ref_adjust_checked(False)                 # Simulate canvasESC Exit
    assert not page._ref_adjust_btn.isChecked()
```

- [ ] **Step 2: Run test to confirm failure**

Run: `python -m pytest tests/views/test_land_page_ref_card.py -v`
Expected: FAIL — `AttributeError: _open_vanilla_btn`

- [ ] **Step 3: English copy**

In `ui/i18n/en/land.py`, update the existing value and add the new values near `land_btn_import_ref`:

```python
    "land_btn_import_ref": "Import reference image…",
    "land_btn_open_vanilla": "Open original reference",
    "land_btn_open_vanilla_tip": "Load the original map from the game directory with one click and trace it according to the original terrain.",
    "land_btn_fit": "Covered",
    "land_btn_ref_adjust": "🖐 Adjust the position of the reference image",
    "land_btn_ref_adjust_active": "🖐 Adjusting the reference image (click orESC exit)",
    "land_label_adjust_target": "Adjust object:",
    "land_adjust_custom": "Customize",
    "land_adjust_vanilla": "Original",
    "land_ref_adjust_hint": "In adjustment mode: left-click to move the reference image and scroll wheel to zoom; during this period, the drawing function is suspended. Also available in normal timesCtrl+Left click drag/ Ctrl+Scroll wheel to zoom custom graph.",
```

Run the i18n audit after updating the English catalog.

- [ ] **Step 4: Rewrite card UI**

`features/map/land/page.py`：

Signal area added:

```python
    open_vanilla_requested = pyqtSignal()        # Open original reference
    ref_adjust_toggled = pyqtSignal(bool)        # Adjust the reference image mode switch
    ref_adjust_target_changed = pyqtSignal(str)  # Adjust object: "custom"/"vanilla"
```

In the import area, add the `QButtonGroup` line with `QRadioButton` (`from PyQt5.QtWidgets import ... QRadioButton`).

Style constants (outside the class, after import):

```python
# Adjust mode switch: Normal secondary button appearance, Orange when checked= "In progress"（Same as transform tool)
_ADJUST_BTN_STYLE = _SECONDARY_BTN_STYLE + """
    QPushButton:checked {
        background: #f97316;
        border: 2px solid #fb923c;
        color: white;
        font-weight: 700;
    }
"""
```

Replace the entire section from `ref_card = _make_card(...)` to `lay.addWidget(ref_card)` (now lines 53-146) in `_init_ui` with:

```python
        # ══ ① Reference base map— The first step in making a picture: Put it under the canvas and trace it══
        ref_card = _make_card(tr("land_section_ref"), "①")

        # top: Two loading entrances (import custom/ Open the original version)
        load_row = QHBoxLayout()
        load_row.setSpacing(4)
        import_ref_btn = QPushButton(tr("land_btn_import_ref"))
        import_ref_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        import_ref_btn.setToolTip(tr("land_btn_import_ref_tip"))
        import_ref_btn.clicked.connect(self.import_ref_requested.emit)
        load_row.addWidget(import_ref_btn)
        self._open_vanilla_btn = QPushButton(tr("land_btn_open_vanilla"))
        self._open_vanilla_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._open_vanilla_btn.setToolTip(tr("land_btn_open_vanilla_tip"))
        self._open_vanilla_btn.clicked.connect(self.open_vanilla_requested.emit)
        load_row.addWidget(self._open_vanilla_btn)
        ref_card.layout().addLayout(load_row)

        # Original reference: Transparency+ Zoom+ Covered+ hide
        (self._vanilla_ref_opacity_slider, self._vanilla_ref_opacity_label,
         self._vanilla_ref_toggle) = self._add_ref_group(
            ref_card, tr("land_section_vanilla_ref"), opacity=30)
        (self._vanilla_ref_scale_slider, self._vanilla_ref_scale_label,
         self._vanilla_ref_fit_btn) = self._add_scale_row(ref_card)

        # Custom reference map: Same set
        (self._ref_opacity_slider, self._ref_opacity_label,
         self._ref_toggle) = self._add_ref_group(
            ref_card, tr("land_section_custom_ref"), opacity=40)
        (self._ref_scale_slider, self._ref_scale_label,
         self._ref_fit_btn) = self._add_scale_row(ref_card)

        # Adjust the reference picture position (switch+ Adjust object radio)
        self._ref_adjust_btn = QPushButton(tr("land_btn_ref_adjust"))
        self._ref_adjust_btn.setCheckable(True)
        self._ref_adjust_btn.setStyleSheet(_ADJUST_BTN_STYLE)
        self._ref_adjust_btn.toggled.connect(self._on_adjust_toggled)
        ref_card.layout().addWidget(self._ref_adjust_btn)

        target_row = QHBoxLayout()
        target_row.setSpacing(10)
        t_lbl = QLabel(tr("land_label_adjust_target"))
        t_lbl.setStyleSheet(_DIM_LABEL_STYLE)
        target_row.addWidget(t_lbl)
        self._adjust_custom_radio = QRadioButton(tr("land_adjust_custom"))
        self._adjust_custom_radio.setChecked(True)
        self._adjust_vanilla_radio = QRadioButton(tr("land_adjust_vanilla"))
        self._adjust_target_group = QButtonGroup(self)
        for r in (self._adjust_custom_radio, self._adjust_vanilla_radio):
            self._adjust_target_group.addButton(r)
            r.setEnabled(False)          # Normally put into ashes, Available only after entering adjustment mode
            target_row.addWidget(r)
        target_row.addStretch()
        self._adjust_custom_radio.toggled.connect(
            lambda on: on and self.ref_adjust_target_changed.emit("custom"))
        self._adjust_vanilla_radio.toggled.connect(
            lambda on: on and self.ref_adjust_target_changed.emit("vanilla"))
        ref_card.layout().addLayout(target_row)

        ref_card.layout().addWidget(_make_hint(tr("land_ref_adjust_hint")))
        lay.addWidget(ref_card)
```

Add two UI constructor helpers and three public methods + slot functions to the class (put before `_on_land_brush`):

```python
    # ── Basemap cardhelper ──
    def _add_ref_group(self, card, title: str, opacity: int):
        """The first two rows of a set of reference drawing controls: Title+Hide button/ Transparency slider."""
        head = QHBoxLayout()
        head.setSpacing(4)
        lbl = QLabel(title)
        lbl.setStyleSheet(_LABEL_STYLE)
        head.addWidget(lbl)
        head.addStretch()
        toggle = QPushButton(tr("land_btn_hide"))
        toggle.setCheckable(True)
        toggle.setStyleSheet(_SECONDARY_BTN_STYLE)
        toggle.setMinimumWidth(50)
        toggle.toggled.connect(
            lambda on, b=toggle: b.setText(
                tr("land_btn_show") if on else tr("land_btn_hide")))
        head.addWidget(toggle)
        card.layout().addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(4)
        cap = QLabel(tr("land_label_opacity"))
        cap.setStyleSheet(_DIM_LABEL_STYLE)
        row.addWidget(cap)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(opacity)
        slider.setStyleSheet(_SLIDER_STYLE)
        val = QLabel(f"{opacity}%")
        val.setStyleSheet(_DIM_LABEL_STYLE)
        val.setFixedWidth(36)
        slider.valueChanged.connect(lambda v, l=val: l.setText(f"{v}%"))
        row.addWidget(slider)
        row.addWidget(val)
        card.layout().addLayout(row)
        return slider, val, toggle

    def _add_scale_row(self, card):
        """One line zoom control: Zoom slider+ % + Covered with buttons."""
        row = QHBoxLayout()
        row.setSpacing(4)
        cap = QLabel(tr("land_label_scale"))
        cap.setStyleSheet(_DIM_LABEL_STYLE)
        row.addWidget(cap)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(10, 500)
        slider.setValue(100)
        slider.setStyleSheet(_SLIDER_STYLE)
        val = QLabel("100%")
        val.setStyleSheet(_DIM_LABEL_STYLE)
        val.setFixedWidth(36)
        slider.valueChanged.connect(lambda v, l=val: l.setText(f"{v}%"))
        fit = QPushButton(tr("land_btn_fit"))
        fit.setStyleSheet(_SECONDARY_BTN_STYLE)
        fit.setMinimumWidth(50)
        row.addWidget(slider)
        row.addWidget(val)
        row.addWidget(fit)
        card.layout().addLayout(row)
        return slider, val, fit

    def _on_adjust_toggled(self, on: bool) -> None:
        self._ref_adjust_btn.setText(
            tr("land_btn_ref_adjust_active") if on else tr("land_btn_ref_adjust"))
        self._adjust_custom_radio.setEnabled(on)
        self._adjust_vanilla_radio.setEnabled(on)
        self.ref_adjust_toggled.emit(on)

    def current_adjust_target(self) -> str:
        """Current adjustment object: "vanilla" / "custom"。"""
        return "vanilla" if self._adjust_vanilla_radio.isChecked() else "custom"

    def set_ref_adjust_checked(self, on: bool) -> None:
        """external(canvasESC Exit) sync button check status."""
        self._ref_adjust_btn.setChecked(on)

    def set_ref_scale_percent(self, target: str, percent: int) -> None:
        """Write back slider after canvas scroll wheel zooms (blockSignals Prevent scaling loops from being triggered again)."""
        slider = (self._vanilla_ref_scale_slider if target == "vanilla"
                  else self._ref_scale_slider)
        label = (self._vanilla_ref_scale_label if target == "vanilla"
                 else self._ref_scale_label)
        slider.blockSignals(True)
        slider.setValue(percent)
        slider.blockSignals(False)
        label.setText(f"{percent}%")
```

Note:`_DIM` / `_LABEL_STYLE` Waitimport Already exists; delete the original53-146 All old control construction code that was replaced in line (`v_lbl` / `v_row` / `c_head` / `c_row` / `scale_row` Wait for the entire local variable to disappear).

- [ ] **Step 5: Run the test to confirm it passed**

Run: `python -m pytest tests/views/test_land_page_ref_card.py -v`
Expected: 6 passed

- [ ] **Step 6: Run full test to prevent regression**

Run: `python -m pytest -m "not slow" -q`
Expected: All passed (all control names referenced by tool_panel property are retained)

- [ ] **Step 7: Commit**

```powershell
git add features/map/land/page.py ui/i18n/en/land.py tests/views/test_land_page_ref_card.py
git commit -m "feat: Rearrange basemap cards (import pinned to top)+Open the original version+Double graph symmetry control+Adjust mode switch)"
```

---

### Task 4: ToolPanel forwarding + MainWindow wiring + manual verification

**Files:**
- Modify: `ui/tool_panel.py` (3 signals + `_connect_land_signals` + 2 properties + 3 delegate methods)
- Modify: `views/main_window.py:322-345` (reference diagram wiring area added)
- Test: full pytest + manual GUI list

**Interfaces:**
- Consumes: Task 2 of`set_ref_adjust_mode` / `ref_adjust_exited` / `ref_adjust_scale_changed` / `set_ref_layer_scale` / `fit_ref_layer`；Task 3 All new signals of/method;`main_window_file_ops.py` ready-made`_on_load_vanilla_ref`
- Produces: Complete and available function chain

- [ ] **Step 1: tool_panel.py forward**

The signal area (next to `import_ref_requested = pyqtSignal()`) is added:

```python
    open_vanilla_requested = pyqtSignal()
    ref_adjust_toggled = pyqtSignal(bool)
    ref_adjust_target_changed = pyqtSignal(str)
```

Append `_connect_land_signals` at the end:

```python
        p.open_vanilla_requested.connect(self.open_vanilla_requested)
        p.ref_adjust_toggled.connect(self.ref_adjust_toggled)
        p.ref_adjust_target_changed.connect(self.ref_adjust_target_changed)
```

property area (after `_ref_toggle`) append:

```python
    @property
    def _vanilla_ref_scale_slider(self) -> QSlider:
        return self._land_page._vanilla_ref_scale_slider

    @property
    def _vanilla_ref_fit_btn(self) -> QPushButton:
        return self._land_page._vanilla_ref_fit_btn

    # Adjust reference image mode— entrustland page
    def current_adjust_target(self) -> str:
        return self._land_page.current_adjust_target()

    def set_ref_adjust_checked(self, on: bool) -> None:
        self._land_page.set_ref_adjust_checked(on)

    def set_ref_scale_percent(self, target: str, percent: int) -> None:
        self._land_page.set_ref_scale_percent(target, percent)
```

- [ ] **Step 2: main_window.py wiring**

Append at the end of the "Reference Picture Control → Canvas" area (lines 322-338):

```python
        # Original reference: Zoom+ Full (symmetrical to custom graph)
        tp._vanilla_ref_scale_slider.valueChanged.connect(
            lambda v: cv.set_ref_layer_scale("vanilla", v / 100.0)
        )
        tp._vanilla_ref_fit_btn.clicked.connect(
            lambda: cv.fit_ref_layer("vanilla")
        )
        # Open original reference (reuse File menu action)
        tp.open_vanilla_requested.connect(self._on_load_vanilla_ref)
        # Adjust reference image mode
        tp.ref_adjust_toggled.connect(
            lambda on: cv.set_ref_adjust_mode(
                tp.current_adjust_target() if on else None)
        )
        tp.ref_adjust_target_changed.connect(cv.set_ref_adjust_mode)
        cv.ref_adjust_exited.connect(lambda: tp.set_ref_adjust_checked(False))
        cv.ref_adjust_scale_changed.connect(
            lambda t, s: tp.set_ref_scale_percent(t, int(round(s * 100)))
        )
```

(`ref_adjust_target_changed` only transmits when the radio is available, and the radio is only available when the adjustment mode is activated. Direct connection to the `set_ref_adjust_mode` is safe.)

- [ ] **Step 3: Run full test**

Run: `python -m pytest -m "not slow" -q`
Expected: All passed

- [ ] **Step 4: Manual GUI Verification Checklist**

Run: `$env:PYTHONIOENCODING='utf-8'; python main.py`

Confirm item by item:
1. At the top of the land page card ① are two buttons [Import reference image...] [Open original reference]
2. Click "Open Original Reference" → the original map appears (when the game directory exists)
3. The zoom slider/fill button of the original reference takes effect and does not affect the customized image.
4. Click "🖐 Adjust reference image position" → the button turns orange, radio selection is available, the canvas cursor moves, and an orange dotted frame appears in the reference image
5. Left-click dragging in adjustment mode = move the reference image, **the brush does not drop**; scroll wheel = zoom the reference image and the slider value is synchronized
6. Select "Original" → drag/scroll to the original image
7. ESC → The button pops up, the dotted frame disappears, and the brush resumes
8. Normally Ctrl+left-click dragging/Ctrl+scroll wheel still works on the customized image

- [ ] **Step 5: Commit**

```powershell
git add ui/tool_panel.py views/main_window.py
git commit -m "feat: Refer to the base map for new signal wiring (open the original version/original zoom/Adjustment mode linkage)"
```

---

## After completion

- Report: changed files and verification results from the English-only i18n audit.
- Do not push, wait for user confirmation.
