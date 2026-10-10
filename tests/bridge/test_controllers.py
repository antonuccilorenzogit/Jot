import os
import tempfile
import threading
import unittest
from collections import OrderedDict
from typing import cast
from unittest.mock import MagicMock, patch

from jot.bridge.controllers.export_controller import ExportControllerMixin
from jot.bridge.controllers.html_controller import HtmlControllerMixin
from jot.bridge.controllers.media_controller import MediaControllerMixin
from jot.bridge.controllers.session_controller import SessionControllerMixin
from jot.bridge.controllers.settings_controller import SettingsControllerMixin
from jot.bridge.controllers.system_controller import SystemControllerMixin


class DummyExportHost(ExportControllerMixin):
    def __init__(self, window=None, session_root=""):
        self._window = window
        self._session_root = session_root
        self.invalidated = False

    def _get_session_root(self) -> str:
        return self._session_root

    def _invalidate_sessions_cache(self) -> None:
        self.invalidated = True


class DummySystemHost(SystemControllerMixin):
    def __init__(self, session_root=""):
        self._session_root = session_root
        self._logger = MagicMock()
        self._adapter = MagicMock()

    def _get_session_root(self) -> str:
        return self._session_root


class DummySettingsHost(SettingsControllerMixin):
    def __init__(self, window=None):
        self._window = window
        self._logger = MagicMock()
        self._processing_thread = None
        self._move_lock = threading.Lock()
        self._move_state = {
            "status": "idle",
            "moved": 0,
            "total": 0,
            "error": None,
        }
        self._sessions_cache = None
        self._sessions_cache_gen = 0
        self._sessions_cache_lock = threading.Lock()


class DummyMediaHost(MediaControllerMixin):
    def __init__(self, window=None):
        self._window = window
        self._adapter = MagicMock()
        self.console_messages: list[str] = []

    def _push_console(self, msg: str) -> None:
        self.console_messages.append(msg)


class DummyHtmlHost(HtmlControllerMixin):
    def __init__(self, session_root=""):
        self._session_root = session_root
        self._logger = MagicMock()
        self._resolved_cache_lock = threading.Lock()
        self._resolved_path_cache: dict[str, str] = {}
        self._html_shell_cache: dict[str, tuple[str, str]] = {}
        self._sessions_cache_lock = threading.Lock()
        self._sessions_cache = None
        self._sessions_cache_gen = 0

    def _get_session_root(self) -> str:
        return self._session_root


class DummySessionHost(SessionControllerMixin):
    def __init__(self, session_root=""):
        self._session_root = session_root
        self._logger = MagicMock()
        self._sessions_cache = None
        self._sessions_cache_ts = 0.0
        self._sessions_cache_gen = 0
        self._sessions_cache_lock = threading.Lock()
        self._resolved_path_cache: dict[str, str] = {}
        self._resolved_cache_lock = threading.Lock()
        self._html_shell_cache: dict[str, tuple[str, str]] = {}
        self._text_cache: OrderedDict = OrderedDict()
        self._text_cache_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()

    def _get_session_root(self) -> str:
        return self._session_root

    def _find_candidate_audio_path(
        self, data, session_dir, session_path, write_back=True
    ):
        return data.get("input", {}).get("path")


