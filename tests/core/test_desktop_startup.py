import html
import io
import json
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jot.core.desktop_startup import DesktopStartupServer


@pytest.fixture
def server(tmp_path):
    (tmp_path / "index.html").write_text(
        '<html><head></head><body><script src="./boot.js"></script></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "boot.js").write_text("window.boot = true;", encoding="utf-8")
    (tmp_path / "desktop-build.json").write_text(
        '{"version":"2.7.3"}', encoding="utf-8"
    )
    with (
        patch("jot.core.desktop_startup.record_startup_diagnostic") as record,
        patch(
            "jot.core.desktop_startup.get_startup_diagnostic",
            return_value={"renderer": "wkwebview"},
        ),
        patch("jot.core.desktop_startup.record_incident"),
    ):
        instance = DesktopStartupServer(str(tmp_path / "index.html"), port=0)
        cast(Any, instance).test_record = record
        try:
            yield instance
        finally:
            instance.close()


def request(server, path, *, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    return urlopen(
        Request(server.origin + path, data=data, method=method, headers=headers or {}),
        timeout=3,
    )


def test_real_http_headers_identity_and_public_script_namespace(server):
    with urlopen(server.entry_url(), timeout=3) as response:
        document = response.read().decode()
        assert (
            response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
        )
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Expires"] == "0"
        assert server.build_id in document
        assert "jot-startup" in document
        assert "2.7.3" in document
    with request(server, server.prefix + "boot.js", method="HEAD") as response:
        assert response.read() == b""
        assert response.headers["Cache-Control"].startswith("no-cache")
        assert response.headers["Content-Type"] == "application/javascript"
    with request(server, server.prefix + "boot.js") as response:
        assert response.read() == b"window.boot = true;"


@pytest.mark.parametrize(
    "path",
    [
        "/index.html",
        "/ui/old-build/boot.js",
        "missing.js",
        "../secret.txt",
        "%2e%2e/%2e%2e/secret.txt",
    ],
)
def test_no_old_build_or_path_escape(server, path):
    target = path if path.startswith("/") else server.prefix + path
    with pytest.raises(HTTPError) as error:
        request(server, target)
    assert error.value.code == 404
    assert error.value.headers["Cache-Control"].startswith("no-cache")


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_rejects_external_origin_and_dns_rebinding(server, headers):
    with pytest.raises(HTTPError) as error:
        request(server, server.prefix + "index.html", headers=headers)
    assert error.value.code == 403


def test_content_changes_change_entire_resource_namespace(server):
    (server.root / "boot.js").write_text("window.boot = 'new';", encoding="utf-8")
    other = DesktopStartupServer(str(server.root / "index.html"), port=0)
    try:
        assert other.build_id != server.build_id
        with pytest.raises(HTTPError) as error:
            request(other, server.prefix + "boot.js")
        assert error.value.code == 404
    finally:
        other.close()


def test_port_busy_falls_back_to_own_bound_listener(server):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        other = DesktopStartupServer(str(server.root / "index.html"), port=port)
        try:
            assert other.port_fallback
            assert other.httpd.server_port != port
            with urlopen(other.entry_url(), timeout=3) as response:
                assert response.status == 200
                document = response.read().decode()
                assert "Avvio temporaneamente bloccato" in document
                assert "Chiudi eventuali altre finestre" in document
                assert "tentativo automatico" not in document
                assert "<script" not in document
                assert "jot-startup" not in document
            assert other.state == "port_conflict"
            assert other.failed.is_set()
        finally:
            other.close()


@pytest.mark.parametrize("same_build", [True, False])
def test_second_desktop_server_cannot_share_listener_or_bootstrap_on_fallback(
    server, tmp_path, same_build
):
    index = server.root / "index.html"
    if not same_build:
        build = tmp_path / "other-build"
        build.mkdir()
        index = build / "index.html"
        index.write_text("<html><head></head><body>Other build</body></html>")
        (build / "desktop-build.json").write_text('{"version":"2.7.3"}')
    other = DesktopStartupServer(str(index), port=server.httpd.server_port)
    try:
        assert other.port_fallback
        assert other.origin != server.origin
        assert (other.build_id == server.build_id) is same_build
        assert other.entry_url() == other.origin + other.control + "port-conflict"
        # In particular, Windows must reject another reusable listener too.
        with socket.socket() as competing:
            competing.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                competing.bind(("127.0.0.1", server.httpd.server_port))
        with urlopen(server.entry_url(), timeout=3) as response:
            assert "jot-startup" in response.read().decode()
        with urlopen(other.entry_url(), timeout=3) as response:
            assert "Coda, preferenze, chiavi e sbobine sono conservate" in (
                response.read().decode()
            )
        # A manually requested index or bundle must not enable localStorage
        # persistence under the temporary recovery origin either.
        for path in ("index.html", "boot.js", "desktop-build.json"):
            with pytest.raises(HTTPError) as error:
                request(other, other.prefix + path)
            assert error.value.code == 503
        with pytest.raises(HTTPError) as error:
            request(
                other,
                other.control + "event",
                method="POST",
                body=startup_event(other, "ready"),
            )
        assert error.value.code == 400
        assert not other.ready.is_set()
        assert not server.ready.is_set()
        window = MagicMock()
        other.monitor(window, timeout=0)
        window.gui.evaluate_js.assert_not_called()
        window.load_url.assert_not_called()
    finally:
        other.close()


def test_port_conflict_clears_on_restart_without_changing_app_origin(server):
    index = str(server.root / "index.html")
    first = DesktopStartupServer(index, port=0)
    port = first.httpd.server_port
    origin = first.origin
    other = None
    try:
        with urlopen(first.entry_url(), timeout=3) as response:
            response.read()
        other = DesktopStartupServer(index, port=port)
        assert other.port_fallback
        with urlopen(other.entry_url(), timeout=3) as response:
            assert "<script" not in response.read().decode()
    finally:
        if other is not None:
            other.close()
        first.close()
    restarted = DesktopStartupServer(index, port=port)
    try:
        assert not restarted.port_fallback
        assert restarted.origin == origin
        with urlopen(restarted.entry_url(), timeout=3) as response:
            assert "jot-startup" in response.read().decode()
    finally:
        restarted.close()


def test_ready_requires_build_identity_and_current_attempt(server):
    with request(
        server,
        server.control + "event",
        method="POST",
        body={
            "kind": "ready",
            "attempt": 0,
            "version": "2.7.0",
            "build_id": server.build_id,
        },
    ) as response:
        assert response.status == 200
    assert not server.ready.is_set()
    assert server.failed.is_set()
    server.attempt = 1
    server.failed.clear()
    with pytest.raises(HTTPError) as error:
        request(
            server,
            server.control + "event",
            method="POST",
            body={"kind": "ready", "attempt": 0},
        )
    assert error.value.code == 400
    assert server.receive_event(
        {"kind": "ready", "attempt": 1, "version": "2.7.3", "build_id": server.build_id}
    )
    assert server.ready.is_set()
    assert server.test_record.call_args.kwargs["status"] == "bridge_ready"


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "unknown", "attempt": 0},
        [1, 2],
        {"kind": "page", "attempt": 0, "message": "x" * 9000},
    ],
)
def test_invalid_or_oversized_event_is_rejected(server, body):
    with pytest.raises(HTTPError) as error:
        request(server, server.control + "event", method="POST", body=body)
    assert error.value.code == 400


