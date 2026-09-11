"""Input event routing Mixin — mouse/keyboard event handling
Split from canvas_widget.py"""
from PyQt5.QtWidgets import QGraphicsView
from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import QMouseEvent, QWheelEvent

from data.constants import (
    TILE_SEA, TILE_LAKE,
    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP,
)
from data.terrain_types import TERRAIN_TYPES, PALETTE_TO_TYPE


class InputMixin:
    """Mouse/keyboard event handling methods. Assume that self owns all the state properties of the MapCanvas."""

    def _ensure_continuous_brush_timer(self):
        """Lazy initialization of the continuous brush timer (you can continue to draw even if you hold down the mouse)."""
        if not hasattr(self, "_continuous_brush_timer"):
            self._continuous_brush_timer = QTimer(self)
            self._continuous_brush_timer.setInterval(50)  # 50ms ≈ 20Hz, smooth and no lag
            self._continuous_brush_timer.timeout.connect(self._on_continuous_brush_tick)
            self._continuous_brush_pos: tuple[int, int] | None = None

    def _on_continuous_brush_tick(self):
        """timer trigger: draw a stroke at the last recorded position (used when the mouse is not moving)."""
        pos = getattr(self, "_continuous_brush_pos", None)
        if pos is None or not self._is_drawing:
            return
        sx, sy = pos
        if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
            self._paint_at(sx, sy)

    def _start_continuous_brush(self, sx: int, sy: int) -> None:
        """Starts a continuous brush (fires while held down)."""
        self._ensure_continuous_brush_timer()
        self._continuous_brush_pos = (sx, sy)
        self._continuous_brush_timer.start()

    def _stop_continuous_brush(self) -> None:
        """Stop the continuous brush (called when mouse is released)."""
        timer = getattr(self, "_continuous_brush_timer", None)
        if timer is not None:
            timer.stop()
        self._continuous_brush_pos = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        # Adjust the reference image mode: left click = drag the reference image, all other drawing interactions are intercepted
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

        # Frame selection mode interception
        if self._selection_mode and event.button() == Qt.MouseButton.LeftButton:
            sx, sy = self._scene_pos(event)
            self._selection_start = (int(sx), int(sy))
            self._selection_rect_item.setRect(QRectF(sx, sy, 0, 0))
            self._selection_rect_item.setVisible(True)
            event.accept()
            return

        # Ctrl+left click: drag and move the reference image
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.ControlModifier):
            self._ref_dragging = True
            self._ref_drag_start = event.pos()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
            return

        # Framework Tool Distribution (New Specification)
        if (event.button() == Qt.MouseButton.LeftButton
                and self._framework_tool is not None
                and not self._space_pressed):
            sx, sy = self._scene_pos(event)
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._framework_ctx.dirty_bbox = None
                # Snapshot before on_press: brush/fill both modify pixels on the
                # initial click, so recording afterwards would make that first
                # stamp impossible to undo.
                self.stroke_started.emit()
                self._framework_tool.begin_undo(self._framework_ctx)
                self._framework_tool.on_press(self._framework_ctx, sx, sy)
                self._is_drawing = True

                # Expansion tool visual feedback: allowed area overlay is displayed after selecting a province
                if self._framework_ctx.state.get("allowed_mask") is not None:
                    self._show_expand_overlay()

                self._render_province_overlay()
                event.accept()
                return

        if event.button() == Qt.MouseButton.LeftButton:
            if self._space_pressed or self._current_tool == "pan":
                self._is_panning = True
                self._pan_start = event.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return

            # Transform tool
            if self._current_tool == "transform" and self._display_mode == "land":
                sx, sy = self._scene_pos(event)

                if self._transform_active:
                    # Transform box already exists - determine click position
                    hit = self._hit_test_transform(sx, sy)
                    if hit:
                        self._transform_drag = hit
                        self._transform_drag_start = (sx, sy)
                        self._transform_box_start = tuple(self._transform_box)
                        self._transform_angle_start = self._transform_angle
                        if hit == "move":
                            self.setCursor(Qt.CursorShape.SizeAllCursor)
                        elif hit == "rotate":
                            self.setCursor(Qt.CursorShape.CrossCursor)
                        else:
                            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                        event.accept()
                        return
                    else:
                        # Click outside the far box = Confirm transformation
                        self._apply_transform()
                        self.stroke_ended.emit()
                        self._end_transform()
                        event.accept()
                        return

                # No transform box — start box selection
                self._transform_selecting = True
                self._selection_start = (int(sx), int(sy))
                self._selection_rect_item.setRect(QRectF(sx, sy, 0, 0))
                self._selection_rect_item.setVisible(True)
                self.stroke_started.emit()
                event.accept()
                return

            # Height mode + mountain line drawing: drag and collect points (but the height brush has higher priority - the user clicks the brush to indicate that he does not want to draw mountains)
            if (self._display_mode == "height"
                    and getattr(self, '_ridge_mode', False)
                    and getattr(self, '_height_brush_mode', 'off') == "off"):
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    self._is_drawing = True
                    self._ridge_drawing = True
                    self._ridge_path = [(int(sy), int(sx))]
                    # Initialize red line path preview
                    from PyQt5.QtGui import QPainterPath
                    path = QPainterPath()
                    path.moveTo(sx, sy)
                    self._ridge_path_item.setPath(path)
                    self._ridge_path_item.setVisible(True)
                    self.stroke_started.emit()
                event.accept()
                return

            # Terrain Mode + Selection Downgrade Lasso: Drag to collect closed polygons
            # (Historically, highly refined lasso also used this set of drawing codes. This function has been deleted and the variable names are retained.)
            _active_lasso = None
            if (self._display_mode == "terrain"
                    and getattr(self, '_downgrade_lasso_mode', False)):
                _active_lasso = "downgrade"
            if _active_lasso is not None:
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    self._is_drawing = True
                    self._refine_lasso_drawing = True
                    self._active_lasso_kind = _active_lasso
                    self._refine_lasso_path = [(int(sy), int(sx))]
                    from PyQt5.QtGui import QPainterPath
                    path = QPainterPath()
                    path.moveTo(sx, sy)
                    self._refine_lasso_item.setPath(path)
                    self._refine_lasso_item.setVisible(True)
                    self.stroke_started.emit()
                event.accept()
                return

            # Terrain/Height/State/Country/Logistics/Strategic Area/Attribute Terrain Mode: Click on the province → entrust the controller to handle it
            if self._display_mode in ("terrain", "height", "state", "country",
                                       "province_terrain", "logistics", "strategic_region",
                                       "continent"):
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    pid = int(self._province_map[sy, sx])
                    # Height brush mode: lift/sink/smooth pixel by pixel (handled even if falling on pid=0, e.g. new land)
                    if (self._display_mode == "height"
                            and getattr(self, '_height_brush_mode', 'off') != "off"):
                        self._is_drawing = True
                        self.stroke_started.emit()
                        self._paint_at(sx, sy)
                        event.accept()
                        return
                    if pid > 0:
                        # Terrain Brush Mode: Draw pixel by pixel + hold down the mouse and continue drawing
                        if self._display_mode == "terrain" and self._terrain_brush_mode:
                            self._is_drawing = True
                            self.stroke_started.emit()
                            self._paint_at(sx, sy)
                            self._start_continuous_brush(sx, sy)
                            event.accept()
                            return
                        self.province_clicked.emit(pid)
                        # Drag-and-drop assignment mode: start dragging (controller internally presses assign_mode to decide whether to write)
                        if self._display_mode in (
                            "state", "country", "strategic_region", "continent",
                            "province_terrain",
                        ):
                            self._assign_dragging = True
                            self._assign_drag_seen = {pid}
                event.accept()
                return

            # Province mode + cutting mode: rotating line cutting
            if self._display_mode == "province" and getattr(self, '_split_mode', False):
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    pid = int(self._province_map[int(sy), int(sx)])
                    if pid > 0:
                        if getattr(self, '_split_ready', False):
                            # Click to confirm cutting - transmit center of mass, direction, mouse click position
                            import math
                            self._split_ready = False
                            self._split_line_item.setVisible(False)
                            angle = getattr(self, '_split_angle', 0.0)
                            self.split_line_drawn.emit(self._split_pid, [
                                (self._split_cy, self._split_cx),
                                (int(self._split_cy + 9999 * math.sin(angle)),
                                 int(self._split_cx + 9999 * math.cos(angle))),
                                (int(sy), int(sx)),  # Mouse click position → cut out this side
                            ])
                        else:
                            # Click on province → Initialize cutting preview
                            self._init_split_preview(pid)
                event.accept()
                return

            # Province mode: left-click only to select (expansion requires lasso framework tool, direct dragging to change boundaries is not allowed)
            if self._display_mode == "province":
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    pid = int(self._province_map[int(sy), int(sx)])
                    if pid > 0:
                        additive = bool(
                            event.modifiers()
                            & (Qt.ControlModifier | Qt.ShiftModifier)
                        )
                        self.select_province(
                            pid,
                            int(self._tile_map[int(sy), int(sx)]),
                            additive=additive,
                        )
                        self.province_clicked.emit(pid)
                        self._render_province_overlay()
                event.accept()
                return

            # River Mode: Brush Drawing
            if self._display_mode == "river":
                if self._current_tool in ("brush", "eraser"):
                    self._is_drawing = True
                    self.stroke_started.emit()
                    sx, sy = self._scene_pos(event)
                    # Automatic river source: In brush mode, if the starting point is not on an existing river,
                    # Automatically place a source marker (0=green) at the starting point to ensure that the drawn river is legal.
                    # HOI4 Rules: Rivers without sources are not rendered by the engine (Paradox wiki Map modding §721)
                    if (self._current_tool == "brush"
                        and self._current_river_type not in (0, 1, 2)
                        and 0 <= sx < self.map_w and 0 <= sy < self.map_h):
                        from domain.managers.river import VALID_RIVER_VALUES
                        val = int(self._river_map[sy, sx])
                        if val not in VALID_RIVER_VALUES:
                            # Temporarily cut the source to draw, and then cut it back to the original width.
                            orig_type = self._current_river_type
                            self._current_river_type = 0
                            self._stamp_brush(sx, sy)
                            self._current_river_type = orig_type
                            # To avoid the diagonal between the next step and the source, _last_draw_pos is set to the source position
                            self._last_draw_pos = (sx, sy)
                            event.accept()
                            return
                    self._paint_at(sx, sy)
                    event.accept()
                    return

            if self._current_tool in ("brush", "eraser", "new_land"):
                # Province has been generated → Brush/eraser flick first to confirm (borders will be misaligned).
                # Expanding the land is not blocked: it is designed for the incremental generation process of existing provinces.
                if (self._current_tool != "new_land"
                        and not self._confirm_land_paint()):
                    event.accept()
                    return
                self._is_drawing = True
                self.stroke_started.emit()
                sx, sy = self._scene_pos(event)
                self._paint_at(sx, sy)
                event.accept()
                return

            if self._current_tool == "fill":
                if not self._confirm_land_paint():
                    event.accept()
                    return
                self.stroke_started.emit()
                sx, sy = self._scene_pos(event)
                self._flood_fill(sx, sy)
                self.stroke_ended.emit()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        sx, sy = self._scene_pos(event)
        if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
            self.mouse_moved.emit(sx, sy)
            self._update_brush_cursor(sx, sy)
            # Update the position of the continuous brush (when the mouse moves, the latest position is used, when the mouse is stopped, the timer uses the remembered position to repaint)
            if getattr(self, "_continuous_brush_pos", None) is not None:
                self._continuous_brush_pos = (sx, sy)
        else:
            self._brush_cursor.setVisible(False)

        # Transform tool selection drag
        if self._transform_selecting and self._selection_start:
            x0, y0 = self._selection_start
            x1 = max(0, min(self.map_w, int(sx)))
            y1 = max(0, min(self.map_h, int(sy)))
            rx0, ry0 = min(x0, x1), min(y0, y1)
            rx1, ry1 = max(x0, x1), max(y0, y1)
            self._selection_rect = (rx0, ry0, rx1, ry1)
            self._selection_rect_item.setRect(QRectF(rx0, ry0, rx1 - rx0, ry1 - ry0))
            event.accept()
            return

        # Transform tool drag (move/zoom)
        if self._transform_drag and self._transform_box:
            dx = sx - self._transform_drag_start[0]
            dy = sy - self._transform_drag_start[1]
            bx0, by0, bx1, by1 = self._transform_box_start

            if self._transform_drag == "move":
                self._transform_box = (bx0 + dx, by0 + dy, bx1 + dx, by1 + dy)
            elif self._transform_drag == "rotate":
                # Taking the center of the box as the origin, calculate the difference between the starting angle and the current angle
                import math
                cx = (bx0 + bx1) / 2
                cy = (by0 + by1) / 2
                start_angle = math.atan2(
                    self._transform_drag_start[1] - cy,
                    self._transform_drag_start[0] - cx,
                )
                cur_angle = math.atan2(sy - cy, sx - cx)
                delta_deg = math.degrees(cur_angle - start_angle)
                self._transform_angle = self._transform_angle_start + delta_deg
            elif self._transform_drag == "tl":
                self._transform_box = (bx0 + dx, by0 + dy, bx1, by1)
            elif self._transform_drag == "tr":
                self._transform_box = (bx0, by0 + dy, bx1 + dx, by1)
            elif self._transform_drag == "bl":
                self._transform_box = (bx0 + dx, by0, bx1, by1 + dy)
            elif self._transform_drag == "br":
                self._transform_box = (bx0, by0, bx1 + dx, by1 + dy)

            self._update_transform_visuals()

            # Live preview
            self._apply_transform()

            event.accept()
            return

        # Drag and drop in frame selection mode
        if self._selection_mode and self._selection_start:
            x0, y0 = self._selection_start
            x1, y1 = max(0, min(self.map_w, int(sx))), max(0, min(self.map_h, int(sy)))
            rx0, ry0 = min(x0, x1), min(y0, y1)
            rx1, ry1 = max(x0, x1), max(y0, y1)
            self._selection_rect = (rx0, ry0, rx1, ry1)
            self._selection_rect_item.setRect(QRectF(rx0, ry0, rx1 - rx0, ry1 - ry0))
            event.accept()
            return

        # Drag and drop to move the reference map (Ctrl+drag = custom map; adjustment mode = current adjustment object)
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

        if self._is_panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        # Drag and drop allocation mode (continent/state/country/strategic area)
        if getattr(self, '_assign_dragging', False):
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                pid = int(self._province_map[int(sy), int(sx)])
                if pid > 0 and pid not in self._assign_drag_seen:
                    self._assign_drag_seen.add(pid)
                    self.province_clicked.emit(pid)
            event.accept()
            return

        # Framework tool distribution
        if self._is_drawing and self._framework_tool is not None:
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._framework_tool.on_drag(self._framework_ctx, sx, sy)
                # Continuously refresh the canvas during dragging to allow users to see the expansion effect
                if self._framework_ctx.state.get("painting"):
                    brush_radius = max(10, int(self._framework_ctx.brush_size) // 2 + 2)
                    self._mark_dirty(
                        max(0, sx - brush_radius), max(0, sy - brush_radius),
                        min(self.map_w, sx + brush_radius + 1),
                        min(self.map_h, sy + brush_radius + 1),
                    )
                    self._flush_dirty()
                    self._render_province_overlay()
                event.accept()
                return

        # Mountain line drawing is being dragged
        if getattr(self, '_ridge_drawing', False) and self._is_drawing:
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._ridge_path.append((int(sy), int(sx)))
                # Real-time extended redline preview
                current_path = self._ridge_path_item.path()
                current_path.lineTo(sx, sy)
                self._ridge_path_item.setPath(current_path)
            event.accept()
            return

        # Partial finishing lasso dragging
        if getattr(self, '_refine_lasso_drawing', False) and self._is_drawing:
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._refine_lasso_path.append((int(sy), int(sx)))
                current_path = self._refine_lasso_item.path()
                current_path.lineTo(sx, sy)
                self._refine_lasso_item.setPath(current_path)
            event.accept()
            return

        # Cut rotation line - angle updated with mouse movement
        if getattr(self, '_split_ready', False):
            import math
            cx, cy = self._split_cx, self._split_cy
            angle = math.atan2(sy - cy, sx - cx)
            self._split_angle = angle
            self._update_split_rotate_preview()
            event.accept()
            return

        # Height brush drag
        if (self._is_drawing and self._display_mode == "height"
                and getattr(self, '_height_brush_mode', 'off') != "off"):
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._paint_at(sx, sy)
            event.accept()
            return

        if self._is_drawing and self._current_tool in ("brush", "eraser", "new_land"):
            self._paint_at(sx, sy)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # Transform tool box selection completed - activate transform box
        if self._transform_selecting and self._selection_start:
            self._transform_selecting = False
            self._selection_start = None
            self._selection_rect_item.setVisible(False)
            if self._selection_rect:
                x0, y0, x1, y1 = self._selection_rect
                if x1 - x0 > 5 and y1 - y0 > 5:
                    # Cut selection content
                    from data.constants import TILE_SEA
                    self._transform_snippet = self._tile_map[y0:y1, x0:x1].copy()
                    self._transform_orig_box = (x0, y0, x1, y1)
                    self._transform_box = (float(x0), float(y0), float(x1), float(y1))
                    # Clear original location
                    self._tile_map[y0:y1, x0:x1] = TILE_SEA
                    self._full_render()
                    self._transform_active = True
                    self._update_transform_visuals()
            self._selection_rect = None
            event.accept()
            return

        # Transform tool drag and release
        if self._transform_drag:
            self._transform_drag = None
            self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return

        # Frame selection completed
        if self._selection_mode and self._selection_start:
            self._selection_start = None
            self._finish_selection()
            event.accept()
            return

        # End reference image dragging
        if getattr(self, '_ref_dragging', False):
            self._ref_dragging = False
            self.setCursor(Qt.CursorShape.SizeAllCursor
                           if self._ref_adjust_target is not None
                           else Qt.CursorShape.CrossCursor)
            event.accept()
            return

        # End drag assignment
        if getattr(self, '_assign_dragging', False):
            self._assign_dragging = False
            self._assign_drag_seen = set()
            event.accept()
            return

        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            if self._is_panning:
                self._is_panning = False
                self.setCursor(Qt.CursorShape.CrossCursor if self._current_tool != "pan"
                              else Qt.CursorShape.OpenHandCursor)
                event.accept()
                return
            if self._is_drawing:
                self._is_drawing = False
                self._last_draw_pos = None  # Clear interpolation start point
                self._stop_continuous_brush()  # Mouse release stops continuous brush timer

                # Mountain line drawing release → Send signal to MainWindow for processing
                if getattr(self, '_ridge_drawing', False):
                    self._ridge_drawing = False
                    path = getattr(self, '_ridge_path', [])
                    # Hide red lines (show preview mountains next)
                    self._ridge_path_item.setVisible(False)
                    if len(path) >= 2:
                        self.ridge_drawn.emit(path)
                    self._ridge_path = []
                    self.stroke_ended.emit()
                    event.accept()
                    return

                # Lasso release → Close polygon → Signal selection downgrade
                if getattr(self, '_refine_lasso_drawing', False):
                    self._refine_lasso_drawing = False
                    path = getattr(self, '_refine_lasso_path', [])
                    # Closure: Connect the last point back to the starting point
                    if len(path) >= 3:
                        current_path = self._refine_lasso_item.path()
                        current_path.lineTo(path[0][1], path[0][0])
                        self._refine_lasso_item.setPath(current_path)
                    self._refine_lasso_item.setVisible(False)
                    if len(path) >= 3:
                        self.downgrade_lasso_drawn.emit(path)
                    self._refine_lasso_path = []
                    self._active_lasso_kind = None
                    self.stroke_ended.emit()
                    event.accept()
                    return

                # (Click to confirm cutting mode, no need to release)

                # Framework tools: release first, then clean, then end_undo, and finally refresh
                if self._framework_tool is not None:
                    sx, sy = self._scene_pos(event)
                    self._framework_tool.on_release(self._framework_ctx, sx, sy)
                    self._framework_tool.run_cleanup(self._framework_ctx)
                    self._framework_tool.end_undo(self._framework_ctx)
                    # Synchronize the selected state to canvas
                    selected_tile = self._framework_ctx.state.get("tile")
                    self.select_province(
                        self._framework_ctx.selected_province_id,
                        int(selected_tile) if selected_tile is not None else None,
                        additive=False,
                    )
                    # Overlay follows: If there is still pid, keep it displayed, otherwise clear it.
                    if self._framework_ctx.state.get("allowed_mask") is not None:
                        self._show_expand_overlay()
                    else:
                        self._clear_lasso_visual()
                    # Clear boundary cache + full refresh
                    self._border_cache = None
                    if hasattr(self, '_border_base_pixmap'):
                        self._border_base_pixmap = None
                    self._full_render()
                    if self._display_mode == "province":
                        self._render_province_overlay()
                    # Detect province ID holes (expansion may swallow entire neighbors)
                    import numpy as np
                    pm = self._province_map
                    max_id = int(pm.max())
                    existing = set(np.unique(pm)) - {0}
                    gap_ids = sorted(set(range(1, max_id + 1)) - existing)
                    self.province_gaps_detected.emit(gap_ids)
                    self.stroke_ended.emit()
                    if (self._selected_province_id > 0
                            and self._selected_province_id in existing):
                        self.province_clicked.emit(self._selected_province_id)
                    event.accept()
                    return

                self._flush_dirty()
                # After dragging in province mode: only the boundaries are refreshed and no re-cleaning is performed.
                if self._display_mode == "province":
                    self._render_province_overlay()
                # Refresh overlay after density brush ends
                if getattr(self, '_density_overlay_visible', False):
                    self._render_density_overlay()
                self.stroke_ended.emit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Double click on province → Set VP (all modes, but not triggering the brush)"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Adjust reference map mode: double-click does not trigger province VP settings
            if self._ref_adjust_target is not None:
                event.accept()
                return
            # Prevent double-click from triggering brush
            self._is_drawing = False
            self._last_draw_pos = None
            sx, sy = self._scene_pos(event)
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                pid = int(self._province_map[sy, sx])
                if pid > 0:
                    self.province_double_clicked.emit(pid)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        """Right-click on a province → pop up context menu (all modes)"""
        # Adjust the reference map mode: do not pop up the province right-click menu
        if self._ref_adjust_target is not None:
            event.accept()
            return
        pos = self.mapToScene(event.pos())
        sx, sy = int(pos.x()), int(pos.y())
        if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
            pid = int(self._province_map[sy, sx])
            if pid > 0:
                if self._display_mode == "province":
                    selected = self.selected_province_ids()
                    if pid not in selected:
                        self.select_province(
                            pid, int(self._tile_map[sy, sx]), additive=False
                        )
                        self._render_province_overlay()
                self.province_right_clicked.emit(pid)
                # Pass screen coordinates for pop-up menu positioning
                global_pos = self.mapToGlobal(event.pos())
                self.province_right_clicked_at.emit(pid, global_pos.x(), global_pos.y())
                return
        super().contextMenuEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Adjust reference image mode: Wheel = zoom the adjusted reference image
        if self._ref_adjust_target is not None:
            delta = event.angleDelta().y()
            step = 0.1 if delta > 0 else -0.1
            target = self._ref_adjust_target
            self.set_ref_layer_scale(target, self._ref_layers[target].scale + step)
            self.ref_adjust_scale_changed.emit(target, self._ref_layers[target].scale)
            event.accept()
            return

        # Ctrl+scroll wheel: zoom reference image
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            scale_step = 0.1 if delta > 0 else -0.1
            new_scale = self._ref_layers[self.REF_CUSTOM].scale + scale_step
            self.set_ref_scale(new_scale)
            event.accept()
            return

        factor = ZOOM_STEP if event.angleDelta().y() > 0 else 1.0 / ZOOM_STEP
        new_zoom = self._zoom * factor
        if ZOOM_MIN <= new_zoom <= ZOOM_MAX:
            self._zoom = new_zoom
            self.scale(factor, factor)
            self.zoom_changed.emit(self._zoom)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = True
            if not self._is_drawing:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
        # ESC: Cancel an ongoing Lasso/Frame tool operation
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Enter to confirm the transformation
            if self._transform_active:
                self._apply_transform()
                self.stroke_ended.emit()
                self._end_transform()
                return
        elif event.key() == Qt.Key.Key_Escape:
            # ESC exits the adjustment reference image mode
            if self._ref_adjust_target is not None:
                self.set_ref_adjust_mode(None)
                self.ref_adjust_exited.emit()
                return
            # ESC cancels transformation
            if self._transform_active:
                self._cancel_transform()
                self.stroke_ended.emit()
                return
            if self._is_drawing and self._framework_tool is not None:
                self._framework_tool.on_cancel(self._framework_ctx)
                self._is_drawing = False
                self._clear_lasso_visual()
                # Does not enter the undo stack (because it is cancelled, pending is discarded directly)
                self._framework_ctx.undo_mgr._pending = None
                self.stroke_ended.emit()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            if not self._is_panning:
                self.setCursor(Qt.CursorShape.CrossCursor if self._current_tool != "pan"
                              else Qt.CursorShape.OpenHandCursor)
        super().keyReleaseEvent(event)

    def _init_split_preview(self, pid: int) -> None:
        """Initialize cutting preview: calculate province centroid and bbox, display line."""
        import numpy as np
        mask = self._province_map == pid
        ys, xs = np.where(mask)
        if len(ys) == 0:
            return
        self._split_pid = pid
        self._split_cy = int(np.mean(ys))
        self._split_cx = int(np.mean(xs))
        self._split_bbox = (int(ys.min()), int(xs.min()),
                            int(ys.max()), int(xs.max()))
        self._split_angle = 0.0
        self._split_ready = True
        self._update_split_rotate_preview()

    def _update_split_rotate_preview(self) -> None:
        """Real-time update of cutting rotation line preview. The line passes through the province centroid and its length covers the bbox."""
        import math
        from PyQt5.QtGui import QPainterPath

        cx = self._split_cx
        cy = self._split_cy
        angle = getattr(self, '_split_angle', 0.0)
        y0, x0, y1, x1 = self._split_bbox

        # Line length = bbox diagonal, ensuring it passes completely through the province
        diag = math.sqrt((y1 - y0) ** 2 + (x1 - x0) ** 2) / 2 + 10
        dx = diag * math.cos(angle)
        dy = diag * math.sin(angle)

        pp = QPainterPath()
        pp.moveTo(cx - dx, cy - dy)
        pp.lineTo(cx + dx, cy + dy)
        self._split_line_item.setPath(pp)
        self._split_line_item.setVisible(True)
