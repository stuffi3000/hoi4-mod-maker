"""Global crash handler - captures unhandled exceptions, displays the cause in a pop-up window + writes a crash log file.

Usage: Create QApplication after `install_crash_handler()` in main.py.
All exceptions not wrapped by try/except will trigger a crash dialog and log records."""

from __future__ import annotations

import datetime
import os
import sys
import traceback
from pathlib import Path


def _write_crash_log(tb_text: str) -> str:
    """Write the traceback to logs/crash_YYYYMMDD_HHMMSS.log and return the file path."""
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"crash_{ts}.log"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Crash time: {datetime.datetime.now().isoformat()}\n")
        f.write(f"# Python: {sys.version}\n")
        f.write(f"# Platform: {sys.platform}\n\n")
        f.write(tb_text)
    return str(path)


def _show_crash_dialog(exc_type, exc_value, exc_tb) -> None:
    """Use QMessageBox to display crash messages. If Qt has not been initialized, only print to stderr."""
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    # Write log file
    try:
        log_path = _write_crash_log(tb_text)
    except Exception:
        log_path = "(Failed to write log file)"

    # Print to terminal (if available)
    print("=" * 60, file=sys.stderr)
    print("CRASH:", file=sys.stderr)
    print(tb_text, file=sys.stderr)
    print(f"Log: {log_path}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Try popping up a Qt dialog box
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None:
            return  # Qt is not up yet, can only print

        # Short summary (the last line is usually the exception type and message)
        last_line = tb_text.strip().split("\n")[-1]

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        from ui.i18n import tr
        box.setWindowTitle(tr("crash_title"))
        box.setText(tr("crash_message").format(last_line))
        box.setInformativeText(tr("crash_log_saved").format(log_path))
        box.setDetailedText(tb_text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec_()
    except Exception:
        # The pop-up window itself fails and is not thrown.
        pass


def install_crash_handler() -> None:
    """Install global sys.excepthook. Called before QApplication is constructed."""
    def _handler(exc_type, exc_value, exc_tb):
        # KeyboardInterrupt takes default behavior
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _show_crash_dialog(exc_type, exc_value, exc_tb)

    sys.excepthook = _handler
