"""Tests for jot.services.folders_service."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch


class TestFoldersService(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.folders_file = os.path.join(self.tmp_dir, "folders.json")
        self._patcher = patch(
            "jot.services.folders_service.FOLDERS_FILE",
            self.folders_file,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # get_folders
    # ------------------------------------------------------------------

    def test_get_folders_returns_empty_when_file_absent(self):
        from jot.services.folders_service import get_folders

        self.assertEqual(get_folders(), [])

    def test_get_folders_round_trip(self):
        from jot.services.folders_service import get_folders, save_folders

        folders = [
            {
                "id": "abc",
                "name": "Anatomia",
                "color": "#FF6B6B",
                "session_dirs": ["/a", "/b"],
            },
        ]
        save_folders(folders)
        result = get_folders()
        self.assertEqual(result, folders)

    def test_get_folders_returns_empty_on_corrupt_json(self):
        from jot.services.folders_service import get_folders

        with open(self.folders_file, "w", encoding="utf-8") as fh:
            fh.write("not valid json {{")
        self.assertEqual(get_folders(), [])

    def test_get_folders_returns_empty_when_top_level_not_dict(self):
        from jot.services.folders_service import get_folders

        with open(self.folders_file, "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)
        self.assertEqual(get_folders(), [])

    def test_get_folders_returns_empty_when_folders_not_list(self):
        from jot.services.folders_service import get_folders

        with open(self.folders_file, "w", encoding="utf-8") as fh:
            json.dump({"folders": "bad"}, fh)
        self.assertEqual(get_folders(), [])

    def test_get_folders_skips_non_dict_entries(self):
        from jot.services.folders_service import get_folders

        with open(self.folders_file, "w", encoding="utf-8") as fh:
            json.dump({"folders": [{"id": "x"}, "oops", None]}, fh)
        result = get_folders()
        self.assertEqual(result, [{"id": "x"}])

    # ------------------------------------------------------------------
    # save_folders
    # ------------------------------------------------------------------

    def test_save_folders_creates_file(self):
        from jot.services.folders_service import save_folders

        self.assertFalse(os.path.exists(self.folders_file))
        save_folders([])
        self.assertTrue(os.path.exists(self.folders_file))

    def test_save_folders_multiple_items(self):
        from jot.services.folders_service import get_folders, save_folders

        folders = [
            {"id": "1", "name": "A", "color": "#fff", "session_dirs": []},
            {"id": "2", "name": "B", "color": "#000", "session_dirs": ["/x"]},
        ]
        save_folders(folders)
        self.assertEqual(get_folders(), folders)

    def test_save_folders_raises_on_non_list(self):
        from jot.services.folders_service import save_folders

        with self.assertRaises(TypeError):
            save_folders("not a list")  # type: ignore[arg-type]

    def test_save_folders_overwrites_existing(self):
        from jot.services.folders_service import get_folders, save_folders

        save_folders([{"id": "old"}])
        save_folders([{"id": "new"}])
        self.assertEqual(get_folders(), [{"id": "new"}])

    def test_save_folders_exception_handling(self):
        from jot.services.folders_service import save_folders

        with patch("builtins.open", side_effect=OSError("write error")):
            with self.assertRaises(IOError):
                save_folders([{"id": "test"}])

    # ------------------------------------------------------------------
    # migrate_session_roots
    # ------------------------------------------------------------------

    def test_migrate_session_roots_updates_matching_paths(self):
        from jot.services.folders_service import (
            get_folders,
            migrate_session_roots,
            save_folders,
        )

        old_root = os.path.join(self.tmp_dir, "old_sessions")
        new_root = os.path.join(self.tmp_dir, "new_sessions")
        os.makedirs(old_root, exist_ok=True)
        os.makedirs(new_root, exist_ok=True)

        s1_old = os.path.join(old_root, "sess_1")
        s2_old = os.path.join(old_root, "sess_2")
        s3_other = os.path.join(self.tmp_dir, "other", "sess_3")

        folders = [
            {"id": "f1", "name": "Cardio", "session_dirs": [s1_old, s2_old]},
            {"id": "f2", "name": "Anato", "session_dirs": [s3_other]},
        ]
        save_folders(folders)

        migrated = migrate_session_roots(old_root, new_root)
        s1_new = os.path.normpath(os.path.join(new_root, "sess_1"))
        s2_new = os.path.normpath(os.path.join(new_root, "sess_2"))

        self.assertEqual(migrated[0]["session_dirs"], [s1_new, s2_new])
        self.assertEqual(migrated[1]["session_dirs"], [s3_other])

        # Verify disk persistence
        on_disk = get_folders()
        self.assertEqual(on_disk[0]["session_dirs"], [s1_new, s2_new])
        self.assertEqual(on_disk[1]["session_dirs"], [s3_other])

    def test_migrate_session_roots_same_root_noop(self):
        from jot.services.folders_service import (
            migrate_session_roots,
            save_folders,
        )

        root = os.path.join(self.tmp_dir, "same_root")
        os.makedirs(root, exist_ok=True)
        s1 = os.path.join(root, "sess_1")
        folders = [{"id": "f1", "session_dirs": [s1]}]
        save_folders(folders)

        migrated = migrate_session_roots(root, root)
        self.assertEqual(migrated, folders)

    def test_migrate_session_roots_empty_input_noop(self):
        from jot.services.folders_service import migrate_session_roots

        self.assertEqual(migrate_session_roots("", "/new"), [])
        self.assertEqual(migrate_session_roots("/old", ""), [])

    # ------------------------------------------------------------------
    # reconcile_folders_with_session_root
    # ------------------------------------------------------------------

    def test_reconcile_folders_heals_missing_session_dirs(self):
        from jot.services.folders_service import (
            get_folders,
            reconcile_folders_with_session_root,
            save_folders,
        )

        current_root = os.path.join(self.tmp_dir, "current_sessions")
        os.makedirs(os.path.join(current_root, "sess_1"), exist_ok=True)
        os.makedirs(os.path.join(current_root, "sess_2"), exist_ok=True)

        old_dead_s1 = os.path.join(self.tmp_dir, "dead_old", "sess_1")
        old_dead_s2 = os.path.join(self.tmp_dir, "dead_old", "sess_2")
        nonexistent_s3 = os.path.join(self.tmp_dir, "dead_old", "sess_3")

        folders = [
            {
                "id": "f1",
                "name": "Cardio",
                "session_dirs": [old_dead_s1, old_dead_s2, nonexistent_s3],
            }
        ]
        save_folders(folders)

        reconciled, modified = reconcile_folders_with_session_root(
            folders, current_root
        )
        self.assertTrue(modified)

        s1_expected = os.path.normpath(os.path.join(current_root, "sess_1"))
        s2_expected = os.path.normpath(os.path.join(current_root, "sess_2"))

        self.assertEqual(
            reconciled[0]["session_dirs"],
            [s1_expected, s2_expected, nonexistent_s3],
        )

        # Verify disk persistence
        on_disk = get_folders()
        self.assertEqual(
            on_disk[0]["session_dirs"],
            [s1_expected, s2_expected, nonexistent_s3],
        )

    def test_reconcile_folders_noop_when_dirs_exist(self):
        from jot.services.folders_service import (
            reconcile_folders_with_session_root,
            save_folders,
        )

        current_root = os.path.join(self.tmp_dir, "current_sessions")
        existing_dir = os.path.join(current_root, "sess_1")
        os.makedirs(existing_dir, exist_ok=True)

        folders = [{"id": "f1", "session_dirs": [existing_dir]}]
        save_folders(folders)

        reconciled, modified = reconcile_folders_with_session_root(
            folders, current_root
        )
        self.assertFalse(modified)
        self.assertEqual(reconciled[0]["session_dirs"], [existing_dir])

    def test_reconcile_folders_canonicalizes_casing_under_session_root(self):
        from jot.services.folders_service import (
            get_folders,
            reconcile_folders_with_session_root,
            save_folders,
        )

        current_root = os.path.join(self.tmp_dir, "Sessions")
        os.makedirs(os.path.join(current_root, "sess_1"), exist_ok=True)

        # Saved with lower-case 'sessions'
        different_cased_root = os.path.join(self.tmp_dir, "sessions")
        saved_dir = os.path.join(different_cased_root, "sess_1")

        folders = [{"id": "f1", "session_dirs": [saved_dir]}]
        save_folders(folders)

        reconciled, modified = reconcile_folders_with_session_root(
            folders, current_root
        )
        expected_dir = os.path.normpath(os.path.join(current_root, "sess_1"))
        self.assertTrue(modified)
        self.assertEqual(reconciled[0]["session_dirs"], [expected_dir])
        self.assertEqual(get_folders()[0]["session_dirs"], [expected_dir])


if __name__ == "__main__":
    unittest.main()
