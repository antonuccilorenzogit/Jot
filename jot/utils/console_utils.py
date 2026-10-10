"""Line-oriented forwarding of Python output to the application console."""

from __future__ import annotations

import threading
from collections.abc import Callable

from jot.utils.logging_utils import LogStream, redact_secrets

MAX_CONSOLE_LINE_LEN = 2000
MAX_PENDING_LINE_LEN = 65_536
OVERSIZED_LINE_MESSAGE = "[console] Riga troppo lunga: contenuto omesso."


class _ThreadLineState(threading.local):
    def __init__(self) -> None:
        self.pending = ""
        self.overflow = False


class LineConsoleTee:
    """Keep native output immediate, but forward complete, sanitized UI lines.

    Pending lines belong to the calling thread. A flush only drains that thread,
    so another worker cannot publish a partial traceback or split API key.
    """

    def __init__(
        self,
        original: LogStream | None,
        emit: Callable[[str], object],
        *,
        keep_line: Callable[[str], bool] | None = None,
    ) -> None:
        self._original = original
        self._emit = emit
        self._keep_line = keep_line
        self._line_state = _ThreadLineState()
        self._lock = threading.RLock()

    def _finish_line(self) -> None:
        state = self._line_state
        raw, overflow = state.pending, state.overflow
        state.pending, state.overflow = "", False
        if overflow:
            self._emit(OVERSIZED_LINE_MESSAGE)
            return
        if not raw.strip():
            return
        line = redact_secrets(raw.rstrip())
        if self._keep_line is not None and not self._keep_line(line):
            return
        if len(line) > MAX_CONSOLE_LINE_LEN:
            line = line[:MAX_CONSOLE_LINE_LEN] + "… [troncato]"
        self._emit(line)

    def write(self, text: str) -> None:
        with self._lock:
            if self._original is not None:
                try:
                    self._original.write(text)
                except Exception:
                    pass
            state = self._line_state
            # Slice only the retained prefix: a huge write must not create an
            # equally huge pending buffer or a list of all its newline splits.
            start = 0
            while start < len(text):
                newline = text.find("\n", start)
                end = len(text) if newline < 0 else newline
                if not state.overflow:
                    if len(state.pending) + end - start > MAX_PENDING_LINE_LEN:
                        state.pending = ""
                        state.overflow = True
                    else:
                        state.pending += text[start:end]
                if newline < 0:
                    break
                self._finish_line()
                start = newline + 1

    def flush(self) -> None:
        with self._lock:
            try:
                self._finish_line()
            finally:
                if self._original is not None:
                    try:
                        self._original.flush()
                    except Exception:
                        pass
