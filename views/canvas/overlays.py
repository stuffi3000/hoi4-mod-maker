"""Overlay Mixin — Province border/VP marker/Transform box/Lasso/Brush cursor
Split from canvas_widget.py"""
import math

import numpy as np
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QPainterPath, QBrush, QPolygonF,
    QFont,
)

# Modes that are allowed to be displayed by the country/state attribution overlay (those in which the base view itself is not colored by country/state).
# Modes that allow "Country Color + State Borders" overlays
# state/country itself has been colored according to ownership → overlay. In these two modes, only the border is drawn and no longer filled.
CS_OVERLAY_ALLOWED_MODES = frozenset({
    "land", "terrain", "height", "river", "province",
    "logistics", "colormap", "default_map", "province_terrain",
    "state", "country",
})

_PLACEMENT_ROLE_COLORS = {
    "reviewed": (46, 204, 113),
    "accepted": (26, 188, 156),
    "generated": (241, 196, 15),
    "authored": (52, 152, 219),
    "unreviewed": (149, 165, 166),
    "vp": (230, 30, 150),
    "collision": (255, 70, 0),
}

# Placement type is deliberately more stable and more useful to the mapper
# than review status.  Slots and authored building coordinates share green;
# ports are always blue; victory points are always amber/gold.
_PLACEMENT_KIND_COLORS = {
    "slot": (46, 204, 113),
    "building": (46, 204, 113),
    "port": (52, 152, 219),
    "vp": (245, 176, 65),
    "weather": (149, 165, 166),
    "collision": (255, 70, 0),
}

_PLACEMENT_FAST_MARKER_THRESHOLD = 512


def _placement_stamp_offsets(kind, *, inner=False):
    """Return a small raster template for a batched placement marker."""
    if kind == "slot":
        radius = 2 if inner else 3
        return tuple(
            (dx, dy)
            for dy in range(-radius, radius + 1)
            for dx in range(-radius, radius + 1)
            if inner or max(abs(dx), abs(dy)) == radius
        )
    if kind == "port":
        radius_squared = 9 if inner else 20
        return tuple(
            (dx, dy)
            for dy in range(-4, 5)
            for dx in range(-4, 5)
            if dx * dx + dy * dy <= radius_squared
        )
    if kind == "building":
        return tuple(
            (dx, dy)
            for dy in range(-5, 4)
            for dx in range(-4, 5)
            if abs(dx) <= (dy + 5) * 4 // 8
        )
    if kind == "weather":
        radius = 3 if inner else 5
        return tuple(
            (dx, dy)
            for dy in range(-radius, radius + 1)
            for dx in range(-radius, radius + 1)
            if abs(dx) + abs(dy) <= radius
        )
    if kind == "vp":
        radius = 2 if inner else 6
        return tuple(
            (dx, dy)
            for dy in range(-5, 6)
            for dx in range(-5, 6)
            if abs(dx) + abs(dy) <= radius
        )
    if kind == "collision":
        width = 1 if inner else 2
        return tuple(
            (dx, dy)
            for dy in range(-5, 6)
            for dx in range(-5, 6)
            if abs(dx - dy) <= width or abs(dx + dy) <= width
        )
    radius_squared = 4 if inner else 9
    return tuple(
        (dx, dy)
        for dy in range(-3, 4)
        for dx in range(-3, 4)
        if dx * dx + dy * dy <= radius_squared
    )


def _stamp_placement_group(rgba, markers, kind, color):
    """Stamp one marker kind/role group into an RGBA raster."""
    if not markers:
        return
    centers = np.asarray(
        [
            (
                int(math.floor(float(marker.x))),
                int(math.floor(float(marker.y))),
            )
            for marker in markers
        ],
        dtype=np.int32,
    )
    xs = centers[:, 0]
    ys = centers[:, 1]
    height, width = rgba.shape[:2]

    def stamp(offsets, stamp_color):
        for dx, dy in offsets:
            target_x = xs + dx
            target_y = ys + dy
            valid = (
                (target_x >= 0)
                & (target_x < width)
                & (target_y >= 0)
                & (target_y < height)
            )
            if np.any(valid):
                rgba[target_y[valid], target_x[valid]] = stamp_color

    white = (255, 255, 255, 230)
    stamp(_placement_stamp_offsets(kind), white)
    if kind == "vp":
        stamp(_placement_stamp_offsets(kind, inner=True), color)
        stamp(((0, 0),), white)
    else:
        stamp(_placement_stamp_offsets(kind, inner=True), color)


def _render_placement_markers_fast(width, height, markers):
    """Render a large marker set without one QPainter call per marker."""
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    groups = {}
    for marker in markers:
        kind = str(getattr(marker, "kind", ""))
        groups.setdefault(kind, []).append(marker)
    for kind, group in groups.items():
        rgb = _PLACEMENT_KIND_COLORS.get(
            kind, _PLACEMENT_ROLE_COLORS["unreviewed"]
        )
        _stamp_placement_group(rgba, group, kind, (*rgb, 255))
    image = QImage(
        rgba.data,
        width,
        height,
        width * 4,
        QImage.Format.Format_RGBA8888,
    )
    image._ref = rgba
    return image.copy()


def _placement_role_color(role):
    """Map a pure-model role string to a Qt color."""
    try:
        key = str(role).strip().lower()
    except Exception:
        key = ""
    rgb = _PLACEMENT_ROLE_COLORS.get(key, _PLACEMENT_ROLE_COLORS["unreviewed"])
    return QColor(rgb[0], rgb[1], rgb[2], 255)


