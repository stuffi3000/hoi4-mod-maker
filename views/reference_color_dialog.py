"""Visual color-role editor for image-based map generation.

The dialog is shared by the land, province-outline, and hydrology import
actions.  It presents a compact quantized palette with swatches and pixel
counts, lets a color be assigned to one or more semantic roles, and returns a
small immutable selection object to the command handler.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.reference_map_service import (
    Color,
    ReferenceColor,
    extract_reference_colors_from_path,
    suggest_reference_color_mapping,
)
from ui.i18n import tr


OPERATION_ROLES = {
    "land": ("land", "sea", "lake"),
    "province": ("land_province", "sea_province"),
    "hydrology": ("lake", "river"),
}

ROLE_LABEL_KEYS = {
    "land": "reference_role_land",
    "sea": "reference_role_sea",
    "land_province": "reference_role_land_province",
    "sea_province": "reference_role_sea_province",
    "lake": "reference_role_lake",
    "river": "reference_role_river",
}


@dataclass(frozen=True)
class ReferenceColorSelection:
    """Colors selected for the active generator and their RGB tolerance."""

    colors: dict[str, list[Color]]
    tolerance: int = 18


class ReferenceColorMappingDialog(QDialog):
    """Show a reference image and assign discovered colors to generation roles."""

    def __init__(
        self,
        parent: QWidget | None,
        image_path: str | Path,
        operation: str,
        *,
        palette: list[ReferenceColor] | None = None,
    ) -> None:
        if operation not in OPERATION_ROLES:
            raise ValueError(f"Unknown reference color operation: {operation}")
        super().__init__(parent)
        self.image_path = Path(image_path)
        self.operation = operation
        self.active_roles = OPERATION_ROLES[operation]
        self.selection: ReferenceColorSelection | None = None

        if palette is None:
            rgb, palette = extract_reference_colors_from_path(self.image_path)
            self._suggestions = suggest_reference_color_mapping(
                rgb, operation, max_colors=max(2, len(palette))
            )
            del rgb
        else:
            # Suggestions still come from the image when a caller supplies a
            # custom palette.  Keeping this fallback cheap is useful in tests
            # and for embedders that already computed their own palette.
            self._suggestions = {
                role: [entry.rgb for entry in palette[:1]]
                for role in self.active_roles
            }
        self._palette = list(palette)

        self.setWindowTitle(tr("reference_color_editor_title"))
        self.setMinimumSize(900, 620)
        self.resize(1080, 760)
        self._build_ui()

    @classmethod
    def choose(
        cls,
        parent: QWidget | None,
        image_path: str | Path,
        operation: str,
    ) -> ReferenceColorSelection | None:
        """Open the modal editor and return its mapping, or ``None`` on cancel."""
        dialog = cls(parent, image_path, operation)
        if dialog.exec_() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selection

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        preview = QLabel()
        preview.setMinimumHeight(220)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setStyleSheet(
            "QLabel { background: #111217; border: 1px solid #2c2f36; "
            "border-radius: 5px; color: #9aa0ab; padding: 6px; }"
        )
        pixmap = QPixmap(str(self.image_path))
        if pixmap.isNull():
            preview.setText(tr("reference_color_editor_preview_unavailable"))
        else:
            preview.setPixmap(
                pixmap.scaled(
                    1040,
                    250,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        root.addWidget(preview)

        hint = QLabel(tr("reference_color_editor_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("labelDim")
        root.addWidget(hint)

        table = QTableWidget(0, 2 + len(self.active_roles))
        self._table = table
        table.setHorizontalHeaderLabels(
            [
                tr("reference_color_editor_color"),
                tr("reference_color_editor_pixels"),
                *[tr(ROLE_LABEL_KEYS[role]) for role in self.active_roles],
            ]
        )
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        # Keep the palette table readable when the global theme supplies a
        # light alternate-row background.  Explicit item/header colors avoid
        # white text disappearing on white rows in qdarktheme and native Qt
        # styles alike.
        table.setStyleSheet(
            """
            QTableWidget {
                background-color: #151a21;
                alternate-background-color: #222a35;
                color: #f3f6fa;
                gridline-color: #3c4654;
                border: 1px solid #3c4654;
                selection-background-color: #365f8a;
                selection-color: #ffffff;
            }
            QTableWidget::item {
                background-color: #151a21;
                color: #f3f6fa;
                padding: 4px 6px;
            }
            QTableWidget::item:alternate {
                background-color: #222a35;
                color: #f3f6fa;
            }
            QTableWidget::item:hover {
                background-color: #2b3b50;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #303a49;
                color: #ffffff;
                border: 1px solid #465160;
                padding: 6px;
                font-weight: 600;
            }
            QTableCornerButton::section {
                background-color: #303a49;
                border: 1px solid #465160;
            }
            """
        )
        palette = table.palette()
        palette.setColor(QPalette.Base, QColor("#151a21"))
        palette.setColor(QPalette.AlternateBase, QColor("#222a35"))
        palette.setColor(QPalette.Text, QColor("#f3f6fa"))
        palette.setColor(QPalette.WindowText, QColor("#f3f6fa"))
        palette.setColor(QPalette.Highlight, QColor("#365f8a"))
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.Button, QColor("#303a49"))
        palette.setColor(QPalette.ButtonText, QColor("#ffffff"))
        table.setPalette(palette)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 270)
        table.setColumnWidth(1, 110)
        for index in range(2, table.columnCount()):
            table.setColumnWidth(index, 155)
        self._role_columns = {
            role: 2 + index for index, role in enumerate(self.active_roles)
        }

        for row, entry in enumerate(self._palette):
            table.insertRow(row)
            color_item = QTableWidgetItem(
                f"#{entry.rgb[0]:02X}{entry.rgb[1]:02X}{entry.rgb[2]:02X}  "
                f"RGB({entry.rgb[0]}, {entry.rgb[1]}, {entry.rgb[2]})"
            )
            color_item.setIcon(self._swatch(entry.rgb))
            color_item.setData(Qt.ItemDataRole.UserRole, entry.rgb)
            table.setItem(row, 0, color_item)
            table.setItem(row, 1, QTableWidgetItem(f"{entry.count:,}"))
            for role, column in self._role_columns.items():
                role_item = QTableWidgetItem()
                role_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                )
                checked = entry.rgb in self._suggestions.get(role, [])
                role_item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
                role_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, column, role_item)
            table.setRowHeight(row, 30)
        root.addWidget(table, 1)

        settings = QWidget()
        settings_layout = QGridLayout(settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setColumnStretch(2, 1)
        tolerance_label = QLabel(tr("reference_color_editor_tolerance"))
        settings_layout.addWidget(tolerance_label, 0, 0)
        self._tolerance = QSpinBox()
        self._tolerance.setRange(0, 80)
        self._tolerance.setValue(18)
        self._tolerance.setSuffix(" RGB")
        self._tolerance.setToolTip(tr("reference_color_editor_tolerance_tip"))
        settings_layout.addWidget(self._tolerance, 0, 1)
        settings_layout.addWidget(
            QLabel(tr("reference_color_editor_palette_note")), 0, 2
        )
        root.addWidget(settings)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText(tr("reference_color_editor_apply"))
            ok_button.setDefault(True)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText(tr("reference_color_editor_cancel"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _swatch(color: Color):
        from PyQt5.QtGui import QIcon

        pixmap = QPixmap(22, 22)
        pixmap.fill(QColor(*color))
        return QIcon(pixmap)

    def _accept(self) -> None:
        mapping: dict[str, list[Color]] = {}
        for role, column in self._role_columns.items():
            selected: list[Color] = []
            for row, entry in enumerate(self._palette):
                item = self._table.item(row, column)
                if item is not None and item.checkState() == Qt.CheckState.Checked:
                    selected.append(entry.rgb)
            mapping[role] = selected

        if not any(mapping.values()):
            QMessageBox.warning(
                self,
                tr("reference_color_editor_title"),
                tr("reference_color_editor_no_selection"),
            )
            return
        if self.operation == "province" and not mapping.get("land_province"):
            QMessageBox.warning(
                self,
                tr("reference_color_editor_title"),
                tr("reference_color_editor_no_land_province"),
            )
            return
        self.selection = ReferenceColorSelection(
            mapping,
            int(self._tolerance.value()),
        )
        self.accept()
