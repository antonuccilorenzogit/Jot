import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

from jot.bridge.controllers.system_controller import SystemControllerMixin
from jot.services import diagnostics_service as ds
from jot.utils import logging_utils as lu


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.config = self.base / "config"
        self.config.mkdir()
        self.root = self.base / "archive"
        self.root.mkdir()
        self.session = self.root / "lesson"
        self.session.mkdir()
        self.secret = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        data = {
            "stage": "phase2",
            "last_error": "autosave_failed",
            "input": {"path": str(self.base / "private_lecture.wav"), "size": 123},
            "phase1": {"chunks_done": 4, "memoria_precedente": "PRIVATE_TRANSCRIPT"},
            "phase2": {"revised_done": 2},
            "settings": {"api_key": self.secret},
        }
        (self.session / "session.json").write_text(json.dumps(data), encoding="utf-8")
        (self.session / "run.log").write_text(
            "autosave_failed api_key=" + self.secret, encoding="utf-8"
        )
        (self.config / "config.json").write_text(
            json.dumps({"api_key": self.secret, "preferred_model": "gemini-test"}),
            encoding="utf-8",
        )
        self.patches = [
            patch.object(ds, "get_config_dir", return_value=str(self.config)),
            patch(
                "jot.services.config_service.get_config_dir",
                return_value=str(self.config),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for handler in list(lu.configure_logging().handlers):
            if getattr(handler, "_el_general_log", False) or isinstance(
                handler, lu.IncidentHandler
            ):
                lu.detach_file_handler(handler)
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def test_export_whitelists_metadata_and_preserves_failure_context(self):
        files = ds.collect_files(str(self.root), str(self.session), "v1.2.3")
        combined = "\n".join(files.values())
        self.assertNotIn(self.secret, combined)
        self.assertNotIn("PRIVATE_TRANSCRIPT", combined)
        self.assertNotIn("private_lecture.wav", combined)
        self.assertNotIn("config.json", files)
        self.assertNotIn("session.json", files)
        summary = json.loads(files["session_summary.json"])
        self.assertEqual(summary["stage"], "phase2")
        self.assertEqual(summary["phase1"]["chunks_done"], 4)
        self.assertIn("autosave_failed", files["logs/selected_run.log"])
        target = ds.export_bundle(str(self.base / "support.zip"), files)
        with zipfile.ZipFile(target) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()), set(files))

    def test_general_export_has_no_session_data_and_reads_rotated_log(self):
        (self.config / "jot.log.1").write_text("OLDER_FAILURE", encoding="utf-8")
        files = ds.collect_files(str(self.root))
        self.assertIn("OLDER_FAILURE", files["report.md"])
        self.assertNotIn("session_summary.json", files)

    def test_session_labels_prefer_title_then_filename_without_extension(self):
        metadata = self.session / "session.json"
        data = json.loads(metadata.read_text(encoding="utf-8"))
        self.assertEqual(
            ds.list_sessions(str(self.root))[0]["label"], "private_lecture"
        )
        data["title"] = "  Fisiologia - Lezione 2  "
        metadata.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(
            ds.list_sessions(str(self.root))[0]["label"], "Fisiologia - Lezione 2"
        )
        data["title"] = " "
        data["input"] = {}
        metadata.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(ds.list_sessions(str(self.root))[0]["label"], "lesson")

    def test_selection_cannot_read_outside_archive_or_follow_log_symlink(self):
        with self.assertRaises(ValueError):
            ds.collect_files(str(self.root), str(self.config))
        with self.assertRaises(ValueError):
            ds.collect_files(str(self.root), str(self.root))
        with patch.object(Path, "is_symlink", return_value=True):
            self.assertEqual(ds.read_text(self.session / "run.log"), "")

    def test_corrupt_and_large_files_are_bounded(self):
        (self.config / "startup_diagnostic.json").write_text(
            "bad json", encoding="utf-8"
        )
        (self.config / "jot.log").write_text("x" * (ds.MAX_BYTES * 3), encoding="utf-8")
        files = ds.collect_files(str(self.root))
        self.assertNotIn("startup_diagnostic.json", files)
        self.assertLessEqual(len(files["logs/jot.log"]), ds.MAX_BYTES)

    def test_failure_survives_successful_restart_and_pipeline_warning(self):
        lu.record_startup_diagnostic(status="recovery", native_error="FAILED_STARTUP")
        lu.record_startup_diagnostic(status="detected")
        lu.get_logger("jot.pipeline", run_id="op", session_dir="session").error(
            "PIPELINE_ERROR"
        )
        lu.get_logger().warning("LATER_WARNING")
        files = ds.collect_files(str(self.root))
        self.assertIn("FAILED_STARTUP", files["startup_failure.json"])
        self.assertIn("PIPELINE_ERROR", files["last_failure.json"])
        self.assertIn("PIPELINE_ERROR", files["incidents.json"])

    def test_listing_returns_labels_and_export_failure_leaves_no_partial_zip(self):
        sessions = ds.list_sessions(str(self.root))
        self.assertEqual(sessions[0]["path"], str(self.session))
        self.assertEqual(sessions[0]["label"], "private_lecture")
        destination = self.base / "existing.zip"
        destination.write_bytes(b"original")
        with patch("os.replace", side_effect=PermissionError()):
            with self.assertRaises(PermissionError):
                ds.export_bundle(str(destination), {"report.md": "hello"})
        self.assertEqual(destination.read_bytes(), b"original")
        self.assertEqual(list(self.base.glob("*.zip")), [destination])

    def test_build_info_uses_packaged_manifest(self):
        (self.base / "diagnostic_build.json").write_text(
            '{"version":"2.0.0","commit":"abc"}', encoding="utf-8"
        )
        with patch.object(ds.sys, "_MEIPASS", str(self.base), create=True):
            self.assertEqual(ds.build_info()["version"], "2.0.0")

    def test_macos_build_info_resolves_internal_metadata_link(self):
        contents = self.base / "jot.app" / "Contents"
        frameworks = contents / "Frameworks"
        resources = contents / "Resources"
        frameworks.mkdir(parents=True)
        resources.mkdir()
        metadata = resources / "diagnostic_build.json"
        metadata.write_text('{"version":"2.7.3","commit":"abc","mode":"packaged"}')
        link = frameworks / metadata.name
        resolve = Path.resolve

        def resolve_metadata(path, *args, **kwargs):
            return metadata if path == link else resolve(path, *args, **kwargs)

        with (
            patch.object(ds.sys, "_MEIPASS", str(frameworks), create=True),
            patch.object(ds.sys, "frozen", True, create=True),
            patch.object(ds.sys, "platform", "darwin"),
            patch.object(Path, "resolve", resolve_metadata),
        ):
            self.assertEqual(
                ds.build_info(),
                {"version": "2.7.3", "commit": "abc", "mode": "packaged"},
            )

    def test_macos_build_info_reads_real_pyinstaller_symlink(self):
        contents = self.base / "jot.app" / "Contents"
        frameworks = contents / "Frameworks"
        resources = contents / "Resources"
        frameworks.mkdir(parents=True)
        resources.mkdir()
        metadata = resources / "diagnostic_build.json"
        metadata.write_text('{"version":"2.7.3","commit":"abc"}')
        link = frameworks / metadata.name
        try:
            link.symlink_to(Path("..") / "Resources" / metadata.name)
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        self.assertEqual(ds.read_json(link), {})
        with (
            patch.object(ds.sys, "_MEIPASS", str(frameworks), create=True),
            patch.object(ds.sys, "frozen", True, create=True),
            patch.object(ds.sys, "platform", "darwin"),
        ):
            self.assertEqual(ds.build_info()["version"], "2.7.3")

    def test_build_metadata_rejects_link_outside_installation(self):
        contents = self.base / "jot.app" / "Contents"
        frameworks = contents / "Frameworks"
        frameworks.mkdir(parents=True)
        outside = self.base / "outside.json"
        outside.write_text('{"version":"2.7.3"}')
        link = frameworks / "diagnostic_build.json"
        resolve = Path.resolve

        def resolve_metadata(path, *args, **kwargs):
            return outside if path == link else resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve_metadata):
            self.assertEqual(ds.read_build_metadata(frameworks, macos_bundle=True), {})

    def test_build_metadata_rejects_frameworks_directory_outside_bundle(self):
        contents = self.base / "jot.app" / "Contents"
        frameworks = contents / "Frameworks"
        contents.mkdir(parents=True)
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "diagnostic_build.json").write_text('{"version":"2.7.3"}')
        resolve = Path.resolve

        def resolve_frameworks(path, *args, **kwargs):
            return outside if path == frameworks else resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve_frameworks):
            self.assertEqual(ds.read_build_metadata(frameworks, macos_bundle=True), {})

    def test_packaged_build_info_does_not_fallback_to_frontend_version(self):
        webui = self.base / "webui"
        (webui / "dist").mkdir(parents=True)
        (webui / "package.json").write_text('{"version":"2.7.3"}')
        (webui / "dist" / "desktop-build.json").write_text('{"version":"2.7.3"}')
        with (
            patch.object(ds.sys, "_MEIPASS", str(self.base), create=True),
            patch.object(ds.sys, "frozen", True, create=True),
        ):
            self.assertEqual(
                ds.build_info(), {"version": "unknown", "mode": "packaged"}
            )
        with (
            patch.object(ds.sys, "_MEIPASS", str(self.base), create=True),
            patch.object(ds.sys, "frozen", False, create=True),
        ):
            self.assertEqual(ds.build_info(), {"version": "2.7.3", "mode": "source"})

    def test_build_metadata_rejects_invalid_versions_and_malformed_json(self):
        metadata = self.base / "diagnostic_build.json"
        for version in (None, 123, "", " ", "unknown", "broken", {"version": "2.7.3"}):
            with self.subTest(version=version):
                metadata.write_text(json.dumps({"version": version}))
                self.assertEqual(ds.read_build_metadata(self.base), {})
        for content in ("not json", "[]", '{"version":"2.7.3"' + " " * ds.MAX_BYTES):
            with self.subTest(content=content[:30]):
                metadata.write_text(content)
                self.assertEqual(ds.read_build_metadata(self.base), {})
        metadata.write_text('{"version":" v2.7.3-rc.1+build.2 "}')
        self.assertEqual(
            ds.read_build_metadata(self.base)["version"], "2.7.3-rc.1+build.2"
        )

    def controller(self):
        root = str(self.root)

        class Host(SystemControllerMixin):
            _window: MagicMock

            def _get_session_root(self):
                return root

        host = Host()
        host._window = MagicMock()
        host._logger = MagicMock()
        return host

    def test_native_export_cancel_and_selected_session(self):
        host = self.controller()
        host._window.create_file_dialog.return_value = None
        self.assertTrue(host.export_diagnostics()["cancelled"])
        target = self.base / "support.zip"
        host._window.create_file_dialog.return_value = [str(target)]
        result = host.export_diagnostics(str(self.session), "1.2.3")
        self.assertTrue(result["ok"])
        with zipfile.ZipFile(target) as archive:
            self.assertIn("session_summary.json", archive.namelist())
            self.assertNotIn(self.secret, archive.read("report.md").decode())
        host._window.create_file_dialog.reset_mock()
        self.assertFalse(host.export_diagnostics(str(self.config))["ok"])
        host._window.create_file_dialog.assert_not_called()

    def test_frontend_ready_preserves_native_version_and_previous_failure(self):
        lu.record_startup_diagnostic(status="recovery", native_error="PREVIOUS")
        lu.record_startup_diagnostic(status="detected", version="154.1")
        host = self.controller()
        self.assertFalse(host.record_frontend_event("unsupported")["ok"])
        self.assertFalse(host.record_frontend_event("error", cast(Any, 123))["ok"])
        host.record_frontend_event("ready")
        host.record_frontend_event("ready")
        snapshot = lu.get_startup_diagnostic()
        self.assertEqual(snapshot["status"], "ui_ready")
        self.assertEqual(snapshot["version"], "154.1")
        host.record_frontend_event("react", "render failed", "stack")
        files = ds.collect_files(str(self.root))
        self.assertIn("PREVIOUS", files["startup_failure.json"])
        self.assertIn("render failed", files["last_failure.json"])

    def test_uncaught_hooks_chain_existing_handlers_and_record_threads(self):
        main, thread = MagicMock(), MagicMock()
        with (
            patch.object(lu.sys, "excepthook", main),
            patch.object(lu.threading, "excepthook", thread),
        ):
            # MagicMock attributes are truthy unless explicitly cleared.
            main._el_diagnostic_hook = False
            lu.install_exception_hooks()
            lu.sys.excepthook(ValueError, ValueError("MAIN_FAILURE"), None)
            lu.threading.excepthook(
                cast(
                    Any,
                    SimpleNamespace(
                        exc_type=RuntimeError,
                        exc_value=RuntimeError("THREAD_FAILURE"),
                        exc_traceback=None,
                    ),
                )
            )
            main.assert_called_once()
            thread.assert_called_once()
            files = ds.collect_files(str(self.root))
            self.assertIn("MAIN_FAILURE", files["incidents.json"])
            self.assertIn("THREAD_FAILURE", files["last_failure.json"])

    def test_explicit_validation_is_cached_redacted_and_bounded(self):
        ds.save_validation_snapshot(
            {
                "ok": False,
                "checks": [
                    {
                        "id": "api_key",
                        "message": "api_key=" + self.secret,
                        "private": "NO_EXPORT",
                    }
                ],
            }
        )
        content = ds.collect_files(str(self.root))["last_validation.json"]
        self.assertNotIn(self.secret, content)
        self.assertNotIn("NO_EXPORT", content)
        self.assertEqual(json.loads(content)["checks"][0]["id"], "api_key")

    def test_multibyte_incidents_stay_readable_and_keep_latest_failure(self):
        for index in range(30):
            lu.record_incident("frontend", str(index) + "🙂" * 3000, "🙂" * 6000)
        path = self.config / "incidents.json"
        self.assertLess(path.stat().st_size, ds.MAX_BYTES)
        events = json.loads(ds.collect_files(str(self.root))["incidents.json"])[
            "events"
        ]
        self.assertTrue(events[-1]["message"].startswith("29"))
        self.assertLessEqual(len(events), 20)

    def test_pipeline_failure_keeps_operation_and_per_call_stage(self):
        lu.initialize_app_logging()
        lu.get_logger(
            "jot.pipeline", run_id="operation42", session_dir="selected"
        ).error("FAILED", extra={"stage": "phase2"})
        event = json.loads(ds.collect_files(str(self.root))["last_failure.json"])
        self.assertEqual(event["operation"], "operation42")
        self.assertEqual(event["stage"], "phase2")