def _placement_marker_color(kind, role="unreviewed"):
    """Return the stable type colour, with a role fallback for unknown kinds."""
    try:
        marker_kind = str(kind).strip().lower()
    except Exception:
        marker_kind = ""
    rgb = _PLACEMENT_KIND_COLORS.get(marker_kind)
    if rgb is None:
        try:
            marker_role = str(role).strip().lower()
        except Exception:
            marker_role = "unreviewed"
        rgb = _PLACEMENT_ROLE_COLORS.get(
            marker_role, _PLACEMENT_ROLE_COLORS["unreviewed"]
        )
    return QColor(rgb[0], rgb[1], rgb[2], 255)


def _draw_placement_marker(painter, kind, x, y, color):
    """Draw one marker symbol centered at fractional map coordinates."""
    fx = float(x)
    fy = float(y)
    white = QColor(255, 255, 255, 230)
    if kind == "slot":
        painter.setPen(QPen(white, 1))
        painter.setBrush(QBrush(color))
        painter.drawRect(QRectF(fx - 3.5, fy - 3.5, 7.0, 7.0))
    elif kind == "port":
        painter.setPen(QPen(white, 1))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QRectF(fx - 4.5, fy - 4.5, 9.0, 9.0))
    elif kind == "building":
        painter.setPen(QPen(white, 1))
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([
            QPointF(fx, fy - 5.0),
            QPointF(fx - 4.5, fy + 3.5),
            QPointF(fx + 4.5, fy + 3.5),
        ]))
    elif kind == "weather":
        painter.setPen(QPen(white, 1))
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([
            QPointF(fx, fy - 5.0),
            QPointF(fx + 5.0, fy),
            QPointF(fx, fy + 5.0),
            QPointF(fx - 5.0, fy),
        ]))
    elif kind == "vp":
        painter.setPen(QPen(white, 2))
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([
            QPointF(fx, fy - 6.0),
            QPointF(fx + 6.0, fy),
            QPointF(fx, fy + 6.0),
            QPointF(fx - 6.0, fy),
        ]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
        painter.drawEllipse(QRectF(fx - 1.5, fy - 1.5, 3.0, 3.0))
    elif kind == "collision":
        painter.setPen(QPen(white, 5))
        painter.drawLine(QPointF(fx - 5.0, fy - 5.0), QPointF(fx + 5.0, fy + 5.0))
        painter.drawLine(QPointF(fx - 5.0, fy + 5.0), QPointF(fx + 5.0, fy - 5.0))
        painter.setPen(QPen(color, 3))
        painter.drawLine(QPointF(fx - 5.0, fy - 5.0), QPointF(fx + 5.0, fy + 5.0))
        painter.drawLine(QPointF(fx - 5.0, fy + 5.0), QPointF(fx + 5.0, fy - 5.0))
    else:
        painter.setPen(QPen(white, 1))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QRectF(fx - 3.0, fy - 3.0, 6.0, 6.0))


