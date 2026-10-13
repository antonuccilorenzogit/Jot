import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jot.core.session_store import SessionCollisionError
from jot.core.shared import (
    PRECONVERTED_AUDIO_FINAL,
    PRECONVERTED_AUDIO_PARTIAL,
    _file_tail_hash,
    _session_id_for_file,
)
from jot.pipeline.pipeline_session import (
    AutosaveFailedError,
    SaveSessionGuard,
    check_disk_space,
    ensure_preconverted_audio,
    estimate_disk_space,
    initialize_session_context,
    normalize_stage,
    phase1_has_progress,
    record_step_metric,
    reset_for_regeneration,
    restore_phase1_progress,
)
from jot.pipeline.pipeline_settings import PipelineSettings


class _DummyContext:
    def __init__(self, session, phase1_chunks_dir):
        self.session = session
        self.phase1_chunks_dir = phase1_chunks_dir


class _DummyPreconvContext:
    def __init__(self, session_dir):
        self.session = {}
        self.session_dir = session_dir
        self.settings = PipelineSettings(
            model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
            effective_model="gemini-2.5-flash",
            chunk_minutes=15,
            overlap_seconds=30,
            macro_char_limit=22000,
            preconvert_audio=True,
            audio_bitrate="48k",
            prefetch_next_chunk=True,
            inline_audio_max_mb=6.0,
        )
        self.save_calls = 0

    def save(self):
        self.save_calls += 1
        return True


class _DummyRegenContext:
    def __init__(self, input_path: str, session_dir: str):
        self.input_path = input_path
        self.session_paths = SimpleNamespace(session_dir=session_dir)
        self.session = {
            "settings": {
                "model": "gemini-2.5-flash",
                "fallback_models": ["gemini-3.6-flash"],
                "effective_model": "gemini-2.5-flash",
            }
        }
        self.settings = PipelineSettings(
            model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
            effective_model="gemini-2.5-flash",
            chunk_minutes=15,
            overlap_seconds=30,
            macro_char_limit=22000,
            preconvert_audio=True,
            audio_bitrate="48k",
            prefetch_next_chunk=True,
            inline_audio_max_mb=6.0,
        )
        self.settings_changed = False
        self.save_calls = 0

    def save(self):
        self.save_calls += 1
        return True


