"""Name Tag Overlay Mixin — State/country mode displays names on the map (HOI4 style).

Effect: The text is tilted along the main axis of the area. The larger the area, the larger the text. The vector text scales with the canvas without blurring.
Applicable: state mode displays the state name, country mode displays the country name.
Call: app_controller push provider → set_name_label_data(mode, provider);
     _update_name_labels_visibility() is called in _full_render to control visibility.
Lazy execution of typesetting: ID map construction + typesetting are postponed until "the overlay is visible and the 400ms anti-shake expires",
Each transaction attributable to editing only pays the cost of one lambda, and does not perform full graph calculations."""
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QPen, QBrush, QFont
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsSimpleTextItem

# Display mode with name tag
_LABEL_MODES = ("state", "country")
# After scaling, if the text height is less than this number of pixels, it will not be displayed (it cannot be read anyway, and it will cause confusion)
_MIN_TEXT_HEIGHT = 4.0


class NameLabelsMixin:
    """Assume self owns: _scene, _display_mode"""

    def _init_name_labels(self) -> None:
        self._name_label_data: dict = {}    # mode → provider() → (id_map, {id: name})
        self._name_label_dirty: dict = {}   # mode → bool
        self._name_label_items: dict = {}   # mode → list[QGraphicsSimpleTextItem]
        self._name_labels_enabled: dict = {m: True for m in _LABEL_MODES}  # Page switch
        self._name_label_timer = QTimer(self)
        self._name_label_timer.setSingleShot(True)
        self._name_label_timer.setInterval(400)
        self._name_label_timer.timeout.connect(self._update_name_labels_visibility)

    def set_name_label_data(self, mode: str, provider) -> None:
        """Receive data source provider() → (id_map, names), mark dirty and start anti-shake rearrangement.
        The provider is only called when the anti-shake expires and the mode is visible, ensuring no lag during editing."""
        self._name_label_data[mode] = provider
        self._name_label_dirty[mode] = True
        self._name_label_timer.start()

    def set_name_labels_enabled(self, mode: str, on: bool) -> None:
        """Page "Show Name" switch. Turning off only hides, data and layout cache are retained."""
        self._name_labels_enabled[mode] = bool(on)
        self._update_name_labels_visibility()

    def clear_name_labels(self) -> None:
        """Clear all labels when changing map data (old coordinates are meaningless)."""
        for items in self._name_label_items.values():
            for it in items:
                self._scene.removeItem(it)
        self._name_label_items.clear()
        self._name_label_data.clear()
        self._name_label_dirty.clear()

    def _update_name_labels_visibility(self) -> None:
        """It will only be displayed when the current pattern matches; it will be rearranged only when dirty data and anti-shake expires."""
        for mode in _LABEL_MODES:
            visible = (
                self._display_mode == mode
                and self._name_labels_enabled.get(mode, True)
            )
            if visible and self._name_label_dirty.get(mode):
                if self._name_label_timer.isActive():
                    continue  # Still within the anti-shake window, the timer will come in again at that point
                self._rebuild_name_labels(mode)
            for it in self._name_label_items.get(mode, []):
                it.setVisible(visible)

    def _rebuild_name_labels(self, mode: str) -> None:
        from domain.label_placement import compute_region_labels

        for it in self._name_label_items.get(mode, []):
            self._scene.removeItem(it)
        self._name_label_items[mode] = []
        self._name_label_dirty[mode] = False

        provider = self._name_label_data.get(mode)
        if provider is None:
            return
        id_map, names = provider()
        placements = compute_region_labels(id_map)

        font = QFont("Segoe UI")
        font.setPixelSize(24)
        font.setBold(True)
        brush = QBrush(QColor(255, 255, 255, 235))
        pen = QPen(QColor(20, 20, 20, 170))
        pen.setWidthF(0.8)

        items = []
        for rid, spots in placements.items():
            text = names.get(rid, "")
            if not text:
                continue
            # Put a name on each connected block in the area (enclaves/cut parts are labeled separately)
            for cx, cy, angle, length, width in spots:
                it = QGraphicsSimpleTextItem(text)
                it.setFont(font)
                it.setBrush(brush)
                it.setPen(pen)
                br = it.boundingRect()
                # The text covers ~70% of the long axis and does not exceed 90% of the short axis height
                s = min(
                    length * 0.7 / max(br.width(), 1.0),
                    width * 0.9 / max(br.height(), 1.0),
                )
                if br.height() * s < _MIN_TEXT_HEIGHT:
                    continue
                it.setTransformOriginPoint(br.center())
                it.setRotation(angle)
                it.setScale(s)
                it.setPos(cx - br.center().x(), cy - br.center().y())
                it.setZValue(6)
                # Cache rendering results: When dragging the canvas, the cached bitmap is pasted, and the vector text is not redrawn frame by frame.
                it.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
                it.setVisible(False)  # Unification of visibility and visibility is managed by _update_name_labels_visibility
                self._scene.addItem(it)
                items.append(it)
        self._name_label_items[mode] = items
