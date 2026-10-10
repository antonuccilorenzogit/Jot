import unittest
from unittest.mock import patch

from jot.core.model_registry import (
    DEFAULT_FALLBACK_MODELS,
    DEFAULT_MODEL,
    MODEL_OPTIONS,
    SUPPORTED_MODELS,
    build_model_state,
    default_chunk_minutes_for_model,
    default_macro_char_limit_for_model,
    sanitize_fallback_models,
)
from jot.pipeline.pipeline_settings import load_and_sanitize_settings


class ResumeModelStateTests(unittest.TestCase):
    def test_resume_without_effective_starts_from_primary(self):
        """Resume with no effective_model → current = primary."""
        ms = build_model_state("gemini-2.5-flash", ["gemini-3.6-flash"])
        self.assertEqual(ms.current, "gemini-2.5-flash")

    def test_resume_ignores_stale_effective_model(self):
        """Pipeline no longer passes effective_model at resume; chain and primary are correct."""
        ms = build_model_state("gemini-2.5-flash", ["gemini-3.6-flash"])
        self.assertEqual(ms.current, "gemini-2.5-flash")
        self.assertEqual(ms.chain, ("gemini-2.5-flash", "gemini-3.6-flash"))

    def test_chain_preserved_for_fallback_on_503(self):
        """Fallback chain is still intact so retry_with_quota can degrade if needed."""
        ms = build_model_state("gemini-2.5-flash", ["gemini-3.6-flash"])
        self.assertIn("gemini-3.6-flash", ms.chain)


class SupportedModelsTests(unittest.TestCase):
    def test_gemini_25_flash_in_supported_models(self):
        self.assertIn("gemini-2.5-flash", SUPPORTED_MODELS)

    def test_removed_models_not_in_supported_models(self):
        for removed in (
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-3.5-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
        ):
            self.assertNotIn(
                removed, SUPPORTED_MODELS, f"{removed} should have been removed"
            )

    def test_gemini_35_flash_in_supported_models(self):
        self.assertIn("gemini-3.5-flash", SUPPORTED_MODELS)

    def test_gemini_37_flash_in_supported_models(self):
        self.assertIn("gemini-3.7-flash", SUPPORTED_MODELS)

    def test_gemini_38_flash_in_supported_models(self):
        self.assertIn("gemini-3.8-flash", SUPPORTED_MODELS)

    def test_gemini_36_flash_in_supported_models(self):
        self.assertIn("gemini-3.6-flash", SUPPORTED_MODELS)

    def test_gemini_15_flash_not_in_supported_models(self):
        self.assertNotIn("gemini-1.5-flash", SUPPORTED_MODELS)

    def test_no_default_fallback_models(self):
        self.assertEqual(DEFAULT_FALLBACK_MODELS, ())

    def test_current_fallbacks_accepted_by_sanitize_fallback_models(self):
        result = sanitize_fallback_models(
            ["gemini-3.6-flash", "gemini-3.7-flash"],
            primary_model="gemini-2.5-flash",
        )
        self.assertEqual(
            result,
            ["gemini-3.6-flash", "gemini-3.7-flash"],
        )

    def test_removed_models_filtered_by_sanitize_fallback_models(self):
        result = sanitize_fallback_models(
            ["gemini-2.0-flash", "gemini-3.6-flash", "gemini-2.5-pro"],
            primary_model="gemini-2.5-flash",
        )
        self.assertEqual(result, ["gemini-3.6-flash"])

    def test_removed_models_migrate_to_default_and_are_dropped_from_fallbacks(self):
        removed_models = (
            "gemini-2.5-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
        )
        for removed in removed_models:
            with self.subTest(model=removed):
                session = {
                    "settings": {
                        "model": removed,
                        "effective_model": removed,
                        "fallback_models": [removed, "gemini-3.6-flash"],
                        "audio": {"bitrate": "48k"},
                    }
                }

                settings, changed = load_and_sanitize_settings(session)

                self.assertTrue(changed)
                self.assertEqual(settings.model, DEFAULT_MODEL)
                self.assertEqual(settings.effective_model, DEFAULT_MODEL)
                self.assertEqual(settings.fallback_models, ["gemini-3.6-flash"])

    def test_chain_with_current_default_fallbacks(self):
        ms = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash", "gemini-3.7-flash"],
        )
        self.assertEqual(
            ms.chain,
            (
                "gemini-2.5-flash",
                "gemini-3.6-flash",
                "gemini-3.7-flash",
            ),
        )
        self.assertEqual(ms.current, "gemini-2.5-flash")

    def test_unsupported_primary_falls_back_to_default(self):
        ms = build_model_state("gemini-2.5-pro", ["gemini-2.5-flash"])
        self.assertEqual(ms.current, DEFAULT_MODEL)
        self.assertIn("gemini-2.5-flash", ms.chain)


