# UI burden reduction and reconstruction implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge 13 editing modes into 7, fold advanced options on each page, and add protection against accidental touches.

**Architecture:** Create 4 merged pages (QTabWidget wraps the original page), modify the ToolPanel mode list and signal forwarding, and add anti-accidental touch confirmation on the canvas. The original page file is not modified, only wrapped in the outer layer.

**Tech Stack:** Python 3.10, PyQt5 (QTabWidget, QGroupBox collapse)

---

### Task 1: Create a collapsible group component

**Files:**
- Create: `ui/collapsible.py`

- [ ] **Step 1: Create CollapsibleSection widget**

```python
# ui/collapsible.py
"""Collapsible grouping— Click on title to expand/Collapse content."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy
from PyQt5.QtCore import Qt
from ui.styles import _ACCENT, _INPUT_BG, _BORDER, _DIM


class CollapsibleSection(QWidget):
    """Collapsible Area: Title Button+ Content container."""

    def __init__(self, title: str, parent=None, collapsed: bool = True):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._toggle = QPushButton(f"▸ {title}")
        self._toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {_ACCENT};
                font-size: 11px;
                font-weight: bold;
                text-align: left;
                padding: 6px 8px;
            }}
            QPushButton:hover {{
                color: #7c7cff;
            }}
        """)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self._on_toggle)
        lay.addWidget(self._toggle)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 4, 8, 8)
        self._content_layout.setSpacing(6)
        lay.addWidget(self._content)

        self._title = title
        self._collapsed = not collapsed  # _on_toggle will flip it
        self._on_toggle()

    def layout_content(self) -> QVBoxLayout:
        """Returns the content arealayout，Add controls from outside."""
        return self._content_layout

    def _on_toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        arrow = "▸" if self._collapsed else "▾"
        self._toggle.setText(f"{arrow} {self._title}")
```

- [ ] **Step 2: Verify import**

Run: `cd hoi4_map_maker && python -c "from ui.collapsible import CollapsibleSection; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ui/collapsible.py
git commit -m "feat: Collapsible group componentCollapsibleSection"
```

---

### Task 2: Create merge page — terrain (height + terrain)

**Files:**
- Create: `features/map/terrain_combined/page.py`
- Create: `features/map/terrain_combined/__init__.py`

- [ ] **Step 1: Create merge page**

```python
# features/map/terrain_combined/__init__.py
"""Terrain merge mode (height+terrain)."""
```

```python
# features/map/terrain_combined/page.py
"""Terrain merge page— QTabWidget packageHeightPage + TerrainPage。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import pyqtSignal
from ui.i18n import tr


class TerrainCombinedPage(QWidget):
    """Terrain merge page: Tabs switch height and terrain."""

    # Forward all subpage signals (height + terrain）
    # Height signals
    height_value_changed = pyqtSignal(int)
    auto_height_requested = pyqtSignal()
    smooth_height_requested = pyqtSignal()
    ridge_mode_toggled = pyqtSignal(bool)
    ridge_peak_changed = pyqtSignal(int)
    ridge_falloff_changed = pyqtSignal(int)
    # Terrain signals
    terrain_index_changed = pyqtSignal(int)
    terrain_brush_mode_changed = pyqtSignal(bool)
    terrain_brush_size_changed = pyqtSignal(int)
    terrain_soft_edge_changed = pyqtSignal(bool)
    auto_terrain_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from features.map.height.page import HeightPage
        from features.map.terrain.page import TerrainPage

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 6px 16px; font-size: 12px; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid #6c6cf0; }
            QTabBar::tab:!selected { color: #8888a8; }
        """)

        self._height_page = HeightPage()
        self._terrain_page = TerrainPage()
        self._tabs.addTab(self._height_page, tr("tab_height"))
        self._tabs.addTab(self._terrain_page, tr("tab_terrain"))
        lay.addWidget(self._tabs)

        # forwardheight signal
        self._height_page.height_value_changed.connect(self.height_value_changed)
        self._height_page.auto_height_requested.connect(self.auto_height_requested)
        self._height_page.smooth_height_requested.connect(self.smooth_height_requested)
        self._height_page.ridge_mode_toggled.connect(self.ridge_mode_toggled)
        self._height_page.ridge_peak_changed.connect(self.ridge_peak_changed)
        self._height_page.ridge_falloff_changed.connect(self.ridge_falloff_changed)
        # forwardterrain signal
        self._terrain_page.terrain_index_changed.connect(self.terrain_index_changed)
        self._terrain_page.terrain_brush_mode_changed.connect(self.terrain_brush_mode_changed)
        self._terrain_page.terrain_brush_size_changed.connect(self.terrain_brush_size_changed)
        self._terrain_page.terrain_soft_edge_changed.connect(self.terrain_soft_edge_changed)
        self._terrain_page.auto_terrain_requested.connect(self.auto_terrain_requested)
```

