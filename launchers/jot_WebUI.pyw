"""
Entrypoint PyWebView (compatibile con PyInstaller).

La logica dell'app vive in `jot/app_webview.py` per mantenere il progetto modulare.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jot.utils.logging_utils import prepare_startup

prepare_startup()

from jot.app_webview import main

if __name__ == "__main__":
    main()