class TestExportController(unittest.TestCase):
    def test_export_sbobina_package_no_target_path_cancelled(self):
        win = MagicMock()
        win.create_file_dialog.return_value = None
        host = DummyExportHost(window=win)
        res = host.export_sbobina_package("/fake/session")
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("cancelled"))

    def test_export_sbobina_package_dialog_fallback(self):
        win = MagicMock()
        win.create_file_dialog.side_effect = [
            Exception("dialog fail"),
            ["/out/file.sbobina"],
        ]
        host = DummyExportHost(window=win)
        with patch(
            "jot.bridge.controllers.export_controller.create_sbobina_package"
        ) as mock_create:
            mock_create.return_value = {"ok": True, "package_path": "/out/file.sbobina"}
            res = host.export_sbobina_package("/fake/session")
            self.assertTrue(res.get("ok"))
            mock_create.assert_called_once_with(
                "/fake/session",
                "/out/file.sbobina",
                include_mode="full",
            )

    def test_export_sbobina_package_explicit_target_path(self):
        host = DummyExportHost(window=None)
        with patch(
            "jot.bridge.controllers.export_controller.create_sbobina_package"
        ) as mock_create:
            mock_create.return_value = {"ok": True}
            res = host.export_sbobina_package(
                "/fake/session",
                export_type="media_only",
                target_path="/out/pkg.sbobina",
            )
            self.assertTrue(res.get("ok"))
            mock_create.assert_called_once_with(
                "/fake/session",
                "/out/pkg.sbobina",
                include_mode="media_only",
            )

    def test_export_sbobina_package_no_window_no_target(self):
        host = DummyExportHost(window=None)
        res = host.export_sbobina_package("/fake/session")
        self.assertFalse(res.get("ok"))
        self.assertIn("non specificato", res.get("error", ""))

    def test_import_sbobina_package_cancelled(self):
        win = MagicMock()
        win.create_file_dialog.return_value = None
        host = DummyExportHost(window=win)
        res = host.import_sbobina_package()
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("cancelled"))

    def test_import_sbobina_package_dialog_fallback(self):
        win = MagicMock()
        win.create_file_dialog.side_effect = [Exception("error"), "/in/pkg.sbobina"]
        host = DummyExportHost(window=win, session_root="/sessions")
        with patch(
            "jot.bridge.controllers.export_controller.unpack_and_import_package"
        ) as mock_import:
            mock_import.return_value = {"ok": True, "session_id": "123"}
            res = host.import_sbobina_package()
            self.assertTrue(res.get("ok"))
            self.assertTrue(host.invalidated)
            mock_import.assert_called_once_with("/in/pkg.sbobina", "/sessions")

    def test_import_sbobina_package_no_path(self):
        host = DummyExportHost(window=None)
        res = host.import_sbobina_package()
        self.assertFalse(res.get("ok"))
        self.assertIn("Nessun pacchetto", res.get("error", ""))


class TestSystemController(unittest.TestCase):
    def test_validate_environment(self):
        host = DummySystemHost()
        with patch("jot.services.validation_service.validate_environment") as mock_val:
            mock_val.return_value = {"valid": True}
            res = host.validate_environment(api_key="key123", check_api_key=True)
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("result"), {"valid": True})

    def test_validate_environment_exception(self):
        host = DummySystemHost()
        with patch(
            "jot.services.validation_service.validate_environment",
            side_effect=ValueError("boom"),
        ):
            res = host.validate_environment()
            self.assertFalse(res.get("ok"))
            self.assertIn("boom", res.get("error", ""))

    def test_open_file_invalid_inputs(self):
        host = DummySystemHost()
        self.assertFalse(host.open_file(123).get("ok"))  # type: ignore[arg-type]
        self.assertFalse(host.open_file("https://google.com").get("ok"))

    def test_open_file_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            host = DummySystemHost(session_root=os.path.join(temp_dir, "sessions"))
            res = host.open_file(os.path.join(temp_dir, "other", "secret.txt"))
            self.assertFalse(res.get("ok"))
            self.assertIn("Accesso negato", res.get("error", ""))

    def test_open_file_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_root = os.path.join(temp_dir, "sessions")
            os.makedirs(session_root, exist_ok=True)
            target = os.path.join(session_root, "doc.txt")
            with open(target, "w") as f:
                f.write("hello")
            host = DummySystemHost(session_root=session_root)
            with patch(
                "jot.utils.file_ops.open_path_with_default_app"
            ) as mock_open_app:
                res = host.open_file(target)
                self.assertTrue(res.get("ok"))
                mock_open_app.assert_called_once_with(os.path.realpath(target))

    def test_open_url_allowed_and_blocked(self):
        host = DummySystemHost()
        # Invalid
        self.assertFalse(host.open_url("ftp://malicious.com").get("ok"))
        self.assertFalse(host.open_url(123).get("ok"))  # type: ignore[arg-type]

        # Allowed
        with patch("jot.utils.file_ops.open_path_with_default_app") as mock_open_app:
            res = host.open_url("https://aistudio.google.com/apikey")
            self.assertTrue(res.get("ok"))
            mock_open_app.assert_called_once_with("https://aistudio.google.com/apikey")

    def test_show_notification(self):
        host = DummySystemHost()
        with (
            patch("plyer.notification.notify") as mock_notify,
            patch.object(host, "flash_window") as mock_flash,
        ):
            res = host.show_notification("Title", "Message")
            self.assertTrue(res.get("ok"))
            mock_flash.assert_called_once()
            mock_notify.assert_called_once_with(
                title="Title", message="Message", app_name="jot", timeout=5
            )

    def test_flash_window_windows(self):
        host = DummySystemHost()
        with (
            patch("sys.platform", "win32"),
            patch(
                "jot.utils.win32_window_utils.get_window_hwnd",
                return_value=12345,
            ),
            patch("jot.utils.win32_window_utils.flash_window") as mock_flash,
        ):
            res = host.flash_window()
            self.assertTrue(res.get("ok"))
            mock_flash.assert_called_once_with(12345)

    def test_flash_window_non_windows(self):
        host = DummySystemHost()
        with patch("sys.platform", "linux"):
            res = host.flash_window()
            self.assertTrue(res.get("ok"))

    def test_download_and_install_update(self):
        host = DummySystemHost()
        with patch("jot.core.updater.download_and_install_update") as mock_upd:
            mock_upd.return_value = {"ok": True}
            res = host.download_and_install_update("2.0.0")
            self.assertTrue(res.get("ok"))
            mock_upd.assert_called_once_with("2.0.0", emit_fn=host._adapter.emit)