- [ ] **Step 2: Verify import**

Run: `cd hoi4_map_maker && python -c "from PyQt5.QtWidgets import QApplication; app=QApplication([]); from features.map.terrain_combined.page import TerrainCombinedPage; p=TerrainCombinedPage(); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add features/map/terrain_combined/
git commit -m "feat: terrain merge page(height+Terrain tab)"
```

---

### Task 3: Create a merge page — Country and Region (State + Country + Continent)

**Files:**
- Create: `features/map/region_combined/page.py`
- Create: `features/map/region_combined/__init__.py`

- [ ] **Step 1: Create merge page**

```python
# features/map/region_combined/__init__.py
"""National and regional merger patterns (state+country+continent)."""
```

```python
# features/map/region_combined/page.py
"""Country and region merged page— QTabWidget packageStatePage + CountryPage + ContinentPage。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import pyqtSignal
from ui.i18n import tr


class RegionCombinedPage(QWidget):
    """Country and region merge page: tab switch state/country/continent."""

    # State signals
    auto_states_requested = pyqtSignal(int)
    state_selected = pyqtSignal(int)
    state_property_changed = pyqtSignal(int, str, object)
    state_detail_requested = pyqtSignal(int)
    batch_create_state_toggled = pyqtSignal(bool)
    batch_create_state_confirmed = pyqtSignal()
    # Country signals
    create_country_requested = pyqtSignal()
    quick_create_country_requested = pyqtSignal(str, str, str)
    country_selected = pyqtSignal(str)
    country_property_changed = pyqtSignal(str, str, object)
    country_color_change_requested = pyqtSignal(str)
    # Continent signals
    continent_pick_toggled = pyqtSignal(bool)
    continent_add_requested = pyqtSignal(str)
    continent_rename_requested = pyqtSignal(int, str)
    continent_remove_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        from features.map.state.page import StatePage
        from features.map.country.page import CountryPage
        from features.map.continent.page import ContinentPage

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 6px 12px; font-size: 12px; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid #6c6cf0; }
            QTabBar::tab:!selected { color: #8888a8; }
        """)

        self._state_page = StatePage()
        self._country_page = CountryPage()
        self._continent_page = ContinentPage()
        self._tabs.addTab(self._state_page, tr("tab_state"))
        self._tabs.addTab(self._country_page, tr("tab_country"))
        self._tabs.addTab(self._continent_page, tr("tab_continent"))
        lay.addWidget(self._tabs)

        # forwardstate signal
        self._state_page.auto_states_requested.connect(self.auto_states_requested)
        self._state_page.state_selected.connect(self.state_selected)
        self._state_page.state_property_changed.connect(self.state_property_changed)
        self._state_page.state_detail_requested.connect(self.state_detail_requested)
        self._state_page.batch_create_state_toggled.connect(self.batch_create_state_toggled)
        self._state_page.batch_create_state_confirmed.connect(self.batch_create_state_confirmed)
        # forwardcountry signal
        self._country_page.create_country_requested.connect(self.create_country_requested)
        self._country_page.quick_create_country_requested.connect(self.quick_create_country_requested)
        self._country_page.country_selected.connect(self.country_selected)
        self._country_page.country_property_changed.connect(self.country_property_changed)
        self._country_page.country_color_change_requested.connect(self.country_color_change_requested)
        # forwardcontinent signal
        self._continent_page.continent_pick_toggled.connect(self.continent_pick_toggled)
        self._continent_page.continent_add_requested.connect(self.continent_add_requested)
        self._continent_page.continent_rename_requested.connect(self.continent_rename_requested)
        self._continent_page.continent_remove_requested.connect(self.continent_remove_requested)
```

