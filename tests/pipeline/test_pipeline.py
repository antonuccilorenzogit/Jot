import contextlib
import os
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import patch

from jot.pipeline.pipeline import (
    _pipeline_finally_cleanup,
    esegui_sbobinatura,
)
from jot.pipeline.pipeline_adapter import PipelineAdapter
from jot.pipeline.pipeline_hooks import PipelineRuntime


class _FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None


class _FakeModels:
    def get(self, model=None, **kwargs):
        return {"model": model}


class _FakeClient:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.models = _FakeModels()


class _FakeSessionContext:
    def __init__(self, root: str):
        self.session_dir = root
        self.session_path = os.path.join(root, "session.json")
        self.phase1_chunks_dir = os.path.join(root, "phase1")
        self.phase2_revised_dir = os.path.join(root, "phase2")
        self.macro_path = os.path.join(root, "macro.md")
        self.session = {
            "stage": "phase1",
            "phase1": {},
            "phase2": {},
            "outputs": {},
        }
        self.settings = SimpleNamespace(
            model="gemini-test",
            fallback_models=["gemini-3.6-flash"],
            effective_model="gemini-test",
            chunk_minutes=15,
            chunk_seconds=60,
            step_seconds=60,
            preconvert_audio=False,
            audio_bitrate="48k",
            prefetch_next_chunk=True,
            inline_max_bytes=None,
            macro_char_limit=22000,
        )
        os.makedirs(self.phase1_chunks_dir, exist_ok=True)
        os.makedirs(self.phase2_revised_dir, exist_ok=True)

    def save(self):
        return True


class _PromptBlockingApp:
    _callback: Callable[[dict], None] | None

    def __init__(self):
        self.cancel_event = threading.Event()
        self.file_temporanei = []
        self.last_run_status = "idle"
        self.last_run_error = None
        self.last_run_error_detail = None
        self.effective_api_key = None
        self.prompt_shown = threading.Event()
        self.regenerate_prompt_dismissed = threading.Event()
        self._callback = None

    def winfo_exists(self):
        return True

    def ask_regenerate(self, filename, callback, mode="resume", session_dir=""):
        self.prompt_shown.set()
        self._callback = callback
        return None

    def dismiss_regenerate_prompt(self):
        self._callback = None
        self.regenerate_prompt_dismissed.set()

    def aggiorna_progresso(self, value):
        return None

    def aggiorna_fase(self, text):
        return None

    def imposta_output_html(self, path, output_dir=None):
        return None

    def processo_terminato(self):
        return None


class _DoneEarlyReturnApp:
    """App with no dialog methods so ask_should_regenerate returns False immediately,
    triggering the early-return path at stage=='done'."""

    def __init__(self):
        self.cancel_event = threading.Event()
        self.file_temporanei = []
        self.last_run_status = "idle"
        self.last_run_error = None
        self.last_run_error_detail = None
        self.effective_api_key = None

    def winfo_exists(self):
        return True

    def aggiorna_progresso(self, value):
        pass

    def aggiorna_fase(self, text):
        pass

    def imposta_output_html(self, path, output_dir=None):
        pass

    def processo_terminato(self):
        pass


class PipelinePausedCleanupTests(unittest.TestCase):
    def test_cleanup_preserves_paused_terminal_state(self):
        adapter = PipelineAdapter(None, threading.Event())
        runtime = PipelineRuntime(adapter)
        adapter.set_run_result("paused", "circuit breaker exhausted")

        _pipeline_finally_cleanup(
            None,
            {"last_error_detail": "503 Service Unavailable"},
            None,
            adapter,
            runtime,
            None,
            False,
        )

        self.assertEqual(adapter.last_run_status, "paused")
        self.assertEqual(adapter.last_run_error, "circuit breaker exhausted")
        self.assertEqual(adapter.last_run_error_detail, "503 Service Unavailable")


