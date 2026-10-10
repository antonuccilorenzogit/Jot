import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from jot.core import shared
from jot.core.shared import (
    _folder_newest_mtime,
    _folder_size,
    _partial_file_hash,
    cleanup_orphan_temp_chunks,
)
from jot.pipeline.pipeline_settings import (
    build_default_pipeline_settings,
    load_and_sanitize_settings,
)


class SharedCleanupTests(unittest.TestCase):
    def _make_session(
        self, root: str, name: str, stage: str, *, with_html: bool
    ) -> str:
        session_dir = os.path.join(root, name)
        os.makedirs(session_dir, exist_ok=True)
        html_path = os.path.join(session_dir, "out.html")
        if with_html:
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write("<html></html>")
        with open(
            os.path.join(session_dir, "session.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump({"stage": stage, "outputs": {"html": html_path}}, fh)
        return session_dir

    def _make_old(self, path: str, days: int = 15) -> None:
        old = time.time() - days * 86400
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                os.utime(os.path.join(dirpath, filename), (old, old))
        os.utime(path, (old, old))

    def test_cleanup_orphan_sessions_respects_cutoff_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            expired_dir = os.path.join(tmpdir, "expired")
            recent_dir = os.path.join(tmpdir, "recent")
            os.makedirs(expired_dir, exist_ok=True)
            os.makedirs(recent_dir, exist_ok=True)

            expired_file = os.path.join(expired_dir, "session.json")
            recent_file = os.path.join(recent_dir, "session.json")
            with open(expired_file, "w", encoding="utf-8") as fh:
                fh.write("expired")
            with open(recent_file, "w", encoding="utf-8") as fh:
                fh.write("recent")

            now = time.time()
            os.utime(expired_file, (now - 15 * 86400, now - 15 * 86400))
            os.utime(expired_dir, (now - 15 * 86400, now - 15 * 86400))
            os.utime(recent_file, (now - 13 * 86400, now - 13 * 86400))
            os.utime(recent_dir, (now - 13 * 86400, now - 13 * 86400))

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                result = shared.cleanup_orphan_sessions(14)

            self.assertEqual(result["removed"], 1)
            self.assertEqual(result["errors"], 0)
            self.assertFalse(os.path.exists(expired_dir))
            self.assertTrue(os.path.exists(recent_dir))

    def test_cleanup_orphan_sessions_removes_recent_incomplete_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            incomplete_dir = self._make_session(
                tmpdir, "incomplete_recent", "phase1", with_html=False
            )

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                result = shared.cleanup_orphan_sessions()

            self.assertEqual(result["removed"], 1)
            self.assertFalse(os.path.exists(incomplete_dir))

    def test_cleanup_orphan_sessions_preserves_old_completed_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed_dir = self._make_session(
                tmpdir, "completed", "done", with_html=True
            )
            self._make_old(completed_dir)

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                result = shared.cleanup_orphan_sessions()

            self.assertEqual(result["removed"], 0)
            self.assertEqual(result["preserved_completed"], 1)
            self.assertTrue(os.path.exists(completed_dir))

    def test_cleanup_orphan_sessions_removes_old_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            incomplete_dir = self._make_session(
                tmpdir, "incomplete", "phase2", with_html=False
            )
            self._make_old(incomplete_dir)

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                result = shared.cleanup_orphan_sessions()

            self.assertEqual(result["removed"], 1)
            self.assertFalse(os.path.exists(incomplete_dir))

    def test_cleanup_orphan_sessions_reports_done_missing_html_as_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_dir = self._make_session(tmpdir, "missing", "done", with_html=False)
            self._make_old(missing_dir)

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                result = shared.cleanup_orphan_sessions()

            self.assertEqual(result["removed"], 1)
            self.assertEqual(result["missing_completed_html"], 1)
            self.assertFalse(os.path.exists(missing_dir))

    def test_cleanup_completed_sessions_dry_run_counts_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed_dir = self._make_session(
                tmpdir, "completed", "done", with_html=True
            )
            incomplete_dir = self._make_session(
                tmpdir, "incomplete", "phase1", with_html=False
            )
            self._make_old(completed_dir)
            self._make_old(incomplete_dir)

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                result = shared.cleanup_completed_sessions(dry_run=True)

            self.assertEqual(result["removed"], 0)
            self.assertEqual(result["candidates"], 1)
            self.assertEqual(result["deleted_paths"], [])
            self.assertTrue(os.path.exists(completed_dir))
            self.assertTrue(os.path.exists(incomplete_dir))

    def test_cleanup_completed_sessions_deletes_only_completed_html_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed_dir = self._make_session(
                tmpdir, "completed", "done", with_html=True
            )
            incomplete_dir = self._make_session(
                tmpdir, "incomplete", "phase1", with_html=False
            )
            self._make_old(completed_dir)
            self._make_old(incomplete_dir)

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                result = shared.cleanup_completed_sessions(dry_run=False)

            self.assertEqual(result["removed"], 1)
            self.assertEqual(
                [os.path.realpath(p) for p in result["deleted_paths"]],
                [os.path.realpath(completed_dir)],
            )
            self.assertFalse(os.path.exists(completed_dir))
            self.assertTrue(os.path.exists(incomplete_dir))

    def test_get_session_storage_info_ignores_preconverted_partial_until_promoted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "active")
            os.makedirs(session_dir, exist_ok=True)

            partial_path = os.path.join(session_dir, shared.PRECONVERTED_AUDIO_PARTIAL)
            final_path = os.path.join(session_dir, shared.PRECONVERTED_AUDIO_FINAL)

            with open(partial_path, "wb") as fh:
                fh.write(b"x" * 4096)

            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                shared.invalidate_session_storage_cache()
                info = shared.get_session_storage_info()
                self.assertEqual(info["total_sessions"], 1)
                self.assertEqual(info["total_bytes"], 0)

                os.replace(partial_path, final_path)

                shared.invalidate_session_storage_cache()
                info = shared.get_session_storage_info()
                self.assertEqual(info["total_sessions"], 1)
                self.assertEqual(info["total_bytes"], 4096)


class SharedPipelineDefaultsTests(unittest.TestCase):
    def test_build_default_pipeline_settings_uses_model_default_chunk_minutes(
        self,
    ):
        with patch(
            "jot.pipeline.pipeline_settings.default_chunk_minutes_for_model",
            return_value=5,
        ):
            settings = build_default_pipeline_settings(
                {"preferred_model": "gemini-3.5-flash", "fallback_models": []}
            )
            self.assertEqual(settings["model"], "gemini-3.5-flash")
            self.assertEqual(settings["chunk_minutes"], 5)

    def test_build_default_pipeline_settings_keeps_15_minutes_for_other_models(self):
        settings = build_default_pipeline_settings(
            {"preferred_model": "gemini-2.5-flash", "fallback_models": []}
        )
        self.assertEqual(settings["model"], "gemini-2.5-flash")
        self.assertEqual(settings["chunk_minutes"], 15)

    def test_load_and_sanitize_settings_defaults_chunk_minutes_when_missing(
        self,
    ):
        session = {
            "settings": {
                "model": "gemini-3.5-flash",
                "fallback_models": [],
                "effective_model": "gemini-3.5-flash",
                "audio": {"bitrate": "48k"},
            }
        }

        with patch(
            "jot.pipeline.pipeline_settings.default_chunk_minutes_for_model",
            return_value=5,
        ):
            settings, changed = load_and_sanitize_settings(session)

            self.assertTrue(changed)
            self.assertEqual(settings.chunk_minutes, 5)
            self.assertEqual(session["settings"]["chunk_minutes"], 5)

    def test_load_and_sanitize_settings_preserves_explicit_chunk_minutes(
        self,
    ):
        session = {
            "settings": {
                "model": "gemini-3.5-flash",
                "fallback_models": [],
                "effective_model": "gemini-3.5-flash",
                "chunk_minutes": 15,
                "overlap_seconds": 30,
                "macro_char_limit": 15000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            }
        }

        settings, changed = load_and_sanitize_settings(session)

        self.assertFalse(changed)
        self.assertEqual(settings.chunk_minutes, 15)
        self.assertEqual(session["settings"]["chunk_minutes"], 15)


class CleanupOrphanTempChunksTests(unittest.TestCase):
    def test_removes_old_matching_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_file = os.path.join(tmpdir, "jot_temp_old.mp3")
            fresh_file = os.path.join(tmpdir, "jot_temp_fresh.mp3")
            unrelated = os.path.join(tmpdir, "other_file.mp3")

            for p in (old_file, fresh_file, unrelated):
                with open(p, "w") as f:
                    f.write("x")

            now = time.time()
            past = now - 13 * 3600
            os.utime(old_file, (past, past))

            with patch("tempfile.gettempdir", return_value=tmpdir):
                removed = cleanup_orphan_temp_chunks(max_age_seconds=12 * 3600)

            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(old_file))
            self.assertTrue(os.path.exists(fresh_file))
            self.assertTrue(os.path.exists(unrelated))

    def test_non_matching_extensions_not_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            non_audio = os.path.join(tmpdir, "jot_temp_x.txt")
            with open(non_audio, "w") as f:
                f.write("x")
            now = time.time()
            old = now - 25 * 3600
            os.utime(non_audio, (old, old))

            with patch("tempfile.gettempdir", return_value=tmpdir):
                removed = cleanup_orphan_temp_chunks(max_age_seconds=12 * 3600)

            self.assertEqual(removed, 0)
            self.assertTrue(os.path.exists(non_audio))

    def test_removes_old_session_temp_chunk_files_and_empty_run_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session-a")
            run_dir = os.path.join(session_dir, "temp_chunks", "run_123_abc")
            os.makedirs(run_dir)
            chunk_path = os.path.join(run_dir, "chunk_001_0_60.mp3")
            with open(chunk_path, "wb") as f:
                f.write(b"x")

            old = time.time() - 13 * 3600
            os.utime(chunk_path, (old, old))

            with (
                patch("tempfile.gettempdir", return_value=os.path.join(tmpdir, "tmp")),
                patch("jot.core.shared.SESSION_ROOT", tmpdir),
            ):
                removed = cleanup_orphan_temp_chunks(max_age_seconds=12 * 3600)

            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(chunk_path))
            self.assertFalse(os.path.exists(run_dir))

    def test_preserves_fresh_empty_session_temp_run_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session-a")
            run_dir = os.path.join(session_dir, "temp_chunks", "run_123_abc")
            os.makedirs(run_dir)

            with (
                patch("tempfile.gettempdir", return_value=os.path.join(tmpdir, "tmp")),
                patch("jot.core.shared.SESSION_ROOT", tmpdir),
            ):
                removed = cleanup_orphan_temp_chunks(max_age_seconds=12 * 3600)

            self.assertEqual(removed, 0)
            self.assertTrue(os.path.exists(run_dir))


