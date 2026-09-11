"""Welcome page - displayed at startup, providing entry to new/open/recent projects."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QDialog,
    QSpinBox, QDialogButtonBox, QFormLayout,
)
from PyQt5.QtCore import pyqtSignal, Qt, QSettings
from PyQt5.QtGui import QFont

from ui.i18n import tr


# ── Color palette (consistent with ui/styles.py) ──
_BG = "#17181c"
_INPUT_BG = "#1f2126"
_BORDER = "#2c2f36"
_TEXT = "#e8eaed"
_DIM = "#9aa0ab"
_ACCENT = "#4f8cff"
_ACCENT_HOVER = "#6ba1ff"

_MAX_RECENT = 10


def _load_recent_projects() -> list[str]:
    """Read the list of recent items from QSettings."""
    settings = QSettings("HOI4MapMaker", "RecentProjects")
    paths = settings.value("paths", [])
    if isinstance(paths, str):
        return [paths] if paths else []
    return list(paths or [])


def save_recent_project(path: str) -> None:
    """Add path to recent items list (duplicate, limited quantity)."""
    recent = _load_recent_projects()
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    recent = recent[:_MAX_RECENT]
    settings = QSettings("HOI4MapMaker", "RecentProjects")
    settings.setValue("paths", recent)


class _SizePickerDialog(QDialog):
    """Map size selection dialog."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("welcome_size_picker_title"))
        self.setMinimumSize(300, 160)
        self.resize(300, 160)

        layout = QFormLayout(self)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(256, 16384)
        self._width_spin.setValue(5632)
        self._width_spin.setSingleStep(256)
        layout.addRow(tr("welcome_width"), self._width_spin)

        self._height_spin = QSpinBox()
        self._height_spin.setRange(256, 16384)
        self._height_spin.setValue(2048)
        self._height_spin.setSingleStep(256)
        layout.addRow(tr("welcome_height"), self._height_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @property
    def chosen_size(self) -> tuple[int, int]:
        return self._width_spin.value(), self._height_spin.value()


class WelcomePage(QWidget):
    """Start the welcome page, create new/open/recent projects."""

    new_project_requested = pyqtSignal(int, int)   # width, height
    open_project_requested = pyqtSignal()
    open_recent_requested = pyqtSignal(str)         # path
    import_mod_requested = pyqtSignal()              # Import MOD map
    open_vanilla_requested = pyqtSignal()            # Open the original game map (read-only reference)
    language_changed = pyqtSignal(str)               # retained for compatibility; always "en"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"WelcomePage {{ background: {_BG}; }}")
        self._init_ui()

    _CARD_WIDTH = 280
    _CARD_SPACING = 40

    def _init_ui(self) -> None:
        # Layout: left spacer | stretch | main menu (centered) | spacing | community card | stretch
        # Left spacer width = card width + spacing to keep the main menu in the center of the screen
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Balanced placeholder on the left (same width as the card + spacing on the right)
        left_spacer = QWidget()
        left_spacer.setFixedWidth(self._CARD_WIDTH + self._CARD_SPACING)
        left_spacer.setStyleSheet("background: transparent;")
        outer.addWidget(left_spacer)
        outer.addStretch(1)

        # ══════ Main menu (centered body) ══════
        left = QVBoxLayout()
        left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.setSpacing(16)

        # Title
        title = QLabel(tr("welcome_title"))
        title_font = QFont("Segoe UI", 28, QFont.Weight.Bold)
        title_font.setFamilies(["Segoe UI", "Arial", "sans-serif"])
        title.setFont(title_font)
        title.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(title)

        # version
        from version import VERSION
        version = QLabel(f"v{VERSION}")
        version.setStyleSheet(f"color: {_DIM}; font-size: 14px; background: transparent;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(version)

        left.addSpacing(24)

        # button style
        btn_style = f"""
            QPushButton {{
                background: {_INPUT_BG};
                border: 1px solid {_BORDER};
                color: {_TEXT};
                padding: 12px 32px;
                font-size: 15px;
                border-radius: 6px;
                min-width: 200px;
            }}
            QPushButton:hover {{
                border-color: {_ACCENT};
                background: rgba(79, 140, 255, 0.12);
            }}
        """

        btn_new = QPushButton(tr("action_new"))
        btn_new.setStyleSheet(btn_style)
        btn_new.clicked.connect(self._on_new)
        left.addWidget(btn_new, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_open = QPushButton(tr("action_open"))
        btn_open.setStyleSheet(btn_style)
        btn_open.clicked.connect(lambda: self.open_project_requested.emit())
        left.addWidget(btn_open, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_import = QPushButton(tr("welcome_import_mod"))
        btn_import.setStyleSheet(btn_style)
        btn_import.clicked.connect(lambda: self.import_mod_requested.emit())
        left.addWidget(btn_import, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_vanilla = QPushButton(tr("welcome_open_vanilla"))
        btn_vanilla.setStyleSheet(btn_style)
        btn_vanilla.clicked.connect(lambda: self.open_vanilla_requested.emit())
        left.addWidget(btn_vanilla, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_guide = QPushButton(tr("action_guide"))
        btn_guide.setStyleSheet(btn_style)
        btn_guide.clicked.connect(self._on_guide)
        left.addWidget(btn_guide, alignment=Qt.AlignmentFlag.AlignCenter)

        left.addSpacing(12)

        # Recent projects
        recent_label = QLabel(tr("welcome_recent"))
        recent_label.setStyleSheet(f"color: {_DIM}; font-size: 12px; background: transparent;")
        recent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(recent_label)

        self._recent_list = QListWidget()
        # Soft constraints: minimum 640x220, adaptive when the window is large
        self._recent_list.setMinimumSize(640, 220)
        self._recent_list.setToolTip(tr("welcome_recent_tooltip"))
        self._recent_list.setStyleSheet(f"""
            QListWidget {{
                background: {_INPUT_BG};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                color: {_TEXT};
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
            }}
            QListWidget::item:selected {{
                background: {_ACCENT};
                color: white;
            }}
            QListWidget::item:hover:!selected {{
                background: rgba(255, 255, 255, 0.05);
            }}
        """)
        self._recent_list.itemDoubleClicked.connect(self._on_recent_clicked)
        left.addWidget(self._recent_list, alignment=Qt.AlignmentFlag.AlignCenter)

        self._populate_recent()
        outer.addLayout(left)

        outer.addSpacing(self._CARD_SPACING)

        # ══════ Community Card (next to the right of the main menu, vertically centered) ══════
        right = QVBoxLayout()
        right.setSpacing(0)
        right.addStretch(1)

        info_card = QWidget()
        info_card.setFixedWidth(self._CARD_WIDTH)
        info_card.setStyleSheet(f"""
            QWidget {{
                background: {_INPUT_BG};
                border: 1px solid {_BORDER};
                border-radius: 8px;
            }}
        """)
        card_lay = QVBoxLayout(info_card)
        card_lay.setContentsMargins(24, 24, 24, 24)
        card_lay.setSpacing(16)

        # community support
        community_title = QLabel(tr("welcome_community_title"))
        community_title.setStyleSheet(f"color: {_ACCENT}; font-size: 15px; font-weight: bold; background: transparent; border: none;")
        card_lay.addWidget(community_title)

        community = QLabel(tr("welcome_community"))
        community.setWordWrap(True)
        community.setTextFormat(Qt.TextFormat.RichText)
        community.setOpenExternalLinks(True)
        community.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        community.setStyleSheet(f"color: {_TEXT}; font-size: 13px; line-height: 1.8; background: transparent; border: none;")
        card_lay.addWidget(community)

        # divider
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_BORDER}; border: none;")
        card_lay.addWidget(sep)

        # GitHub + Feedback
        links = QLabel(tr("welcome_links"))
        links.setWordWrap(True)
        links.setTextFormat(Qt.TextFormat.RichText)
        links.setOpenExternalLinks(True)
        links.setStyleSheet(f"color: {_TEXT}; font-size: 13px; background: transparent; border: none;")
        card_lay.addWidget(links)

        right.addWidget(info_card)
        right.addStretch(1)
        outer.addLayout(right)
        outer.addStretch(1)

    def _populate_recent(self) -> None:
        self._recent_list.clear()
        for path in _load_recent_projects():
            item = QListWidgetItem(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)  # Hover to show the full path (in case it's still exceeded)
            self._recent_list.addItem(item)
        if self._recent_list.count() == 0:
            empty = QListWidgetItem(tr("welcome_no_recent"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._recent_list.addItem(empty)

    def _on_new(self) -> None:
        dlg = _SizePickerDialog(self)
        if dlg.exec_() == QDialog.DialogCode.Accepted:
            w, h = dlg.chosen_size
            self.new_project_requested.emit(w, h)

    def _on_guide(self) -> None:
        from views.guide_dialog import GuideDialog
        dlg = GuideDialog(self)
        dlg.exec_()

    def _switch_lang(self, lang: str) -> None:
        """Compatibility hook; locale switching is disabled in English-only mode."""
        from ui.i18n import set_language
        set_language("en")
        self.language_changed.emit("en")

    def retranslateUi(self) -> None:
        """Rebuild the entire welcome page after language switching."""
        # Delete the old layout and all child widgets
        old_layout = self.layout()
        if old_layout:
            from PyQt5 import sip
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
                sub = item.layout()
                if sub:
                    self._clear_layout(sub)
            sip.delete(old_layout)
        self._init_ui()

    @staticmethod
    def _clear_layout(layout) -> None:
        """Recursively clear all widgets and sub-layouts under the layout."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            sub = item.layout()
            if sub:
                WelcomePage._clear_layout(sub)

    def _on_recent_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_recent_requested.emit(path)