class OverlayMixin:
    """Overlay related methods. Assume self owns:
    - _province_pixmap_item, _province_map, _selected_province_id
    - _show_provinces, _display_mode
    - _vp_overlay_item, _vp_data, _map_data
    - _transform_border, _transform_handles, _transform_box, _zoom
    - _lasso_path_item, _lasso_overlay, _framework_ctx
    - _brush_cursor, _current_tool, _brush_size"""

    def _rebuild_border_cache(self) -> None:
        """Rebuild province boundary cache + base QPixmap (only called when province data changes)."""
        if self._province_map.max() == 0:
            self._border_cache = None
            self._border_base_pixmap = None
            return
        h, w = self._province_map.shape
        borders = np.zeros((h, w), dtype=bool)
        borders[:-1, :] |= self._province_map[:-1, :] != self._province_map[1:, :]
        borders[:, :-1] |= self._province_map[:, :-1] != self._province_map[:, 1:]
        self._border_cache = borders
        # Generate base pixmap (only do it once, no need to copy 46MB each time)
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[borders, 3] = 180
        img = QImage(rgba.data, w, h,
                     w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        self._border_base_pixmap = QPixmap.fromImage(img)

    def _render_province_overlay(self) -> None:
        """Render province boundary overlay (base pixmap + highlight painted with QPainter)"""
        if not self._show_provinces or self._province_map.max() == 0:
            self._province_pixmap_item.setVisible(False)
            return

        if not hasattr(self, '_border_cache') or self._border_cache is None:
            self._rebuild_border_cache()
        if not hasattr(self, '_border_base_pixmap') or self._border_base_pixmap is None:
            self._rebuild_border_cache()

        # Copy from base pixmap (QPixmap copy is fast, no numpy involved)
        result = QPixmap(self._border_base_pixmap)

        # Highlight the selected province (use QPainter to draw a yellow border and do not operate numpy arrays)
        selected = self.selected_province_ids()
        if selected:
            selected_mask = np.isin(self._province_map, tuple(sorted(selected)))
            ys, xs = np.where(selected_mask)
            if len(ys) > 0:
                y0 = max(0, int(ys.min()) - 1)
                y1 = min(self.map_h, int(ys.max()) + 2)
                x0 = max(0, int(xs.min()) - 1)
                x1 = min(self.map_w, int(xs.max()) + 2)

                # Calculate highlight boundaries in small areas
                sub = self._province_map[y0:y1, x0:x1]
                sel_mask = selected_mask[y0:y1, x0:x1]
                sel_border = np.zeros_like(sel_mask)
                sel_border[:-1, :] |= sel_mask[:-1, :] & ~sel_mask[1:, :]
                sel_border[1:, :]  |= sel_mask[1:, :] & ~sel_mask[:-1, :]
                sel_border[:, :-1] |= sel_mask[:, :-1] & ~sel_mask[:, 1:]
                sel_border[:, 1:]  |= sel_mask[:, 1:] & ~sel_mask[:, :-1]

                # Paint yellow highlight to small area
                h_rgba = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
                h_rgba[sel_border] = (0, 230, 255, 255)  # BGRA: yellow
                h_img = QImage(h_rgba.data, x1 - x0, y1 - y0,
                              (x1 - x0) * 4, QImage.Format.Format_ARGB32)
                h_img._ref = h_rgba

                painter = QPainter(result)
                painter.drawImage(x0, y0, h_img)
                painter.end()
        self._province_pixmap_item.setPixmap(result)
        self._province_pixmap_item.setVisible(True)

    def show_state_borders(self, visible: bool, state_mgr=None) -> None:
        """Show/hide State shading + border overlay (for strategic region state selection mode).

        Semi-transparent State color fill + white border line to ensure that each State can be clearly seen."""
        overlay = getattr(self, '_state_border_overlay', None)
        if overlay is None:
            return
        if not visible:
            overlay.setVisible(False)
            return
        if state_mgr is None or self._province_map.max() == 0:
            overlay.setVisible(False)
            return

        # Construct province→state ID mapping table
        max_pid = int(self._province_map.max())
        pid_to_sid = np.zeros(max_pid + 1, dtype=np.int32)
        for sid, state in state_mgr._states.items():
            for pid in state.provinces:
                if 0 < pid <= max_pid:
                    pid_to_sid[pid] = sid

        # Convert province_map to state_map through LUT
        pm = np.clip(self._province_map, 0, max_pid)
        state_map = pid_to_sid[pm]

        h, w = state_map.shape

        # Generate deterministic colors (semi-transparent fills) for each state
        max_sid = int(state_map.max()) + 1
        # Generate highly distinguishable colors using golden ratio hashing
        color_lut = np.zeros((max_sid, 4), dtype=np.uint8)
        for sid in range(1, max_sid):
            hue = (sid * 137) % 360  # golden angle hash
            # Simple HSV→RGB (S=0.5, V=0.9)
            h_i = hue // 60
            f = (hue % 60) / 60.0
            v, s = 230, 0.5
            p = int(v * (1 - s))
            q = int(v * (1 - s * f))
            t = int(v * (1 - s * (1 - f)))
            v = int(v)
            if h_i == 0:   r, g, b = v, t, p
            elif h_i == 1: r, g, b = q, v, p
            elif h_i == 2: r, g, b = p, v, t
            elif h_i == 3: r, g, b = p, q, v
            elif h_i == 4: r, g, b = t, p, v
            else:          r, g, b = v, p, q
            color_lut[sid] = (b, g, r, 90)  # BGRA, alpha=90 translucent

        # fill state color
        rgba = color_lut[state_map]

        # Calculate state boundaries (white bright lines)
        borders = np.zeros((h, w), dtype=bool)
        borders[:-1, :] |= state_map[:-1, :] != state_map[1:, :]
        borders[1:, :]  |= state_map[:-1, :] != state_map[1:, :]
        borders[:, :-1] |= state_map[:, :-1] != state_map[:, 1:]
        borders[:, 1:]  |= state_map[:, :-1] != state_map[:, 1:]
        rgba[borders] = (200, 200, 200, 110)  # Weakened white (off-white translucent)

        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        overlay.setPixmap(QPixmap.fromImage(img))
        overlay.setVisible(True)

    def refresh_terrain_underlay(self) -> None:
        """Rebuild the terrain basemap overlay based on source / display_mode.

        source = 'height': Colored height map LUT (dark blue/green/yellow/brown/white) — looking at mountains/coasts
        source = 'terrain': terrain classification LUT (HOI4 standard terrain color) — see plains/forest/mountain distribution
        The transparency slider controls the degree of blending with the state/country color."""
        from views.canvas.luts import _HEIGHT_COLOR_LUT, _TERRAIN_COLOR_LUT
        item = getattr(self, "_terrain_underlay_item", None)
        if item is None:
            return
        visible = getattr(self, "_terrain_underlay_visible", False)
        if not visible or self._display_mode not in ("state", "country"):
            item.setVisible(False)
            return

        source = getattr(self, "_terrain_underlay_source", "height")
        if source == "terrain":
            # Colored with provincial attribute (provincial_terrain) — user-selected real terrain classification
            pt_rgb = getattr(self, "_provincial_terrain_color_rgb", None)
            if pt_rgb is None:
                item.setVisible(False)
                return
            h, w = pt_rgb.shape[:2]
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            rgba[:, :, 0] = pt_rgb[:, :, 2]  # B
            rgba[:, :, 1] = pt_rgb[:, :, 1]  # G
            rgba[:, :, 2] = pt_rgb[:, :, 0]  # R
            rgba[:, :, 3] = 255
        else:
            hm = getattr(self, "_height_map", None)
            if hm is None:
                item.setVisible(False)
                return
            rgba = np.ascontiguousarray(_HEIGHT_COLOR_LUT[hm])
            h, w = hm.shape

        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        item.setPixmap(QPixmap.fromImage(img))
        item.setOpacity(getattr(self, "_terrain_underlay_opacity", 0.5))
        item.setVisible(True)

    def show_terrain_context_overlay(
        self, visible: bool, country_mgr=None, state_mgr=None,
    ) -> None:
        """Toggles the "Translucent Country Color + White State Borders" overlay (global view toggle, not terrain specific)."""
        self._terrain_context_visible = bool(visible)
        if country_mgr is not None:
            self._terrain_ctx_country_mgr = country_mgr
        if state_mgr is not None:
            self._terrain_ctx_state_mgr = state_mgr
        self.refresh_terrain_context_overlay()

    def refresh_terrain_context_overlay(self) -> None:
        """Rebuild the overlay pixmap based on the cache mgrs; do not change the visible switch, only determine the visibility according to the current mode."""
        overlay = getattr(self, '_terrain_context_overlay', None)
        if overlay is None:
            return
        visible = getattr(self, '_terrain_context_visible', False)
        if not visible or self._display_mode not in CS_OVERLAY_ALLOWED_MODES:
            overlay.setVisible(False)
            return
        country_mgr = getattr(self, '_terrain_ctx_country_mgr', None)
        state_mgr = getattr(self, '_terrain_ctx_state_mgr', None)
        if country_mgr is None or state_mgr is None:
            overlay.setVisible(False)
            return
        pm_max = int(self._province_map.max()) if self._province_map is not None else 0
        if pm_max <= 0:
            overlay.setVisible(False)
            return

        h, w = self._province_map.shape
        max_pid = pm_max

        # In state/country mode, the base map has been colored according to ownership, and the overlay is no longer filled with the country color, only the border is drawn.
        borders_only = self._display_mode in ("state", "country")

        # pid → (state_id, bgra color) two LUTs
        pid_to_sid = np.zeros(max_pid + 1, dtype=np.int32)
        pid_to_color = np.zeros((max_pid + 1, 4), dtype=np.uint8)  # BGRA
        countries = getattr(country_mgr, "countries", {}) or {}
        states = getattr(state_mgr, "states", {}) or {}
        get_owner = getattr(country_mgr, "get_owner_of_state", lambda _sid: "")
        for sid, state in states.items():
            if borders_only:
                bgra = (0, 0, 0, 0)  # Fully transparent—only state border effects remain
            else:
                owner_tag = get_owner(sid)
                if owner_tag and owner_tag in countries:
                    c = countries[owner_tag].color
                    r, g, b = int(c[0]) & 0xFF, int(c[1]) & 0xFF, int(c[2]) & 0xFF
                    bgra = (b, g, r, 110)
                else:
                    bgra = (90, 90, 90, 55)  # Unassigned countries: light gray
            for pid in state.provinces:
                if 0 < pid <= max_pid:
                    pid_to_sid[pid] = sid
                    pid_to_color[pid] = bgra

        pm = np.clip(self._province_map, 0, max_pid)
        rgba = pid_to_color[pm]           # Coloring (H, W, 4) BGRA
        state_map = pid_to_sid[pm]        # (H, W) int32

        # State boundary (white bright line): use !=right and !=down two directions to cover the left, right, upper and lower sides
        borders = np.zeros((h, w), dtype=bool)
        diff_v = state_map[:-1, :] != state_map[1:, :]
        diff_h = state_map[:, :-1] != state_map[:, 1:]
        borders[:-1, :] |= diff_v
        borders[1:, :]  |= diff_v
        borders[:, :-1] |= diff_h
        borders[:, 1:]  |= diff_h
        rgba[borders] = (255, 255, 255, 220)

        # ascontiguousarray ensures that the buffer obtained by QImage is continuous (fancy-index is already continuous, this is defensive)
        rgba = np.ascontiguousarray(rgba)
        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        overlay.setPixmap(QPixmap.fromImage(img))
        overlay.setVisible(True)

    def set_vp_data(self, vp_dict: dict[int, int], name_dict: dict[int, str] | None = None) -> None:
        """Set VP data {province_id: vp_value} + city name {province_id: name}"""
        self._vp_data = dict(vp_dict)
        self._vp_names = dict(name_dict) if name_dict else {}
        self._vp_cache_dirty = True
        self._update_vp_visibility()

    def set_vp_overlay_visible(self, mode: str, visible: bool) -> None:
        """Toggle VP markers for one of the terrain editing modes."""
        if mode not in ("terrain", "province_terrain"):
            return
        if not hasattr(self, "_vp_overlay_mode_visibility"):
            self._vp_overlay_mode_visibility = {}
        self._vp_overlay_mode_visibility[mode] = bool(visible)
        self._update_vp_visibility()

    def _update_vp_visibility(self) -> None:
        """Show/hide VP overlay based on current mode and only redraw when data changes"""
        mode_allowed = self._display_mode in ("state", "province")
        if self._display_mode in ("terrain", "province_terrain"):
            mode_allowed = bool(
                getattr(self, "_vp_overlay_mode_visibility", {}).get(
                    self._display_mode, False
                )
            )
        if not mode_allowed or not self._vp_data:
            self._vp_overlay_item.setVisible(False)
            return
        if getattr(self, '_vp_cache_dirty', True):
            # Make sure the centroid cache exists
            if self._map_data and not getattr(self._map_data, '_centroid_cache', None):
                self._map_data.build_centroid_cache()
            self._render_vp_overlay()
            self._vp_cache_dirty = False
        self._vp_overlay_item.setVisible(True)

    def _render_vp_overlay(self) -> None:
        """Render VP marker overlay (only called when VP data changes, results cached)"""
        if not self._vp_data:
            return

        # Create a transparent canvas
        img = QImage(self.map_w, self.map_h, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        from PyQt5.QtGui import QFont
        name_font = QFont("Segoe UI")
        name_font.setPixelSize(12)
        name_font.setBold(True)
        painter.setFont(name_font)

        for pid, vp_val in self._vp_data.items():
            if vp_val <= 0:
                continue
            centroid = self._map_data.get_province_centroid(pid)
            if centroid is None:
                continue
            cx, cy = centroid

            # Tiny red dot (1px circle)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(220, 30, 30)))
            painter.drawEllipse(cx - 1, cy - 1, 3, 3)

            # City name: to the right of the red dot, dark stroke + white text (enlarge the canvas to read it clearly, consistent with the game)
            name = self._vp_names.get(pid, "")
            if name:
                painter.setPen(QColor(20, 20, 20, 200))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    painter.drawText(cx + 5 + dx, cy + 4 + dy, name)
                painter.setPen(QColor(255, 255, 255, 235))
                painter.drawText(cx + 5, cy + 4, name)

        painter.end()
        self._vp_overlay_item.setPixmap(QPixmap.fromImage(img))

    def _update_transform_visuals(self) -> None:
        """Update the transform box and handle position according to _transform_box."""
        if not self._transform_box:
            self._transform_border.setVisible(False)
            for h in self._transform_handles.values():
                h.setVisible(False)
            return

        x0, y0, x1, y1 = self._transform_box
        self._transform_border.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        self._transform_border.setVisible(True)

        positions = {"tl": (x0, y0), "tr": (x1, y0), "bl": (x0, y1), "br": (x1, y1)}
        for hid, (hx, hy) in positions.items():
            self._transform_handles[hid].setPos(hx, hy)
            self._transform_handles[hid].setVisible(True)

    def _hit_test_transform(self, sx: float, sy: float) -> str | None:
        """Determine which part of the transformation box the click position is in. Return "move"/"tl"/"tr"/"bl"/"br"/None."""
        if not self._transform_box:
            return None
        x0, y0, x1, y1 = self._transform_box
        handle_r = 10 / self._zoom  # handle hot zone radius (screen pixels to scene pixels)

        # Check the 4 corner handles
        for hid, (hx, hy) in [("tl", (x0, y0)), ("tr", (x1, y0)),
                               ("bl", (x0, y1)), ("br", (x1, y1))]:
            if abs(sx - hx) < handle_r and abs(sy - hy) < handle_r:
                return hid

        # Check if inside the box (move)
        if x0 <= sx <= x1 and y0 <= sy <= y1:
            return "move"

        # Near outside the box = rotate (< 30px from the edge of the box)
        margin = 30 / self._zoom
        if (x0 - margin <= sx <= x1 + margin and y0 - margin <= sy <= y1 + margin):
            return "rotate"
        return None

    def _show_expand_overlay(self) -> None:
        """Shows the allowed area of the selected province (translucent yellow) + turns green when entering expansion."""
        if self._framework_ctx is None:
            return
        mask = self._framework_ctx.state.get("allowed_mask")
        if mask is None:
            return
        active = self._framework_ctx.state.get("active", False)
        # The active state is green (prompt "can now draw"), the inactive state is yellow (prompt "click again to enter")
        color = (50, 220, 80, 70) if active else (255, 230, 0, 60)
        rgba = np.zeros((self.map_h, self.map_w, 4), dtype=np.uint8)
        rgba[mask] = color
        img = QImage(rgba.data, self.map_w, self.map_h,
                     self.map_w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        self._lasso_overlay.setPixmap(QPixmap.fromImage(img))
        self._lasso_overlay.setVisible(True)
        # Do not show path lines
        self._lasso_path_item.setVisible(False)

    def _clear_lasso_visual(self) -> None:
        """Clears all lasso feedback elements."""
        self._lasso_path_item.setPath(QPainterPath())
        self._lasso_path_item.setVisible(False)
        self._lasso_overlay.setVisible(False)

    def _update_brush_cursor(self, sx: int, sy: int) -> None:
        """Updated brush preview cursor position and size."""
        self._brush_cursor_pos = (sx, sy)  # Remember the position and refresh in place when the slider is resized
        density_on = getattr(self, '_density_overlay_visible', False)
        terrain_brush_on = (self._display_mode == "terrain"
                            and self._terrain_brush_mode)
        height_brush_on = (self._display_mode == "height"
                           and getattr(self, '_height_brush_mode', 'off') != "off")
        province_brush_on = (
            self._display_mode == "province"
            and self._framework_tool is not None
            and self._framework_tool.name == "province_paint"
            and self._framework_ctx is not None
            and self._framework_ctx.state.get("mode", "brush") == "brush"
        )
        show_brush = (
            (self._current_tool in ("brush", "eraser", "new_land")
             and self._display_mode in ("land", "river"))
            or density_on or terrain_brush_on or height_brush_on or province_brush_on
        )

        if show_brush:
            # Each brush mode uses its own independent size
            if density_on:
                bs = getattr(self, '_density_brush_size', 30)
            elif terrain_brush_on:
                bs = self._terrain_brush_size
            elif height_brush_on:
                bs = self._height_brush_size
            elif province_brush_on:
                bs = self._framework_ctx.brush_size
            else:
                bs = self._brush_size
            r = bs // 2
            self._brush_cursor.setRect(sx - r, sy - r, bs, bs)
            self._brush_cursor.setVisible(True)
        else:
            self._brush_cursor.setVisible(False)

    def _refresh_brush_cursor(self) -> None:
        """The preview circle is refreshed in place when the brush size slider is dragged, without waiting for the mouse to move."""
        pos = getattr(self, '_brush_cursor_pos', None)
        if pos is not None:
            self._update_brush_cursor(*pos)

    # ── Density Overlay ──

    def _render_density_overlay(self) -> None:
        """The rendered density map is a semi-transparent heat map overlaid on the map."""
        density = getattr(self._map_data, 'density_map', None) if self._map_data else None
        overlay_item = getattr(self, '_density_overlay_item', None)
        if overlay_item is None:
            return

        if density is None or not getattr(self, '_density_overlay_visible', False):
            overlay_item.setVisible(False)
            return

        h, w = density.shape
        # Convert to RGBA heat map: low density = blue and transparent, high density = red and opaque
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        d = np.clip(density, 0, 1)
        rgba[:, :, 0] = (d * 255).astype(np.uint8)          # R: high density → red
        rgba[:, :, 2] = ((1 - d) * 200).astype(np.uint8)    # B: low density → blue
        rgba[:, :, 3] = 100                                   # translucent

        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        overlay_item.setPixmap(QPixmap.fromImage(img.copy()))
        overlay_item.setVisible(True)

    def set_density_overlay_visible(self, visible: bool) -> None:
        """Switch density overlay."""
        self._density_overlay_visible = visible
        if visible:
            # Make sure density_map exists
            if self._map_data and self._map_data.density_map is None:
                self._map_data.density_map = np.full(
                    (self.map_h, self.map_w), 0.5, dtype=np.float32
                )
            self._render_density_overlay()
        else:
            overlay_item = getattr(self, '_density_overlay_item', None)
            if overlay_item:
                overlay_item.setVisible(False)

    @staticmethod
    def _normalize_placement_vp_names(names):
        normalized = {}
        for raw_pid, raw_name in dict(names or {}).items():
            try:
                pid = int(raw_pid)
            except (TypeError, ValueError):
                continue
            if pid <= 0 or not isinstance(raw_name, str) or not raw_name.strip():
                continue
            normalized[pid] = raw_name.strip()
        return normalized

    def set_placement_overlay_data(
        self, records=(), vp_points=(), findings=(), vp_names=None
    ):
        """Provide placement records, VP points, and validation findings."""
        self._placement_records = () if records is None else records
        self._placement_vp_points = () if vp_points is None else vp_points
        self._placement_findings = () if findings is None else findings
        if vp_names is not None:
            self._placement_vp_names = self._normalize_placement_vp_names(vp_names)
        self._placement_overlay_model = None
        self._render_placement_overlay()

    def set_placement_vp_names(self, names=None):
        """Set optional province-id to victory-point-name labels."""
        normalized = self._normalize_placement_vp_names(names)
        if normalized == getattr(self, "_placement_vp_names", {}):
            return
        self._placement_vp_names = normalized
        self._render_placement_overlay()

    def set_placement_selection_filter(self, filter_name: str) -> None:
        """Limit map hit-testing to one placement marker type."""
        value = str(filter_name or "all").strip().lower()
        if value not in {"all", "building", "port", "vp"}:
            value = "all"
        if value == getattr(self, "_placement_selection_filter", "all"):
            return
        self._placement_selection_filter = value
        self._clear_placement_selection()
        self._render_placement_overlay()

    def set_placement_urban_overlay_visible(self, visible: bool) -> None:
        """Show the graphical urban-terrain pixels in placement mode."""
        self._placement_urban_overlay_visible = bool(visible)
        self._render_placement_context_overlay()

    def set_placement_vp_names_visible(self, visible: bool) -> None:
        """Toggle victory-point name labels in the placement overlay."""
        self._placement_vp_names_visible = bool(visible)
        self._render_placement_overlay()

    def set_placement_overlay_visible(self, visible):
        """Toggle the read-only placement overlay."""
        self._placement_overlay_enabled = bool(visible)
        if not self._placement_overlay_enabled:
            self._placement_overlay_model = None
            self._clear_placement_selection(emit=False)
            self._render_placement_context_overlay()
            item = getattr(self, "_placement_overlay_item", None)
            if item is not None:
                try:
                    item.setPixmap(QPixmap())
                except Exception:
                    pass
                try:
                    item.setVisible(False)
                except Exception:
                    pass
            return
        # _render_placement_overlay() refreshes the context after the marker
        # layer. Rendering it here as well would rebuild the full map-sized
        # border/coastline image twice for every mode entry.
        self._render_placement_overlay()

    def _render_placement_overlay(self):
        """Render pure-model markers into a transparent map-sized pixmap."""
        item = getattr(self, "_placement_overlay_item", None)
        if item is None:
            return
        if not bool(getattr(self, "_placement_overlay_enabled", False)):
            self._placement_overlay_model = None
            self._clear_placement_selection(emit=False)
            self._render_placement_context_overlay()
            try:
                item.setVisible(False)
            except Exception:
                pass
            return
        try:
            width = int(self.map_w)
            height = int(self.map_h)
        except Exception:
            try:
                item.setVisible(False)
            except Exception:
                pass
            return
        if width <= 0 or height <= 0:
            try:
                item.setVisible(False)
            except Exception:
                pass
            return
        records = getattr(self, "_placement_records", ())
        vp_points = getattr(self, "_placement_vp_points", ())
        findings = getattr(self, "_placement_findings", ())
        try:
            from features.map.placement.overlay import build_placement_overlay_model
        except Exception:
            try:
                item.setVisible(False)
            except Exception:
                pass
            return
        try:
            model = build_placement_overlay_model(
                records,
                vp_points=vp_points,
                findings=findings,
                width=width,
                height=height,
            )
        except Exception:
            try:
                item.setVisible(False)
            except Exception:
                pass
            return
        self._placement_overlay_model = model
        try:
            markers = tuple(getattr(model, "markers", ()))
            if len(markers) >= _PLACEMENT_FAST_MARKER_THRESHOLD:
                image = _render_placement_markers_fast(width, height, markers)
            else:
                image = QImage(width, height, QImage.Format.Format_ARGB32)
                image.fill(QColor(0, 0, 0, 0))
                painter = QPainter(image)
                try:
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    for marker in markers:
                        try:
                            color = _placement_marker_color(
                                getattr(marker, "kind", ""),
                                getattr(marker, "role", "unreviewed"),
                            )
                            _draw_placement_marker(
                                painter,
                                getattr(marker, "kind", ""),
                                marker.x,
                                marker.y,
                                color,
                            )
                        except Exception:
                            continue
                finally:
                    painter.end()
            self._draw_placement_vp_names(image, markers)
            item.setPixmap(QPixmap.fromImage(image))
            item.setVisible(True)
            self._update_placement_selection_visual()
        except Exception:
            try:
                item.setVisible(False)
            except Exception:
                pass
        self._render_placement_context_overlay()

    def _draw_placement_vp_names(self, image, markers) -> None:
        """Paint optional VP labels after marker rasterization."""
        if not bool(getattr(self, "_placement_vp_names_visible", False)):
            return
        names = getattr(self, "_placement_vp_names", {}) or {}
        if not names:
            return
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            font = QFont("Segoe UI")
            font.setPixelSize(12)
            font.setBold(True)
            painter.setFont(font)
            for marker in markers:
                if str(getattr(marker, "kind", "")) != "vp":
                    continue
                key = self._placement_key_from_marker(marker)
                name = names.get(key)
                if not name:
                    continue
                marker_x, marker_y = self._placement_marker_position(marker)
                label_x = int(round(marker_x)) + 8
                label_y = int(round(marker_y)) + 4
                painter.setPen(QColor(20, 20, 20, 220))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    painter.drawText(label_x + dx, label_y + dy, name)
                painter.setPen(QColor(255, 255, 255, 240))
                painter.drawText(label_x, label_y, name)
        finally:
            painter.end()

    def _render_placement_context_overlay(self) -> None:
        """Render province borders and land/sea coastlines for placement mode."""
        context_item = getattr(self, "_placement_context_item", None)
        if context_item is None:
            return
        if not bool(getattr(self, "_placement_overlay_enabled", False)):
            context_item.setVisible(False)
            return
        try:
            province_map = np.asarray(self._province_map)
            tile_map = np.asarray(self._tile_map)
            if province_map.ndim != 2 or tile_map.ndim != 2:
                context_item.setVisible(False)
                return
            height, width = province_map.shape
            if tile_map.shape != province_map.shape or height <= 0 or width <= 0:
                context_item.setVisible(False)
                return

            province_borders = np.zeros((height, width), dtype=bool)
            province_borders[:-1, :] |= province_map[:-1, :] != province_map[1:, :]
            province_borders[:, :-1] |= province_map[:, :-1] != province_map[:, 1:]

            from data.constants import TILE_LAND
            land = tile_map == TILE_LAND
            coastlines = np.zeros((height, width), dtype=bool)
            coastlines[:-1, :] |= land[:-1, :] != land[1:, :]
            coastlines[:, :-1] |= land[:, :-1] != land[:, 1:]

            rgba = np.zeros((height, width, 4), dtype=np.uint8)
            terrain_map = np.asarray(getattr(self, "_terrain_map", ()))
            if (
                bool(getattr(self, "_placement_urban_overlay_visible", False))
                and terrain_map.shape == province_map.shape
            ):
                from data.terrain_types import TERRAIN_PALETTE_INDEX

                urban = terrain_map == TERRAIN_PALETTE_INDEX["urban"]
                # BGRA: translucent purple marks the graphical urban terrain
                # while leaving the underlying map visible.
                rgba[urban] = (180, 90, 210, 120)
            # QImage.Format_ARGB32 uses BGRA byte order here; neutral white
            # borders and a warm cyan coastline remain legible over regions.
            rgba[province_borders] = (225, 225, 225, 145)
            rgba[coastlines] = (210, 180, 20, 220)
            rgba = np.ascontiguousarray(rgba)
            image = QImage(
                rgba.data,
                width,
                height,
                width * 4,
                QImage.Format.Format_ARGB32,
            )
            image._ref = rgba
            context_item.setPixmap(QPixmap.fromImage(image.copy()))
            context_item.setVisible(True)
        except Exception:
            context_item.setVisible(False)
            return

    @staticmethod
    def _placement_key_from_marker(marker):
        """Convert a pure overlay marker key to a controller key."""
        kind = str(getattr(marker, "kind", ""))
        key = str(getattr(marker, "key", ""))
        parts = key.split(":")
        try:
            if kind == "slot" and len(parts) == 3 and parts[0] == "slot":
                if parts[1] == "?":
                    return None
                return (int(parts[1]), int(parts[2]))
            if kind == "port" and len(parts) == 2 and parts[0] == "port":
                return int(parts[1])
            if kind == "building" and len(parts) == 2 and parts[0] == "building":
                return int(parts[1])
            if kind == "weather" and len(parts) == 2 and parts[0] == "weather":
                return int(parts[1])
            if kind == "vp" and len(parts) == 2 and parts[0] == "vp":
                return int(parts[1])
        except (TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _placement_marker_is_editable(marker) -> bool:
        return str(getattr(marker, "kind", "")) in {
            "slot", "port", "building", "weather"
        }

    def _placement_marker_position(self, marker) -> tuple[float, float]:
        """Return a marker position, using the live drag preview if selected."""
        selected = getattr(self, "_placement_selected", None)
        preview = getattr(self, "_placement_preview_position", None)
        key = self._placement_key_from_marker(marker)
        if (
            selected is not None
            and preview is not None
            and key is not None
            and (str(getattr(marker, "kind", "")), key) == selected
        ):
            return (float(preview[0]), float(preview[1]))
        return (float(marker.x), float(marker.y))

    @staticmethod
    def _placement_marker_matches_filter(marker, filter_name: str) -> bool:
        kind = str(getattr(marker, "kind", ""))
        value = str(filter_name or "all").strip().lower()
        if value == "building":
            return kind in {"slot", "building"}
        if value == "port":
            return kind == "port"
        if value == "vp":
            return kind == "vp"
        return kind in {"slot", "port", "building", "weather", "vp"}

    def placement_marker_at(self, x: float, y: float):
        """Return ``(kind, key, x, y)`` for the nearest selectable marker."""
        if not bool(getattr(self, "_placement_overlay_enabled", False)):
            return None
        model = getattr(self, "_placement_overlay_model", None)
        if model is None:
            return None
        try:
            sx = float(x)
            sy = float(y)
            zoom = max(float(getattr(self, "_zoom", 1.0)), 1e-6)
        except (TypeError, ValueError, OverflowError):
            return None
        radius = max(6.0, 10.0 / zoom)
        best = None
        best_distance = radius * radius
        filter_name = getattr(self, "_placement_selection_filter", "all")
        for marker in getattr(model, "markers", ()):
            if not self._placement_marker_matches_filter(marker, filter_name):
                continue
            key = self._placement_key_from_marker(marker)
            if key is None:
                continue
            marker_x, marker_y = self._placement_marker_position(marker)
            distance = (sx - marker_x) ** 2 + (sy - marker_y) ** 2
            if distance <= best_distance:
                best_distance = distance
                best = (str(marker.kind), key, marker_x, marker_y)
        return best

    def _update_placement_selection_visual(self) -> None:
        item = getattr(self, "_placement_selection_item", None)
        if item is None:
            return
        selected = getattr(self, "_placement_selected", None)
        model = getattr(self, "_placement_overlay_model", None)
        if (
            not bool(getattr(self, "_placement_overlay_enabled", False))
            or selected is None
            or model is None
        ):
            item.setVisible(False)
            return
        for marker in getattr(model, "markers", ()):
            key = self._placement_key_from_marker(marker)
            if key is None:
                continue
            if (str(marker.kind), key) != selected:
                continue
            marker_x, marker_y = self._placement_marker_position(marker)
            item.setPos(marker_x, marker_y)
            item.setVisible(True)
            return
        item.setVisible(False)

    def _set_placement_selection(self, kind: str, key, *, emit: bool = True) -> None:
        selected = (str(kind), key)
        if getattr(self, "_placement_selected", None) == selected:
            self._update_placement_selection_visual()
            return
        self._placement_selected = selected
        self._placement_preview_position = None
        self._update_placement_selection_visual()
        if emit:
            self.placement_selection_changed.emit(str(kind), key)

    def _clear_placement_selection(self, *, emit: bool = True) -> None:
        had_selection = getattr(self, "_placement_selected", None) is not None
        self._placement_selected = None
        self._placement_drag_state = None
        self._placement_preview_position = None
        item = getattr(self, "_placement_selection_item", None)
        if item is not None:
            item.setVisible(False)
        if emit and had_selection:
            self.placement_selection_changed.emit("", None)

    def _begin_placement_drag(self, x: float, y: float) -> bool:
        hit = self.placement_marker_at(x, y)
        if hit is None:
            self._clear_placement_selection()
            return True
        kind, key, marker_x, marker_y = hit
        self._set_placement_selection(kind, key)
        if kind == "vp":
            # VPs are state data, so they can be selected for identification
            # but are not dragged through the placement controller.
            self._placement_drag_state = None
            self._placement_preview_position = None
            return True
        self._placement_drag_state = (kind, key, marker_x, marker_y)
        self._placement_preview_position = (marker_x, marker_y)
        return True

    def _update_placement_drag(self, x: float, y: float) -> bool:
        state = getattr(self, "_placement_drag_state", None)
        if state is None:
            return False
        try:
            preview_x = max(0.0, min(float(self.map_w - 1), float(x)))
            preview_y = max(0.0, min(float(self.map_h - 1), float(y)))
        except (TypeError, ValueError, OverflowError):
            return True
        self._placement_preview_position = (preview_x, preview_y)
        self._update_placement_selection_visual()
        return True

    def _finish_placement_drag(self) -> bool:
        state = getattr(self, "_placement_drag_state", None)
        preview = getattr(self, "_placement_preview_position", None)
        self._placement_drag_state = None
        self._placement_preview_position = None
        self._update_placement_selection_visual()
        if state is None or preview is None:
            return True
        kind, key, start_x, start_y = state
        if abs(float(preview[0]) - float(start_x)) <= 1e-9 and abs(float(preview[1]) - float(start_y)) <= 1e-9:
            return True
        self.placement_position_change_requested.emit(
            str(kind), key, float(preview[0]), float(preview[1])
        )
        return True
