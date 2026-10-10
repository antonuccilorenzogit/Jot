import io
import logging
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from jot.utils.logging_utils import LOGGER_NAME, get_logger
from jot.webview_entry import (
    _MAX_CONSOLE_LINE_LEN,
    _ConsoleTee,
    build_close_handler,
    main,
)


class WindowlessStartupLoggingTests(unittest.TestCase):
    def test_main_connects_early_logging_to_ui_without_native_console(self):
        logger = logging.getLogger(LOGGER_NAME)
        api = MagicMock()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(logger, "handlers", []),
            patch.dict(logger.__dict__, {"_jot_configured": False}),
            patch("jot.utils.logging_utils._STARTUP_PREPARED", False),
            patch("jot.utils.logging_utils.install_exception_hooks"),
            patch(
                "jot.services.config_service.get_config_dir",
                return_value=directory,
            ),
            patch("jot.app_webview.JotApi", return_value=api),
            patch(
                "jot.webview_entry.get_dist_path",
                side_effect=RuntimeError("stop before native window"),
            ),
            patch("sys.stdout", None),
            patch("sys.stderr", None),
            patch("sys.__stdout__", None),
            patch("sys.__stderr__", None),
        ):
            try:
                with self.assertRaisesRegex(RuntimeError, "stop before native window"):
                    main()
                with patch.object(logging.Handler, "handleError") as error:
                    get_logger().info("Elaborazione avviata.")
                    error.assert_not_called()
                lines = [call.args[0] for call in api._push_console.call_args_list]
                self.assertEqual(
                    sum("Elaborazione avviata." in line for line in lines), 1
                )
                self.assertFalse(any("Logging error" in line for line in lines))
                with open(
                    os.path.join(directory, "jot.log"), encoding="utf-8"
                ) as handle:
                    content = handle.read()
                self.assertIn("Avvio interfaccia:", content)
                self.assertIn("Elaborazione avviata.", content)
            finally:
                for handler in logger.handlers:
                    handler.close()


class ConsoleTeeTests(unittest.TestCase):
    def test_console_tee_writes_to_original(self):
        original = io.StringIO()
        api = MagicMock()
        tee = _ConsoleTee(original, api)

        tee.write("Hello World\n")

        self.assertEqual(original.getvalue(), "Hello World\n")
        api._push_console.assert_called_once_with("Hello World")

    def test_console_tee_ignores_empty_or_whitespace_only(self):
        original = io.StringIO()
        api = MagicMock()
        tee = _ConsoleTee(original, api)

        tee.write("   \n")

        self.assertEqual(original.getvalue(), "   \n")
        api._push_console.assert_not_called()

    def test_console_tee_redacts_api_key(self):
        original = io.StringIO()
        api = MagicMock()
        tee = _ConsoleTee(original, api)

        # Gemini API Key (starts with AIzaSy)
        key = "AIzaSyFakeKey1234567890123"
        tee.write(f"Error: invalid key: {key}\n")

        self.assertEqual(original.getvalue(), f"Error: invalid key: {key}\n")
        api._push_console.assert_called_once_with(
            "Error: invalid key: [API_KEY_REDACTED]"
        )

    def test_console_tee_redacts_before_truncating(self):
        original = io.StringIO()
        api = MagicMock()
        tee = _ConsoleTee(original, api)

        # Create a line that is longer than _MAX_CONSOLE_LINE_LEN.
        # Place an API key well before the truncation limit, but extend the line
        # with extra text so that it gets truncated.
        prefix = "x" * 1000 + " "
        key = "AIzaSyFakeKey1234567890123"
        suffix = " " + "y" * 1100
        long_line = prefix + key + suffix

        tee.write(long_line + "\n")

        # Get the argument passed to _push_console
        api._push_console.assert_called_once()
        pushed_text = api._push_console.call_args[0][0]

        # Verify that the API key was redacted, NOT truncated/leaked
        self.assertNotIn("AIzaSy", pushed_text)
        self.assertIn("[API_KEY_REDACTED]", pushed_text)
        self.assertTrue(pushed_text.endswith("\u2026 [troncato]"))


