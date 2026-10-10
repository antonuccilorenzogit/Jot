import os
import tempfile
import threading
import unittest

from jot.pipeline.pipeline_hooks import PipelineRuntime


class _DummyTarget:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.file_temporanei = []
        self.events = []
        self.last_run_status: str | None = "idle"
        self.last_run_error: str | None = None
        self.last_run_error_detail: str | None = None
        self.effective_api_key: str | None = None

    def winfo_exists(self):
        return True

    def aggiorna_progresso(self, value):
        self.events.append(("progress", value))

    def aggiorna_fase(self, text):
        self.events.append(("phase", text))

    def imposta_output_html(self, path, output_dir=None):
        self.events.append(("output", path, output_dir))

    def processo_terminato(self):
        self.events.append(("done", None))

    def set_work_totals(self, **kwargs):
        self.events.append(("totals", kwargs))

    def update_work_done(self, kind, done, total=None):
        self.events.append(("work_done", kind, done, total))

    def register_step_time(self, kind, seconds, done=None, total=None):
        self.events.append(("step_time", kind, seconds, done, total))


class PipelineRuntimeTests(unittest.TestCase):
    def test_runtime_forwards_callbacks_and_state(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)

        runtime.progress(0.4)
        runtime.phase("fase test")
        runtime.output_html("out.html")
        runtime.output_html("out2.html", output_dir="/some/dir")
        runtime.set_work_totals(chunks_total=3)
        runtime.update_work_done("chunks", 1, total=3)
        runtime.register_step_time("chunks", 2.5, done=1, total=3)
        runtime.set_run_result("completed", None)
        runtime.set_effective_api_key("  key-123  ")
        runtime.process_done()

        self.assertIn(("progress", 0.4), target.events)
        self.assertIn(("phase", "fase test"), target.events)
        self.assertIn(("output", "out.html", None), target.events)
        self.assertIn(("output", "out2.html", "/some/dir"), target.events)
        self.assertEqual(target.last_run_status, "completed")
        self.assertEqual(target.effective_api_key, "key-123")

    def test_runtime_cleans_temp_files(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)

        fd, path = tempfile.mkstemp()
        os.close(fd)
        runtime.track_temp_file(path)
        self.assertTrue(os.path.exists(path))

        runtime.cleanup_temp_files()

        self.assertFalse(os.path.exists(path))
        self.assertEqual(target.file_temporanei, [])

    def test_runtime_removes_empty_phase1_temp_run_dir_after_cleaning_files(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = os.path.join(tmpdir, "session", "temp_chunks", "run_test")
            os.makedirs(run_dir)
            chunk_path = os.path.join(run_dir, "chunk_001_0_60.mp3")
            with open(chunk_path, "wb") as handle:
                handle.write(b"x")
            runtime.track_temp_file(chunk_path)

            runtime.cleanup_temp_files()

            self.assertFalse(os.path.exists(chunk_path))
            self.assertFalse(os.path.exists(run_dir))
            self.assertEqual(target.file_temporanei, [])


class PipelineRuntimeCancelledTests(unittest.TestCase):
    def test_cancelled_false_when_event_not_set(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        self.assertFalse(runtime.cancelled())

    def test_cancelled_true_when_event_set(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        target.cancel_event.set()
        self.assertTrue(runtime.cancelled())

    def test_cancelled_false_when_no_cancel_event(self):
        class _NoEventTarget:
            def __init__(self):
                self.file_temporanei = []

            last_run_status = "idle"
            last_run_error = None
            effective_api_key = None

        runtime = PipelineRuntime(_NoEventTarget())
        self.assertFalse(runtime.cancelled())


class PipelineRuntimeUiAliveTests(unittest.TestCase):
    def test_ui_alive_true_when_winfo_exists_returns_true(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        self.assertTrue(runtime.ui_alive())

    def test_ui_alive_false_when_winfo_exists_raises(self):
        class _BrokenTarget:
            def __init__(self):
                self.file_temporanei = []

            last_run_status = "idle"
            last_run_error = None
            effective_api_key = None

            def winfo_exists(self):
                raise RuntimeError("destroyed")

        runtime = PipelineRuntime(_BrokenTarget())
        self.assertFalse(runtime.ui_alive())

    def test_ui_alive_true_when_no_winfo_exists(self):
        class _SimpleTarget:
            def __init__(self):
                self.file_temporanei = []

            last_run_status = "idle"
            last_run_error = None
            effective_api_key = None

        runtime = PipelineRuntime(_SimpleTarget())
        self.assertTrue(runtime.ui_alive())


class PipelineRuntimeScheduleTests(unittest.TestCase):
    def test_schedule_calls_after_when_available(self):
        class _AfterTarget(_DummyTarget):
            def after(self, delay_ms, callback, *args):
                self.events.append(("after", delay_ms))

        target = _AfterTarget()
        runtime = PipelineRuntime(target)
        result = runtime.schedule(100, lambda: None)
        self.assertTrue(result)
        self.assertIn(("after", 100), target.events)

    def test_schedule_returns_false_when_no_after_method(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        result = runtime.schedule(100, lambda: None)
        self.assertFalse(result)

    def test_schedule_returns_false_when_ui_dead(self):
        class _DeadTarget(_DummyTarget):
            def winfo_exists(self):
                return False

        target = _DeadTarget()
        runtime = PipelineRuntime(target)
        result = runtime.schedule(100, lambda: None)
        self.assertFalse(result)


class PipelineRuntimeAskRegenerateTests(unittest.TestCase):
    def test_ask_regenerate_returns_false_when_no_method(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_regenerate("file.mp3", lambda: None)
        self.assertFalse(result)

    def test_ask_regenerate_calls_method_and_returns_true(self):
        class _RegTarget(_DummyTarget):
            def ask_regenerate(self, filename, callback, mode="resume", session_dir=""):
                self.events.append(("ask_regenerate", filename, mode, session_dir))

        target = _RegTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_regenerate(
            "audio.mp3", lambda: None, mode="restart", session_dir="/sessions/abc"
        )
        self.assertTrue(result)
        self.assertIn(
            ("ask_regenerate", "audio.mp3", "restart", "/sessions/abc"), target.events
        )

    def test_ask_regenerate_returns_false_on_exception(self):
        class _BrokenTarget(_DummyTarget):
            def ask_regenerate(self, *args, **kwargs):
                raise RuntimeError("boom")

        target = _BrokenTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_regenerate("file.mp3", lambda: None)
        self.assertFalse(result)


class PipelineRuntimeAskNewApiKeyTests(unittest.TestCase):
    def test_returns_false_when_no_method(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_new_api_key(lambda: None)
        self.assertFalse(result)

    def test_calls_method_and_returns_true(self):
        class _KeyTarget(_DummyTarget):
            def ask_new_api_key(self, callback):
                self.events.append(("ask_new_api_key",))

        target = _KeyTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_new_api_key(lambda: None)
        self.assertTrue(result)
        self.assertIn(("ask_new_api_key",), target.events)

    def test_returns_false_on_exception(self):
        class _BrokenTarget(_DummyTarget):
            def ask_new_api_key(self, *args):
                raise RuntimeError("broken")

        target = _BrokenTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_new_api_key(lambda: None)
        self.assertFalse(result)


class PipelineRuntimeAskConfirmationTests(unittest.TestCase):
    def test_returns_none_when_no_window(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_confirmation("Title", "Message")
        self.assertIsNone(result)

    def test_calls_window_and_returns_bool(self):
        class _WindowTarget(_DummyTarget):
            class window:
                @staticmethod
                def create_confirmation_dialog(title, message):
                    return True

        target = _WindowTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_confirmation("Title", "Message?")
        self.assertTrue(result)

    def test_returns_none_on_exception(self):
        class _BrokenWindowTarget(_DummyTarget):
            class window:
                @staticmethod
                def create_confirmation_dialog(*args):
                    raise RuntimeError("boom")

        target = _BrokenWindowTarget()
        runtime = PipelineRuntime(target)
        result = runtime.ask_confirmation("Title", "Message")
        self.assertIsNone(result)


class PipelineRuntimeMiscTests(unittest.TestCase):
    def test_reset_temp_files_clears_list(self):
        target = _DummyTarget()
        target.file_temporanei = ["a.mp3", "b.wav"]
        runtime = PipelineRuntime(target)
        runtime.reset_temp_files()
        self.assertEqual(target.file_temporanei, [])

    def test_update_model_forwarded(self):
        class _ModelTarget(_DummyTarget):
            def update_model(self, model):
                self.events.append(("update_model", model))

        target = _ModelTarget()
        runtime = PipelineRuntime(target)
        runtime.update_model("gemini-2.5-flash")
        self.assertIn(("update_model", "gemini-2.5-flash"), target.events)

    def test_set_run_result_fallback_when_no_method(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        runtime.set_run_result("failed", "some error")
        self.assertEqual(target.last_run_status, "failed")
        self.assertEqual(target.last_run_error, "some error")

    def test_set_run_error_detail_fallback_when_no_method(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        runtime.set_run_error_detail("detail")
        self.assertEqual(target.last_run_error_detail, "detail")

    def test_dismiss_new_api_key_prompt_forwarded(self):
        class _DismissTarget(_DummyTarget):
            def dismiss_new_api_key_prompt(self):
                self.events.append(("dismiss_new_api_key_prompt",))

        target = _DismissTarget()
        runtime = PipelineRuntime(target)
        runtime.dismiss_new_api_key_prompt()
        self.assertIn(("dismiss_new_api_key_prompt",), target.events)

    def test_set_effective_api_key_none_strips_to_none(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        runtime.set_effective_api_key(None)
        self.assertIsNone(target.effective_api_key)

    def test_set_effective_api_key_exception_suppressed(self):
        class _BrokenTarget(_DummyTarget):
            def set_effective_api_key(self, key):
                raise RuntimeError("broken")

        target = _BrokenTarget()
        runtime = PipelineRuntime(target)
        runtime.set_effective_api_key("key")

    def test_safe_call_suppresses_exception(self):
        class _BrokenMethod(_DummyTarget):
            def aggiorna_progresso(self, value):
                raise RuntimeError("crash")

        target = _BrokenMethod()
        runtime = PipelineRuntime(target)
        runtime.progress(0.5)

    def test_init_sets_defaults_on_target_without_attributes(self):
        class _BareTarget:
            pass

        target = _BareTarget()
        PipelineRuntime(target)
        self.assertEqual(target.file_temporanei, [])  # type: ignore[attr-defined]
        self.assertEqual(target.last_run_status, "idle")  # type: ignore[attr-defined]
        self.assertIsNone(target.last_run_error)  # type: ignore[attr-defined]
        self.assertIsNone(target.last_run_error_detail)  # type: ignore[attr-defined]
        self.assertIsNone(target.effective_api_key)  # type: ignore[attr-defined]

    def test_revision_failed_blocks_get_and_set(self):
        target = _DummyTarget()
        runtime = PipelineRuntime(target)
        self.assertEqual(runtime.get_revision_failed_blocks(), [])
        runtime.set_revision_failed_blocks([1, 2, "3"])
        self.assertEqual(runtime.get_revision_failed_blocks(), [1, 2, 3])

    def test_revision_failed_blocks_target_with_methods(self):
        class _MethodTarget(_DummyTarget):
            def __init__(self):
                super().__init__()
                self.blocks = []

            def set_revision_failed_blocks(self, blocks):
                self.blocks = blocks

            def get_revision_failed_blocks(self):
                return self.blocks

        target = _MethodTarget()
        runtime = PipelineRuntime(target)
        runtime.set_revision_failed_blocks([4, 5])
        self.assertEqual(runtime.get_revision_failed_blocks(), [4, 5])

    def test_get_last_run_status_and_error(self):
        target = _DummyTarget()
        target.last_run_status = "failed"
        target.last_run_error = "custom_error"
        target.effective_api_key = "key-xyz"
        runtime = PipelineRuntime(target)
        self.assertEqual(runtime.get_last_run_status(), "failed")
        self.assertEqual(runtime.get_last_run_error(), "custom_error")
        self.assertEqual(runtime.get_effective_api_key(), "key-xyz")

    def test_get_last_run_status_and_error_with_methods(self):
        class _MethodTarget:
            def get_last_run_status(self):
                return "completed"

            def get_last_run_error(self):
                return None

            def get_effective_api_key(self):
                return "method-key"

        runtime = PipelineRuntime(_MethodTarget())
        self.assertEqual(runtime.get_last_run_status(), "completed")
        self.assertIsNone(runtime.get_last_run_error())
        self.assertEqual(runtime.get_effective_api_key(), "method-key")


if __name__ == "__main__":
    unittest.main()
