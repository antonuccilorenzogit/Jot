import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import jot.utils.file_ops as _fo
from jot.utils.file_ops import (
    _HTML_CACHE_MAX,
    _html_last_gen,
    _html_write_locks,
    evict_html_paths_under,
    extract_html_shell,
    open_path_with_default_app,
    read_html_content,
    save_html_body_content,
)

_SHELL_HTML = (
    "<!DOCTYPE html><html><head></head><body>",
    "</body></html>",
)


def _write(path, content, generation=None):
    return save_html_body_content(
        path, content, shell=_SHELL_HTML, generation=generation
    )


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class GenerationOrderingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "doc.html")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("<html><body><p>initial</p></body></html>")
        _write(self.path, "<p>initial</p>")

    def tearDown(self):
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    # Basic generation semantics
    # ------------------------------------------------------------------

    def test_no_generation_always_writes(self):
        _write(self.path, "<p>v1</p>")
        _write(self.path, "<p>v2</p>")
        self.assertIn("v2", _read(self.path))

    def test_generation_newer_wins(self):
        _write(self.path, "<p>old</p>", generation=1)
        result = _write(self.path, "<p>new</p>", generation=2)
        self.assertTrue(result)
        self.assertIn("new", _read(self.path))

    def test_generation_stale_discarded(self):
        _write(self.path, "<p>new</p>", generation=5)
        result = _write(self.path, "<p>old</p>", generation=3)
        self.assertFalse(result)
        self.assertIn("new", _read(self.path))

    def test_same_generation_discarded(self):
        _write(self.path, "<p>first</p>", generation=2)
        result = _write(self.path, "<p>second</p>", generation=2)
        self.assertFalse(result)
        self.assertIn("first", _read(self.path))

    def test_generation_none_overwrites_tracked_file(self):
        _write(self.path, "<p>gen1</p>", generation=10)
        result = _write(self.path, "<p>forced</p>", generation=None)
        self.assertTrue(result)
        self.assertIn("forced", _read(self.path))

    def test_last_gen_updated_after_write(self):
        _write(self.path, "<p>x</p>", generation=7)
        self.assertEqual(_html_last_gen.get(self.path), 7)

    # ------------------------------------------------------------------
    # Concurrent write ordering
    # ------------------------------------------------------------------

    def test_concurrent_saves_newer_generation_wins_on_disk(self):
        """Simulate two threads racing: older gen must not overwrite newer content."""
        new_done = threading.Event()
        results = {}

        def save_old():
            new_done.wait(timeout=5.0)
            results["old"] = _write(self.path, "<p>OLD</p>", generation=1)

        def save_new():
            results["new"] = _write(self.path, "<p>NEW</p>", generation=2)
            new_done.set()

        t1 = threading.Thread(target=save_old)
        t2 = threading.Thread(target=save_new)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        disk = _read(self.path)
        self.assertIn("NEW", disk)
        self.assertNotIn("OLD", disk)
        self.assertTrue(results["new"])
        self.assertFalse(results["old"])

    def test_concurrent_saves_no_generation_both_complete(self):
        """Without generation, both writes go through (no ordering guarantee, but no crash)."""
        barrier = threading.Barrier(2)

        def save(content):
            barrier.wait()
            _write(self.path, content)

        threads = [
            threading.Thread(target=save, args=(f"<p>v{i}</p>",)) for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        disk = _read(self.path)
        self.assertTrue(disk)  # file exists and is non-empty


class ExtractHtmlShellTests(unittest.TestCase):
    def test_valid_html_returns_tuple(self):
        html = "<!DOCTYPE html><html><head></head><body><p>Hello</p></body></html>"
        result = extract_html_shell(html)
        assert result is not None
        open_tag, close_tag = result
        self.assertIn("<body", open_tag)
        self.assertIn("</body>", close_tag)

    def test_no_body_tag_returns_none(self):
        html = "<html><p>no body tag</p></html>"
        self.assertIsNone(extract_html_shell(html))

    def test_body_with_attributes(self):
        html = '<html><body class="main"><p>content</p></body></html>'
        result = extract_html_shell(html)
        assert result is not None
        open_tag, _ = result
        self.assertIn('class="main"', open_tag)

    def test_empty_string_returns_none(self):
        self.assertIsNone(extract_html_shell(""))

    def test_only_open_body_no_close_returns_none(self):
        html = "<html><body><p>no close</p>"
        self.assertIsNone(extract_html_shell(html))


class ReadHtmlContentTests(unittest.TestCase):
    def test_reads_existing_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", encoding="utf-8", delete=False
        ) as f:
            f.write("<html><body>test</body></html>")
            path = f.name
        try:
            content = read_html_content(path)
            self.assertIn("test", content)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_html_content("/nonexistent/file.html")