class PipelineSessionHelpersTests(unittest.TestCase):
    def test_reset_for_regeneration_uses_current_config_not_old_session_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as handle:
                handle.write(b"fake")

            context = _DummyRegenContext(input_path, os.path.join(tmpdir, "session"))
            fresh_settings = {
                "model": "gemini-3.6-flash",
                "fallback_models": [],
                "effective_model": "gemini-3.6-flash",
                "chunk_minutes": 15,
                "overlap_seconds": 30,
                "macro_char_limit": 22000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }

            with (
                patch("jot.pipeline.pipeline_session.reset_session_dirs"),
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={"preferred_model": "gemini-3.6-flash"},
                ),
                patch(
                    "jot.pipeline.pipeline_session.build_default_pipeline_settings",
                    return_value=fresh_settings,
                ),
            ):
                reset_for_regeneration(context)  # type: ignore[arg-type]

            self.assertEqual(context.session["settings"]["model"], "gemini-3.6-flash")
            self.assertEqual(
                context.session["settings"]["effective_model"],
                "gemini-3.6-flash",
            )
            self.assertEqual(context.settings.model, "gemini-3.6-flash")
            self.assertEqual(context.settings.effective_model, "gemini-3.6-flash")
            self.assertEqual(context.save_calls, 1)

    def test_normalize_stage_falls_back_to_phase1(self):
        session = {"stage": "wat"}
        stage = normalize_stage(session)
        self.assertEqual(stage, "phase1")
        self.assertEqual(session["stage"], "phase1")

    def test_preconverted_audio_partial_has_mp3_extension(self):
        self.assertTrue(PRECONVERTED_AUDIO_PARTIAL.endswith(".mp3"))

    def test_phase1_progress_detects_saved_output(self):
        session = {"outputs": {"html": "ready.html"}}
        self.assertTrue(phase1_has_progress(session, "done", []))

    def test_restore_phase1_progress_loads_existing_chunks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_path = os.path.join(tmpdir, "chunk_001_0_60.md")
            with open(chunk_path, "w", encoding="utf-8") as handle:
                handle.write("Chunk 1 body")

            session = {"phase1": {"next_start_sec": 0, "memoria_precedente": ""}}
            context = _DummyContext(session, tmpdir)
            restored = restore_phase1_progress(context, stage="phase1", step_seconds=30)  # type: ignore[arg-type]

            self.assertEqual(len(restored.existing_chunks), 1)
            self.assertEqual(restored.start_sec, 30)
            self.assertIn("Chunk 1 body", restored.full_transcript)
            self.assertEqual(restored.prev_memory, "Chunk 1 body")

    def test_record_step_metric_accumulates_elapsed_time(self):
        session = {}
        record_step_metric(session, "chunks", 2.5, done=1, total=3)
        record_step_metric(session, "chunks", 1.5, done=2, total=3)

        metric = session["metrics"]["chunks"]
        self.assertEqual(metric["count"], 2)
        self.assertEqual(metric["done"], 2)
        self.assertEqual(metric["total"], 3)
        self.assertAlmostEqual(metric["elapsed_seconds"], 4.0)

    def test_ensure_preconverted_audio_promotes_partial_and_saves_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _DummyPreconvContext(tmpdir)
            partial_path = os.path.join(tmpdir, PRECONVERTED_AUDIO_PARTIAL)
            final_path = os.path.join(tmpdir, PRECONVERTED_AUDIO_FINAL)
            phases = []
            seen_output_paths = []

            def fake_preconvert(**kwargs):
                seen_output_paths.append(kwargs["output_path"])
                with open(kwargs["output_path"], "wb") as handle:
                    handle.write(b"x" * 4096)
                return True, None

            with patch(
                "jot.pipeline.pipeline_session.preconvert_media_to_mp3",
                side_effect=fake_preconvert,
            ):
                with patch(
                    "jot.pipeline.pipeline_session.invalidate_session_storage_cache"
                ) as mock_invalidate:
                    enabled, result_path = ensure_preconverted_audio(  # type: ignore[arg-type]
                        context,  # type: ignore[arg-type]
                        input_path="lesson.mp3",
                        stage="phase1",
                        ffmpeg_exe="ffmpeg",
                        cancel_event=None,
                        cancelled=lambda: False,
                        phase_callback=phases.append,
                    )

            self.assertTrue(enabled)
            self.assertEqual(result_path, final_path)
            self.assertEqual(seen_output_paths, [partial_path])
            self.assertFalse(os.path.exists(partial_path))
            self.assertTrue(os.path.exists(final_path))
            self.assertEqual(context.save_calls, 1)
            self.assertEqual(context.session["phase1"]["preconverted_path"], final_path)
            self.assertTrue(context.session["phase1"]["preconverted_done"])
            self.assertEqual(phases, ["Fase 0/3: pre-conversione audio"])
            mock_invalidate.assert_called_once()

    def test_ensure_preconverted_audio_cache_reflects_promoted_bytes_immediately(self):
        from jot.core import shared as _shared

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(session_dir, exist_ok=True)
            context = _DummyPreconvContext(session_dir)
            partial_path = os.path.join(session_dir, PRECONVERTED_AUDIO_PARTIAL)
            final_path = os.path.join(session_dir, PRECONVERTED_AUDIO_FINAL)

            with open(partial_path, "wb") as handle:
                handle.write(b"p" * 4096)

            def fake_preconvert(**kwargs):
                with open(kwargs["output_path"], "wb") as handle:
                    handle.write(b"f" * 8192)
                return True, None

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                _shared.invalidate_session_storage_cache()
                info_before = _shared.get_session_storage_info()
                self.assertEqual(
                    info_before["total_bytes"],
                    0,
                    "partial file must not count toward storage",
                )

                with patch(
                    "jot.pipeline.pipeline_session.preconvert_media_to_mp3",
                    side_effect=fake_preconvert,
                ):
                    enabled, result_path = ensure_preconverted_audio(  # type: ignore[arg-type]
                        context,  # type: ignore[arg-type]
                        input_path="lesson.mp3",
                        stage="phase1",
                        ffmpeg_exe="ffmpeg",
                        cancel_event=None,
                        cancelled=lambda: False,
                        phase_callback=lambda _: None,
                    )

                self.assertTrue(enabled)
                self.assertEqual(result_path, final_path)
                self.assertTrue(os.path.exists(final_path))
                self.assertFalse(os.path.exists(partial_path))

                info_after = _shared.get_session_storage_info()
                self.assertEqual(
                    info_after["total_bytes"],
                    8192,
                    "promoted final MP3 must be visible immediately without manual cache invalidation",
                )

    def test_ensure_preconverted_audio_cache_not_invalidated_on_cancel(self):
        from jot.core import shared as _shared

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(session_dir, exist_ok=True)
            context = _DummyPreconvContext(session_dir)

            def fake_preconvert(**kwargs):
                with open(kwargs["output_path"], "wb") as handle:
                    handle.write(b"z" * 4096)
                return False, "cancelled"

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                _shared.invalidate_session_storage_cache()
                _shared.get_session_storage_info()

                with patch(
                    "jot.pipeline.pipeline_session.preconvert_media_to_mp3",
                    side_effect=fake_preconvert,
                ):
                    with patch(
                        "jot.pipeline.pipeline_session.invalidate_session_storage_cache"
                    ) as mock_invalidate:
                        ensure_preconverted_audio(  # type: ignore[arg-type]
                            context,  # type: ignore[arg-type]
                            input_path="lesson.mp3",
                            stage="phase1",
                            ffmpeg_exe="ffmpeg",
                            cancel_event=None,
                            cancelled=lambda: True,
                            phase_callback=lambda _: None,
                        )

                mock_invalidate.assert_not_called()

    def test_ensure_preconverted_audio_cache_not_invalidated_on_failed_promotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _DummyPreconvContext(tmpdir)

            def fake_preconvert(**kwargs):
                with open(kwargs["output_path"], "wb") as handle:
                    handle.write(b"k" * 4096)
                return True, None

            with patch(
                "jot.pipeline.pipeline_session.preconvert_media_to_mp3",
                side_effect=fake_preconvert,
            ):
                with patch(
                    "jot.pipeline.pipeline_session.os.replace",
                    side_effect=PermissionError("locked"),
                ):
                    with patch(
                        "jot.pipeline.pipeline_session.invalidate_session_storage_cache"
                    ) as mock_invalidate:
                        ensure_preconverted_audio(  # type: ignore[arg-type]
                            context,  # type: ignore[arg-type]
                            input_path="lesson.mp3",
                            stage="phase1",
                            ffmpeg_exe="ffmpeg",
                            cancel_event=None,
                            cancelled=lambda: False,
                            phase_callback=lambda _: None,
                        )

            mock_invalidate.assert_not_called()

    def test_ensure_preconverted_audio_removes_stale_partial_before_retry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _DummyPreconvContext(tmpdir)
            partial_path = os.path.join(tmpdir, PRECONVERTED_AUDIO_PARTIAL)

            with open(partial_path, "wb") as handle:
                handle.write(b"stale")

            def fake_preconvert(**kwargs):
                self.assertFalse(os.path.exists(kwargs["output_path"]))
                with open(kwargs["output_path"], "wb") as handle:
                    handle.write(b"y" * 4096)
                return True, None

            with patch(
                "jot.pipeline.pipeline_session.preconvert_media_to_mp3",
                side_effect=fake_preconvert,
            ):
                enabled, result_path = ensure_preconverted_audio(  # type: ignore[arg-type]
                    context,  # type: ignore[arg-type]
                    input_path="lesson.mp3",
                    stage="phase1",
                    ffmpeg_exe="ffmpeg",
                    cancel_event=None,
                    cancelled=lambda: False,
                    phase_callback=lambda _phase: None,
                )

            self.assertTrue(enabled)
            self.assertEqual(
                result_path, os.path.join(tmpdir, PRECONVERTED_AUDIO_FINAL)
            )
            self.assertFalse(os.path.exists(partial_path))

    def test_ensure_preconverted_audio_cleans_partial_on_cancel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _DummyPreconvContext(tmpdir)
            partial_path = os.path.join(tmpdir, PRECONVERTED_AUDIO_PARTIAL)

            def fake_preconvert(**kwargs):
                with open(kwargs["output_path"], "wb") as handle:
                    handle.write(b"z" * 4096)
                return False, "cancelled"

            with patch(
                "jot.pipeline.pipeline_session.preconvert_media_to_mp3",
                side_effect=fake_preconvert,
            ):
                enabled, result_path = ensure_preconverted_audio(  # type: ignore[arg-type]
                    context,  # type: ignore[arg-type]
                    input_path="lesson.mp3",
                    stage="phase1",
                    ffmpeg_exe="ffmpeg",
                    cancel_event=None,
                    cancelled=lambda: True,
                    phase_callback=lambda _phase: None,
                )

            self.assertTrue(enabled)
            self.assertIsNone(result_path)
            self.assertFalse(os.path.exists(partial_path))
            self.assertEqual(context.save_calls, 0)
            self.assertNotIn("phase1", context.session)

    def test_ensure_preconverted_audio_cleans_partial_when_promotion_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _DummyPreconvContext(tmpdir)
            partial_path = os.path.join(tmpdir, PRECONVERTED_AUDIO_PARTIAL)

            def fake_preconvert(**kwargs):
                with open(kwargs["output_path"], "wb") as handle:
                    handle.write(b"k" * 4096)
                return True, None

            with patch(
                "jot.pipeline.pipeline_session.preconvert_media_to_mp3",
                side_effect=fake_preconvert,
            ):
                with patch(
                    "jot.pipeline.pipeline_session.os.replace",
                    side_effect=PermissionError("locked"),
                ):
                    enabled, result_path = ensure_preconverted_audio(  # type: ignore[arg-type]
                        context,  # type: ignore[arg-type]
                        input_path="lesson.mp3",
                        stage="phase1",
                        ffmpeg_exe="ffmpeg",
                        cancel_event=None,
                        cancelled=lambda: False,
                        phase_callback=lambda _phase: None,
                    )

            self.assertFalse(enabled)
            self.assertIsNone(result_path)
            self.assertFalse(os.path.exists(partial_path))
            self.assertEqual(context.save_calls, 0)
            self.assertNotIn("phase1", context.session)


