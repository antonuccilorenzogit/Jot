"""
Legacy compatibility shim.

The old CustomTkinter desktop UI has been retired. This module intentionally
keeps the import path alive so existing launchers do not break, but it now
delegates to the WebUI runtime.
"""

from __future__ import annotations

from jot.app_webview import main as run_webui


def main() -> None:
    run_webui()


class JotApp:
    """
    Backward-compatible shim for callers still importing JotApp.

    `mainloop()` simply starts the WebUI version of the application.
    """

    def mainloop(self) -> None:
        run_webui()
