"""
Settings and configuration IPC bridge controller.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

import webview

from jot.bridge.bridge_utils import (
    _path_under_root,
    bridge_error,
    bridge_ok,
)
from jot.core.model_registry import DEFAULT_FALLBACK_MODELS, MODEL_OPTIONS
from jot.core.shared import (
    DEFAULT_MODEL,
    get_session_root,
    invalidate_session_storage_cache,
    set_session_root,
)
from jot.services.config_service import (
    THEME_PREF_FILE,
    load_config,
    save_config,
    save_session_root_to_config,
)
from jot.utils.logging_utils import redact_secrets

if TYPE_CHECKING:
    from typing import Any


class SettingsControllerMixin:
    """Mixin providing settings, configuration, and session storage move IPC methods."""

    if TYPE_CHECKING:
        _window: webview.Window | None
        _logger: Any
        _processing_thread: threading.Thread | None
        _move_lock: threading.Lock
        _move_state: dict
        _sessions_cache: dict | None
        _sessions_cache_gen: int
        _sessions_cache_lock: threading.Lock

    def load_settings(self) -> dict:
        """Load saved config from disk."""
        try:
            cfg = load_config()
            result: dict = {
                "api_key": cfg.get("api_key", ""),
                "fallback_keys": cfg.get("fallback_keys", []),
                "preferred_model": cfg.get("preferred_model", DEFAULT_MODEL),
                "fallback_models": cfg.get("fallback_models", []),
                "available_models": list(MODEL_OPTIONS),
                "has_protected_key": bool(cfg.get("has_protected_key")),
                "api_key_insecure": bool(cfg.get("api_key_insecure")),
                "api_key_insecure_reason": str(
                    cfg.get("api_key_insecure_reason") or ""
                ),
                "credential_storage": cfg.get(
                    "credential_storage", {"primary": "absent", "fallback": "absent"}
                ),
            }
            if cfg.get("config_recovered_from"):
                result["config_recovered_from"] = cfg["config_recovered_from"]
            return result
        except Exception:
            return {
                "api_key": "",
                "fallback_keys": [],
                "preferred_model": DEFAULT_MODEL,
                "fallback_models": list(DEFAULT_FALLBACK_MODELS),
                "available_models": list(MODEL_OPTIONS),
                "has_protected_key": False,
                "api_key_insecure": False,
                "api_key_insecure_reason": "",
                "credential_storage": {"primary": "absent", "fallback": "absent"},
            }

    def save_settings(
        self,
        api_key: str | None,
        fallback_keys: list[str] | None,
        preferred_model: str,
        fallback_models: list[str],
    ) -> dict:
        """Save config to disk."""
        try:
            storage = save_config(
                api_key,
                fallback_keys=fallback_keys,
                preferred_model=preferred_model,
                fallback_models=fallback_models,
            )
            cfg = load_config()
            return bridge_ok(
                credential_storage=cfg.get("credential_storage", storage),
                api_key_insecure=bool(cfg.get("api_key_insecure")),
                api_key_insecure_reason=str(cfg.get("api_key_insecure_reason") or ""),
            )
        except Exception as e:
            return bridge_error(e)

    def save_theme_preference(self, theme: str) -> None:
        """Persist theme preference to disk so the native window gets the right background on next launch."""
        try:
            if theme not in ("light", "dark"):
                return
            os.makedirs(os.path.dirname(THEME_PREF_FILE), exist_ok=True)
            with open(THEME_PREF_FILE, "w", encoding="utf-8") as fh:
                fh.write(theme)
            import sys

            if self._window is not None and sys.platform == "win32":
                try:
                    from jot.webview_entry import (
                        _apply_windows_dark_mode,
                        _get_window_hwnd,
                    )

                    hwnd = _get_window_hwnd(self._window)
                    if hwnd:
                        _apply_windows_dark_mode(hwnd, theme == "dark")
                except Exception:
                    pass
        except Exception:
            pass

    def ask_session_folder(self) -> dict:
        """Open a folder-picker dialog and return the user-selected path."""
        try:
            if self._window is None:
                return bridge_error("Finestra non disponibile")
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            if not result:
                return bridge_error("Operazione annullata.", cancelled=True)
            path = str(result[0]) if isinstance(result, list | tuple) else str(result)
            return bridge_ok(path=path)
        except Exception as e:
            return bridge_error(e)

    def move_session_root(self, new_path: str) -> dict:
        """Start an async move of the session-storage folder to new_path."""
        new_path = str(new_path or "").strip()
        if not new_path or not os.path.isabs(new_path):
            return bridge_error("Percorso non valido")
        old_root = get_session_root()
        if os.path.normcase(os.path.realpath(new_path)) == os.path.normcase(
            os.path.realpath(old_root)
        ):
            return bridge_error("Percorso identico a quello attuale")
        if _path_under_root(
            os.path.normcase(os.path.realpath(new_path)),
            os.path.normcase(os.path.realpath(old_root)),
        ):
            return bridge_error("La destinazione è dentro la cartella attuale")
        if self._processing_thread is not None and self._processing_thread.is_alive():
            return bridge_error("Impossibile spostare durante l'elaborazione")
        with self._move_lock:
            if self._move_state.get("status") == "moving":
                return bridge_error("Spostamento già in corso")
            self._move_state = {
                "status": "moving",
                "moved": 0,
                "total": 0,
                "error": None,
            }
        thread = threading.Thread(
            target=self._do_move_session_root,
            args=(old_root, new_path),
            daemon=True,
            name="session-move",
        )
        thread.start()
        return bridge_ok(started=True)

    def get_session_move_status(self) -> dict:
        """Return the current status of an ongoing or completed session move."""
        with self._move_lock:
            return dict(self._move_state)

    def _finish_move(self, new_path: str, old_root: str | None = None) -> None:
        """Persist new SESSION_ROOT, migrate folders, and invalidate all caches after a move."""
        set_session_root(new_path)
        try:
            save_session_root_to_config(new_path)
        except Exception:
            pass
        if old_root:
            try:
                from jot.services.folders_service import migrate_session_roots

                migrate_session_roots(old_root, new_path)
            except Exception:
                pass
        invalidate_session_storage_cache()
        with self._sessions_cache_lock:
            self._sessions_cache = None
            self._sessions_cache_gen += 1

    def _do_move_session_root(self, old_root: str, new_path: str) -> None:
        import shutil as _shutil

        try:
            items = os.listdir(old_root) if os.path.isdir(old_root) else []
        except Exception:
            items = []
        total = len(items)
        with self._move_lock:
            self._move_state = {
                "status": "moving",
                "moved": 0,
                "total": total,
                "error": None,
            }
        try:
            os.makedirs(new_path, exist_ok=True)
        except Exception as e:
            with self._move_lock:
                self._move_state = {
                    "status": "error",
                    "moved": 0,
                    "total": total,
                    "error": redact_secrets(e),
                }
            return
        try:
            if os.listdir(new_path):
                with self._move_lock:
                    self._move_state = {
                        "status": "error",
                        "moved": 0,
                        "total": total,
                        "error": "Cartella di destinazione non vuota",
                    }
                return
        except Exception as e:
            with self._move_lock:
                self._move_state = {
                    "status": "error",
                    "moved": 0,
                    "total": total,
                    "error": redact_secrets(e),
                }
            return

        try:
            os.rmdir(new_path)
            os.rename(old_root, new_path)
            self._finish_move(new_path, old_root)
            with self._move_lock:
                self._move_state = {
                    "status": "done",
                    "moved": total,
                    "total": total,
                    "error": None,
                    "old_root": old_root,
                    "new_root": new_path,
                }
            return
        except OSError:
            os.makedirs(new_path, exist_ok=True)

        moved = 0
        error_msg: str | None = None
        failed_item: str | None = None
        for name in items:
            src = os.path.join(old_root, name)
            dst = os.path.join(new_path, name)
            try:
                _shutil.move(src, dst)
                moved += 1
                with self._move_lock:
                    self._move_state["moved"] = moved
            except Exception as e:
                error_msg = str(e)
                failed_item = name
                break

        self._finish_move(new_path, old_root)

        if error_msg is not None:
            remaining = total - moved
            split_note = (
                f" {moved} sessioni spostate; {remaining} rimasta/e in {old_root}."
                if remaining > 0
                else ""
            )
            with self._move_lock:
                self._move_state = {
                    "status": "error",
                    "moved": moved,
                    "total": total,
                    "error": f"Errore spostamento {failed_item}: {error_msg}.{split_note}",
                    "old_root": old_root,
                    "new_root": new_path,
                }
            return

        try:
            os.rmdir(old_root)
        except Exception:
            pass
        with self._move_lock:
            self._move_state = {
                "status": "done",
                "moved": moved,
                "total": total,
                "error": None,
                "old_root": old_root,
                "new_root": new_path,
            }
