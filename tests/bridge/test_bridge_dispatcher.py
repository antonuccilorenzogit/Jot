import io
import logging
import os
import tempfile
import threading
import time
import unittest
from functools import partial
from unittest.mock import MagicMock, patch

from jot.bridge.bridge_dispatcher import _BridgeDispatcher
from jot.utils.logging_utils import (
    LOGGER_NAME,
    attach_file_handler,
    configure_logging,
    detach_file_handler,
    get_logger,
)
from jot.webview_entry import _ConsoleTee


class BridgeDispatcherTests(unittest.TestCase):
    def _make(self, window=None, flush_interval=9999):
        """Create a dispatcher with no auto-flush (flush_interval=9999) unless specified."""
        return _BridgeDispatcher(lambda: window, flush_interval=flush_interval)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def test_unknown_event_raises(self):
        d = self._make()
        with self.assertRaises(AssertionError):
            d.emit("nonExistentEvent", {})

    def test_api_usage_updated_event_accepted(self):
        d = self._make()
        # Should not raise AssertionError
        d.emit("apiUsageUpdated", {"quota_date": "2026-09-02"}, batched=False)

    # ------------------------------------------------------------------
    # Batching / coalescing
    # ------------------------------------------------------------------

    def test_batched_events_coalesce(self):
        calls: list[str] = []
        window = MagicMock()
        window.evaluate_js.side_effect = calls.append
        d = self._make(window=window)

        d.emit("updateProgress", 0.25)
        d.emit("updateProgress", 0.75)
        d.flush()

        self.assertEqual(len(calls), 1)
        self.assertIn("0.75", calls[0])
        self.assertNotIn("0.25", calls[0])

    def test_emit_batched_false_override_goes_to_queue(self):
        calls: list[str] = []
        window = MagicMock()
        window.evaluate_js.side_effect = calls.append
        d = self._make(window=window)

        d.emit("updateProgress", 0.10, batched=False)
        d.emit("updateProgress", 0.90, batched=False)
        d.flush()

        self.assertEqual(len(calls), 1)
        js = calls[0]
        self.assertIn("0.1", js)
        self.assertIn("0.9", js)

    def test_non_batched_lifecycle_flushes_pending_batched_first(self):
        """Batched updates must appear before a lifecycle event in the same JS block."""
        order: list[str] = []
        window = MagicMock()

        def record(js):
            order.append(js)

        window.evaluate_js.side_effect = record
        d = self._make(window=window)

        d.emit("updateProgress", 0.5)
        d.emit(
            "fileDone",
            {
                "index": 0,
                "id": "f1",
                "output_html": "/x.html",
                "output_dir": "/",
                "primary_model": "",
                "effective_model": "",
            },
            batched=False,
        )
        d.flush()

        self.assertEqual(len(order), 1)
        js = order[0]
        progress_pos = js.index("updateProgress")
        file_done_pos = js.index("fileDone")
        self.assertLess(progress_pos, file_done_pos)

    # ------------------------------------------------------------------
    # Window not ready — re-queue
    # ------------------------------------------------------------------

    def test_flush_no_window_requeues_events(self):
        d = self._make(window=None)
        d.emit("appendConsole", "hello", batched=False)
        d.flush()

        with d._lock:
            pending_count = len(d._pending)

        self.assertGreater(pending_count, 0)

    def test_flush_no_window_increments_retry_count(self):
        d = self._make(window=None)
        d.emit("appendConsole", "x", batched=False)
        d.flush()

        with d._lock:
            _, _, retry = d._pending[0]

        self.assertEqual(retry, 1)

    # ------------------------------------------------------------------
    # evaluate_js failure — re-queue
    # ------------------------------------------------------------------

    def test_flush_evaluate_js_exception_requeues(self):
        window = MagicMock()
        window.evaluate_js.side_effect = RuntimeError("JS error")
        d = self._make(window=window)

        d.emit("appendConsole", "hi", batched=False)
        d.flush()

        with d._lock:
            pending_count = len(d._pending)

        self.assertGreater(pending_count, 0)

    # ------------------------------------------------------------------
    # Retry exhaustion
    # ------------------------------------------------------------------

    def test_retry_exhaustion_drops_event(self):
        d = self._make(window=None)
        d.emit("appendConsole", "drop me", batched=False)

        for _ in range(_BridgeDispatcher.MAX_RETRIES + 1):
            d.flush()

        with d._lock:
            pending_count = len(d._pending)

        self.assertEqual(pending_count, 0)

    def test_retry_exhaustion_logs_to_file_without_reentering_ui_bridge(self):
        base_logger = logging.getLogger(LOGGER_NAME)
        for failure in ("missing_window", "evaluate_js_failure"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmpdir:
                window = None
                if failure == "evaluate_js_failure":
                    window = MagicMock()
                    window.evaluate_js.side_effect = RuntimeError("WebView unavailable")
                dispatcher = self._make(window=window)
                api = MagicMock()
                api._push_console.side_effect = partial(
                    dispatcher.emit, "appendConsole", batched=False
                )
                log_path = os.path.join(tmpdir, "run.log")
                with (
                    patch.object(base_logger, "handlers", []),
                    patch.dict(base_logger.__dict__, {"_jot_configured": False}),
                    patch.object(dispatcher, "_ensure_timer") as schedule,
                ):
                    configure_logging(stream=io.StringIO())
                    configure_logging(stream=_ConsoleTee(None, api))
                    handler = attach_file_handler(log_path)
                    self.assertIsNotNone(handler)
                    try:
                        get_logger().info("Console ready.")
                        api._push_console.assert_called_once()
                        for _ in range(dispatcher.MAX_RETRIES + 1):
                            dispatcher.flush()

                        self.assertFalse(dispatcher._queue)
                        self.assertFalse(dispatcher._pending)
                        self.assertFalse(dispatcher._latest)
                        api._push_console.assert_called_once()
                        schedule.reset_mock()
                        dispatcher.flush()
                        schedule.assert_not_called()
                        if window is not None:
                            self.assertEqual(
                                window.evaluate_js.call_count,
                                dispatcher.MAX_RETRIES + 1,
                            )

                        with open(log_path, encoding="utf-8") as handle:
                            diagnostic = handle.read()
                        expected = (
                            "Eventi bridge scartati"
                            if window is None
                            else "Invio bridge fallito definitivamente"
                        )
                        self.assertEqual(diagnostic.count(expected), 1)
                        self.assertIn("appendConsole", diagnostic)
                        if window is not None:
                            self.assertIn("Traceback", diagnostic)
                            self.assertIn("WebView unavailable", diagnostic)
                    finally:
                        detach_file_handler(handler)

    # ------------------------------------------------------------------
    # Ordering: retries come after fresh events
    # ------------------------------------------------------------------

    def test_retries_appended_after_new_events(self):
        """A retry event must not precede a freshly emitted lifecycle event."""
        delivered: list[str] = []
        call_count = {"n": 0}
        window_ref = {"w": None}

        class _Win:
            def evaluate_js(self, js):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("force retry")
                delivered.append(js)

        window_ref["w"] = _Win()  # type: ignore[assignment]
        d = _BridgeDispatcher(lambda: window_ref["w"], flush_interval=9999)

        d.emit("appendConsole", "retry-me", batched=False)
        d.flush()  # fails → retry queued

        d.emit(
            "processDone",
            {"cancelled": False, "completed": 1, "failed": 0, "total": 1},
            batched=False,
        )
        d.flush()  # succeeds → both delivered in one call

        self.assertEqual(len(delivered), 1)
        js = delivered[0]
        process_done_pos = js.index("processDone")
        console_pos = js.index("appendConsole")
        self.assertLess(process_done_pos, console_pos)

    # ------------------------------------------------------------------
    # Post-flush state
    # ------------------------------------------------------------------

    def test_flush_clears_latest(self):
        window = MagicMock()
        d = self._make(window=window)
        d.emit("updateProgress", 0.5)
        d.flush()

        with d._lock:
            self.assertEqual(len(d._latest), 0)

    def test_flush_clears_queue(self):
        window = MagicMock()
        d = self._make(window=window)
        d.emit("appendConsole", "hello", batched=False)
        d.flush()

        with d._lock:
            self.assertEqual(len(d._queue), 0)

    # ------------------------------------------------------------------
    # Timer idempotency
    # ------------------------------------------------------------------

    def test_ensure_timer_idempotent(self):
        d = _BridgeDispatcher(lambda: None, flush_interval=9999)
        d.emit("updateProgress", 1)
        d.emit("updateProgress", 2)

        with d._lock:
            timer = d._timer

        assert timer is not None
        timer.cancel()

    # ------------------------------------------------------------------
    # Thread safety
    # ------------------------------------------------------------------

    def test_concurrent_emit_flush_safe(self):
        calls: list[str] = []
        lock = threading.Lock()
        window = MagicMock()

        def record(js):
            with lock:
                calls.append(js)

        window.evaluate_js.side_effect = record
        d = _BridgeDispatcher(lambda: window, flush_interval=9999)

        errors: list[Exception] = []

        def _emitter():
            try:
                for i in range(10):
                    d.emit("updateProgress", i / 10.0)
                    d.emit("appendConsole", f"line {i}", batched=False)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_emitter) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        d.flush()

        self.assertEqual(errors, [], f"Unexpected exceptions: {errors}")


if __name__ == "__main__":
    unittest.main()
