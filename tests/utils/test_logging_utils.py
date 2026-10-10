import io
import json
import logging
import os
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

from jot.utils.logging_utils import (
    LOGGER_NAME,
    StructuredFormatter,
    attach_file_handler,
    configure_logging,
    detach_file_handler,
    get_logger,
    get_startup_diagnostic,
    initialize_app_logging,
    record_startup_diagnostic,
    redact_secrets,
)


class StructuredFormatterTests(unittest.TestCase):
    def _make_record(self, msg="test message", **context):
        record = logging.LogRecord(
            name=LOGGER_NAME,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for key, value in context.items():
            setattr(record, key, value)
        return record

    def test_no_context_returns_base_format(self):
        fmt = StructuredFormatter("%(message)s", "%H:%M:%S")
        record = self._make_record("hello")
        result = fmt.format(record)
        self.assertEqual(result, "hello")

    def test_with_context_appends_key_value_pairs(self):
        fmt = StructuredFormatter("%(message)s", "%H:%M:%S")
        record = self._make_record("hello", run_id="abc123", stage="phase1")
        result = fmt.format(record)
        self.assertIn("run_id=abc123", result)
        self.assertIn("stage=phase1", result)
        self.assertIn("[", result)

    def test_empty_context_values_not_appended(self):
        fmt = StructuredFormatter("%(message)s", "%H:%M:%S")
        record = self._make_record("hello", run_id="", session_dir=None)
        result = fmt.format(record)
        self.assertNotIn("[", result)

    def test_redacts_secrets_from_message_and_context(self):
        fmt = StructuredFormatter("%(message)s", "%H:%M:%S")
        key = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        record = self._make_record(
            f"failed with key={key}",
            input_file=f"https://example.test/?key={key}",
        )
        result = fmt.format(record)
        self.assertNotIn(key, result)
        self.assertIn("[API_KEY_REDACTED]", result)


class RedactSecretsTests(unittest.TestCase):
    def test_redacts_gemini_aq_and_query_string_keys(self):
        gemini_key = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        aq_key = "AQ.abcdefghijklmnopqrstuvwxyz0123456789"
        text = (
            f"Authorization failed for {gemini_key}; backup={aq_key}; "
            f"https://example.test/path?key={gemini_key}&x=1"
        )
        result = redact_secrets(text)
        self.assertNotIn(gemini_key, result)
        self.assertNotIn(aq_key, result)
        self.assertIn("[API_KEY_REDACTED]", result)

    def test_handles_falsy_values_correctly(self):
        self.assertEqual(redact_secrets(0), "0")
        self.assertEqual(redact_secrets(False), "False")
        self.assertEqual(redact_secrets(None), "")
        self.assertEqual(redact_secrets(""), "")


class ConfigureLoggingTests(unittest.TestCase):
    def setUp(self):
        logger = logging.getLogger(LOGGER_NAME)
        logger.__dict__.pop("_jot_configured", None)
        logger.handlers = [
            h for h in logger.handlers if type(h) is not logging.StreamHandler
        ]

    def tearDown(self):
        logger = logging.getLogger(LOGGER_NAME)
        if not getattr(logger, "_jot_configured", False):
            configure_logging()

    def test_returns_logger_with_correct_name(self):
        logger = configure_logging(stream=io.StringIO())
        self.assertEqual(logger.name, LOGGER_NAME)

    def test_second_call_returns_same_logger_without_adding_handler(self):
        stream = io.StringIO()
        logger1 = configure_logging(stream=stream)
        handler_count_before = len(logger1.handlers)
        logger2 = configure_logging(stream=stream)
        self.assertIs(logger1, logger2)
        self.assertEqual(len(logger2.handlers), handler_count_before)

    def test_missing_standard_streams_preserve_file_logging(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.log")
            with patch("sys.stdout", None), patch("sys.stderr", None):
                logger = configure_logging()
                handler = attach_file_handler(path)
                try:
                    with patch.object(logging.Handler, "handleError") as error:
                        logger.info("Elaborazione avviata.")
                        error.assert_not_called()
                    with open(path, encoding="utf-8") as handle:
                        self.assertIn("Elaborazione avviata.", handle.read())
                finally:
                    detach_file_handler(handler)

    def test_console_can_be_attached_after_startup_without_standard_streams(self):
        with patch("sys.stdout", None), patch("sys.stderr", None):
            configure_logging()
        stream = io.StringIO()
        configure_logging(stream=stream)
        get_logger().info("Elaborazione avviata.")
        self.assertIn("Elaborazione avviata.", stream.getvalue())

    def test_explicit_stream_replaces_console_without_replacing_file_handler(self):
        original = io.StringIO()
        replacement = io.StringIO()
        logger = configure_logging(stream=original)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.log")
            handler = attach_file_handler(path)
            try:
                count = len(logger.handlers)
                configure_logging(stream=replacement)
                configure_logging()
                logger.info("Elaborazione avviata.")
                self.assertEqual(len(logger.handlers), count)
                self.assertEqual(original.getvalue(), "")
                self.assertEqual(
                    replacement.getvalue().count("Elaborazione avviata."), 1
                )
                with open(path, encoding="utf-8") as handle:
                    self.assertIn("Elaborazione avviata.", handle.read())
            finally:
                detach_file_handler(handler)


class GetLoggerTests(unittest.TestCase):
    def test_returns_logger_adapter(self):
        adapter = get_logger()
        self.assertIsInstance(adapter, logging.LoggerAdapter)

    def test_context_included_in_adapter_extra(self):
        adapter = get_logger(run_id="run-42", stage="phase2")
        assert adapter.extra is not None
        self.assertEqual(adapter.extra.get("run_id"), "run-42")
        self.assertEqual(adapter.extra.get("stage"), "phase2")

    def test_empty_context_values_excluded(self):
        adapter = get_logger(run_id="", session_dir=None)  # type: ignore[arg-type]
        assert adapter.extra is not None
        self.assertNotIn("run_id", adapter.extra)
        self.assertNotIn("session_dir", adapter.extra)

    def test_named_sub_logger(self):
        adapter = get_logger(name="jot.pipeline")
        self.assertEqual(adapter.logger.name, "jot.pipeline")


class AttachDetachFileHandlerTests(unittest.TestCase):
    def test_attach_creates_file_and_returns_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "sub", "app.log")
            handler = attach_file_handler(log_path)
            try:
                self.assertIsNotNone(handler)
                self.assertTrue(os.path.exists(log_path))
            finally:
                detach_file_handler(handler)

    def test_attach_invalid_path_returns_none(self):
        handler = attach_file_handler("\x00invalid\x00path.log")
        self.assertIsNone(handler)

    def test_detach_none_is_noop(self):
        detach_file_handler(None)

    def test_detach_removes_handler_from_logger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            handler = attach_file_handler(log_path)
            self.assertIsNotNone(handler)
            logger = configure_logging()
            self.assertIn(handler, logger.handlers)
            detach_file_handler(handler)
            self.assertNotIn(handler, logger.handlers)

    def test_detach_handler_exception_safety(self):
        from unittest.mock import MagicMock

        mock_handler = MagicMock()
        mock_handler.close.side_effect = Exception("close err")
        detach_file_handler(mock_handler)


class AppLoggingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.directory_patch = patch(
            "jot.services.config_service.get_config_dir",
            return_value=self.directory.name,
        )
        self.directory_patch.start()

    def tearDown(self):
        for handler in list(configure_logging().handlers):
            if getattr(handler, "_el_general_log", False):
                detach_file_handler(handler)
        self.directory_patch.stop()
        self.directory.cleanup()

    def test_general_log_is_idempotent_and_sanitized(self):
        path = initialize_app_logging()
        assert path is not None
        self.assertEqual(initialize_app_logging(), path)
        handlers = [
            h
            for h in configure_logging().handlers
            if getattr(h, "_el_general_log", False)
        ]
        self.assertEqual(len(handlers), 1)
        secret = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        get_logger().warning("loader failure api_key=%s", secret)
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertNotIn(secret, content)
        self.assertIn("API_KEY_REDACTED", content)

    def test_rotation_preserves_startup_snapshot_and_excludes_session_details(self):
        path = initialize_app_logging()
        assert path is not None
        handler = next(
            h
            for h in configure_logging().handlers
            if getattr(h, "_el_general_log", False)
        )
        assert isinstance(handler, RotatingFileHandler)
        handler.maxBytes = 250
        record_startup_diagnostic(renderer="mshtml", native_error="missing runtime")
        get_logger(session_dir="private_session", input_file="private_audio.wav").info(
            "private transcript"
        )
        for n in range(20):
            get_logger().info("ordinary event %s %s", n, "x" * 80)
        self.assertTrue(os.path.isfile(path + ".1"))
        self.assertFalse(os.path.exists(path + ".4"))
        for filename in os.listdir(self.directory.name):
            if filename.startswith("jot.log"):
                with open(
                    os.path.join(self.directory.name, filename), encoding="utf-8"
                ) as handle:
                    self.assertNotIn("private transcript", handle.read())
        self.assertEqual(get_startup_diagnostic()["native_error"], "missing runtime")

    def test_snapshot_redacts_errors_and_survives_corruption(self):
        secret = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        record_startup_diagnostic(native_error=secret)
        self.assertNotIn(secret, json.dumps(get_startup_diagnostic()))
        with open(
            os.path.join(self.directory.name, "startup_diagnostic.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("invalid json")
        self.assertEqual(get_startup_diagnostic(), {})

    def test_unwritable_log_does_not_interrupt_startup(self):
        with patch("os.makedirs", side_effect=PermissionError()):
            self.assertIsNone(initialize_app_logging())
            record_startup_diagnostic(status="starting")


if __name__ == "__main__":
    unittest.main()