class SaveHtmlBodyContentWithoutShellTests(unittest.TestCase):
    def test_reads_shell_from_file_when_not_provided(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "doc.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("<html><body><p>original</p></body></html>")
            result = save_html_body_content(path, "<p>updated</p>", shell=None)
            self.assertTrue(result)
            with open(path, encoding="utf-8") as f:
                disk = f.read()
            self.assertIn("updated", disk)

    def test_no_body_in_file_writes_fallback_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "bare.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("no body here at all")
            result = save_html_body_content(path, "<p>content</p>", shell=None)
            self.assertTrue(result)
            with open(path, encoding="utf-8") as f:
                disk = f.read()
            self.assertIn("<!DOCTYPE html>", disk)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            save_html_body_content("/nonexistent/path.html", "<p>x</p>")

    def test_concurrent_shell_none_reads_stay_consistent(self):
        """Concurrent writers with shell=None must not see a stale shell.

        Before the fix, the file was read outside _html_write_lock, so a
        concurrent writer could replace the file between the read and the
        write, leaving the winning thread's output with a stale shell.  With
        the fix, the read happens inside the lock so both reads always observe
        the file as it stands at the moment of each writer's turn.
        """

        def _run_single_test() -> None:
            N = 20
            with tempfile.TemporaryDirectory() as tmpdir:
                path = os.path.join(tmpdir, "concurrent.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(
                        "<html><head><meta charset='utf-8'></head>"
                        "<body><p>init</p></body></html>"
                    )

                barrier = threading.Barrier(N)
                errors: list[Exception] = []

                def writer(idx: int) -> None:
                    try:
                        barrier.wait()
                        save_html_body_content(path, f"<p>thread-{idx}</p>", shell=None)
                    except Exception as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=writer, args=(i,)) for i in range(N)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                self.assertEqual(errors, [], errors)
                with open(path, encoding="utf-8") as f:
                    final = f.read()
                self.assertIn("<html", final)
                self.assertIn("</body>", final)
                self.assertIn("<p>thread-", final)

        for _ in range(5):
            _run_single_test()


class HtmlCacheEvictionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        with _fo._html_write_locks_meta:
            _fo._html_write_locks.clear()
            _fo._html_last_gen.clear()

    def tearDown(self):
        self._tmp.cleanup()
        with _fo._html_write_locks_meta:
            _fo._html_write_locks.clear()
            _fo._html_last_gen.clear()

    def _make_html(self, name: str) -> str:
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("<html><body><p>x</p></body></html>")
        return path

    def test_cap_evicts_oldest_when_full(self):
        """Filling the dict beyond _HTML_CACHE_MAX evicts the oldest entry from
        both _html_write_locks and _html_last_gen (shared FIFO eviction)."""
        paths = [self._make_html(f"doc_{i}.html") for i in range(_HTML_CACHE_MAX + 1)]
        for p in paths:
            _write(p, "<p>x</p>", generation=1)

        self.assertNotIn(paths[0], _html_write_locks)  # lock evicted
        self.assertNotIn(paths[0], _html_last_gen)  # generation evicted too
        self.assertIn(paths[-1], _html_write_locks)
        self.assertEqual(len(_html_write_locks), _HTML_CACHE_MAX)

    def test_lock_not_evicted_while_in_use(self):
        """A lock that is currently in use (ref_count > 0) must not be evicted
        even if the cache capacity is exceeded."""
        path_in_use = self._make_html("in_use.html")
        lock_ctx = _fo._html_write_lock(path_in_use)
        self.assertIn(path_in_use, _fo._html_write_locks)
        self.assertEqual(_fo._html_write_locks[path_in_use][1], 1)

        # Fill cache with fillers to trigger eviction
        fillers = [self._make_html(f"filler_{i}.html") for i in range(_HTML_CACHE_MAX)]
        for p in fillers:
            _write(p, "<p>x</p>", generation=1)

        # path_in_use must NOT be evicted because ref_count was 1
        self.assertIn(path_in_use, _fo._html_write_locks)

        # Exit the context
        with lock_ctx:
            pass

        # Now path_in_use has ref_count = 0, so writing another file will evict it
        extra_path = self._make_html("extra.html")
        _write(extra_path, "<p>x</p>", generation=1)
        self.assertNotIn(path_in_use, _fo._html_write_locks)

    def test_generation_guard_reset_after_fifo_eviction(self):
        """After FIFO eviction both the lock and the generation entry are removed.
        The gen guard resets to 0 for that path, so any write with gen>=1 succeeds.
        This is the accepted trade-off of shared eviction (keeps both dicts bounded)."""
        first = self._make_html("evict_me.html")
        _write(first, "<p>initial</p>", generation=10)
        self.assertEqual(_html_last_gen.get(first), 10)

        fillers = [self._make_html(f"filler_{i}.html") for i in range(_HTML_CACHE_MAX)]
        for p in fillers:
            _write(p, "<p>x</p>", generation=1)

        # *first* has been evicted from both dicts.
        self.assertNotIn(first, _html_write_locks)
        self.assertNotIn(first, _html_last_gen)

        # Re-inserting *first*: gen guard was reset, so a formerly-stale gen=5 write
        # now succeeds (accepted behaviour after eviction).
        stale_result = _write(first, "<p>stale</p>", generation=5)
        self.assertTrue(stale_result)
        self.assertIn("stale", _read(first))

        # A newer gen=11 write must also succeed.
        newer_result = _write(first, "<p>newer</p>", generation=11)
        self.assertTrue(newer_result)
        self.assertIn("newer", _read(first))

    def test_evict_html_paths_under_removes_prefixed_leaves_others(self):
        """evict_html_paths_under clears paths under a prefix from both dicts,
        leaving unrelated paths untouched."""
        sub = os.path.join(self._tmp.name, "session_abc")
        os.makedirs(sub, exist_ok=True)
        p1 = os.path.join(sub, "output.html")
        p2 = os.path.join(sub, "output2.html")
        p_other = self._make_html("other.html")
        for p in (p1, p2):
            with open(p, "w", encoding="utf-8") as f:
                f.write("<html><body><p>x</p></body></html>")
            _write(p, "<p>x</p>", generation=1)
        _write(p_other, "<p>y</p>", generation=1)

        evict_html_paths_under(sub + os.sep)

        self.assertNotIn(p1, _html_write_locks)
        self.assertNotIn(p1, _html_last_gen)
        self.assertNotIn(p2, _html_write_locks)
        self.assertNotIn(p2, _html_last_gen)
        self.assertIn(p_other, _html_write_locks)
        self.assertIn(p_other, _html_last_gen)

    def test_lock_exit_ignored_if_recreated_lock_differs(self):
        """If a path's lock is evicted (or deleted) and subsequently recreated
        with a new Lock object, exiting the old lock context manager should NOT
        corrupt/decrement the reference count of the new Lock object."""
        path = self._make_html("recreated.html")
        old_lock_ctx = _fo._html_write_lock(path)
        self.assertIn(path, _fo._html_write_locks)
        old_lock_obj = _fo._html_write_locks[path][0]

        # Simulate eviction/deletion of the path from the locks dict
        with _fo._html_write_locks_meta:
            del _fo._html_write_locks[path]

        # Re-create a new lock for the same path
        new_lock_ctx = _fo._html_write_lock(path)
        self.assertIn(path, _fo._html_write_locks)
        new_lock_obj = _fo._html_write_locks[path][0]
        self.assertNotEqual(old_lock_obj, new_lock_obj)
        self.assertEqual(_fo._html_write_locks[path][1], 1)

        # Exit the OLD lock context. This should be a no-op on the new lock object.
        with old_lock_ctx:
            pass

        # The new lock's reference count must remain 1
        self.assertEqual(_fo._html_write_locks[path][1], 1)

        # Cleanup: exit new lock context
        with new_lock_ctx:
            pass
        self.assertEqual(_fo._html_write_locks[path][1], 0)


