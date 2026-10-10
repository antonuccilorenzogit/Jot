import json
import os
import unittest
from unittest.mock import patch

from jot.core.session_store import (
    SessionCollisionError,
    clone_session_settings,
    new_session,
    resolve_session_paths,
)


class SessionStoreTests(unittest.TestCase):
    def test_new_session_has_expected_defaults(self):
        with patch(
            "jot.core.session_store.build_default_pipeline_settings",
            return_value={
                "model": "gemini-2.5-flash",
                "fallback_models": ["gemini-3.6-flash"],
                "effective_model": "gemini-2.5-flash",
                "chunk_minutes": 15,
                "overlap_seconds": 30,
                "macro_char_limit": 22000,
                "preconvert_audio": True,
                "prefetch_next_chunk": True,
                "inline_audio_max_mb": 6.0,
                "audio": {"bitrate": "48k"},
            },
        ):
            session = new_session("lesson.mp3")
        self.assertEqual(session["stage"], "phase1")
        self.assertIn("phase1", session)
        self.assertIn("outputs", session)
        self.assertEqual(session["settings"]["model"], "gemini-2.5-flash")
        self.assertEqual(session["settings"]["effective_model"], "gemini-2.5-flash")
        self.assertEqual(session["settings"]["fallback_models"], ["gemini-3.6-flash"])
        self.assertEqual(session["settings"]["audio"]["bitrate"], "48k")

    def test_clone_session_settings_is_deep_copy(self):
        session = {"settings": {"audio": {"bitrate": "48k"}}}
        cloned = clone_session_settings(session)
        cloned["audio"]["bitrate"] = "64k"
        self.assertEqual(session["settings"]["audio"]["bitrate"], "48k")

    def test_resolve_session_paths_builds_consistent_layout(self):
        paths = resolve_session_paths("lesson.mp3")
        self.assertTrue(paths.session_path.endswith("session.json"))
        self.assertTrue(paths.phase1_chunks_dir.endswith("phase1_chunks"))
        self.assertTrue(paths.phase2_revised_dir.endswith("phase2_revised"))


class EnsureSessionDirsTests(unittest.TestCase):
    def test_ensure_session_dirs_creates_all_dirs(self):
        import tempfile

        from jot.core.session_store import SessionPaths, ensure_session_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = SessionPaths(
                session_dir=tmpdir,
                session_path=tmpdir + "/session.json",
                phase1_chunks_dir=tmpdir + "/phase1_chunks",
                phase2_revised_dir=tmpdir + "/phase2_revised",
                macro_path=tmpdir + "/macro.json",
            )
            ensure_session_dirs(paths)

            for d in (
                paths.phase1_chunks_dir,
                paths.phase2_revised_dir,
            ):
                self.assertTrue(os.path.isdir(d), f"Expected dir to exist: {d}")

    def test_reset_session_dirs_wipes_and_recreates(self):
        import tempfile

        from jot.core.session_store import SessionPaths, reset_session_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            paths = SessionPaths(
                session_dir=session_dir,
                session_path=session_dir + "/session.json",
                phase1_chunks_dir=session_dir + "/phase1_chunks",
                phase2_revised_dir=session_dir + "/phase2_revised",
                macro_path=session_dir + "/macro.json",
            )
            # Create the dir with a file inside
            os.makedirs(paths.phase1_chunks_dir, exist_ok=True)
            sentinel = os.path.join(paths.phase1_chunks_dir, "chunk_000.md")
            with open(sentinel, "w") as fh:
                fh.write("data")

            reset_session_dirs(paths)

            self.assertFalse(os.path.exists(sentinel), "Old file should be gone")
            self.assertTrue(
                os.path.isdir(paths.phase1_chunks_dir), "Dir should exist again"
            )

    def test_reset_session_dirs_refuses_completed_session_with_html(self):
        import tempfile

        from jot.core.session_store import SessionPaths, reset_session_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            paths = SessionPaths(
                session_dir=session_dir,
                session_path=os.path.join(session_dir, "session.json"),
                phase1_chunks_dir=os.path.join(session_dir, "phase1_chunks"),
                phase2_revised_dir=os.path.join(session_dir, "phase2_revised"),
                macro_path=os.path.join(session_dir, "macro.json"),
            )
            os.makedirs(paths.phase1_chunks_dir, exist_ok=True)
            html_path = os.path.join(session_dir, "output.html")
            sentinel = os.path.join(paths.phase1_chunks_dir, "chunk_000.md")
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write("<html></html>")
            with open(sentinel, "w", encoding="utf-8") as fh:
                fh.write("keep me")
            with open(paths.session_path, "w", encoding="utf-8") as fh:
                json.dump({"stage": "done", "outputs": {"html": html_path}}, fh)

            with self.assertRaises(SessionCollisionError):
                reset_session_dirs(paths)

            self.assertTrue(os.path.exists(html_path))
            self.assertTrue(os.path.exists(sentinel))

    def test_reset_session_dirs_allows_explicit_completed_destroy(self):
        import tempfile

        from jot.core.session_store import SessionPaths, reset_session_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = os.path.join(tmpdir, "session")
            paths = SessionPaths(
                session_dir=session_dir,
                session_path=os.path.join(session_dir, "session.json"),
                phase1_chunks_dir=os.path.join(session_dir, "phase1_chunks"),
                phase2_revised_dir=os.path.join(session_dir, "phase2_revised"),
                macro_path=os.path.join(session_dir, "macro.json"),
            )
            os.makedirs(paths.phase1_chunks_dir, exist_ok=True)
            html_path = os.path.join(session_dir, "output.html")
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write("<html></html>")
            with open(paths.session_path, "w", encoding="utf-8") as fh:
                json.dump({"stage": "done", "outputs": {"html": html_path}}, fh)

            reset_session_dirs(paths, allow_completed_destroy=True)

            self.assertFalse(os.path.exists(html_path))
            self.assertTrue(os.path.isdir(paths.phase1_chunks_dir))


