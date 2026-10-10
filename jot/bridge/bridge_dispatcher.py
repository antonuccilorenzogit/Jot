"""
JS bridge dispatcher for jot.

Handles batching, ordering, and retry logic for pywebview evaluate_js calls.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Any, Literal, Protocol, get_args, runtime_checkable

from jot.utils.logging_utils import get_logger


@runtime_checkable
class EventDispatcher(Protocol):
    """Protocol defining the interface for bridge event dispatchers."""

    def emit(self, fn_name: str, data: Any, batched: bool | None = None) -> None: ...

    def flush(self) -> None: ...


class _BridgeDispatcher:
    _BridgeEvent = Literal[
        "updateProgress",
        "updatePhase",
        "updateModel",
        "setWorkTotals",
        "updateWorkDone",
        "registerStepTime",
        "setCurrentFile",
        "fileDone",
        "fileFailed",
        "filesDropped",
        "processDone",
        "appendConsole",
        "askRegenerate",
        "askNewKey",
        "dismissNewKey",
        "updateDownloadProgress",
        "apiUsageUpdated",
        "requestQuitConfirmation",
    ]
    _ALL_EVENTS: frozenset[str] = frozenset(get_args(_BridgeEvent))
    BATCHABLE: frozenset[str] = frozenset(
        {
            "updateProgress",
            "updatePhase",
            "updateModel",
            "setWorkTotals",
            "updateWorkDone",
            "registerStepTime",
        }
    )
    MAX_RETRIES = 3

    def __init__(self, window_getter, flush_interval: float = 0.12):
        self._window_getter = window_getter
        self._flush_interval = flush_interval
        self._lock = threading.Lock()
        self._queue: deque[tuple[str, object]] = deque()
        self._latest: dict[str, object] = {}
        self._pending: deque[tuple[str, object, int]] = (
            deque()
        )  # (fn_name, data, retry_count)
        self._timer: threading.Timer | None = None

    def emit(self, fn_name: str, data, batched: bool | None = None):
        assert fn_name in self._ALL_EVENTS, f"Unknown bridge event: {fn_name!r}"
        should_batch = fn_name in self.BATCHABLE if batched is None else batched
        with self._lock:
            if should_batch:
                self._latest[fn_name] = data
            else:
                # Preserve event ordering across file boundaries: flush any pending
                # batched progress/phase updates before lifecycle events like
                # setCurrentFile/fileDone, otherwise stale progress can land on the
                # next file currently marked as processing in the frontend.
                if self._latest:
                    self._queue.extend(self._latest.items())
                    self._latest.clear()
                self._queue.append((fn_name, data))
        self._ensure_timer()

    def flush(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = None
            events: list[tuple[str, object, int]] = []
            # New queued events first (maintain causal order)
            for fn_name, data in self._queue:
                events.append((fn_name, data, 0))
            self._queue.clear()
            # Merge latest batched values as new events with retry_count=0
            if self._latest:
                for fn_name, data in self._latest.items():
                    events.append((fn_name, data, 0))
                self._latest.clear()
            # Retries appended last — they're stale and must not precede newer lifecycle events
            while self._pending:
                fn_name, data, retry_count = self._pending.popleft()
                events.append((fn_name, data, retry_count))

        if not events:
            return

        try:
            window = self._window_getter()
        except Exception:
            window = None

        if window is None:
            # Re-queue all events if window not ready
            with self._lock:
                for fn_name, data, retry_count in events:
                    if retry_count < self.MAX_RETRIES:
                        self._pending.append((fn_name, data, retry_count + 1))
            dropped = [
                name for name, _, attempt in events if attempt >= self.MAX_RETRIES
            ]
            if dropped:
                get_logger("jot.bridge").warning(
                    "Eventi bridge scartati: %s (finestra non disponibile)",
                    sorted(set(dropped)),
                    extra={"diagnostic_only": True},
                )
            self._ensure_timer()
            return

        js_calls: list[str] = []
        for fn_name, payload, _retry_count in events:
            safe_data = json.dumps(payload, ensure_ascii=False)
            js_calls.append(
                f"if(window.jotBridge && window.jotBridge.{fn_name}) "
                f"window.jotBridge.{fn_name}({safe_data});"
            )

        try:
            window.evaluate_js("\n".join(js_calls))
        except Exception:
            # Re-queue unsent events for retry (respecting max retries)
            with self._lock:
                for fn_name, data, retry_count in events:
                    if retry_count < self.MAX_RETRIES:
                        self._pending.append((fn_name, data, retry_count + 1))
            dropped = [
                name for name, _, attempt in events if attempt >= self.MAX_RETRIES
            ]
            if dropped:
                get_logger("jot.bridge").exception(
                    "Invio bridge fallito definitivamente: %s",
                    sorted(set(dropped)),
                    extra={"diagnostic_only": True},
                )
            self._ensure_timer()

    def _ensure_timer(self):
        """Schedule next flush attempt."""
        with self._lock:
            if self._timer is not None:
                return
            self._timer = threading.Timer(self._flush_interval, self.flush)
            self._timer.daemon = True
            self._timer.start()