def test_events_are_bounded_and_redacted(server):
    key = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    for _ in range(20):
        assert server.receive_event({"kind": "page", "attempt": 0, "message": key})
    assert not server.receive_event({"kind": "page", "attempt": 0})
    assert key not in json.dumps(server.events)
    server.attempt = 1
    assert server.receive_event(
        {"kind": "ready", "attempt": 1, "build_id": server.build_id, "version": "2.7.3"}
    )
    assert server.ready.is_set()
    assert len(server.events) == 20


def test_report_download_and_failure_page_work_without_bridge(server):
    with (
        patch("jot.core.session_store.get_session_root", return_value="archive"),
        patch(
            "jot.services.diagnostics_service.collect_files",
            return_value={"report.md": "Safe diagnostic report"},
        ),
    ):
        with request(server, server.control + "report") as response:
            assert b"Safe diagnostic report" in response.read()
            assert response.headers["Content-Disposition"].startswith("attachment")
        with request(server, server.control + "report", method="HEAD") as response:
            assert response.read() == b""
    server.failure = "<script>unsafe</script>"
    with request(server, server.control + "failure") as response:
        content = response.read().decode()
        assert "Scarica diagnostica" in content
        assert "&lt;script&gt;" in content
        assert "<script>" not in content
    with patch.object(server, "report", side_effect=OSError("unavailable")):
        with request(server, server.control + "report") as response:
            assert json.loads(response.read())["version"] == "2.7.3"


