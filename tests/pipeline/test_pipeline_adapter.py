import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jot.pipeline.pipeline_adapter import PipelineAdapter, _drain_dnd_paths


def _make_adapter(window=None):
    return PipelineAdapter(window, threading.Event())


class DrainDndPathsTests(unittest.TestCase):
    def test_except_path_returns_empty_list(self):
        with patch.dict(sys.modules, {"webview.dom": None}):
            result = _drain_dnd_paths({"file.mp3"})
        self.assertEqual(result, [])

    def test_matches_and_remaining_correctly_partitioned(self):
        fake_state = {"paths": [("a.mp3", "/dir/a.mp3"), ("b.mp3", "/dir/b.mp3")]}
        mock_dom = MagicMock()
        mock_dom._dnd_state = fake_state
        with patch.dict(sys.modules, {"webview.dom": mock_dom}):
            result = _drain_dnd_paths({"a.mp3"})
        self.assertEqual(result, [("a.mp3", "/dir/a.mp3")])
        self.assertEqual(fake_state["paths"], [("b.mp3", "/dir/b.mp3")])

    def test_empty_names_returns_empty_and_leaves_state(self):
        fake_state = {"paths": [("a.mp3", "/dir/a.mp3")]}
        mock_dom = MagicMock()
        mock_dom._dnd_state = fake_state
        with patch.dict(sys.modules, {"webview.dom": mock_dom}):
            result = _drain_dnd_paths(set())
        self.assertEqual(result, [])
        self.assertEqual(fake_state["paths"], [("a.mp3", "/dir/a.mp3")])


