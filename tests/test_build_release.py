import argparse
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"
_SPEC = importlib.util.spec_from_file_location("build_release_module", _MODULE_PATH)
assert _SPEC is not None
build_release = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(build_release)


class BuildReleaseTests(unittest.TestCase):
    def test_command_build_refreshes_manifest_before_packaging(self):
        for target in ("windows", "macos"):
            for existing in (False, True):
                with self.subTest(target=target, existing=existing):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        root = Path(tmpdir)
                        webui = root / "webui"
                        webui.mkdir()
                        (webui / "package.json").write_text('{"version":"1.0.0"}')
                        manifest = root / "build" / "diagnostic_build.json"
                        if existing:
                            manifest.parent.mkdir()
                            manifest.write_text('{"version":"stale"}')
                        args = argparse.Namespace(
                            target=target,
                            ui="webui",
                            install_deps=False,
                            skip_checks=True,
                            skip_npm_install=True,
                            skip_postbuild_smoke=True,
                            version="v2.1.0",
                        )

                        def verify_manifest(command, manifest_path=manifest, **kwargs):
                            info = json.loads(manifest_path.read_text())
                            self.assertEqual(info["version"], "2.1.0")
                            self.assertEqual(info["commit"], "current-commit")
                            self.assertTrue(
                                any(str(manifest_path) in arg for arg in command)
                            )

                        with (
                            patch.object(build_release, "ROOT", root),
                            patch.object(build_release, "WEBUI_DIR", webui),
                            patch.object(
                                build_release, "print_windows_webview2_notice"
                            ),
                            patch.object(build_release, "build_webui") as build_webui,
                            patch.object(
                                build_release, "run", side_effect=verify_manifest
                            ) as run,
                            patch.object(build_release, "run_inno_setup"),
                            patch.object(build_release, "run_create_dmg"),
                            patch.object(
                                build_release.subprocess,
                                "run",
                                return_value=MagicMock(stdout="current-commit\n"),
                            ),
                        ):
                            build_release.command_build(args)
                        run.assert_called_once()
                        build_webui.assert_called_once_with(
                            skip_npm_install=True, version="2.1.0"
                        )

    def test_webui_build_passes_resolved_version_only_to_child_process(self):
        with (
            patch.object(build_release, "install_node_dependencies") as install,
            patch.object(build_release.subprocess, "run") as run,
            patch.dict(os.environ, {"JOT_BUILD_VERSION": "stale"}),
        ):
            build_release.build_webui(skip_npm_install=True, version="2.7.3")
            install.assert_called_once_with(skip_npm_install=True)
            self.assertEqual(run.call_args.kwargs["env"]["JOT_BUILD_VERSION"], "2.7.3")
            self.assertEqual(os.environ["JOT_BUILD_VERSION"], "stale")

    def test_default_build_uses_package_version_for_frontend_and_packaging(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            webui = root / "webui"
            webui.mkdir()
            package_path = webui / "package.json"
            package_content = '{"version":"1.0.0"}'
            package_path.write_text(package_content)
            args = build_release.build_parser().parse_args(
                [
                    "build",
                    "--target",
                    "windows",
                    "--skip-checks",
                    "--skip-npm-install",
                    "--skip-postbuild-smoke",
                ]
            )
            with (
                patch.object(build_release, "ROOT", root),
                patch.object(build_release, "WEBUI_DIR", webui),
                patch.object(build_release, "print_windows_webview2_notice"),
                patch.object(build_release, "build_webui") as build_webui,
                patch.object(build_release, "run"),
                patch.object(build_release, "run_inno_setup") as installer,
                patch.object(
                    build_release.subprocess,
                    "run",
                    return_value=MagicMock(stdout="current-commit\n"),
                ),
            ):
                build_release.command_build(args)
            build_webui.assert_called_once_with(skip_npm_install=True, version="1.0.0")
            installer.assert_called_once_with("1.0.0")
            metadata = json.loads(
                (root / "build" / "diagnostic_build.json").read_text()
            )
            self.assertEqual(metadata["version"], "1.0.0")
            self.assertEqual(package_path.read_text(), package_content)

    def test_build_manifest_records_release_version_and_is_packaged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            webui = root / "webui"
            webui.mkdir()
            (webui / "package.json").write_text('{"version":"1.0.0"}')
            with (
                patch.object(build_release, "ROOT", root),
                patch.object(build_release, "WEBUI_DIR", webui),
                patch.object(
                    build_release.subprocess,
                    "run",
                    return_value=MagicMock(stdout="abc123\n"),
                ),
            ):
                build_release.write_build_metadata("v2.1.0")
                info = json.loads(
                    (root / "build" / "diagnostic_build.json").read_text()
                )
                self.assertEqual(info["version"], "2.1.0")
                self.assertEqual(info["commit"], "abc123")
                self.assertTrue(
                    any(
                        "diagnostic_build.json" in item
                        for item in build_release.pyinstaller_command(
                            "windows", "webview"
                        )
                    )
                )

    def test_postbuild_smoke_fails_when_artifact_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(build_release, "ROOT", Path(tmpdir)):
                with self.assertRaises(FileNotFoundError):
                    build_release.run_postbuild_smoke("windows")

    def test_postbuild_smoke_runs_smoke_script_when_artifact_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact_dir = root / "dist" / build_release.APP_NAME
            artifact_dir.mkdir(parents=True, exist_ok=True)
            inner_exe = artifact_dir / f"{build_release.APP_NAME}.exe"
            inner_exe.write_bytes(b"ok")

            with (
                patch.object(build_release, "ROOT", root),
                patch.object(build_release, "run") as mock_run,
            ):
                build_release.run_postbuild_smoke("windows")

            mock_run.assert_called_once()

    def test_macos_postbuild_checks_packaged_versions_before_smoke(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            contents = root / "dist" / f"{build_release.APP_NAME}.app" / "Contents"
            frameworks = contents / "Frameworks"
            frontend = frameworks / "webui" / "dist"
            frontend.mkdir(parents=True)
            (root / "build").mkdir()
            generated = root / "build" / "diagnostic_build.json"
            generated.write_text('{"version":"2.7.3"}')
            metadata = frameworks / "diagnostic_build.json"
            manifest = frontend / "desktop-build.json"
            manifest.write_text('{"version":"2.7.3"}')
            with (
                patch.object(build_release, "ROOT", root),
                patch.object(build_release, "run") as run,
            ):
                for content in (None, "invalid json", '{"version":"unknown"}'):
                    if content is not None:
                        metadata.write_text(content)
                    with self.subTest(metadata=content):
                        with self.assertRaisesRegex(RuntimeError, "Metadati"):
                            build_release.run_postbuild_smoke("macos")
                        run.assert_not_called()
                metadata.write_text('{"version":"2.7.2"}')
                with self.assertRaisesRegex(RuntimeError, "incoerenti"):
                    build_release.run_postbuild_smoke("macos")
                metadata.write_text('{"version":"2.7.3"}')
                manifest.write_text('{"version":"2.7.2"}')
                with self.assertRaisesRegex(RuntimeError, "incoerenti"):
                    build_release.run_postbuild_smoke("macos")
                manifest.write_text('{"version":"2.7.3"}')
                generated.write_text('{"version":"2.7.4"}')
                with self.assertRaisesRegex(RuntimeError, "incoerenti"):
                    build_release.run_postbuild_smoke("macos")
                run.assert_not_called()
                generated.write_text('{"version":"2.7.3"}')
                build_release.run_postbuild_smoke("macos")
                run.assert_called_once()

    def test_macos_postbuild_reads_real_pyinstaller_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact = root / "dist" / f"{build_release.APP_NAME}.app"
            contents = artifact / "Contents"
            frameworks = contents / "Frameworks"
            resources = contents / "Resources"
            frameworks.mkdir(parents=True)
            (resources / "webui" / "dist").mkdir(parents=True)
            (root / "build").mkdir()
            content = '{"version":"2.7.3"}'
            (root / "build" / "diagnostic_build.json").write_text(content)
            (resources / "diagnostic_build.json").write_text(content)
            (resources / "webui" / "dist" / "desktop-build.json").write_text(content)
            try:
                (frameworks / "diagnostic_build.json").symlink_to(
                    Path("..") / "Resources" / "diagnostic_build.json"
                )
                (frameworks / "webui").symlink_to(
                    Path("..") / "Resources" / "webui", target_is_directory=True
                )
            except OSError as exc:
                self.skipTest(f"Symlinks unavailable: {exc}")
            with patch.object(build_release, "ROOT", root):
                build_release.verify_macos_build_metadata(artifact)


class Webview2BuildNoticeTests(unittest.TestCase):
    def registry(self):
        registry = MagicMock()
        registry.HKEY_CURRENT_USER = 1
        registry.HKEY_LOCAL_MACHINE = 2
        registry.KEY_READ = 0x20019
        registry.KEY_WOW64_32KEY = 0x200
        registry.KEY_WOW64_64KEY = 0x100
        return registry

    def test_registered_evergreen_version_in_32_bit_view(self):
        registry = self.registry()

        def open_key(root, branch, reserved, flags):
            if root == 2 and flags == registry.KEY_READ | registry.KEY_WOW64_32KEY:
                return MagicMock()
            raise FileNotFoundError()

        registry.OpenKey.side_effect = open_key
        registry.QueryValueEx.return_value = ("154.0.4258.48", 1)
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release, "winreg", registry, create=True),
        ):
            self.assertEqual(
                build_release.get_windows_webview2_runtime_version(), "154.0.4258.48"
            )

    def test_uninstalled_or_malformed_versions_are_not_reported(self):
        for value in (None, "", "0.0.0.0", "broken", "1.2.3", 154):
            with self.subTest(value=value):
                registry = self.registry()
                registry.QueryValueEx.return_value = (value, 1)
                with (
                    patch.object(build_release.os, "name", "nt"),
                    patch.object(build_release, "winreg", registry, create=True),
                ):
                    self.assertIsNone(
                        build_release.get_windows_webview2_runtime_version()
                    )

    def test_leftover_binary_and_uninstall_marker_do_not_count_as_registration(self):
        registry = self.registry()

        def open_key(root, branch, reserved, flags):
            if "Uninstall" in branch or "ClientState" in branch:
                return MagicMock()
            raise FileNotFoundError()

        registry.OpenKey.side_effect = open_key
        registry.QueryValueEx.return_value = ("154.0.4258.48", 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            binary = (
                Path(tmpdir)
                / "Microsoft"
                / "EdgeWebView"
                / "Application"
                / "154.0.4258.48"
                / "msedgewebview2.exe"
            )
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"x")
            with (
                patch.object(build_release.os, "name", "nt"),
                patch.object(build_release, "winreg", registry, create=True),
                patch.dict(
                    build_release.os.environ,
                    {
                        "LOCALAPPDATA": tmpdir,
                        "ProgramFiles": "",
                        "ProgramFiles(x86)": "",
                    },
                ),
            ):
                self.assertIsNone(build_release.get_windows_webview2_runtime_version())

    def test_non_windows_does_not_query_registry(self):
        registry = self.registry()
        with (
            patch.object(build_release.os, "name", "posix"),
            patch.object(build_release, "winreg", registry, create=True),
        ):
            self.assertIsNone(build_release.get_windows_webview2_runtime_version())
        registry.OpenKey.assert_not_called()


