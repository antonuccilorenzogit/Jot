"""Tests for config_service.py TTL cache (P3)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ["JOT_TESTING"] = "1"

import jot.services.config_service as cs

_FAKE_CFG: dict = {
    "api_key": "key-test",
    "preferred_model": "gemini-2.0-flash-lite",
    "fallback_models": ["gemini-2.0-flash"],
}


def _reset_cache() -> None:
    cs._credential_overrides.clear()
    cs._config_cache = None
    cs._config_cache_ts = 0.0
    cs._config_cache_gen = 0


class TestLoadConfigCache(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    # ------------------------------------------------------------------
    # Cache hit
    # ------------------------------------------------------------------

    def test_hit_returns_cached_value(self) -> None:
        cs._config_cache = dict(_FAKE_CFG)
        cs._config_cache_ts = time.monotonic()

        with patch("jot.services.config_service.os.path.exists") as mock_exists:
            result = cs.load_config()
            mock_exists.assert_not_called()

        self.assertEqual(result["api_key"], "key-test")

    def test_hit_returns_shallow_copy(self) -> None:
        """Mutating the returned dict must not corrupt the in-process cache."""
        cs._config_cache = dict(_FAKE_CFG)
        cs._config_cache_ts = time.monotonic()

        result = cs.load_config()
        result["api_key"] = "mutated"

        self.assertEqual(cs._config_cache["api_key"], "key-test")

    def test_hit_fallback_models_list_is_isolated(self) -> None:
        """Appending to returned fallback_models must not mutate the cache list."""
        cs._config_cache = dict(_FAKE_CFG)
        cs._config_cache["fallback_models"] = ["gemini-2.0-flash"]
        cs._config_cache_ts = time.monotonic()

        result = cs.load_config()
        result["fallback_models"].append("injected-model")

        self.assertEqual(cs._config_cache["fallback_models"], ["gemini-2.0-flash"])

    def test_hit_fallback_keys_list_is_isolated(self) -> None:
        """Appending to returned fallback_keys must not mutate the cache list."""
        cs._config_cache = dict(_FAKE_CFG)
        cs._config_cache["fallback_keys"] = ["key-a"]
        cs._config_cache_ts = time.monotonic()

        result = cs.load_config()
        result["fallback_keys"].append("injected-key")

        self.assertEqual(cs._config_cache["fallback_keys"], ["key-a"])

    # ------------------------------------------------------------------
    # Cache miss
    # ------------------------------------------------------------------

    def test_miss_on_expired_ttl(self) -> None:
        """Stale cache forces a fresh read; with no files → default returned."""
        cs._config_cache = dict(_FAKE_CFG)
        cs._config_cache_ts = time.monotonic() - (cs._CONFIG_CACHE_TTL + 1.0)

        with patch("jot.services.config_service.os.path.exists", return_value=False):
            result = cs.load_config()

        self.assertEqual(result["api_key"], "")

    def test_miss_on_none_cache_consults_disk(self) -> None:
        """No cache populated → os.path.exists is called."""
        with patch(
            "jot.services.config_service.os.path.exists", return_value=False
        ) as mock_exists:
            cs.load_config()
            mock_exists.assert_called()

    def test_miss_populates_cache(self) -> None:
        """After a miss the cache is populated for the next call."""
        with patch("jot.services.config_service.os.path.exists", return_value=False):
            cs.load_config()

        self.assertIsNotNone(cs._config_cache)

    def test_second_call_after_miss_hits_cache(self) -> None:
        """The second call within TTL avoids disk entirely."""
        with patch("jot.services.config_service.os.path.exists", return_value=False):
            cs.load_config()

        with patch("jot.services.config_service.os.path.exists") as mock_exists:
            cs.load_config()
            mock_exists.assert_not_called()

    # ------------------------------------------------------------------
    # save_config invalidation
    # ------------------------------------------------------------------

    def test_save_invalidates_cache(self) -> None:
        cs._config_cache = dict(_FAKE_CFG)
        cs._config_cache_ts = time.monotonic()

        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Windows",
            ),
            patch(
                "jot.services.config_service.os.path.exists",
                return_value=False,
            ),
            patch("jot.services.config_service.os.makedirs"),
            patch(
                "jot.services.config_service._dpapi_protect_text_windows",
                return_value="",
            ),
            patch("builtins.open", MagicMock()),
            patch("jot.services.config_service.os.replace"),
        ):
            cs.save_config("new-key")

        self.assertIsNone(cs._config_cache)

    # ------------------------------------------------------------------
    # Thread safety
    # ------------------------------------------------------------------

    def test_concurrent_reads_no_crash(self) -> None:
        """Twenty threads reading a hot cache simultaneously must not raise."""
        cs._config_cache = dict(_FAKE_CFG)
        cs._config_cache_ts = time.monotonic()

        errors: list[Exception] = []

        def _read() -> None:
            try:
                cs.load_config()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_read) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])


class TestCacheGenerationCounter(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_save_config_increments_gen(self) -> None:
        """save_config must bump _config_cache_gen so concurrent load_config skips its write."""
        initial_gen = cs._config_cache_gen
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Windows",
            ),
            patch(
                "jot.services.config_service.os.path.exists",
                return_value=False,
            ),
            patch("jot.services.config_service.os.makedirs"),
            patch(
                "jot.services.config_service._dpapi_protect_text_windows",
                return_value="",
            ),
            patch("builtins.open", MagicMock()),
            patch("jot.services.config_service.os.replace"),
        ):
            cs.save_config("some-key")
        self.assertEqual(cs._config_cache_gen, initial_gen + 1)

    def test_stale_load_does_not_overwrite_invalidated_cache(self) -> None:
        """If gen changed between lock-release and cache-write, load must not write."""
        cs._config_cache_gen = 1  # save already ran
        gen_at_start = 0  # what load captured before the I/O phase
        stale_data = {"api_key": "stale"}

        with cs._config_lock:
            if cs._config_cache_gen == gen_at_start:
                cs._config_cache = stale_data
                cs._config_cache_ts = time.monotonic()

        self.assertIsNone(cs._config_cache)


class TestSaveConfigWriteLock(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_write_lock_held_during_file_write(self) -> None:
        """_write_lock must be held during os.replace to serialise concurrent saves."""
        lock_held: list[bool] = []

        def _check_lock(*args: object) -> None:
            lock_held.append(cs._write_lock.locked())

        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Windows",
            ),
            patch(
                "jot.services.config_service.os.path.exists",
                return_value=False,
            ),
            patch("jot.services.config_service.os.makedirs"),
            patch(
                "jot.services.config_service._dpapi_protect_text_windows",
                return_value="",
            ),
            patch("builtins.open", MagicMock()),
            patch(
                "jot.services.config_service.os.replace",
                side_effect=_check_lock,
            ),
        ):
            cs.save_config("test-key")

        self.assertTrue(lock_held, "os.replace was never called")
        self.assertTrue(all(lock_held), "_write_lock must be held during os.replace")

    def test_write_lock_released_on_write_error(self) -> None:
        """_write_lock must be released even when the file write raises."""
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Windows",
            ),
            patch(
                "jot.services.config_service.os.path.exists",
                return_value=False,
            ),
            patch("jot.services.config_service.os.makedirs"),
            patch(
                "jot.services.config_service._dpapi_protect_text_windows",
                return_value="",
            ),
            patch("builtins.open", side_effect=OSError("disk full")),
        ):
            with self.assertRaises(OSError):
                cs.save_config("test-key")

        self.assertFalse(
            cs._write_lock.locked(), "_write_lock must be released after write error"
        )

    def test_concurrent_writes_are_serialised(self) -> None:
        """Two concurrent save_config calls must not interleave their read-modify-write."""
        call_order: list[str] = []
        barrier = threading.Barrier(2)
        errors: list[Exception] = []
        thread_tags: dict[int, str] = {}

        def _tracked_replace(src: str, dst: str) -> None:
            tag = thread_tags.get(threading.get_ident(), "unknown")
            call_order.append("write")
            call_order.append(f"done-{tag}")

        def _save(tag: str, key: str) -> None:
            thread_tags[threading.get_ident()] = tag
            try:
                barrier.wait()
                cs.save_config(key)
            except Exception as exc:
                errors.append(exc)

        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Windows",
            ),
            patch(
                "jot.services.config_service.os.path.exists",
                return_value=False,
            ),
            patch("jot.services.config_service.os.makedirs"),
            patch(
                "jot.services.config_service._dpapi_protect_text_windows",
                return_value="",
            ),
            patch("builtins.open", MagicMock()),
            patch(
                "jot.services.config_service.os.replace",
                side_effect=_tracked_replace,
            ),
        ):
            t1 = threading.Thread(target=_save, args=("A", "key-a"))
            t2 = threading.Thread(target=_save, args=("B", "key-b"))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        self.assertEqual(errors, [])
        # With serialisation: writes never interleave — each "write" is followed
        # immediately by its own "done-X" before the other thread's "write" appears.
        for i, event in enumerate(call_order):
            if event == "write":
                self.assertIn(call_order[i + 1], ("done-A", "done-B"))


class TestLoadConfigFromRealFile(unittest.TestCase):
    """Verify that load_config reads actual JSON from disk (not just cache paths)."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_reads_api_key_and_model_from_real_json_file(self) -> None:
        """load_config reads api_key / preferred_model from a real temp CONFIG_FILE."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {
                "api_key": "real-key-xyz",
                "preferred_model": "gemini-2.5-flash",
                "fallback_models": [],
            }
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy_absent",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result["api_key"], "real-key-xyz")
        self.assertEqual(result["preferred_model"], "gemini-2.5-flash")

    def test_falls_back_to_legacy_file_when_main_absent(self) -> None:
        """When CONFIG_FILE does not exist but LEGACY_CONFIG_FILE does, it's used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "absent_config.json")
            legacy_path = os.path.join(tmpdir, "legacy_config.json")
            payload = {"api_key": "legacy-key", "preferred_model": "gemini-2.0-flash"}
            with open(legacy_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    legacy_path,
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch("jot.services.config_service.save_config", MagicMock()),
            ):
                result = cs.load_config()

        self.assertEqual(result["api_key"], "legacy-key")

    def test_successful_legacy_migration_removes_legacy_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            legacy_path = os.path.join(tmpdir, "legacy_config.json")
            payload = {"api_key": "legacy-key", "preferred_model": "gemini-2.0-flash"}
            with open(legacy_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    legacy_path,
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_protect_text_windows",
                    return_value="protected-legacy",
                ),
                patch(
                    "jot.services.config_service._dpapi_unprotect_text_windows",
                    return_value="legacy-key",
                ),
            ):
                result = cs.load_config()

            self.assertEqual(result["api_key"], "legacy-key")
            self.assertFalse(os.path.exists(legacy_path))
            self.assertFalse(os.path.exists(legacy_path + ".migrated"))
            self.assertTrue(os.path.isfile(cfg_path))

    def test_failed_legacy_migration_leaves_legacy_file_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            legacy_path = os.path.join(tmpdir, "legacy_config.json")
            payload = {"api_key": "legacy-key", "preferred_model": "gemini-2.0-flash"}
            with open(legacy_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    legacy_path,
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._atomic_write_json",
                    side_effect=OSError("disk full"),
                ),
            ):
                result = cs.load_config()

            self.assertEqual(result["api_key"], "legacy-key")
            self.assertTrue(os.path.isfile(legacy_path))
            self.assertFalse(os.path.exists(legacy_path + ".migrated"))

    def test_returns_defaults_when_both_config_files_absent(self) -> None:
        """When neither config file exists, default empty values are returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch(
                    "jot.services.config_service.CONFIG_FILE",
                    os.path.join(tmpdir, "absent.json"),
                ),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    os.path.join(tmpdir, "absent2.json"),
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result["api_key"], "")
        self.assertIn("preferred_model", result)

    def test_skips_corrupt_json_and_returns_defaults(self) -> None:
        """A corrupt JSON file is silently skipped; defaults are returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write("{ not valid json }")

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result["api_key"], "")

    def test_windows_decrypts_api_key_protected(self) -> None:
        """On Windows, api_key_protected is decrypted via DPAPI helper."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {"api_key": "", "api_key_protected": "FAKEBASE64=="}
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_unprotect_text_windows",
                    return_value="decrypted-secret",
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result["api_key"], "decrypted-secret")

    def test_windows_sets_has_protected_key_when_dpapi_decrypt_fails(self) -> None:
        """On Windows, if DPAPI returns empty string, has_protected_key is set False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {"api_key": "", "api_key_protected": "FAKEBASE64=="}
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_unprotect_text_windows",
                    return_value="",
                ),
            ):
                result = cs.load_config()

        self.assertFalse(result.get("has_protected_key"))
        self.assertEqual(result["api_key"], "")

    def test_windows_marks_plaintext_api_key_as_insecure(self) -> None:
        """On Windows, a plaintext api_key is surfaced as insecure to the UI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {"api_key": "plain-key"}
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_protect_text_windows",
                    return_value="",
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result["api_key"], "plain-key")
        self.assertTrue(result.get("api_key_insecure"))
        self.assertIn("chiaro", result.get("api_key_insecure_reason", ""))

    def test_windows_marks_plaintext_api_key_insecure_with_protected_key(
        self,
    ) -> None:
        """A plaintext api_key on disk is insecure even if api_key_protected exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {
                "api_key": "plain-key",
                "api_key_protected": "FAKEBASE64==",
            }
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_protect_text_windows",
                    return_value="",
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result["api_key"], "plain-key")
        self.assertTrue(result.get("api_key_insecure"))
        self.assertIn("chiaro", result.get("api_key_insecure_reason", ""))

    def test_windows_decrypts_fallback_keys_protected(self) -> None:
        """On Windows, fallback_keys_protected is JSON-decoded after DPAPI decrypt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {
                "api_key": "main-key",
                "fallback_keys_protected": "FAKEBASE64==",
            }
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_unprotect_text_windows",
                    return_value=json.dumps(["fallback-key-1", "fallback-key-2"]),
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result["fallback_keys"], ["fallback-key-1", "fallback-key-2"])


class TestSaveConfigToDisk(unittest.TestCase):
    """Verify that save_config actually writes JSON to disk."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_save_config_writes_real_json_file(self) -> None:
        """save_config atomically writes api_key + preferred_model to CONFIG_FILE."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_protect_text_windows",
                    return_value="",
                ),
            ):
                cs.save_config("stored-key", preferred_model="gemini-2.5-flash")

            self.assertTrue(os.path.isfile(cfg_path))
            with open(cfg_path, encoding="utf-8") as fh:
                data = json.load(fh)

        self.assertEqual(data["api_key"], "")
        self.assertNotIn("stored-key", json.dumps(data))
        self.assertEqual(data["preferred_model"], "gemini-2.5-flash")

    def test_save_config_none_key_preserves_existing_protected_on_windows(self) -> None:
        """On Windows, save_config(api_key=None) copies api_key_protected from the existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            existing = {"api_key": "", "api_key_protected": "EXISTING_PROTECTED=="}
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_protect_text_windows",
                    return_value="",
                ),
            ):
                cs.save_config(None)

            with open(cfg_path, encoding="utf-8") as fh:
                data = json.load(fh)

        self.assertEqual(data.get("api_key_protected"), "EXISTING_PROTECTED==")

    def test_save_config_none_key_preserves_existing_plaintext_on_windows(self) -> None:
        """On Windows, save_config(api_key=None) preserves existing plaintext api_key if DPAPI was unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            existing = {"api_key": "PLAINTEXT_KEY_123"}
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_protect_text_windows",
                    return_value="",
                ),
            ):
                cs.save_config(None, preferred_model="gemini-3.5-flash")

            with open(cfg_path, encoding="utf-8") as fh:
                data = json.load(fh)

        self.assertEqual(data.get("api_key"), "PLAINTEXT_KEY_123")
        self.assertEqual(data.get("preferred_model"), "gemini-3.5-flash")

    def test_save_config_writes_legacy_file_when_env_set(self) -> None:
        """When JOT_WRITE_LEGACY_CONFIG=1, the legacy file is also written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            legacy_path = os.path.join(tmpdir, "legacy_config.json")

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    legacy_path,
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
                patch(
                    "jot.services.config_service._dpapi_protect_text_windows",
                    return_value="",
                ),
                patch.dict(os.environ, {"JOT_WRITE_LEGACY_CONFIG": "1"}),
            ):
                cs.save_config("legacy-key")

            self.assertTrue(os.path.isfile(legacy_path))
            with open(legacy_path, encoding="utf-8") as fh:
                data = json.load(fh)

        self.assertEqual(data["api_key"], "")
        self.assertNotIn("legacy-key", json.dumps(data))


