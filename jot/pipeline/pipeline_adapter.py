"""
Pipeline adapter and DnD helper for jot.

PipelineAdapter is the object passed to pipeline.py as "app_instance".
It implements the same duck-typed interface that the old desktop UI (CTk) provided.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Literal, cast

import webview

from jot.bridge.bridge_dispatcher import EventDispatcher, _BridgeDispatcher
from jot.bridge.bridge_types import (
    WorkDonePayload,
    WorkTotalsPayload,
)
from jot.utils.logging_utils import redact_secrets

# ---------------------------------------------------------------------------
# DnD helper
# ---------------------------------------------------------------------------


def _drain_dnd_paths(names: set[str]) -> list[tuple[str, str]]:
    """Return and consume (basename, fullpath) pairs matching *names* from
    pywebview's internal DnD state.

    ``webview.dom._dnd_state`` is an undocumented private implementation
    detail. All access is intentionally confined here so that a future
    pywebview refactor breaks only this one function and always produces a
    safe empty-list fallback.
    """
    try:
        from webview.dom import _dnd_state

        paths: list = list(_dnd_state.get("paths", []))
        matched, remaining = [], []
        for item in paths:
            (matched if item[0] in names else remaining).append(item)
        _dnd_state["paths"] = remaining
        return matched
    except Exception:
        return []


# ---------------------------------------------------------------------------
# PipelineAdapter: oggetto passato a pipeline.py come "app_instance"
# Implementa la stessa interfaccia duck-typed della UI desktop (CTk).
# ---------------------------------------------------------------------------


class PipelineAdapter:
    """Thin adapter mimicking the attributes/methods that pipeline.py reads."""

    def __init__(
        self,
        window: webview.Window | None,
        cancel_event: threading.Event,
        dispatcher: EventDispatcher | None = None,
    ):
        self.window = window
        self.cancel_event = cancel_event
        self._lock = threading.Lock()
        self.file_temporanei: list[str] = []
        self._is_running = False
        self._run_started_monotonic: float | None = None
        self._step_times: dict[str, float] = {}

        # Output info (set by pipeline)
        self.last_output_html: str | None = None
        self.last_output_dir: str | None = None
        self.last_primary_model: str | None = None
        self.last_effective_model: str | None = None
        self.last_revision_failed_blocks: list[int] = []
        self.last_run_status: str = "idle"
        self.last_run_error: str | None = None
        self.last_run_error_detail: str | None = None
        self.last_retry_state: dict[str, Any] | None = None
        self.effective_api_key: str | None = None

        # Pending UI-answer callbacks (written by pipeline thread, read by UI thread)
        self._regenerate_callback = None
        self._new_key_callback = None
        self._has_explicit_dispatcher = dispatcher is not None

        self._dispatcher: EventDispatcher = (
            dispatcher
            if dispatcher is not None
            else _BridgeDispatcher(lambda: self.window, flush_interval=0.08)
        )

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    @is_running.setter
    def is_running(self, value: bool) -> None:
        with self._lock:
            self._is_running = value

    # --- Methods called by pipeline.py's safe_* wrappers ---

    def winfo_exists(self) -> bool:
        try:
            return self.window is not None or self._has_explicit_dispatcher
        except Exception:
            return False

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def after(self, delay_ms: int, callback, *args):
        """Schedule a callback. We just run it in a timer thread."""

        def _run():
            time.sleep(delay_ms / 1000.0)
            try:
                callback(*args)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def aggiorna_progresso(self, value: float):
        self._emit_js("updateProgress", value, batched=True)

    def update_model(self, model: str):
        m = str(model or "").strip() or None
        if self.last_primary_model is None:
            self.last_primary_model = m
        self.last_effective_model = m
        self._emit_js("updateModel", m or "", batched=True)

    def aggiorna_fase(self, text: str):
        self._emit_js("updatePhase", text, batched=True)

    def imposta_output_html(self, path: str, output_dir: str | None = None):
        self.last_output_html = path
        if output_dir is not None:
            self.last_output_dir = output_dir
        else:
            self.last_output_dir = os.path.dirname(path) if path else None

    def processo_terminato(self):
        # Hook per fine file: il lifecycle del batch e' gestito da JotApi.start_processing.
        return None

    def reset_run_state(self, api_key: str | None = None):
        self.last_output_html = None
        self.last_output_dir = None
        self.last_primary_model = None
        self.last_effective_model = None
        self.last_revision_failed_blocks = []
        self.last_run_status = "failed"
        self.last_run_error = None
        self.last_run_error_detail = None
        self.last_retry_state = None
        self.effective_api_key = str(api_key or "").strip() or None

    def set_run_result(self, status: str, error: str | None = None):
        self.last_run_status = str(status or "failed").strip() or "failed"
        self.last_run_error = redact_secrets(error).strip() if error else None

    def set_run_error_detail(self, detail: str | None = None):
        self.last_run_error_detail = redact_secrets(detail).strip() if detail else None

    def set_effective_api_key(self, api_key: str | None):
        self.effective_api_key = str(api_key or "").strip() or None

    def set_work_totals(self, chunks_total=None, macro_total=None):
        payload: WorkTotalsPayload = {
            "chunks": chunks_total,
            "macro": macro_total,
        }
        self._emit_js("setWorkTotals", payload, batched=True)

    def update_work_done(self, kind: str, done: int, total: int | None = None):
        payload: WorkDonePayload = {
            "kind": cast(Literal["chunks", "macro"], kind),
            "done": done,
            "total": total,
        }
        self._emit_js("updateWorkDone", payload, batched=True)

    def emit_retry_state(self, payload: dict[str, Any]):
        self.last_retry_state = dict(payload)
        self._emit_js("retryStateChanged", payload, batched=False)

    def register_step_time(
        self,
        kind: str,
        seconds: float,
        done: int | None = None,
        total: int | None = None,
    ):
        pass

    def ask_regenerate(
        self, filename: str, callback, mode: str = "resume", session_dir: str = ""
    ):
        with self._lock:
            self._regenerate_callback = callback
        self._emit_js(
            "askRegenerate",
            {"filename": filename, "mode": mode, "sessionDir": session_dir},
            batched=False,
        )

    def ask_new_api_key(self, callback):
        with self._lock:
            self._new_key_callback = callback
        self._emit_js("askNewKey", {}, batched=False)

    def dismiss_new_api_key_prompt(self):
        with self._lock:
            self._new_key_callback = None
        self._emit_js("dismissNewKey", {}, batched=False)

    def dismiss_regenerate_prompt(self):
        with self._lock:
            self._regenerate_callback = None

    def answer_regenerate(self, regenerate: bool | None):
        with self._lock:
            cb = self._regenerate_callback
            self._regenerate_callback = None
        if not cb:
            return
        if regenerate is None:
            self.cancel_event.set()
        cb({"regenerate": regenerate})

    def answer_new_key(self, key: str):
        with self._lock:
            cb = self._new_key_callback
            self._new_key_callback = None
        if cb:
            cb({"key": key})

    def cancel_pending_prompts(self):
        with self._lock:
            regenerate_cb = self._regenerate_callback
            new_key_cb = self._new_key_callback
            self._regenerate_callback = None
            self._new_key_callback = None
        if regenerate_cb:
            regenerate_cb({"regenerate": False})
        if new_key_cb:
            new_key_cb({"key": ""})

    # --- Internal helper ---

    def emit(self, fn_name: str, data, batched: bool | None = None):
        self._emit_js(fn_name, data, batched=batched)

    def _emit_js(self, fn_name: str, data, batched: bool | None = None):
        self._dispatcher.emit(fn_name, data, batched=batched)