class DefaultChunkMinutesTests(unittest.TestCase):
    def test_known_models_match_model_options(self):
        for opt in MODEL_OPTIONS:
            expected = int(opt["default_chunk_minutes"])
            got = default_chunk_minutes_for_model(opt["id"])
            self.assertEqual(
                got,
                expected,
                msg=f"model {opt['id']!r}: expected {expected}, got {got}",
            )

    def test_unknown_model_falls_back_to_15(self):
        result = default_chunk_minutes_for_model("gemini-unknown-model")
        self.assertEqual(result, 15)

    def test_derives_from_model_options_not_hardcoded(self):
        patched = tuple(
            {**opt, "default_chunk_minutes": 42}
            if opt["id"] == "gemini-3.5-flash"
            else opt
            for opt in MODEL_OPTIONS
        )
        with patch("jot.core.model_registry.MODEL_OPTIONS", patched):
            result = default_chunk_minutes_for_model("gemini-3.5-flash")
        self.assertEqual(result, 42)


class DefaultMacroCharLimitTests(unittest.TestCase):
    def test_known_models_match_model_options(self):
        for opt in MODEL_OPTIONS:
            expected = int(opt["default_macro_char_limit"])
            got = default_macro_char_limit_for_model(opt["id"])
            self.assertEqual(
                got,
                expected,
                msg=f"model {opt['id']!r}: expected {expected}, got {got}",
            )

    def test_flash_35_returns_22000(self):
        result = default_macro_char_limit_for_model("gemini-3.5-flash")
        self.assertEqual(result, 22000)

    def test_unknown_model_falls_back_to_22000(self):
        result = default_macro_char_limit_for_model("gemini-unknown-model")
        self.assertEqual(result, 22000)

    def test_load_and_sanitize_defaults_macro_from_model_when_missing(self):
        session = {
            "settings": {
                "model": "gemini-3.5-flash",
                "fallback_models": [],
                "effective_model": "gemini-3.5-flash",
                "audio": {"bitrate": "48k"},
            }
        }
        settings, changed = load_and_sanitize_settings(session)
        self.assertEqual(settings.macro_char_limit, 22000)
        self.assertEqual(session["settings"]["macro_char_limit"], 22000)
        self.assertTrue(changed)

    def test_load_and_sanitize_uses_model_macro_char_limit(self):
        patched = tuple(
            {**opt, "default_macro_char_limit": 7500}
            if opt["id"] == "gemini-3.5-flash"
            else opt
            for opt in MODEL_OPTIONS
        )
        session = {
            "settings": {
                "model": "gemini-3.5-flash",
                "fallback_models": [],
                "effective_model": "gemini-3.5-flash",
                "chunk_minutes": 5,
                "overlap_seconds": 30,
                "macro_char_limit": 22000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }
        }
        with patch("jot.core.model_registry.MODEL_OPTIONS", patched):
            settings, changed = load_and_sanitize_settings(session)
            self.assertEqual(settings.macro_char_limit, 7500)
            self.assertEqual(session["settings"]["macro_char_limit"], 7500)
            self.assertTrue(changed)

    def test_load_and_sanitize_preserves_explicit_non_default_macro_char_limit(self):
        session = {
            "settings": {
                "model": "gemini-3.5-flash",
                "fallback_models": [],
                "effective_model": "gemini-3.5-flash",
                "chunk_minutes": 5,
                "overlap_seconds": 30,
                "macro_char_limit": 10000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }
        }
        settings, _changed = load_and_sanitize_settings(session)
        self.assertEqual(settings.macro_char_limit, 10000)


if __name__ == "__main__":
    unittest.main()
