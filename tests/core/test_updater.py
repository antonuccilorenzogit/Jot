import hashlib
import io
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, call, mock_open, patch

from jot.core.updater import (
    _download_and_install_background,
    _poll_then_destroy,
    _verify_sha256,
    download_and_install_update,
)

_original_thread = threading.Thread


class _SyncThread(_original_thread):
    """threading.Thread replacement that runs target() synchronously on start()."""

    def __init__(self, target=None, args=(), daemon=False, **kw):
        _original_thread.__init__(self, daemon=daemon, **kw)
        self._target = target
        self._args = args

    def start(self):
        if self._target:
            self._target(*self._args)

    def join(self, timeout=None):
        pass


class UpdaterTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def test_empty_string_version_returns_error(self):
        result = download_and_install_update("")
        self.assertFalse(result["ok"])
        self.assertIn("Versione", result["error"])

    def test_none_version_returns_error(self):
        result = download_and_install_update(None)  # type: ignore[arg-type]
        self.assertFalse(result["ok"])

    def test_malformed_version_returns_error(self):
        for bad in ("../../etc/passwd", "1.2", "1.2.3.4", "v1.2.x", " 1.2.3"):
            with self.subTest(version=bad):
                result = download_and_install_update(bad)
                self.assertFalse(result["ok"])
                self.assertIn("Versione", result["error"])

    def test_version_v_prefix_stripped_in_filename(self):
        """Both 'v1.2.3' and '1.2.3' must produce filename 'Setup-v1.2.3.exe'."""
        for version in ("v1.2.3", "1.2.3"):
            with self.subTest(version=version):
                with (
                    patch.object(sys, "platform", "win32"),
                    patch("jot.core.updater._Thread") as mock_thread,
                    patch("tempfile.NamedTemporaryFile") as mock_tmp,
                    patch("ssl.create_default_context"),
                ):
                    mock_tmp.return_value.__enter__.return_value.name = "/tmp/setup.exe"
                    mock_tmp.return_value.__exit__.return_value = False
                    download_and_install_update(version)
                    url = mock_thread.call_args[1]["args"][0]

                self.assertIn("1.2.3", url)
                self.assertNotIn("vv", url)
                self.assertIn("Setup-v1.2.3.exe", url)

    # ------------------------------------------------------------------
    # Unsupported platform
    # ------------------------------------------------------------------

    def test_unsupported_platform_returns_error(self):
        with patch.object(sys, "platform", "linux"):
            result = download_and_install_update("1.0.0")
        self.assertFalse(result["ok"])
        self.assertIn("linux", result["error"])

    # ------------------------------------------------------------------
    # Download failure
    # ------------------------------------------------------------------

    def test_download_failure_returns_error(self):
        events: list[dict] = []

        def _emit(evt: str, payload: dict) -> None:
            events.append(payload)

        with (
            patch.object(sys, "platform", "win32"),
            patch("urllib.request.urlopen", side_effect=OSError("network error")),
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/setup.exe"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("1.0.0", emit_fn=_emit)

        self.assertTrue(result["ok"])
        self.assertEqual(result.get("status"), "downloading")
        error_events = [e for e in events if e.get("status") == "error"]
        self.assertTrue(len(error_events) > 0)
        self.assertIn("Download", error_events[0].get("error", ""))

    # ------------------------------------------------------------------
    # Windows happy path
    # ------------------------------------------------------------------

    def test_windows_calls_popen_with_currentuser_flag(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = (
            1  # exits immediately so _poll_then_destroy returns fast
        )

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "urllib.request.urlopen",
                return_value=MagicMock(
                    __enter__=lambda s, *a: s,
                    __exit__=lambda s, *a: None,
                    read=lambda s, n=None: b"",
                ),
            ),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch(
                "jot.core.updater.subprocess.Popen",
                return_value=fake_proc,
            ) as mock_popen,
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch.dict("sys.modules", {"webview": MagicMock(windows=[])}),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/setup.exe"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("2.0.0")

        self.assertTrue(result["ok"])
        mock_popen.assert_called_once()
        called_args = mock_popen.call_args[0][0]
        self.assertTrue(called_args[0].endswith(".exe"))
        self.assertIn("/CURRENTUSER", called_args)

    # ------------------------------------------------------------------
    # macOS happy path
    # ------------------------------------------------------------------

    def test_macos_happy_path_calls_subprocess_sequence(self):
        import plistlib

        fake_plist = plistlib.dumps(
            {"system-entities": [{"mount-point": "/Volumes/Jot"}]}
        )

        fake_proc = MagicMock()
        fake_proc.stdout = fake_plist
        fake_proc.returncode = 0

        call_names: list[str] = []

        def _fake_run(cmd, **kwargs):
            call_names.append(cmd[0])
            return fake_proc

        popen_calls = []

        def _fake_popen(cmd, **kwargs):
            popen_calls.append((cmd, kwargs))
            return MagicMock()

        with (
            patch.object(sys, "platform", "darwin"),
            patch(
                "urllib.request.urlopen",
                return_value=MagicMock(
                    __enter__=lambda s, *a: s,
                    __exit__=lambda s, *a: None,
                    read=lambda s, n=None: b"",
                ),
            ),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch("subprocess.run", side_effect=_fake_run),
            patch("subprocess.Popen", side_effect=_fake_popen),
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch("os.unlink"),
            patch("os.path.exists", return_value=True),
            patch("os.access", return_value=True),
            patch.dict("sys.modules", {"webview": MagicMock(windows=[])}),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/app.dmg"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("1.5.0")

        self.assertTrue(result["ok"])
        self.assertIn("hdiutil", call_names)
        self.assertEqual(len(popen_calls), 1)
        cmd, kwargs = popen_calls[0]
        self.assertEqual(cmd[0], "/bin/bash")
        self.assertEqual(cmd[1], "-c")
        self.assertIn("cp -a", cmd[2])
        self.assertTrue(kwargs.get("start_new_session"))

    # ------------------------------------------------------------------
    # macOS — no mount point
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # macOS — cp -R permission denied
    # ------------------------------------------------------------------

    def test_macos_cp_permission_denied_returns_permission_denied_key(self):
        import plistlib

        fake_plist = plistlib.dumps(
            {"system-entities": [{"mount-point": "/Volumes/Jot"}]}
        )

        attach_proc = MagicMock()
        attach_proc.stdout = fake_plist
        attach_proc.returncode = 0

        events: list[dict] = []

        def _emit(evt: str, payload: dict) -> None:
            events.append(payload)

        with (
            patch.object(sys, "platform", "darwin"),
            patch(
                "urllib.request.urlopen",
                return_value=MagicMock(
                    __enter__=lambda s, *a: s,
                    __exit__=lambda s, *a: None,
                    read=lambda s, n=None: b"",
                ),
            ),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch("subprocess.run", return_value=attach_proc),
            patch("subprocess.Popen"),
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch("os.unlink"),
            patch("os.path.exists", return_value=True),
            patch("os.access", return_value=False),  # Simulate permission denied
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/app.dmg"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("1.5.0", emit_fn=_emit)

        self.assertTrue(result["ok"])
        error_events = [e for e in events if e.get("status") == "error"]
        self.assertTrue(len(error_events) > 0)
        self.assertEqual(error_events[0].get("error"), "permission_denied")

    # ------------------------------------------------------------------
    # macOS — no mount point
    # ------------------------------------------------------------------

    def test_macos_no_mount_point_returns_error(self):
        import plistlib

        fake_plist = plistlib.dumps({"system-entities": []})

        fake_proc = MagicMock()
        fake_proc.stdout = fake_plist
        fake_proc.returncode = 0

        events: list[dict] = []

        def _emit2(evt: str, payload: dict) -> None:
            events.append(payload)

        with (
            patch.object(sys, "platform", "darwin"),
            patch(
                "urllib.request.urlopen",
                return_value=MagicMock(
                    __enter__=lambda s, *a: s,
                    __exit__=lambda s, *a: None,
                    read=lambda s, n=None: b"",
                ),
            ),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch("subprocess.run", return_value=fake_proc),
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch("os.unlink"),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/app.dmg"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("1.5.0", emit_fn=_emit2)

        self.assertTrue(result["ok"])
        error_events = [e for e in events if e.get("status") == "error"]
        self.assertTrue(len(error_events) > 0)
        self.assertIn("DMG", error_events[0].get("error", ""))


class TestChecksumVerification(unittest.TestCase):
    def _make_resp(self, content: bytes):
        class _R:
            def read(self, n=None):
                return content

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        return _R()

    def _write_tmp(self, data: bytes) -> str:
        fd, path = tempfile.mkstemp()
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return path

    def test_valid_checksum_returns_none(self):
        data = b"fake installer bytes"
        digest = hashlib.sha256(data).hexdigest()
        checksum_content = f"{digest}  jot-Setup-v1.0.0.exe\n".encode()
        tmp = self._write_tmp(data)
        try:
            with patch(
                "urllib.request.urlopen", return_value=self._make_resp(checksum_content)
            ):
                result = _verify_sha256(
                    tmp, "https://example.com/x.sha256", ssl.create_default_context()
                )
        finally:
            os.unlink(tmp)
        self.assertIsNone(result)

    def test_mismatched_checksum_returns_error(self):
        wrong_digest = "a" * 64
        checksum_content = f"{wrong_digest}  installer.exe\n".encode()
        tmp = self._write_tmp(b"real installer")
        try:
            with patch(
                "urllib.request.urlopen", return_value=self._make_resp(checksum_content)
            ):
                result = _verify_sha256(
                    tmp, "https://example.com/x.sha256", ssl.create_default_context()
                )
        finally:
            os.unlink(tmp)
        self.assertIsNotNone(result)
        self.assertIn("integrit", result or "")  # type: ignore[operator]

    def test_empty_checksum_content_returns_error(self):
        tmp = self._write_tmp(b"data")
        try:
            with patch("urllib.request.urlopen", return_value=self._make_resp(b"")):
                result = _verify_sha256(
                    tmp, "https://example.com/x.sha256", ssl.create_default_context()
                )
        finally:
            os.unlink(tmp)
        self.assertIsNotNone(result)
        self.assertIn("vuoto", result or "")  # type: ignore[operator]

    def test_malformed_hash_returns_error(self):
        checksum_content = b"not-a-hash  installer.exe\n"
        tmp = self._write_tmp(b"data")
        try:
            with patch(
                "urllib.request.urlopen", return_value=self._make_resp(checksum_content)
            ):
                result = _verify_sha256(
                    tmp, "https://example.com/x.sha256", ssl.create_default_context()
                )
        finally:
            os.unlink(tmp)
        self.assertIsNotNone(result)
        self.assertIn("valido", result or "")  # type: ignore[operator]

    def test_checksum_download_error_returns_error(self):
        tmp = self._write_tmp(b"data")
        try:
            with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
                result = _verify_sha256(
                    tmp, "https://example.com/x.sha256", ssl.create_default_context()
                )
        finally:
            os.unlink(tmp)
        self.assertIsNotNone(result)
        self.assertIn("checksum", result or "")  # type: ignore[operator]

    def test_checksum_404_is_hard_fail(self):
        """A 404 on the .sha256 file must block the update — CI always emits the checksum."""
        import urllib.error

        tmp = self._write_tmp(b"data")
        try:
            http_err = urllib.error.HTTPError(
                url="https://example.com/x.sha256",
                code=404,
                msg="Not Found",
                hdrs=None,  # type: ignore[arg-type]
                fp=None,
            )
            with patch("urllib.request.urlopen", side_effect=http_err):
                result = _verify_sha256(
                    tmp, "https://example.com/x.sha256", ssl.create_default_context()
                )
        finally:
            os.unlink(tmp)
        self.assertIsNotNone(result)
        self.assertIn("assente", result or "")  # type: ignore[operator]

    def test_checksum_non_404_http_error_returns_error(self):
        """Non-404 HTTP errors (e.g. 503) should still block the update."""
        import urllib.error

        tmp = self._write_tmp(b"data")
        try:
            http_err = urllib.error.HTTPError(
                url="https://example.com/x.sha256",
                code=503,
                msg="Service Unavailable",
                hdrs=None,  # type: ignore[arg-type]
                fp=None,
            )
            with patch("urllib.request.urlopen", side_effect=http_err):
                result = _verify_sha256(
                    tmp, "https://example.com/x.sha256", ssl.create_default_context()
                )
        finally:
            os.unlink(tmp)
        self.assertIsNotNone(result)
        self.assertIn("checksum", result or "")  # type: ignore[operator]

    def test_oserror_reading_tmp_file_returns_error(self):
        """OSError when open(tmp_path, 'rb') fails after a successful checksum download."""
        data = b"fake installer bytes"
        digest = hashlib.sha256(data).hexdigest()
        checksum_content = f"{digest}  jot-Setup-v1.0.0.exe\n".encode()
        tmp = self._write_tmp(data)
        os.unlink(
            tmp
        )  # FileNotFoundError (OSError subclass) when _verify_sha256 tries to read it
        with patch(
            "urllib.request.urlopen", return_value=self._make_resp(checksum_content)
        ):
            result = _verify_sha256(
                tmp, "https://example.com/x.sha256", ssl.create_default_context()
            )
        self.assertIsNotNone(result)
        self.assertIn("Lettura file temporaneo fallita", result or "")  # type: ignore[operator]


class TestChecksumIntegration(unittest.TestCase):
    def test_checksum_failure_blocks_install_and_deletes_tmp(self):
        events: list[dict] = []

        def _emit(evt: str, payload: dict) -> None:
            events.append(payload)

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "urllib.request.urlopen",
                return_value=MagicMock(
                    __enter__=lambda s, *a: s,
                    __exit__=lambda s, *a: None,
                    read=lambda *_: b"",
                    headers=MagicMock(get=lambda *_: None),
                ),
            ),
            patch("builtins.open", mock_open()),
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("os.unlink") as mock_unlink,
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/setup.exe"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("1.0.0", emit_fn=_emit)

        self.assertTrue(result["ok"])
        error_events = [e for e in events if e.get("status") == "error"]
        self.assertTrue(len(error_events) > 0)
        self.assertIn("vuoto", error_events[0].get("error", ""))
        mock_unlink.assert_called_with("/tmp/setup.exe")


class TestMacOSDmgInstall(unittest.TestCase):
    """Unit tests for macOS-only DMG install paths — all subprocess calls mocked."""

    # ------------------------------------------------------------------
    # Filename / URL construction
    # ------------------------------------------------------------------

    def test_macos_dmg_url_contains_correct_filename(self):
        """download_and_install_update on darwin must build URL with jot-v{ver}.dmg."""
        with (
            patch.object(sys, "platform", "darwin"),
            patch("jot.core.updater._Thread") as mock_thread,
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/app.dmg"
            mock_tmp.return_value.__exit__.return_value = False
            download_and_install_update("2.3.4")
            url = mock_thread.call_args[1]["args"][0]

        self.assertIn("jot-v2.3.4.dmg", url)
        self.assertNotIn(".exe", url)

    # ------------------------------------------------------------------
    # hdiutil attach failure
    # ------------------------------------------------------------------

    def test_macos_hdiutil_attach_failure_returns_installazione_fallita(self):
        """CalledProcessError from hdiutil attach must bubble as 'Installazione fallita'."""
        attach_err = subprocess.CalledProcessError(1, ["hdiutil", "attach"])
        attach_err.stderr = b"hdiutil: attach failed"

        events: list[dict] = []

        def _emit(evt: str, payload: dict) -> None:
            events.append(payload)

        with (
            patch.object(sys, "platform", "darwin"),
            patch(
                "urllib.request.urlopen",
                return_value=MagicMock(
                    __enter__=lambda s, *a: s,
                    __exit__=lambda s, *a: None,
                    read=lambda s, n=None: b"",
                ),
            ),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch("subprocess.run", side_effect=attach_err),
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch("os.unlink"),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/app.dmg"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("1.0.0", emit_fn=_emit)

        self.assertTrue(result["ok"])
        error_events = [e for e in events if e.get("status") == "error"]
        self.assertTrue(len(error_events) > 0)
        self.assertIn("Installazione fallita", error_events[0].get("error", ""))

    # ------------------------------------------------------------------
    # Happy path — xattr and open called
    # ------------------------------------------------------------------

    def test_macos_xattr_and_open_called_in_happy_path(self):
        """On a successful DMG install the spawned Popen bash script must contain xattr and open."""
        import plistlib

        fake_plist = plistlib.dumps(
            {"system-entities": [{"mount-point": "/Volumes/Jot"}]}
        )

        run_proc = MagicMock()
        run_proc.stdout = fake_plist
        run_proc.returncode = 0

        popen_calls: list[list[str]] = []

        def _fake_popen(cmd, **kwargs):
            popen_calls.append(list(cmd))

        with (
            patch.object(sys, "platform", "darwin"),
            patch(
                "urllib.request.urlopen",
                return_value=MagicMock(
                    __enter__=lambda s, *a: s,
                    __exit__=lambda s, *a: None,
                    read=lambda s, n=None: b"",
                ),
            ),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch("subprocess.run", return_value=run_proc),
            patch("subprocess.Popen", side_effect=_fake_popen),
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch("os.unlink"),
            patch("os.path.exists", return_value=True),
            patch("os.access", return_value=True),
            patch.dict("sys.modules", {"webview": MagicMock(windows=[])}),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/app.dmg"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("1.5.0")

        self.assertTrue(result["ok"])
        self.assertEqual(len(popen_calls), 1)
        cmd = popen_calls[0]
        self.assertEqual(cmd[0], "/bin/bash")
        self.assertEqual(cmd[1], "-c")
        script = cmd[2]
        self.assertIn("xattr -dr com.apple.quarantine", script)
        self.assertIn("open ", script)

    # ------------------------------------------------------------------
    # hdiutil detach called in finally even when cp fails (non-permission)
    # ------------------------------------------------------------------

    def test_macos_hdiutil_detach_called_when_app_src_missing(self):
        """hdiutil detach must be called in the finally block if the source application is missing in the DMG."""
        import plistlib

        fake_plist = plistlib.dumps(
            {"system-entities": [{"mount-point": "/Volumes/Jot"}]}
        )

        attach_proc = MagicMock()
        attach_proc.stdout = fake_plist
        attach_proc.returncode = 0

        detach_calls: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            if cmd[0] == "hdiutil" and len(cmd) > 1 and cmd[1] == "detach":
                detach_calls.append(list(cmd))
            return attach_proc

        events: list[dict] = []

        def _emit(evt: str, payload: dict) -> None:
            events.append(payload)

        with (
            patch.object(sys, "platform", "darwin"),
            patch(
                "urllib.request.urlopen",
                return_value=MagicMock(
                    __enter__=lambda s, *a: s,
                    __exit__=lambda s, *a: None,
                    read=lambda s, n=None: b"",
                ),
            ),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch("subprocess.run", side_effect=_fake_run),
            patch("subprocess.Popen"),
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThread,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch("os.unlink"),
            # Make exists return False to simulate missing app_src
            patch("os.path.exists", return_value=False),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/app.dmg"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("1.5.0", emit_fn=_emit)

        self.assertTrue(result["ok"])
        error_events = [e for e in events if e.get("status") == "error"]
        self.assertTrue(len(error_events) > 0)
        self.assertIn("non trovata nel DMG", error_events[0].get("error", ""))
        self.assertEqual(
            len(detach_calls),
            1,
            "hdiutil detach must always be called when installation fails before spawn",
        )
        self.assertIn("/Volumes/Jot", detach_calls[0])

    # ------------------------------------------------------------------
    # _install_macos_dmg in isolation — no-mount-point path tmp cleanup
    # ------------------------------------------------------------------

    def test_install_macos_dmg_unlinks_tmp_on_no_mount_point(self):
        """_install_macos_dmg must delete the tmp file even when no mount point is found."""
        import plistlib

        from jot.core.updater import _install_macos_dmg

        fake_plist = plistlib.dumps({"system-entities": []})
        fake_proc = MagicMock()
        fake_proc.stdout = fake_plist
        fake_proc.returncode = 0

        unlinked: list[str] = []

        with (
            patch("subprocess.run", return_value=fake_proc),
            patch("os.unlink", side_effect=lambda p: unlinked.append(p)),
        ):
            result = _install_macos_dmg("/tmp/fake.dmg")

        self.assertIsNotNone(result)
        self.assertFalse(result["ok"])  # type: ignore[index]
        self.assertIn("/tmp/fake.dmg", unlinked)


class TestWindowsInstallerLaunch(unittest.TestCase):
    """Tests for poll-then-destroy guard that prevents window close on UAC denial."""

    class _FakeResp:
        def read(self, n):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def _sync_thread_cls(self):
        """Return a threading.Thread replacement that runs target() synchronously on start()."""
        _original_thread = threading.Thread

        class _SyncThread(_original_thread):
            def __init__(self, target=None, args=(), daemon=False, **kw):
                _original_thread.__init__(self, daemon=daemon, **kw)
                self._target = target
                self._args = args

            def start(self):
                if self._target:
                    self._target(*self._args)

            def join(self, timeout=None):
                pass

        return _SyncThread

    def test_popen_called_with_detached_process_creationflag(self):
        """Popen must include DETACHED_PROCESS (0x8) in creationflags on Windows."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = (
            1  # exits immediately so _poll_then_destroy returns fast
        )

        _SyncThreadCls = self._sync_thread_cls()

        with (
            patch.object(sys, "platform", "win32"),
            patch("urllib.request.urlopen", return_value=self._FakeResp()),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch(
                "jot.core.updater.subprocess.Popen", return_value=fake_proc
            ) as mock_popen,
            patch(
                "jot.core.updater._Thread",
                side_effect=_SyncThreadCls,
            ),
            patch("jot.core.updater.time.sleep"),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch.dict("sys.modules", {"webview": MagicMock(windows=[])}),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/setup.exe"
            mock_tmp.return_value.__exit__.return_value = False
            download_and_install_update("2.0.0")

        kw = mock_popen.call_args[1]
        self.assertIn("creationflags", kw)
        self.assertTrue(
            kw["creationflags"] & 0x00000008, "DETACHED_PROCESS bit must be set"
        )

    def test_window_destroyed_when_installer_stays_alive(self):
        """destroy() must be called when the installer process remains alive past the confirm threshold."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # installer never exits

        fake_window = MagicMock()
        fake_webview = MagicMock()
        fake_webview.windows = [fake_window]

        _SyncThread = self._sync_thread_cls()

        with (
            patch.object(sys, "platform", "win32"),
            patch("urllib.request.urlopen", return_value=self._FakeResp()),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch("jot.core.updater.subprocess.Popen", return_value=fake_proc),
            patch("jot.core.updater.time.sleep"),
            patch("jot.core.updater._Thread", side_effect=_SyncThread),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch.dict("sys.modules", {"webview": fake_webview}),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/setup.exe"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("2.0.0")

        self.assertTrue(result["ok"])
        fake_window.destroy.assert_called_once()

    def test_window_not_destroyed_when_installer_exits_quickly(self):
        """destroy() must NOT be called when the installer exits immediately (e.g. UAC denied)."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1  # exits on first poll — UAC denied

        fake_window = MagicMock()
        fake_webview = MagicMock()
        fake_webview.windows = [fake_window]

        _SyncThread = self._sync_thread_cls()

        with (
            patch.object(sys, "platform", "win32"),
            patch("urllib.request.urlopen", return_value=self._FakeResp()),
            patch("builtins.open", mock_open()),
            patch("jot.core.updater._verify_sha256", return_value=None),
            patch("jot.core.updater.subprocess.Popen", return_value=fake_proc),
            patch("jot.core.updater.time.sleep"),
            patch("jot.core.updater._Thread", side_effect=_SyncThread),
            patch("tempfile.NamedTemporaryFile") as mock_tmp,
            patch.dict("sys.modules", {"webview": fake_webview}),
        ):
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/setup.exe"
            mock_tmp.return_value.__exit__.return_value = False
            result = download_and_install_update("2.0.0")

        self.assertTrue(result["ok"])
        fake_window.destroy.assert_not_called()


class TestPollThenDestroy(unittest.TestCase):
    """Direct unit tests for _poll_then_destroy — verifies UAC-denial guard logic."""

    def test_destroy_called_after_full_confirmation_window(self):
        """destroy() is called when the installer survives all _ALIVE_CONFIRM_POLLS polls."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # process never exits

        fake_window = MagicMock()
        fake_webview = MagicMock()
        fake_webview.windows = [fake_window]

        with (
            patch("jot.core.updater.time.sleep"),
            patch.dict("sys.modules", {"webview": fake_webview}),
        ):
            _poll_then_destroy(fake_proc)

        fake_window.destroy.assert_called_once()

    def test_destroy_not_called_when_process_exits_on_first_poll(self):
        """destroy() is NOT called when the installer exits immediately (UAC denied)."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1  # exits on every check

        fake_window = MagicMock()
        fake_webview = MagicMock()
        fake_webview.windows = [fake_window]

        with (
            patch("jot.core.updater.time.sleep"),
            patch.dict("sys.modules", {"webview": fake_webview}),
        ):
            _poll_then_destroy(fake_proc)

        fake_window.destroy.assert_not_called()

    def test_unlink_called_when_process_exits_on_first_poll_with_tmp_path(self):
        """_try_unlink is called with tmp_path when the installer exits immediately."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1  # exits on first check

        fake_webview = MagicMock()
        fake_webview.windows = [MagicMock()]

        with (
            patch("jot.core.updater.time.sleep"),
            patch.dict("sys.modules", {"webview": fake_webview}),
            patch("jot.core.updater._try_unlink") as mock_unlink,
        ):
            _poll_then_destroy(fake_proc, tmp_path="/tmp/fake_setup.exe")
            mock_unlink.assert_called_once_with("/tmp/fake_setup.exe")

    def test_destroy_not_called_when_process_exits_mid_window(self):
        """destroy() is NOT called when the installer exits before the confirmation threshold."""
        fake_proc = MagicMock()
        # Returns None for the first 2 polls, then exits — never reaches full confirmation
        fake_proc.poll.side_effect = [None, None, 1, 1, 1]

        fake_window = MagicMock()
        fake_webview = MagicMock()
        fake_webview.windows = [fake_window]

        with (
            patch("jot.core.updater.time.sleep"),
            patch.dict("sys.modules", {"webview": fake_webview}),
        ):
            _poll_then_destroy(fake_proc)

        fake_window.destroy.assert_not_called()

    def test_poll_called_exactly_alive_confirm_count_when_always_alive(self):
        """poll() is called exactly _ALIVE_CONFIRM_POLLS (5) times when process stays alive."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None

        fake_webview = MagicMock()
        fake_webview.windows = []

        with (
            patch("jot.core.updater.time.sleep"),
            patch.dict("sys.modules", {"webview": fake_webview}),
        ):
            _poll_then_destroy(fake_proc)

        self.assertEqual(fake_proc.poll.call_count, 5)

    def test_poll_called_once_when_exits_on_first_check(self):
        """poll() is called exactly once when process exits on the first check."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1

        fake_webview = MagicMock()
        fake_webview.windows = [MagicMock()]

        with (
            patch("jot.core.updater.time.sleep"),
            patch.dict("sys.modules", {"webview": fake_webview}),
        ):
            _poll_then_destroy(fake_proc)

        self.assertEqual(fake_proc.poll.call_count, 1)

    def test_emit_fn_done_called_when_installer_confirmed_alive(self):
        """emit_fn must receive 'done' (not 'error') when installer survives the confirmation window."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # never exits

        events: list[tuple[str, str]] = []

        def _emit(
            status: str, *, bytes_done: int = 0, bytes_total: int = 0, error: str = ""
        ) -> None:
            events.append((status, error))

        with (
            patch("jot.core.updater.time.sleep"),
            patch.dict("sys.modules", {"webview": MagicMock(windows=[])}),
        ):
            _poll_then_destroy(fake_proc, _emit)

        statuses = [s for s, _ in events]
        self.assertIn("done", statuses)
        self.assertNotIn("error", statuses)

    def test_emit_fn_uac_denied_called_when_installer_exits_quickly(self):
        """emit_fn must receive error='uac_denied' (not 'done') when installer exits immediately."""
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1  # exits on first poll — UAC denied

        events: list[tuple[str, str]] = []

        def _emit(
            status: str, *, bytes_done: int = 0, bytes_total: int = 0, error: str = ""
        ) -> None:
            events.append((status, error))

        with (
            patch("jot.core.updater.time.sleep"),
            patch.dict("sys.modules", {"webview": MagicMock(windows=[MagicMock()])}),
        ):
            _poll_then_destroy(fake_proc, _emit)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], ("error", "uac_denied"))


if __name__ == "__main__":
    unittest.main()