class PartialFileHashTests(unittest.TestCase):
    def test_existing_file_returns_hex_string(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            result = _partial_file_hash(path)
            self.assertIsInstance(result, str)
            self.assertEqual(len(result), 64)
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_empty_string(self):
        result = _partial_file_hash("/nonexistent/does/not/exist.bin")
        self.assertEqual(result, "")

    def test_same_content_same_hash(self):
        with tempfile.NamedTemporaryFile(delete=False) as f1:
            f1.write(b"identical content")
            p1 = f1.name
        with tempfile.NamedTemporaryFile(delete=False) as f2:
            f2.write(b"identical content")
            p2 = f2.name
        try:
            self.assertEqual(_partial_file_hash(p1), _partial_file_hash(p2))
        finally:
            os.unlink(p1)
            os.unlink(p2)


class FolderSizeTests(unittest.TestCase):
    def test_counts_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "data.bin")
            with open(path, "wb") as f:
                f.write(b"x" * 1024)
            size = _folder_size(tmpdir)
            self.assertEqual(size, 1024)

    def test_excludes_preconverted_partial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            partial = os.path.join(tmpdir, shared.PRECONVERTED_AUDIO_PARTIAL)
            real = os.path.join(tmpdir, "real.bin")
            with open(partial, "wb") as f:
                f.write(b"x" * 2048)
            with open(real, "wb") as f:
                f.write(b"y" * 512)
            size = _folder_size(tmpdir)
            self.assertEqual(size, 512)

    def test_nonexistent_directory_returns_zero(self):
        size = _folder_size("/nonexistent/directory/abc")
        self.assertEqual(size, 0)


