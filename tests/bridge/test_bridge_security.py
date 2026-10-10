"""
Comprehensive security tests for PyWebView bridge controllers.
Verifies defense against path traversal, symlink escapes, disallowed URL schemes,
and arbitrary file access outside sandboxed session and desktop directories.
"""

import os
import tempfile
import threading
import unittest
from collections import OrderedDict
from unittest.mock import MagicMock, patch

from jot.bridge.bridge_utils import _path_under_root
from jot.bridge.controllers.html_controller import HtmlControllerMixin
from jot.bridge.controllers.session_controller import SessionControllerMixin
from jot.bridge.controllers.system_controller import SystemControllerMixin


class DummySecurityHost(
    HtmlControllerMixin, SessionControllerMixin, SystemControllerMixin
):
    def __init__(self, session_root: str):
        self._session_root = session_root
        self._logger = MagicMock()
        self._adapter = MagicMock()
        self._window = MagicMock()

        # HTML controller state
        self._resolved_cache_lock = threading.Lock()
        self._resolved_path_cache: dict[str, str] = {}
        self._html_shell_cache: dict[str, tuple[str, str]] = {}

        # Session controller state
        self._sessions_cache = None
        self._sessions_cache_ts = 0.0
        self._sessions_cache_gen = 0
        self._sessions_cache_lock = threading.Lock()
        self._text_cache: OrderedDict = OrderedDict()
        self._text_cache_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._processing_thread = None

    def _get_session_root(self) -> str:
        return self._session_root


class BridgePathUnderRootTests(unittest.TestCase):
    """Test the core path containment security primitive."""

    def test_exact_path_matches(self):
        root = os.path.realpath(tempfile.gettempdir())
        self.assertTrue(_path_under_root(root, root))

    def test_nested_child_path(self):
        root = os.path.realpath(tempfile.gettempdir())
        child = os.path.join(root, "subfolder", "file.txt")
        self.assertTrue(_path_under_root(child, root))

    def test_prefix_collision_is_rejected(self):
        # /path/to/folder vs /path/to/folder_sibling
        base = os.path.join(tempfile.gettempdir(), "sandbox")
        sibling = os.path.join(tempfile.gettempdir(), "sandbox_sibling")
        self.assertFalse(_path_under_root(sibling, base))

    def test_parent_escape_is_rejected(self):
        base = os.path.join(tempfile.gettempdir(), "sandbox", "inner")
        parent = os.path.join(tempfile.gettempdir(), "sandbox")
        self.assertFalse(_path_under_root(parent, base))


class SystemControllerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.session_root = os.path.join(self.temp_dir, "sessions")
        os.makedirs(self.session_root, exist_ok=True)
        self.host = DummySecurityHost(session_root=self.session_root)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_open_url_rejects_disallowed_schemes(self):
        evil_urls = [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "file:///C:/Windows/System32/calc.exe",
            "data:text/html,<script>alert(1)</script>",
            "http://evil.com",
            "https://malicious-site.com/exploit",
            "about:blank",
            "vbscript:msgbox(1)",
        ]
        for url in evil_urls:
            with self.subTest(url=url):
                res = self.host.open_url(url)
                self.assertFalse(res["ok"])
                self.assertIn("non consentito", res["error"].lower())

    def test_open_url_accepts_allowlisted_prefixes(self):
        allowed_urls = [
            "https://github.com/antonuccilorenzogit/Jot",
            "https://aistudio.google.com/app/apikey",
        ]
        with patch("jot.utils.file_ops.open_path_with_default_app") as mock_open:
            for url in allowed_urls:
                with self.subTest(url=url):
                    res = self.host.open_url(url)
                    self.assertTrue(res["ok"])
                    mock_open.assert_called_with(url)

    def test_open_file_rejects_urls(self):
        res = self.host.open_file("https://github.com")
        self.assertFalse(res["ok"])
        self.assertIn("open_url", res["error"])

    def test_open_file_rejects_non_string(self):
        res = self.host.open_file(12345)  # type: ignore[arg-type]
        self.assertFalse(res["ok"])
        self.assertIn("stringa", res["error"])

    def test_open_file_rejects_path_traversal_outside_allowed_roots(self):
        # An absolute path outside session root and desktop
        outside_file = os.path.join(self.temp_dir, "outside.txt")
        with open(outside_file, "w") as f:
            f.write("secret data")

        res = self.host.open_file(outside_file)
        self.assertFalse(res["ok"])
        self.assertIn("Accesso negato", res["error"])


class HtmlControllerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.session_root = os.path.join(self.temp_dir, "sessions")
        os.makedirs(self.session_root, exist_ok=True)
        self.host = DummySecurityHost(session_root=self.session_root)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_html_rejects_non_html_extensions(self):
        bad_paths = ["file.txt", "script.py", "session.json", "image.png"]
        for p in bad_paths:
            with self.subTest(path=p):
                res = self.host.read_html_content(p)
                self.assertFalse(res["ok"])
                self.assertIn(".html", res["error"])

    def test_read_html_rejects_path_traversal_outside_sandbox(self):
        # Create an existing file outside the sandbox
        outside_html = os.path.join(self.temp_dir, "sensitive.html")
        with open(outside_html, "w", encoding="utf-8") as f:
            f.write("<html><body>Classified</body></html>")

        # Attempt to read via direct path and traversal relative path
        res = self.host.read_html_content(outside_html)
        self.assertFalse(res["ok"])
        self.assertIn("Accesso negato", res["error"])

        traversal_path = os.path.join(self.session_root, "..", "sensitive.html")
        res2 = self.host.read_html_content(traversal_path)
        self.assertFalse(res2["ok"])
        self.assertIn("Accesso negato", res2["error"])

    def test_save_html_rejects_non_html_extensions(self):
        res = self.host.save_html_content("script.sh", "echo evil")
        self.assertFalse(res["ok"])
        self.assertIn(".html", res["error"])

    def test_save_html_rejects_path_outside_sandbox(self):
        outside_html = os.path.join(self.temp_dir, "overwrite_target.html")
        with open(outside_html, "w", encoding="utf-8") as f:
            f.write("<html><body>Original</body></html>")

        res = self.host.save_html_content(outside_html, "Overwritten")
        self.assertFalse(res["ok"])
        self.assertIn("Accesso negato", res["error"])


class SessionControllerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.session_root = os.path.join(self.temp_dir, "sessions")
        os.makedirs(self.session_root, exist_ok=True)
        self.host = DummySecurityHost(session_root=self.session_root)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_delete_session_rejects_traversal_outside_session_root(self):
        # Create an outside directory with sensitive files
        outside_dir = os.path.join(self.temp_dir, "critical_system_data")
        os.makedirs(outside_dir, exist_ok=True)
        canary_file = os.path.join(outside_dir, "canary.txt")
        with open(canary_file, "w") as f:
            f.write("must survive")

        # Try to delete using traversal path
        traversal_path = os.path.join(self.session_root, "..", "critical_system_data")
        res = self.host.delete_session(traversal_path)

        self.assertFalse(res["ok"])
        self.assertIn("Percorso non valido", res["error"])
        # Ensure canary file and outside dir were not touched
        self.assertTrue(os.path.isdir(outside_dir))
        self.assertTrue(os.path.isfile(canary_file))

    def test_delete_session_cannot_delete_session_root_itself(self):
        res = self.host.delete_session(self.session_root)
        self.assertFalse(res["ok"])
        self.assertIn("principale", res["error"])
        self.assertTrue(os.path.isdir(self.session_root))

    def test_touch_session_opened_rejects_traversal(self):
        outside_dir = os.path.join(self.temp_dir, "other")
        os.makedirs(outside_dir, exist_ok=True)

        res = self.host.touch_session_opened(outside_dir)
        self.assertFalse(res["ok"])
        self.assertIn("Percorso non valido", res["error"])

    def test_update_session_input_path_rejects_traversal_session_dir(self):
        outside_dir = os.path.join(self.temp_dir, "other")
        os.makedirs(outside_dir, exist_ok=True)

        res = self.host.update_session_input_path(outside_dir, "dummy_audio.mp3")
        self.assertFalse(res["ok"])
        self.assertIn("Percorso non valido", res["error"])

    def test_remove_session_audio_rejects_traversal(self):
        outside_dir = os.path.join(self.temp_dir, "other")
        os.makedirs(outside_dir, exist_ok=True)

        res = self.host.remove_session_audio(outside_dir)
        self.assertFalse(res["ok"])
        self.assertIn("Percorso non valido", res["error"])


if __name__ == "__main__":
    unittest.main()
