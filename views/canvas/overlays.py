"""Overlay Mixin — Province border/VP marker/Transform box/Lasso/Brush cursor
Split from canvas_widget.py"""
import numpy as np
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QPainterPath, QBrush,
)

# Modes that are allowed to be displayed by the country/state attribution overlay (those in which the base view itself is not colored by country/state).
# Modes that allow "Country Color + State Borders" overlays
# state/country itself has been colored according to ownership → overlay. In these two modes, only the border is drawn and no longer filled.
CS_OVERLAY_ALLOWED_MODES = frozenset({
    "land", "terrain", "height", "river", "province",
    "logistics", "colormap", "default_map", "province_terrain",
    "state", "country",
})

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