class FolderNewestMtimeTests(unittest.TestCase):
    def test_returns_newest_file_mtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old = os.path.join(tmpdir, "old.txt")
            new = os.path.join(tmpdir, "new.txt")
            with open(old, "w") as f:
                f.write("old")
            with open(new, "w") as f:
                f.write("new")
            now = time.time()
            os.utime(old, (now - 100, now - 100))
            os.utime(new, (now - 10, now - 10))
            mtime = _folder_newest_mtime(tmpdir)
            self.assertAlmostEqual(mtime, now - 10, delta=2)

    def test_empty_directory_falls_back_to_dir_mtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mtime = _folder_newest_mtime(tmpdir)
            self.assertGreater(mtime, 0)


class CleanupOrphanSessionsMissingRootTests(unittest.TestCase):
    def test_absent_session_root_returns_zeros(self):
        with patch("jot.core.shared.SESSION_ROOT", "/nonexistent/path/abc123"):
            result = shared.cleanup_orphan_sessions()
        self.assertEqual(result["removed"], 0)
        self.assertEqual(result["freed_bytes"], 0)
        self.assertEqual(result["errors"], 0)


class SessionStorageCacheHitTests(unittest.TestCase):
    def test_second_call_within_ttl_returns_cached_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                shared.invalidate_session_storage_cache()
                first = shared.get_session_storage_info()
                os.makedirs(os.path.join(tmpdir, "new_session"))
                second = shared.get_session_storage_info()
                self.assertEqual(first["total_sessions"], second["total_sessions"])

    def test_invalidate_clears_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("jot.core.shared.SESSION_ROOT", tmpdir):
                shared.invalidate_session_storage_cache()
                shared.get_session_storage_info()
                shared.invalidate_session_storage_cache()
                result = shared.get_session_storage_info()
                self.assertIn("total_sessions", result)

    def test_concurrent_callers_share_one_traversal(self):
        import concurrent.futures as cf
        import threading

        call_count = 0
        call_count_lock = threading.Lock()
        gate = threading.Event()

        def slow_compute() -> dict:
            nonlocal call_count
            gate.wait(timeout=5.0)
            with call_count_lock:
                call_count += 1
            return {"total_bytes": 0, "total_sessions": 0}

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("jot.core.shared.SESSION_ROOT", tmpdir),
                patch(
                    "jot.core.shared._compute_session_storage_info",
                    side_effect=slow_compute,
                ),
            ):
                shared.invalidate_session_storage_cache()
                with cf.ThreadPoolExecutor(max_workers=3) as pool:
                    futs = [
                        pool.submit(shared.get_session_storage_info) for _ in range(3)
                    ]
                    time.sleep(0.05)
                    gate.set()
                    results = [f.result() for f in futs]

        self.assertTrue(all("total_sessions" in r for r in results))
        self.assertEqual(call_count, 1)