class CloseHandlerTests(unittest.TestCase):
    def test_close_when_not_busy(self):
        api = MagicMock()
        api.is_busy.return_value = False
        api._force_close = False
        window = MagicMock()
        stop_event = MagicMock()

        handler = build_close_handler(api, window, stop_event)

        with patch("jot.webview_entry.LocalMediaServer.shutdown_all") as mock_shutdown:
            result = handler()
            self.assertIsNone(result)
            window.create_confirmation_dialog.assert_not_called()
            stop_event.set.assert_called_once()
            mock_shutdown.assert_called_once()

    def test_close_when_force_close_true(self):
        api = MagicMock()
        api.is_busy.return_value = True
        api._force_close = True
        window = MagicMock()
        stop_event = MagicMock()

        handler = build_close_handler(api, window, stop_event)

        with patch("jot.webview_entry.LocalMediaServer.shutdown_all") as mock_shutdown:
            result = handler()
            self.assertIsNone(result)
            window.create_confirmation_dialog.assert_not_called()
            stop_event.set.assert_called_once()
            mock_shutdown.assert_called_once()

    def test_close_when_busy_emits_request_quit_confirmation(self):
        api = MagicMock()
        api.is_busy.return_value = True
        api._force_close = False
        window = MagicMock()
        api._adapter = MagicMock()
        api._adapter.window = window
        stop_event = MagicMock()

        handler = build_close_handler(api, window, stop_event)

        with patch("jot.webview_entry.LocalMediaServer.shutdown_all") as mock_shutdown:
            result = handler()
            self.assertFalse(result)
            api._adapter.emit.assert_called_once_with(
                "requestQuitConfirmation", {}, batched=False
            )
            window.create_confirmation_dialog.assert_not_called()
            api.request_shutdown.assert_not_called()
            stop_event.set.assert_not_called()
            mock_shutdown.assert_not_called()

    def test_close_when_busy_fallback_to_dialog_cancel(self):
        api = MagicMock()
        api.is_busy.return_value = True
        api._force_close = False
        api._adapter = None
        window = MagicMock()
        window.create_confirmation_dialog.return_value = False
        stop_event = MagicMock()

        handler = build_close_handler(api, window, stop_event)

        with patch("jot.webview_entry.LocalMediaServer.shutdown_all") as mock_shutdown:
            result = handler()
            self.assertFalse(result)
            window.create_confirmation_dialog.assert_called_once()
            api.request_shutdown.assert_not_called()
            stop_event.set.assert_not_called()
            mock_shutdown.assert_not_called()

    def test_close_when_busy_fallback_to_dialog_confirm(self):
        api = MagicMock()
        api.is_busy.return_value = True
        api._force_close = False
        api._adapter = None
        window = MagicMock()
        window.create_confirmation_dialog.return_value = True
        stop_event = MagicMock()

        handler = build_close_handler(api, window, stop_event)

        with patch("jot.webview_entry.LocalMediaServer.shutdown_all") as mock_shutdown:
            result = handler()
            self.assertIsNone(result)
            window.create_confirmation_dialog.assert_called_once()
            api.request_shutdown.assert_called_once_with(timeout=1.5)
            stop_event.set.assert_called_once()
            mock_shutdown.assert_called_once()

    def test_close_when_busy_dialog_exception_fallback(self):
        api = MagicMock()
        api.is_busy.return_value = True
        api._force_close = False
        api._adapter = None
        window = MagicMock()
        window.create_confirmation_dialog.side_effect = RuntimeError("Dialog failed")
        stop_event = MagicMock()

        handler = build_close_handler(api, window, stop_event)

        with patch("jot.webview_entry.LocalMediaServer.shutdown_all") as mock_shutdown:
            result = handler()
            self.assertIsNone(result)
            api.request_shutdown.assert_called_once_with(timeout=1.5)
            stop_event.set.assert_called_once()
            mock_shutdown.assert_called_once()


class WebuiCspTests(unittest.TestCase):
    def test_webui_csp_allows_pywebview_bridge(self):
        """Verify webui/index.html CSP permits pywebview's dynamic API bridge construction on macOS/WebKit."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        index_html = root / "webui" / "index.html"
        self.assertTrue(index_html.exists(), "webui/index.html must exist")
        content = index_html.read_text(encoding="utf-8")

        self.assertIn("Content-Security-Policy", content)
        # pywebview uses new Function(...) in api.js to expose Python bridge methods to React.
        # Without 'unsafe-eval', WebKit (macOS) raises an EvalError and completely breaks the bridge.
        self.assertIn("'unsafe-eval'", content)
        self.assertIn("'unsafe-inline'", content)


if __name__ == "__main__":
    unittest.main()