class PipelineCancellationTests(unittest.TestCase):
    def test_regenerate_rebinds_model_state_from_reset_session_settings(self):
        app = _PromptBlockingApp()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            session_ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))
            session_ctx.session = {
                "stage": "phase1",
                "phase1": {},
                "phase2": {},
                "outputs": {},
            }
            session_ctx.settings = SimpleNamespace(
                model="gemini-2.5-flash",
                fallback_models=["gemini-3.6-flash"],
                effective_model="gemini-2.5-flash",
                chunk_minutes=15,
                chunk_seconds=60,
                step_seconds=60,
                preconvert_audio=False,
                audio_bitrate="48k",
                prefetch_next_chunk=True,
                inline_max_bytes=None,
                macro_char_limit=22000,
            )

            seen = {}

            def fake_phase1(**kwargs):
                seen["current_model"] = kwargs["model_state"].current
                seen["chain"] = kwargs["model_state"].chain
                return kwargs["client"], None, ""

            def fake_reset(context):
                context.session = {
                    "stage": "phase1",
                    "phase1": {},
                    "phase2": {},
                    "outputs": {},
                }
                context.settings = SimpleNamespace(
                    model="gemini-2.5-flash",
                    fallback_models=["gemini-3.6-flash"],
                    effective_model="gemini-3.6-flash",
                    chunk_minutes=10,
                    chunk_seconds=60,
                    step_seconds=60,
                    preconvert_audio=False,
                    audio_bitrate="48k",
                    prefetch_next_chunk=True,
                    inline_max_bytes=None,
                    macro_char_limit=22000,
                )

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(120.0, None),
                ),
                patch("jot.pipeline.pipeline.persist_phase1_metadata"),
                patch(
                    "jot.pipeline.pipeline.normalize_stage",
                    return_value="phase1",
                ),
                patch(
                    "jot.pipeline.pipeline.list_phase1_chunks",
                    return_value=[(0, 0, 60, "chunk_000_0_60.md")],
                ),
                patch(
                    "jot.pipeline.pipeline.phase1_has_progress",
                    return_value=True,
                ),
                patch(
                    "jot.pipeline.pipeline.ensure_preconverted_audio",
                    return_value=(False, None),
                ),
                patch(
                    "jot.pipeline.pipeline.reset_for_regeneration",
                    side_effect=fake_reset,
                ),
                patch(
                    "jot.pipeline.pipeline.process_phase1_transcription",
                    side_effect=fake_phase1,
                ),
            ):
                thread = threading.Thread(
                    target=esegui_sbobinatura,
                    args=(input_path, "fake-key", app),
                    kwargs={"resume_session": True},
                    daemon=True,
                )
                thread.start()
                self.assertTrue(app.prompt_shown.wait(timeout=1))
                assert app._callback is not None
                app._callback({"regenerate": True})
                thread.join(timeout=2)

        self.assertEqual(seen.get("current_model"), "gemini-2.5-flash")
        self.assertIn("gemini-3.6-flash", seen.get("chain", ()))

    def test_api_key_prompt_timeout_saves_quota_detail(self):
        from jot.services.generation_service import QuotaDailyLimitError

        app = _DoneEarlyReturnApp()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            session_ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))

            def fake_request_new_api_key(runtime, cancelled, *, on_timeout=None, **_):
                if on_timeout is not None:
                    on_timeout()
                return None

            def fake_phase1(**kwargs):
                with self.assertRaises(QuotaDailyLimitError):
                    kwargs["request_fallback_key"]()
                return kwargs["client"], None, ""

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(120.0, None),
                ),
                patch("jot.pipeline.pipeline.persist_phase1_metadata"),
                patch(
                    "jot.pipeline.pipeline.normalize_stage",
                    return_value="phase1",
                ),
                patch(
                    "jot.pipeline.pipeline.list_phase1_chunks",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.phase1_has_progress",
                    return_value=False,
                ),
                patch(
                    "jot.pipeline.pipeline.ensure_preconverted_audio",
                    return_value=(False, None),
                ),
                patch(
                    "jot.pipeline.pipeline.generation_service.request_new_api_key",
                    side_effect=fake_request_new_api_key,
                ),
                patch(
                    "jot.pipeline.pipeline.process_phase1_transcription",
                    side_effect=fake_phase1,
                ),
            ):
                esegui_sbobinatura(input_path, "fake-key", app)

        self.assertEqual(
            session_ctx.session.get("last_error"), "quota_daily_limit_phase1"
        )
        self.assertEqual(
            session_ctx.session.get("last_error_detail"), "api_key_prompt_timeout"
        )
        self.assertEqual(app.last_run_status, "failed")
        self.assertEqual(app.last_run_error, "quota_daily_limit_phase1")
        self.assertEqual(app.last_run_error_detail, "api_key_prompt_timeout")

    def test_resume_always_starts_from_primary_ignoring_stale_effective_model(self):
        """On resume, model_state.current must be the primary model, even when the session
        recorded a different effective_model from a previous fallback switch.
        effective_model is kept for observability but must not drive the resume start."""
        app = _PromptBlockingApp()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            session_ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))
            session_ctx.settings = SimpleNamespace(
                model="gemini-2.5-flash",
                fallback_models=["gemini-3.6-flash"],
                effective_model="gemini-3.6-flash",
                chunk_minutes=15,
                chunk_seconds=60,
                step_seconds=60,
                preconvert_audio=False,
                audio_bitrate="48k",
                prefetch_next_chunk=True,
                inline_max_bytes=None,
                macro_char_limit=22000,
            )

            seen = {}

            def fake_phase1(**kwargs):
                seen["current_model"] = kwargs["model_state"].current
                seen["chain"] = kwargs["model_state"].chain
                return kwargs["client"], None, ""

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(120.0, None),
                ),
                patch("jot.pipeline.pipeline.persist_phase1_metadata"),
                patch(
                    "jot.pipeline.pipeline.normalize_stage",
                    return_value="phase1",
                ),
                patch(
                    "jot.pipeline.pipeline.list_phase1_chunks",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.phase1_has_progress",
                    return_value=False,
                ),
                patch(
                    "jot.pipeline.pipeline.ensure_preconverted_audio",
                    return_value=(False, None),
                ),
                patch(
                    "jot.pipeline.pipeline.process_phase1_transcription",
                    side_effect=fake_phase1,
                ),
            ):
                esegui_sbobinatura(input_path, "fake-key", app, resume_session=True)

        self.assertEqual(seen.get("current_model"), "gemini-2.5-flash")
        self.assertIn("gemini-3.6-flash", seen.get("chain", ()))

    def test_cancel_during_regenerate_prompt_exits_prompt_wait_immediately(self):
        app = _PromptBlockingApp()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            session_ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(120.0, None),
                ),
                patch("jot.pipeline.pipeline.persist_phase1_metadata"),
                patch(
                    "jot.pipeline.pipeline.normalize_stage",
                    return_value="phase1",
                ),
                patch(
                    "jot.pipeline.pipeline.list_phase1_chunks",
                    return_value=[(0, 0, 60, "chunk_000_0_60.md")],
                ),
                patch(
                    "jot.pipeline.pipeline.phase1_has_progress",
                    return_value=True,
                ),
                patch(
                    "jot.pipeline.pipeline.ensure_preconverted_audio",
                    return_value=(False, None),
                ),
            ):
                thread = threading.Thread(
                    target=esegui_sbobinatura,
                    args=(input_path, "fake-key", app),
                    kwargs={"resume_session": True},
                    daemon=True,
                )
                started = time.monotonic()
                thread.start()

                self.assertTrue(app.prompt_shown.wait(timeout=1))
                app.cancel_event.set()

                thread.join(timeout=2)
                elapsed = time.monotonic() - started

            self.assertFalse(
                thread.is_alive(),
                "La pipeline e' rimasta bloccata in attesa del prompt di rigenerazione.",
            )
            self.assertLess(elapsed, 2.5)
            self.assertEqual(app.last_run_status, "cancelled")

    def test_dismiss_regenerate_prompt_cancels_before_resuming_work(self):
        app = _PromptBlockingApp()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            session_ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(120.0, None),
                ),
                patch("jot.pipeline.pipeline.persist_phase1_metadata"),
                patch(
                    "jot.pipeline.pipeline.normalize_stage",
                    return_value="phase1",
                ),
                patch(
                    "jot.pipeline.pipeline.list_phase1_chunks",
                    return_value=[(0, 0, 60, "chunk_000_0_60.md")],
                ),
                patch(
                    "jot.pipeline.pipeline.phase1_has_progress",
                    return_value=True,
                ),
                patch(
                    "jot.pipeline.pipeline.ensure_preconverted_audio"
                ) as mock_preconvert,
            ):
                thread = threading.Thread(
                    target=esegui_sbobinatura,
                    args=(input_path, "fake-key", app),
                    kwargs={"resume_session": True},
                    daemon=True,
                )
                thread.start()

                self.assertTrue(app.prompt_shown.wait(timeout=1))
                assert app._callback is not None
                app._callback({"regenerate": None})

                thread.join(timeout=2)

            self.assertFalse(
                thread.is_alive(),
                "La pipeline e' rimasta bloccata dopo la chiusura del prompt.",
            )
            self.assertEqual(app.last_run_status, "cancelled")
            mock_preconvert.assert_not_called()

    def test_regenerate_prompt_timeout_fails_visibly_before_resuming_work(self):
        app = _PromptBlockingApp()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            session_ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(120.0, None),
                ),
                patch("jot.pipeline.pipeline.persist_phase1_metadata"),
                patch(
                    "jot.pipeline.pipeline.normalize_stage",
                    return_value="phase1",
                ),
                patch(
                    "jot.pipeline.pipeline.list_phase1_chunks",
                    return_value=[(0, 0, 60, "chunk_000_0_60.md")],
                ),
                patch(
                    "jot.pipeline.pipeline.phase1_has_progress",
                    return_value=True,
                ),
                patch(
                    "jot.pipeline.pipeline._REGENERATE_DIALOG_TIMEOUT_SECONDS",
                    0.05,
                ),
                patch(
                    "jot.pipeline.pipeline.ensure_preconverted_audio"
                ) as mock_preconvert,
            ):
                thread = threading.Thread(
                    target=esegui_sbobinatura,
                    args=(input_path, "fake-key", app),
                    kwargs={"resume_session": True},
                    daemon=True,
                )
                thread.start()

                self.assertTrue(app.prompt_shown.wait(timeout=1))
                thread.join(timeout=2)

            self.assertFalse(thread.is_alive())
            self.assertEqual(app.last_run_status, "failed")
            self.assertEqual(app.last_run_error, "regenerate_prompt_timeout")
            self.assertEqual(
                session_ctx.session["last_error"], "regenerate_prompt_timeout"
            )
            self.assertTrue(app.regenerate_prompt_dismissed.is_set())
            self.assertIsNone(app._callback)
            mock_preconvert.assert_not_called()

    def test_regenerate_prompt_timeout_expires_adapter_callback_before_late_dismiss(
        self,
    ):
        cancel_event = threading.Event()
        app = PipelineAdapter(None, cancel_event)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            session_ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(120.0, None),
                ),
                patch("jot.pipeline.pipeline.persist_phase1_metadata"),
                patch(
                    "jot.pipeline.pipeline.normalize_stage",
                    return_value="phase1",
                ),
                patch(
                    "jot.pipeline.pipeline.list_phase1_chunks",
                    return_value=[(0, 0, 60, "chunk_000_0_60.md")],
                ),
                patch(
                    "jot.pipeline.pipeline.phase1_has_progress",
                    return_value=True,
                ),
                patch(
                    "jot.pipeline.pipeline._REGENERATE_DIALOG_TIMEOUT_SECONDS",
                    0.05,
                ),
                patch(
                    "jot.pipeline.pipeline.ensure_preconverted_audio"
                ) as mock_preconvert,
            ):
                thread = threading.Thread(
                    target=esegui_sbobinatura,
                    args=(input_path, "fake-key", app),
                    kwargs={"resume_session": True},
                    daemon=True,
                )
                thread.start()

                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    with app._lock:
                        if app._regenerate_callback is not None:
                            break
                    time.sleep(0.01)

                thread.join(timeout=2)

            self.assertFalse(thread.is_alive())
            self.assertEqual(app.last_run_status, "failed")
            self.assertEqual(app.last_run_error, "regenerate_prompt_timeout")
            with app._lock:
                self.assertIsNone(app._regenerate_callback)

            app.answer_regenerate(None)

            self.assertFalse(cancel_event.is_set())
            self.assertEqual(app.last_run_status, "failed")
            self.assertEqual(app.last_run_error, "regenerate_prompt_timeout")
            mock_preconvert.assert_not_called()

    def test_regenerate_prompt_timeout_not_overwritten_by_close_race(self):
        class _TimeoutCloseRaceApp(_PromptBlockingApp):
            def dismiss_regenerate_prompt(self):
                cb = self._callback
                if cb:
                    cb({"regenerate": None})
                self._callback = None
                self.regenerate_prompt_dismissed.set()

        app = _TimeoutCloseRaceApp()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            session_ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(120.0, None),
                ),
                patch("jot.pipeline.pipeline.persist_phase1_metadata"),
                patch(
                    "jot.pipeline.pipeline.normalize_stage",
                    return_value="phase1",
                ),
                patch(
                    "jot.pipeline.pipeline.list_phase1_chunks",
                    return_value=[(0, 0, 60, "chunk_000_0_60.md")],
                ),
                patch(
                    "jot.pipeline.pipeline.phase1_has_progress",
                    return_value=True,
                ),
                patch(
                    "jot.pipeline.pipeline._REGENERATE_DIALOG_TIMEOUT_SECONDS",
                    0.05,
                ),
                patch(
                    "jot.pipeline.pipeline.ensure_preconverted_audio"
                ) as mock_preconvert,
            ):
                thread = threading.Thread(
                    target=esegui_sbobinatura,
                    args=(input_path, "fake-key", app),
                    kwargs={"resume_session": True},
                    daemon=True,
                )
                thread.start()

                self.assertTrue(app.prompt_shown.wait(timeout=1))
                thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertTrue(app.cancel_event.is_set())
        self.assertEqual(app.last_run_status, "failed")
        self.assertEqual(app.last_run_error, "regenerate_prompt_timeout")
        self.assertEqual(session_ctx.session["last_error"], "regenerate_prompt_timeout")
        self.assertTrue(app.regenerate_prompt_dismissed.is_set())
        self.assertIsNone(app._callback)
        mock_preconvert.assert_not_called()


