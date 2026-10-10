"""
Unit and integration tests for jot.browser_server.
"""

from __future__ import annotations

import io
import os
import tempfile
import threading
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from jot.browser_server.rpc_allowlist import (
    ALLOWED_RPC_METHODS,
    invoke_rpc,
    sanitize_settings_for_browser,
)
from jot.browser_server.scenarios import (
    SAMPLE_HTML_NOTE,
    run_deterministic_scenario,
)
from jot.browser_server.server import create_browser_app
from jot.browser_server.ws_dispatcher import WebSocketDispatcher
from jot.pipeline.pipeline_adapter import PipelineAdapter


def test_lifespan_keeps_stdout_and_stderr_separate():
    import asyncio
    import sys

    stdout, stderr = io.StringIO(), io.StringIO()

    async def exercise():
        with tempfile.TemporaryDirectory() as root:
            app = create_browser_app(session_root=root)
            with (
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
                patch.object(app.state.api, "_push_console") as emit,
            ):
                async with app.router.lifespan_context(app):
                    sys.stdout.write("out ")
                    sys.stderr.write("err ")
                    sys.stdout.write("line\n")
                    sys.stderr.write("line\n")
                    assert [call.args[0] for call in emit.call_args_list] == [
                        "out line",
                        "err line",
                    ]
                assert sys.stdout is stdout
                assert sys.stderr is stderr

    asyncio.run(exercise())
    assert stdout.getvalue() == "out line\n"
    assert stderr.getvalue() == "err line\n"


@pytest.fixture
def isolated_app():
    temp_dir = tempfile.mkdtemp()
    app = create_browser_app(session_root=temp_dir)
    client = TestClient(app)
    yield client, app, temp_dir


def test_bootstrap_endpoint(isolated_app):
    client, _app, _ = isolated_app
    res = client.get("/api/bootstrap")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["mode"] == "browser"
    assert "session_token" in data
    assert "jot_session" in res.cookies
    assert data["scenario"] == "success"
    assert data["event_sequence"] == 0
    assert data["capabilities"] == {
        "fileUpload": True,
        "fileDrop": True,
        "nativeFolderPicker": False,
        "openLocalPath": False,
        "osNotifications": False,
        "updateInstallation": False,
        "realPipeline": False,
        "credentialPersistence": False,
        "windowControls": False,
    }


def test_rpc_authentication(isolated_app):
    client, _, _ = isolated_app
    # Unauthenticated request
    res = client.post("/api/rpc/load_settings", json={"args": []})
    assert res.status_code == 401

    # Authenticated via cookie
    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]

    client.cookies.set("jot_session", token)
    res_auth = client.post(
        "/api/rpc/load_settings",
        json={"args": []},
    )
    assert res_auth.status_code == 200


def test_rpc_allowlist_enforcement(isolated_app):
    client, _, _ = isolated_app
    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]
    headers = {"X-Session-Token": token}

    # Disallowed private method
    res_priv = client.post(
        "/api/rpc/_private_method", json={"args": []}, headers=headers
    )
    assert res_priv.status_code == 403

    # Disallowed non-whitelisted method
    res_unauth = client.post(
        "/api/rpc/evil_command", json={"args": []}, headers=headers
    )
    assert res_unauth.status_code == 403


def test_load_settings_masks_api_key(isolated_app):
    client, _, _ = isolated_app
    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]
    headers = {"X-Session-Token": token}

    res = client.post("/api/rpc/load_settings", json={"args": []}, headers=headers)
    assert res.status_code == 200
    settings = res.json()
    assert settings["api_key"] == ""
    assert isinstance(settings["has_protected_key"], bool)
    assert isinstance(settings["available_models"], list)
    assert settings["fallback_keys"] == []
    assert settings["configuredFallbackKeyCount"] == 0


def test_settings_sanitizer_reports_fallback_count_without_placeholders():
    settings = sanitize_settings_for_browser(
        {"api_key": "primary", "fallback_keys": ["fallback-a", "", "fallback-b"]}
    )

    assert settings["api_key"] == ""
    assert settings["fallback_keys"] == []
    assert settings["configuredFallbackKeyCount"] == 2