class WriteSha256Tests(unittest.TestCase):
    def test_round_trip_digest_matches_known_bytes(self):
        import hashlib

        data = b"hello sha256"
        expected_digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = Path(tmpdir) / "release.exe"
            artifact.write_bytes(data)
            result = build_release.write_sha256(artifact)
            content = result.read_text(encoding="utf-8")
            digest_in_file = content.split()[0]
            self.assertEqual(digest_in_file, expected_digest)

    def test_output_path_has_sha256_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = Path(tmpdir) / "release.exe"
            artifact.write_bytes(b"x")
            result = build_release.write_sha256(artifact)
            self.assertEqual(result.name, "release.exe.sha256")

    def test_output_line_format_includes_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = Path(tmpdir) / "mypkg.dmg"
            artifact.write_bytes(b"dmg content")
            result = build_release.write_sha256(artifact)
            content = result.read_text(encoding="utf-8")
            parts = content.rstrip("\n").split("  ", 1)
            self.assertEqual(len(parts), 2)
            self.assertEqual(parts[1], "mypkg.dmg")
            self.assertTrue(content.endswith("\n"))

    def test_returns_path_to_checksum_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = Path(tmpdir) / "setup.exe"
            artifact.write_bytes(b"data")
            result = build_release.write_sha256(artifact)
            self.assertIsInstance(result, Path)
            self.assertTrue(result.exists())

    def test_large_file_digest_correct(self):
        import hashlib

        data = b"A" * (65536 * 3 + 100)
        expected_digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = Path(tmpdir) / "big.exe"
            artifact.write_bytes(data)
            result = build_release.write_sha256(artifact)
            content = result.read_text(encoding="utf-8")
            self.assertEqual(content.split()[0], expected_digest)


if __name__ == "__main__":
    unittest.main()