class SaveLoadSessionTests(unittest.TestCase):
    def test_save_load_round_trip_and_sets_updated_at(self):
        import tempfile

        from jot.core.session_store import load_session, save_session

        session = {"stage": "phase2", "custom_key": "hello"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "session.json")
            save_session(path, session)
            loaded = load_session(path)

        self.assertEqual(loaded["stage"], "phase2")
        self.assertEqual(loaded["custom_key"], "hello")
        self.assertIn("updated_at", loaded)

    def test_update_session_returns_old_snapshot(self):
        from jot.core.session_store import _update_session

        session = {"stage": "phase1", "value": 1}
        snapshot = _update_session(session, {"stage": "phase2", "value": 2})

        self.assertEqual(snapshot["stage"], "phase1")
        self.assertEqual(snapshot["value"], 1)
        self.assertEqual(session["stage"], "phase2")
        self.assertEqual(session["value"], 2)


class NewSessionCustomSettingsTests(unittest.TestCase):
    def test_new_session_custom_settings_used_verbatim(self):
        from jot.core.session_store import new_session

        custom = {"model": "custom-model", "chunk_minutes": 5}
        session = new_session("lesson.mp3", settings=custom)
        self.assertEqual(session["settings"]["model"], "custom-model")
        self.assertEqual(session["settings"]["chunk_minutes"], 5)


class ResolveSessionPathsHintTests(unittest.TestCase):
    def test_hint_overrides_default_path(self):
        import tempfile

        from jot.core.session_store import resolve_session_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            hint_dir = os.path.join(tmpdir, "my_session")
            paths = resolve_session_paths("lesson.mp3", session_dir_hint=hint_dir)

        self.assertTrue(paths.session_dir.endswith("my_session"))