- [ ] **Step 2: Verification + Commit**

Run: `cd hoi4_map_maker && python -c "from PyQt5.QtWidgets import QApplication; app=QApplication([]); from features.map.region_combined.page import RegionCombinedPage; p=RegionCombinedPage(); print('OK')"`

```bash
git add features/map/region_combined/
git commit -m "feat: Country and region merge page(state+country+Continents tab)"
```

---

### Task 4: Create a merge page - Logistics (strategic area + logistics system)

**Files:**
- Create: `features/map/logistics_combined/page.py`
- Create: `features/map/logistics_combined/__init__.py`

- [ ] **Step 1: Create merge page**

```python
# features/map/logistics_combined/__init__.py
"""Logistics consolidation model (strategic area+logistics system)."""
```

```python
# features/map/logistics_combined/page.py
"""Logistics merge page— QTabWidget packageStrategicRegionPage + LogisticsPage。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import pyqtSignal
from ui.i18n import tr


class LogisticsCombinedPage(QWidget):
    """Logistics merger page: The tab page switches strategic areas and logistics systems."""

    # Strategic region signals
    strategic_region_auto_requested = pyqtSignal()
    strategic_region_selected = pyqtSignal(int)
    strategic_region_new_requested = pyqtSignal()
    strategic_region_delete_requested = pyqtSignal()
    strategic_region_name_changed = pyqtSignal(str)
    strategic_region_weather_changed = pyqtSignal(str)
    strategic_region_naval_changed = pyqtSignal(str)
    strategic_region_pick_toggled = pyqtSignal(bool)
    create_from_states_toggled = pyqtSignal(bool)
    create_from_states_confirmed = pyqtSignal()
    # Logistics signals
    open_adjacency_dialog_requested = pyqtSignal()
    open_railway_list_requested = pyqtSignal()
    logistics_railway_level_changed = pyqtSignal(int)
    logistics_railway_draw_toggled = pyqtSignal(bool)
    logistics_supply_pick_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        from features.map.strategic_region.page import StrategicRegionPage
        from features.map.logistics.page import LogisticsPage

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 6px 12px; font-size: 12px; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid #6c6cf0; }
            QTabBar::tab:!selected { color: #8888a8; }
        """)

        self._strategic_region_page = StrategicRegionPage()
        self._logistics_page = LogisticsPage()
        self._tabs.addTab(self._strategic_region_page, tr("tab_strategic_region"))
        self._tabs.addTab(self._logistics_page, tr("tab_logistics"))
        lay.addWidget(self._tabs)

        # forwardstrategic_region signal
        p = self._strategic_region_page
        p.strategic_region_auto_requested.connect(self.strategic_region_auto_requested)
        p.strategic_region_selected.connect(self.strategic_region_selected)
        p.strategic_region_new_requested.connect(self.strategic_region_new_requested)
        p.strategic_region_delete_requested.connect(self.strategic_region_delete_requested)
        p.strategic_region_name_changed.connect(self.strategic_region_name_changed)
        p.strategic_region_weather_changed.connect(self.strategic_region_weather_changed)
        p.strategic_region_naval_changed.connect(self.strategic_region_naval_changed)
        p.strategic_region_pick_toggled.connect(self.strategic_region_pick_toggled)
        p.create_from_states_toggled.connect(self.create_from_states_toggled)
        p.create_from_states_confirmed.connect(self.create_from_states_confirmed)
        # forwardlogistics signal
        p2 = self._logistics_page
        p2.open_adjacency_dialog_requested.connect(self.open_adjacency_dialog_requested)
        p2.open_railway_list_requested.connect(self.open_railway_list_requested)
        p2.logistics_railway_level_changed.connect(self.logistics_railway_level_changed)
        p2.logistics_railway_draw_toggled.connect(self.logistics_railway_draw_toggled)
        p2.logistics_supply_pick_toggled.connect(self.logistics_supply_pick_toggled)
```