class TestSettingsController(unittest.TestCase):
    def test_load_settings(self):
        host = DummySettingsHost()
        with patch(
            "jot.bridge.controllers.settings_controller.load_config"
        ) as mock_cfg:
            mock_cfg.return_value = {
                "api_key": "k",
                "fallback_keys": ["k2"],
                "preferred_model": "model-1",
                "fallback_models": ["model-2"],
                "has_protected_key": True,
                "api_key_insecure": False,
                "config_recovered_from": "backup.json",
                "credential_storage": {
                    "primary": "protected",
                    "fallback": "session_only",
                },
            }
            res = host.load_settings()
            self.assertEqual(res["api_key"], "k")
            self.assertEqual(res["config_recovered_from"], "backup.json")
            self.assertEqual(res["credential_storage"]["fallback"], "session_only")
            self.assertTrue(res["has_protected_key"])

    def test_load_settings_fallback_on_exception(self):
        host = DummySettingsHost()
        with patch(
            "jot.bridge.controllers.settings_controller.load_config",
            side_effect=Exception("bad file"),
        ):
            res = host.load_settings()
            self.assertEqual(res["api_key"], "")
            self.assertFalse(res["has_protected_key"])

    def test_save_settings(self):
        host = DummySettingsHost()
        with (
            patch(
                "jot.bridge.controllers.settings_controller.save_config"
            ) as mock_save,
            patch(
                "jot.bridge.controllers.settings_controller.load_config",
                return_value={"api_key_insecure": True},
            ),
        ):
            mock_save.return_value = {
                "primary": "session_only",
                "fallback": "protected",
            }
            res = host.save_settings("k", ["k2"], "m1", ["m2"])
            self.assertEqual(res["credential_storage"], mock_save.return_value)
            self.assertTrue(res["api_key_insecure"])
            self.assertTrue(res.get("ok"))
            mock_save.assert_called_once_with(
                "k", fallback_keys=["k2"], preferred_model="m1", fallback_models=["m2"]
            )

    def test_save_theme_preference(self):
        host = DummySettingsHost()
        with tempfile.TemporaryDirectory() as td:
            pref_file = os.path.join(td, "theme.txt")
            with patch(
                "jot.bridge.controllers.settings_controller.THEME_PREF_FILE",
                pref_file,
            ):
                host.save_theme_preference("dark")
                with open(pref_file) as f:
                    self.assertEqual(f.read(), "dark")

                host.save_theme_preference("invalid")
                with open(pref_file) as f:
                    self.assertEqual(f.read(), "dark")

    def test_ask_session_folder(self):
        win = MagicMock()
        win.create_file_dialog.return_value = ["/path/to/folder"]
        host = DummySettingsHost(window=win)
        res = host.ask_session_folder()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("path"), "/path/to/folder")

        # Cancelled
        win.create_file_dialog.return_value = None
        res2 = host.ask_session_folder()
        self.assertFalse(res2.get("ok"))
        self.assertTrue(res2.get("cancelled"))

        # No window
        host_no_win = DummySettingsHost(window=None)
        res3 = host_no_win.ask_session_folder()
        self.assertFalse(res3.get("ok"))

    def test_move_session_root_validation(self):
        with tempfile.TemporaryDirectory() as td:
            old_root = os.path.join(td, "old_sessions")
            os.makedirs(old_root, exist_ok=True)
            with patch(
                "jot.bridge.controllers.settings_controller.get_session_root",
                return_value=old_root,
            ):
                host = DummySettingsHost()
                self.assertFalse(host.move_session_root("").get("ok"))
                self.assertFalse(host.move_session_root("relative/path").get("ok"))
                self.assertFalse(host.move_session_root(old_root).get("ok"))
                nested = os.path.join(old_root, "nested")
                self.assertFalse(host.move_session_root(nested).get("ok"))

                # Processing thread busy
                busy_thread = MagicMock()
                busy_thread.is_alive.return_value = True
                host._processing_thread = busy_thread
                new_root = os.path.join(td, "new_sessions")
                self.assertFalse(host.move_session_root(new_root).get("ok"))
                host._processing_thread = None

                # Already moving
                host._move_state["status"] = "moving"
                self.assertFalse(host.move_session_root(new_root).get("ok"))

    def test_do_move_session_root_success(self):
        with tempfile.TemporaryDirectory() as td:
            old_root = os.path.join(td, "old_sessions")
            new_root = os.path.join(td, "new_sessions")
            os.makedirs(old_root, exist_ok=True)
            with open(os.path.join(old_root, "sess1.txt"), "w") as f:
                f.write("content")

            with patch(
                "jot.services.folders_service.migrate_session_roots"
            ) as mock_mig:
                host = DummySettingsHost()
                host._do_move_session_root(old_root, new_root)
                status = host.get_session_move_status()
                self.assertEqual(status["status"], "done")
                self.assertEqual(status["old_root"], old_root)
                self.assertEqual(status["new_root"], new_root)
                self.assertTrue(os.path.isdir(new_root))
                self.assertTrue(os.path.exists(os.path.join(new_root, "sess1.txt")))
                mock_mig.assert_called_once_with(old_root, new_root)


