"""
PyWebView backend bridge for jot.

This module contains JotApi, the JS-facing API class.
Supporting infrastructure lives in dedicated modules:
  - bridge_dispatcher.py  (_BridgeDispatcher)
  - bridge_utils.py       (Shared helpers and constants)
  - pipeline_adapter.py   (_drain_dnd_paths, PipelineAdapter)
  - webview_entry.py      (_ConsoleTee, get_dist_path, has_webview2_runtime,
                           build_missing_webview2_html, main)
  - controllers/          (Mixin classes for IPC methods)
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import ClassVar

import webview

from jot.bridge.bridge_dispatcher import EventDispatcher
from jot.bridge.controllers import (
    ExportControllerMixin,
    HtmlControllerMixin,
    MediaControllerMixin,
    PipelineControllerMixin,
    SessionControllerMixin,
    SettingsControllerMixin,
    SystemControllerMixin,
)
from jot.core.shared import (
    cleanup_orphan_temp_chunks,
    get_session_root,
    migrate_legacy_session_root,
    set_session_root,
)
from jot.pipeline.pipeline_adapter import PipelineAdapter
from jot.services.config_service import load_config
from jot.utils.logging_utils import (
    configure_logging,
    get_logger,
    redact_secrets,
)

_TEXT_CACHE_MAX = 50


class JotApi(
    SettingsControllerMixin,
    SessionControllerMixin,
    PipelineControllerMixin,
    ExportControllerMixin,
    SystemControllerMixin,
    MediaControllerMixin,
    HtmlControllerMixin,
):
    """Methods callable from React via window.pywebview.api.*"""

    def __init__(
        self,
        *,
        session_root_override: str | None = None,
        load_persisted_session_root: bool = True,
        event_dispatcher: EventDispatcher | None = None,
    ):
        if session_root_override:
            set_session_root(os.path.abspath(session_root_override))
        self._window: webview.Window | None = None
        self._cancel_event = threading.Event()
        self._adapter = PipelineAdapter(
            None, self._cancel_event, dispatcher=event_dispatcher
        )
        self._processing_thread: threading.Thread | None = None
        self._html_shell_cache: dict[str, tuple[str, str]] = {}
        self._resolved_path_cache: dict[str, str] = {}
        self._resolved_cache_lock = threading.Lock()
        self._sessions_cache: dict | None = None
        self._sessions_cache_ts: float = 0.0
        self._sessions_cache_gen: int = 0
        self._sessions_cache_lock = threading.Lock()
        self._text_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._text_cache_lock = threading.Lock()
        self._move_state: dict = {
            "status": "idle",
            "moved": 0,
            "total": 0,
            "error": None,
        }
        self._move_lock = threading.Lock()
        self._retry_active_count: int = 0
        self._active_retry_cancel_event: threading.Event | None = None
        self._force_close: bool = False
        self._pipeline_lifecycle_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()

        configure_logging()
        self._logger = get_logger("jot.webview")

        # Desktop loads the persisted location. Browser development passes an
        # explicit isolated root and must never inspect the user's config.
        if load_persisted_session_root:
            try:
                _cfg = load_config()
                _custom_root = str(_cfg.get("session_root") or "").strip()
                if _custom_root and os.path.isabs(_custom_root):
                    set_session_root(_custom_root)
                    real_root = get_session_root()
                    if real_root != _custom_root:
                        from jot.services.config_service import (
                            save_session_root_to_config,
                        )

                        save_session_root_to_config(real_root)
                else:
                    migrate_legacy_session_root()
            except Exception:
                pass

        self._startup_cleanup_thread = threading.Thread(
            target=self._cleanup_orphan_temp_chunks_on_startup,
            daemon=True,
            name="temp-chunks-startup-cleanup",
        )
        self._startup_cleanup_thread.start()

        self._prewarm_thread = threading.Thread(
            target=self.get_completed_sessions,
            daemon=True,
            name="sessions-prewarm",
        )
        self._prewarm_thread.start()

    def _cleanup_orphan_temp_chunks_on_startup(self) -> None:
        try:
            removed = cleanup_orphan_temp_chunks()
            if removed > 0 and self._adapter.window is not None:
                self._push_console(f"[*] Pulizia: rimossi {removed} file temporanei.")
        except Exception as exc:
            try:
                self._logger.debug("startup temp cleanup failed: %s", exc)
            except Exception:
                pass

    def _get_session_root(self) -> str:
        """Return the session storage root directory."""

        return get_session_root()

    def set_window(self, window: webview.Window):
        self._window = window
        self._adapter.window = window

    # ---- Console push helper ----

    def _push_console(self, msg: str):
        self._adapter.emit("appendConsole", redact_secrets(msg), batched=False)


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility and tests
# ---------------------------------------------------------------------------
import os
import threading

from jot.bridge.bridge_utils import (
    _ALLOWED_URL_PREFIXES,
    _normalize_revision_failed_blocks,
    _path_under_root,
    _retry_no_failed_blocks_response,
    _retry_would_overwrite_user_html,
    _retry_zero_retried_response,
    _safe_relpath,
)
from jot.core.media_server import LocalMediaServer
from jot.core.model_registry import DEFAULT_FALLBACK_MODELS, MODEL_OPTIONS
from jot.core.session_store import (
    mark_html_exported,
    resolve_session_paths,
    save_session,
)
from jot.core.shared import (
    DEFAULT_MODEL,
    _atomic_write_json,
    _load_json,
    cleanup_orphan_sessions,
    get_session_root,
    get_session_storage_info,
    invalidate_session_storage_cache,
)
from jot.core.shared import (
    cleanup_completed_sessions as _cleanup_completed_sessions,
)
from jot.pipeline.pipeline_settings import (
    build_default_pipeline_settings,
    load_and_sanitize_settings,
)
from jot.services.config_service import (
    THEME_PREF_FILE,
    get_desktop_dir,
    load_config,
    save_config,
    save_session_root_to_config,
)
from jot.utils.file_ops import (
    evict_html_paths_under,
    extract_html_shell,
    open_path_with_default_app,
    save_html_body_content,
)
from jot.webview_entry import main

if __name__ == "__main__":
    main()
