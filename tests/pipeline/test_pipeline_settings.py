import unittest
from typing import Any, cast
from unittest.mock import patch

from jot.pipeline.pipeline_settings import (
    PipelineSettings,
    _as_bool,
    _as_float,
    _as_int,
    build_default_pipeline_settings,
    load_and_sanitize_settings,
)


class AsBoolTests(unittest.TestCase):
    def test_bool_true(self):
        self.assertTrue(_as_bool(True, False))

    def test_bool_false(self):
        self.assertFalse(_as_bool(False, True))

    def test_int_nonzero(self):
        self.assertTrue(_as_bool(1, False))

    def test_int_zero(self):
        self.assertFalse(_as_bool(0, True))

    def test_string_truthy_values(self):
        for val in ("1", "true", "yes", "y", "on", "TRUE", "Yes"):
            with self.subTest(val=val):
                self.assertTrue(_as_bool(val, False))

    def test_string_falsy_values(self):
        for val in ("0", "false", "no", "n", "off", "FALSE", "No"):
            with self.subTest(val=val):
                self.assertFalse(_as_bool(val, True))

    def test_garbage_returns_default(self):
        self.assertTrue(_as_bool("garbage", True))
        self.assertFalse(_as_bool("garbage", False))

    def test_none_returns_default(self):
        self.assertTrue(_as_bool(None, True))


class AsFloatTests(unittest.TestCase):
    def test_valid_float(self):
        self.assertAlmostEqual(_as_float(3.14, 0.0), 3.14)

    def test_valid_string_float(self):
        self.assertAlmostEqual(_as_float("2.5", 0.0), 2.5)

    def test_invalid_returns_default(self):
        self.assertAlmostEqual(_as_float("bad", 9.9), 9.9)

    def test_none_returns_default(self):
        self.assertAlmostEqual(_as_float(None, 1.5), 1.5)


class AsIntTests(unittest.TestCase):
    def test_valid_int(self):
        self.assertEqual(_as_int(42, 0), 42)

    def test_valid_string_int(self):
        self.assertEqual(_as_int("7", 0), 7)

    def test_invalid_returns_default(self):
        self.assertEqual(_as_int("bad", 5), 5)


class InlineMaxBytesTests(unittest.TestCase):
    def _make_settings(self, inline_audio_max_mb):
        return PipelineSettings(
            model="gemini-2.5-flash",
            fallback_models=[],
            effective_model="gemini-2.5-flash",
            chunk_minutes=15,
            overlap_seconds=30,
            macro_char_limit=22000,
            preconvert_audio=True,
            audio_bitrate="48k",
            prefetch_next_chunk=True,
            inline_audio_max_mb=inline_audio_max_mb,
        )

    def test_zero_returns_none(self):
        s = self._make_settings(0.0)
        self.assertIsNone(s.inline_max_bytes)

    def test_negative_returns_none(self):
        s = self._make_settings(-1.0)
        self.assertIsNone(s.inline_max_bytes)

    def test_positive_returns_bytes(self):
        s = self._make_settings(6.0)
        self.assertEqual(s.inline_max_bytes, int(6.0 * 1024 * 1024))

    def test_chunk_seconds_property(self):
        s = self._make_settings(0.0)
        self.assertEqual(s.chunk_seconds, 15 * 60)

    def test_step_seconds_property(self):
        s = self._make_settings(0.0)
        self.assertEqual(s.step_seconds, 15 * 60 - 30)


