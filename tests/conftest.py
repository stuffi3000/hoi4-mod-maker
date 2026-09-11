"""pytest global configuration.
- Add the project root to sys.path to make import take effect (the project does not use src/ layout).
- Qt tests in offscreen mode without pop-up windows."""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Qt headless
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
