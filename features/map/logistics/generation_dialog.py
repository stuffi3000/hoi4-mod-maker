"""Preview and apply map/reference logistics generation."""
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QCheckBox, QFileDialog, QColorDialog, QMessageBox,
)
from domain.generators.logistics import (
    LogisticsGenerationError, generate_logistics, reference_route_mask,
)
from commands.map.generate_logistics import GenerateLogisticsCommand
from ui.i18n import tr


class LogisticsGenerationDialog(QDialog):
    def __init__(self, project, history, parent=None):
        super().__init__(parent)
        self.project, self.history = project, history
        self.proposal = None
        self.path = ""
        self.color = QColor("#ff0000")
        self.setWindowTitle(tr("logistics_generate_title"))
        self.resize(480, 380)
        layout = QVBoxLayout(self)
        hint = QLabel(tr("logistics_generate_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        layout.addLayout(form)
        self.source = QComboBox()
        self.source.addItems([tr("logistics_generate_source_map"), tr("logistics_generate_reference")])
        form.addRow(tr("logistics_generate_source"), self.source)
        self.file_button = QPushButton(tr("logistics_generate_choose_reference"))
        self.file_button.clicked.connect(self._choose_file)
        form.addRow(self.file_button)
        hint = QLabel(tr("logistics_generate_reference_help"))
        hint.setWordWrap(True)
        form.addRow(hint)
        self.color_button = QPushButton(tr("logistics_generate_color", "#ff0000"))
        self.color_button.clicked.connect(self._choose_color)
        form.addRow(self.color_button)
        self.tolerance = QSpinBox()
        self.tolerance.setRange(0, 255)
        self.tolerance.setValue(40)
        form.addRow(tr("logistics_generate_tolerance"), self.tolerance)
        self.level = QSpinBox()
        self.level.setRange(1, 5)
        self.level.setValue(3)
        form.addRow(tr("logistics_generate_level"), self.level)
        self.supply = QCheckBox(tr("logistics_generate_supply"))
        self.supply.setChecked(True)
        form.addRow(self.supply)
        self.replace = QCheckBox(tr("logistics_generate_replace"))
        form.addRow(self.replace)
        self.summary = QLabel(tr("logistics_generate_waiting"))
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        preview = QPushButton(tr("logistics_generate_preview"))
        preview.clicked.connect(self._preview)
        layout.addWidget(preview)
        self.apply_button = QPushButton(tr("logistics_generate_apply"))
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        layout.addWidget(self.apply_button)
        self.source.currentIndexChanged.connect(self._invalidate)
        self.tolerance.valueChanged.connect(self._invalidate)
        self.level.valueChanged.connect(self._invalidate)
        self.supply.toggled.connect(self._invalidate)
        self.replace.toggled.connect(self._invalidate)

    def _invalidate(self, *_):
        self.proposal = None
        self.apply_button.setEnabled(False)
        self.summary.setText(tr("logistics_generate_changed"))

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("logistics_generate_reference_title"), "", "Images (*.png *.jpg *.jpeg *.bmp *.tga)")
        if path:
            self.path = path
            self.file_button.setText(path)
            self.source.setCurrentIndex(1)
            self._invalidate()

    def _choose_color(self):
        color = QColorDialog.getColor(self.color, self)
        if color.isValid():
            self.color = color
            self.color_button.setText(tr("logistics_generate_color", color.name()))
            self._invalidate()

    def _preview(self):
        self._invalidate()
        try:
            mask = None
            if self.source.currentIndex() == 1:
                if not self.path:
                    raise ValueError("Choose an aligned reference image first.")
                mask = reference_route_mask(self.path, self.project.map_data.province_map.shape,
                                            self.color.getRgb()[:3], self.tolerance.value())
            self.proposal = generate_logistics(self.project, mask)
            self.summary.setText(tr(
                "logistics_generate_summary", edges=len(self.proposal.edges),
                hubs=len(self.proposal.hubs) if self.supply.isChecked() else 0))
            self.apply_button.setEnabled(bool(self.proposal.edges or
                                               (self.supply.isChecked() and self.proposal.hubs)))
        except (ValueError, OSError) as exc:
            message = (tr(f"logistics_generate_error_{exc.code}")
                       if isinstance(exc, LogisticsGenerationError) else str(exc))
            QMessageBox.warning(self, tr("logistics_generate_error"), message)

    def _apply(self):
        if self.proposal is not None:
            self.history.execute(GenerateLogisticsCommand(
                self.project, self.proposal, self.level.value(),
                self.supply.isChecked(), self.replace.isChecked()))
            self.accept()