class PipelineCleanupCacheTests(unittest.TestCase):
    def _make_session_ctx(self, session_dir):
        ctx = _FakeSessionContext(session_dir)
        ctx.settings = SimpleNamespace(
            model="gemini-test",
            fallback_models=[],
            effective_model="gemini-test",
            chunk_minutes=15,
            chunk_seconds=60,
            step_seconds=60,
            preconvert_audio=True,
            audio_bitrate="48k",
            prefetch_next_chunk=False,
            inline_max_bytes=None,
            macro_char_limit=22000,
        )
        return ctx

    def _make_pipeline_patches(self, session_ctx, preconv_path, html_path, tmpdir):
        """Base patches that drive the pipeline through to the final cleanup block."""

        def fake_export(**kwargs):
            with open(html_path, "w") as fh:
                fh.write("<html></html>")
            return "Test Title", html_path

        return [
            patch("google.genai.Client", _FakeClient),
            # the course step (summary + course folder) has its own tests
            patch(
                "jot.pipeline.pipeline.run_course_step",
                side_effect=lambda **kwargs: kwargs["client"],
            ),
            patch(
                "jot.pipeline.pipeline.initialize_session_context",
                return_value=session_ctx,
            ),
            patch("jot.pipeline.pipeline.attach_file_handler", return_value=None),
            patch("jot.pipeline.pipeline.detach_file_handler"),
            patch("jot.pipeline.pipeline.get_logger", return_value=_FakeLogger()),
            patch("jot.pipeline.pipeline.load_fallback_keys", return_value=[]),
            patch("jot.pipeline.pipeline.resolve_ffmpeg", return_value="ffmpeg"),
            patch(
                "jot.pipeline.pipeline.probe_media_duration",
                return_value=(120.0, None),
            ),
            patch("jot.pipeline.pipeline.persist_phase1_metadata"),
            patch("jot.pipeline.pipeline.normalize_stage", return_value="phase1"),
            patch("jot.pipeline.pipeline.list_phase1_chunks", return_value=[]),
            patch(
                "jot.pipeline.pipeline.phase1_has_progress",
                return_value=False,
            ),
            patch(
                "jot.pipeline.pipeline.ensure_preconverted_audio",
                return_value=(True, preconv_path),
            ),
            patch(
                "jot.pipeline.pipeline.restore_phase1_progress",
                return_value=SimpleNamespace(
                    existing_chunks=[], start_sec=0, full_transcript="", prev_memory=""
                ),
            ),
            patch(
                "jot.pipeline.pipeline.process_phase1_transcription",
                return_value=(_FakeClient(), "transcript", ""),
            ),
            patch(
                "jot.pipeline.pipeline.build_macro_blocks",
                return_value=["block"],
            ),
            patch("jot.pipeline.pipeline._atomic_write_json"),
            patch(
                "jot.pipeline.pipeline.process_macro_revision_phase",
                return_value=(_FakeClient(), "revised"),
            ),
            patch(
                "jot.pipeline.pipeline.export_final_html_document",
                side_effect=fake_export,
            ),
        ]

    def test_cleanup_path_invalidates_cache_and_bytes_drop_immediately(self):
        from jot.core import shared as _shared
        from jot.core.shared import PRECONVERTED_AUDIO_FINAL

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            session_ctx = self._make_session_ctx(session_dir)

            preconv_path = os.path.join(session_dir, PRECONVERTED_AUDIO_FINAL)
            with open(preconv_path, "wb") as fh:
                fh.write(b"x" * 8192)
            preconv_size = os.path.getsize(preconv_path)

            html_path = os.path.join(tmpdir, "output.html")
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                _shared.invalidate_session_storage_cache()
                info_before = _shared.get_session_storage_info()
                self.assertGreaterEqual(
                    info_before["total_bytes"],
                    preconv_size,
                    "preconv file must be visible before pipeline runs",
                )

                base_patches = self._make_pipeline_patches(
                    session_ctx, preconv_path, html_path, tmpdir
                )
                spy = patch(
                    "jot.pipeline.pipeline.invalidate_session_storage_cache",
                    wraps=_shared.invalidate_session_storage_cache,
                )

                app = _PromptBlockingApp()
                with contextlib.ExitStack() as stack:
                    for p in base_patches:
                        stack.enter_context(p)
                    mock_invalidate = stack.enter_context(spy)
                    esegui_sbobinatura(input_path, "fake-key", app)

                mock_invalidate.assert_called_once()
                self.assertFalse(
                    os.path.exists(preconv_path),
                    "preconv file must be deleted by pipeline cleanup",
                )
                info_after = _shared.get_session_storage_info()
                self.assertEqual(
                    info_after["total_bytes"],
                    info_before["total_bytes"] - preconv_size,
                    "storage must reflect deletion immediately without manual invalidation",
                )

    def test_cleanup_failed_removal_does_not_invalidate_cache(self):
        from jot.core.shared import PRECONVERTED_AUDIO_FINAL

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            session_ctx = self._make_session_ctx(session_dir)

            preconv_path = os.path.join(session_dir, PRECONVERTED_AUDIO_FINAL)
            with open(preconv_path, "wb") as fh:
                fh.write(b"x" * 8192)

            html_path = os.path.join(tmpdir, "output.html")
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            base_patches = self._make_pipeline_patches(
                session_ctx, preconv_path, html_path, tmpdir
            )
            spy = patch("jot.pipeline.pipeline.invalidate_session_storage_cache")
            _real_remove = os.remove

            def _selective_remove(p):
                if os.path.basename(str(p)) == PRECONVERTED_AUDIO_FINAL:
                    raise PermissionError("locked")
                return _real_remove(p)

            remove_fail = patch("os.remove", side_effect=_selective_remove)

            app = _PromptBlockingApp()
            with contextlib.ExitStack() as stack:
                for p in base_patches:
                    stack.enter_context(p)
                mock_invalidate = stack.enter_context(spy)
                stack.enter_context(remove_fail)
                esegui_sbobinatura(input_path, "fake-key", app)

            mock_invalidate.assert_not_called()

    def test_cleanup_runs_on_done_early_return(self):
        """finally-block safety net deletes the preconverted audio on the
        'done early return' path (stage==done, HTML present, user keeps old result)."""
        from jot.core.shared import PRECONVERTED_AUDIO_FINAL

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            session_ctx = self._make_session_ctx(session_dir)

            preconv_path = os.path.join(session_dir, PRECONVERTED_AUDIO_FINAL)
            with open(preconv_path, "wb") as fh:
                fh.write(b"x" * 8192)

            html_path = os.path.join(session_dir, "output.html")
            with open(html_path, "w") as fh:
                fh.write("<html></html>")

            session_ctx.session["stage"] = "done"
            session_ctx.session["outputs"] = {"html": html_path}

            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            app = _DoneEarlyReturnApp()

            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("google.genai.Client", _FakeClient))
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.initialize_session_context",
                        return_value=session_ctx,
                    )
                )
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.attach_file_handler",
                        return_value=None,
                    )
                )
                stack.enter_context(patch("jot.pipeline.pipeline.detach_file_handler"))
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.get_logger",
                        return_value=_FakeLogger(),
                    )
                )
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.load_fallback_keys",
                        return_value=[],
                    )
                )
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.resolve_ffmpeg",
                        return_value="ffmpeg",
                    )
                )
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.probe_media_duration",
                        return_value=(120.0, None),
                    )
                )
                stack.enter_context(
                    patch("jot.pipeline.pipeline.persist_phase1_metadata")
                )
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.normalize_stage",
                        return_value="done",
                    )
                )
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.list_phase1_chunks",
                        return_value=[],
                    )
                )
                stack.enter_context(
                    patch(
                        "jot.pipeline.pipeline.phase1_has_progress",
                        return_value=True,
                    )
                )
                esegui_sbobinatura(input_path, "fake-key", app, resume_session=True)

            self.assertFalse(
                os.path.exists(preconv_path),
                "preconv file must be deleted by finally-block safety net on done early return",
            )
            self.assertEqual(app.last_run_status, "completed")

    def test_cleanup_skipped_when_stage_not_done(self):
        """Preconverted audio is NOT deleted when stage is still phase1 (needed for resume)."""
        from jot.core.shared import PRECONVERTED_AUDIO_FINAL

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            session_ctx = self._make_session_ctx(session_dir)

            preconv_path = os.path.join(session_dir, PRECONVERTED_AUDIO_FINAL)
            with open(preconv_path, "wb") as fh:
                fh.write(b"x" * 8192)

            html_path = os.path.join(tmpdir, "output.html")
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            base_patches = self._make_pipeline_patches(
                session_ctx, preconv_path, html_path, tmpdir
            )
            phase1_fail = patch(
                "jot.pipeline.pipeline.process_phase1_transcription",
                return_value=(_FakeClient(), None, ""),
            )

            app = _DoneEarlyReturnApp()
            with contextlib.ExitStack() as stack:
                for p in base_patches:
                    stack.enter_context(p)
                stack.enter_context(phase1_fail)
                esegui_sbobinatura(input_path, "fake-key", app)

            self.assertTrue(
                os.path.exists(preconv_path),
                "preconv file must be kept when processing is incomplete (stage!=done)",
            )


