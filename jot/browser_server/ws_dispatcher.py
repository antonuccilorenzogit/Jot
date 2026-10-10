"""
WebSocket event dispatcher for jot browser server.

Implements the EventDispatcher protocol, maintaining sequence numbering,
batched collapsing, bounded replay history for reconnects, and thread-safe
broadcasting to connected WebSocket clients.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any

from jot.bridge.bridge_dispatcher import EventDispatcher, _BridgeDispatcher


class WebSocketDispatcher(EventDispatcher):
    """EventDispatcher that broadcasts events to WebSockets with sequence numbering."""

    def __init__(
        self,
        flush_interval: float = 0.08,
        history_maxlen: int = 150,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self._flush_interval = flush_interval
        self._history_maxlen = history_maxlen
        self._loop = loop
        self._lock = threading.Lock()
        self._sequence = 0
        self._history: deque[dict[str, Any]] = deque(maxlen=history_maxlen)
        self._queue: deque[tuple[str, Any]] = deque()
        self._latest: dict[str, Any] = {}
        self._timer: threading.Timer | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop

    def close(self) -> None:
        """Cancel pending work and detach all browser subscribers."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._queue.clear()
            self._latest.clear()
            self._subscribers.clear()
            self._loop = None

    @property
    def current_sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def register_subscriber(
        self, last_sequence: int = 0
    ) -> tuple[asyncio.Queue[dict[str, Any]], list[dict[str, Any]]]:
        """Register a subscriber queue and return replay events since last_sequence."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._lock:
            self._subscribers.add(q)
            replays = [e for e in self._history if e["sequence"] > last_sequence]
        return q, replays

    def unregister_subscriber(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def emit(self, fn_name: str, data: Any, batched: bool | None = None) -> None:
        assert fn_name in _BridgeDispatcher._ALL_EVENTS, (
            f"Unknown bridge event: {fn_name!r}"
        )
        should_batch = (
            fn_name in _BridgeDispatcher.BATCHABLE if batched is None else batched
        )
        with self._lock:
            if should_batch:
                self._latest[fn_name] = data
            else:
                if self._latest:
                    self._queue.extend(self._latest.items())
                    self._latest.clear()
                self._queue.append((fn_name, data))
        self._ensure_timer()

    def _ensure_timer(self) -> None:
        with self._lock:
            if self._timer is None:
                t = threading.Timer(self._flush_interval, self.flush)
                t.daemon = True
                self._timer = t
                t.start()

    def flush(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

            items: list[tuple[str, Any]] = []
            if self._queue:
                items.extend(self._queue)
                self._queue.clear()
            if self._latest:
                items.extend(self._latest.items())
                self._latest.clear()

            if not items:
                return

            packaged: list[dict[str, Any]] = []
            for fn_name, data in items:
                self._sequence += 1
                evt = {
                    "sequence": self._sequence,
                    "name": fn_name,
                    "payload": data,
                }
                self._history.append(evt)
                packaged.append(evt)

            subscribers = list(self._subscribers)
            loop = self._loop

        if not subscribers:
            return

        def _broadcast():
            for evt in packaged:
                for q in subscribers:
                    try:
                        q.put_nowait(evt)
                    except Exception:
                        pass

        if loop is not None and loop.is_running():
            try:
                running_loop = None
                try:
                    running_loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass
                if running_loop is loop:
                    _broadcast()
                else:
                    loop.call_soon_threadsafe(_broadcast)
            except Exception:
                pass
        else:
            _broadcast()