class TestMigrateSession(unittest.TestCase):
    def test_pre_versioned_session_migrated_to_current_version(self):
        from jot.core.session_store import migrate_session

        session = {"stage": "phase2", "settings": {"model": "x"}}
        result, changed = migrate_session(session)
        self.assertTrue(changed)
        self.assertEqual(result["schema_version"], 2)
        self.assertIn("phase1", result)
        self.assertIn("phase2", result)
        self.assertIn("outputs", result)
        self.assertIn("last_error", result)
        self.assertIsNone(result["retry_state"])
        self.assertEqual(result["stage"], "phase2")

    def test_current_version_is_no_op(self):
        from jot.core.session_store import migrate_session

        session = {
            "schema_version": 2,
            "stage": "boundary",
            "phase1": {"chunks_done": 3},
            "phase2": {"macro_total": 5},
            "outputs": {"html": "out.html"},
            "last_error": None,
            "retry_state": None,
        }
        result, changed = migrate_session(session)
        self.assertFalse(changed)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["phase1"]["chunks_done"], 3)
        self.assertEqual(result["outputs"]["html"], "out.html")

    def test_missing_schema_version_treated_as_pre_versioned(self):
        from jot.core.session_store import migrate_session

        session = {"stage": "done", "outputs": {"html": "path.html"}}
        result, changed = migrate_session(session)
        self.assertTrue(changed)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["outputs"]["html"], "path.html")

    def test_migration_is_idempotent(self):
        from jot.core.session_store import migrate_session

        session = {"stage": "phase1"}
        result, _ = migrate_session(session)
        result2, changed2 = migrate_session(result)
        self.assertFalse(changed2)
        self.assertEqual(result2["schema_version"], 2)

    def test_v1_adds_retry_state_without_losing_progress(self):
        from jot.core.session_store import migrate_session

        session = {
            "schema_version": 1,
            "stage": "phase2",
            "phase1": {"chunks_done": 7},
            "phase2": {"revised_done": 2},
            "outputs": {"html": "partial.html"},
        }

        result, changed = migrate_session(session)

        self.assertTrue(changed)
        self.assertEqual(result["schema_version"], 2)
        self.assertIsNone(result["retry_state"])
        self.assertEqual(result["phase1"]["chunks_done"], 7)
        self.assertEqual(result["phase2"]["revised_done"], 2)
        self.assertEqual(result["outputs"]["html"], "partial.html")


class SessionStoreDomainDutiesTests(unittest.TestCase):
    def test_get_and_set_session_root(self):
        from jot.core.session_store import (
            get_session_root,
            set_session_root,
        )

        orig = get_session_root()
        try:
            set_session_root("/tmp/custom_sessions")
            self.assertEqual(get_session_root(), "/tmp/custom_sessions")
        finally:
            set_session_root(orig)

    def test_fingerprinting_and_session_id(self):
        import tempfile

        from jot.core.session_store import (
            _file_fingerprint,
            _file_tail_hash,
            _partial_file_hash,
            _session_dir_for_file,
            _session_id_for_file,
        )

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"Audio content test bytes " * 100)
            path = f.name

        try:
            fp = _file_fingerprint(path)
            self.assertEqual(fp["path"], os.path.abspath(path))
            self.assertGreater(fp["size"], 0)

            head_hash = _partial_file_hash(path)
            self.assertTrue(len(head_hash) > 0)

            tail_hash = _file_tail_hash(path)
            self.assertTrue(len(tail_hash) > 0)

            sid = _session_id_for_file(path)
            self.assertTrue(len(sid) > 0)
            self.assertEqual(_session_id_for_file(path), sid)  # Cache check

            sdir = _session_dir_for_file(path)
            self.assertTrue(sdir.endswith(sid))
        finally:
            os.unlink(path)

    def test_storage_info_and_cleanup(self):
        import tempfile

        from jot.core.session_store import (
            cleanup_completed_sessions,
            cleanup_orphan_sessions,
            cleanup_orphan_temp_chunks,
            get_session_storage_info,
            invalidate_session_storage_cache,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("jot.core.session_store.SESSION_ROOT", tmpdir):
                invalidate_session_storage_cache()
                info = get_session_storage_info()
                self.assertEqual(info["total_sessions"], 0)
                self.assertEqual(info["total_bytes"], 0)

                # Orphan cleanup in empty directory
                cleanup_res = cleanup_orphan_sessions()
                self.assertEqual(cleanup_res["removed"], 0)

                completed_res = cleanup_completed_sessions()
                self.assertEqual(completed_res["removed"], 0)

                temp_res = cleanup_orphan_temp_chunks()
                self.assertIsInstance(temp_res, int)


if __name__ == "__main__":
    unittest.main()
