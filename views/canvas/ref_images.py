"""Reference map management Mixin — user reference map + original map reference layer
The two pictures share the same "reference layer" structure, and are independent of each other: loading/transparency/zoom/move/show/hide.
The old method names remain as thin wrappers, existing calls to main_window / input_router are not affected."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem


class RefLayer:
    """Single reference layer: scene item + original pixmap + current zoom ratio."""

    def __init__(self, item: QGraphicsPixmapItem):
        self.item = item
        self.original = QPixmap()
        self.scale = 1.0


class RefImageMixin:
    """Reference diagram related methods. Assume self owns:
    - _ref_layers: dict[str, RefLayer] (key: REF_CUSTOM / REF_VANILLA)
    - map_w/map_h/_show_ref_image"""

    REF_CUSTOM = "custom"
    REF_VANILLA = "vanilla"

    # ── Universal layer interface ─────────────────────────────────

    def load_ref_layer(self, key: str, file_path: str, fit: bool = False) -> bool:
        """Load a reference image. When fit=True, the image is scaled to fit exactly into the map (without stretching or deformation)."""
        layer = self._ref_layers[key]
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            return False
        layer.original = pixmap
        if fit:
            # Contain: Take the smaller of the scaling ratios in the width and height directions, without deformation
            scale = min(self.map_w / pixmap.width(),
                        self.map_h / pixmap.height())
            self.set_ref_layer_scale(key, scale)
            # Automatic scaling changed the scale and wrote back the page slider (main_window has received this signal)
            self.ref_adjust_scale_changed.emit(key, layer.scale)
            shown = layer.item.pixmap()
            layer.item.setPos(
                (self.map_w - shown.width()) / 2,
                (self.map_h - shown.height()) / 2,
            )
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
        """Scale the reference map (1.0 = original size), based on the original pixmap."""
        layer = self._ref_layers[key]
        scale = max(0.1, min(10.0, scale))
        layer.scale = scale
        if not layer.original.isNull():
            scaled = layer.original.scaled(
                int(layer.original.width() * scale),
                int(layer.original.height() * scale),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            layer.item.setPixmap(scaled)
        if getattr(self, '_ref_adjust_target', None) == key:
            self._update_ref_adjust_border()

    def move_ref_layer(self, key: str, dx: float, dy: float) -> None:
        item = self._ref_layers[key].item
        pos = item.pos()
        item.setPos(pos.x() + dx, pos.y() + dy)
        if getattr(self, '_ref_adjust_target', None) == key:
            self._update_ref_adjust_border()

    def toggle_ref_layer(self, key: str, visible: bool) -> None:
        self._ref_layers[key].item.setVisible(visible)

    # ── Compatible with old interfaces (main_window / input_router / old test) ──

    def load_reference_image(self, file_path: str) -> bool:
        ok = self.load_ref_layer(self.REF_CUSTOM, file_path)
        if ok:
            self._ref_layers[self.REF_CUSTOM].item.setVisible(self._show_ref_image)
        return ok

    def load_vanilla_reference(self, file_path: str) -> bool:
        """Load the original map reference (independent of the user reference map, scaled and centered)."""
        return self.load_ref_layer(self.REF_VANILLA, file_path, fit=True)

    def set_vanilla_ref_opacity(self, opacity: float) -> None:
        self.set_ref_layer_opacity(self.REF_VANILLA, opacity)

    def toggle_vanilla_ref(self, visible: bool) -> None:
        self.toggle_ref_layer(self.REF_VANILLA, visible)

    def set_ref_opacity(self, opacity: float) -> None:
        self.set_ref_layer_opacity(self.REF_CUSTOM, opacity)

    def set_ref_scale(self, scale: float) -> None:
        self.set_ref_layer_scale(self.REF_CUSTOM, scale)

    def move_ref_image(self, dx: int, dy: int) -> None:
        self.move_ref_layer(self.REF_CUSTOM, dx, dy)

    def toggle_ref_image(self, visible: bool) -> None:
        self._show_ref_image = visible
        self.toggle_ref_layer(self.REF_CUSTOM, visible)

    # ── Adjust reference image mode ──────────────────────────────

    def set_ref_adjust_mode(self, target: str | None) -> None:
        """Enter/exit the adjustment reference image mode. target=None exits and resumes drawing."""
        self._ref_adjust_target = target
        if target is None:
            self._ref_adjust_border.setVisible(False)
            self.setCursor(Qt.CursorShape.CrossCursor if self._current_tool != "pan"
                           else Qt.CursorShape.OpenHandCursor)
            # The drag mark must be cleared when exiting adjustment mode: otherwise _ref_dragging will occur after ESC interrupts dragging.
            # Still True, the next mouseMoveEvent will fallback to REF_CUSTOM and drag the custom image by mistake.
            self._ref_dragging = False
        else:
            self._update_ref_adjust_border()
            self._ref_adjust_border.setVisible(True)
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def _update_ref_adjust_border(self) -> None:
        """The dotted frame affixes the currently adjusted reference image."""
        if self._ref_adjust_target is None:
            return
        item = self._ref_layers[self._ref_adjust_target].item
        self._ref_adjust_border.setRect(item.sceneBoundingRect())
