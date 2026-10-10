import io
import threading
from unittest.mock import MagicMock, patch

import pytest

from jot.browser_server.server import _BrowserConsoleTee
from jot.utils.console_utils import (
    MAX_CONSOLE_LINE_LEN,
    MAX_PENDING_LINE_LEN,
    OVERSIZED_LINE_MESSAGE,
)
from jot.webview_entry import _ConsoleTee


@pytest.fixture(params=[_ConsoleTee, _BrowserConsoleTee])
def console(request):
    original = io.StringIO()
    api = MagicMock()
    tee = request.param(original, api)
    return tee, original, api


def emitted(api):
    return [call.args[0] for call in api._push_console.call_args_list]


def test_traceback_fragments_are_complete_indented_lines(console):
    tee, original, api = console
    tee.write("    notify_data = NOTIFYICONDATAW(*largs)\n")
    tee.write("                  ")
    for _ in range(22):
        tee.write("^")
    assert len(emitted(api)) == 1
    tee.write("\n")
    tee.write("ValueError")
    tee.write(":")
    tee.write(" string too long (65, maximum length 64)")
    assert len(emitted(api)) == 2
    tee.write("\n")
    assert emitted(api) == [
        "    notify_data = NOTIFYICONDATAW(*largs)",
        "                  " + "^" * 22,
        "ValueError: string too long (65, maximum length 64)",
    ]
    assert original.getvalue() == "\n".join(emitted(api)) + "\n"


def test_multiline_and_fragmented_crlf_ignore_blank_lines(console):
    tee, original, api = console
    tee.write("first\r")
    assert original.getvalue() == "first\r"
    assert emitted(api) == []
    tee.write("\n   \n\n  second\r\nthird\n")
    assert emitted(api) == ["first", "  second", "third"]


def test_flush_emits_residue_once_and_flushes_original(console):
    tee, original, api = console
    with patch.object(original, "flush") as flush:
        tee.write("pending")
        tee.flush()
        tee.flush()
        assert emitted(api) == ["pending"]
        assert flush.call_count == 2
    tee.write("next\n")
    assert emitted(api) == ["pending", "next"]


def test_split_secret_is_redacted_before_ui_truncation(console):
    tee, original, api = console
    key = "AIzaSyFakeKey1234567890123"
    prefix = "x" * 1000 + " "
    tee.write(prefix + key[:7])
    assert emitted(api) == []
    tee.write(key[7:] + " " + "y" * 1100 + "\n")
    line = emitted(api)[0]
    assert "[API_KEY_REDACTED]" in line
    assert "AIza" not in line
    assert line.endswith("… [troncato]")
    assert len(line) == MAX_CONSOLE_LINE_LEN + len("… [troncato]")
    assert key in original.getvalue()


@pytest.mark.parametrize("finish", ["newline", "flush"])
def test_oversized_line_discards_entire_content_and_recovers(console, finish):
    tee, original, api = console
    tee.write("AIzaSySecret" + "a" * MAX_PENDING_LINE_LEN)
    tee.write("discard this too")
    assert emitted(api) == []
    if finish == "newline":
        tee.write("\n")
    else:
        tee.flush()
    tee.flush()
    tee.write("next\n")
    assert emitted(api) == [OVERSIZED_LINE_MESSAGE, "next"]
    assert "discard this too" in original.getvalue()


def test_pending_limit_is_inclusive_and_applies_across_writes(console):
    tee, _, api = console
    tee.write("x" * MAX_PENDING_LINE_LEN)
    tee.write("\n")
    assert emitted(api) == ["x" * MAX_CONSOLE_LINE_LEN + "… [troncato]"]
    tee.write("y" * MAX_PENDING_LINE_LEN)
    tee.write("z\nvalid\n")
    assert emitted(api)[1:] == [OVERSIZED_LINE_MESSAGE, "valid"]


def test_interleaved_threads_and_main_flush_do_not_mix_lines(console):
    tee, _, api = console
    ready = threading.Event()
    resume = threading.Event()

    def worker():
        tee.write("worker ")
        ready.set()
        if resume.wait(5):
            tee.write("line")
            tee.flush()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert ready.wait(5)
        tee.flush()
        assert emitted(api) == []
        tee.write("main ")
        tee.write("line\n")
    finally:
        resume.set()
        thread.join(5)
    assert not thread.is_alive()
    assert emitted(api) == ["main line", "worker line"]


@pytest.mark.parametrize("original_kind", ["missing", "failing"])
@pytest.mark.parametrize("tee_class", [_ConsoleTee, _BrowserConsoleTee])
def test_unavailable_original_stream_does_not_block_ui(original_kind, tee_class):
    original = None if original_kind == "missing" else MagicMock()
    if original is not None:
        original.write.side_effect = OSError("closed")
        original.flush.side_effect = OSError("closed")
    api = MagicMock()
    tee = tee_class(original, api)
    tee.write("line\nresidue")
    tee.flush()
    assert emitted(api) == ["line", "residue"]


def test_browser_filters_complete_http_lines_but_desktop_keeps_them():
    for tee_class in (_BrowserConsoleTee, _ConsoleTee):
        api = MagicMock()
        original = io.StringIO()
        tee = tee_class(original, api)
        for first, second in (
            ('request "GET / ', 'HTTP/1.1" 200\n'),
            ("INFO:     127.", "0.0.1:1234\n"),
            ("INFO:     con", "nection open\n"),
        ):
            tee.write(first)
            tee.write(second)
        tee.write("pipeline message\n")
        lines = emitted(api)
        assert lines[-1] == "pipeline message"
        assert len(lines) == (1 if tee_class is _BrowserConsoleTee else 4)
        assert "HTTP/1.1" in original.getvalue()