class InitializeSessionContextTests(unittest.TestCase):
    def test_resume_uses_the_model_chosen_now(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import json

            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(os.path.join(session_dir, "phase1_chunks"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "phase2_revised"), exist_ok=True)
            session_data = {
                "schema_version": 1,
                "created_at": "2024-01-01 00:00:00",
                "updated_at": "2024-01-01 00:00:00",
                "stage": "phase1",
                "input": {"path": input_path, "size": 4, "mtime": 0.0},
                "settings": {
                    "model": "gemini-2.5-flash",
                    "fallback_models": [],
                    "effective_model": "gemini-2.5-flash",
                    "chunk_minutes": 15,
                    "overlap_seconds": 30,
                    "macro_char_limit": 22000,
                    "preconvert_audio": True,
                    "prefetch_next_chunk": True,
                    "inline_audio_max_mb": 6.0,
                    "audio": {"bitrate": "48k"},
                },
                "phase1": {
                    "next_start_sec": 30,
                    "chunks_done": 1,
                    "memoria_precedente": "",
                },
                "phase2": {"macro_total": 0, "revised_done": 0},
                "outputs": {},
                "last_error": None,
            }
            session_path = os.path.join(session_dir, "session.json")
            with open(session_path, "w", encoding="utf-8") as fh:
                json.dump(session_data, fh)

            with (
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={
                        "preferred_model": "gemini-3.6-flash",
                        "fallback_models": [],
                    },
                ),
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
            ):
                ctx = initialize_session_context(input_path, resume_session=True)

            # the lesson started on 2.5; the settings now say 3.6: the rest goes on 3.6
            self.assertEqual(ctx.settings.model, "gemini-3.6-flash")
            self.assertEqual(
                ctx.session["settings"]["effective_model"],
                "gemini-3.6-flash",
            )
            self.assertEqual(ctx.settings.chunk_minutes, 15)

    def test_resume_uses_the_reserve_models_chosen_now(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import json

            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(os.path.join(session_dir, "phase1_chunks"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "phase2_revised"), exist_ok=True)
            session_data = {
                "schema_version": 1,
                "created_at": "2024-01-01 00:00:00",
                "updated_at": "2024-01-01 00:00:00",
                "stage": "phase1",
                "input": {"path": input_path, "size": 4, "mtime": 0.0},
                "settings": {
                    "model": "gemini-2.5-flash",
                    "fallback_models": [],
                    "effective_model": "gemini-2.5-flash",
                    "chunk_minutes": 15,
                    "overlap_seconds": 30,
                    "macro_char_limit": 22000,
                    "preconvert_audio": True,
                    "prefetch_next_chunk": True,
                    "inline_audio_max_mb": 6.0,
                    "audio": {"bitrate": "48k"},
                },
                "phase1": {
                    "next_start_sec": 30,
                    "chunks_done": 1,
                    "memoria_precedente": "",
                },
                "phase2": {"macro_total": 0, "revised_done": 0},
                "outputs": {},
                "last_error": None,
            }
            session_path = os.path.join(session_dir, "session.json")
            with open(session_path, "w", encoding="utf-8") as fh:
                json.dump(session_data, fh)

            with (
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={
                        "preferred_model": "gemini-3.6-flash",
                        "fallback_models": ["gemini-2.5-flash"],
                    },
                ),
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
            ):
                ctx = initialize_session_context(input_path, resume_session=True)

            # the reserve models chosen now apply to the resumed lesson too
            self.assertEqual(ctx.settings.fallback_models, ["gemini-2.5-flash"])
            self.assertEqual(
                ctx.session["settings"]["fallback_models"], ["gemini-2.5-flash"]
            )

    def _make_session_file(self, tmpdir, model, chunk_minutes, chunks_done):
        import json

        input_path = os.path.join(tmpdir, "lesson.mp3")
        with open(input_path, "wb") as fh:
            fh.write(b"fake")

        session_dir = os.path.join(tmpdir, "session")
        os.makedirs(os.path.join(session_dir, "phase1_chunks"), exist_ok=True)
        os.makedirs(os.path.join(session_dir, "phase2_revised"), exist_ok=True)
        session_data = {
            "schema_version": 1,
            "created_at": "2024-01-01 00:00:00",
            "updated_at": "2024-01-01 00:00:00",
            "stage": "phase1",
            "input": {"path": input_path, "size": 4, "mtime": 0.0},
            "settings": {
                "model": model,
                "fallback_models": [],
                "effective_model": model,
                "chunk_minutes": chunk_minutes,
                "overlap_seconds": 30,
                "macro_char_limit": 22000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            },
            "phase1": {
                "next_start_sec": chunks_done * (chunk_minutes * 60 - 30),
                "chunks_done": chunks_done,
                "memoria_precedente": "",
            },
            "phase2": {"macro_total": 0, "revised_done": 0},
            "outputs": {},
            "last_error": None,
        }
        session_path = os.path.join(session_dir, "session.json")
        with open(session_path, "w", encoding="utf-8") as fh:
            json.dump(session_data, fh)
        return input_path, session_dir

    def test_chunk_minutes_and_model_updated_when_no_chunks_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path, session_dir = self._make_session_file(
                tmpdir,
                model="gemini-3.6-flash",
                chunk_minutes=10,
                chunks_done=0,
            )
            new_defaults = {
                "model": "gemini-2.5-flash",
                "fallback_models": [],
                "effective_model": "gemini-2.5-flash",
                "chunk_minutes": 15,
                "overlap_seconds": 30,
                "macro_char_limit": 22000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }
            with (
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={
                        "preferred_model": "gemini-2.5-flash",
                        "fallback_models": [],
                    },
                ),
                patch(
                    "jot.pipeline.pipeline_session.build_default_pipeline_settings",
                    return_value=new_defaults,
                ),
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
            ):
                ctx = initialize_session_context(input_path, resume_session=True)

            self.assertEqual(ctx.settings.model, "gemini-2.5-flash")
            self.assertEqual(ctx.settings.chunk_minutes, 15)

    def test_chunk_minutes_preserved_and_model_updated_when_chunks_already_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path, session_dir = self._make_session_file(
                tmpdir,
                model="gemini-3.6-flash",
                chunk_minutes=10,
                chunks_done=3,
            )
            new_defaults = {
                "model": "gemini-2.5-flash",
                "fallback_models": [],
                "effective_model": "gemini-2.5-flash",
                "chunk_minutes": 15,
                "overlap_seconds": 30,
                "macro_char_limit": 22000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }
            with (
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={
                        "preferred_model": "gemini-2.5-flash",
                        "fallback_models": [],
                    },
                ),
                patch(
                    "jot.pipeline.pipeline_session.build_default_pipeline_settings",
                    return_value=new_defaults,
                ),
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
            ):
                ctx = initialize_session_context(input_path, resume_session=True)

            self.assertEqual(ctx.settings.model, "gemini-2.5-flash")
            self.assertEqual(ctx.settings.chunk_minutes, 10)