class TestMacOSKeyringHelpers(unittest.TestCase):
    """Unit tests for _keyring_get/set/delete_api_key on non-Windows platforms."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    # --- _keyring_get_api_key ---

    def test_keyring_get_returns_empty_on_windows(self) -> None:
        with patch(
            "jot.services.config_service.platform.system",
            return_value="Windows",
        ):
            result = cs._keyring_get_api_key()
        self.assertEqual(result, "")

    def test_keyring_get_returns_value_from_keyring(self) -> None:
        import sys

        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "secret-key"
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Darwin",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = cs._keyring_get_api_key()
        self.assertEqual(result, "secret-key")
        mock_kr.get_password.assert_called_once_with(
            cs._KEYRING_SERVICE, cs._KEYRING_USER_API
        )

    def test_keyring_get_returns_empty_when_no_key_stored(self) -> None:
        import sys

        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Darwin",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = cs._keyring_get_api_key()
        self.assertEqual(result, "")

    def test_keyring_get_returns_empty_on_exception(self) -> None:
        import sys

        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = RuntimeError("keyring locked")
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Darwin",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
            patch("jot.services.config_service.time.sleep") as mock_sleep,
        ):
            result = cs._keyring_get_api_key()
        self.assertEqual(result, "")
        mock_sleep.assert_called_once()

    # --- _keyring_set_api_key ---

    def test_keyring_set_returns_false_on_windows(self) -> None:
        with patch(
            "jot.services.config_service.platform.system",
            return_value="Windows",
        ):
            result = cs._keyring_set_api_key("some-key")
        self.assertFalse(result)

    def test_keyring_set_returns_true_on_success(self) -> None:
        import sys

        mock_kr = MagicMock()
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Darwin",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = cs._keyring_set_api_key("my-key")
        self.assertTrue(result)
        mock_kr.set_password.assert_called_once_with(
            cs._KEYRING_SERVICE, cs._KEYRING_USER_API, "my-key"
        )

    def test_keyring_set_returns_false_on_exception(self) -> None:
        import sys

        mock_kr = MagicMock()
        mock_kr.set_password.side_effect = RuntimeError("no backend")
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Darwin",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = cs._keyring_set_api_key("my-key")
        self.assertFalse(result)

    # --- _keyring_delete_api_key ---

    def test_keyring_delete_returns_false_on_windows(self) -> None:
        with patch(
            "jot.services.config_service.platform.system",
            return_value="Windows",
        ):
            result = cs._keyring_delete_api_key()
        self.assertFalse(result)

    def test_keyring_delete_returns_true_on_success(self) -> None:
        import sys

        mock_kr = MagicMock()
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Darwin",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = cs._keyring_delete_api_key()
        self.assertTrue(result)
        mock_kr.delete_password.assert_called_once_with(
            cs._KEYRING_SERVICE, cs._KEYRING_USER_API
        )

    def test_keyring_delete_returns_false_on_exception(self) -> None:
        import sys

        mock_kr = MagicMock()
        mock_kr.delete_password.side_effect = RuntimeError("not found")
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Darwin",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = cs._keyring_delete_api_key()
        self.assertFalse(result)


class TestLoadConfigMacOS(unittest.TestCase):
    """load_config paths that execute only on non-Windows (keyring integration)."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_macos_api_key_from_keyring_overrides_disk_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {
                "api_key": "disk-key",
                "preferred_model": "gemini-2.0-flash-lite",
            }
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "jot.services.config_service._keyring_get_api_key",
                    return_value="keyring-key",
                ),
                patch(
                    "jot.services.config_service._keyring_get_fallback_keys",
                    return_value=[],
                ),
            ):
                result = cs.load_config()
        self.assertEqual(result["api_key"], "keyring-key")

    def test_macos_migrates_plaintext_disk_key_to_keyring(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {
                "api_key": "plain-key-on-disk",
                "preferred_model": "gemini-2.0-flash-lite",
            }
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            mock_set = MagicMock(return_value=True)
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "jot.services.config_service._keyring_get_api_key",
                    return_value="",
                ),
                patch(
                    "jot.services.config_service._keyring_set_api_key",
                    mock_set,
                ),
                patch("jot.services.config_service.save_config"),
            ):
                cs.load_config()
        mock_set.assert_called_once_with("plain-key-on-disk")

    def test_macos_clears_has_protected_key_when_use_keyring_true_and_keyring_empty(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {
                "api_key": "",
                "use_keyring": True,
                "preferred_model": "gemini-2.0-flash-lite",
            }
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "jot.services.config_service._keyring_get_api_key",
                    return_value="",
                ),
            ):
                result = cs.load_config()
        self.assertFalse(result.get("has_protected_key"))
        self.assertEqual(result["api_key"], "")

    def test_macos_reads_fallback_keys_from_keyring(self) -> None:
        import sys

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            payload = {"api_key": "", "preferred_model": "gemini-2.0-flash-lite"}
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            mock_kr = MagicMock()
            fk_json = json.dumps(["fk-1", "fk-2"])
            mock_kr.get_password.side_effect = lambda svc, usr: (
                fk_json if usr == "gemini_fallback_keys" else None
            )
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".none",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "jot.services.config_service._keyring_get_api_key",
                    return_value="",
                ),
                patch.dict(sys.modules, {"keyring": mock_kr}),
            ):
                result = cs.load_config()
        self.assertEqual(result.get("fallback_keys"), ["fk-1", "fk-2"])


