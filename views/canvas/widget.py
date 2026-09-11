"""Map canvas component — a large canvas based on QGraphicsView
Supports six editing modes: land/terrain/height/province/state/country
Performance optimization: Partial update of dirty rectangles to avoid rendering the entire map for each operation

Split from ui/canvas_widget.py, retaining the core logic:
- __init__: scene/layer/state initialization
- Data attributes (tile_map, province_map, etc.)
- Render distribution (_full_render / _partial_render)
- Paint operations (_stamp_brush / _paint_at / _flood_fill)
- Transform operations (_apply_transform / _cancel_transform / _end_transform)
- Province operations (merge / split / cleanup)
- Mode/Tool settings
- Navigation aid"""
import numpy as np
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsRectItem,
)
from PyQt5.QtCore import Qt, QPoint, QRectF, QRect, pyqtSignal, QTimer
from PyQt5.QtGui import (
    QImage, QPixmap, QPainter, QColor, QWheelEvent, QMouseEvent,
    QPen, QPainterPath, QBrush, QKeyEvent,
)

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_UNDEFINED, TILE_LAND, TILE_SEA, TILE_LAKE,
    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP,
    BRUSH_DEFAULT,
)
from data.terrain_types import TERRAIN_TYPES, TERRAIN_PALETTE_INDEX, GRAPHICAL_TERRAINS, PALETTE_TO_TYPE
from domain.managers.river import (
    RIVER_DISPLAY_COLORS, RIVER_SOURCE, RIVER_BG_LAND, RIVER_BG_SEA,
    RIVER_ERASE, VALID_RIVER_VALUES,
)

from views.canvas.ref_images import RefImageMixin, RefLayer
from views.canvas.overlays import OverlayMixin, CS_OVERLAY_ALLOWED_MODES
from views.canvas.input_router import InputMixin
from views.canvas.name_labels import NameLabelsMixin