class TestMediaController(unittest.TestCase):
    def test_validate_media_path(self):
        with tempfile.TemporaryDirectory() as td:
            valid_mp3 = os.path.join(td, "test.mp3")
            with open(valid_mp3, "wb") as f:
                f.write(b"fake mp3 data")

            valid_txt = os.path.join(td, "test.txt")
            with open(valid_txt, "w") as f:
                f.write("text")

            # Nonexistent
            ok, _err, _dur = MediaControllerMixin._validate_media_path(
                os.path.join(td, "nonexistent.mp3")
            )
            self.assertFalse(ok)

            # Unsupported ext
            ok, _err, _dur = MediaControllerMixin._validate_media_path(valid_txt)
            self.assertFalse(ok)

            # Valid media without duration check
            ok, _err, _dur = MediaControllerMixin._validate_media_path(
                valid_mp3, require_duration=False
            )
            self.assertTrue(ok)

            # Valid media with duration check
            with patch(
                "jot.services.audio_service.probe_media_duration",
                return_value=(42.0, None),
            ):
                ok, _err, dur = MediaControllerMixin._validate_media_path(
                    valid_mp3, require_duration=True
                )
                self.assertTrue(ok)
                self.assertEqual(dur, 42.0)

            # Extensionless media with valid audio probe
            ext_audio = os.path.join(td, "Fisiologia II Lezione 1 pt 1")
            with open(ext_audio, "wb") as f:
                f.write(b"m4a container data")

            with patch(
                "jot.services.audio_service.probe_media_duration",
                return_value=(3320.0, None),
            ):
                ok, _err, dur = MediaControllerMixin._validate_media_path(
                    ext_audio, require_duration=False
                )
                self.assertTrue(ok)
                self.assertEqual(dur, 3320.0)

                ok2, _err2, dur2 = MediaControllerMixin._validate_media_path(
                    ext_audio, require_duration=True
                )
                self.assertTrue(ok2)
                self.assertEqual(dur2, 3320.0)

            # Extensionless media with dots in filename (e.g. date)
            dotted_audio = os.path.join(td, "Fisiologia II Lezione 10.10.2024")
            with open(dotted_audio, "wb") as f:
                f.write(b"m4a container data")

            with patch(
                "jot.services.audio_service.probe_media_duration",
                return_value=(2800.0, None),
            ) as mock_probe:
                ok, _err, dur = MediaControllerMixin._validate_media_path(
                    dotted_audio, require_duration=False
                )
                self.assertTrue(ok)
                self.assertEqual(dur, 2800.0)

                # Verify _build_valid_media_descriptor does not re-probe duration
                mock_probe.reset_mock()
                host = DummyMediaHost()
                desc = host._build_valid_media_descriptor(dotted_audio)
                self.assertIsNotNone(desc)
                assert desc is not None
                self.assertEqual(desc.get("duration"), 2800.0)
                mock_probe.assert_called_once()

            # Extensionless non-media file (probe returns no duration)
            ext_text = os.path.join(td, "README")
            with open(ext_text, "w") as f:
                f.write("text without extension")

            with patch(
                "jot.services.audio_service.probe_media_duration",
                return_value=(None, "duration_NA"),
            ):
                ok, _err, dur = MediaControllerMixin._validate_media_path(
                    ext_text, require_duration=False
                )
                self.assertFalse(ok)
                self.assertIsNone(dur)

    def test_supported_media_label_includes_all_formats(self):
        label = MediaControllerMixin._SUPPORTED_MEDIA_LABEL
        for ext in [
            "OPUS",
            "MOV",
            "3GP",
            "MP3",
            "M4A",
            "WAV",
            "OGG",
            "FLAC",
            "AAC",
            "MP4",
            "MKV",
        ]:
            self.assertIn(ext, label)

    def test_ask_files_no_window(self):
        host = DummyMediaHost(window=None)
        self.assertEqual(host.ask_files(), [])
        self.assertIsNone(host.ask_media_file())

    def test_ask_files_with_dialog(self):
        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "a.mp3")
            with open(f1, "w") as f:
                f.write("test")

            win = MagicMock()
            win.create_file_dialog.return_value = [f1]
            host = DummyMediaHost(window=win)

            with patch(
                "jot.services.audio_service.probe_media_duration",
                return_value=(10.0, None),
            ):
                res = host.ask_files()
                self.assertEqual(len(res), 1)
                self.assertEqual(res[0]["path"], f1)

                single = host.ask_media_file()
                self.assertIsNotNone(single)
                assert single is not None
                self.assertEqual(single["path"], f1)

    def test_check_path_exists(self):
        host = DummyMediaHost()
        self.assertFalse(host.check_path_exists("/nonexistent/file")["exists"])

    def test_collect_dropped_files_extensionless(self):
        with tempfile.TemporaryDirectory() as td:
            ext_audio = os.path.join(td, "Fisiologia II Lezione 1 pt 1")
            with open(ext_audio, "wb") as f:
                f.write(b"fake audio data")

            host = DummyMediaHost()
            with (
                patch(
                    "jot.bridge.controllers.media_controller._drain_dnd_paths",
                    return_value=[("Fisiologia II Lezione 1 pt 1", ext_audio)],
                ),
                patch(
                    "jot.services.audio_service.probe_media_duration",
                    return_value=(3320.0, None),
                ),
            ):
                res = host.collect_dropped_files(["Fisiologia II Lezione 1 pt 1"])
                self.assertTrue(res.get("ok"))
                mock_emit = cast(MagicMock, host._adapter.emit)
                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                self.assertEqual(call_args[0][0], "filesDropped")
                descriptors = call_args[0][1]
                self.assertEqual(len(descriptors), 1)
                self.assertEqual(descriptors[0]["path"], ext_audio)
                self.assertEqual(descriptors[0]["duration"], 3320.0)


