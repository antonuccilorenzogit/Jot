import os
import threading
import unittest
from unittest.mock import MagicMock, patch

from jot.bridge.bridge_utils import (
    _ALLOWED_URL_PREFIXES,
    _candidate_from_relative,
    _normalize_revision_failed_blocks,
    _path_under_root,
    _retry_no_failed_blocks_response,
    _retry_would_overwrite_user_html,
    _retry_zero_retried_response,
    _RetryRuntime,
    _safe_relpath,
)


class TestBridgeUtils(unittest.TestCase):
    def test_path_under_root(self):
        root = os.path.realpath("/base/dir")
        child = os.path.realpath("/base/dir/subdir/file.txt")
        outside = os.path.realpath("/other/dir/file.txt")

        self.assertTrue(_path_under_root(root, root))
        self.assertTrue(_path_under_root(child, root))
        self.assertFalse(_path_under_root(outside, root))

    def test_safe_relpath(self):
        rel = _safe_relpath("/a/b/c", "/a")
        self.assertIsNotNone(rel)

        # On error (e.g. ValueError when on different drives or invalid paths)
        with patch("os.path.relpath", side_effect=ValueError("different drive")):
            self.assertIsNone(_safe_relpath("/a/b/c", "/x"))

    def test_candidate_from_relative(self):
        base = os.path.realpath("/base/dir")
        self.assertIsNone(_candidate_from_relative(base, ""))
        self.assertIsNone(_candidate_from_relative(base, None))
        self.assertIsNone(_candidate_from_relative(base, "/absolute/path"))
        candidate = _candidate_from_relative(base, "sub/file.html")
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertTrue(candidate.endswith(os.path.join("sub", "file.html")))

    def test_normalize_revision_failed_blocks(self):
        self.assertEqual(_normalize_revision_failed_blocks(None), [])
        self.assertEqual(_normalize_revision_failed_blocks("invalid"), [])
        self.assertEqual(
            _normalize_revision_failed_blocks([0, "1", " 2 ", "abc", -3]), [0, 1, 2]
        )

    def test_retry_runtime(self):
        adapter = MagicMock()
        cancel_event = threading.Event()
        runtime = _RetryRuntime(adapter, cancel_event)

        self.assertFalse(runtime.cancelled())
        cancel_event.set()
        self.assertTrue(runtime.cancelled())

        # Telemetry hook forwarding coverage
        runtime.phase("test")
        adapter.aggiorna_fase.assert_called_once_with("test")
        runtime.progress(0.5)
        adapter.aggiorna_progresso.assert_called_once_with(0.5)
        runtime.set_work_totals(chunks_total=10, macro_total=5)
        adapter.set_work_totals.assert_called_once_with(chunks_total=10, macro_total=5)
        runtime.update_work_done("macro", 2, total=5)
        adapter.update_work_done.assert_called_once_with("macro", 2, total=5)
        self.assertIsNone(runtime.register_step_time("step1", 1.2))

        # Effective API key
        runtime.set_effective_api_key("  secret_key  ")
        self.assertEqual(runtime.effective_api_key, "secret_key")
        runtime.set_effective_api_key("")
        self.assertIsNone(runtime.effective_api_key)

        # ask_new_api_key
        cb = MagicMock()
        self.assertTrue(runtime.ask_new_api_key(cb))
        adapter.ask_new_api_key.assert_called_once_with(cb)

        adapter.ask_new_api_key.side_effect = RuntimeError("fail")
        self.assertFalse(runtime.ask_new_api_key(cb))

        # dismiss_new_api_key_prompt
        adapter.dismiss_new_api_key_prompt.side_effect = None
        runtime.dismiss_new_api_key_prompt()
        adapter.dismiss_new_api_key_prompt.assert_called_once()

        adapter.dismiss_new_api_key_prompt.side_effect = RuntimeError("fail")
        # should not raise
        runtime.dismiss_new_api_key_prompt()

    def test_retry_zero_retried_response(self):
        # retried_blocks non-empty returns None
        self.assertIsNone(
            _retry_zero_retried_response(
                retried_blocks=[1],
                remaining=[],
                cancelled=False,
                quota_exhausted=False,
                session_dir="/dir",
                html_path="/dir/doc.html",
            )
        )

        # cancelled
        res_cancelled = _retry_zero_retried_response(
            retried_blocks=[],
            remaining=[1],
            cancelled=True,
            quota_exhausted=False,
            session_dir="/dir",
            html_path="/dir/doc.html",
        )
        self.assertIsNotNone(res_cancelled)
        assert res_cancelled is not None
        self.assertFalse(res_cancelled["ok"])
        self.assertEqual(res_cancelled["error"], "Operazione annullata.")

        # quota_exhausted
        res_quota = _retry_zero_retried_response(
            retried_blocks=[],
            remaining=[1],
            cancelled=False,
            quota_exhausted=True,
            session_dir="/dir",
            html_path="/dir/doc.html",
        )
        self.assertIsNotNone(res_quota)
        assert res_quota is not None
        self.assertFalse(res_quota["ok"])
        self.assertIn("Quota", res_quota["error"])

        # remaining blocks
        res_remaining = _retry_zero_retried_response(
            retried_blocks=[],
            remaining=[1, 2],
            cancelled=False,
            quota_exhausted=False,
            session_dir="/dir",
            html_path="/dir/doc.html",
        )
        self.assertIsNotNone(res_remaining)
        assert res_remaining is not None
        self.assertFalse(res_remaining["ok"])
        self.assertIn("Nessun blocco", res_remaining["error"])

        # no remaining blocks and no retried blocks (success edge case)
        res_ok = _retry_zero_retried_response(
            retried_blocks=[],
            remaining=[],
            cancelled=False,
            quota_exhausted=False,
            session_dir="/dir",
            html_path="/dir/doc.html",
        )
        self.assertIsNotNone(res_ok)
        assert res_ok is not None
        self.assertTrue(res_ok["ok"])
        self.assertEqual(res_ok["html_path"], "/dir/doc.html")

    def test_retry_would_overwrite_user_html(self):
        self.assertTrue(_retry_would_overwrite_user_html({"user_edited": True}, None))
        self.assertTrue(
            _retry_would_overwrite_user_html({"user_edited": None}, "/path/to.html")
        )
        self.assertFalse(
            _retry_would_overwrite_user_html({"user_edited": False}, "/path/to.html")
        )
        self.assertFalse(_retry_would_overwrite_user_html({}, None))

    def test_retry_no_failed_blocks_response(self):
        self.assertIsNone(_retry_no_failed_blocks_response({}, [1, 2], "/session"))
        res = _retry_no_failed_blocks_response(
            {"outputs": {"html": "/path/output.html"}}, [], "/session"
        )
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res["ok"])
        self.assertEqual(res["html_path"], "/path/output.html")
        self.assertEqual(res["session_dir"], "/session")

    def test_allowed_url_prefixes(self):
        self.assertTrue(any("github.com" in p for p in _ALLOWED_URL_PREFIXES))


if __name__ == "__main__":
    unittest.main()