class TestCheckDiskSpace(unittest.TestCase):
    @staticmethod
    def _settings(**kw) -> PipelineSettings:
        defaults: dict = dict(
            model="gemini-2.5-flash",
            fallback_models=[],
            effective_model="gemini-2.5-flash",
            chunk_minutes=15,
            overlap_seconds=30,
            macro_char_limit=22000,
            preconvert_audio=True,
            audio_bitrate="48k",
            prefetch_next_chunk=False,
            inline_audio_max_mb=6.0,
        )
        defaults.update(kw)
        return PipelineSettings(**defaults)

    @staticmethod
    def _fake_du(free_bytes: int):
        return SimpleNamespace(total=10 << 30, used=0, free=free_bytes)

    def test_skips_non_phase1(self):
        """No print for stage != 'phase1'."""
        with patch("builtins.print") as mock_print:
            check_disk_space("/any", 3600.0, self._settings(), "phase2")
            check_disk_space("/any", 3600.0, self._settings(), "done")
            mock_print.assert_not_called()

    def test_no_warning_when_space_sufficient(self):
        """No warning when free space is well above estimated needs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("shutil.disk_usage", return_value=self._fake_du(10 << 30)),
                patch("builtins.print") as mock_print,
            ):
                check_disk_space(tmpdir, 3600.0, self._settings(), "phase1")
            mock_print.assert_not_called()

    def test_warns_when_space_tight(self):
        """Warning printed when total_needed > free space."""
        with tempfile.TemporaryDirectory() as tmpdir:
            printed: list[str] = []
            with (
                patch("shutil.disk_usage", return_value=self._fake_du(1 << 20)),
                patch("builtins.print", side_effect=printed.append),
            ):
                check_disk_space(tmpdir, 3600.0, self._settings(), "phase1")
        self.assertTrue(any("ATTENZIONE" in m for m in printed))

    def test_preconvert_disabled_no_session_estimate(self):
        """When preconvert is disabled, session_needed=0; only chunk temp space checked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("shutil.disk_usage", return_value=self._fake_du(10 << 30)),
                patch("builtins.print") as mock_print,
            ):
                check_disk_space(
                    tmpdir, 3600.0, self._settings(preconvert_audio=False), "phase1"
                )
            mock_print.assert_not_called()

    def test_preconverted_file_exists_skips_session_estimate(self):
        """If preconverted audio already exists on disk, session_needed=0 (no double-count)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            preconv = os.path.join(tmpdir, PRECONVERTED_AUDIO_FINAL)
            open(preconv, "wb").close()
            with (
                patch("shutil.disk_usage", return_value=self._fake_du(10 << 30)),
                patch("builtins.print") as mock_print,
            ):
                check_disk_space(tmpdir, 3600.0, self._settings(), "phase1")
            mock_print.assert_not_called()

    def test_disk_usage_exception_is_silent(self):
        """OSError from shutil.disk_usage is swallowed — no crash, no print."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("shutil.disk_usage", side_effect=OSError("no disk")),
                patch("builtins.print") as mock_print,
            ):
                check_disk_space(tmpdir, 3600.0, self._settings(), "phase1")
            mock_print.assert_not_called()

    def test_warns_different_fs_session_dir_low(self):
        """Warns about session dir when on a different filesystem and free < session_needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_tmp = tmpdir + "_tmp"

            def fake_stat(path, *a, **kw):  # type: ignore[arg-type]
                s = str(path)
                if s == tmpdir:
                    return SimpleNamespace(st_dev=1)
                if s == fake_tmp:
                    return SimpleNamespace(st_dev=2)
                raise FileNotFoundError(f"fake: {s}")

            def fake_du(path):  # type: ignore[arg-type]
                if str(path) == tmpdir:
                    return self._fake_du(1 << 20)  # 1 MB in session dir
                return self._fake_du(10 << 30)  # 10 GB in temp dir

            printed: list[str] = []
            with (
                patch("os.stat", side_effect=fake_stat),
                patch("shutil.disk_usage", side_effect=fake_du),
                patch("tempfile.gettempdir", return_value=fake_tmp),
                patch("builtins.print", side_effect=printed.append),
            ):
                check_disk_space(tmpdir, 3600.0, self._settings(), "phase1")
        self.assertTrue(any("ATTENZIONE" in m for m in printed))

    def test_warns_different_fs_temp_dir_low(self):
        """Warns about temp dir when on a different filesystem and free < chunk estimate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_tmp = tmpdir + "_tmp"

            def fake_stat(path, *a, **kw):  # type: ignore[arg-type]
                s = str(path)
                if s == tmpdir:
                    return SimpleNamespace(st_dev=1)
                if s == fake_tmp:
                    return SimpleNamespace(st_dev=2)
                raise FileNotFoundError(f"fake: {s}")

            def fake_du(path):  # type: ignore[arg-type]
                if str(path) == tmpdir:
                    return self._fake_du(10 << 30)  # 10 GB session dir fine
                return self._fake_du(1 << 10)  # 1 KB temp dir — not enough for chunk

            printed: list[str] = []
            with (
                patch("os.stat", side_effect=fake_stat),
                patch("shutil.disk_usage", side_effect=fake_du),
                patch("tempfile.gettempdir", return_value=fake_tmp),
                patch("builtins.print", side_effect=printed.append),
            ):
                check_disk_space(
                    tmpdir, 3600.0, self._settings(preconvert_audio=False), "phase1"
                )
        self.assertTrue(any("ATTENZIONE" in m for m in printed))

    def test_resume_last_chunk_caps_concurrent_no_spurious_warning(self):
        """On resume with only 1 chunk remaining, prefetch=True is capped to 1 — no false warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            printed: list[str] = []
            settings = self._settings(preconvert_audio=False, prefetch_next_chunk=True)
            chunk_sec = settings.chunk_seconds  # 900s
            bytes_per_sec = 48_000 / 8  # 6000 B/s
            one_chunk = int(chunk_sec * bytes_per_sec)  # 5_400_000 bytes
            free = one_chunk + 1  # just enough for 1 chunk, not 2
            with (
                patch("shutil.disk_usage", return_value=self._fake_du(free)),
                patch("builtins.print", side_effect=printed.append),
            ):
                check_disk_space(
                    tmpdir,
                    3600.0,
                    settings,
                    "phase1",
                    next_start_sec=3600 - settings.step_seconds,
                )
        self.assertFalse(
            any("ATTENZIONE" in m for m in printed),
            "Should not warn when only 1 chunk remains and free >= 1 chunk",
        )

    def test_resume_all_chunks_done_temp_zero_no_warning(self):
        """On resume when next_start_sec >= total_duration, temp_needed=0 — no warning even with tiny free space."""
        with tempfile.TemporaryDirectory() as tmpdir:
            printed: list[str] = []
            with (
                patch("shutil.disk_usage", return_value=self._fake_du(1 << 10)),
                patch("builtins.print", side_effect=printed.append),
            ):
                check_disk_space(
                    tmpdir,
                    3600.0,
                    self._settings(preconvert_audio=False),
                    "phase1",
                    next_start_sec=3600,
                )
        self.assertFalse(
            any("ATTENZIONE" in m for m in printed),
            "Should not warn when no chunks remain (next_start_sec >= total_duration)",
        )

    def test_invalid_bitrate_uses_fallback_no_crash(self):
        """Bogus bitrate string falls back to 48k — no crash, estimate still computed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("shutil.disk_usage", return_value=self._fake_du(10 << 30)),
                patch("builtins.print") as mock_print,
            ):
                check_disk_space(
                    tmpdir, 3600.0, self._settings(audio_bitrate="bad!"), "phase1"
                )
            mock_print.assert_not_called()

    def test_estimate_marks_clearly_insufficient_only_beyond_ten_percent_deficit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._settings(preconvert_audio=False)
            needed = int(settings.chunk_seconds * 48_000 / 8)
            with patch(
                "shutil.disk_usage",
                return_value=self._fake_du(int(needed * 0.95)),
            ):
                estimates = estimate_disk_space(tmpdir, 3600.0, settings, "phase1")
            self.assertFalse(estimates[0].is_clearly_insufficient)

            with patch(
                "shutil.disk_usage",
                return_value=self._fake_du(int(needed * 0.5)),
            ):
                estimates = estimate_disk_space(tmpdir, 3600.0, settings, "phase1")
            self.assertTrue(estimates[0].is_clearly_insufficient)


