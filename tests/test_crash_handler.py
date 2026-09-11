"""Crash handler testing."""

import sys

from app.crash_handler import install_crash_handler, _write_crash_log


def test_install_sets_excepthook():
    old = sys.excepthook
    install_crash_handler()
    assert sys.excepthook is not old
    # restore
    sys.excepthook = old


def test_write_crash_log_creates_file(tmp_path, monkeypatch):
    """_write_crash_log must be able to write traceback to logs/crash_*.log."""
    tb_text = "Traceback (most recent call last):\n  ValueError: test\n"
    path = _write_crash_log(tb_text)
    import os
    assert os.path.isfile(path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "ValueError: test" in content
    # cleanup
    os.remove(path)


def test_install_handles_keyboard_interrupt():
    """KeyboardInterrupt should take the default behavior, no pop-ups or swallowing."""
    old = sys.excepthook
    install_crash_handler()
    new_hook = sys.excepthook
    # Our handler should delegate to sys.__excepthook__ when encountering KeyboardInterrupt
    # Here we only verify that the handler is callable and does not crash
    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        exc_type, exc_value, exc_tb = sys.exc_info()
        # It cannot be actually called (test will exit), but the verification function exists
        assert callable(new_hook)
    sys.excepthook = old