class OpenPathWithDefaultAppTests(unittest.TestCase):
    def test_empty_string_raises_value_error(self):
        with self.assertRaises(ValueError):
            open_path_with_default_app("")

    def test_non_string_raises_value_error(self):
        with self.assertRaises(ValueError):
            open_path_with_default_app(None)  # type: ignore[arg-type]

    def test_nonexistent_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            open_path_with_default_app("/nonexistent/really/does/not/exist.html")

    def test_disallowed_extension_raises_value_error(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError):
                open_path_with_default_app(path)
        finally:
            os.unlink(path)

    def test_allowed_html_file_on_win32(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        try:
            with (
                patch.object(sys, "platform", "win32"),
                patch("os.startfile", create=True) as mock_sf,
            ):
                open_path_with_default_app(path)
                mock_sf.assert_called_once()
        finally:
            os.unlink(path)

    def test_allowed_html_file_on_darwin(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        try:
            with (
                patch.object(sys, "platform", "darwin"),
                patch("subprocess.Popen") as mock_popen,
            ):
                open_path_with_default_app(path)
                mock_popen.assert_called_once()
        finally:
            os.unlink(path)

    def test_url_http_on_win32(self):
        with (
            patch.object(sys, "platform", "win32"),
            patch("os.startfile", create=True) as mock_sf,
        ):
            open_path_with_default_app("http://example.com")
            mock_sf.assert_called_once_with("http://example.com")

    def test_url_linux_xdg_open(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch("subprocess.Popen") as mock_popen,
        ):
            open_path_with_default_app("https://example.com")
            mock_popen.assert_called_once_with(["xdg-open", "https://example.com"])

    def test_file_linux_xdg_open(self):
        fd, path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        try:
            with (
                patch.object(sys, "platform", "linux"),
                patch("subprocess.Popen") as mock_popen,
            ):
                open_path_with_default_app(path)
                mock_popen.assert_called_once_with(["xdg-open", os.path.realpath(path)])
        finally:
            os.unlink(path)

    def test_html_gen_max_eviction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("jot.utils.file_ops._HTML_GEN_MAX", 2):
                paths = [os.path.join(tmpdir, f"test{i}.html") for i in range(3)]
                for p in paths:
                    with open(p, "w", encoding="utf-8") as f:
                        f.write("<html><body></body></html>")
                for i, p in enumerate(paths, 1):
                    save_html_body_content(
                        p, f"<p>{i}</p>", shell=_SHELL_HTML, generation=i
                    )


class AtomicFileOpsTests(unittest.TestCase):
    def test_safe_mkdir(self):
        from jot.utils.file_ops import _safe_mkdir

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "a", "b", "c")
            _safe_mkdir(target)
            self.assertTrue(os.path.isdir(target))
            # Idempotent call
            _safe_mkdir(target)
            self.assertTrue(os.path.isdir(target))

    def test_atomic_write_text_and_fsync(self):
        from jot.utils.file_ops import _atomic_write_text, _fsync_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "test.txt")
            _atomic_write_text(target, "hello atomic world")
            with open(target, encoding="utf-8") as fh:
                content = fh.read()
            self.assertEqual(content, "hello atomic world")
            _fsync_dir(target)

    def test_atomic_write_json_and_load_json(self):
        from jot.utils.file_ops import _atomic_write_json, _load_json

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "data.json")
            data = {"key": "value", "numbers": [1, 2, 3]}
            _atomic_write_json(target, data)
            loaded = _load_json(target)
            self.assertEqual(loaded, data)


if __name__ == "__main__":
    unittest.main()