if __name__ == "__main__":
    unittest.main()


class TestPipelineSessionEdgeCases(unittest.TestCase):
    """Tests for uncovered branches in pipeline_session.py."""

    @staticmethod
    def _make_settings(**kw) -> PipelineSettings:
        defaults: dict = dict(
            model="gemini-2.5-flash",
            fallback_models=[],
            effective_model="gemini-2.5-flash",
            chunk_minutes=15,
            overlap_seconds=30,
            macro_char_limit=22000,
            preconvert_audio=True,
            audio_bitrate="48k",
            prefetch_next_chunk=False,
            inline_audio_max_mb=6.0,
        )
        defaults.update(kw)
        return PipelineSettings(**defaults)

    # ── initialize_session_context ─────────────────────────────────────────────

    def test_initialize_session_context_new_session_uses_current_config(self):
        """resume_session=False creates a fresh session with config-derived model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(os.path.join(session_dir, "phase1_chunks"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "phase2_revised"), exist_ok=True)

            defaults = {
                "model": "gemini-2.5-flash",
                "fallback_models": [],
                "effective_model": "gemini-2.5-flash",
                "chunk_minutes": 15,
                "overlap_seconds": 30,
                "macro_char_limit": 22000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }

            with (
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={"preferred_model": "gemini-2.5-flash"},
                ),
                patch(
                    "jot.pipeline.pipeline_session.build_default_pipeline_settings",
                    return_value=defaults,
                ),
                # new_session() in session_store imports build_default_pipeline_settings
                # at module level and calls it with no args when settings=None, so we must
                # also patch the session_store reference to prevent a live load_config() call.
                patch(
                    "jot.core.session_store.build_default_pipeline_settings",
                    return_value=defaults,
                ),
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
                patch("jot.pipeline.pipeline_session.reset_session_dirs"),
                patch("jot.pipeline.pipeline_session.save_session_data"),
            ):
                ctx = initialize_session_context(input_path, resume_session=False)

            self.assertEqual(ctx.settings.model, "gemini-2.5-flash")
            self.assertEqual(ctx.session["stage"], "phase1")

    def test_initialize_session_context_resume_migrates_schema(self):
        """resume_session=True with a schema-v0 file migrates to the current schema."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(os.path.join(session_dir, "phase1_chunks"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "phase2_revised"), exist_ok=True)

            # schema v0: no schema_version key
            session_data = {
                "created_at": "2024-01-01 00:00:00",
                "updated_at": "2024-01-01 00:00:00",
                "stage": "phase1",
                "input": {"path": input_path, "size": 4, "mtime": 0.0},
                "settings": {
                    "model": "gemini-2.5-flash",
                    "fallback_models": [],
                    "effective_model": "gemini-2.5-flash",
                    "chunk_minutes": 15,
                    "overlap_seconds": 30,
                    "macro_char_limit": 22000,
                    "preconvert_audio": True,
                    "prefetch_next_chunk": True,
                    "inline_audio_max_mb": 6.0,
                    "audio": {"bitrate": "48k"},
                },
                "phase1": {
                    "next_start_sec": 0,
                    "chunks_done": 0,
                    "memoria_precedente": "",
                },
                "phase2": {"macro_total": 0, "revised_done": 0},
                "outputs": {},
                "last_error": None,
            }
            session_path = os.path.join(session_dir, "session.json")
            with open(session_path, "w", encoding="utf-8") as fh:
                json.dump(session_data, fh)

            with (
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={
                        "preferred_model": "gemini-2.5-flash",
                        "fallback_models": [],
                    },
                ),
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
                patch("jot.pipeline.pipeline_session.save_session_data"),
            ):
                ctx = initialize_session_context(input_path, resume_session=True)

            self.assertEqual(ctx.session["schema_version"], 2)

    def test_initialize_session_context_resume_missing_file_falls_back_to_new(self):
        """resume_session=True but session.json absent → new session created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            session_dir = os.path.join(tmpdir, "session")
            os.makedirs(os.path.join(session_dir, "phase1_chunks"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "phase2_revised"), exist_ok=True)
            # No session.json written → file absent

            with (
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={
                        "preferred_model": "gemini-2.5-flash",
                        "fallback_models": [],
                    },
                ),
                patch(
                    "jot.pipeline.pipeline_session.build_default_pipeline_settings",
                    return_value={
                        "model": "gemini-2.5-flash",
                        "fallback_models": [],
                        "effective_model": "gemini-2.5-flash",
                        "chunk_minutes": 15,
                        "overlap_seconds": 30,
                        "macro_char_limit": 22000,
                        "preconvert_audio": True,
                        "prefetch_next_chunk": True,
                        "inline_audio_max_mb": 6.0,
                        "audio": {"bitrate": "48k"},
                    },
                ),
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
                patch("jot.pipeline.pipeline_session.save_session_data"),
            ):
                ctx = initialize_session_context(input_path, resume_session=True)

            # Falls back to new session
            self.assertEqual(ctx.session["stage"], "phase1")

    # ── ensure_preconverted_audio ──────────────────────────────────────────────

    def test_ensure_preconverted_audio_disabled_returns_false_none(self):
        """preconvert_audio=False → (False, None) without touching disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _DummyPreconvContext(tmpdir)
            context.settings = self._make_settings(preconvert_audio=False)

            enabled, result_path = ensure_preconverted_audio(  # type: ignore[arg-type]
                context,  # type: ignore[arg-type]
                input_path="lesson.mp3",
                stage="phase1",
                ffmpeg_exe="ffmpeg",
                cancel_event=None,
                cancelled=lambda: False,
                phase_callback=lambda _: None,
            )

        self.assertFalse(enabled)
        self.assertIsNone(result_path)

    def test_ensure_preconverted_audio_final_file_already_large_enough_returns_early(
        self,
    ):
        """Final file exists and > 1 KB → return early without re-encoding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _DummyPreconvContext(tmpdir)
            final_path = os.path.join(tmpdir, PRECONVERTED_AUDIO_FINAL)
            with open(final_path, "wb") as fh:
                fh.write(b"x" * 2048)  # > 1024 bytes

            enabled, result_path = ensure_preconverted_audio(  # type: ignore[arg-type]
                context,  # type: ignore[arg-type]
                input_path="lesson.mp3",
                stage="phase1",
                ffmpeg_exe="ffmpeg",
                cancel_event=None,
                cancelled=lambda: False,
                phase_callback=lambda _: None,
            )

        self.assertTrue(enabled)
        self.assertEqual(result_path, final_path)
        self.assertEqual(context.save_calls, 0)  # no re-save needed

    def test_ensure_preconverted_audio_conversion_error_returns_false_none(self):
        """preconvert_media_to_mp3 returning (False, "error") → (False, None)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _DummyPreconvContext(tmpdir)

            with patch(
                "jot.pipeline.pipeline_session.preconvert_media_to_mp3",
                return_value=(False, "conversion error"),
            ):
                enabled, result_path = ensure_preconverted_audio(  # type: ignore[arg-type]
                    context,  # type: ignore[arg-type]
                    input_path="lesson.mp3",
                    stage="phase1",
                    ffmpeg_exe="ffmpeg",
                    cancel_event=None,
                    cancelled=lambda: False,
                    phase_callback=lambda _: None,
                )

        self.assertFalse(enabled)
        self.assertIsNone(result_path)

    # ── check_disk_space ───────────────────────────────────────────────────────

    def test_check_disk_space_stat_exception_on_tempdir_is_silent(self):
        """os.stat raising on tempdir → silent, no warning printed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_tmp = tmpdir + "_tmp"

            def fake_stat(path, *a, **kw):  # type: ignore[arg-type]
                if str(path) == tmpdir:
                    return SimpleNamespace(st_dev=1)
                raise OSError("stat failed on tmp")

            printed: list[str] = []
            with (
                patch("os.stat", side_effect=fake_stat),
                patch(
                    "shutil.disk_usage",
                    return_value=SimpleNamespace(total=10 << 30, used=0, free=10 << 30),
                ),
                patch("tempfile.gettempdir", return_value=fake_tmp),
                patch("builtins.print", side_effect=printed.append),
            ):
                check_disk_space(tmpdir, 3600.0, self._make_settings(), "phase1")

        self.assertFalse(any("ATTENZIONE" in m for m in printed))

    def test_check_disk_space_zero_total_duration_skips_estimate(self):
        """total_duration_sec=0 → remaining=0 → temp_needed=0 → no warning even with 1 byte free."""
        with tempfile.TemporaryDirectory() as tmpdir:
            printed: list[str] = []
            with (
                patch(
                    "shutil.disk_usage",
                    return_value=SimpleNamespace(total=10 << 30, used=0, free=1),
                ),
                patch("builtins.print", side_effect=printed.append),
            ):
                check_disk_space(
                    tmpdir, 0.0, self._make_settings(preconvert_audio=False), "phase1"
                )

        self.assertFalse(any("ATTENZIONE" in m for m in printed))

    # ── normalize_stage ────────────────────────────────────────────────────────

    def test_normalize_stage_preserves_known_stages(self):
        """Valid stage strings are returned unchanged."""
        for stage in ("phase1", "phase2", "boundary", "done"):
            session = {"stage": stage}
            self.assertEqual(normalize_stage(session), stage)
            self.assertEqual(session["stage"], stage)

    def test_normalize_stage_unknown_becomes_phase1(self):
        """Unknown stage falls back to 'phase1' and mutates session."""
        session = {"stage": "invalid_stage"}
        result = normalize_stage(session)
        self.assertEqual(result, "phase1")
        self.assertEqual(session["stage"], "phase1")

    # ── phase1_has_progress ────────────────────────────────────────────────────

    def test_phase1_has_progress_false_when_stage_is_phase1_and_no_data(self):
        """stage='phase1', no chunks, no outputs, no error → False."""
        self.assertFalse(phase1_has_progress({}, "phase1", []))

    def test_phase1_has_progress_true_when_stage_is_not_phase1(self):
        """Any non-'phase1' stage → True (progress already beyond phase1)."""
        self.assertTrue(phase1_has_progress({}, "done", []))
        self.assertTrue(phase1_has_progress({}, "phase2", []))

    def test_phase1_has_progress_true_when_chunks_exist(self):
        """existing_chunks non-empty → True."""
        self.assertTrue(phase1_has_progress({}, "phase1", [(1, 0, 60, "/p")]))

    def test_phase1_has_progress_true_when_outputs_html_set(self):
        """outputs.html non-empty → True even in phase1."""
        session = {"outputs": {"html": "result.html"}}
        self.assertTrue(phase1_has_progress(session, "phase1", []))

    def test_phase1_has_progress_false_when_only_last_error_set(self):
        """last_error alone without saved chunks or progress is False (0 chunks completed)."""
        session = {"last_error": "quota_daily_limit"}
        self.assertFalse(phase1_has_progress(session, "phase1", []))

    def test_phase1_has_progress_true_when_chunks_done_or_next_start_sec_set(self):
        """chunks_done > 0 or next_start_sec > 0 in phase1 state is True."""
        session1 = {"phase1": {"chunks_done": 1}}
        self.assertTrue(phase1_has_progress(session1, "phase1", []))
        session2 = {"phase1": {"next_start_sec": 600}}
        self.assertTrue(phase1_has_progress(session2, "phase1", []))

    # ── record_step_metric ─────────────────────────────────────────────────────

    def test_record_step_metric_creates_entry_from_scratch(self):
        """First call creates metrics dict and key with correct values."""
        session: dict = {}
        record_step_metric(session, "chunks", 2.5, done=1, total=5)

        m = session["metrics"]["chunks"]
        self.assertEqual(m["count"], 1)
        self.assertEqual(m["done"], 1)
        self.assertEqual(m["total"], 5)
        self.assertAlmostEqual(m["elapsed_seconds"], 2.5)

    def test_record_step_metric_accumulates_elapsed_and_count(self):
        """Subsequent calls accumulate elapsed_seconds and increment count."""
        session: dict = {}
        record_step_metric(session, "chunks", 1.0, done=1, total=3)
        record_step_metric(session, "chunks", 3.0, done=2, total=3)

        m = session["metrics"]["chunks"]
        self.assertEqual(m["count"], 2)
        self.assertEqual(m["done"], 2)
        self.assertAlmostEqual(m["elapsed_seconds"], 4.0)

    # ── restore_phase1_progress ────────────────────────────────────────────────

    def test_restore_phase1_progress_missing_dir_returns_empty_state(self):
        """Nonexistent phase1_chunks_dir → empty restore state, start_sec=0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = {"phase1": {"next_start_sec": 0, "memoria_precedente": "prev"}}
            context = _DummyContext(session, os.path.join(tmpdir, "chunks_missing"))

            restored = restore_phase1_progress(context, stage="phase1", step_seconds=30)  # type: ignore[arg-type]

        self.assertEqual(restored.existing_chunks, [])
        self.assertEqual(restored.start_sec, 0)
        self.assertEqual(restored.full_transcript, "")
        self.assertEqual(restored.prev_memory, "prev")

    def test_restore_phase1_progress_read_error_in_chunk_file_gives_empty_transcript(
        self,
    ):
        """Chunk file exists → existing_chunks populated; read error → transcript empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_path = os.path.join(tmpdir, "chunk_001_0_60.md")
            with open(chunk_path, "w", encoding="utf-8") as fh:
                fh.write("Chunk body")

            session = {"phase1": {"next_start_sec": 0, "memoria_precedente": ""}}
            context = _DummyContext(session, tmpdir)

            with patch(
                "jot.pipeline.pipeline_session.read_text_file",
                side_effect=OSError("locked"),
            ):
                restored = restore_phase1_progress(
                    context,  # type: ignore[arg-type]
                    stage="phase1",
                    step_seconds=30,
                )

        # list_phase1_chunks uses os.listdir (not open), so chunk IS found
        self.assertEqual(len(restored.existing_chunks), 1)
        # But reading the content fails → empty transcript/memory
        self.assertEqual(restored.full_transcript, "")
        self.assertEqual(restored.prev_memory, "")

    # ── reset_for_regeneration ─────────────────────────────────────────────────

    def test_reset_for_regeneration_replaces_session_settings(self):
        """reset_for_regeneration builds fresh settings from current config, not old session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            context = _DummyRegenContext(input_path, os.path.join(tmpdir, "session"))
            # Old session has model gemini-2.5-flash; new config will use flash-lite
            fresh_settings = {
                "model": "gemini-3.6-flash",
                "fallback_models": [],
                "effective_model": "gemini-3.6-flash",
                "chunk_minutes": 15,
                "overlap_seconds": 30,
                "macro_char_limit": 22000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }

            with (
                patch("jot.pipeline.pipeline_session.reset_session_dirs"),
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={"preferred_model": "gemini-3.6-flash"},
                ),
                patch(
                    "jot.pipeline.pipeline_session.build_default_pipeline_settings",
                    return_value=fresh_settings,
                ),
            ):
                reset_for_regeneration(context)  # type: ignore[arg-type]

        self.assertEqual(context.session["settings"]["model"], "gemini-3.6-flash")
        self.assertEqual(context.settings.model, "gemini-3.6-flash")
        self.assertEqual(context.save_calls, 1)