class PipelineAdapterBasicTests(unittest.TestCase):
    def test_is_running_setter_and_getter(self):
        adapter = _make_adapter()
        self.assertFalse(adapter.is_running)
        adapter.is_running = True
        self.assertTrue(adapter.is_running)
        adapter.is_running = False
        self.assertFalse(adapter.is_running)

    def test_is_cancelled_reflects_cancel_event(self):
        cancel = threading.Event()
        adapter = PipelineAdapter(None, cancel)
        self.assertFalse(adapter.is_cancelled())
        cancel.set()
        self.assertTrue(adapter.is_cancelled())

    def test_winfo_exists_true_when_window_set(self):
        adapter = PipelineAdapter(MagicMock(), threading.Event())
        self.assertTrue(adapter.winfo_exists())

    def test_winfo_exists_false_when_window_none(self):
        self.assertFalse(_make_adapter(None).winfo_exists())

    def test_after_executes_callback_eventually(self):
        adapter = _make_adapter()
        done = threading.Event()
        adapter.after(10, done.set)
        self.assertTrue(done.wait(timeout=2.0), "callback should fire within 2s")

    def test_after_swallows_callback_exception(self):
        adapter = _make_adapter()
        done = threading.Event()

        def boom():
            done.set()
            raise ValueError("intentional")

        adapter.after(5, boom)
        self.assertTrue(done.wait(timeout=2.0))

    def test_processo_terminato_returns_none(self):
        self.assertIsNone(_make_adapter().processo_terminato())

    def test_imposta_output_html_without_output_dir_uses_dirname(self):
        adapter = _make_adapter()
        adapter.imposta_output_html("/some/dir/output.html")
        self.assertEqual(adapter.last_output_html, "/some/dir/output.html")
        self.assertEqual(adapter.last_output_dir, "/some/dir")

    def test_imposta_output_html_with_explicit_output_dir(self):
        adapter = _make_adapter()
        adapter.imposta_output_html("/a/output.html", output_dir="/custom/dir")
        self.assertEqual(adapter.last_output_dir, "/custom/dir")

    def test_set_run_result_stores_status_and_error(self):
        adapter = _make_adapter()
        adapter.set_run_result("completed", error=None)
        self.assertEqual(adapter.last_run_status, "completed")
        self.assertIsNone(adapter.last_run_error)
        adapter.set_run_result("failed", error="something went wrong")
        self.assertEqual(adapter.last_run_status, "failed")
        self.assertEqual(adapter.last_run_error, "something went wrong")

    def test_set_run_result_redacts_secret(self):
        adapter = _make_adapter()
        secret = "AIza" + ("C" * 24)
        adapter.set_run_result("failed", f"SDK failed api_key={secret}")
        self.assertNotIn(secret, adapter.last_run_error or "")
        self.assertIn("[API_KEY_REDACTED]", adapter.last_run_error or "")

    def test_set_run_error_detail_stores_detail(self):
        adapter = _make_adapter()
        adapter.set_run_error_detail(" api_key_prompt_timeout ")
        self.assertEqual(adapter.last_run_error_detail, "api_key_prompt_timeout")
        adapter.set_run_error_detail(None)
        self.assertIsNone(adapter.last_run_error_detail)

    def test_set_run_error_detail_redacts_secret(self):
        adapter = _make_adapter()
        secret = "AIza" + ("D" * 24)
        adapter.set_run_error_detail(f" detail key={secret} ")
        self.assertNotIn(secret, adapter.last_run_error_detail or "")
        self.assertIn("[API_KEY_REDACTED]", adapter.last_run_error_detail or "")

    def test_set_effective_api_key_strips_and_stores(self):
        adapter = _make_adapter()
        adapter.set_effective_api_key("  my-key  ")
        self.assertEqual(adapter.effective_api_key, "my-key")
        adapter.set_effective_api_key("")
        self.assertIsNone(adapter.effective_api_key)

    def test_set_work_totals_does_not_raise(self):
        _make_adapter().set_work_totals(chunks_total=10, macro_total=5)

    def test_update_work_done_does_not_raise(self):
        _make_adapter().update_work_done("chunks", 3, total=10)

    def test_register_step_time_does_not_raise(self):
        adapter = _make_adapter()
        adapter.register_step_time("chunks", 1.5, done=1, total=5)

    def test_answer_new_key_fires_callback_and_clears_it(self):
        adapter = _make_adapter()
        received = []
        adapter._new_key_callback = lambda r: received.append(r)
        adapter.answer_new_key("fresh-key")
        self.assertEqual(received, [{"key": "fresh-key"}])
        self.assertIsNone(adapter._new_key_callback)

    def test_answer_new_key_noop_when_no_callback(self):
        adapter = _make_adapter()
        adapter._new_key_callback = None
        adapter.answer_new_key("key")

    def test_answer_regenerate_none_noop_when_callback_expired(self):
        cancel = threading.Event()
        adapter = PipelineAdapter(None, cancel)
        adapter._regenerate_callback = None
        adapter.answer_regenerate(None)
        self.assertFalse(cancel.is_set())

    def test_dismiss_regenerate_prompt_clears_without_callback(self):
        adapter = _make_adapter()
        received = []
        adapter._regenerate_callback = lambda r: received.append(r)
        adapter.dismiss_regenerate_prompt()
        self.assertEqual(received, [])
        self.assertIsNone(adapter._regenerate_callback)

    def test_cancel_pending_prompts_fires_both_callbacks(self):
        adapter = _make_adapter()
        regen_received = []
        key_received = []
        adapter._regenerate_callback = lambda r: regen_received.append(r)
        adapter._new_key_callback = lambda r: key_received.append(r)
        adapter.cancel_pending_prompts()
        self.assertEqual(regen_received, [{"regenerate": False}])
        self.assertEqual(key_received, [{"key": ""}])
        self.assertIsNone(adapter._regenerate_callback)
        self.assertIsNone(adapter._new_key_callback)

    def test_dismiss_new_api_key_prompt_clears_without_callback(self):
        adapter = _make_adapter()
        received = []
        adapter._new_key_callback = lambda r: received.append(r)
        adapter.dismiss_new_api_key_prompt()
        self.assertEqual(received, [])
        self.assertIsNone(adapter._new_key_callback)

    def test_winfo_exists_exception_handling(self):
        from unittest.mock import PropertyMock, patch

        adapter = _make_adapter()
        with patch.object(
            PipelineAdapter,
            "window",
            create=True,
            new_callable=PropertyMock,
            side_effect=RuntimeError("err"),
        ):
            self.assertFalse(adapter.winfo_exists())


if __name__ == "__main__":
    unittest.main()