- [ ] **Step 2: Verification + Commit**

```bash
git add features/map/logistics_combined/
git commit -m "feat: Logistics merge page(strategic area+Logistics tab)"
```

---

### Task 5: Create merge page — settings (overview map + map configuration)

**Files:**
- Create: `features/map/settings_combined/page.py`
- Create: `features/map/settings_combined/__init__.py`

- [ ] **Step 1: Create merge page**

```python
# features/map/settings_combined/__init__.py
"""Set merge mode (overview map+map configuration)."""
```

```python
# features/map/settings_combined/page.py
"""Set up merge page— QTabWidget packageColormapPage + DefaultMapPage。"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import pyqtSignal
from ui.i18n import tr


class SettingsCombinedPage(QWidget):
    """Set merge page: tab to switch overview map and map configuration."""

    colormap_color_changed = pyqtSignal(str, int, int, int)
    colormap_reset_requested = pyqtSignal()
    default_map_river_changed = pyqtSignal(int)
    default_map_tree_add_requested = pyqtSignal()
    default_map_tree_del_requested = pyqtSignal()
    default_map_tree_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from features.map.colormap.page import ColormapPage
        from features.map.default_map.page import DefaultMapPage

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 6px 12px; font-size: 12px; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid #6c6cf0; }
            QTabBar::tab:!selected { color: #8888a8; }
        """)

        self._colormap_page = ColormapPage()
        self._default_map_page = DefaultMapPage()
        self._tabs.addTab(self._colormap_page, tr("tab_colormap"))
        self._tabs.addTab(self._default_map_page, tr("tab_default_map"))
        lay.addWidget(self._tabs)

        self._colormap_page.colormap_color_changed.connect(self.colormap_color_changed)
        self._colormap_page.colormap_reset_requested.connect(self.colormap_reset_requested)
        self._default_map_page.default_map_river_changed.connect(self.default_map_river_changed)
        self._default_map_page.default_map_tree_add_requested.connect(self.default_map_tree_add_requested)
        self._default_map_page.default_map_tree_del_requested.connect(self.default_map_tree_del_requested)
        self._default_map_page.default_map_tree_reset_requested.connect(self.default_map_tree_reset_requested)
```

- [ ] **Step 2: Verification + Commit**

```bash
git add features/map/settings_combined/
git commit -m "feat: Set up merge pages(Overview map+Map configuration tab)"
```

---

### Task 6: Refactor ToolPanel — 13→7 mode

**Files:**
- Modify: `ui/tool_panel.py`

- [ ] **Step 1: Update pattern list and page creation**

Modify the `_GroupedModeBar` parameters in `_init_ui` from 13 modes to 7:

```python
# old3group13mode→ new7Mode (no grouping, direct list)
self._mode_tabs = _GroupedModeBar([
    (tr("group_map_drawing"), [
        ("land", tr("mode_land_new")),         # draw a map
        ("province", tr("mode_province")),      # Province
        ("terrain", tr("mode_terrain_new")),     # terrain
        ("river", tr("mode_river_nav")),         # river
    ]),
    (tr("group_region_mgmt"), [
        ("region", tr("mode_region")),           # Countries and regions
        ("logistics", tr("mode_logistics_new")), # Logistics
    ]),
    (tr("group_settings"), [
        ("settings", tr("mode_settings")),       # settings
    ]),
])
```

Modify `_create_pages`: replace the original page with the merged page, while retaining references to subpages (compatible with external access through attributes such as `_land_page`):