def test_browser_runtime_never_reads_desktop_config_or_credentials(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("desktop persistence must not be used by browser mode")

    monkeypatch.setattr("jot.app_webview.load_config", fail)
    monkeypatch.setattr("jot.services.config_service.load_config", fail)
    monkeypatch.setattr("jot.core.credentials.keyring_get_fallback_keys", fail)

    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_browser_app(session_root=temp_dir, scenario="success")
        with TestClient(app) as client:
            token = client.get("/api/bootstrap").json()["session_token"]
            headers = {"X-Session-Token": token}
            for method, args in (
                ("load_settings", []),
                ("get_api_usage", []),
                ("validate_environment", []),
                ("get_diagnostic_report", []),
                (
                    "save_settings",
                    [None, None, "gemini-2.5-flash", []],
                ),
                (
                    "start_processing",
                    [[{"id": "f", "name": "fake.mp3"}]],
                ),
            ):
                response = client.post(
                    f"/api/rpc/{method}", json={"args": args}, headers=headers
                )
                assert response.status_code == 200


def test_fallback_key_metadata_preserves_or_explicitly_clears(isolated_app):
    client, _, _ = isolated_app
    token = client.get("/api/bootstrap").json()["session_token"]
    headers = {"X-Session-Token": token}

    saved = client.post(
        "/api/rpc/save_settings",
        json={"args": [None, ["first", "second"], "gemini-2.5-flash", []]},
        headers=headers,
    )
    assert saved.json()["ok"] is True
    loaded = client.post(
        "/api/rpc/load_settings", json={"args": []}, headers=headers
    ).json()
    assert loaded["fallback_keys"] == []
    assert loaded["configuredFallbackKeyCount"] == 2

    client.post(
        "/api/rpc/save_settings",
        json={"args": [None, None, "gemini-2.5-flash", []]},
        headers=headers,
    )
    preserved = client.post(
        "/api/rpc/load_settings", json={"args": []}, headers=headers
    ).json()
    assert preserved["configuredFallbackKeyCount"] == 2

    client.post(
        "/api/rpc/save_settings",
        json={"args": [None, [], "gemini-2.5-flash", []]},
        headers=headers,
    )
    cleared = client.post(
        "/api/rpc/load_settings", json={"args": []}, headers=headers
    ).json()
    assert cleared["configuredFallbackKeyCount"] == 0


def test_desktop_only_methods_fallback(isolated_app):
    client, _, _ = isolated_app
    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]
    headers = {"X-Session-Token": token}

    res_open = client.post(
        "/api/rpc/open_file", json={"args": ["test.txt"]}, headers=headers
    )
    assert res_open.status_code == 200
    assert res_open.json()["ok"] is False
    assert "desktop" in res_open.json()["error"].lower()

    res_flash = client.post("/api/rpc/flash_window", json={"args": []}, headers=headers)
    assert res_flash.status_code == 200
    assert res_flash.json()["ok"] is True


def test_file_upload_endpoint(isolated_app):
    client, _, _ = isolated_app
    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]
    headers = {"X-Session-Token": token}

    file_content = b"fake audio mp3 content header"
    files = [("files", ("test_audio.mp3", io.BytesIO(file_content), "audio/mpeg"))]

    res = client.post("/api/upload", files=files, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["files"]) == 1
    uploaded = data["files"][0]
    assert uploaded["name"] == "test_audio.mp3"
    assert uploaded["size"] == len(file_content)
    assert os.path.exists(uploaded["path"])


def test_html_preview_security(isolated_app):
    client, _, temp_dir = isolated_app
    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]
    headers = {"X-Session-Token": token}

    # Safe HTML inside session root
    safe_html_path = os.path.join(temp_dir, "test.html")
    with open(safe_html_path, "w", encoding="utf-8") as f:
        f.write("<h1>Test</h1>")

    res_safe = client.get(
        f"/api/preview/html?path={safe_html_path}",
        headers=headers,
    )
    assert res_safe.status_code == 200
    assert "<h1>Test</h1>" in res_safe.text

    # Malicious attempt outside session root
    outside_path = os.path.abspath(os.path.join(temp_dir, "..", "outside.html"))
    res_bad = client.get(
        f"/api/preview/html?path={outside_path}",
        headers=headers,
    )
    assert res_bad.status_code in (403, 404)