class SessionIdForFileTests(unittest.TestCase):
    def _write_file(self, directory: str, name: str, content: bytes) -> str:
        path = os.path.join(directory, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_same_content_different_mtime_yields_same_id(self):
        """mtime_ns invalidates the process cache but not the durable session ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_file(tmpdir, "lecture.mp3", b"audio" * 1000)
            shared._session_id_cache.clear()
            id1 = shared._session_id_for_file(path)
            now = time.time()
            os.utime(path, (now - 3600, now - 3600))
            id2 = shared._session_id_for_file(path)
            self.assertEqual(id1, id2)

    def test_different_content_different_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = self._write_file(tmpdir, "a.mp3", b"audio_version_1" * 500)
            p2 = self._write_file(tmpdir, "b.mp3", b"audio_version_2" * 500)
            shared._session_id_cache.clear()
            self.assertNotEqual(
                shared._session_id_for_file(p1),
                shared._session_id_for_file(p2),
            )

    def test_renamed_file_same_content_same_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = self._write_file(tmpdir, "original.mp3", b"lecture_data" * 200)
            shared._session_id_cache.clear()
            id1 = shared._session_id_for_file(p1)
            p2 = os.path.join(tmpdir, "renamed.mp3")
            os.rename(p1, p2)
            shared._session_id_cache.clear()
            id2 = shared._session_id_for_file(p2)
            self.assertEqual(id1, id2)

    def test_cache_hit_returns_same_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_file(tmpdir, "lecture.mp3", b"data" * 100)
            shared._session_id_cache.clear()
            id1 = shared._session_id_for_file(path)
            id2 = shared._session_id_for_file(path)
            self.assertEqual(id1, id2)

    def test_cache_miss_after_size_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_file(tmpdir, "lecture.mp3", b"x" * 1000)
            shared._session_id_cache.clear()
            id1 = shared._session_id_for_file(path)
            with open(path, "ab") as f:
                f.write(b"extra")
            id2 = shared._session_id_for_file(path)
            self.assertNotEqual(id1, id2)

    def test_different_content_same_size_different_id(self):
        """Overwriting a file with equal-size but different content must yield a new ID.

        The cache key includes mtime precisely for this case.  If mtime were
        removed from the key, (abs_path, size) would still match and the stale
        cached ID would be returned — making this assertion fail.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_file(tmpdir, "lecture.mp3", b"A" * 1000)
            shared._session_id_cache.clear()
            id1 = shared._session_id_for_file(path)
            with open(path, "wb") as f:
                f.write(b"B" * 1000)
            now = time.time()
            os.utime(path, (now, now + 3600))
            id2 = shared._session_id_for_file(path)
            self.assertNotEqual(id1, id2)

    def test_partial_hash_default_reads_one_megabyte(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "big.bin")
            with open(path, "wb") as f:
                f.write(b"A" * (2 * 1024 * 1024))
            h_default = shared._partial_file_hash(path)
            h_1mb = shared._partial_file_hash(path, max_bytes=1048576)
            self.assertEqual(h_default, h_1mb)
            h_64k = shared._partial_file_hash(path, max_bytes=65536)
            self.assertNotEqual(h_default, h_64k)


class SessionRootTests(unittest.TestCase):
    def test_get_default_session_root_windows(self):
        with (
            patch("jot.core.shared.platform.system", return_value="Windows"),
            patch.dict(
                os.environ,
                {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"},
                clear=False,
            ),
        ):
            result = shared._get_default_session_root(r"C:\Users\test")
        self.assertIn("jot", result)
        self.assertTrue(result.endswith("sessions"))
        self.assertIn("AppData", result)
        self.assertNotIn("Roaming", result)

    def test_get_default_session_root_windows_fallback_no_env(self):
        env_without_localappdata = {
            k: v for k, v in os.environ.items() if k != "LOCALAPPDATA"
        }
        with (
            patch("jot.core.shared.platform.system", return_value="Windows"),
            patch.dict(os.environ, env_without_localappdata, clear=True),
        ):
            result = shared._get_default_session_root(r"C:\Users\test")
        self.assertIn("AppData", result)
        self.assertIn("Local", result)
        self.assertTrue(result.endswith("sessions"))

    def test_get_default_session_root_macos(self):
        with patch("jot.core.shared.platform.system", return_value="Darwin"):
            result = shared._get_default_session_root("/Users/test")
        self.assertIn("Library", result)
        self.assertIn("Caches", result)
        self.assertIn("jot", result)
        self.assertTrue(result.endswith("sessions"))

    def test_get_default_session_root_linux(self):
        with patch("jot.core.shared.platform.system", return_value="Linux"):
            result = shared._get_default_session_root("/home/test")
        self.assertEqual(result, os.path.join("/home/test", ".jot_sessions"))

    def test_get_and_set_session_root_round_trip(self):
        original = shared.get_session_root()
        try:
            shared.set_session_root("/custom/sessions/path")
            self.assertEqual(shared.get_session_root(), "/custom/sessions/path")
            self.assertEqual(shared.SESSION_ROOT, "/custom/sessions/path")
        finally:
            shared.set_session_root(original)
        self.assertEqual(shared.get_session_root(), original)

    def test_migrate_legacy_session_root_happy_path(self):
        with tempfile.TemporaryDirectory() as base:
            old_root = os.path.join(base, "old_sessions")
            new_root = os.path.join(base, "new_sessions")
            os.makedirs(old_root)
            os.makedirs(os.path.join(old_root, "abc123"))

            with (
                patch("jot.core.shared.SESSION_ROOT", new_root),
                patch("jot.core.shared._LEGACY_SESSION_ROOT", old_root),
            ):
                result = shared.migrate_legacy_session_root()

            self.assertTrue(result)
            self.assertFalse(os.path.exists(old_root))
            self.assertTrue(os.path.isdir(new_root))
            self.assertTrue(os.path.isdir(os.path.join(new_root, "abc123")))

    def test_migrate_legacy_session_root_noop_if_old_absent(self):
        with tempfile.TemporaryDirectory() as base:
            old_root = os.path.join(base, "nonexistent")
            new_root = os.path.join(base, "new_sessions")
            with (
                patch("jot.core.shared.SESSION_ROOT", new_root),
                patch("jot.core.shared._LEGACY_SESSION_ROOT", old_root),
            ):
                result = shared.migrate_legacy_session_root()
            self.assertFalse(result)
            self.assertFalse(os.path.exists(new_root))

    def test_migrate_legacy_session_root_noop_if_new_exists(self):
        with tempfile.TemporaryDirectory() as base:
            old_root = os.path.join(base, "old_sessions")
            new_root = os.path.join(base, "new_sessions")
            os.makedirs(old_root)
            os.makedirs(new_root)
            with (
                patch("jot.core.shared.SESSION_ROOT", new_root),
                patch("jot.core.shared._LEGACY_SESSION_ROOT", old_root),
            ):
                result = shared.migrate_legacy_session_root()
            self.assertFalse(result)
            self.assertTrue(os.path.exists(old_root))

    def test_migrate_legacy_session_root_noop_if_paths_identical(self):
        with tempfile.TemporaryDirectory() as base:
            same_root = os.path.join(base, "sessions")
            os.makedirs(same_root)
            with (
                patch("jot.core.shared.SESSION_ROOT", same_root),
                patch("jot.core.shared._LEGACY_SESSION_ROOT", same_root),
            ):
                result = shared.migrate_legacy_session_root()
            self.assertFalse(result)


class SharedFacadeTests(unittest.TestCase):
    def test_shared_re_exports_expected_functions_and_constants(self):
        self.assertTrue(hasattr(shared, "get_session_root"))
        self.assertTrue(hasattr(shared, "set_session_root"))
        self.assertTrue(hasattr(shared, "_atomic_write_json"))
        self.assertTrue(hasattr(shared, "_atomic_write_text"))
        self.assertTrue(hasattr(shared, "_safe_mkdir"))
        self.assertTrue(hasattr(shared, "_load_json"))
        self.assertTrue(hasattr(shared, "cleanup_orphan_sessions"))
        self.assertTrue(hasattr(shared, "DEFAULT_MODEL"))

    def test_shared_getattr_fallback_and_missing_attribute(self):
        # Attribute on session_store accessible dynamically
        self.assertTrue(callable(shared.new_session))
        with self.assertRaises(AttributeError):
            _ = shared.non_existent_attribute_12345


if __name__ == "__main__":
    unittest.main()
