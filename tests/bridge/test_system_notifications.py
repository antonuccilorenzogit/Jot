import sys
from unittest.mock import patch

import pytest

from jot.bridge.controllers.system_controller import SystemControllerMixin


def notify_on(platform, title, message):
    host = SystemControllerMixin()
    with (
        patch("sys.platform", platform),
        patch.object(host, "flash_window") as flash,
        patch("plyer.notification.notify") as notify,
    ):
        result = host.show_notification(title, message)
    assert result == {"ok": True}
    flash.assert_called_once()
    notify.assert_called_once()
    assert notify.call_args.kwargs["app_name"] == "jot"
    assert notify.call_args.kwargs["timeout"] == 5
    return notify.call_args.kwargs


@pytest.mark.parametrize(
    "title,message", [("Title", "Message"), ("", ""), ("t" * 63, "m" * 255)]
)
def test_windows_keeps_text_within_limits(title, message):
    args = notify_on("win32", title, message)
    assert args["title"] == title
    assert args["message"] == message


@pytest.mark.parametrize(
    "title,message",
    [
        ("t" * 64, "m" * 256),
        ("😀" * 32, "𝄞" * 128),
        ("t" * 61 + "😀" + "x", "m" * 253 + "𝄞" + "x"),
        (
            "❌ Errore elaborazione — Fisiopatologia generale I - Lezione 1.m4a",
            "Messaggio",
        ),
        (
            "⏸️ Elaborazione in pausa — Fisiopatologia generale I - Lezione 1.m4a",
            "Messaggio",
        ),
    ],
)
def test_windows_truncates_by_utf16_units_without_splitting_characters(title, message):
    args = notify_on("win32", title, message)
    for field, source, limit in (("title", title, 63), ("message", message, 255)):
        normalized = args[field]
        assert len(normalized.encode("utf-16-le")) // 2 <= limit
        if len(source.encode("utf-16-le")) // 2 > limit:
            assert normalized.endswith("…")
            assert source.startswith(normalized[:-1])
        else:
            assert normalized == source


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_other_platforms_preserve_long_text(platform):
    title, message = "😀" * 100, "𝄞" * 300
    args = notify_on(platform, title, message)
    assert args["title"] == title
    assert args["message"] == message


def test_synchronous_notification_failure_keeps_bridge_error():
    host = SystemControllerMixin()
    with (
        patch.object(host, "flash_window", side_effect=RuntimeError("no window")),
        patch("plyer.notification.notify", side_effect=RuntimeError("no notifier")),
    ):
        result = host.show_notification("Title", "Message")
    assert not result["ok"]
    assert "no notifier" in result["error"]


@pytest.mark.skipif(
    sys.platform != "win32", reason="Requires native Windows WCHAR structure"
)
def test_real_plyer_structure_accepts_normalized_text_without_showing_notification():
    from plyer.platforms.win.libs.win_api_defs import NOTIFYICONDATAW

    title = "❌ Errore elaborazione — Fisiopatologia generale I - Lezione 1.m4a"
    data = NOTIFYICONDATAW()
    with pytest.raises(ValueError, match="string too long"):
        data.szInfoTitle = title
    args = notify_on("win32", title, "😀" * 200)
    data.szInfoTitle = args["title"]
    data.szInfo = args["message"]
    assert data.szInfoTitle == args["title"]
    assert data.szInfo == args["message"]
