"""pytest global configuration.
- Add the project root to sys.path to make import take effect (the project does not use src/ layout).
- Qt tests in offscreen mode without pop-up windows."""

import os
import sys
import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Qt headless
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_REQUIRED_TEST_MODULES = {
    "PyQt5": "PyQt5",
    "numpy": "numpy",
    "PIL": "Pillow",
    "scipy": "scipy",
    "cv2": "opencv-python",
    # The distribution is named PyQtDarkTheme, while its import package is
    # qdarktheme.
    "qdarktheme": "pyqtdarktheme",
    "pytestqt": "pytest-qt",
}


def pytest_sessionstart(session):
    """Fail collection early with an actionable dependency message."""

    missing = [
        package
        for module, package in _REQUIRED_TEST_MODULES.items()
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        pytest.exit(
            "Missing required test dependencies: "
            + ", ".join(missing)
            + ". Install them with: python -m pip install -r requirements.txt",
            returncode=4,
        )