```python
def _create_pages(self) -> None:
    from features.map.land.page import LandPage
    from features.map.province.page import ProvincePage
    from features.map.terrain_combined.page import TerrainCombinedPage
    from features.map.river.page import RiverPage
    from features.map.region_combined.page import RegionCombinedPage
    from features.map.logistics_combined.page import LogisticsCombinedPage
    from features.map.settings_combined.page import SettingsCombinedPage

    self._land_page = LandPage()
    self._province_page = ProvincePage()
    self._terrain_combined = TerrainCombinedPage()
    self._river_page = RiverPage()
    self._region_combined = RegionCombinedPage()
    self._logistics_combined = LogisticsCombinedPage()
    self._settings_combined = SettingsCombinedPage()

    # Compatibility attribute: external code passes_height_page, _terrain_page Waiting for visit
    self._height_page = self._terrain_combined._height_page
    self._terrain_page = self._terrain_combined._terrain_page
    self._state_page = self._region_combined._state_page
    self._country_page = self._region_combined._country_page
    self._continent_page = self._region_combined._continent_page
    self._strategic_region_page = self._logistics_combined._strategic_region_page
    self._logistics_page = self._logistics_combined._logistics_page
    self._colormap_page = self._settings_combined._colormap_page
    self._default_map_page = self._settings_combined._default_map_page

    page_list = [
        ("land", self._land_page),
        ("province", self._province_page),
        ("terrain", self._terrain_combined),
        ("river", self._river_page),
        ("region", self._region_combined),
        ("logistics", self._logistics_combined),
        ("settings", self._settings_combined),
    ]
    # ... rest same as before
```

Modify the signal connection: the signals of the merged page are directly connected to the ToolPanel (replacing the original separate `_connect_height_signals` + `_connect_terrain_signals`, etc.):

```python
self._connect_land_signals()
self._connect_province_signals()
self._connect_terrain_combined_signals()  # replaceheight + terrain
self._connect_river_signals()
self._connect_region_combined_signals()   # replacestate + country + continent
self._connect_logistics_combined_signals() # replacestrategic_region + logistics
self._connect_settings_combined_signals()  # replacecolormap + default_map
```

Each new method is directly connected to the signal of the merged page (the merged page has already forwarded the subpage → itself).

- [ ] **Step 2: Update display_mode mapping of _on_mode_changed**

The display_mode of the merged mode needs to be mapped to a mode name recognized by canvas. Canvas' `_full_render` has a renderers dictionary and needs to add "region"/"settings" mapping:

```python
def _on_mode_changed(self, mode: str) -> None:
    idx = self._mode_index.get(mode, 0)
    self._stack.setCurrentIndex(idx)
    # Merge mode maps tocanvas display_mode
    canvas_mode = {
        "region": "state",      # Displayed by defaultstate rendering
        "settings": "colormap", # Displayed by defaultcolormap rendering
    }.get(mode, mode)
    if mode not in ("province", "region"):
        self.tool_changed.emit("brush")
    self._hint_bar.on_mode_changed(mode)
    self.mode_changed.emit(canvas_mode)
```

- [ ] **Step 3: Verify ToolPanel starts**

Run: `cd hoi4_map_maker && python -c "from PyQt5.QtWidgets import QApplication; app=QApplication([]); from ui.tool_panel import ToolPanel; tp=ToolPanel(); print('modes:', len(tp._pages)); print('OK')"`
Expected: `modes: 7` + `OK`

- [ ] **Step 4: Commit**

```bash
git add ui/tool_panel.py
git commit -m "refactor: ToolPanelmode13→7(Merge pages+signal forwarding)"
```

---

### Task 7: Update main_window.py signal connection

**Files:**
- Modify: `views/main_window.py`

- [ ] **Step 1: Update _connect_signals**

The renderers dictionary of canvas display_mode needs to add the mapping of merged modes. In `views/canvas/widget.py`'s `_full_render` and `_partial_render` add:

```python
"region": self._render_state_mode,
"settings": self._render_land_mode,
```

At the same time, check whether all `tp.xxx.connect()` in `_connect_signals` of `views/main_window.py` are still valid (the signal name of ToolPanel remains unchanged, but the internal forwarding path has changed).

- [ ] **Step 2: Verify complete startup**

