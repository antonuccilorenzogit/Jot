from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

from jot.utils.webview2_recovery import (
    _check_webview2_native,
    build_missing_webview2_html,
    clear_webview2_cache,
    get_boot_bg_color,
    has_webview2_runtime,
    start_webview2_monitor,
)


class Webview2RecoveryTests(unittest.TestCase):
    def setUp(self):
        recorder = patch("jot.utils.webview2_recovery.record_startup_diagnostic")
        self.record_startup = recorder.start()
        self.addCleanup(recorder.stop)

    def native_modules(
        self,
        *,
        selected: bool = False,
        version: str | None = "120.0.2210.144",
        error: Exception | None = None,
    ):
        platforms: Any = ModuleType("webview.platforms")
        wf: Any = ModuleType("webview.platforms.winforms")
        wf.is_chromium = selected
        wf.is_cef = False
        wf.renderer = "edgechromium" if selected else "mshtml"
        wf.BrowserView = MagicMock()
        chromium: Any = ModuleType("webview.platforms.edgechromium")
        chromium.CoreWebView2Environment = MagicMock()
        chromium.CoreWebView2Environment.GetAvailableBrowserVersionString.return_value = version
        chromium.CoreWebView2Environment.GetAvailableBrowserVersionString.side_effect = error
        ie: Any = ModuleType("webview.platforms.mshtml")
        ie._set_ie_mode = MagicMock()
        platforms.winforms = wf
        platforms.edgechromium = chromium
        platforms.mshtml = ie
        return (
            {
                "webview.platforms": platforms,
                "webview.platforms.winforms": wf,
                "webview.platforms.edgechromium": chromium,
                "webview.platforms.mshtml": ie,
            },
            wf,
            chromium,
            ie,
        )

    def test_has_webview2_runtime_non_windows_skips_native_probe(self):
        for platform in ("darwin", "linux"):
            with (
                self.subTest(platform=platform),
                patch.object(sys, "platform", platform),
                patch("jot.utils.webview2_recovery._check_webview2_native") as probe,
            ):
                self.assertTrue(has_webview2_runtime())
                probe.assert_not_called()

    def test_native_loader_overrides_missing_registry_detection(self):
        modules, wf, chromium, _ = self.native_modules(selected=False)
        with patch.dict(sys.modules, modules):
            self.assertTrue(_check_webview2_native())
        chromium.CoreWebView2Environment.GetAvailableBrowserVersionString.assert_called_once_with(
            None
        )
        self.assertTrue(wf.is_chromium)
        self.assertTrue(self.record_startup.call_args.kwargs["runtime_available"])
        self.assertEqual(wf.renderer, "edgechromium")
        self.assertIs(wf.Chromium, chromium)

    def test_cached_chromium_selection_still_requires_native_confirmation(self):
        modules, wf, _, ie = self.native_modules(
            selected=True, error=FileNotFoundError()
        )
        with patch.dict(sys.modules, modules):
            self.assertFalse(_check_webview2_native())
        self.assertFalse(wf.is_chromium)
        self.assertEqual(wf.renderer, "mshtml")
        self.assertIs(wf.IE, ie)
        ie._set_ie_mode.assert_called_once()
        self.assertIn(
            "FileNotFoundError", self.record_startup.call_args.kwargs["native_error"]
        )

    def test_native_loader_confirms_already_selected_chromium(self):
        modules, wf, chromium, _ = self.native_modules(selected=True)
        with patch.dict(sys.modules, modules):
            self.assertTrue(_check_webview2_native())
        chromium.CoreWebView2Environment.GetAvailableBrowserVersionString.assert_called_once_with(
            None
        )
        self.assertTrue(wf.is_chromium)

    def test_empty_native_version_uses_recovery_renderer(self):
        for version in (None, "", "   "):
            with self.subTest(version=version):
                modules, wf, _, _ = self.native_modules(selected=True, version=version)
                with patch.dict(sys.modules, modules):
                    self.assertFalse(_check_webview2_native())
                self.assertEqual(wf.renderer, "mshtml")

    def test_check_webview2_native_handles_import_error(self):
        with patch.dict(sys.modules, {"webview.platforms.winforms": None}):
            self.assertFalse(_check_webview2_native())

    def test_missing_edge_loader_uses_recovery_renderer(self):
        modules, wf, _, _ = self.native_modules(selected=True)
        modules["webview.platforms"].edgechromium = None
        modules["webview.platforms.edgechromium"] = None
        with patch.dict(sys.modules, modules):
            self.assertFalse(_check_webview2_native())
        self.assertEqual(wf.renderer, "mshtml")

    def test_leftover_binary_and_stale_registry_cannot_unlock_webui(self):
        modules, wf, _, _ = self.native_modules(
            selected=True, error=FileNotFoundError()
        )
        registry = MagicMock()
        registry.QueryValueEx.return_value = (r"C:\deleted-runtime", 1)
        modules["winreg"] = registry
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = os.path.join(
                tmpdir, "Microsoft", "EdgeWebView", "Application", "154.0.4258.37"
            )
            os.makedirs(app_dir)
            with open(os.path.join(app_dir, "msedgewebview2.exe"), "wb") as f:
                f.write(b"x")
            with (
                patch.object(sys, "platform", "win32"),
                patch.dict(sys.modules, modules),
                patch.dict(
                    os.environ,
                    {
                        "LOCALAPPDATA": tmpdir,
                        "ProgramFiles": "",
                        "ProgramFiles(x86)": "",
                    },
                ),
            ):
                self.assertFalse(has_webview2_runtime())
        self.assertEqual(wf.renderer, "mshtml")

    def test_polling_installation_preserves_live_mshtml_window(self):
        modules, wf, _, ie = self.native_modules(selected=False)
        wf.IE = ie
        original_browser = wf.BrowserView
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, modules),
        ):
            self.assertTrue(has_webview2_runtime(activate_renderer=False))
        self.assertFalse(wf.is_chromium)
        self.assertEqual(wf.renderer, "mshtml")
        self.assertIs(wf.IE, ie)
        self.assertIs(wf.BrowserView, original_browser)
        ie._set_ie_mode.assert_not_called()
        self.record_startup.assert_not_called()

    def test_renderer_setup_error_is_handled(self):
        modules, _, _, ie = self.native_modules(error=FileNotFoundError())
        ie._set_ie_mode.side_effect = OSError("Cannot configure recovery renderer")
        with patch.dict(sys.modules, modules):
            self.assertFalse(_check_webview2_native())

    def test_build_missing_webview2_html(self):
        html = build_missing_webview2_html()
        self.assertIn("<!doctype html>", html)
        self.assertIn("Serve WebView2", html)
        self.assertIn("jot.log", html)
        self.assertIn("status-box", html)
        self.assertIn("status-dot", html)
        self.assertIn("Scarica WebView2 Runtime", html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_get_boot_bg_color_from_theme_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            theme_file = os.path.join(tmpdir, "theme.txt")
            with patch("jot.services.config_service.THEME_PREF_FILE", theme_file):
                with open(theme_file, "w", encoding="utf-8") as f:
                    f.write("dark")
                self.assertEqual(get_boot_bg_color(), "#161618")

                with open(theme_file, "w", encoding="utf-8") as f:
                    f.write("light")
                self.assertEqual(get_boot_bg_color(), "#eceae5")

    def test_get_boot_bg_color_windows_os_theme(self):
        with patch.object(sys, "platform", "win32"):
            with patch(
                "jot.services.config_service.THEME_PREF_FILE",
                "/nonexistent/theme.txt",
            ):
                mock_winreg = MagicMock()
                mock_key = MagicMock()
                mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
                mock_winreg.QueryValueEx.return_value = (0, 4)  # Dark mode

                with patch.dict(sys.modules, {"winreg": mock_winreg}):
                    self.assertEqual(get_boot_bg_color(), "#161618")

                mock_winreg.QueryValueEx.return_value = (1, 4)  # Light mode
                with patch.dict(sys.modules, {"winreg": mock_winreg}):
                    self.assertEqual(get_boot_bg_color(), "#eceae5")

    def test_get_boot_bg_color_darwin_os_theme(self):
        with patch.object(sys, "platform", "darwin"):
            with patch(
                "jot.services.config_service.THEME_PREF_FILE",
                "/nonexistent/theme.txt",
            ):
                mock_res = MagicMock()
                mock_res.stdout = "Dark\n"
                with patch("subprocess.run", return_value=mock_res):
                    self.assertEqual(get_boot_bg_color(), "#161618")

    def test_clear_webview2_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_dir = os.path.join(tmpdir, "storage")
            os.makedirs(storage_dir, exist_ok=True)
            dist_file = os.path.join(tmpdir, "dist", "index.html")
            os.makedirs(os.path.dirname(dist_file), exist_ok=True)
            with open(dist_file, "w", encoding="utf-8") as f:
                f.write("<html></html>")

            cache_dir = os.path.join(storage_dir, "EBWebView", "Default", "Cache")
            os.makedirs(cache_dir, exist_ok=True)
            test_cached_file = os.path.join(cache_dir, "cached.data")
            with open(test_cached_file, "w") as f:
                f.write("cached data")

            # First run: should clear cache because .build_mtime did not exist
            clear_webview2_cache(storage_dir, dist_file)
            self.assertFalse(os.path.exists(cache_dir))
            self.assertTrue(os.path.exists(os.path.join(storage_dir, ".build_mtime")))

            # Recreate cache and run again: mtime unchanged, so should NOT clear
            os.makedirs(cache_dir, exist_ok=True)
            with open(test_cached_file, "w") as f:
                f.write("cached data 2")
            clear_webview2_cache(storage_dir, dist_file)
            self.assertTrue(os.path.exists(cache_dir))

    def test_clear_webview2_cache_failure_handled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_dir = os.path.join(tmpdir, "storage")
            cache_dir = os.path.join(storage_dir, "EBWebView", "Default", "Cache")
            os.makedirs(cache_dir, exist_ok=True)
            dist_file = os.path.join(tmpdir, "dist", "index.html")
            os.makedirs(os.path.dirname(dist_file), exist_ok=True)
            with open(dist_file, "w") as f:
                f.write("test")

            with patch("shutil.rmtree", side_effect=OSError("Access denied")):
                # Should not raise
                clear_webview2_cache(storage_dir, dist_file)

    def test_start_webview2_monitor_stops_on_event(self):
        stop_event = threading.Event()
        mock_window = MagicMock()
        with patch(
            "jot.utils.webview2_recovery.has_webview2_runtime",
            return_value=False,
        ):
            start_webview2_monitor(mock_window, stop_event)
            time.sleep(0.05)
            stop_event.set()
            time.sleep(0.05)
            # Thread should terminate cleanly without raising

    def test_start_webview2_monitor_triggers_restart_when_runtime_detected(self):
        stop_event = threading.Event()
        mock_window = MagicMock()

        with (
            patch.object(stop_event, "wait", return_value=False),
            patch(
                "jot.utils.webview2_recovery.has_webview2_runtime",
                return_value=True,
            ) as probe,
            patch("subprocess.Popen") as mock_popen,
            patch("os._exit", side_effect=lambda code: stop_event.set()) as mock_exit,
        ):
            start_webview2_monitor(mock_window, stop_event)
            time.sleep(0.08)
            probe.assert_called_once_with(activate_renderer=False)
            mock_window.evaluate_js.assert_called_once()
            mock_popen.assert_called_once()
            mock_window.destroy.assert_called_once()
            mock_exit.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
