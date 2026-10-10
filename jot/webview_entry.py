"""
Application entry point for jot (pywebview).

Contains: _ConsoleTee, get_dist_path(), has_webview2_runtime(),
build_missing_webview2_html(), and main().
"""

from __future__ import annotations

import os
import sys
import threading
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import webview

from jot.core.desktop_startup import DesktopStartupServer
from jot.core.media_server import LocalMediaServer
from jot.utils.console_utils import MAX_CONSOLE_LINE_LEN, LineConsoleTee
from jot.utils.logging_utils import (
    configure_logging,
    prepare_startup,
)
from jot.utils.webview2_recovery import (
    build_missing_webview2_html,
    clear_webview2_cache,
    get_boot_bg_color,
    has_webview2_runtime,
    start_webview2_monitor,
)
from jot.utils.win32_window_utils import (
    apply_windows_dark_mode,
    get_window_hwnd,
    get_window_position,
)

# Backward-compatibility aliases
_apply_windows_dark_mode = apply_windows_dark_mode
_get_window_hwnd = get_window_hwnd
_get_window_position = get_window_position
_boot_bg_color = get_boot_bg_color
_clear_webview2_cache = clear_webview2_cache
_start_webview2_monitor = start_webview2_monitor

# Suppress benign requests warning about chardet/charset_normalizer failing to import
warnings.filterwarnings(
    "ignore", message="Unable to find acceptable character detection dependency"
)

# ---------------------------------------------------------------------------
# Console interceptor
# ---------------------------------------------------------------------------

_MAX_CONSOLE_LINE_LEN = MAX_CONSOLE_LINE_LEN


class _ConsoleTee(LineConsoleTee):
    """Intercept print() calls and forward to React console too."""

    def __init__(self, original, api: JotApi):  # type: ignore[name-defined]  # noqa: F821
        self._api = api
        super().__init__(original, api._push_console)


# ---------------------------------------------------------------------------
# Entry-point helpers
# ---------------------------------------------------------------------------


def get_dist_path() -> str:
    """Locate the webui dist folder (works both in dev and PyInstaller)."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle
        base = sys._MEIPASS  # type: ignore
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist = os.path.join(base, "webui", "dist", "index.html")
    if os.path.exists(dist):
        return dist
    # Fallback: relative to cwd
    alt = os.path.join(os.getcwd(), "webui", "dist", "index.html")
    if os.path.exists(alt):
        return alt
    raise FileNotFoundError(
        f"Non trovo webui/dist/index.html. Esegui 'npm run build' nella cartella webui/.\n"
        f"Cercato in: {dist} e {alt}"
    )


def build_close_handler(
    api: Any,
    window: webview.Window,
    stop_event: threading.Event | None = None,
) -> Callable[[], bool | None]:
    """Return a closing event handler that prompts for confirmation if busy."""

    def _on_closing() -> bool | None:
        if getattr(api, "_force_close", False):
            if stop_event is not None:
                stop_event.set()
            LocalMediaServer.shutdown_all()
            return None

        if getattr(api, "is_busy", lambda: False)():
            adapter = getattr(api, "_adapter", None)
            if adapter is not None and getattr(adapter, "window", None) is not None:
                try:
                    adapter.emit("requestQuitConfirmation", {}, batched=False)
                    return False
                except Exception:
                    pass

            # Fallback to native confirmation dialog if WebUI is not ready/available
            confirmed = False
            try:
                confirmed = bool(
                    window.create_confirmation_dialog(
                        "jot - Elaborazione in corso",
                        "Un'elaborazione è attualmente in corso.\n\n"
                        "Se chiudi l'applicazione, l'elaborazione verrà interrotta e i progressi correnti potrebbero andare persi.\n\n"
                        "Vuoi davvero uscire?",
                    )
                )
            except Exception:
                confirmed = True

            if not confirmed:
                return False

            if hasattr(api, "request_shutdown"):
                try:
                    api.request_shutdown(timeout=1.5)
                except Exception:
                    pass

        if stop_event is not None:
            stop_event.set()
        LocalMediaServer.shutdown_all()
        return None

    return _on_closing


def main():
    prepare_startup()
    from jot.app_webview import JotApi

    api = JotApi()

    # Intercept stdout/stderr to forward to React console
    sys.stdout = _ConsoleTee(sys.__stdout__, api)
    sys.stderr = _ConsoleTee(sys.__stderr__, api)
    configure_logging(stream=sys.stdout)

    dist_path = get_dist_path()
    webview2_available = has_webview2_runtime()

    # Storage path for WebView2 profile cache (avoids re-init freeze)
    storage_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "jot",
        "webview_cache",
    )
    os.makedirs(storage_dir, exist_ok=True)

    _clear_webview2_cache(storage_dir, dist_path)

    win_w, win_h = 900, 820
    _pos_kwargs = _get_window_position(win_w, win_h)

    stop_event: threading.Event | None = None
    startup_server: DesktopStartupServer | None = None

    if webview2_available:
        startup_server = DesktopStartupServer(dist_path)
        try:
            window = webview.create_window(
                "jot",
                startup_server.entry_url(),
                js_api=api,
                width=win_w,
                height=win_h,
                **_pos_kwargs,
                min_size=(750, 620),
                background_color=_boot_bg_color(),
                maximized=True,
            )
        except Exception:
            startup_server.close()
            raise
    else:
        print(
            "[!] Microsoft Edge WebView2 Runtime non trovato. Mostro schermata di recupero."
        )
        window = webview.create_window(
            "jot",
            html=build_missing_webview2_html(),
            width=win_w,
            height=win_h,
            **_pos_kwargs,
            min_size=(750, 620),
            background_color=_boot_bg_color(),
            maximized=True,
        )

        stop_event = threading.Event()
        _start_webview2_monitor(window, stop_event)

    api.set_window(window)

    def _on_shown():
        if sys.platform == "win32":
            hwnd = _get_window_hwnd(window)
            if hwnd:
                is_dark = _boot_bg_color() == "#161618"
                _apply_windows_dark_mode(hwnd, is_dark)

    window.events.shown += _on_shown

    window.events.closing += build_close_handler(api, window, stop_event)

    try:
        from webview.dom import _dnd_state

        _dnd_state["num_listeners"] += 1
    except Exception:
        pass

    if startup_server is not None:
        window.events.closed += startup_server.stop.set
    startup_monitor = (
        startup_server.monitor
        if startup_server is not None and not startup_server.port_fallback
        else None
    )
    try:
        webview.start(
            startup_monitor,
            (window,) if startup_monitor is not None else None,
            private_mode=False,
            storage_path=storage_dir,
            debug=False,
        )
    finally:
        if startup_server is not None:
            startup_server.close()


if __name__ == "__main__":
    main()