class LoadAndSanitizeSettingsTests(unittest.TestCase):
    def _base_session(self, **overrides):
        s = {
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
        s.update(overrides)
        return {"settings": s}

    def test_missing_settings_key_creates_defaults(self):
        session = {}
        _settings, changed = load_and_sanitize_settings(session)
        self.assertTrue(changed)
        self.assertIsInstance(session["settings"], dict)

    def test_settings_not_a_dict_is_replaced(self):
        session = {"settings": "garbage"}
        _settings, changed = load_and_sanitize_settings(session)
        self.assertTrue(changed)
        self.assertIsInstance(session["settings"], dict)

    def test_chunk_minutes_below_1_clamped_to_default(self):
        session = self._base_session(chunk_minutes=0)
        settings, _ = load_and_sanitize_settings(session)
        self.assertGreaterEqual(settings.chunk_minutes, 1)

    def test_chunk_minutes_above_180_clamped_to_180(self):
        session = self._base_session(chunk_minutes=999)
        settings, _ = load_and_sanitize_settings(session)
        self.assertEqual(settings.chunk_minutes, 180)

    def test_overlap_above_max_clamped(self):
        session = self._base_session(chunk_minutes=1, overlap_seconds=99999)
        settings, _ = load_and_sanitize_settings(session)
        self.assertLessEqual(settings.overlap_seconds, settings.chunk_seconds - 1)

    def test_overlap_negative_clamped_to_zero(self):
        session = self._base_session(overlap_seconds=-10)
        settings, _ = load_and_sanitize_settings(session)
        self.assertEqual(settings.overlap_seconds, 0)

    def test_macro_char_limit_below_6000_clamped(self):
        session = self._base_session(macro_char_limit=100)
        settings, _ = load_and_sanitize_settings(session)
        self.assertEqual(settings.macro_char_limit, 6000)

    def test_macro_char_limit_above_90000_clamped(self):
        session = self._base_session(macro_char_limit=200000)
        settings, _ = load_and_sanitize_settings(session)
        self.assertEqual(settings.macro_char_limit, 90000)

    def test_inline_audio_below_0_clamped(self):
        session = self._base_session(inline_audio_max_mb=-5.0)
        settings, _ = load_and_sanitize_settings(session)
        self.assertEqual(settings.inline_audio_max_mb, 0.0)

    def test_inline_audio_above_25_clamped(self):
        session = self._base_session(inline_audio_max_mb=100.0)
        settings, _ = load_and_sanitize_settings(session)
        self.assertEqual(settings.inline_audio_max_mb, 25.0)

    def test_effective_model_reset_when_not_in_fallbacks(self):
        session = self._base_session(
            model="gemini-2.5-flash",
            fallback_models=[],
            effective_model="gemini-3.6-flash",
        )
        settings, _ = load_and_sanitize_settings(session)
        self.assertEqual(settings.effective_model, "gemini-2.5-flash")

    def test_effective_model_kept_when_in_fallbacks(self):
        session = self._base_session(
            model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
            effective_model="gemini-3.6-flash",
        )
        settings, _ = load_and_sanitize_settings(session)
        self.assertEqual(settings.effective_model, "gemini-3.6-flash")

    def test_macro_22000_clamped_down_for_flash_lite_preview(self):
        session = self._base_session(
            model="gemini-3.6-flash",
            effective_model="gemini-3.6-flash",
            macro_char_limit=22000,
        )
        with patch(
            "jot.pipeline.pipeline_settings.default_macro_char_limit_for_model",
            return_value=7500,
        ):
            settings, _ = load_and_sanitize_settings(session)
            self.assertLess(settings.macro_char_limit, 22000)

    def test_audio_dict_missing_creates_with_default_bitrate(self):
        session = {"settings": {"model": "gemini-2.5-flash"}}
        session["settings"].pop("audio", None)
        settings, changed = load_and_sanitize_settings(session)
        self.assertTrue(changed)
        self.assertEqual(settings.audio_bitrate, "48k")

    def test_no_change_when_all_values_already_canonical(self):
        from jot.core.model_registry import (
            default_chunk_minutes_for_model,
            default_macro_char_limit_for_model,
        )

        model = "gemini-2.5-flash"
        session = {
            "settings": {
                "model": model,
                "fallback_models": [],
                "effective_model": model,
                "chunk_minutes": default_chunk_minutes_for_model(model),
                "overlap_seconds": 30,
                "macro_char_limit": default_macro_char_limit_for_model(model),
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }
        }
        _, changed = load_and_sanitize_settings(session)
        self.assertFalse(changed)


class BuildDefaultPipelineSettingsTests(unittest.TestCase):
    def test_returns_dict_with_required_keys(self):
        result = build_default_pipeline_settings(
            {"preferred_model": "gemini-2.5-flash"}
        )
        for key in (
            "model",
            "fallback_models",
            "effective_model",
            "chunk_minutes",
            "audio",
        ):
            self.assertIn(key, result)

    def test_fallback_models_default_to_empty_when_not_configured(self):
        result = build_default_pipeline_settings(
            {"preferred_model": "gemini-2.5-flash"}
        )
        self.assertEqual(result["fallback_models"], [])

    def test_inline_max_bytes_invalid_value(self):
        from jot.pipeline.pipeline_settings import PipelineSettings

        settings = PipelineSettings(
            model="gemini-2.5-flash",
            fallback_models=[],
            effective_model="gemini-2.5-flash",
            chunk_minutes=10,
            overlap_seconds=30,
            macro_char_limit=10000,
            preconvert_audio=True,
            audio_bitrate="48k",
            prefetch_next_chunk=True,
            inline_audio_max_mb=cast(Any, "invalid_mb"),
        )
        self.assertIsNone(settings.inline_max_bytes)

    def test_loads_from_system_config_when_none_passed(self):
        fake_cfg = {"preferred_model": "gemini-2.5-flash", "fallback_models": []}
        with patch(
            "jot.pipeline.pipeline_settings.load_config",
            return_value=fake_cfg,
        ):
            result = build_default_pipeline_settings(None)
        self.assertEqual(result["model"], "gemini-2.5-flash")

    def test_loads_from_system_config_when_non_dict_passed(self):
        fake_cfg = {"preferred_model": "gemini-2.5-flash", "fallback_models": []}
        with patch(
            "jot.pipeline.pipeline_settings.load_config",
            return_value=fake_cfg,
        ):
            result = build_default_pipeline_settings("not a dict")  # type: ignore[arg-type]
        self.assertEqual(result["model"], "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