class MapCanvas(InputMixin, OverlayMixin, NameLabelsMixin, RefImageMixin, QGraphicsView):
    """Map canvas, supports zoom/drag/draw, dirty rectangle local update"""

    mouse_moved = pyqtSignal(int, int)
    zoom_changed = pyqtSignal(float)
    province_clicked = pyqtSignal(int)
    province_double_clicked = pyqtSignal(int)   # Double-click the province (set VP)
    province_right_clicked = pyqtSignal(int)    # Right click on the province (set capital)
    province_right_clicked_at = pyqtSignal(int, int, int)  # pid, screen_x, screen_y (for right-click menu)
    provinces_cleared = pyqtSignal()  # Automatically clear provinces when modifying continental mode
    stroke_started = pyqtSignal()     # Brush operation starts
    stroke_ended = pyqtSignal()       # End of brush operation
    ridge_drawn = pyqtSignal(list)    # The mountain line drawing is completed, [(y,x), ...]
    downgrade_lasso_drawn = pyqtSignal(list)  # Selection downgrade lasso completed, [(y,x), ...]
    split_line_drawn = pyqtSignal(int, list)  # Cutting line completed, (pid, [(y,x), ...])
    province_gaps_detected = pyqtSignal(list)  # Province ID empty, [gap_id, ...]

    # Adjust reference image mode
    ref_adjust_exited = pyqtSignal()                    # ESC exit (page button synchronization is unchecked)
    ref_adjust_scale_changed = pyqtSignal(str, float)   # Wheel zoom (target, scale)

    # After generating provinces, draw land and sea → Request MainWindow to pop up the confirmation box (direct signal, synchronous return)
    land_paint_confirm_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Data layer—centrally managed through MapData
        # Private fields are aliases for MapData arrays (pointing to the same numpy object)
        from domain.map_data import MapData
        self._map_data = MapData()
        self._tile_map = self._map_data.tile_map
        self._province_map = self._map_data.province_map
        self._terrain_map = self._map_data.terrain_map
        self._height_map = self._map_data.height_map
        self._river_map = self._map_data.river_map

        # New World Brush Mask: Record which pixels were painted (only those that actually changed from sea/lake to land)
        self.new_land_mask = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=bool)

        # River edit status
        self._current_river_type = RIVER_SOURCE

        # Terrain brush mode: False=per-province (default), True=pixel-by-pixel brush
        self._terrain_brush_mode = False
        self._terrain_brush_size = 20  # Independent terrain brush size, separate from the common _brush_size

        # Height brush: "off" (by province) / "raise" / "lower" / "smooth"
        self._height_brush_mode = "off"
        self._height_brush_size = 30
        self._height_brush_strength = 5  # ±N per brush, do blend strength when smooth

        # display buffer (BGRA)
        self._display_buffer = np.zeros((MAP_HEIGHT, MAP_WIDTH, 4), dtype=np.uint8)
        self._province_border_buffer = None  # Delayed creation

        # Display mode renderer registry: mode → renderer module path (lazy loading and caching)
        from views.canvas.render_registry import DEFAULT_RENDERERS
        self._renderer_paths: dict[str, str] = dict(DEFAULT_RENDERERS)
        self._renderer_cache: dict[str, object] = {}

        # State / Country / Strategic Region / Railway color buffer
        self._state_color_rgb = None   # np.ndarray (H, W, 3) or None
        self._country_color_rgb = None  # np.ndarray (H, W, 3) or None
        # Selected country highlight: country RGB (used for mask matching in country renderer)
        self._highlight_country_rgb: tuple[int, int, int] | None = None
        # Land pixel mask of allocated countries (H, W bool) — Makes the country renderer skip unallocated areas without drawing borders
        self._country_assigned_mask: "np.ndarray | None" = None
        # country boundary cache (to avoid calculating the entire map every time it is redrawn): (rgb_id, assigned_mask_id) → (white, red)
        self._country_borders_cache: tuple | None = None
        # Terrain basemap source: "height" (color height map) or "terrain" (terrain classification map)
        self._terrain_underlay_source: str = "height"
        self._sr_color_rgb = None      # np.ndarray (H, W, 3) or None
        self._railway_color_rgb = None # np.ndarray (H, W, 3) or None
        # Province attribute terrain (gameplay terrain) color buffer
        self._provincial_terrain_color_rgb = None  # np.ndarray (H, W, 3) or None
        # continent color buffer
        self._continent_color_rgb = None  # np.ndarray (H, W, 3) or None

        # display/edit mode
        self._display_mode = "land"

        # Framework tools (new spec): When not None, mouse events are forwarded to it
        self._framework_tool = None     # core.tools.base.Tool instance
        self._framework_ctx = None       # ToolContext

        # Current status
        self._zoom = 1.0
        self._current_tool = "brush"
        self._current_tile_type = TILE_LAND
        self._current_terrain_index = 0
        self._selected_province_id = 0  # Province ID selected in province mode
        self._selected_province_ids: set[int] = set()
        self._selected_province_tile = 0  # The land parcel type of the selected province (only pixels of the same type can be affected during boundary editing)
        self._has_provinces = False     # Whether there is province data (to avoid scanning the entire picture for each transaction)
        self._land_paint_confirmed = False  # After provinces are generated, land and sea are drawn. Has the user confirmed it?
        self._current_height_value = 120
        self._brush_size = BRUSH_DEFAULT
        self._is_drawing = False
        self._is_panning = False
        self._pan_start = QPoint()
        self._space_pressed = False
        self._last_draw_pos = None  # The last drawn position, used for interpolation connections
        self._show_ref_image = True
        self._show_provinces = True

        # Frame selection mode
        self._selection_mode = False
        self._selection_rect = None  # (x0, y0, x1, y1) scene coords
        self._selection_start = None
        self._selection_callback = None  # Callback after frame selection is completed

        # Change tool state
        self._transform_active = False    # Is the transform box activated?
        self._transform_selecting = False # In frame selection stage
        self._transform_box = None       # (x0, y0, x1, y1) current transformation box
        self._transform_snippet = None   # Cut out tile_map fragment (numpy)
        self._transform_orig_box = None  # Original box position
        self._transform_drag = None      # Current drag type: "move"/"tl"/"tr"/"bl"/"br"/"rotate"/None
        self._transform_drag_start = None
        self._transform_angle = 0.0      # Rotation angle (degrees)
        # The target box (x0, y0, x1, y1) written by the last real-time apply; erase it before the next apply.
        # Prevent dragging from leaving a "trail" at every intermediate location (land being copied bug)
        self._transform_last_written_box: tuple[int, int, int, int] | None = None

        # Dirty rectangle (area that needs to be refreshed)
        self._dirty_rect = None  # (x0, y0, x1, y1) or None

        # Delayed rendering timer (merges continuous drawing operations)
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(16)  # ~60fps
        self._render_timer.timeout.connect(self._flush_dirty)

        # Scenes and layers
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, MAP_WIDTH, MAP_HEIGHT)
        self.setScene(self._scene)

        self._map_pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._map_pixmap_item)

        # Original map reference layer (bottom layer)
        self._vanilla_ref_item = QGraphicsPixmapItem()
        self._vanilla_ref_item.setOpacity(0.3)
        self._vanilla_ref_item.setZValue(1)
        self._scene.addItem(self._vanilla_ref_item)

        # User-defined reference layer (upper layer)
        self._ref_pixmap_item = QGraphicsPixmapItem()
        self._ref_pixmap_item.setOpacity(0.4)
        self._ref_pixmap_item.setZValue(2)
        self._scene.addItem(self._ref_pixmap_item)

        # Unified reference layer registry (ref_images.py common interface)
        self._ref_layers = {
            RefImageMixin.REF_VANILLA: RefLayer(self._vanilla_ref_item),
            RefImageMixin.REF_CUSTOM: RefLayer(self._ref_pixmap_item),
        }

        # Adjust reference picture mode: None=off, "custom"/"vanilla"=which picture is being adjusted
        self._ref_adjust_target: str | None = None

        self._province_pixmap_item = QGraphicsPixmapItem()
        self._province_pixmap_item.setOpacity(0.6)
        self._province_pixmap_item.setZValue(2)
        self._scene.addItem(self._province_pixmap_item)

        # Frame selection rectangle (used for functions such as frame selection and magnification)
        self._selection_rect_item = QGraphicsRectItem()
        self._selection_rect_item.setPen(QPen(QColor(255, 255, 0), 2, Qt.DashLine))
        self._selection_rect_item.setBrush(QBrush(QColor(255, 255, 0, 30)))
        self._selection_rect_item.setZValue(100)
        self._selection_rect_item.setVisible(False)
        self._scene.addItem(self._selection_rect_item)

        # Adjust the orange dotted frame of the reference image mode (marking the reference image being dragged)
        self._ref_adjust_border = QGraphicsRectItem()
        self._ref_adjust_border.setPen(QPen(QColor(249, 115, 22), 2, Qt.DashLine))
        self._ref_adjust_border.setBrush(QBrush(Qt.NoBrush))
        self._ref_adjust_border.setZValue(103)
        self._ref_adjust_border.setVisible(False)
        self._scene.addItem(self._ref_adjust_border)

        # Cut preview line
        from PyQt5.QtWidgets import QGraphicsPathItem
        self._split_line_item = QGraphicsPathItem()
        self._split_line_item.setPen(QPen(QColor(255, 80, 80), 2, Qt.SolidLine))
        self._split_line_item.setZValue(102)
        self._split_line_item.setVisible(False)
        self._scene.addItem(self._split_line_item)

        # Transform box (border + 4 corner handles)
        self._transform_border = QGraphicsRectItem()
        self._transform_border.setPen(QPen(QColor(0, 200, 255), 2))
        self._transform_border.setBrush(QBrush(Qt.NoBrush))
        self._transform_border.setZValue(101)
        self._transform_border.setVisible(False)
        self._scene.addItem(self._transform_border)

        self._transform_handles: dict[str, QGraphicsRectItem] = {}
        for hid in ("tl", "tr", "bl", "br"):
            h = QGraphicsRectItem(-4, -4, 8, 8)
            h.setPen(QPen(QColor(0, 200, 255), 1))
            h.setBrush(QBrush(QColor(255, 255, 255)))
            h.setZValue(102)
            h.setVisible(False)
            self._scene.addItem(h)
            self._transform_handles[hid] = h

        # Brush preview cursor (semi-transparent circle)
        self._brush_cursor = QGraphicsEllipseItem()
        self._brush_cursor.setPen(QPen(QColor(255, 255, 255, 180), 1))
        self._brush_cursor.setBrush(QColor(255, 255, 255, 40))
        self._brush_cursor.setZValue(10)
        self._brush_cursor.setVisible(False)
        self._scene.addItem(self._brush_cursor)

        # density overlay
        self._density_overlay_item = QGraphicsPixmapItem()
        self._density_overlay_item.setZValue(5)
        self._density_overlay_item.setVisible(False)
        self._density_overlay_visible = False
        self._scene.addItem(self._density_overlay_item)

        # State boundary overlay (displayed when selecting a state to create a strategic area)
        self._state_border_overlay = QGraphicsPixmapItem()
        self._state_border_overlay.setZValue(6)
        self._state_border_overlay.setVisible(False)
        self._scene.addItem(self._state_border_overlay)

        # Country/state overlay in terrain view (translucent country color + white state borders)
        self._terrain_context_overlay = QGraphicsPixmapItem()
        self._terrain_context_overlay.setZValue(6)
        self._terrain_context_overlay.setVisible(False)
        self._scene.addItem(self._terrain_context_overlay)
        self._terrain_context_visible = False
        self._terrain_ctx_country_mgr = None
        self._terrain_ctx_state_mgr = None

        # Terrain basemap overlay in State / Country mode (use heightmap color map as reference)
        self._terrain_underlay_item = QGraphicsPixmapItem()
        self._terrain_underlay_item.setZValue(5)
        self._terrain_underlay_item.setVisible(False)
        self._terrain_underlay_item.setOpacity(0.4)
        self._scene.addItem(self._terrain_underlay_item)
        self._terrain_underlay_visible = False
        self._terrain_underlay_opacity = 0.4

        # Lasso path feedback (yellow dashed line)
        self._lasso_path_item = QGraphicsPathItem()
        pen = QPen(QColor(255, 230, 0, 230), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCosmetic(True)  # Does not change thickness with scaling
        self._lasso_path_item.setPen(pen)
        self._lasso_path_item.setZValue(11)
        self._lasso_path_item.setVisible(False)
        self._scene.addItem(self._lasso_path_item)

        # Mountain line drawing path feedback (red solid line, thicker than the lasso)
        self._ridge_path_item = QGraphicsPathItem()
        ridge_pen = QPen(QColor(230, 60, 60, 240), 3)
        ridge_pen.setStyle(Qt.PenStyle.SolidLine)
        ridge_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        ridge_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        ridge_pen.setCosmetic(True)
        self._ridge_path_item.setPen(ridge_pen)
        self._ridge_path_item.setZValue(12)
        self._ridge_path_item.setVisible(False)
        self._scene.addItem(self._ridge_path_item)

        # Lasso allowed area overlay (translucent yellow fill)
        self._lasso_overlay = QGraphicsPixmapItem()
        self._lasso_overlay.setZValue(9)
        self._lasso_overlay.setVisible(False)
        self._scene.addItem(self._lasso_overlay)

        # Local refinement lasso preview (blue dashed polygon)
        self._refine_lasso_item = QGraphicsPathItem()
        refine_pen = QPen(QColor(80, 150, 255, 240), 2)
        refine_pen.setStyle(Qt.PenStyle.DashLine)
        refine_pen.setCosmetic(True)
        self._refine_lasso_item.setPen(refine_pen)
        self._refine_lasso_item.setZValue(12)
        self._refine_lasso_item.setVisible(False)
        self._scene.addItem(self._refine_lasso_item)

        # VP Marker Overlay (Feature 10)
        self._vp_overlay_item = QGraphicsPixmapItem()
        self._vp_overlay_item.setZValue(5)
        self._vp_overlay_item.setVisible(False)
        self._scene.addItem(self._vp_overlay_item)
        self._vp_data: dict[int, int] = {}  # {province_id: vp_value}
        # Terrain editors opt in to the VP overlay independently. State and
        # province display modes retain their existing always-visible behavior.
        self._vp_overlay_mode_visibility: dict[str, bool] = {
            "terrain": False,
            "province_terrain": False,
        }

        # Name tag overlay (showing names in state/country mode)
        self._init_name_labels()

        # View settings
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setStyleSheet("background: #050a12; border: none;")

        # Initial full rendering
        self._full_render()

    # ========== Dynamic map size ==========

    @property
    def map_h(self) -> int:
        return self._display_buffer.shape[0]

    @property
    def map_w(self) -> int:
        return self._display_buffer.shape[1]

    # ========== Data Access ==========

    def set_map_data(self, map_data) -> None:
        """Replaces the underlying MapData and rebinds all local aliases.

        Timing of calling: after MainWindow initialization/new project/loading project,
        Let canvas and project share the same MapData instance,
        In this way, when the controller modifies the array of project.map_data through Command,
        canvas can also see changes immediately."""
        self._map_data = map_data
        self._tile_map = map_data.tile_map
        self._province_map = map_data.province_map
        self._terrain_map = map_data.terrain_map
        self._height_map = map_data.height_map
        self._river_map = map_data.river_map
        self._has_provinces = int(self._province_map.max()) > 0
        self._selected_province_id = 0
        self._selected_province_ids.clear()
        self._selected_province_tile = 0
        self._land_paint_confirmed = False  # New data → Drawing land and sea reconfirmation
        # clear all cache
        self._border_cache = None
        if hasattr(self, '_border_base_pixmap'):
            self._border_base_pixmap = None
        self._state_color_rgb = None
        self._country_color_rgb = None
        self._sr_color_rgb = None
        self._railway_color_rgb = None
        self._provincial_terrain_color_rgb = None
        self._continent_color_rgb = None
        self.clear_name_labels()  # The old label coordinates will be invalidated along with the map.
        h, w = map_data.tile_map.shape[0], map_data.tile_map.shape[1]
        self.new_land_mask = np.zeros((h, w), dtype=bool)
        self._display_buffer = np.zeros((h, w, 4), dtype=np.uint8)
        self._scene.setSceneRect(0, 0, w, h)
        # map_data has been changed, the pixmap size of the terrain context overlay does not match, rebuild
        if getattr(self, '_terrain_context_visible', False):
            self.refresh_terrain_context_overlay()
        # The same goes for terrain basemaps — follow heightmap
        if getattr(self, '_terrain_underlay_visible', False):
            self.refresh_terrain_underlay()

    @property
    def map_data(self):
        """Expose MapData to external users using advanced query methods (get_neighbors, etc.)."""
        return self._map_data

    def set_framework_tool(self, tool_name: str | None, undo_mgr=None,
                            state_mgr=None, country_mgr=None) -> None:
        """Enable/disable a framework tool. tool_name=None is off."""
        from domain.tools import get_tool, ToolContext

        if tool_name is None:
            if self._framework_tool is not None and self._framework_ctx is not None:
                self._framework_tool.on_cancel(self._framework_ctx)
            self._framework_tool = None
            self._framework_ctx = None
            self._clear_lasso_visual()
            self._render_province_overlay()
            return

        tool = get_tool(tool_name)
        if tool is None:
            return
        if undo_mgr is None:
            return
        self._framework_tool = tool
        self._framework_ctx = ToolContext(
            map_data=self._map_data,
            undo_mgr=undo_mgr,
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            display_mode=self._display_mode,
            brush_size=self._brush_size,
        )

    def configure_province_paint(
        self, mode: str, brush_size: int, pid: int = 0, tile_type: int = 0
    ) -> bool:
        """Configure the active manual province tool and its paint target."""
        if (self._framework_tool is None
                or self._framework_tool.name != "province_paint"
                or self._framework_ctx is None):
            return False
        kwargs = {"mode": mode, "brush_size": brush_size}
        if pid > 0:
            kwargs["pid"] = pid
            kwargs["tile_type"] = tile_type
        self._framework_tool.configure(self._framework_ctx, **kwargs)
        self._refresh_brush_cursor()
        return True

    def set_province_paint_brush_size(self, size: int) -> None:
        """Update the manual province brush without reselecting its target."""
        size = max(1, min(100, int(size)))
        if (self._framework_tool is not None
                and self._framework_tool.name == "province_paint"
                and self._framework_ctx is not None):
            self._framework_ctx.brush_size = size
            self._refresh_brush_cursor()

    def begin_new_manual_province(self) -> int:
        """Allocate and select a new province ID for the next paint stroke."""
        if (self._framework_tool is None
                or self._framework_tool.name != "province_paint"
                or self._framework_ctx is None):
            return 0
        pid = self._framework_tool.begin_new_province(self._framework_ctx)
        self._selected_province_id = pid
        self._selected_province_ids = {pid} if pid > 0 else set()
        self._selected_province_tile = 0
        self._render_province_overlay()
        return pid

    def select_province(
        self, pid: int, tile_type: int | None = None, additive: bool = False
    ) -> set[int]:
        """Select a province, optionally adding it to the current selection."""
        pid = int(pid)
        if pid <= 0:
            self._selected_province_id = 0
            self._selected_province_ids.clear()
            self._selected_province_tile = 0
            return set()

        if additive:
            self._selected_province_ids.add(pid)
        else:
            self._selected_province_ids = {pid}
        self._selected_province_id = pid
        if tile_type is not None:
            self._selected_province_tile = int(tile_type)
        return set(self._selected_province_ids)

    def selected_province_ids(self) -> set[int]:
        """Return the selection while remaining compatible with legacy setters."""
        if self._selected_province_id <= 0:
            self._selected_province_ids.clear()
        elif self._selected_province_id not in self._selected_province_ids:
            self._selected_province_ids = {self._selected_province_id}
        return set(self._selected_province_ids)

    def _set_layer(self, attr: str, data: np.ndarray, dtype) -> None:
        """Unified layer replacement: writing to MapData, synchronizing local aliases.

        If the shape is the same, write it in place to keep the reference stable (the reference held by the controller/command will not be invalidated).
        The entire array is only replaced when the shape is different (the map size changes)."""
        existing = getattr(self._map_data, attr, None)
        if existing is not None and existing.shape == data.shape:
            existing[:] = data.astype(dtype)
            # The alias still points to the same object and does not need to be updated
        else:
            new_arr = data.astype(dtype)
            setattr(self._map_data, attr, new_arr)
            setattr(self, "_" + attr, new_arr)
            # When the map size changes, synchronize display_buffer and scene rect
            h, w = new_arr.shape[:2]
            if (h, w) != (self._display_buffer.shape[0], self._display_buffer.shape[1]):
                self._display_buffer = np.zeros((h, w, 4), dtype=np.uint8)
                self._scene.setSceneRect(0, 0, w, h)

    def _rebind_aliases(self) -> None:
        """Rebind the local alias to the current MapData property.

        When Command or external code replaces a property of MapData (rather than modifying it in place),
        Local aliases such as canvas's _tile_map will expire. Call this method to refresh."""
        self._tile_map = self._map_data.tile_map
        self._province_map = self._map_data.province_map
        self._terrain_map = self._map_data.terrain_map
        self._height_map = self._map_data.height_map
        self._river_map = self._map_data.river_map

    @property
    def tile_map(self) -> np.ndarray:
        return self._tile_map

    @tile_map.setter
    def tile_map(self, data: np.ndarray) -> None:
        self._set_layer("tile_map", data, np.uint8)
        if self._display_mode == "land":
            self._full_render()

    @property
    def province_map(self) -> np.ndarray:
        return self._province_map

    @province_map.setter
    def province_map(self, data: np.ndarray) -> None:
        self._set_layer("province_map", data, np.int32)
        self._has_provinces = int(self._province_map.max()) > 0
        self._land_paint_confirmed = False  # Provinces are regenerated → borders are realigned, and land and sea are re-confirmed next time.
        # The province data has changed. Clear the boundary cache so that it can be rebuilt next time.
        self._border_cache = None
        if hasattr(self, '_border_base_pixmap'):
            self._border_base_pixmap = None
        if self._display_mode == "province":
            self._full_render()
        self._render_province_overlay()
        # The country/state overlay pixmap size and content of the terrain view must be reconstructed according to the province map
        if getattr(self, '_terrain_context_visible', False):
            self.refresh_terrain_context_overlay()
        if getattr(self, '_terrain_underlay_visible', False):
            self.refresh_terrain_underlay()

    @property
    def terrain_map(self) -> np.ndarray:
        return self._terrain_map

    @terrain_map.setter
    def terrain_map(self, data: np.ndarray) -> None:
        self._set_layer("terrain_map", data, np.uint8)
        if self._display_mode == "terrain":
            self._full_render()

    @property
    def height_map(self) -> np.ndarray:
        return self._height_map

    @height_map.setter
    def height_map(self, data: np.ndarray) -> None:
        self._set_layer("height_map", data, np.uint8)
        if self._display_mode == "height":
            self._full_render()

    @property
    def river_map(self) -> np.ndarray:
        return self._river_map

    @river_map.setter
    def river_map(self, data: np.ndarray) -> None:
        self._set_layer("river_map", data, np.uint8)
        if self._display_mode == "river":
            self._full_render()

    def set_river_type(self, river_type: int) -> None:
        self._current_river_type = max(0, min(255, river_type))

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @display_mode.setter
    def display_mode(self, mode: str) -> None:
        _VALID = (
            "land", "terrain", "height", "province",
            "state", "country", "river", "logistics",
            "continent", "strategic_region", "colormap", "default_map",
            "province_terrain", "preview",
        )
        if mode not in _VALID:
            return
        if mode == self._display_mode:
            return
        self._display_mode = mode
        # The preview is a textured composite: the zoomed display must be sampled smoothly, otherwise nearest neighbor sampling will
        # Texture details are broken into noise (looking blurry). Edit mode maintains pixel hard edges for precise manipulation.
        self.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, mode == "preview")
        # Country/state attribution overlay — a global switch that only displays in modes where the base view itself is not colored by country/state,
        # Avoid confusion caused by double-coloring in state/country/continent/strategic_region mode.
        overlay = getattr(self, '_terrain_context_overlay', None)
        if overlay is not None:
            if getattr(self, '_terrain_context_visible', False) \
                    and mode in CS_OVERLAY_ALLOWED_MODES:
                self.refresh_terrain_context_overlay()
            else:
                overlay.setVisible(False)
        # Topographic basemaps are only displayed in state/country mode
        underlay = getattr(self, '_terrain_underlay_item', None)
        if underlay is not None:
            if getattr(self, '_terrain_underlay_visible', False) and mode in ("state", "country"):
                self.refresh_terrain_underlay()
            else:
                underlay.setVisible(False)
        self._full_render()
        # Logistics mode no longer requires overlay (uses shaded map instead)
        if mode != "logistics" and self._lasso_overlay.isVisible():
            # Exit logistics mode: clear logistics overlay (but the overlay of lasso/batch selection will be managed elsewhere)
            # It is only cleared when it is not in the state of batch selection etc.
            pass  # Don't move for now and let set_batch_selection_pids etc. manage it.

    # ========== Tool Settings ==========

    def set_tool(self, tool: str) -> None:
        self._current_tool = tool
        self.setCursor(Qt.CursorShape.OpenHandCursor if tool == "pan"
                       else Qt.CursorShape.CrossCursor)

    def set_tile_type(self, tile_type: int) -> None:
        self._current_tile_type = tile_type

    def set_brush_size(self, size: int) -> None:
        self._brush_size = max(1, min(100, size))
        self._refresh_brush_cursor()

    def set_terrain_index(self, index: int) -> None:
        self._current_terrain_index = max(0, min(255, index))

    def set_terrain_brush_mode(self, brush_mode: bool) -> None:
        """Toggle terrain editing mode: True=brush-by-pixel, False=by-province (default)"""
        self._terrain_brush_mode = brush_mode

    def set_terrain_brush_size(self, size: int) -> None:
        """Terrain brush size (decoupled from universal brushes)."""
        self._terrain_brush_size = max(1, min(200, int(size)))
        self._refresh_brush_cursor()

    def set_height_value(self, value: int) -> None:
        self._current_height_value = max(0, min(255, value))

    def set_height_brush_mode(self, mode: str) -> None:
        """Height brush modes: 'off' / 'raise' / 'lower' / 'smooth'."""
        if mode not in ("off", "raise", "lower", "smooth"):
            mode = "off"
        self._height_brush_mode = mode
        self.setCursor(Qt.CursorShape.CrossCursor if mode != "off"
                       else Qt.CursorShape.ArrowCursor)

    def set_height_brush_size(self, size: int) -> None:
        self._height_brush_size = max(1, min(400, int(size)))
        self._refresh_brush_cursor()

    def set_density_brush_size(self, size: int) -> None:
        self._density_brush_size = max(1, min(200, int(size)))
        self._refresh_brush_cursor()

    def _confirm_land_paint(self) -> bool:
        """When provinces have been generated, ask the user to confirm once before drawing land and sea (the boundaries will be misaligned, and provinces need to be regenerated).

        Let MainWindow pop up the modal box through direct connection signal, and return _land_paint_confirmed
        has been written. After confirming once, you will not be asked again in this session; if you cancel, the drawing will not be done and you will be asked again next time."""
        if self._display_mode != "land" or self._land_paint_confirmed:
            return True
        if not self._has_provinces:
            return True
        self.land_paint_confirm_requested.emit()
        return self._land_paint_confirmed

    def set_height_brush_strength(self, strength: int) -> None:
        self._height_brush_strength = max(1, min(50, int(strength)))

    # ========== State / Country Color Settings ==========

    def set_state_colors(self, rgb: np.ndarray) -> None:
        """Store State color RGB array and trigger rendering"""
        self._state_color_rgb = rgb
        if self._display_mode == "state":
            self._full_render()

    def set_country_colors(self, rgb: np.ndarray, assigned_mask=None) -> None:
        """Stores Country color RGB array + assigned country pixel mask, triggers rendering.

        assigned_mask: H×W bool, True = The pixel belongs to the land of the assigned country
            (False in ocean/unallocated state, country renderer does not draw white edges on these borders)."""
        self._country_color_rgb = rgb
        self._country_assigned_mask = assigned_mask
        # rgb changed → country renderer border cache and state renderer country border cache are invalid
        self._country_borders_cache = None
        self._state_country_borders_cache = None
        # The political view in the preview is superimposed with the national color → it will be disabled altogether.
        self._preview_political_cache = None
        # The state mode also superimposes national borders → needs to be refreshed when changing country ownership
        if self._display_mode in ("country", "state"):
            self._full_render()

    def set_highlight_country(self, rgb: tuple[int, int, int] | None) -> None:
        """Sets the RGB of the selected country.

        In country mode: The country's borders are outlined in 2 pixels red.
        In state mode: all the pixels in the country are superimposed in warm yellow, and you can see at a glance which other states have the same owner.
        Pass None to cancel."""
        self._highlight_country_rgb = rgb
        # Highlighting does not affect the country border cache, only redrawing
        if self._display_mode in ("country", "state"):
            self._full_render()

    def set_terrain_underlay_visible(self, visible: bool) -> None:
        """Toggle terrain basemap overlay in state/country mode."""
        self._terrain_underlay_visible = bool(visible)
        self.refresh_terrain_underlay()

    def set_terrain_underlay_opacity(self, opacity: float) -> None:
        """Set the terrain basemap opacity (0.0 fully transparent ~ 1.0 fully opaque)."""
        self._terrain_underlay_opacity = max(0.0, min(1.0, float(opacity)))
        item = getattr(self, "_terrain_underlay_item", None)
        if item is not None:
            item.setOpacity(self._terrain_underlay_opacity)

    def set_terrain_underlay_source(self, source: str) -> None:
        """Toggle terrain basemap source: 'height' (color heightmap) or 'terrain' (terrain classification map)."""
        if source not in ("height", "terrain"):
            return
        self._terrain_underlay_source = source
        self.refresh_terrain_underlay()

    def set_sr_colors(self, rgb: np.ndarray) -> None:
        """Store Strategic Region color RGB array and trigger rendering"""
        self._sr_color_rgb = rgb
        if self._display_mode == "strategic_region":
            self._full_render()

    def set_railway_colors(self, rgb: np.ndarray) -> None:
        """Store rail grade color RGB array and trigger rendering"""
        self._railway_color_rgb = rgb
        if self._display_mode == "logistics":
            self._full_render()

    def set_provincial_terrain_colors(self, rgb: np.ndarray) -> None:
        """Store province attribute terrain RGB array and trigger rendering"""
        self._provincial_terrain_color_rgb = rgb
        if self._display_mode == "province_terrain":
            self._full_render()

    def set_continent_colors(self, rgb: np.ndarray) -> None:
        """Store continent color RGB array and trigger rendering"""
        self._continent_color_rgb = rgb
        if self._display_mode == "continent":
            self._full_render()

    def set_batch_selection_pids(self, pids: list[int]) -> None:
        """Highlight provinces selected in batches (used for creating state/country and other scenarios).

        Clear the highlight when pids is empty. Use a translucent yellow overlay."""
        from PyQt5.QtGui import QImage, QPixmap
        if not pids or self._province_map is None:
            self._lasso_overlay.setVisible(False)
            return
        mask = np.isin(self._province_map, list(pids))
        h, w = self._province_map.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        # Translucent bright yellow (BGRA byte order: B=0, G=220, R=255, A=160)
        rgba[mask] = (0, 220, 255, 160)
        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba  # Prevent memory from being freed
        self._lasso_overlay.setPixmap(QPixmap.fromImage(img))
        self._lasso_overlay.setVisible(True)

    def refresh_logistics_overlay(self) -> None:
        """Draw supply nodes and railway overlay in logistics mode (draw on _lasso_overlay).

        Supply node: small green circle, radius=3+level
        Railway: colored lines (level 1=fine gray / level 5=thick red), line width = 1+level"""
        from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QPen
        if self._province_map is None:
            self._lasso_overlay.setVisible(False)
            return

        pm = self._province_map
        tm = self._tile_map
        h, w = pm.shape

        # Get managers (hanging on the canvas instance)
        supply_mgr = getattr(self, '_supply_mgr', None)
        railway_mgr = getattr(self, '_railway_mgr', None)
        if supply_mgr is None and railway_mgr is None:
            self._lasso_overlay.setVisible(False)
            return

        # Precompute province centroid (used for drawing nodes/lines)
        max_pid = int(pm.max())
        if max_pid <= 0:
            return
        flat = pm.ravel()
        pid_count = np.bincount(flat, minlength=max_pid + 1)
        ys_grid, xs_grid = np.mgrid[0:h, 0:w]
        sum_y = np.bincount(flat, weights=ys_grid.ravel().astype(np.float64), minlength=max_pid + 1)
        sum_x = np.bincount(flat, weights=xs_grid.ravel().astype(np.float64), minlength=max_pid + 1)

        # Use QPainter to draw on transparent QImage
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(0)  # Fully transparent
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Railroad lines (levels 1-5 gray to red, thickness 2 to 6)
        RAIL_COLORS = {
            1: QColor(120, 120, 140, 200),  # gray
            2: QColor(100, 160, 100, 210),  # dark green
            3: QColor(230, 180, 60, 220),   # golden
            4: QColor(230, 130, 60, 230),   # Orange
            5: QColor(230, 60, 60, 240),    # Red (highest grade)
        }
        # Railway lines: only draw line segments between land provinces and skip maritime provinces (to avoid flying lines across the sea)
        if railway_mgr is not None:
            from data.constants import TILE_LAND
            for entry in railway_mgr._entries:
                lvl = entry.level
                color = RAIL_COLORS.get(lvl, RAIL_COLORS[1])
                pen = QPen(color, 1 + lvl)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                pts = []
                for pid in entry.province_ids:
                    if 0 < pid <= max_pid and pid_count[pid] > 0:
                        # Check if province is land (skip ocean/lake provinces)
                        cy_idx = int(sum_y[pid] / pid_count[pid])
                        cx_idx = int(sum_x[pid] / pid_count[pid])
                        cy_idx = min(cy_idx, h - 1)
                        cx_idx = min(cx_idx, w - 1)
                        if tm is not None and int(tm[cy_idx, cx_idx]) != TILE_LAND:
                            # Maritime Provinces → Disconnect line segment (restart later)
                            pts.append(None)
                            continue
                        pts.append((sum_x[pid] / pid_count[pid], sum_y[pid] / pid_count[pid]))
                # Draw a line segment and break when None is encountered
                for i in range(len(pts) - 1):
                    if pts[i] is None or pts[i + 1] is None:
                        continue
                    x1, y1 = pts[i]
                    x2, y2 = pts[i + 1]
                    # Skipping too long line segments (cross-ocean connection > 200px)
                    if abs(x1 - x2) > 200 or abs(y1 - y2) > 200:
                        continue
                    painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # Straits/adjacencies — not drawn in the logistic overlay (too many would be cluttered), only managed in the adjacencies dialog
        # Can be rendered separately while the adjacency dialog is open if desired

        # Supply nodes (diamond + cross sign, HOI4 style)
        if supply_mgr is not None:
            from PyQt5.QtCore import QPointF
            from PyQt5.QtGui import QPolygonF
            for pid, node in supply_mgr._nodes.items():
                if 0 < pid <= max_pid and pid_count[pid] > 0:
                    cx = int(sum_x[pid] / pid_count[pid])
                    cy = int(sum_y[pid] / pid_count[pid])
                    r = 4  # rhombus radius
                    diamond = QPolygonF([
                        QPointF(cx, cy - r),
                        QPointF(cx + r, cy),
                        QPointF(cx, cy + r),
                        QPointF(cx - r, cy),
                    ])
                    painter.setPen(QPen(QColor(0, 0, 0, 230), 1))
                    painter.setBrush(QColor(60, 200, 60, 240))
                    painter.drawPolygon(diamond)
                    # white cross
                    painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
                    painter.drawLine(cx - 2, cy, cx + 2, cy)
                    painter.drawLine(cx, cy - 2, cx, cy + 2)

        painter.end()
        self._lasso_overlay.setPixmap(QPixmap.fromImage(img))
        self._lasso_overlay.setVisible(True)

    # ──Transform Tool──

    def _apply_transform(self) -> None:
        """Write the transformation results (scale + rotation) to tile_map."""
        if self._transform_snippet is None or self._transform_box is None:
            return

        from scipy.ndimage import zoom, rotate

        x0, y0, x1, y1 = [int(v) for v in self._transform_box]
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(self.map_w, x1); y1 = min(self.map_h, y1)
        tw, th = x1 - x0, y1 - y0
        if tw < 2 or th < 2:
            return

        # 1. Scale snippet to target size
        src_h, src_w = self._transform_snippet.shape
        zy = th / src_h
        zx = tw / src_w
        scaled = zoom(self._transform_snippet.astype(np.float32), (zy, zx), order=0)
        scaled = np.round(scaled).astype(np.uint8)

        # 2. Rotation (if there is an angle)
        if abs(self._transform_angle) > 0.5:
            # cval=TILE_SEA fills the empty space after rotation
            rotated = rotate(scaled.astype(np.float32), -self._transform_angle,
                             reshape=False, order=0, cval=float(TILE_SEA))
            scaled = np.round(rotated).astype(np.uint8)

        # 3. Clear the old transformation area first, and then write
        # Clear the entire potentially affected area
        ox0, oy0, ox1, oy1 = self._transform_orig_box
        self._tile_map[oy0:oy1, ox0:ox1] = TILE_SEA  # clear original position
        # Erase the location where the last real-time apply was written - fix the "drag leaves copy traces" bug
        if self._transform_last_written_box is not None:
            lx0, ly0, lx1, ly1 = self._transform_last_written_box
            self._tile_map[ly0:ly1, lx0:lx1] = TILE_SEA
        # Also clear the current frame position (may be contaminated by the last preview)
        self._tile_map[y0:y1, x0:x1] = TILE_SEA

        # write
        sh, sw = scaled.shape
        ph = min(sh, y1 - y0)
        pw = min(sw, x1 - x0)
        self._tile_map[y0:y0 + ph, x0:x0 + pw] = scaled[:ph, :pw]
        self._transform_last_written_box = (x0, y0, x0 + pw, y0 + ph)
        # _tile_map and _map_data.tile_map are the same array, no additional synchronization is required
        self._full_render()

    def _cancel_transform(self) -> None:
        """Cancel the transformation and restore the original state."""
        if self._transform_snippet is not None and self._transform_orig_box is not None:
            # First erase the content left on the canvas by a real-time apply — otherwise there will still be "copy" residue when ESC cancels
            if self._transform_last_written_box is not None:
                lx0, ly0, lx1, ly1 = self._transform_last_written_box
                self._tile_map[ly0:ly1, lx0:lx1] = TILE_SEA
            # Restore original clip to original position
            ox0, oy0, ox1, oy1 = self._transform_orig_box
            self._tile_map[oy0:oy1, ox0:ox1] = self._transform_snippet
            # _tile_map and _map_data.tile_map are the same array, no additional synchronization is required
            self._full_render()
        self._end_transform()

    def _end_transform(self) -> None:
        """Clean up transform state."""
        self._transform_active = False
        self._transform_selecting = False
        self._transform_box = None
        self._transform_snippet = None
        self._transform_orig_box = None
        self._transform_drag = None
        self._transform_angle = 0.0
        self._transform_last_written_box = None
        self._update_transform_visuals()

    # ── Frame selection mode ──

    def start_selection_mode(self, callback) -> None:
        """Enter box selection mode. Callback(x0, y0, x1, y1) is called after the user drags out the rectangle."""
        self._selection_mode = True
        self._selection_callback = callback
        self._selection_rect_item.setVisible(False)
        self.setCursor(Qt.CrossCursor)

    def _finish_selection(self) -> None:
        """When the frame selection is completed, the callback is called."""
        self._selection_mode = False
        self._selection_rect_item.setVisible(False)
        self.setCursor(Qt.CursorShape.CrossCursor)
        if self._selection_rect and self._selection_callback:
            x0, y0, x1, y1 = self._selection_rect
            if x1 > x0 + 5 and y1 > y0 + 5:  # Minimum 5px
                self._selection_callback(x0, y0, x1, y1)
        self._selection_rect = None
        self._selection_callback = None

    # ========== Rendering (Performance Core) ==========

    def register_renderer(self, mode: str, module_path: str) -> None:
        """Register/override a renderer module for display modes (runtime extension points, such as preview mode).

        For the renderer module convention, see views/canvas/render_registry.py module description."""
        self._renderer_paths[mode] = module_path
        self._renderer_cache.pop(mode, None)

    def _resolve_renderer(self, mode: str):
        """Get the renderer module by mode. Unregistered modes fall back to land; defer import and cache."""
        if mode not in self._renderer_cache:
            import importlib
            path = self._renderer_paths.get(mode) or self._renderer_paths["land"]
            self._renderer_cache[mode] = importlib.import_module(path)
        return self._renderer_cache[mode]

    def _full_render(self) -> None:
        """Fully render the entire map into the display buffer (according to the current mode)"""
        self._resolve_renderer(self._display_mode).render(self)
        self._update_pixmap_from_buffer()
        # VP overlay visibility toggle (no redraw, use cache)
        self._update_vp_visibility()
        # Show and hide name tags (state/country mode)
        self._update_name_labels_visibility()
        # Density overlay: The display is managed by app_controller. Only the content is refreshed here.
        if getattr(self, '_density_overlay_visible', False):
            self._render_density_overlay()

    def _partial_render(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Partially render a specified rectangular area (according to the current mode)"""
        renderer = self._resolve_renderer(self._display_mode)
        partial = getattr(renderer, "partial_render", None)
        if partial is None:
            # This renderer does not support partial rendering (whole image synthesis class, such as preview) → fallback to full rendering
            self._full_render()
            return
        partial(self, x0, y0, x1, y1)
        self._update_pixmap_from_buffer()

    # ---------- General rendering assistance ----------

    def _update_pixmap_from_buffer(self) -> None:
        """Write display buffer to QPixmap"""
        img = QImage(self._display_buffer.data, self.map_w, self.map_h,
                     self.map_w * 4, QImage.Format.Format_RGB32)
        img._ref = self._display_buffer  # Prevent GC
        self._map_pixmap_item.setPixmap(QPixmap.fromImage(img))

    def _cleanup_after_province_edit(self) -> None:
        """Security cleanup after boundary editing:
        1. Fix possible X-crossings
        2. Repair possible disconnected fragments (border editing may cut the other province in half)
        3. Compact ID (to prevent a province from being pushed to 0 pixels and leaving a gap after disappearing)
        4. Maintain the selected province ID to still point to the correct province after compaction"""
        from domain.validators.province import fix_x_crossings
        from domain.generators.province import _fix_non_contiguous_fast, compact_province_ids

        old_sel = self._selected_province_id

        # 1. X-crossings
        for _ in range(5):
            if fix_x_crossings(self._province_map) == 0:
                break

        # 2. Disconnected fragments
        _fix_non_contiguous_fast(self._province_map)

        # 3. Before compaction, record whether selected still exists
        sel_existed = bool((self._province_map == old_sel).any()) if old_sel > 0 else False

        # 4. Compact ID (use mapping table to track selected new ID)
        if old_sel > 0 and sel_existed:
            unique_before = np.unique(self._province_map)
            compact_province_ids(self._province_map)
            unique_after = np.unique(self._province_map)
            # Find the new ID of old_sel after compaction
            old_list = unique_before.tolist()
            new_list = unique_after.tolist()
            if old_sel in old_list:
                idx = old_list.index(old_sel)
                self._selected_province_id = int(new_list[idx])
        else:
            compact_province_ids(self._province_map)
            if not sel_existed:
                # The selected province was pushed away
                self._selected_province_id = 0
        self._selected_province_ids = (
            {self._selected_province_id}
            if self._selected_province_id > 0
            else set()
        )

    def center_on_pixel(self, x: int, y: int, zoom: float | None = None) -> None:
        """Center the canvas at map coordinates (x, y), optionally zooming in to zoom times.
        Used to verify that the dialog box jumps to the location of the problem."""
        if not (0 <= x < self.map_w and 0 <= y < self.map_h):
            return
        if zoom is not None:
            self.resetTransform()
            self.scale(zoom, zoom)
        self.centerOn(float(x), float(y))

    def center_on_province(self, pid: int) -> None:
        """Jump to the center of the specified province and select it"""
        if pid <= 0 or pid > self._province_map.max():
            return
        ys, xs = np.where(self._province_map == pid)
        if len(ys) == 0:
            return
        cx = int(xs.mean())
        cy = int(ys.mean())
        self._selected_province_id = pid
        self._selected_province_ids = {pid}
        self._selected_province_tile = int(self._tile_map[cy, cx])
        self._render_province_overlay()
        self.center_on_pixel(cx, cy, zoom=2.0)

    def split_province(self, pid: int) -> bool:
        """Cut province: Divide a province into two halves along the center line, and use a new ID for the new half."""
        if pid <= 0:
            return False
        mask = self._province_map == pid
        ys, xs = np.where(mask)
        if len(ys) < 2:
            return False

        # Cut along the midline of the longer axis
        y_range = ys.max() - ys.min()
        x_range = xs.max() - xs.min()
        new_id = int(self._province_map.max()) + 1

        if x_range >= y_range:
            # Wider horizontally, cut along the x centerline
            mid_x = (xs.min() + xs.max()) // 2
            right_half = mask & (np.arange(self.map_w)[np.newaxis, :] > mid_x)
        else:
            # Higher vertically, tangent along the y midline
            mid_y = (ys.min() + ys.max()) // 2
            right_half = mask & (np.arange(self.map_h)[:, np.newaxis] > mid_y)

        if not np.any(right_half):
            return False

        self._province_map[right_half] = new_id
        self._full_render()
        self._render_province_overlay()
        return True

    def refresh_display(self) -> None:
        self._has_provinces = int(self._province_map.max()) > 0
        self._border_cache = None
        if hasattr(self, '_border_base_pixmap'):
            self._border_base_pixmap = None
        self._full_render()
        self._render_province_overlay()

    # ========== Dirty Rectangle System ==========

    def _mark_dirty(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Mark dirty areas and merge multiple draws"""
        if self._dirty_rect is None:
            self._dirty_rect = (x0, y0, x1, y1)
        else:
            dx0, dy0, dx1, dy1 = self._dirty_rect
            self._dirty_rect = (min(dx0, x0), min(dy0, y0), max(dx1, x1), max(dy1, y1))
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush_dirty(self) -> None:
        """Refresh dirty areas"""
        if self._dirty_rect is None:
            return
        x0, y0, x1, y1 = self._dirty_rect
        self._dirty_rect = None
        self._partial_render(x0, y0, x1, y1)

    # ========== Drawing operations ==========

    def _stamp_brush(self, cx: int, cy: int) -> None:
        """Stamp a circular brush seal in a single location (according to the current mode)"""
        import numpy as np

        # Province mode: fixed 1 pixel, does not depend on brush size (border editing needs to be precise)
        if self._display_mode == "province":
            r = 0
        elif self._display_mode == "river" and self._current_tool != "eraser":
            # River brush is forced to 1px (HOI4 rivers must be 1 pixel wide), the size slider only works on the eraser
            r = 0
        else:
            r = self._brush_size // 2
        x0 = max(0, cx - r)
        y0 = max(0, cy - r)
        x1 = min(self.map_w, cx + r + 1)
        y1 = min(self.map_h, cy + r + 1)
        if x0 >= x1 or y0 >= y1:
            return

        # Construct a circular mask (use circle when r >= 2, not needed for small brushes)
        if r >= 2:
            yy, xx = np.ogrid[y0:y1, x0:x1]
            circle = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
        else:
            circle = None  # Small brushes directly cover the whole area

        mode = self._display_mode

        if mode == "land":
            # Density brush mode (when density mask is on)
            if getattr(self, '_density_overlay_visible', False):
                dm = getattr(self._map_data, 'density_map', None) if self._map_data else None
                if dm is not None:
                    # Dedicate brush size with density
                    dr = getattr(self, '_density_brush_size', 30) // 2
                    dy0, dy1 = max(0, cy - dr), min(self.map_h, cy + dr + 1)
                    dx0, dx1 = max(0, cx - dr), min(self.map_w, cx + dr + 1)
                    yy_d, xx_d = np.ogrid[dy0:dy1, dx0:dx1]
                    dist_sq = (yy_d - cy) ** 2 + (xx_d - cx) ** 2
                    r_sq = dr * dr
                    d_circle = dist_sq <= r_sq
                    dv = getattr(self, '_density_paint_value', 0.8)
                    soft = getattr(self, '_density_soft_edge', 0.5)
                    if soft > 0.01:
                        dist_norm = np.sqrt(dist_sq[d_circle].astype(np.float32)) / max(dr, 1)
                        falloff = np.exp(-dist_norm * dist_norm / (2 * soft * soft))
                        old_vals = dm[dy0:dy1, dx0:dx1][d_circle]
                        dm[dy0:dy1, dx0:dx1][d_circle] = old_vals + (dv - old_vals) * falloff
                    else:
                        dm[dy0:dy1, dx0:dx1][d_circle] = dv
                return

            # Provinces are no longer automatically cleared when they already exist - the user may just want to expand the land
            # The newly drawn land area province_map remains 0 (unallocated),
            # Later, use "incremental province generation" to add provinces to the new area.

            if self._current_tool == "eraser":
                if circle is not None:
                    self._tile_map[y0:y1, x0:x1][circle] = TILE_SEA
                else:
                    self._tile_map[y0:y1, x0:x1] = TILE_SEA
            elif self._current_tool in ("brush", "new_land"):
                tile_val = TILE_LAND if self._current_tool == "new_land" else self._current_tile_type
                if self._current_tool == "new_land":
                    # Record the pixels that actually changed from non-land to land (old land is not recorded)
                    sub = self._tile_map[y0:y1, x0:x1]
                    if circle is not None:
                        changed = circle & (sub != TILE_LAND)
                        self.new_land_mask[y0:y1, x0:x1][changed] = True
                        sub[circle] = tile_val
                    else:
                        changed = sub != TILE_LAND
                        self.new_land_mask[y0:y1, x0:x1][changed] = True
                        sub[:] = tile_val
                else:
                    if circle is not None:
                        self._tile_map[y0:y1, x0:x1][circle] = tile_val
                    else:
                        self._tile_map[y0:y1, x0:x1] = tile_val

        elif mode == "terrain":
            if not self._terrain_brush_mode:
                return
            # Use independent terrain brush size, ignore general brush_size
            tr = self._terrain_brush_size // 2
            if tr < 1:
                tr = 1
            ty0 = max(0, cy - tr)
            ty1 = min(self.map_h, cy + tr + 1)
            tx0 = max(0, cx - tr)
            tx1 = min(self.map_w, cx + tr + 1)
            if ty0 >= ty1 or tx0 >= tx1:
                return
            yy_t, xx_t = np.ogrid[ty0:ty1, tx0:tx1]
            dist_sq_t = (yy_t - cy) ** 2 + (xx_t - cx) ** 2
            t_circle = dist_sq_t <= tr * tr
            # Sea/Lake Protection: Visual topography does not change sea and lake
            sub_tile = self._tile_map[ty0:ty1, tx0:tx1]
            t_circle = t_circle & (sub_tile == TILE_LAND)
            if not np.any(t_circle):
                self._mark_dirty(tx0, ty0, tx1, ty1)
                return
            if self._current_tool == "eraser":
                self._terrain_map[ty0:ty1, tx0:tx1][t_circle] = 0
            elif self._current_tool == "brush":
                self._terrain_map[ty0:ty1, tx0:tx1][t_circle] = self._current_terrain_index
            self._mark_dirty(tx0, ty0, tx1, ty1)
            return

        elif mode == "height":
            if self._height_brush_mode == "off":
                return
            # Use independent height brush size, ignore general brush_size
            hr = self._height_brush_size // 2
            if hr < 1:
                hr = 1
            hy0 = max(0, cy - hr)
            hy1 = min(self.map_h, cy + hr + 1)
            hx0 = max(0, cx - hr)
            hx1 = min(self.map_w, cx + hr + 1)
            if hy0 >= hy1 or hx0 >= hx1:
                return
            yy_h, xx_h = np.ogrid[hy0:hy1, hx0:hx1]
            dist_sq = (yy_h - cy) ** 2 + (xx_h - cx) ** 2
            r_sq = hr * hr
            disk = dist_sq <= r_sq
            # Only land pixels are changed (sea and lake are not changed)
            sub_tile = self._tile_map[hy0:hy1, hx0:hx1]
            disk = disk & (sub_tile == TILE_LAND)
            if not np.any(disk):
                return
            # Distance attenuation (0..1, strongest at the center, weakest at the edges)
            dist_norm = np.sqrt(dist_sq.astype(np.float32)) / max(hr, 1)
            falloff = np.clip(1.0 - dist_norm, 0.0, 1.0)
            sub_h = self._height_map[hy0:hy1, hx0:hx1].astype(np.int16)
            strength = float(self._height_brush_strength)
            if self._height_brush_mode == "raise":
                delta = (falloff * strength).astype(np.int16)
                new_h = np.clip(sub_h + delta, 0, 255).astype(np.uint8)
                self._height_map[hy0:hy1, hx0:hx1][disk] = new_h[disk]
                # If the lifted land is still below sea level, it will be pulled to sea level +1
                from data.constants import SEA_LEVEL
                low_mask = disk & (self._height_map[hy0:hy1, hx0:hx1] <= SEA_LEVEL)
                if np.any(low_mask):
                    self._height_map[hy0:hy1, hx0:hx1][low_mask] = SEA_LEVEL + 1
            elif self._height_brush_mode == "lower":
                delta = (falloff * strength).astype(np.int16)
                new_h = np.clip(sub_h - delta, 0, 255).astype(np.uint8)
                self._height_map[hy0:hy1, hx0:hx1][disk] = new_h[disk]
                # Prevent land from sinking below sea level (maintain land identity)
                from data.constants import SEA_LEVEL
                below = disk & (self._height_map[hy0:hy1, hx0:hx1] <= SEA_LEVEL)
                if np.any(below):
                    self._height_map[hy0:hy1, hx0:hx1][below] = SEA_LEVEL + 1
            elif self._height_brush_mode == "smooth":
                # Box blur (average within disk only): Zoom in evenly with disk pixels
                area_vals = sub_h[disk]
                avg = int(area_vals.mean())
                blend = falloff * (strength / 10.0)  # 10 Strength = Fully Pulled to Mean
                blend = np.clip(blend, 0.0, 1.0)
                new_h = (sub_h * (1.0 - blend) + avg * blend).astype(np.int16)
                new_h = np.clip(new_h, 0, 255).astype(np.uint8)
                self._height_map[hy0:hy1, hx0:hx1][disk] = new_h[disk]
            self._mark_dirty(hx0, hy0, hx1, hy1)
            return

        elif mode == "province":
            if self._selected_province_id <= 0:
                return
            sub_pm = self._province_map[y0:y1, x0:x1]
            sub_tm = self._tile_map[y0:y1, x0:x1]
            mask = (
                (sub_tm == self._selected_province_tile)
                & (sub_pm != 0)
                & (sub_pm != self._selected_province_id)
            )
            sub_pm[mask] = self._selected_province_id

        elif mode == "river":
            if self._current_tool == "eraser":
                if circle is not None:
                    self._river_map[y0:y1, x0:x1][circle] = RIVER_ERASE
                else:
                    self._river_map[y0:y1, x0:x1] = RIVER_ERASE
            elif self._current_tool == "brush":
                if circle is not None:
                    self._river_map[y0:y1, x0:x1][circle] = self._current_river_type
                else:
                    self._river_map[y0:y1, x0:x1] = self._current_river_type

        self._mark_dirty(x0, y0, x1, y1)

    def _paint_at(self, scene_x: int, scene_y: int) -> None:
        """Draw at the specified position and interpolate with the previous position to avoid line breakage.

        River mode uses **stepped orthogonal paths** (horizontal first, then vertical), compliant with HOI4 rules
        (pixels do not connect diagonally — Paradox wiki "Map modding").
        Other modes use Bresenham slopes (smoother)."""
        if self._last_draw_pos is not None:
            lx, ly = self._last_draw_pos
            dx = abs(scene_x - lx)
            dy = abs(scene_y - ly)
            steps = max(dx, dy)
            if self._display_mode == "river":
                # Rivers: Always go stairs (even if it’s just a 1 pixel diagonal move, go orthogonal)
                # Dragging the mouse slowly will only report 1px each time. When dx=dy=1, steps=1.
                # Direct stamping will produce a series of diagonal pixels → illegal
                if dx > 0 or dy > 0:
                    self._stamp_orthogonal(lx, ly, scene_x, scene_y)
            elif steps > 1:
                # Other modes: Bresenham slope interpolation (smoothing)
                for i in range(1, steps + 1):
                    t = i / steps
                    ix = int(lx + (scene_x - lx) * t)
                    iy = int(ly + (scene_y - ly) * t)
                    self._stamp_brush(ix, iy)
            else:
                self._stamp_brush(scene_x, scene_y)
        else:
            self._stamp_brush(scene_x, scene_y)

        self._last_draw_pos = (scene_x, scene_y)

    def _stamp_orthogonal(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Orthogonal ladder line drawing: first go one square in the x direction, and then in the y direction.
        It is guaranteed that two adjacent pixels must be in contact with each other up, down, left, and right, without any diagonal connection.
        For use in river mode - HOI4 specifies that rivers can only be connected orthogonally."""
        # horizontal section
        x = x0
        step_x = 1 if x1 > x0 else -1 if x1 < x0 else 0
        while x != x1:
            x += step_x
            self._stamp_brush(x, y0)
        # vertical section
        y = y0
        step_y = 1 if y1 > y0 else -1 if y1 < y0 else 0
        while y != y1:
            y += step_y
            self._stamp_brush(x1, y)

    def _flood_fill(self, x: int, y: int) -> None:
        if x < 0 or x >= self.map_w or y < 0 or y >= self.map_h:
            return

        mode = self._display_mode

        if mode in ("province", "state", "country", "river"):
            return  # These modes do not support padding

        # Determine the fill target array and fill value
        if mode == "land":
            data = self._tile_map
            fill_val = self._current_tile_type
        elif mode == "terrain":
            data = self._terrain_map
            fill_val = self._current_terrain_index
        elif mode == "height":
            data = self._height_map
            fill_val = self._current_height_value
        else:
            return

        target = data[y, x]
        if target == fill_val:
            return

        stack = [(x, y)]
        visited = np.zeros((self.map_h, self.map_w), dtype=bool)

        while stack:
            cx, cy = stack.pop()
            if cx < 0 or cx >= self.map_w or cy < 0 or cy >= self.map_h:
                continue
            if visited[cy, cx] or data[cy, cx] != target:
                continue

            left = cx
            while left > 0 and data[cy, left - 1] == target and not visited[cy, left - 1]:
                left -= 1
            right = cx
            while right < self.map_w - 1 and data[cy, right + 1] == target and not visited[cy, right + 1]:
                right += 1

            data[cy, left:right + 1] = fill_val
            visited[cy, left:right + 1] = True

            for nx in range(left, right + 1):
                if cy > 0 and not visited[cy - 1, nx] and data[cy - 1, nx] == target:
                    stack.append((nx, cy - 1))
                if cy < self.map_h - 1 and not visited[cy + 1, nx] and data[cy + 1, nx] == target:
                    stack.append((nx, cy + 1))

        # Render in full after filling (because the area is uncertain)
        self._full_render()

    # ========== Event Auxiliary ==========

    def _scene_pos(self, event: QMouseEvent) -> tuple[int, int]:
        pos = self.mapToScene(event.pos())
        return int(pos.x()), int(pos.y())

    def _scene_pos_clamped(self, event: QMouseEvent) -> tuple[int, int]:
        """Returns scene coordinates restricted to map boundaries"""
        sx, sy = self._scene_pos(event)
        return max(0, min(self.map_w - 1, sx)), max(0, min(self.map_h - 1, sy))

    def _is_in_bounds(self, sx: int, sy: int) -> bool:
        """Check if coordinates are within map boundaries"""
        return 0 <= sx < self.map_w and 0 <= sy < self.map_h

    def cleanup_mode_state(self) -> None:
        """Clean up all temporary mode state. Called when switching modes to prevent exceptions caused by state residue."""
        # Change tool state
        if self._transform_active:
            self._end_transform()
        self._transform_selecting = False
        self._transform_box = None
        self._transform_snippet = None
        self._transform_orig_box = None
        self._transform_drag = None
        self._transform_drag_start = None
        self._transform_angle = 0.0
        self._transform_last_written_box = None

        # Frame selection state
        self._selection_mode = False
        self._selection_rect = None
        self._selection_start = None
        self._selection_rect_item.setVisible(False)

        # drawing status
        self._is_drawing = False
        self._last_draw_pos = None

        # Framework tools
        self._framework_tool = None

        # Province selected
        self._selected_province_id = 0
        self._selected_province_ids.clear()

        # lasso / overlay cleaning
        self._clear_lasso_visual()

        # cursor reset
        self.setCursor(Qt.CursorShape.CrossCursor)

    def fit_in_view(self) -> None:
        self.fitInView(QRectF(0, 0, self.map_w, self.map_h),
                       Qt.AspectRatioMode.KeepAspectRatio)
        transform = self.transform()
        self._zoom = transform.m11()
        self.zoom_changed.emit(self._zoom)