def test_websocket_dispatcher_monotonic_sequence_and_batching():
    dispatcher = WebSocketDispatcher(flush_interval=0.01)
    q, _ = dispatcher.register_subscriber()

    # Emit batched events
    dispatcher.emit("updateProgress", 10.0, batched=True)
    dispatcher.emit("updateProgress", 20.0, batched=True)
    dispatcher.emit("updateProgress", 30.0, batched=True)

    # Emit unbatched event
    dispatcher.emit("updatePhase", "Fase 1", batched=False)
    dispatcher.flush()

    assert dispatcher.current_sequence >= 2

    # Replay subscriber
    q2, replays = dispatcher.register_subscriber(last_sequence=0)
    assert len(replays) >= 2
    assert replays[0]["sequence"] == 1
    assert replays[1]["sequence"] == 2

    dispatcher.unregister_subscriber(q)
    dispatcher.unregister_subscriber(q2)


def test_websocket_client_connection(isolated_app):
    client, app, _ = isolated_app
    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]

    dispatcher: WebSocketDispatcher = app.state.ws_dispatcher

    with client.websocket_connect(f"/api/events?token={token}") as ws:
        dispatcher.emit("updatePhase", "Connesso!", batched=False)
        dispatcher.flush()
        msg = ws.receive_json()
        assert msg["name"] == "updatePhase"
        assert msg["payload"] == "Connesso!"
        assert msg["sequence"] == 1

    assert dispatcher.subscriber_count == 0


def test_deterministic_scenarios_execution(isolated_app):
    _client, _app, _ = isolated_app
    dispatcher = WebSocketDispatcher(flush_interval=0.01)
    cancel_event = threading.Event()

    # Success scenario
    events: list[dict[str, Any]] = []

    def mock_emit(name: str, payload: Any, batched: bool | None = None):
        events.append({"name": name, "payload": payload})

    dispatcher.emit = mock_emit  # type: ignore

    run_deterministic_scenario(
        "success",
        dispatcher,
        cancel_event,
        file_item={"id": "f1", "name": "lezione.mp3"},
        speed_factor=0.01,
    )

    names = [e["name"] for e in events]
    assert "setCurrentFile" in names
    assert "fileDone" in names
    assert "processDone" in names

    # Failure scenario
    events.clear()
    run_deterministic_scenario(
        "failure",
        dispatcher,
        cancel_event,
        file_item={"id": "f2", "name": "broken.mp3"},
        speed_factor=0.01,
    )
    names_fail = [e["name"] for e in events]
    assert "fileFailed" in names_fail
    assert "processDone" in names_fail


def test_all_deterministic_scenarios():
    dispatcher = WebSocketDispatcher(flush_interval=0.01)
    cancel_event = threading.Event()
    events: list[dict[str, Any]] = []

    def mock_emit(name: str, payload: Any, batched: bool | None = None):
        events.append({"name": name, "payload": payload})

    dispatcher.emit = mock_emit  # type: ignore

    # Quota scenario
    events.clear()
    run_deterministic_scenario("quota", dispatcher, cancel_event, speed_factor=0.001)
    assert any(e["name"] == "askNewKey" for e in events)

    # Paused scenario
    events.clear()
    run_deterministic_scenario("paused", dispatcher, cancel_event, speed_factor=0.001)
    assert any(
        e["name"] == "fileFailed" and e["payload"].get("retryable") for e in events
    )

    # Regenerate scenario
    events.clear()
    run_deterministic_scenario(
        "regenerate", dispatcher, cancel_event, speed_factor=0.001
    )
    assert any(e["name"] == "askRegenerate" for e in events)

    # Cancelled during execution
    events.clear()
    cancel_event.set()
    run_deterministic_scenario("success", dispatcher, cancel_event, speed_factor=0.001)
    assert any(
        e["name"] == "processDone" and e["payload"].get("cancelled") for e in events
    )


