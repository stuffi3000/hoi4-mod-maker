"""Tools panel — dark theme, 7-icon navigation mode + subtabs

Refactored from 13 mode grouping list → 7 icon buttons (Draw Map/Province/Terrain/River/Country and Region/Logistics/Settings).
Use horizontal subtabs to switch subpages in composite mode, and the stack still retains all 13 original pages.
The externally transmitted mode_id remains unchanged (land/density/province/height/terrain/river/state/...),
MainWindow/Canvas/Controller Zero changes."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QButtonGroup,
    QFrame, QStackedWidget, QScrollArea,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QTimer

from data.constants import BRUSH_DEFAULT
from ui.i18n import tr

from ui.styles import (
    _BG, _INPUT_BG, _BORDER, _TEXT, _ACCENT, _DIM,
    _SECTION_STYLE, _SUCCESS_BTN_STYLE,
)


# ── 7 navigation mode definitions ───────────────────────────────────────
# (nav_id, icon, i18n_key, [(sub_mode_id, i18n_key, risk), ...], nav_tooltip)
#
# Risk level (prompts the user which operations affect the game / are prone to crashing):
# "🎨" rendering layer (purely visual, absolutely safe)
# "🟢" Basic data (required but low risk)
# "🟠" affects game mechanics (need to be careful)
# "🔴" High-prone crash area (must strictly follow specifications)
# The fifth item is the i18n key of the tooltip (tr() gets the translation when rendering)
_NAV_MODES: list[tuple[str, str, str, list[tuple[str, str, str]], str]] = [
    ("map_draw", "🏖", "nav_map_draw", [
        ("land", "tab_land", "🟢"),
        ("density", "tab_density", "🟢"),
    ], "nav_tooltip_map_draw"),
    ("province", "🧩", "nav_province", [
        ("province", "", "🟢"),
    ], "nav_tooltip_province"),
    ("terrain_group", "⛰", "nav_terrain", [
        ("height", "tab_height", "🟠"),
        ("terrain", "tab_terrain", "🎨"),
        ("province_terrain", "tab_province_terrain", "🟢"),
    ], "nav_tooltip_terrain"),
    ("river", "💧", "nav_river", [
        ("river", "", "🔴"),
    ], "nav_tooltip_river"),
    ("region", "🏛", "nav_region", [
        ("state", "tab_state", "🟢"),
        ("country", "tab_country", "🟢"),
        ("continent", "tab_continent", "🟢"),
    ], "nav_tooltip_region"),
    ("logistics_group", "🛤", "nav_logistics", [
        ("strategic_region", "tab_strategic_region", "🟠"),
        ("logistics", "tab_logistics", "🟠"),
    ], "nav_tooltip_logistics"),
    ("preview_group", "👁", "nav_preview", [
        ("preview", "", "🎨"),
    ], "nav_tooltip_preview"),
    ("settings_group", "⚙", "nav_settings", [
        ("colormap", "tab_colormap", "🎨"),
        ("default_map", "tab_default_map", "🟠"),
    ], "nav_tooltip_settings"),
]


# ── risk label → color (for sub tab text) ────────────────────
_RISK_COLORS = {
    "🎨": "#7DD3FC",  # Light blue — render layer, safe
    "🟢": "#86EFAC",  # Light green — basic data, low risk
    "🟠": "#FDBA74",  # Orange - affects the game, need to be cautious
    "🔴": "#FCA5A5",  # Light red - crashes are common and regulations need to be strictly followed
}


# ── Icon mode navigation bar ─────────────────────────────────────────
_ICON_BTN_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-left: 3px solid transparent;
        color: {_DIM};
        padding: 10px 12px;
        font-size: 13px;
        font-weight: 400;
        text-align: left;
        margin: 0;
    }}
    QPushButton:checked {{
        background: rgba(79, 140, 255, 0.15);
        border-left: 3px solid {_ACCENT};
        color: white;
        font-weight: 600;
    }}
    QPushButton:hover:!checked {{
        background: rgba(79, 140, 255, 0.06);
        color: {_TEXT};
    }}
"""


class _IconModeBar(QWidget):
    """7 icon navigation buttons (compact vertical column)."""
    nav_changed = pyqtSignal(str)  # emit nav_id

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._buttons: dict[str, QPushButton] = {}
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)

        for nav_id, icon, label_key, _subs, tooltip_key in _NAV_MODES:
            btn = QPushButton(f"  {icon}  {tr(label_key)}")
            btn.setCheckable(True)
            btn.setProperty("nav_id", nav_id)
            btn.setStyleSheet(_ICON_BTN_STYLE)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setToolTip(tr(tooltip_key))  # Risk level reminder
            self._btn_group.addButton(btn)
            self._buttons[nav_id] = btn
            layout.addWidget(btn)

        self._btn_group.buttonClicked.connect(
            lambda btn: self.nav_changed.emit(btn.property("nav_id"))
        )

        # The first one is selected by default
        first = list(self._buttons.values())[0]
        first.setChecked(True)

    def retranslateUi(self) -> None:
        """Refresh button text after language switching."""
        for nav_id, icon, label_key, _subs, tooltip_key in _NAV_MODES:
            btn = self._buttons.get(nav_id)
            if btn:
                btn.setText(f"  {icon}  {tr(label_key)}")
                btn.setToolTip(tr(tooltip_key))