def test_recovery_is_bounded_and_late_old_attempt_cannot_unlock(server):
    window = MagicMock()
    window.gui.evaluate_js.return_value = {
        "url": server.entry_url(),
        "version": "2.7.0",
        "scripts": ["old.js"],
        "load_settings": False,
        "save_settings": False,
    }
    server.monitor(window, timeout=0.01)
    assert window.load_url.call_count == 2
    assert "attempt=1" in window.load_url.call_args_list[0].args[0]
    assert window.load_url.call_args.args[0].endswith("/failure")
    assert server.snapshot["version"] == "2.7.0"
    assert not server.receive_event(
        {"kind": "ready", "attempt": 0, "build_id": server.build_id, "version": "2.7.3"}
    )


def test_successful_settings_handshake_does_not_reload(server):
    window = MagicMock()
    window.gui.evaluate_js.return_value = {
        "url": server.entry_url(),
        "version": "2.7.3",
        "scripts": [],
        "load_settings": True,
        "save_settings": True,
    }
    server.receive_event(
        {"kind": "ready", "attempt": 0, "build_id": server.build_id, "version": "2.7.3"}
    )
    server.monitor(window, timeout=0.01)
    window.load_url.assert_not_called()
    assert server.test_record.call_args.kwargs["page"]["version"] == "2.7.3"


