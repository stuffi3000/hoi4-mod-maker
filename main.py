"""Application entry point for HOI4 Map Maker."""
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.crash_handler import install_crash_handler
from ui.main_window import MainWindow


def main() -> None:
    """Create and run the desktop application."""
    install_crash_handler()

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    from ui.i18n import tr

    app.setApplicationName(tr("app_title"))
    app.setOrganizationName("HOI4ModTools")

    from PyQt5.QtGui import QFont

    base_font = QFont("Segoe UI", 9)
    base_font.setFamilies(["Segoe UI", "Arial", "sans-serif"])
    app.setFont(base_font)

    font_override_css = """
QWidget, QMainWindow, QDialog, QMessageBox,
QPushButton, QLabel, QLineEdit, QTextEdit, QPlainTextEdit,
QComboBox, QSpinBox, QDoubleSpinBox, QSlider,
QListWidget, QListView, QTreeWidget, QTreeView, QTableWidget, QTableView,
QGroupBox, QCheckBox, QRadioButton, QProgressBar,
QTabWidget, QTabBar, QMenuBar, QMenu, QToolBar, QToolButton,
QStatusBar, QHeaderView, QScrollBar, QToolTip {
    font-family: "Segoe UI", Arial, sans-serif;
}
"""

    try:
        import qdarktheme

        stylesheet = qdarktheme.load_stylesheet(
            "dark",
            custom_colors={"primary": "#4f8cff"},
        )
        app.setStyleSheet(stylesheet + font_override_css)
    except Exception as exc:
        print(
            f"[warn] qdarktheme unavailable; using the built-in theme: {exc}",
            file=sys.stderr,
        )
        from ui.styles import DARK_STYLESHEET

        app.setStyleSheet(DARK_STYLESHEET + font_override_css)

    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
