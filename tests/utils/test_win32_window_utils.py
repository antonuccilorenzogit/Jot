from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from jot.utils.win32_window_utils import (
    apply_windows_dark_mode,
    flash_window,
    get_window_hwnd,
    get_window_position,
)


class Win32WindowUtilsTests(unittest.TestCase):
    def test_apply_windows_dark_mode_non_windows(self):
        with patch.object(sys, "platform", "darwin"):
            # Should be a no-op
            apply_windows_dark_mode(12345, True)

    def test_apply_windows_dark_mode_no_hwnd(self):
        with patch.object(sys, "platform", "win32"):
            apply_windows_dark_mode(None, True)
            apply_windows_dark_mode(0, True)

    def test_apply_windows_dark_mode_success(self):
        with patch.object(sys, "platform", "win32"):
            mock_ctypes = MagicMock()
            mock_ctypes.windll.dwmapi.DwmSetWindowAttribute.return_value = 0
            with patch.dict(
                sys.modules, {"ctypes": mock_ctypes, "ctypes.wintypes": MagicMock()}
            ):
                apply_windows_dark_mode(12345, True)
                mock_ctypes.windll.dwmapi.DwmSetWindowAttribute.assert_called_once()

    def test_apply_windows_dark_mode_fallback_attribute(self):
        with patch.object(sys, "platform", "win32"):
            mock_ctypes = MagicMock()
            # First call returns error code (non-zero), triggers fallback to old attribute 19
            mock_ctypes.windll.dwmapi.DwmSetWindowAttribute.side_effect = [1, 0]
            with patch.dict(
                sys.modules, {"ctypes": mock_ctypes, "ctypes.wintypes": MagicMock()}
            ):
                apply_windows_dark_mode(12345, False)
                self.assertEqual(
                    mock_ctypes.windll.dwmapi.DwmSetWindowAttribute.call_count, 2
                )

    def test_apply_windows_dark_mode_handles_exception(self):
        with patch.object(sys, "platform", "win32"):
            mock_ctypes = MagicMock()
            mock_ctypes.windll.dwmapi.DwmSetWindowAttribute.side_effect = RuntimeError(
                "DWM not available"
            )
            with patch.dict(
                sys.modules, {"ctypes": mock_ctypes, "ctypes.wintypes": MagicMock()}
            ):
                # Must not raise
                apply_windows_dark_mode(12345, True)

    def test_flash_window_non_windows(self):
        with patch.object(sys, "platform", "linux"):
            self.assertFalse(flash_window(12345))

    def test_flash_window_no_hwnd(self):
        with patch.object(sys, "platform", "win32"):
            self.assertFalse(flash_window(None))
            self.assertFalse(flash_window(0))

    def test_flash_window_success(self):
        with patch.object(sys, "platform", "win32"):
            mock_ctypes = MagicMock()
            mock_ctypes.sizeof.return_value = 20
            with patch.dict(
                sys.modules, {"ctypes": mock_ctypes, "ctypes.wintypes": MagicMock()}
            ):
                res = flash_window(12345)
                self.assertTrue(res)
                mock_ctypes.windll.user32.FlashWindowEx.assert_called_once()

    def test_flash_window_exception(self):
        with patch.object(sys, "platform", "win32"):
            mock_ctypes = MagicMock()
            mock_ctypes.windll.user32.FlashWindowEx.side_effect = RuntimeError(
                "Flash failed"
            )
            with patch.dict(
                sys.modules, {"ctypes": mock_ctypes, "ctypes.wintypes": MagicMock()}
            ):
                self.assertFalse(flash_window(12345))

    def test_get_window_hwnd_non_windows_or_none(self):
        with patch.object(sys, "platform", "darwin"):
            self.assertIsNone(get_window_hwnd(MagicMock()))
        with patch.object(sys, "platform", "win32"):
            self.assertIsNone(get_window_hwnd(None))

    def test_get_window_hwnd_from_native_handle(self):
        with patch.object(sys, "platform", "win32"):
            mock_window = MagicMock()
            mock_window.native.Handle.ToInt64.return_value = 998877
            del mock_window.native.Dispatcher
            hwnd = get_window_hwnd(mock_window)
            self.assertEqual(hwnd, 998877)

    def test_get_window_hwnd_from_dispatcher(self):
        with patch.object(sys, "platform", "win32"):
            mock_window = MagicMock()
            del mock_window.native.Handle
            mock_window.native.Dispatcher = MagicMock()

            mock_interop = MagicMock()
            mock_helper_inst = MagicMock()
            mock_helper_inst.Handle.ToInt64.return_value = 554433
            mock_interop.WindowInteropHelper.return_value = mock_helper_inst

            with patch.dict(sys.modules, {"System.Windows.Interop": mock_interop}):
                hwnd = get_window_hwnd(mock_window)
                self.assertEqual(hwnd, 554433)

    def test_get_window_hwnd_find_window_fallback(self):
        with patch.object(sys, "platform", "win32"):
            mock_window = MagicMock(spec=["title"])
            mock_window.title = "Custom Title"
            mock_ctypes = MagicMock()
            mock_ctypes.windll.user32.FindWindowW.return_value = 112233
            with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
                hwnd = get_window_hwnd(mock_window)
                self.assertEqual(hwnd, 112233)
                mock_ctypes.windll.user32.FindWindowW.assert_called_once_with(
                    None, "Custom Title"
                )

    def test_get_window_hwnd_not_found(self):
        with patch.object(sys, "platform", "win32"):
            mock_window = MagicMock(spec=["title"])
            mock_window.title = "Not Found"
            mock_ctypes = MagicMock()
            mock_ctypes.windll.user32.FindWindowW.return_value = 0
            with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
                self.assertIsNone(get_window_hwnd(mock_window))

    def test_get_window_position_non_windows(self):
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(get_window_position(800, 600), {})

    def test_get_window_position_windows(self):
        with patch.object(sys, "platform", "win32"):
            mock_ctypes = MagicMock()
            mock_ctypes.windll.user32.GetSystemMetrics.side_effect = lambda code: (
                1920 if code == 0 else 1080
            )
            with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
                pos = get_window_position(900, 820)
                self.assertEqual(pos, {"x": 510, "y": 130})

    def test_get_window_position_windows_exception_fallback(self):
        with patch.object(sys, "platform", "win32"):
            mock_ctypes = MagicMock()
            mock_ctypes.windll.user32.GetSystemMetrics.side_effect = RuntimeError(
                "Display error"
            )
            with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
                pos = get_window_position(900, 820)
                self.assertEqual(pos, {"x": 100, "y": 50})


if __name__ == "__main__":
    unittest.main()
