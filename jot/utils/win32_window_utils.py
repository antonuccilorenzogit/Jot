"""
Win32 window and display utilities for jot.
"""

from __future__ import annotations

import sys
from typing import Any


def apply_windows_dark_mode(hwnd: int | None, dark: bool) -> None:
    """Set DWM immersive dark mode on Windows window handle to eliminate titlebar/frame flash."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        from ctypes import wintypes

        # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 on Win11/Win10 20H1+, 19 on earlier Win10
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
        value = ctypes.c_int(1 if dark else 0)
        pv = ctypes.byref(value)
        cb = ctypes.sizeof(value)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_USE_IMMERSIVE_DARK_MODE),
            pv,
            wintypes.DWORD(cb),
        )
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_USE_IMMERSIVE_DARK_MODE_OLD),
                pv,
                wintypes.DWORD(cb),
            )
    except Exception:
        pass


def flash_window(hwnd: int | None) -> bool:
    """Flash the application taskbar icon on Windows."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        finfo = FLASHWINFO(
            cbSize=ctypes.sizeof(FLASHWINFO),
            hwnd=hwnd,
            dwFlags=0x00000003 | 0x0000000C,  # FLASHW_ALL | FLASHW_TIMERNOFG
            uCount=0,
            dwTimeout=0,
        )
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(finfo))
        return True
    except Exception:
        return False


def get_window_hwnd(window: Any) -> int | None:
    """Extract Win32 HWND from pywebview window instance."""
    if sys.platform != "win32" or window is None:
        return None
    try:
        if hasattr(window, "native") and window.native:
            if hasattr(window.native, "Handle"):
                return int(window.native.Handle.ToInt64())
            if hasattr(window.native, "Dispatcher"):
                from System.Windows.Interop import WindowInteropHelper  # type: ignore

                helper = WindowInteropHelper(window.native)
                return int(helper.Handle.ToInt64())
    except Exception:
        pass
    try:
        import ctypes

        title = getattr(window, "title", "jot")
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            return int(hwnd)
    except Exception:
        pass
    return None


def get_window_position(win_w: int, win_h: int) -> dict[str, Any]:
    """Center the window on screen (Windows only; other platforms let pywebview center by default)."""
    center_x: int | None = None
    center_y: int | None = None
    if sys.platform == "win32":
        try:
            import ctypes

            scr_w = ctypes.windll.user32.GetSystemMetrics(0)
            scr_h = ctypes.windll.user32.GetSystemMetrics(1)
            center_x = max(0, (scr_w - win_w) // 2)
            center_y = max(0, (scr_h - win_h) // 2)
        except Exception:
            center_x, center_y = 100, 50

    if center_x is not None and center_y is not None:
        return {"x": center_x, "y": center_y}
    return {}