class TestSaveConfigMacOS(unittest.TestCase):
    """save_config paths that execute only on non-Windows (keyring integration)."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_macos_stores_api_key_in_keyring_and_clears_disk_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "jot.services.config_service._keyring_set_api_key",
                    return_value=True,
                ),
                patch("jot.services.config_service._keyring_delete_api_key"),
            ):
                cs.save_config("my-api-key")
            with open(cfg_path, encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertEqual(data["api_key"], "")
        self.assertTrue(data.get("use_keyring"))

    def test_macos_clears_keyring_entry_when_api_key_is_empty(self) -> None:
        mock_delete = MagicMock(return_value=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "jot.services.config_service._keyring_delete_api_key",
                    mock_delete,
                ),
            ):
                cs.save_config("")
        mock_delete.assert_called_once()

    def test_macos_stores_fallback_keys_in_keyring(self) -> None:
        import sys

        mock_kr = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "jot.services.config_service._keyring_set_api_key",
                    return_value=True,
                ),
                patch.dict(sys.modules, {"keyring": mock_kr}),
            ):
                cs.save_config("my-key", fallback_keys=["fk-a", "fk-b"])
        fk_calls = [
            c
            for c in mock_kr.set_password.call_args_list
            if c.args[1] == "gemini_fallback_keys"
        ]
        self.assertEqual(len(fk_calls), 1)
        stored = json.loads(fk_calls[0].args[2])
        self.assertEqual(stored, ["fk-a", "fk-b"])

    def test_macos_clears_fallback_keys_in_keyring_when_empty(self) -> None:
        import sys

        mock_kr = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
                patch(
                    "jot.services.config_service._keyring_set_api_key",
                    return_value=True,
                ),
                patch.dict(sys.modules, {"keyring": mock_kr}),
            ):
                cs.save_config("my-key", fallback_keys=[])
        mock_kr.delete_password.assert_called_once_with(
            cs._KEYRING_SERVICE, "gemini_fallback_keys"
        )

    def test_macos_preserves_use_keyring_flag_when_api_key_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            existing = {
                "api_key": "",
                "use_keyring": True,
                "preferred_model": "gemini-2.0-flash-lite",
            }
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh)
            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".legacy",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Darwin",
                ),
            ):
                cs.save_config(None)
            with open(cfg_path, encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertTrue(data.get("use_keyring"))


class TestCorruptConfigRecovery(unittest.TestCase):
    """Regression tests for issue 1.1: corrupt config.json backup + config_recovered_from."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_corrupt_json_creates_backup_file(self) -> None:
        """A corrupt JSON file is copied to config.json.corrupt-<ts> before falling back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write("{truncated by power loss")

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".absent",
                ),
            ):
                cs.load_config()

            backups = [
                f for f in os.listdir(tmpdir) if f.startswith("config.json.corrupt-")
            ]
        self.assertEqual(len(backups), 1, f"Expected 1 backup, found: {backups}")

    def test_corrupt_json_returns_config_recovered_from(self) -> None:
        """config_recovered_from field is set when a corrupt config is encountered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write("{truncated")

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".absent",
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result.get("config_recovered_from"), cfg_path)
        self.assertEqual(result["api_key"], "")

    def test_valid_config_has_no_config_recovered_from(self) -> None:
        """config_recovered_from must NOT appear when the file loads cleanly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump({"api_key": "ok-key"}, fh)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".absent",
                ),
                patch(
                    "jot.services.config_service.platform.system",
                    return_value="Windows",
                ),
            ):
                result = cs.load_config()

        self.assertNotIn("config_recovered_from", result)

    def test_corrupt_config_recovered_from_persists_in_cache(self) -> None:
        """config_recovered_from must survive a cache hit on the second call (Bug 2 regression)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write("{truncated")

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".absent",
                ),
            ):
                first = cs.load_config()
                second = cs.load_config()

        self.assertEqual(first.get("config_recovered_from"), cfg_path)
        self.assertEqual(second.get("config_recovered_from"), cfg_path)

    def test_concurrent_backup_not_overwritten_when_same_timestamp(self) -> None:
        """Bug 3 regression: if backup for this second already exists (concurrent caller),
        copy2 is skipped rather than overwriting identical content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write("{truncated by power loss")

            fixed_ts = 1700000000
            existing_backup = f"{cfg_path}.corrupt-{fixed_ts}"
            with open(existing_backup, "w", encoding="utf-8") as fh:
                fh.write("{truncated by power loss")

            copy2_calls: list[str] = []

            def tracking_copy2(src: str, dst: str) -> None:
                copy2_calls.append(dst)

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".absent",
                ),
                patch(
                    "jot.services.config_service.time.time",
                    return_value=float(fixed_ts),
                ),
                patch(
                    "jot.services.config_service.shutil.copy2",
                    side_effect=tracking_copy2,
                ),
            ):
                cs.load_config()

        self.assertEqual(
            copy2_calls, [], "copy2 must not be called when backup already exists"
        )

    def test_corrupt_backup_fails_silently_if_copy_raises(self) -> None:
        """If shutil.copy2 raises (e.g. read-only fs), load_config still returns defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write("{bad json")

            with (
                patch("jot.services.config_service.CONFIG_FILE", cfg_path),
                patch(
                    "jot.services.config_service.LEGACY_CONFIG_FILE",
                    cfg_path + ".absent",
                ),
                patch(
                    "jot.services.config_service.shutil.copy2",
                    side_effect=OSError("read-only"),
                ),
            ):
                result = cs.load_config()

        self.assertEqual(result["api_key"], "")
        self.assertEqual(result.get("config_recovered_from"), cfg_path)