class TestHtmlController(unittest.TestCase):
    def test_read_html_content_invalid_extension(self):
        host = DummyHtmlHost()
        res = host.read_html_content("document.pdf")
        self.assertFalse(res.get("ok"))
        self.assertIn(".html", res.get("error", ""))

    def test_read_html_content_valid(self):
        with tempfile.TemporaryDirectory() as td:
            session_root = os.path.join(td, "sessions")
            os.makedirs(session_root, exist_ok=True)
            html_file = os.path.join(session_root, "test.html")
            with open(html_file, "w", encoding="utf-8") as f:
                f.write("<html><body><h1>Hello</h1></body></html>")

            host = DummyHtmlHost(session_root=session_root)
            res = host.read_html_content(html_file)
            self.assertTrue(res.get("ok"))
            self.assertIn("Hello", res.get("content", ""))


class TestSessionController(unittest.TestCase):
    def test_get_session_storage_info(self):
        host = DummySessionHost()
        with (
            patch(
                "jot.bridge.controllers.session_controller.get_session_storage_info",
                return_value={"total_bytes": 1024, "total_sessions": 3},
            ),
            patch(
                "jot.bridge.controllers.session_controller.get_session_root",
                return_value="/dummy/root",
            ),
        ):
            res = host.get_session_storage_info()
            self.assertTrue(res["ok"])
            self.assertEqual(res["total_bytes"], 1024)
            self.assertEqual(res["total_sessions"], 3)
            self.assertEqual(res["session_root"], "/dummy/root")

    def test_get_session_storage_info_error(self):
        host = DummySessionHost()
        with patch(
            "jot.bridge.controllers.session_controller.get_session_storage_info",
            side_effect=RuntimeError("storage error"),
        ):
            res = host.get_session_storage_info()
            self.assertFalse(res["ok"])
            self.assertIn("storage error", res["error"])

    def test_get_and_save_archive_folders(self):
        host = DummySessionHost()
        with (
            patch(
                "jot.services.folders_service.get_folders",
                return_value=[{"id": "f1", "name": "Folder 1"}],
            ),
            patch("jot.services.folders_service.save_folders") as mock_save,
        ):
            res_get = host.get_archive_folders()
            self.assertTrue(res_get["ok"])
            self.assertEqual(len(res_get["folders"]), 1)

            res_save_invalid = host.save_archive_folders("not-a-list")  # type: ignore[arg-type]
            self.assertFalse(res_save_invalid["ok"])

            res_save = host.save_archive_folders([{"id": "f1", "name": "Folder 1"}])
            self.assertTrue(res_save["ok"])
            mock_save.assert_called_once()

    def test_get_completed_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            session_root = os.path.join(td, "sessions")
            os.makedirs(session_root, exist_ok=True)
            host = DummySessionHost(session_root=session_root)

            # Empty
            res = host.get_completed_sessions()
            self.assertTrue(res["ok"])
            self.assertEqual(res["sessions"], [])

            # Create a completed session
            s1_dir = os.path.join(session_root, "sess_1")
            os.makedirs(s1_dir, exist_ok=True)
            html_path = os.path.join(s1_dir, "doc.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write("<html><body>Test Document</body></html>")

            import json

            s1_data = {
                "stage": "done",
                "updated_at": "2026-08-01T12:00:00Z",
                "outputs": {"html": html_path},
                "input": {"path": "/fake/input.mp3", "size": 1234},
                "metadata": {"title": "Test Title"},
            }
            with open(os.path.join(s1_dir, "session.json"), "w", encoding="utf-8") as f:
                json.dump(s1_data, f)

            res = host.get_completed_sessions()
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["sessions"]), 1)
            self.assertEqual(res["sessions"][0]["name"], "input.mp3")

    def test_get_completed_sessions_respects_title(self):
        with tempfile.TemporaryDirectory() as td:
            session_root = os.path.join(td, "sessions")
            os.makedirs(session_root, exist_ok=True)
            host = DummySessionHost(session_root=session_root)
            s1_dir = os.path.join(session_root, "sess1")
            os.makedirs(s1_dir, exist_ok=True)
            html_path = os.path.join(s1_dir, "doc.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write("<html><body>Test Document</body></html>")

            import json

            s1_data = {
                "stage": "done",
                "title": "Biochimica",
                "updated_at": "2026-08-01T12:00:00Z",
                "outputs": {"html": html_path},
                "input": {"path": "/fake/altro.mp3", "size": 1234},
            }
            with open(os.path.join(s1_dir, "session.json"), "w", encoding="utf-8") as f:
                json.dump(s1_data, f)

            res = host.get_completed_sessions()
            self.assertTrue(res["ok"])
            self.assertEqual(res["sessions"][0]["name"], "Biochimica")

    def test_remove_session_audio(self):
        with tempfile.TemporaryDirectory() as td:
            session_root = os.path.join(td, "sessions")
            os.makedirs(session_root, exist_ok=True)
            host = DummySessionHost(session_root=session_root)
            s1_dir = os.path.join(session_root, "sess1")
            os.makedirs(s1_dir, exist_ok=True)
            html_path = os.path.join(s1_dir, "Doc_Sbobina.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write("<html><body>Test Document</body></html>")

            import json

            s1_data = {
                "stage": "done",
                "updated_at": "2026-08-01T12:00:00Z",
                "outputs": {"html": html_path},
                "input": {"path": "/fake/input.mp3", "name": "input.mp3", "size": 1234},
            }
            session_json_path = os.path.join(s1_dir, "session.json")
            with open(session_json_path, "w", encoding="utf-8") as f:
                json.dump(s1_data, f)

            res = host.remove_session_audio(s1_dir)
            self.assertTrue(res["ok"])

            with open(session_json_path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["input"]["path"], "")
            self.assertEqual(saved["input"]["name"], "")
            self.assertEqual(saved["title"], "Doc")

    def test_search_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            session_root = os.path.join(td, "sessions")
            os.makedirs(session_root, exist_ok=True)
            host = DummySessionHost(session_root=session_root)

            # Query too short
            res = host.search_sessions("a")
            self.assertFalse(res["ok"])
            self.assertEqual(res["results"], [])
            self.assertEqual(res["total"], 0)


class TestSystemControllerDiagnostics(unittest.TestCase):
    def test_get_api_usage(self):
        host = DummySystemHost()
        res = host.get_api_usage(
            api_key="AIzaSyTestKey1234567890",
            fallback_keys=[],
            preferred_model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
        )
        self.assertTrue(res["ok"])
        self.assertIn("result", res)
        self.assertIn("keys", res["result"])
        self.assertIn("estimated_sbobine_remaining", res["result"])

    def test_get_diagnostic_report(self):
        host = DummySystemHost()
        res = host.get_diagnostic_report(
            api_key="AIzaSyTestKey1234567890",
            preferred_model="gemini-2.5-flash",
        )
        self.assertTrue(res["ok"])
        self.assertIn("report", res)
        self.assertIn("Report Diagnostico", res["report"])

    @patch("jot.utils.file_ops.open_path_with_default_app")
    def test_open_logs_folder(self, mock_open_path):
        host = DummySystemHost()
        res = host.open_logs_folder()
        self.assertTrue(res["ok"])
        mock_open_path.assert_called_once()


if __name__ == "__main__":
    unittest.main()