def test_media_stream_and_scenario_server_endpoints():
    temp_dir = tempfile.mkdtemp()
    app = create_browser_app(session_root=temp_dir, scenario="success")
    client = TestClient(app)

    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]
    headers = {"X-Session-Token": token}

    # Test media streaming
    media_file = os.path.join(temp_dir, "audio.mp3")
    with open(media_file, "wb") as f:
        f.write(b"dummy audio data for test")

    res_stream = client.get(f"/api/media/stream?path={media_file}", headers=headers)
    assert res_stream.status_code == 200
    assert res_stream.content == b"dummy audio data for test"

    # Missing media file
    res_stream_404 = client.get(
        "/api/media/stream?path=nonexistent.mp3", headers=headers
    )
    assert res_stream_404.status_code == 404

    unsupported_file = os.path.join(temp_dir, "notes.txt")
    with open(unsupported_file, "w", encoding="utf-8") as file_handle:
        file_handle.write("not media")
    unsupported = client.get(
        f"/api/media/stream?path={unsupported_file}", headers=headers
    )
    assert unsupported.status_code == 404

    resolved = client.get(
        f"/api/media/resolve?path={media_file}&session_dir={temp_dir}",
        headers=headers,
    ).json()
    assert resolved["ok"] is True
    assert resolved["has_audio"] is True
    assert "/api/media/stream?" in resolved["url"]

    # Scenario RPC start and stop
    res_start = client.post(
        "/api/rpc/start_processing",
        json={"args": [[{"id": "1", "name": "test.mp3"}]]},
        headers=headers,
    )
    assert res_start.status_code == 200
    assert res_start.json()["ok"] is True

    res_stop = client.post(
        "/api/rpc/stop_processing",
        json={"args": []},
        headers=headers,
    )
    assert res_stop.status_code == 200
    assert res_stop.json()["ok"] is True


def test_package_endpoints_and_preview_missing(isolated_app):
    client, _app, _temp_dir = isolated_app
    boot = client.get("/api/bootstrap")
    token = boot.json()["session_token"]
    headers = {"X-Session-Token": token}

    # Missing preview file
    res_miss = client.get(
        "/api/preview/html?path=nonexistent_file.html", headers=headers
    )
    assert res_miss.status_code == 404

    # Upload package
    fake_pkg = io.BytesIO(b"PK\x05\x06" + b"\x00" * 18)
    res_pkg = client.post(
        "/api/upload_package",
        files={"package": ("test.sbobina", fake_pkg, "application/octet-stream")},
        headers=headers,
    )
    assert res_pkg.status_code == 200

    # Export package (invalid directory)
    res_exp = client.get(
        "/api/export_package?session_dir=invalid_dir",
        headers=headers,
    )
    assert res_exp.status_code == 400


@pytest.mark.anyio
async def test_ws_dispatcher_asyncio_loop():
    import asyncio

    loop = asyncio.get_running_loop()
    dispatcher = WebSocketDispatcher(flush_interval=0.01, loop=loop)
    q, _ = dispatcher.register_subscriber()

    dispatcher.emit("updatePhase", "Async Loop Test", batched=False)
    dispatcher.flush()

    evt = await asyncio.wait_for(q.get(), timeout=2.0)
    assert evt["name"] == "updatePhase"
    assert evt["payload"] == "Async Loop Test"

    dispatcher.unregister_subscriber(q)


def test_pipeline_adapter_with_custom_dispatcher():
    dispatcher = WebSocketDispatcher(flush_interval=0.01)
    cancel_event = threading.Event()
    adapter = PipelineAdapter(None, cancel_event, dispatcher=dispatcher)

    adapter.aggiorna_progresso(77.5)
    adapter.aggiorna_fase("Testing custom dispatcher")
    dispatcher.flush()

    assert dispatcher.current_sequence >= 2
    assert adapter.winfo_exists() is True


def test_browser_shutdown_cancels_dispatcher_timer():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_browser_app(session_root=temp_dir)
        dispatcher = app.state.ws_dispatcher
        with TestClient(app) as client:
            client.get("/api/bootstrap")
            dispatcher.emit("updateProgress", 0.2, batched=True)
        assert dispatcher._timer is None
        assert not dispatcher._subscribers