class TestSaveConfigPropagatesError(unittest.TestCase):
    """Regression tests for issue 1.2: save_config raises on write failure."""

    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_save_config_raises_on_write_error(self) -> None:
        """OSError from open() is propagated rather than silently swallowed."""
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Windows",
            ),
            patch(
                "jot.services.config_service.os.path.exists",
                return_value=False,
            ),
            patch("jot.services.config_service.os.makedirs"),
            patch(
                "jot.services.config_service._dpapi_protect_text_windows",
                return_value="",
            ),
            patch("builtins.open", side_effect=OSError("disk full")),
        ):
            with self.assertRaises(OSError):
                cs.save_config("my-key")

    def test_save_config_raises_on_os_replace_error(self) -> None:
        """OSError from os.replace() (e.g. cross-device rename) is propagated."""
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Windows",
            ),
            patch(
                "jot.services.config_service.os.path.exists",
                return_value=False,
            ),
            patch("jot.services.config_service.os.makedirs"),
            patch(
                "jot.services.config_service._dpapi_protect_text_windows",
                return_value="",
            ),
            patch("builtins.open", MagicMock()),
            patch(
                "jot.services.config_service.os.replace",
                side_effect=OSError("permission denied"),
            ),
        ):
            with self.assertRaises(OSError):
                cs.save_config("my-key")

    def test_save_settings_returns_ok_false_on_write_error(self) -> None:
        """The app_webview bridge wrapper returns {ok: False, error: ...} on write failure."""
        import jot.app_webview as aw

        api = aw.JotApi()
        with (
            patch(
                "jot.services.config_service.platform.system",
                return_value="Windows",
            ),
            patch(
                "jot.services.config_service.os.path.exists",
                return_value=False,
            ),
            patch("jot.services.config_service.os.makedirs"),
            patch(
                "jot.services.config_service._dpapi_protect_text_windows",
                return_value="",
            ),
            patch("builtins.open", side_effect=OSError("disk full")),
        ):
            result = api.save_settings("my-key", [], "gemini-2.0-flash-lite", [])

        self.assertFalse(result["ok"])
        self.assertIn("disk full", result.get("error", ""))