def test_ready_in_flight_at_timeout_is_completed_before_retry_decision(server):
    event_in_flight = threading.Event()
    release_event = threading.Event()
    monitor_at_decision = threading.Event()
    monitor_finished = threading.Event()
    receiver_finished = threading.Event()
    errors: list[Exception] = []
    accepted: list[bool] = []
    real_lock = threading.Lock()

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread() is monitor:
                monitor_at_decision.set()
            real_lock.acquire()

        def __exit__(self, *args):
            real_lock.release()

    def pause_message(value, max_len=None):
        event_in_flight.set()
        if not release_event.wait(3):
            raise TimeoutError("Test did not release in-flight event")
        return str(value)

    def receive_ready():
        try:
            accepted.append(
                server.receive_event(
                    {
                        "kind": "ready",
                        "attempt": 0,
                        "build_id": server.build_id,
                        "version": "2.7.3",
                        "message": "late ready",
                    }
                )
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            receiver_finished.set()

    window = MagicMock()

    def run_monitor():
        try:
            server.monitor(window, timeout=0)
        except Exception as exc:
            errors.append(exc)
        finally:
            # The old implementation skips the lock and finishes instead.
            monitor_at_decision.set()
            monitor_finished.set()

    monitor = threading.Thread(target=run_monitor, daemon=True)
    receiver = threading.Thread(target=receive_ready, daemon=True)
    with (
        patch.object(server, "lock", ObservedLock()),
        patch.object(server, "observe_page"),
        patch(
            "jot.core.desktop_startup.redact_secrets",
            side_effect=pause_message,
        ),
    ):
        try:
            receiver.start()
            assert event_in_flight.wait(3)
            monitor.start()
            assert monitor_at_decision.wait(3)
            assert not monitor_finished.is_set()
            assert server.attempt == 0
        finally:
            release_event.set()
            assert receiver_finished.wait(3)
            if monitor.ident is not None:
                assert monitor_finished.wait(3)
            receiver.join(timeout=3)
            if monitor.ident is not None:
                monitor.join(timeout=3)
    assert not errors
    assert accepted == [True]
    assert server.ready.is_set()
    assert server.attempt == 0
    window.load_url.assert_not_called()


def test_shutdown_and_failed_native_snapshot_do_not_block(server):
    window = MagicMock()
    server.stop.set()
    server.monitor(window, timeout=1)
    window.load_url.assert_not_called()
    server.window = window
    window.gui.evaluate_js.side_effect = RuntimeError("renderer failed")
    server.observe_page()


def startup_event(server, kind):
    return {
        "kind": kind,
        "attempt": server.attempt,
        "build_id": server.build_id,
        "version": server.version,
    }


def test_terminal_failure_rejects_ready_during_native_navigation(server):
    accepted = []
    window = MagicMock()

    def navigate(url):
        if url.endswith("/failure"):
            # The native call runs outside the lock, while an HTTP request can arrive.
            accepted.append(server.receive_event(startup_event(server, "ready")))

    window.load_url.side_effect = navigate
    server.monitor(window, timeout=0)
    assert accepted == [False]
    assert server.state == "failed"
    assert not server.ready.is_set()
    with pytest.raises(HTTPError) as error:
        request(
            server,
            server.control + "event",
            method="POST",
            body=startup_event(server, "ready"),
        )
    assert error.value.code == 400
    with request(server, server.control + "failure") as response:
        assert b"Scarica diagnostica" in response.read()


@pytest.mark.parametrize("kind", ["ready", "settings-started"])
def test_success_is_terminal_but_bootstrap_can_retry_its_ack(server, kind):
    assert server.receive_event(startup_event(server, "ready"))
    data = startup_event(server, kind)
    assert server.receive_event(data)
    assert not server.receive_event(startup_event(server, "error"))
    assert not server.receive_event({**data, "version": "old-version"})
    assert not server.receive_event({**data, "build_id": "old-build"})
    assert not server.receive_event({**data, "attempt": -1})
    server.stop.set()
    assert not server.receive_event(data)
    server.stop.clear()
    server.state = "failed"
    assert not server.receive_event(data)
    assert server.ready.is_set()
    assert not server.failed.is_set()


def test_real_http_bootstrap_retry_after_discarded_ready_ack_preserves_success(server):
    for kind in ("settings-started", "ready"):
        with request(
            server,
            server.control + "event",
            method="POST",
            body=startup_event(server, kind),
        ) as response:
            assert response.status == 200
            # Discard the ready response: the frontend will repeat the bootstrap.
    started_at = server.settings_started_at
    events = list(server.events)
    record_count = server.test_record.call_count
    for kind in ("settings-started", "ready", "settings-started", "ready"):
        with request(
            server,
            server.control + "event",
            method="POST",
            body=startup_event(server, kind),
        ) as response:
            assert response.status == 200
        assert server.state == "ready"
        assert server.ready.is_set()
        assert not server.failed.is_set()
        assert server.settings_started_at == started_at
        assert server.events == events
        assert server.test_record.call_count == record_count


def test_slow_settings_load_outlives_bridge_deadline_without_reloading(server):
    clock = [0.0]
    window = MagicMock()

    def progress(_):
        if clock[0] == 0:
            clock[0] = 20
        else:
            assert not window.load_url.called
            server.receive_event(startup_event(server, "ready"))

    with (
        patch(
            "jot.core.desktop_startup.time.monotonic",
            side_effect=lambda: clock[0],
        ),
        patch.object(server.stop, "wait", side_effect=progress),
    ):
        assert server.receive_event(startup_event(server, "settings-started"))
        server.monitor(window, timeout=15, settings_timeout=60)
    assert server.ready.is_set()
    window.load_url.assert_not_called()


def test_settings_retries_do_not_extend_budget_and_second_timeout_is_terminal(server):
    clock = [0.0]
    navigation_times = []
    window = MagicMock()

    def progress(_):
        clock[0] += 20
        assert server.receive_event(startup_event(server, "settings-started"))

    def navigate(url):
        navigation_times.append(clock[0])
        if not url.endswith("/failure"):
            assert server.settings_started_at is None
            assert server.receive_event(startup_event(server, "settings-started"))

    window.load_url.side_effect = navigate
    with (
        patch(
            "jot.core.desktop_startup.time.monotonic",
            side_effect=lambda: clock[0],
        ),
        patch.object(server.stop, "wait", side_effect=progress),
    ):
        assert server.receive_event(startup_event(server, "settings-started"))
        server.monitor(window, timeout=15, settings_timeout=60)
    assert navigation_times == [60, 120]
    assert server.state == "failed"


def test_settings_begin_during_diagnostic_probe_gets_its_own_budget(server):
    window = MagicMock()
    with (
        patch.object(
            server,
            "observe_page",
            side_effect=lambda: server.receive_event(
                startup_event(server, "settings-started")
            ),
        ),
        patch.object(
            server.stop,
            "wait",
            side_effect=lambda _: server.receive_event(startup_event(server, "ready")),
        ),
    ):
        server.monitor(window, timeout=0, settings_timeout=60)
    assert server.ready.is_set()
    window.load_url.assert_not_called()


def test_wrong_settings_identity_cannot_extend_wait(server):
    assert not server.receive_event(
        {**startup_event(server, "settings-started"), "build_id": "old-build"}
    )
    assert server.settings_started_at is None
    assert server.state == "waiting_bridge"


def test_hung_native_snapshot_cannot_hold_recovery(server):
    release = threading.Event()
    window = MagicMock()
    window.gui.evaluate_js.side_effect = lambda *args: release.wait(4)
    try:
        server.monitor(window, timeout=0.01)
        assert window.load_url.call_count == 2
    finally:
        release.set()


def test_cocoa_probe_is_async_and_preserves_pywebview_evaluator(server):
    class View:
        webview: Any

        def evaluate_js(self, script, parse_json):
            return "original"

    original = View.evaluate_js
    callbacks = []
    view = View()
    cocoa = SimpleNamespace(
        BrowserView=SimpleNamespace(instances={"probe": view}),
        AppHelper=SimpleNamespace(callAfter=lambda callback: callback()),
    )
    view.webview = SimpleNamespace(
        evaluateJavaScript_completionHandler_=lambda script, handler: callbacks.append(
            handler
        )
    )
    server.window = SimpleNamespace(uid="probe", gui=MagicMock())
    with (
        patch("jot.core.desktop_startup.sys.platform", "darwin"),
        patch.dict("sys.modules", {"webview.platforms.cocoa": cocoa}),
    ):
        server.observe_page()
        assert len(callbacks) == 1
        assert not server.snapshot
        assert View.evaluate_js is original
        assert view.evaluate_js("normal application call", True) == "original"
        # Completion is allowed after the probe returns, without changing API results.
        callbacks[0]('{"version":"2.7.3","scripts":["current.js"]}', None)
        assert server.snapshot["version"] == "2.7.3"
        assert server.snapshot["scripts"] == ["current.js"]
        server.window.gui.evaluate_js.assert_not_called()
        server.observe_page()
        server.attempt = 1
        callbacks[1]('{"version":"old-attempt","scripts":[]}', None)
        assert server.snapshot["version"] == "2.7.3"
        server.observe_page()
        server.stop.set()
        callbacks[2]('{"version":"closed-window","scripts":[]}', None)
        assert server.snapshot["version"] == "2.7.3"
    assert View.evaluate_js is original


@pytest.mark.parametrize(
    "result,error", [(None, "CSP blocked"), ("invalid json", None)]
)
def test_cocoa_probe_records_its_own_failure_without_failing_bootstrap(
    server, result, error
):
    view = SimpleNamespace(
        webview=SimpleNamespace(
            evaluateJavaScript_completionHandler_=lambda script, handler: handler(
                result, error
            )
        )
    )
    cocoa = SimpleNamespace(
        BrowserView=SimpleNamespace(instances={"probe": view}),
        AppHelper=SimpleNamespace(callAfter=lambda callback: callback()),
    )
    server.window = SimpleNamespace(uid="probe")
    with (
        patch("jot.core.desktop_startup.sys.platform", "darwin"),
        patch.dict("sys.modules", {"webview.platforms.cocoa": cocoa}),
        patch("jot.core.desktop_startup.record_incident") as incident,
    ):
        server.observe_page()
    incident.assert_called_once()
    assert not server.failed.is_set()
    assert server.state == "waiting_bridge"


def test_cocoa_probe_tolerates_a_missing_native_view(server):
    cocoa = SimpleNamespace(BrowserView=SimpleNamespace(instances={}))
    server.window = SimpleNamespace(uid="not-created")
    with (
        patch("jot.core.desktop_startup.sys.platform", "darwin"),
        patch.dict("sys.modules", {"webview.platforms.cocoa": cocoa}),
    ):
        server.observe_page()
    assert not server.snapshot


@pytest.mark.parametrize("port_conflict", [False, True])
@pytest.mark.parametrize("failure", [None, "window", "renderer"])
def test_entrypoint_uses_versioned_url_monitor_and_always_releases_listener(
    tmp_path, failure, port_conflict
):
    from jot import webview_entry as entry

    api, startup, window = MagicMock(), MagicMock(), MagicMock()
    startup.port_fallback = port_conflict
    startup.entry_url.return_value = (
        "http://127.0.0.1:50000/ui/build/_startup/token/port-conflict"
        if port_conflict
        else "http://127.0.0.1:42001/ui/build/index.html"
    )
    with (
        patch.object(entry, "prepare_startup"),
        patch("jot.app_webview.JotApi", return_value=api),
        patch.object(entry, "get_dist_path", return_value="dist/index.html"),
        patch.object(entry, "has_webview2_runtime", return_value=True),
        patch.object(entry, "DesktopStartupServer", return_value=startup),
        patch.object(entry, "_clear_webview2_cache"),
        patch.object(entry, "_get_window_position", return_value={}),
        patch.object(entry.webview, "create_window", return_value=window) as create,
        patch.object(entry.webview, "start") as start,
        patch("sys.stdout", io.StringIO()),
        patch("sys.stderr", io.StringIO()),
        patch.dict("os.environ", {"LOCALAPPDATA": str(tmp_path)}),
    ):
        if failure == "window":
            create.side_effect = RuntimeError("native window failed")
        elif failure == "renderer":
            start.side_effect = RuntimeError("renderer failed")
        if failure:
            with pytest.raises(RuntimeError):
                entry.main()
        else:
            entry.main()
        assert create.call_args.args[1] == startup.entry_url()
        if failure != "window":
            assert start.call_args.args == (
                (None, None) if port_conflict else (startup.monitor, (window,))
            )
            assert start.call_args.kwargs["private_mode"] is False
        startup.close.assert_called_once()


def test_packaged_backend_version_is_authoritative(server):
    with (
        patch("jot.core.desktop_startup.sys.frozen", True, create=True),
        patch(
            "jot.services.diagnostics_service.build_info",
            return_value={"version": "2.7.4"},
        ),
    ):
        other = DesktopStartupServer(str(server.root / "index.html"), port=0)
        try:
            assert other.version == "2.7.4"
            other.receive_event(
                {
                    "kind": "ready",
                    "attempt": 0,
                    "version": "2.7.3",
                    "build_id": other.build_id,
                }
            )
            assert other.failed.is_set()
            assert not other.ready.is_set()
        finally:
            other.close()


@pytest.mark.parametrize("kind", ["mismatch", "error", "ready"])
@pytest.mark.parametrize("frontend_version", ["2.7.3", "unknown"])
def test_missing_packaged_metadata_keeps_startup_blocked_with_specific_reason(
    server, kind, frontend_version
):
    with (
        patch("jot.core.desktop_startup.sys.frozen", True, create=True),
        patch(
            "jot.services.diagnostics_service.build_info",
            return_value={"version": "unknown", "mode": "packaged"},
        ),
    ):
        other = DesktopStartupServer(str(server.root / "index.html"), port=0)
        try:
            assert other.version == "unknown"
            assert other.receive_event(
                {
                    "kind": kind,
                    "attempt": 0,
                    "version": frontend_version,
                    "build_id": other.build_id,
                }
            )
            assert other.failed.is_set()
            assert not other.ready.is_set()
            assert "Impossibile leggere la versione dell'app installata." in (
                html.unescape(other.failure_html().decode())
            )
            with (
                patch.object(other, "report", return_value=b"metadata unavailable"),
                request(other, other.control + "report") as response,
            ):
                assert response.read() == b"metadata unavailable"
        finally:
            other.close()


@pytest.mark.parametrize("backend_version", ["2.7.3", "2.7.4"])
def test_macos_metadata_link_controls_real_http_handshake(
    server, tmp_path, backend_version
):
    contents = tmp_path / "jot.app" / "Contents"
    frameworks = contents / "Frameworks"
    resources = contents / "Resources"
    frameworks.mkdir(parents=True)
    resources.mkdir()
    metadata = resources / "diagnostic_build.json"
    metadata.write_text(json.dumps({"version": backend_version, "mode": "packaged"}))
    link = frameworks / metadata.name
    resolve = Path.resolve

    def resolve_metadata(path, *args, **kwargs):
        return metadata if path == link else resolve(path, *args, **kwargs)

    with (
        patch("jot.core.desktop_startup.sys.frozen", True, create=True),
        patch("jot.core.desktop_startup.sys.platform", "darwin"),
        patch(
            "jot.core.desktop_startup.sys._MEIPASS",
            str(frameworks),
            create=True,
        ),
        patch.object(Path, "resolve", resolve_metadata),
    ):
        other = DesktopStartupServer(str(server.root / "index.html"), port=0)
        try:
            assert other.version == backend_version
            with urlopen(other.entry_url(), timeout=3) as response:
                document = response.read().decode()
            assert f'"version": "{backend_version}"' in html.unescape(document)
            with request(
                other,
                other.control + "event",
                method="POST",
                body={
                    "kind": "ready",
                    "attempt": 0,
                    "version": "2.7.3",
                    "build_id": other.build_id,
                },
            ) as response:
                assert response.status == 200
            assert other.ready.is_set() == (backend_version == "2.7.3")
            assert other.failed.is_set() == (backend_version != "2.7.3")
        finally:
            other.close()