class TestSaveSessionGuard(unittest.TestCase):
    """Unit tests for SaveSessionGuard and its AutosaveFailedError integration."""

    def test_single_failure_returns_false_no_exception(self):
        """First consecutive failure returns False silently — no exception."""
        guard = SaveSessionGuard(
            lambda: False, lambda msg: None, sleep_fn=lambda _delay: None
        )
        result = guard()
        self.assertFalse(result)

    def test_success_resets_counter(self):
        """A success between failures resets the counter so no exception is raised."""
        results = iter([False, True, False])
        guard = SaveSessionGuard(
            lambda: next(results), lambda msg: None, sleep_fn=lambda _delay: None
        )
        guard()  # failure 1
        guard()  # success → counter reset
        guard()  # failure 1 again — should NOT raise

    def test_five_consecutive_failures_raise(self):
        """Five consecutive failures trigger AutosaveFailedError."""
        guard = SaveSessionGuard(
            lambda: False, lambda msg: None, sleep_fn=lambda _delay: None
        )
        for _ in range(4):
            self.assertFalse(guard())
        with self.assertRaises(AutosaveFailedError):
            guard()

    def test_on_fatal_callback_receives_message(self):
        """on_fatal is called exactly once with a non-empty diagnostic message."""
        messages: list[str] = []
        guard = SaveSessionGuard(
            lambda: False, messages.append, sleep_fn=lambda _delay: None
        )
        try:
            for _ in range(5):
                guard()
        except AutosaveFailedError:
            pass
        self.assertEqual(len(messages), 1)
        self.assertIn("autosalvataggio", messages[0].lower())

    def test_subsequent_calls_raise_without_invoking_save_fn(self):
        """Once fatal, every subsequent call raises immediately without calling save_fn."""
        call_count = 0

        def counting_save() -> bool:
            nonlocal call_count
            call_count += 1
            return False

        guard = SaveSessionGuard(
            counting_save, lambda msg: None, sleep_fn=lambda _delay: None
        )
        try:
            for _ in range(5):
                guard()
        except AutosaveFailedError:
            pass
        count_after_fatal = call_count
        with self.assertRaises(AutosaveFailedError):
            guard()  # must NOT call counting_save again
        self.assertEqual(call_count, count_after_fatal)

    def test_read_only_session_triggers_fatal(
        self,
    ):
        """Regression: simulates a read-only session dir mid-run.

        Two consecutive PermissionError saves must trigger the fatal guard and
        emit a diagnostic message without calling save_fn a third time.
        """
        messages: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake")

            with patch(
                "jot.core.session_store._session_dir_for_file",
                return_value=os.path.join(tmpdir, "session"),
            ):
                session_ctx = initialize_session_context(input_path)

            with patch(
                "jot.pipeline.pipeline_session.save_session_data",
                side_effect=PermissionError("read-only"),
            ):
                guard = SaveSessionGuard(
                    session_ctx.save, messages.append, sleep_fn=lambda _delay: None
                )

                first = (
                    guard()
                )  # failure 1 — save_session_data raises → save() returns False
                self.assertFalse(first)
                self.assertEqual(len(messages), 0)  # no warning yet

                for _ in range(3):
                    self.assertFalse(guard())
                with self.assertRaises(AutosaveFailedError):
                    guard()

            self.assertEqual(len(messages), 1)
            self.assertIn("autosalvataggio", messages[0].lower())

    def test_autosave_failed_error_is_not_caught_by_except_exception(self):
        """AutosaveFailedError(BaseException) must escape broad except Exception handlers."""
        guard = SaveSessionGuard(
            lambda: False, lambda msg: None, sleep_fn=lambda _delay: None
        )
        for _ in range(4):
            guard()
        escaped = False
        try:
            try:
                guard()
            except Exception:
                pass  # must NOT land here
        except AutosaveFailedError:
            escaped = True
        self.assertTrue(
            escaped, "AutosaveFailedError was swallowed by except Exception"
        )

    def test_failed_saves_use_backoff_sequence_before_fatal(self):
        delays: list[float] = []
        guard = SaveSessionGuard(
            lambda: False, lambda msg: None, sleep_fn=delays.append
        )

        for _ in range(4):
            self.assertFalse(guard())
        with self.assertRaises(AutosaveFailedError):
            guard()

        self.assertEqual(delays, [0.5, 1.0, 2.0, 4.0])