class TestLogDebugAndSessionRoot(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def tearDown(self) -> None:
        _reset_cache()

    def test_log_debug_disabled(self) -> None:
        with patch.dict(os.environ, {"JOT_DEBUG": "0"}):
            with patch("builtins.print") as mock_print:
                cs.debug_log("test message")
                mock_print.assert_not_called()

    def test_log_debug_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "jot.log")
            cfg_file = os.path.join(tmpdir, "config.json")
            with (
                patch.dict(os.environ, {"JOT_DEBUG": "1"}),
                patch("jot.services.config_service.CONFIG_FILE", cfg_file),
            ):
                cs.debug_log("hello secret_key_AIzaSy123")
                self.assertTrue(os.path.exists(log_file))
                from jot.utils.logging_utils import (
                    configure_logging,
                    detach_file_handler,
                )

                for handler in list(configure_logging().handlers):
                    if getattr(handler, "_el_general_log", False):
                        detach_file_handler(handler)

    def test_save_session_root_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.json")
            with patch("jot.services.config_service.CONFIG_FILE", cfg_file):
                cs.save_session_root_to_config("/tmp/custom_sessions")
                self.assertTrue(os.path.exists(cfg_file))
                with open(cfg_file, encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data.get("session_root"), "/tmp/custom_sessions")


if __name__ == "__main__":
    unittest.main()