class PipelineStageRoutingTests(unittest.TestCase):
    """Tests that verify phase-skipping when resuming from phase2."""

    def _base_patches(self, session_ctx, stage, tmpdir=None):
        """Return the minimal patch set to get past init and into the stage router."""
        return [
            patch("google.genai.Client", _FakeClient),
            # the course step (summary + course folder) has its own tests
            patch(
                "jot.pipeline.pipeline.run_course_step",
                side_effect=lambda **kwargs: kwargs["client"],
            ),
            patch(
                "jot.pipeline.pipeline.initialize_session_context",
                return_value=session_ctx,
            ),
            patch(
                "jot.pipeline.pipeline.attach_file_handler",
                return_value=None,
            ),
            patch("jot.pipeline.pipeline.detach_file_handler"),
            patch(
                "jot.pipeline.pipeline.get_logger",
                return_value=_FakeLogger(),
            ),
            patch("jot.pipeline.pipeline.load_fallback_keys", return_value=[]),
            patch("jot.pipeline.pipeline.resolve_ffmpeg", return_value="ffmpeg"),
            patch(
                "jot.pipeline.pipeline.probe_media_duration",
                return_value=(120.0, None),
            ),
            patch("jot.pipeline.pipeline.persist_phase1_metadata"),
            patch("jot.pipeline.pipeline.normalize_stage", return_value=stage),
            patch("jot.pipeline.pipeline.list_phase1_chunks", return_value=[]),
            patch(
                "jot.pipeline.pipeline.phase1_has_progress",
                return_value=False,
            ),
            patch(
                "jot.pipeline.pipeline.ensure_preconverted_audio",
                return_value=(False, None),
            ),
            patch(
                "jot.pipeline.pipeline.restore_phase1_progress",
                return_value=SimpleNamespace(
                    existing_chunks=[],
                    start_sec=120,
                    full_transcript="",
                    prev_memory="",
                ),
            ),
            patch("jot.pipeline.pipeline.build_macro_blocks", return_value=[]),
            patch("jot.pipeline.pipeline._atomic_write_json"),
            patch(
                "jot.pipeline.pipeline.process_macro_revision_phase",
                return_value=(_FakeClient(), ""),
            ),
            patch(
                "jot.pipeline.pipeline.export_final_html_document",
                side_effect=self._make_fake_export(tmpdir),
            ),
        ]

    @staticmethod
    def _make_fake_export(tmpdir):
        """Return a side_effect for export_final_html_document that creates a real file."""
        if tmpdir is None:
            return lambda **kw: ("Title", "/tmp/out.html")

        html_path = os.path.join(tmpdir, "out.html")

        def _fake_export(**kwargs):
            with open(html_path, "w") as fh:
                fh.write("<html></html>")
            return "Title", html_path

        return _fake_export

    def _make_session(self, tmpdir, stage):
        ctx = _FakeSessionContext(os.path.join(tmpdir, "session"))
        ctx.session["stage"] = stage
        return ctx

    def test_phase2_stage_skips_phase1_transcription(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_ctx = self._make_session(tmpdir, "phase2")
            app = _PromptBlockingApp()

            import contextlib

            with contextlib.ExitStack() as stack:
                mocks = {}
                for p in self._base_patches(session_ctx, "phase2", tmpdir):
                    m = stack.enter_context(p)
                    mocks[p.attribute if hasattr(p, "attribute") else str(p)] = m
                phase1_mock = stack.enter_context(
                    patch("jot.pipeline.pipeline.process_phase1_transcription")
                )
                esegui_sbobinatura(input_path, "fake-key", app)

        phase1_mock.assert_not_called()

    def test_boundary_stage_skips_phase1_and_advances_to_done(self):
        """Resuming with stage='boundary' must skip phase-1, run through phase-2,
        update session stage to 'done', and complete successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_ctx = self._make_session(tmpdir, "boundary")
            app = _PromptBlockingApp()

            with contextlib.ExitStack() as stack:
                for p in self._base_patches(session_ctx, "boundary", tmpdir):
                    stack.enter_context(p)
                phase1_mock = stack.enter_context(
                    patch("jot.pipeline.pipeline.process_phase1_transcription")
                )
                esegui_sbobinatura(input_path, "fake-key", app)

        phase1_mock.assert_not_called()
        self.assertEqual(session_ctx.session.get("stage"), "done")
        self.assertEqual(app.last_run_status, "completed")


class PipelineEarlyExitTests(unittest.TestCase):
    """Tests that verify the pipeline exits cleanly on ffmpeg/probe failures."""

    def _make_session_ctx(self, session_dir):
        return _FakeSessionContext(session_dir)

    def test_resolve_ffmpeg_raises_sets_status_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_ctx = self._make_session_ctx(os.path.join(tmpdir, "session"))
            app = _PromptBlockingApp()

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    side_effect=FileNotFoundError("ffmpeg not found"),
                ),
            ):
                esegui_sbobinatura(input_path, "fake-key", app)

        self.assertEqual(app.last_run_status, "failed")

    def test_probe_media_duration_none_sets_status_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_ctx = self._make_session_ctx(os.path.join(tmpdir, "session"))
            app = _PromptBlockingApp()

            with (
                patch("google.genai.Client", _FakeClient),
                # the course step (summary + course folder) has its own tests
                patch(
                    "jot.pipeline.pipeline.run_course_step",
                    side_effect=lambda **kwargs: kwargs["client"],
                ),
                patch(
                    "jot.pipeline.pipeline.initialize_session_context",
                    return_value=session_ctx,
                ),
                patch(
                    "jot.pipeline.pipeline.attach_file_handler",
                    return_value=None,
                ),
                patch("jot.pipeline.pipeline.detach_file_handler"),
                patch(
                    "jot.pipeline.pipeline.get_logger",
                    return_value=_FakeLogger(),
                ),
                patch(
                    "jot.pipeline.pipeline.load_fallback_keys",
                    return_value=[],
                ),
                patch(
                    "jot.pipeline.pipeline.resolve_ffmpeg",
                    return_value="ffmpeg",
                ),
                patch(
                    "jot.pipeline.pipeline.probe_media_duration",
                    return_value=(None, "duration_NA"),
                ),
            ):
                esegui_sbobinatura(input_path, "fake-key", app)

        self.assertEqual(app.last_run_status, "failed")


if __name__ == "__main__":
    unittest.main()
