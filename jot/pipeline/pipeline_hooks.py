"""
Pipeline hook helpers for jot.

The core pipeline talks to this runtime object instead of reaching directly
into whichever UI implementation is currently attached.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any


class PipelineRuntime:
    def __init__(self, target: Any):
        self.target = target
        if not hasattr(self.target, "file_temporanei"):
            self.target.file_temporanei = []
        if not hasattr(self.target, "last_run_status"):
            self.target.last_run_status = "idle"
        if not hasattr(self.target, "last_run_error"):
            self.target.last_run_error = None
        if not hasattr(self.target, "last_run_error_detail"):
            self.target.last_run_error_detail = None
        if not hasattr(self.target, "effective_api_key"):
            self.target.effective_api_key = None

    @property
    def cancel_event(self):
        return getattr(self.target, "cancel_event", None)

    def cancelled(self) -> bool:
        cancel_event = self.cancel_event
        return cancel_event is not None and cancel_event.is_set()

    def ui_alive(self) -> bool:
        try:
            if hasattr(self.target, "winfo_exists"):
                return bool(self.target.winfo_exists())
            return True
        except Exception:
            return False

    def schedule(self, delay_ms: int, callback: Callable, *args) -> bool:
        if not self.ui_alive():
            return False
        try:
            if hasattr(self.target, "after"):
                self.target.after(delay_ms, callback, *args)
                return True
        except Exception:
            return False
        return False

    def progress(self, value: float) -> None:
        self._safe_call("aggiorna_progresso", value)

    def phase(self, text: str) -> None:
        self._safe_call("aggiorna_fase", text)

    def console_error(self, msg: str) -> None:
        self._safe_call("emit", "appendConsole", msg, batched=False)

    def output_html(self, path: str, output_dir: str | None = None) -> None:
        self._safe_call("imposta_output_html", path, output_dir=output_dir)

    def process_done(self) -> None:
        self._safe_call("processo_terminato")

    def retry_state(self, payload: dict[str, Any]) -> None:
        if hasattr(self.target, "emit_retry_state"):
            self._safe_call("emit_retry_state", payload)
        else:
            self._safe_call("emit", "retryStateChanged", payload, batched=False)

    def set_work_totals(self, chunks_total=None, macro_total=None) -> None:
        self._safe_call(
            "set_work_totals",
            chunks_total=chunks_total,
            macro_total=macro_total,
        )

    def update_work_done(self, kind: str, done: int, total: int | None = None) -> None:
        self._safe_call("update_work_done", kind, done, total=total)

    def register_step_time(
        self,
        kind: str,
        seconds: float,
        done: int | None = None,
        total: int | None = None,
    ) -> None:
        self._safe_call("register_step_time", kind, seconds, done=done, total=total)

    def set_run_result(self, status: str, error: str | None = None) -> None:
        try:
            if hasattr(self.target, "set_run_result"):
                self.target.set_run_result(status, error)
            else:
                self.target.last_run_status = status
                self.target.last_run_error = error
        except Exception:
            pass

    def set_run_error_detail(self, detail: str | None = None) -> None:
        try:
            if hasattr(self.target, "set_run_error_detail"):
                self.target.set_run_error_detail(detail)
            else:
                self.target.last_run_error_detail = detail
        except Exception:
            pass

    def set_revision_failed_blocks(self, blocks: Sequence[int | str] | None) -> None:
        try:
            cleaned = [int(idx) for idx in (blocks or [])]
            if hasattr(self.target, "set_revision_failed_blocks"):
                self.target.set_revision_failed_blocks(cleaned)
            elif self.target is not None:
                self.target.last_revision_failed_blocks = cleaned
        except Exception:
            pass

    def get_revision_failed_blocks(self) -> list[int]:
        if hasattr(self.target, "get_revision_failed_blocks"):
            return self.target.get_revision_failed_blocks()
        return list(getattr(self.target, "last_revision_failed_blocks", []))

    def get_last_run_status(self) -> str | None:
        if hasattr(self.target, "get_last_run_status"):
            return self.target.get_last_run_status()
        return getattr(self.target, "last_run_status", None)

    def get_last_run_error(self) -> str | None:
        if hasattr(self.target, "get_last_run_error"):
            return self.target.get_last_run_error()
        return getattr(self.target, "last_run_error", None)

    def get_effective_api_key(self) -> str | None:
        if hasattr(self.target, "get_effective_api_key"):
            return self.target.get_effective_api_key()
        return getattr(self.target, "effective_api_key", None)

    def update_model(self, model: str) -> None:
        self._safe_call("update_model", model)

    def set_effective_api_key(self, api_key: str | None) -> None:
        key = str(api_key or "").strip() or None
        try:
            if hasattr(self.target, "set_effective_api_key"):
                self.target.set_effective_api_key(key)
            else:
                self.target.effective_api_key = key
        except Exception:
            pass

    def ask_regenerate(
        self,
        filename: str,
        callback: Callable,
        mode: str = "resume",
        session_dir: str = "",
    ) -> bool:
        method = getattr(self.target, "ask_regenerate", None)
        if not method:
            return False
        try:
            method(filename, callback, mode, session_dir=session_dir)
            return True
        except Exception:
            return False

    def ask_new_api_key(self, callback: Callable) -> bool:
        method = getattr(self.target, "ask_new_api_key", None)
        if not method:
            return False
        try:
            method(callback)
            return True
        except Exception:
            return False

    def dismiss_new_api_key_prompt(self) -> None:
        self._safe_call("dismiss_new_api_key_prompt")

    def dismiss_regenerate_prompt(self) -> None:
        try:
            method = getattr(self.target, "dismiss_regenerate_prompt", None)
            if method:
                method()
        except Exception:
            pass

    def ask_confirmation(self, title: str, message: str) -> bool | None:
        try:
            window = getattr(self.target, "window", None)
            if window:
                return bool(window.create_confirmation_dialog(title, message))
        except Exception:
            return None
        return None

    def reset_temp_files(self) -> None:
        self.target.file_temporanei = []

    def track_temp_file(self, path: str) -> None:
        self.target.file_temporanei.append(path)

    def cleanup_temp_files(self) -> None:
        parent_dirs = []
        for path in list(getattr(self.target, "file_temporanei", [])):
            try:
                parent_dirs.append(os.path.dirname(os.path.abspath(path)))
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        for parent_dir in dict.fromkeys(parent_dirs):
            try:
                if (
                    os.path.basename(parent_dir).startswith("run_")
                    and os.path.basename(os.path.dirname(parent_dir)) == "temp_chunks"
                ):
                    os.rmdir(parent_dir)
            except Exception:
                pass
        self.target.file_temporanei = []

    def _safe_call(self, method_name: str, *args, **kwargs) -> None:
        try:
            if self.ui_alive() and hasattr(self.target, method_name):
                getattr(self.target, method_name)(*args, **kwargs)
        except Exception:
            pass