class TestSessionCollisionGuard(unittest.TestCase):
    """initialize_session_context must raise SessionCollisionError instead of wiping
    a completed session when resume_session=False."""

    def _make_session_dir(self, tmpdir: str, stage: str, html_exists: bool) -> str:
        session_dir = os.path.join(tmpdir, "session")
        os.makedirs(os.path.join(session_dir, "phase1_chunks"), exist_ok=True)
        os.makedirs(os.path.join(session_dir, "phase2_revised"), exist_ok=True)
        html_path = os.path.join(session_dir, "output.html")
        if html_exists:
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write("<html><body>done</body></html>")
        import json

        session_data = {
            "schema_version": 1,
            "stage": stage,
            "outputs": {"html": html_path if html_exists else ""},
        }
        with open(
            os.path.join(session_dir, "session.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(session_data, fh)
        return session_dir

    def test_no_collision_when_dir_absent(self):
        """No error when the session directory does not exist yet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake audio")

            non_existent = os.path.join(tmpdir, "no_such_session")
            with (
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=non_existent,
                ),
                patch("jot.pipeline.pipeline_session.save_session_data"),
            ):
                ctx = initialize_session_context(input_path, resume_session=False)
            self.assertEqual(ctx.session["stage"], "phase1")

    def test_no_collision_when_stage_not_done(self):
        """No error when existing session is not done (in-progress phase1)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake audio")

            session_dir = self._make_session_dir(
                tmpdir, stage="phase1", html_exists=False
            )
            with (
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
                patch("jot.pipeline.pipeline_session.save_session_data"),
            ):
                ctx = initialize_session_context(input_path, resume_session=False)
            self.assertEqual(ctx.session["stage"], "phase1")

    def test_no_collision_when_html_absent(self):
        """No error when stage==done but the HTML file no longer exists on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake audio")

            session_dir = self._make_session_dir(
                tmpdir, stage="done", html_exists=False
            )
            with (
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
                patch("jot.pipeline.pipeline_session.save_session_data"),
            ):
                ctx = initialize_session_context(input_path, resume_session=False)
            self.assertEqual(ctx.session["stage"], "phase1")

    def test_raises_when_stage_done_and_html_exists(self):
        """SessionCollisionError raised when session is done + HTML exists + resume=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake audio")

            session_dir = self._make_session_dir(tmpdir, stage="done", html_exists=True)
            with (
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
                patch("jot.pipeline.pipeline_session.save_session_data"),
            ):
                with self.assertRaises(SessionCollisionError) as cm:
                    initialize_session_context(input_path, resume_session=False)
            self.assertEqual(str(cm.exception), "session_collision")
            self.assertEqual(cm.exception.session_dir, session_dir)

    def test_no_collision_when_allow_completed_destroy_true(self):
        """allow_completed_destroy=True bypasses the SessionCollisionError when resume=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake audio")

            session_dir = self._make_session_dir(tmpdir, stage="done", html_exists=True)
            with (
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
                patch("jot.pipeline.pipeline_session.save_session_data"),
            ):
                ctx = initialize_session_context(
                    input_path, resume_session=False, allow_completed_destroy=True
                )
            self.assertEqual(ctx.session["stage"], "phase1")

    def test_no_collision_when_resume_true(self):
        """resume_session=True must never trigger the collision guard."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "lesson.mp3")
            with open(input_path, "wb") as fh:
                fh.write(b"fake audio")

            session_dir = self._make_session_dir(tmpdir, stage="done", html_exists=True)
            with (
                patch(
                    "jot.core.session_store._session_dir_for_file",
                    return_value=session_dir,
                ),
                patch("jot.pipeline.pipeline_session.save_session_data"),
                patch(
                    "jot.pipeline.pipeline_session.load_config",
                    return_value={},
                ),
                patch(
                    "jot.pipeline.pipeline_session.build_default_pipeline_settings",
                    return_value={
                        "model": "gemini-2.5-flash",
                        "fallback_models": [],
                        "effective_model": "gemini-2.5-flash",
                        "chunk_minutes": 15,
                        "overlap_seconds": 30,
                        "macro_char_limit": 22000,
                        "preconvert_audio": True,
                        "prefetch_next_chunk": True,
                        "inline_audio_max_mb": 6.0,
                        "audio": {"bitrate": "48k"},
                    },
                ),
            ):
                ctx = initialize_session_context(input_path, resume_session=True)
            self.assertEqual(ctx.session["stage"], "done")

    def test_session_collision_str_is_error_code(self):
        """str(SessionCollisionError) returns the raw error code consumed by the pipeline."""
        err = SessionCollisionError("/some/dir")
        self.assertEqual(str(err), "session_collision")
        self.assertEqual(err.session_dir, "/some/dir")


class TestSessionFingerprint(unittest.TestCase):
    """_session_id_for_file must distinguish files that share size and first 1 MB."""

    def test_same_head_different_tail_yields_different_id(self):
        """Two files with identical first bytes but different tails must get different IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shared_head = b"A" * (1024 * 1024 + 512)  # 1 MB + 512 bytes common prefix

            path_a = os.path.join(tmpdir, "a.mp3")
            path_b = os.path.join(tmpdir, "b.mp3")
            with open(path_a, "wb") as fh:
                fh.write(shared_head + b"\x01" * 512)
            with open(path_b, "wb") as fh:
                fh.write(shared_head + b"\x02" * 512)

            id_a = _session_id_for_file(path_a)
            id_b = _session_id_for_file(path_b)
            self.assertNotEqual(id_a, id_b)

    def test_identical_files_yield_same_id(self):
        """Two copies of the same content must yield the same session ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            content = b"lecture content" * 10000

            path_a = os.path.join(tmpdir, "copy_a.mp3")
            path_b = os.path.join(tmpdir, "copy_b.mp3")
            with open(path_a, "wb") as fh:
                fh.write(content)
            with open(path_b, "wb") as fh:
                fh.write(content)
            same_mtime_ns = 1_700_000_000_000_000_000
            os.utime(path_a, ns=(same_mtime_ns, same_mtime_ns))
            os.utime(path_b, ns=(same_mtime_ns, same_mtime_ns))

            id_a = _session_id_for_file(path_a)
            id_b = _session_id_for_file(path_b)
            self.assertEqual(id_a, id_b)

    def test_same_content_different_mtime_yields_same_id(self):
        """mtime_ns does not participate in the durable session ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            content = b"same lecture content" * 10000

            path_a = os.path.join(tmpdir, "copy_a.mp3")
            path_b = os.path.join(tmpdir, "copy_b.mp3")
            with open(path_a, "wb") as fh:
                fh.write(content)
            with open(path_b, "wb") as fh:
                fh.write(content)
            os.utime(path_a, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
            os.utime(path_b, ns=(1_700_000_100_000_000_000, 1_700_000_100_000_000_000))

            id_a = _session_id_for_file(path_a)
            id_b = _session_id_for_file(path_b)
            self.assertEqual(id_a, id_b)

    def test_file_tail_hash_differs_for_different_endings(self):
        """_file_tail_hash returns different digests for files with different last bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path_a = os.path.join(tmpdir, "a.bin")
            path_b = os.path.join(tmpdir, "b.bin")
            with open(path_a, "wb") as fh:
                fh.write(b"same start" + b"\xff" * 100)
            with open(path_b, "wb") as fh:
                fh.write(b"same start" + b"\x00" * 100)

            self.assertNotEqual(_file_tail_hash(path_a), _file_tail_hash(path_b))

    def test_file_tail_hash_small_file_equals_full_hash(self):
        """For files smaller than max_bytes, tail hash == hash of whole file."""
        import hashlib

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "small.bin")
            data = b"tiny file content"
            with open(path, "wb") as fh:
                fh.write(data)

            expected = hashlib.sha256(data).hexdigest()
            self.assertEqual(_file_tail_hash(path), expected)