# ── Submode tab bar ───────────────────────────────────────────
_TAB_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        color: {_DIM};
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton:checked {{
        border-bottom: 2px solid {_ACCENT};
        color: white;
        font-weight: 600;
    }}
    QPushButton:hover:!checked {{
        color: {_TEXT};
    }}
"""


class _SubModeTabBar(QWidget):
    """Horizontal subtab bar — only shown in compound mode (submode > 1)."""
    sub_mode_changed = pyqtSignal(str)  # emit sub_mode_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setStyleSheet(f"background: {_INPUT_BG}; border-bottom: 1px solid {_BORDER};")

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 0, 8, 0)
        self._layout.setSpacing(0)

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._btn_group.buttonClicked.connect(self._on_tab_clicked)
        self._buttons: list[QPushButton] = []
        self._current_tabs: list[tuple[str, str, str]] = []
        # Some tabs use the risk dot as a live completion indicator.  Keep the
        # catalogue risk as the fallback for modes without a readiness rule.
        self._feature_ready: dict[str, bool] = {}

        self.hide()

    def set_tabs(self, tabs: list[tuple[str, str, str]]) -> None:
        """Set a list of subtags. tabs=[(mode_id, i18n_key, risk), ...].
        risk is the risk level emoji (🎨/🟢/🟠/🔴), displayed before the button text.
        If there is only one tab (or label_key is empty), it is hidden."""
        # clear old button
        for btn in self._buttons:
            self._btn_group.removeButton(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._buttons.clear()
        self._current_tabs = list(tabs)

        # Clear stretch items
        while self._layout.count():
            self._layout.takeAt(0)

        # Displayed only if there is >1 sub-mode and both have labels
        visible_tabs = [(mid, lk, risk) for mid, lk, risk in tabs if lk]
        if len(visible_tabs) <= 1:
            self.hide()
            return

        self._layout.addStretch()
        for mode_id, label_key, risk in visible_tabs:
            # The risk label is displayed as a prefix
            if mode_id in self._feature_ready:
                risk = "🟢" if self._feature_ready[mode_id] else "🟠"
            btn_text = f"{risk} {tr(label_key)}" if risk else tr(label_key)
            btn = QPushButton(btn_text)
            btn.setCheckable(True)
            btn.setProperty("sub_mode_id", mode_id)
            btn.setStyleSheet(_TAB_STYLE)
            self._btn_group.addButton(btn)
            self._buttons.append(btn)
            self._layout.addWidget(btn)
        self._layout.addStretch()

        # The first one is selected by default
        if self._buttons:
            self._buttons[0].setChecked(True)

        self.show()

    def set_feature_ready(self, mode_id: str, ready: bool) -> None:
        """Update a live readiness dot without changing other tab risk labels."""
        self._feature_ready[mode_id] = bool(ready)
        for button in self._buttons:
            if button.property("sub_mode_id") == mode_id:
                label = next(
                    (label_key for mid, label_key, _risk in self._current_tabs
                     if mid == mode_id),
                    "",
                )
                if label:
                    button.setText(f"{'🟢' if ready else '🟠'} {tr(label)}")
                break

    def _on_tab_clicked(self, btn: QPushButton) -> None:
        mid = btn.property("sub_mode_id")
        if mid:
            self.sub_mode_changed.emit(mid)

    def select_tab(self, mode_id: str) -> None:
        """Select a subtab externally."""
        for btn in self._buttons:
            if btn.property("sub_mode_id") == mode_id:
                btn.setChecked(True)
                break


# ── Main panel ─────────────────────────────────────────────
class ToolPanel(QWidget):
    """Left tool panel — 7 navigation icons + subtabs + 13 page stacks"""

    # Signal (keeps connection to MainWindow intact)
    mode_changed = pyqtSignal(str)
    tool_changed = pyqtSignal(str)
    tile_type_changed = pyqtSignal(int)
    brush_size_changed = pyqtSignal(int)
    terrain_index_changed = pyqtSignal(int)
    terrain_brush_mode_changed = pyqtSignal(bool)
    # Property terrain: Which provincial terrain type is selected
    province_terrain_type_changed = pyqtSignal(str)
    # Attribute Terrain: Assign Mode Switch
    province_terrain_assign_mode_changed = pyqtSignal(bool)
    # Attributed terrain: attributes are fully recalculated from the visual terrain
    province_terrain_sync_requested = pyqtSignal()
    height_value_changed = pyqtSignal(int)
    generate_provinces_requested = pyqtSignal(str, int)
    validate_requested = pyqtSignal()
    smooth_coast_requested = pyqtSignal()
    import_ref_requested = pyqtSignal()
    auto_land_from_ref_requested = pyqtSignal()
    auto_provinces_from_ref_requested = pyqtSignal()
    random_split_requested = pyqtSignal(int)
    open_vanilla_requested = pyqtSignal()
    ref_adjust_toggled = pyqtSignal(bool)
    ref_adjust_target_changed = pyqtSignal(str)
    clear_new_land_mask_requested = pyqtSignal()

    # Density mode signal
    density_value_changed = pyqtSignal(float)
    density_brush_size_changed = pyqtSignal(int)
    density_soft_edge_changed = pyqtSignal(int)
    density_clear_requested = pyqtSignal()
    auto_terrain_requested = pyqtSignal()
    detail_terrain_requested = pyqtSignal(int)
    beautify_terrain_requested = pyqtSignal(int)
    downgrade_mountain_requested = pyqtSignal()
    downgrade_lasso_mode_toggled = pyqtSignal(bool)
    terrain_brush_size_changed = pyqtSignal(int)
    terrain_soft_edge_changed = pyqtSignal(bool)
    auto_height_requested = pyqtSignal()
    realistic_height_requested = pyqtSignal()
    height_from_terrain_requested = pyqtSignal()
    height_brush_mode_changed = pyqtSignal(str)
    height_brush_size_changed = pyqtSignal(int)
    height_brush_strength_changed = pyqtSignal(int)
    ridge_mode_toggled = pyqtSignal(bool)
    ridge_peak_changed = pyqtSignal(int)
    ridge_falloff_changed = pyqtSignal(int)
    ridge_preview_requested = pyqtSignal()
    ridge_confirmed = pyqtSignal()
    ridge_cancelled = pyqtSignal()
    refine_whole_map_requested = pyqtSignal()
    export_requested = pyqtSignal()
    preview_refresh_requested = pyqtSignal()
    preview_game_dir_changed = pyqtSignal(str)
    preview_political_toggled = pyqtSignal(bool)
    preview_night_toggled = pyqtSignal(bool)
    split_mode_toggled = pyqtSignal(bool)
    lasso_province_toggled = pyqtSignal(bool)
    merge_mode_toggled = pyqtSignal(bool)
    find_province_requested = pyqtSignal(int)
    province_paint_mode_changed = pyqtSignal(str)
    province_brush_size_changed = pyqtSignal(int)
    new_province_requested = pyqtSignal()

    # State / Country signal
    auto_states_requested = pyqtSignal(int)
    state_selected = pyqtSignal(int)
    state_property_changed = pyqtSignal(int, str, object)
    state_detail_requested = pyqtSignal(int)
    batch_create_state_toggled = pyqtSignal(bool)
    batch_create_state_confirmed = pyqtSignal()
    state_assign_mode_changed = pyqtSignal(bool)
    state_delete_requested = pyqtSignal(int)
    state_show_names_toggled = pyqtSignal(bool)
    state_resplit_requested = pyqtSignal(int, int)
    create_country_requested = pyqtSignal()
    quick_create_country_requested = pyqtSignal(str, str, str)
    country_selected = pyqtSignal(str)
    country_delete_requested = pyqtSignal(str)
    country_property_changed = pyqtSignal(str, str, object)
    country_color_change_requested = pyqtSignal(str)
    country_show_names_toggled = pyqtSignal(bool)
    country_assign_mode_toggled = pyqtSignal(bool)

    # river signal
    river_type_changed = pyqtSignal(int)
    validate_river_requested = pyqtSignal()
    auto_hydrology_from_ref_requested = pyqtSignal()

    # logistic signal
    open_adjacency_dialog_requested = pyqtSignal()
    open_railway_list_requested = pyqtSignal()
    generate_logistics_requested = pyqtSignal()
    logistics_railway_level_changed = pyqtSignal(int)
    logistics_supply_pick_toggled = pyqtSignal(bool, bool)

    # continental division signal
    continent_pick_toggled = pyqtSignal(bool)
    continent_add_requested = pyqtSignal(str)
    continent_rename_requested = pyqtSignal(int, str)
    continent_remove_requested = pyqtSignal(int)
    assign_by_state_changed = pyqtSignal(bool)

    # strategic area signals
    strategic_region_auto_requested = pyqtSignal()
    auto_weather_requested = pyqtSignal()
    strategic_region_selected = pyqtSignal(int)
    strategic_region_new_requested = pyqtSignal()
    strategic_region_delete_requested = pyqtSignal()
    strategic_region_name_changed = pyqtSignal(str)
    strategic_region_name_en_changed = pyqtSignal(str)
    strategic_region_weather_changed = pyqtSignal(str)
    strategic_region_naval_changed = pyqtSignal(str)
    strategic_region_pick_toggled = pyqtSignal(bool)
    sr_assign_mode_changed = pyqtSignal(bool)
    create_from_states_toggled = pyqtSignal(bool)
    create_from_states_confirmed = pyqtSignal()

    # Overview map signal
    colormap_color_changed = pyqtSignal(str, int, int, int)
    colormap_reset_requested = pyqtSignal()

    # map configuration signal
    default_map_river_changed = pyqtSignal(int)
    default_map_tree_add_requested = pyqtSignal()
    default_map_tree_del_requested = pyqtSignal()
    default_map_tree_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(520)
        self.setStyleSheet(f"background: {_BG};")

        # nav_id → subpattern list (lookup table)
        self._nav_subs: dict[str, list[tuple[str, str, str]]] = {}
        # sub_mode_id → nav_id (reverse lookup)
        self._sub_to_nav: dict[str, str] = {}
        # sub_mode_id → risk emoji (used to display risk labels)
        self._sub_risks: dict[str, str] = {}
        for nav_id, _icon, _label, subs, _tooltip in _NAV_MODES:
            self._nav_subs[nav_id] = subs
            for sub_id, _sub_label, risk in subs:
                self._sub_to_nav[sub_id] = nav_id
                self._sub_risks[sub_id] = risk

        self._current_nav = ""
        self._init_ui()

    # ── UI construction ─────────────────────────────────────────
    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Icon navigation bar (7 buttons)
        self._icon_bar = _IconModeBar()
        self._icon_bar.nav_changed.connect(self._on_nav_changed)
        root.addWidget(self._icon_bar)

        # Subtab bar (displayed in composite mode)
        self._sub_tabs = _SubModeTabBar()
        self._sub_tabs.sub_mode_changed.connect(self._on_sub_mode_changed)
        root.addWidget(self._sub_tabs)

        # Mode operation prompt bar
        from ui.mode_hint_bar import ModeHintBar
        self._hint_bar = ModeHintBar()
        root.addWidget(self._hint_bar)

        # Page content scroll area
        self._page_scroll = QScrollArea()
        self._page_scroll.setWidgetResizable(True)
        self._page_scroll.setFrameShape(QFrame.NoFrame)
        self._page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._page_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent; border: none;")
        self._stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # Scroll back cover: After page cutting, the scrolling range is reset according to the height of the current page (delayed by one frame until the layout is stable)
        self._stack.currentChanged.connect(
            lambda _: QTimer.singleShot(0, self._sync_stack_height))
        self._page_scroll.setWidget(self._stack)
        root.addWidget(self._page_scroll, 1)

        # Create each page instance and connect the signal
        self._create_pages()

        # Initialize the subtab bar of the first navigation group (the icon bar setChecked does not trigger the signal)
        first_nav = _NAV_MODES[0][0]
        self._on_nav_changed(first_nav)

        # Bottom fixed area
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {_BORDER}; margin: 0;")
        root.addWidget(sep)

        self._export_btn = QPushButton(tr("panel_export_btn"))
        self._export_btn.setStyleSheet(_SUCCESS_BTN_STYLE)
        self._export_btn.clicked.connect(self.export_requested.emit)
        root.addWidget(self._export_btn)

    def _sync_stack_height(self) -> None:
        """Scroll back cover: stack height = max (viewport height, current page demand is high).

        QStackedWidget defaults to "the highest page among all pages" to expand the scrolling range and shorten the page.
        Can scroll down to create a large blank; QScrollArea's automatic resize will override the normal resize
        and sizeHint are overridden, so use setFixedHeight to force pinning."""
        cur = self._stack.currentWidget()
        if cur is None:
            return
        h = max(self._page_scroll.viewport().height(), cur.sizeHint().height())
        self._stack.setFixedHeight(h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_stack_height()

    def _create_pages(self) -> None:
        """Instantiate each page class, add to stack, and connect signal forwarding."""
        from features.map.land.page import LandPage
        from features.map.density.page import DensityPage
        from features.map.province.page import ProvincePage
        from features.map.terrain.page import TerrainPage
        from features.map.province_terrain.page import ProvincialTerrainPage
        from features.map.height.page import HeightPage
        from features.map.river.page import RiverPage
        from features.map.state.page import StatePage
        from features.map.country.page import CountryPage
        from features.map.continent.page import ContinentPage
        from features.map.strategic_region.page import StrategicRegionPage
        from features.map.logistics.page import LogisticsPage
        from features.map.colormap.page import ColormapPage
        from features.map.default_map.page import DefaultMapPage
        from features.map.preview.page import PreviewPage

        # Create instance
        self._land_page = LandPage()
        self._density_page = DensityPage()
        self._province_page = ProvincePage()
        self._terrain_page = TerrainPage()
        self._province_terrain_page = ProvincialTerrainPage()
        self._height_page = HeightPage()
        self._river_page = RiverPage()
        self._state_page = StatePage()
        self._country_page = CountryPage()
        self._continent_page = ContinentPage()
        self._strategic_region_page = StrategicRegionPage()
        self._logistics_page = LogisticsPage()
        self._colormap_page = ColormapPage()
        self._default_map_page = DefaultMapPage()
        self._preview_page = PreviewPage()

        # Add to stack in order of mode_id
        page_list = [
            ("land", self._land_page),
            ("density", self._density_page),
            ("province", self._province_page),
            ("height", self._height_page),
            ("terrain", self._terrain_page),
            ("province_terrain", self._province_terrain_page),
            ("river", self._river_page),
            ("state", self._state_page),
            ("country", self._country_page),
            ("continent", self._continent_page),
            ("strategic_region", self._strategic_region_page),
            ("logistics", self._logistics_page),
            ("colormap", self._colormap_page),
            ("default_map", self._default_map_page),
            ("preview", self._preview_page),
        ]
        self._pages: dict[str, QWidget] = {}
        self._mode_index: dict[str, int] = {}
        for i, (mode_id, page) in enumerate(page_list):
            self._stack.addWidget(page)
            self._pages[mode_id] = page
            self._mode_index[mode_id] = i
        self._stack.setCurrentIndex(0)

        # ── Signal forwarding ──
        self._connect_land_signals()
        self._connect_density_signals()
        self._connect_province_signals()
        self._connect_terrain_signals()
        self._connect_height_signals()
        self._connect_river_signals()
        self._connect_state_signals()
        self._connect_country_signals()
        self._connect_continent_signals()
        self._connect_strategic_region_signals()
        self._connect_logistics_signals()
        self._connect_colormap_signals()
        self._connect_default_map_signals()
        self._connect_preview_signals()

    def _connect_land_signals(self) -> None:
        p = self._land_page
        p.tool_changed.connect(self.tool_changed)
        p.tile_type_changed.connect(self.tile_type_changed)
        p.brush_size_changed.connect(self.brush_size_changed)
        p.smooth_coast_requested.connect(self.smooth_coast_requested)
        p.clear_new_land_mask_requested.connect(self.clear_new_land_mask_requested)
        p.import_ref_requested.connect(self.import_ref_requested)
        p.auto_land_from_ref_requested.connect(self.auto_land_from_ref_requested)
        p.open_vanilla_requested.connect(self.open_vanilla_requested)
        p.ref_adjust_toggled.connect(self.ref_adjust_toggled)
        p.ref_adjust_target_changed.connect(self.ref_adjust_target_changed)

    def _connect_density_signals(self) -> None:
        p = self._density_page
        p.density_value_changed.connect(self.density_value_changed)
        p.density_brush_size_changed.connect(self.density_brush_size_changed)
        p.density_soft_edge_changed.connect(self.density_soft_edge_changed)
        p.density_clear_requested.connect(self.density_clear_requested)

    def _connect_province_signals(self) -> None:
        p = self._province_page
        p.split_mode_toggled.connect(self.split_mode_toggled)
        p.lasso_province_toggled.connect(self.lasso_province_toggled)
        p.merge_mode_toggled.connect(self.merge_mode_toggled)
        p.find_province_requested.connect(self.find_province_requested)
        p.province_paint_mode_changed.connect(self.province_paint_mode_changed)
        p.province_brush_size_changed.connect(self.province_brush_size_changed)
        p.new_province_requested.connect(self.new_province_requested)
        p.generate_provinces_requested.connect(self.generate_provinces_requested)
        p.validate_requested.connect(self.validate_requested)
        p.import_ref_requested.connect(self.import_ref_requested)
        p.auto_provinces_from_ref_requested.connect(self.auto_provinces_from_ref_requested)
        p.random_split_requested.connect(self.random_split_requested)

    def _connect_terrain_signals(self) -> None:
        p = self._terrain_page
        p.terrain_index_changed.connect(self.terrain_index_changed)
        p.terrain_brush_mode_changed.connect(self.terrain_brush_mode_changed)
        p.terrain_brush_size_changed.connect(self.terrain_brush_size_changed)
        p.terrain_soft_edge_changed.connect(self.terrain_soft_edge_changed)
        p.auto_terrain_requested.connect(self.auto_terrain_requested)
        p.detail_terrain_requested.connect(self.detail_terrain_requested)
        p.beautify_terrain_requested.connect(self.beautify_terrain_requested)
        p.downgrade_mountain_requested.connect(self.downgrade_mountain_requested)
        p.downgrade_lasso_mode_toggled.connect(self.downgrade_lasso_mode_toggled)
        # Property terrain page signal
        self._province_terrain_page.type_changed.connect(self.province_terrain_type_changed)
        self._province_terrain_page.assign_mode_changed.connect(self.province_terrain_assign_mode_changed)
        self._province_terrain_page.sync_requested.connect(self.province_terrain_sync_requested)

    def _connect_height_signals(self) -> None:
        p = self._height_page
        p.height_value_changed.connect(self.height_value_changed)
        p.auto_height_requested.connect(self.auto_height_requested)
        p.realistic_height_requested.connect(self.realistic_height_requested)
        p.height_from_terrain_requested.connect(self.height_from_terrain_requested)
        p.ridge_mode_toggled.connect(self.ridge_mode_toggled)
        p.ridge_peak_changed.connect(self.ridge_peak_changed)
        p.ridge_falloff_changed.connect(self.ridge_falloff_changed)
        p.ridge_preview_requested.connect(self.ridge_preview_requested)
        p.ridge_confirmed.connect(self.ridge_confirmed)
        p.ridge_cancelled.connect(self.ridge_cancelled)
        p.refine_whole_map_requested.connect(self.refine_whole_map_requested)
        p.height_brush_mode_changed.connect(self.height_brush_mode_changed)
        p.height_brush_size_changed.connect(self.height_brush_size_changed)
        p.height_brush_strength_changed.connect(self.height_brush_strength_changed)

    def _connect_river_signals(self) -> None:
        p = self._river_page
        p.tool_changed.connect(self.tool_changed)
        p.brush_size_changed.connect(self.brush_size_changed)
        p.river_type_changed.connect(self.river_type_changed)
        p.validate_river_requested.connect(self.validate_river_requested)
        p.auto_hydrology_from_ref_requested.connect(self.auto_hydrology_from_ref_requested)

    def _connect_state_signals(self) -> None:
        p = self._state_page
        p.auto_states_requested.connect(self.auto_states_requested)
        p.state_selected.connect(self.state_selected)
        p.state_property_changed.connect(self.state_property_changed)
        p.state_detail_requested.connect(self.state_detail_requested)
        p.batch_create_state_toggled.connect(self.batch_create_state_toggled)
        p.batch_create_state_confirmed.connect(self.batch_create_state_confirmed)
        p.assign_mode_changed.connect(self.state_assign_mode_changed)
        p.state_delete_requested.connect(self.state_delete_requested)
        p.show_names_toggled.connect(self.state_show_names_toggled)
        p.resplit_state_requested.connect(self.state_resplit_requested)

    def _connect_country_signals(self) -> None:
        p = self._country_page
        p.create_country_requested.connect(self.create_country_requested)
        p.quick_create_country_requested.connect(self.quick_create_country_requested)
        p.country_selected.connect(self.country_selected)
        p.country_property_changed.connect(self.country_property_changed)
        p.country_color_change_requested.connect(self.country_color_change_requested)
        p.country_delete_requested.connect(self.country_delete_requested)
        p.show_names_toggled.connect(self.country_show_names_toggled)
        p.assign_mode_toggled.connect(self.country_assign_mode_toggled)

    def reset_country_assign_mode(self) -> None:
        """Reset the "Assign Territory Mode" button when switching out of country mode (does not trigger the signal)."""
        self._country_page.reset_assign_mode()

    def set_country_assign_mode(self, on: bool) -> None:
        """Programmatically switch "assignment territory mode" (trigger signal, controller will synchronize)."""
        self._country_page.set_assign_mode(on)

    def select_country_in_list(self, tag: str) -> None:
        """After clicking on the map to select a country, the country list will be highlighted."""
        self._country_page.select_country_in_list(tag)

    def _connect_continent_signals(self) -> None:
        p = self._continent_page
        p.continent_pick_toggled.connect(self.continent_pick_toggled)
        p.continent_add_requested.connect(self.continent_add_requested)
        p.continent_rename_requested.connect(self.continent_rename_requested)
        p.continent_remove_requested.connect(self.continent_remove_requested)
        p.assign_by_state_changed.connect(self.assign_by_state_changed)

    def _connect_strategic_region_signals(self) -> None:
        p = self._strategic_region_page
        p.strategic_region_auto_requested.connect(self.strategic_region_auto_requested)
        p.auto_weather_requested.connect(self.auto_weather_requested)
        p.strategic_region_selected.connect(self.strategic_region_selected)
        p.strategic_region_new_requested.connect(self.strategic_region_new_requested)
        p.strategic_region_delete_requested.connect(self.strategic_region_delete_requested)
        p.strategic_region_name_changed.connect(self.strategic_region_name_changed)
        p.strategic_region_name_en_changed.connect(self.strategic_region_name_en_changed)
        p.strategic_region_weather_changed.connect(self.strategic_region_weather_changed)
        p.strategic_region_naval_changed.connect(self.strategic_region_naval_changed)
        p.strategic_region_pick_toggled.connect(self.strategic_region_pick_toggled)
        p.sr_assign_mode_changed.connect(self.sr_assign_mode_changed)
        p.create_from_states_toggled.connect(self.create_from_states_toggled)
        p.create_from_states_confirmed.connect(self.create_from_states_confirmed)

    def _connect_logistics_signals(self) -> None:
        p = self._logistics_page
        p.open_adjacency_dialog_requested.connect(self.open_adjacency_dialog_requested)
        p.open_railway_list_requested.connect(self.open_railway_list_requested)
        p.generate_logistics_requested.connect(self.generate_logistics_requested)
        p.logistics_railway_level_changed.connect(self.logistics_railway_level_changed)
        p.logistics_supply_pick_toggled.connect(self.logistics_supply_pick_toggled)

    def _connect_colormap_signals(self) -> None:
        p = self._colormap_page
        p.colormap_color_changed.connect(self.colormap_color_changed)
        p.colormap_reset_requested.connect(self.colormap_reset_requested)

    def _connect_default_map_signals(self) -> None:
        p = self._default_map_page
        p.default_map_river_changed.connect(self.default_map_river_changed)
        p.default_map_tree_add_requested.connect(self.default_map_tree_add_requested)
        p.default_map_tree_del_requested.connect(self.default_map_tree_del_requested)
        p.default_map_tree_reset_requested.connect(self.default_map_tree_reset_requested)

    def _connect_preview_signals(self) -> None:
        p = self._preview_page
        p.refresh_requested.connect(self.preview_refresh_requested)
        p.game_dir_changed.connect(self.preview_game_dir_changed)
        p.political_toggled.connect(self.preview_political_toggled)
        p.night_toggled.connect(self.preview_night_toggled)

    # ── Properties (remain compatible with MainWindow) ─────────────────────
    @property
    def ref_opacity_slider(self) -> QSlider:
        return self._land_page._ref_opacity_slider

    @property
    def mode_tabs(self) -> _IconModeBar:
        return self._icon_bar

    # Reference Diagram Control — Exposed to MainWindow Direct Canvas
    @property
    def _vanilla_ref_opacity_slider(self) -> QSlider:
        return self._land_page._vanilla_ref_opacity_slider

    @property
    def _vanilla_ref_toggle(self) -> QPushButton:
        return self._land_page._vanilla_ref_toggle

    @property
    def _ref_scale_slider(self) -> QSlider:
        return self._land_page._ref_scale_slider

    @property
    def _ref_toggle(self) -> QPushButton:
        return self._land_page._ref_toggle

    @property
    def _vanilla_ref_scale_slider(self) -> QSlider:
        return self._land_page._vanilla_ref_scale_slider

    # Adjust reference drawing mode — delegate land page
    def current_adjust_target(self) -> str:
        return self._land_page.current_adjust_target()

    def set_ref_adjust_checked(self, on: bool) -> None:
        self._land_page.set_ref_adjust_checked(on)

    def set_ref_scale_percent(self, target: str, percent: int) -> None:
        self._land_page.set_ref_scale_percent(target, percent)

    # Quickly create colors - external reading
    @property
    def _quick_create_color(self) -> tuple:
        return self._country_page._quick_create_color

    # Logistics status label - external direct update
    @property
    def _logi_adj_status(self) -> QLabel:
        return self._logistics_page._logi_adj_status

    @property
    def _logi_rail_status(self) -> QLabel:
        return self._logistics_page._logi_rail_status

    @property
    def _logi_sup_status(self) -> QLabel:
        return self._logistics_page._logi_sup_status

    @property
    def _logi_rail_draw_btn(self) -> QPushButton:
        return self._logistics_page._logi_rail_draw_btn

    @property
    def _logi_sup_toggle_btn(self) -> QPushButton:
        return self._logistics_page._logi_sup_toggle_btn

    @property
    def _logi_rail_level(self):
        return self._logistics_page._logi_rail_level

    # Continent List/Loading/Status - direct external access
    @property
    def _continent_list(self):
        return self._continent_page._continent_list

    @property
    def _continent_pick_btn(self):
        return self._continent_page._continent_pick_btn

    @property
    def _continent_status(self):
        return self._continent_page._continent_status

    # Strategic areas - direct external access
    @property
    def _sr_list(self):
        return self._strategic_region_page._sr_list

    @property
    def _sr_name_edit(self):
        return self._strategic_region_page._sr_name_edit

    @property
    def _sr_name_en_edit(self):
        return self._strategic_region_page._sr_name_en_edit

    @property
    def _sr_weather_combo(self):
        return self._strategic_region_page._sr_weather_combo

    @property
    def _sr_naval_combo(self):
        return self._strategic_region_page._sr_naval_combo

    @property
    def _sr_prov_count(self):
        return self._strategic_region_page._sr_prov_count

    @property
    def _sr_pick_btn(self):
        return self._strategic_region_page._sr_pick_btn

    # Colormap swatches — external access via old name
    @property
    def _colormap_land_swatch(self):
        return self._colormap_page._swatches["land"]

    @property
    def _colormap_sea_swatch(self):
        return self._colormap_page._swatches["sea"]

    @property
    def _colormap_lake_swatch(self):
        return self._colormap_page._swatches["lake"]

    # Default map — direct external access
    @property
    def _dm_river_max(self):
        return self._default_map_page._dm_river_max

    @property
    def _dm_tree_list(self):
        return self._default_map_page._dm_tree_list

    # Province Merge/Expand Button - External Access
    @property
    def _merge_btn(self):
        return self._province_page._merge_btn

    @property
    def _expand_btn(self):
        return self._province_page._expand_btn

    @property
    def _province_hint(self):
        return self._province_page._province_hint

    # ── Language switching ───────────────────────────────────────
    def retranslateUi(self) -> None:
        """Refresh navigation bar/subtab/export button text after language switching."""
        self._icon_bar.retranslateUi()
        # Refresh the current subtab bar
        subs = self._nav_subs.get(self._current_nav, [])
        self._sub_tabs.set_tabs(subs)
        # export button
        self._export_btn.setText(tr("panel_export_btn"))
        # Mode prompt bar
        self._hint_bar.on_mode_changed(
            list(self._pages.keys())[self._stack.currentIndex()]
            if self._stack.currentIndex() < len(self._pages)
            else "land"
        )

    # ── Slot function ──────────────────────────────────────────
    def _on_nav_changed(self, nav_id: str) -> None:
        """Click on the icon navigation → Update subtab bar + switch to the default submode."""
        self._current_nav = nav_id
        subs = self._nav_subs.get(nav_id, [])
        self._sub_tabs.set_tabs(subs)

        # Switch to the first submode of this nav
        if subs:
            first_sub = subs[0][0]
            self._switch_to_mode(first_sub)

    def _on_sub_mode_changed(self, mode: str) -> None:
        """Subtab switch → switch page + transmit signal."""
        self._switch_to_mode(mode)

    def set_feature_ready(self, mode_id: str, ready: bool) -> None:
        """Set the live readiness dot for a feature sub-tab."""
        self._sub_tabs.set_feature_ready(mode_id, ready)

    def _switch_to_mode(self, mode: str) -> None:
        """Switch to the specified mode_id and update stack, hint, and signal."""
        # Ensure that the subtab bar is displayed (_on_nav_changed may not be called during initialization)
        nav_id = self._sub_to_nav.get(mode, "")
        if nav_id and nav_id != self._current_nav:
            self._current_nav = nav_id
            subs = self._nav_subs.get(nav_id, [])
            self._sub_tabs.set_tabs(subs)
            self._sub_tabs.select_tab(mode)

        idx = self._mode_index.get(mode, 0)
        self._stack.setCurrentIndex(idx)
        # Automatically set tools when switching modes (the user switches the new_land tool independently on the toolbar, regardless of mode)
        if mode not in ("province", "state", "country"):
            self.tool_changed.emit("brush")
        # Trigger mode prompt bar
        self._hint_bar.on_mode_changed(mode)
        self.mode_changed.emit(mode)

    # ── Public method (forwarded to the corresponding page) ────────────────────────
    def update_province_info(
        self, pid: int, ptype: str, terrain: str, pixels: int, coastal: bool
    ) -> None:
        """Update province information panel"""
        self._province_page.update_province_info(pid, ptype, terrain, pixels, coastal)

    def update_state_list(self, states: list[tuple[int, str, int]]) -> None:
        """Refresh the State list"""
        self._state_page.update_state_list(states)

    def update_state_info(self, name: str, manpower: int, category: str) -> None:
        """Populate the State property field"""
        self._state_page.update_state_info(name, manpower, category)

    def select_state_in_list(self, state_id: int) -> None:
        """Selects the row with the specified ID in the State list."""
        from PyQt5.QtCore import Qt
        lst = self._state_page._state_list
        for i in range(lst.count()):
            item = lst.item(i)
            if item and int(item.data(Qt.UserRole) or 0) == state_id:
                lst.blockSignals(True)
                lst.setCurrentRow(i)
                lst.blockSignals(False)
                self._state_page._current_state_id = state_id
                break

    def update_country_list(self, countries: list[tuple[str, str, tuple]]) -> None:
        """Refresh country list"""
        self._country_page.update_country_list(countries)

    def update_country_info(
        self, tag: str, name: str, party: str, color: tuple, capital_name: str
    ) -> None:
        """Populate country attribute fields"""
        self._country_page.update_country_info(tag, name, party, color, capital_name)

    def update_province_gaps(self, gap_ids: list[int]) -> None:
        """Update province ID empty prompt"""
        self._province_page.update_province_gaps(gap_ids)