Run: `cd hoi4_map_maker && python -c "from PyQt5.QtWidgets import QApplication; app=QApplication([]); from views.main_window import MainWindow; w=MainWindow(); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add views/main_window.py views/canvas/widget.py
git commit -m "fix: updatecanvasRenderer+Signal connection adapts to merge mode"
```

---

### Task 8: Protection against accidental touch

**Files:**
- Modify: `views/canvas/widget.py`

- [ ] **Step 1: Modify the land mode of _stamp_brush**

In the `mode == "land"` branch of `_stamp_brush`, replace the silent clearing logic:

```python
if mode in ("land", "density"):
    if self._display_mode == "density":
        # ... Density brush logic remains unchanged...
        return

    # Prevent accidental touch: If there are already provinces when drawing land, you need to confirm
    if self._has_provinces and not getattr(self, '_province_clear_confirmed', False):
        # Set the flag and letcanvas signal toMainWindow Pop up confirmation box
        self._pending_land_paint = True
        self.land_paint_blocked.emit()  # new signal
        return

    # original logic...
```

Added signal `land_paint_blocked = pyqtSignal()` on MapCanvas.

MainWindow connects to this signal and pops up the confirmation box:
```python
self._canvas.land_paint_blocked.connect(self._on_land_paint_blocked)

def _on_land_paint_blocked(self):
    reply = QMessageBox.warning(
        self, tr("dlg_land_clear_title"),
        tr("dlg_land_clear_body"),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply == QMessageBox.StandardButton.Yes:
        self._canvas._province_clear_confirmed = True
        # Retrigger rendering
    else:
        self._canvas._pending_land_paint = False
```

- [ ] **Step 2: Add translation**

```python
"dlg_land_clear_title": "Modify Land",
"dlg_land_clear_body": "Modifying land will clear existing province data. Continue?",
```

- [ ] **Step 3: Commit**

```bash
git add views/canvas/widget.py views/main_window.py ui/i18n/en/*.py
git commit -m "feat: Anti-accidental touch protection(Make sure to clear the province before modifying the land)"
```

---

### Task 9: Add i18n translation

**Files:**
- Modify: `ui/i18n/en/*.py`

- [ ] **Step 1: Add all new translation keys**

```python
# Merge schema name
"mode_land_new": "Draw Map",
"mode_terrain_new": "Terrain",
"mode_region": "Countries & Regions",
"mode_logistics_new": "Logistics",
"mode_settings": "Settings",
"group_settings": "Config",

# Tab name
"tab_height": "Height",
"tab_terrain": "Terrain",
"tab_state": "States",
"tab_country": "Countries",
"tab_continent": "Continents",
"tab_strategic_region": "Strategic Regions",
"tab_logistics": "Logistics",
"tab_colormap": "Colormap",
"tab_default_map": "Map Config",
```

- [ ] **Step 2: Commit**

```bash
git add ui/i18n/en/*.py
git commit -m "feat: UIBurden-reducing translation(Merge schema name+Tab name)"
```

---

### Task 10: Remove independent density mode (merged into map drawing)

**Files:**
- Delete: `features/map/density/page.py`
- Delete: `features/map/density/__init__.py`
- Modify: `ui/tool_panel.py` — ensure density is no longer registered as a standalone mode

- [ ] **Step 1: Clean up the density directory**

```bash
rm -rf features/map/density/
```

Confirm that density-related signals in ToolPanel have been forwarded through land_page (density is used as a tool option for drawing maps).

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "refactor: Delete independentdensitymode(Merged into map drawing tool)"
```

---

### Task 11: Full testing + final submission

- [ ] **Step 1: Verify full boot and mode switch**

```bash
cd hoi4_map_maker
python -c "
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from views.main_window import MainWindow
w = MainWindow()
print('MainWindow OK')
# Number of verification modes
tp = w._tool_panel
print(f'Modes: {len(tp._pages)}')  # should be7
# Verify subpage references
assert tp._height_page is not None
assert tp._terrain_page is not None
assert tp._state_page is not None
assert tp._country_page is not None
print('All page references OK')
"
```

- [ ] **Step 2: Push**

```bash
git push
```
