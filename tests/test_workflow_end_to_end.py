import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from jot.app_webview import JotApi


class _FakeWindow:
    def __init__(self):
        self.calls: list[str] = []

    def evaluate_js(self, script):
        self.calls.append(script)


class _FakeModels:
    def get(self, model=None, **kwargs):
        return {"model": model}


class _FakeClient:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.models = _FakeModels()


class WorkflowEndToEndTests(unittest.TestCase):
    def setUp(self):
        self._probe_media_duration_patch = patch(
            "jot.services.audio_service.probe_media_duration",
            return_value=(60.0, None),
        )
        self._probe_media_duration_patch.start()

    def tearDown(self):
        self._probe_media_duration_patch.stop()

    def test_start_processing_emits_file_done_and_process_done(self):
        api = JotApi()
        window = _FakeWindow()
        api.set_window(window)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            output_path = os.path.join(tmpdir, "output.html")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            def fake_pipeline(file_path, api_key, adapter, **kwargs):
                with open(output_path, "w", encoding="utf-8") as handle:
                    handle.write("<html><body>ok</body></html>")
                adapter.imposta_output_html(output_path)
                adapter.set_run_result("completed")

            files = [
                {
                    "id": "file-1",
                    "path": input_path,
                    "name": "input.mp3",
                    "size": 4,
                    "duration": 1.0,
                }
            ]
            with (
                patch("google.genai.Client", _FakeClient),
                patch(
                    "jot.pipeline.pipeline.esegui_sbobinatura",
                    side_effect=fake_pipeline,
                ),
            ):
                result = api.start_processing(files, "fake-key", resume_session=True)  # type: ignore[arg-type]
                self.assertTrue(result["ok"])
                self.assertIsNotNone(api._processing_thread)
                assert api._processing_thread is not None
                api._processing_thread.join(timeout=5)
                api._adapter._dispatcher.flush()

            joined = "\n".join(window.calls)
            self.assertIn("fileDone", joined)
            self.assertIn("processDone", joined)

    def test_start_processing_marks_current_file_failed_on_fatal_exception(self):
        api = JotApi()
        window = _FakeWindow()
        api.set_window(window)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            files = [
                {
                    "id": "file-1",
                    "path": input_path,
                    "name": "input.mp3",
                    "size": 4,
                    "duration": 1.0,
                }
            ]
            with (
                patch("google.genai.Client", _FakeClient),
                patch(
                    "jot.pipeline.pipeline.esegui_sbobinatura",
                    side_effect=RuntimeError("boom"),
                ),
            ):
                result = api.start_processing(files, "fake-key", resume_session=True)  # type: ignore[arg-type]
                self.assertTrue(result["ok"])
                self.assertIsNotNone(api._processing_thread)
                assert api._processing_thread is not None
                api._processing_thread.join(timeout=5)
                api._adapter._dispatcher.flush()

            joined = "\n".join(window.calls)
            self.assertIn("fileFailed", joined)
            self.assertIn('"error": "boom"', joined)
            self.assertIn('"failed": 1', joined)

    def test_multi_file_batch_all_done(self):
        api = JotApi()
        window = _FakeWindow()
        api.set_window(window)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            output_paths = []
            for i in range(3):
                input_path = os.path.join(tmpdir, f"input_{i}.mp3")
                output_path = os.path.join(tmpdir, f"output_{i}.html")
                with open(input_path, "wb") as handle:
                    handle.write(b"fake")
                files.append(
                    {
                        "id": f"file-{i}",
                        "path": input_path,
                        "name": f"input_{i}.mp3",
                        "size": 4,
                        "duration": 1.0,
                    }
                )
                output_paths.append(output_path)

            call_index = {"n": 0}

            def fake_pipeline(file_path, api_key, adapter, **kwargs):
                idx = call_index["n"]
                with open(output_paths[idx], "w", encoding="utf-8") as handle:
                    handle.write(f"<html><body>ok {idx}</body></html>")
                adapter.imposta_output_html(output_paths[idx])
                adapter.set_run_result("completed")
                call_index["n"] += 1

            with (
                patch("google.genai.Client", _FakeClient),
                patch(
                    "jot.pipeline.pipeline.esegui_sbobinatura",
                    side_effect=fake_pipeline,
                ),
            ):
                result = api.start_processing(files, "fake-key", resume_session=False)  # type: ignore[arg-type]
                self.assertTrue(result["ok"])
                assert api._processing_thread is not None
                api._processing_thread.join(timeout=10)
                api._adapter._dispatcher.flush()

        joined = "\n".join(window.calls)
        self.assertEqual(joined.count("fileDone("), 3)
        self.assertIn("processDone", joined)
        self.assertIn('"completed": 3', joined)

    def test_cancel_mid_batch_stops_queue(self):
        api = JotApi()
        window = _FakeWindow()
        api.set_window(window)  # type: ignore[arg-type]

        file_started = threading.Event()

        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            for i in range(3):
                input_path = os.path.join(tmpdir, f"input_{i}.mp3")
                with open(input_path, "wb") as handle:
                    handle.write(b"fake")
                files.append(
                    {
                        "id": f"file-{i}",
                        "path": input_path,
                        "name": f"input_{i}.mp3",
                        "size": 4,
                        "duration": 1.0,
                    }
                )

            call_count = {"n": 0}

            def fake_pipeline(file_path, api_key, adapter, **kwargs):
                call_count["n"] += 1
                file_started.set()
                adapter.set_run_result("cancelled")
                adapter.cancel_event.set()

            with (
                patch("google.genai.Client", _FakeClient),
                patch(
                    "jot.pipeline.pipeline.esegui_sbobinatura",
                    side_effect=fake_pipeline,
                ),
            ):
                result = api.start_processing(files, "fake-key", resume_session=False)  # type: ignore[arg-type]
                self.assertTrue(result["ok"])
                file_started.wait(timeout=5)
                assert api._processing_thread is not None
                api._processing_thread.join(timeout=5)
                api._adapter._dispatcher.flush()

        self.assertEqual(
            call_count["n"], 1, "Only the first file should have been processed"
        )

    def test_stop_processing_sets_cancel_event(self):
        api = JotApi()
        window = _FakeWindow()
        api.set_window(window)  # type: ignore[arg-type]

        result = api.stop_processing()
        self.assertTrue(result["ok"])
        self.assertTrue(api._cancel_event.is_set())

    def test_start_processing_while_running_returns_error(self):
        api = JotApi()
        window = _FakeWindow()
        api.set_window(window)  # type: ignore[arg-type]

        started = threading.Event()
        can_finish = threading.Event()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            files = [
                {
                    "id": "file-1",
                    "path": input_path,
                    "name": "input.mp3",
                    "size": 4,
                    "duration": 1.0,
                }
            ]

            def fake_pipeline(file_path, api_key, adapter, **kwargs):
                started.set()
                can_finish.wait(timeout=5)
                adapter.set_run_result("completed")

            with (
                patch("google.genai.Client", _FakeClient),
                patch(
                    "jot.pipeline.pipeline.esegui_sbobinatura",
                    side_effect=fake_pipeline,
                ),
            ):
                first = api.start_processing(files, "fake-key", resume_session=False)  # type: ignore[arg-type]
                started.wait(timeout=5)
                second = api.start_processing(files, "fake-key", resume_session=False)  # type: ignore[arg-type]
                can_finish.set()
                assert api._processing_thread is not None
                api._processing_thread.join(timeout=5)

        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertIn("in corso", second["error"])

    def test_user_declines_key_stops_batch(self):
        """Regression: when user clicks 'No' on the new-key modal, the batch must
        stop immediately — not continue to the next file in the queue."""
        api = JotApi()
        window = _FakeWindow()
        api.set_window(window)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            for i in range(2):
                input_path = os.path.join(tmpdir, f"input_{i}.mp3")
                with open(input_path, "wb") as handle:
                    handle.write(b"fake")
                files.append(
                    {
                        "id": f"file-{i}",
                        "path": input_path,
                        "name": f"input_{i}.mp3",
                        "size": 4,
                        "duration": 1.0,
                    }
                )

            call_count = {"n": 0}

            def fake_pipeline(file_path, api_key, adapter, **kwargs):
                call_count["n"] += 1
                adapter.set_run_result("failed", "quota_daily_limit_phase1")
                # Real flow: request_fallback_key() sets cancel_event → pipeline
                # finally block detects runtime.cancelled() and overwrites
                # last_run_status to "cancelled".  Mirror that here so the fake
                # accurately represents the post-fix causal chain.
                adapter.cancel_event.set()
                adapter.set_run_result("cancelled", "cancelled")

            with (
                patch("google.genai.Client", _FakeClient),
                patch(
                    "jot.pipeline.pipeline.esegui_sbobinatura",
                    side_effect=fake_pipeline,
                ),
            ):
                result = api.start_processing(files, "fake-key", resume_session=False)  # type: ignore[arg-type]
                self.assertTrue(result["ok"])
                assert api._processing_thread is not None
                api._processing_thread.join(timeout=5)
                api._adapter._dispatcher.flush()

        self.assertEqual(
            call_count["n"],
            1,
            "Batch must stop after first file when user declines key",
        )
        joined = "\n".join(window.calls)
        self.assertIn('"cancelled": true', joined)

    def test_api_key_prompt_timeout_stops_batch_as_failed_quota(self):
        api = JotApi()
        window = _FakeWindow()
        api.set_window(window)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            for i in range(2):
                input_path = os.path.join(tmpdir, f"input_{i}.mp3")
                with open(input_path, "wb") as handle:
                    handle.write(b"fake")
                files.append(
                    {
                        "id": f"file-{i}",
                        "path": input_path,
                        "name": f"input_{i}.mp3",
                        "size": 4,
                        "duration": 1.0,
                    }
                )

            call_count = {"n": 0}

            def fake_pipeline(file_path, api_key, adapter, **kwargs):
                call_count["n"] += 1
                adapter.set_run_error_detail("api_key_prompt_timeout")
                adapter.set_run_result("failed", "quota_daily_limit_phase1")

            with (
                patch("google.genai.Client", _FakeClient),
                patch(
                    "jot.pipeline.pipeline.esegui_sbobinatura",
                    side_effect=fake_pipeline,
                ),
            ):
                result = api.start_processing(files, "fake-key", resume_session=False)  # type: ignore[arg-type]
                self.assertTrue(result["ok"])
                assert api._processing_thread is not None
                api._processing_thread.join(timeout=5)
                api._adapter._dispatcher.flush()

        self.assertEqual(call_count["n"], 1)
        joined = "\n".join(window.calls)
        self.assertIn("fileFailed", joined)
        self.assertIn('"error": "quota_daily_limit_phase1"', joined)
        self.assertIn('"error_detail": "api_key_prompt_timeout"', joined)
        self.assertIn('"cancelled": false', joined)
        self.assertIn('"quota_exhausted": true', joined)


if __name__ == "__main__":
    unittest.main()
