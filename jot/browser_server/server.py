"""
FastAPI local browser server for jot.

Provides RPC routing over HTTP, WebSocket progress streaming, file upload/download,
audio/HTML streaming, and deterministic scenario simulation.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import sys
import tempfile
import threading
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jot.app_webview import JotApi
from jot.bridge.bridge_utils import _path_under_root
from jot.browser_server.rpc_allowlist import invoke_rpc
from jot.browser_server.scenarios import run_deterministic_scenario
from jot.browser_server.ws_dispatcher import WebSocketDispatcher
from jot.core.model_registry import DEFAULT_MODEL, MODEL_OPTIONS
from jot.core.shared import get_session_root, set_session_root
from jot.utils.console_utils import MAX_CONSOLE_LINE_LEN, LineConsoleTee
from jot.utils.logging_utils import redact_secrets


class RpcRequest(BaseModel):
    args: list[Any] = []


BROWSER_CAPABILITIES: dict[str, bool] = {
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


def _browser_settings(app: FastAPI) -> dict[str, Any]:
    state = app.state.browser_settings
    return {
        "api_key": "",
        "fallback_keys": [],
        "configuredFallbackKeyCount": state["configured_fallback_key_count"],
        "preferred_model": state["preferred_model"],
        "fallback_models": list(state["fallback_models"]),
        "available_models": list(MODEL_OPTIONS),
        "has_protected_key": state["has_primary_key"],
        "api_key_insecure": False,
        "api_key_insecure_reason": "",
    }


def _browser_validation(app: FastAPI) -> dict[str, Any]:
    root = get_session_root()
    ffmpeg_path = shutil.which("ffmpeg")
    checks = [
        {
            "id": "api_key",
            "label": "API Key Gemini",
            "status": "ok",
            "message": "API simulata: nessuna credenziale reale viene usata.",
        },
        {
            "id": "ffmpeg",
            "label": "FFmpeg",
            "status": "ok" if ffmpeg_path else "warning",
            "message": "FFmpeg disponibile." if ffmpeg_path else "FFmpeg non trovato.",
            "details": ffmpeg_path or "",
        },
        {
            "id": "config",
            "label": "Config locale",
            "status": "ok",
            "message": "Configurazione temporanea in memoria.",
        },
        {
            "id": "output",
            "label": "Cartella sessioni/output",
            "status": "ok" if os.access(root, os.W_OK) else "error",
            "message": "Root temporanea scrivibile."
            if os.access(root, os.W_OK)
            else "Root temporanea non scrivibile.",
            "details": root,
        },
    ]
    has_error = any(check["status"] == "error" for check in checks)
    has_warning = any(check["status"] == "warning" for check in checks)
    return {
        "ok": not has_error,
        "summary": "Ambiente browser simulato pronto."
        if not has_error
        else "Ambiente browser non pronto.",
        "checks": checks,
        "has_warnings": has_warning,
    }


def _handle_browser_runtime_rpc(
    method: str, body: RpcRequest, app: FastAPI
) -> Any | None:
    """Serve browser-only state without touching desktop config or credentials."""
    state = app.state.browser_settings
    if method == "set_browser_scenario":
        scenario = str(body.args[0] if body.args else "").strip()
        if scenario not in {"success", "failure", "quota", "paused", "regenerate"}:
            return {"ok": False, "error": "Scenario browser non valido"}
        app.state.scenario = scenario
        return {"ok": True, "scenario": scenario}
    if method == "load_settings":
        return _browser_settings(app)
    if method == "save_settings":
        api_key = body.args[0] if len(body.args) > 0 else None
        fallback_keys = body.args[1] if len(body.args) > 1 else None
        preferred_model = body.args[2] if len(body.args) > 2 else DEFAULT_MODEL
        fallback_models = body.args[3] if len(body.args) > 3 else []
        if api_key is not None:
            state["has_primary_key"] = bool(str(api_key).strip())
        if fallback_keys is not None:
            if not isinstance(fallback_keys, list):
                return {"ok": False, "error": "Fallback key non valide"}
            state["configured_fallback_key_count"] = len(
                [item for item in fallback_keys if str(item or "").strip()]
            )
        state["preferred_model"] = str(preferred_model or DEFAULT_MODEL)
        state["fallback_models"] = [
            str(item) for item in fallback_models if str(item or "").strip()
        ]
        return {"ok": True}
    if method == "get_api_usage":
        return {
            "ok": True,
            "result": {
                "schema_version": 1,
                "quota_date": "simulata",
                "next_reset_info": "API simulata: nessuna quota reale consumata",
                "primary_status": "operational",
                "status_message": "API simulata",
                "is_degraded_mode": False,
                "project_limits": {},
                "telemetry": {
                    "requests_sent": 0,
                    "responses_succeeded": 0,
                    "final_failures": 0,
                    "retries_total": 0,
                },
                "work_stats": {
                    "chunks_completed": 0,
                    "revisions_completed": 0,
                    "sbobine_completed": 0,
                },
                "credentials": [],
            },
        }
    if method == "validate_environment":
        return {"ok": True, "result": _browser_validation(app)}
    if method == "get_diagnostic_report":
        validation = _browser_validation(app)
        lines = [
            "# Diagnostica jot (browser)",
            "",
            "- Modalità: API simulata",
            "- Credenziali: temporanee in memoria, non persistite",
            f"- Root sessioni: {get_session_root()}",
        ]
        for check in validation["checks"]:
            lines.append(f"- {check['label']}: {check['status']} - {check['message']}")
        return {"ok": True, "report": "\n".join(lines)}
    if method == "get_archive_folders":
        return {"ok": True, "folders": list(app.state.archive_folders)}
    if method == "save_archive_folders":
        folders = body.args[0] if body.args else []
        app.state.archive_folders = list(folders) if isinstance(folders, list) else []
        return {"ok": True}
    if method == "save_theme_preference":
        return None
    if method == "check_path_exists":
        path = str(body.args[0] if body.args else "").strip()
        root = os.path.realpath(get_session_root())
        real_path = os.path.realpath(path) if path else ""
        return {
            "ok": True,
            "exists": bool(
                real_path
                and _path_under_root(real_path, root)
                and os.path.exists(real_path)
            ),
        }
    return None


def _verify_auth(request: Request) -> None:
    session_token = request.app.state.session_token
    cookie_token = request.cookies.get("jot_session")
    header_token = request.headers.get("X-Session-Token")
    if cookie_token != session_token and header_token != session_token:
        raise HTTPException(
            status_code=401, detail="Session token non valido o assente"
        )


def _handle_scenario_rpc(
    method: str, body: RpcRequest, app: FastAPI
) -> dict[str, Any] | None:
    if not app.state.scenario:
        return None

    api = app.state.api
    ws_dispatcher = app.state.ws_dispatcher

    if method == "start_processing":
        files = body.args[0] if body.args else []
        first_file = files[0] if files and isinstance(files, list) else None

        api._cancel_event.clear()

        def _run_scenario():
            try:
                run_deterministic_scenario(
                    app.state.scenario,
                    ws_dispatcher,
                    api._cancel_event,
                    file_item=first_file,
                    on_session_written=api._invalidate_sessions_cache,
                )
            finally:
                api._invalidate_sessions_cache()
                with app.state.scenario_threads_lock:
                    app.state.scenario_threads.discard(threading.current_thread())

        scenario_thread = threading.Thread(
            target=_run_scenario, daemon=True, name="browser-scenario"
        )
        with app.state.scenario_threads_lock:
            app.state.scenario_threads.add(scenario_thread)
        scenario_thread.start()
        return {"ok": True}

    if method == "stop_processing":
        api._cancel_event.set()
        return {"ok": True}

    if method == "is_processing_active":
        return {"ok": True, "active": False}

    return None


def _register_api_routes(app: FastAPI) -> None:
    @app.get("/api/bootstrap")
    async def bootstrap(response: Response):
        response.set_cookie(
            key="jot_session",
            value=app.state.session_token,
            httponly=True,
            samesite="lax",
        )
        return {
            "ok": True,
            "mode": "browser",
            "scenario": app.state.scenario,
            "session_token": app.state.session_token,
            "session_root": get_session_root(),
            "capabilities": BROWSER_CAPABILITIES,
            "event_sequence": app.state.ws_dispatcher.current_sequence,
        }

    @app.post("/api/rpc/{method}")
    async def handle_rpc(
        method: str,
        body: RpcRequest,
        _: None = Depends(_verify_auth),
    ):
        browser_res = _handle_browser_runtime_rpc(method, body, app)
        if browser_res is not None or method in {
            "save_theme_preference",
            "set_browser_scenario",
        }:
            return browser_res

        scenario_res = _handle_scenario_rpc(method, body, app)
        if scenario_res is not None:
            return scenario_res

        try:
            return invoke_rpc(
                app.state.api,
                method,
                body.args,
                has_scenario=bool(getattr(app.state, "scenario", None)),
            )
        except PermissionError as pe:
            raise HTTPException(status_code=403, detail=str(pe))
        except AttributeError as ae:
            raise HTTPException(status_code=404, detail=str(ae))
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )


def _register_websocket_routes(app: FastAPI) -> None:
    @app.websocket("/api/events")
    async def websocket_events(
        websocket: WebSocket,
        last_sequence: Annotated[int, Query()] = 0,
    ):
        session_token = app.state.session_token
        token = websocket.query_params.get("token")
        cookie_token = websocket.cookies.get("jot_session")
        if token != session_token and cookie_token != session_token:
            await websocket.close(code=4001, reason="Unauthorized")
            return

        await websocket.accept()
        ws_dispatcher: WebSocketDispatcher = app.state.ws_dispatcher
        q, replays = ws_dispatcher.register_subscriber(last_sequence=last_sequence)
        try:
            for past_evt in replays:
                await websocket.send_json(past_evt)

            while True:
                event_task = asyncio.create_task(q.get())
                receive_task = asyncio.create_task(websocket.receive())
                done, pending = await asyncio.wait(
                    {event_task, receive_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for pending_task in pending:
                    pending_task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

                if receive_task in done:
                    message = receive_task.result()
                    if message.get("type") == "websocket.disconnect":
                        break
                    continue

                await websocket.send_json(event_task.result())
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            ws_dispatcher.unregister_subscriber(q)


def _register_file_routes(app: FastAPI) -> None:
    @app.post("/api/upload")
    async def upload_files(
        files: Annotated[list[UploadFile], File()],
        _: None = Depends(_verify_auth),
    ):
        results = []
        uploads_dir = app.state.uploads_dir
        for upload in files:
            file_id = secrets.token_hex(8)
            filename = os.path.basename(upload.filename or f"upload_{file_id}")
            save_path = os.path.join(uploads_dir, f"{file_id}_{filename}")
            size = 0
            with open(save_path, "wb") as out_f:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    out_f.write(chunk)
            results.append(
                {
                    "id": file_id,
                    "name": filename,
                    "path": save_path,
                    "size": size,
                    "type": upload.content_type or "application/octet-stream",
                }
            )
        return {"ok": True, "files": results}

    @app.post("/api/upload_package")
    async def upload_package(
        package: Annotated[UploadFile, File()],
        _: None = Depends(_verify_auth),
    ):
        uploads_dir = app.state.uploads_dir
        temp_pkg = os.path.join(uploads_dir, f"pkg_{secrets.token_hex(8)}.sbobina")
        try:
            with open(temp_pkg, "wb") as out_f:
                while chunk := await package.read(1024 * 1024):
                    out_f.write(chunk)
            return app.state.api.import_sbobina_package(temp_pkg)
        finally:
            if os.path.exists(temp_pkg):
                try:
                    os.remove(temp_pkg)
                except Exception:
                    pass

    @app.get("/api/export_package")
    async def export_package(
        session_dir: Annotated[str, Query()],
        export_type: Annotated[str, Query()] = "full",
        _: None = Depends(_verify_auth),
    ):
        target_path = os.path.join(
            app.state.uploads_dir,
            f"export_{secrets.token_hex(8)}.sbobina",
        )
        res = app.state.api.export_sbobina_package(
            session_dir=session_dir,
            export_type=export_type,
            target_path=target_path,
        )
        exported_path = res.get("target_path") or target_path
        if not res.get("ok") or not os.path.exists(exported_path):
            raise HTTPException(
                status_code=400, detail=res.get("error", "Esportazione fallita")
            )

        filename = f"{os.path.basename(os.path.normpath(session_dir))}.sbobina"
        return FileResponse(
            exported_path,
            filename=filename,
            media_type="application/octet-stream",
        )


def _register_media_routes(app: FastAPI) -> None:
    @app.get("/api/media/stream")
    async def stream_media(
        path: Annotated[str, Query()] = "",
        session_dir: Annotated[str | None, Query()] = None,
        _: None = Depends(_verify_auth),
    ):
        resolved, has_audio, error = app.state.api._resolve_stream_media_path(
            path, session_dir
        )
        if not resolved:
            raise HTTPException(
                status_code=404 if has_audio else 400,
                detail=error or "File multimediale non trovato",
            )
        real_path = os.path.realpath(resolved)
        if not os.path.isfile(real_path):
            raise HTTPException(status_code=404, detail="File multimediale non trovato")
        if not _path_under_root(real_path, os.path.realpath(get_session_root())):
            raise HTTPException(status_code=403, detail="Accesso non autorizzato")
        return FileResponse(real_path)

    @app.get("/api/media/resolve")
    async def resolve_media(
        path: Annotated[str, Query()] = "",
        session_dir: Annotated[str | None, Query()] = None,
        _: None = Depends(_verify_auth),
    ):
        resolved, has_audio, error = app.state.api._resolve_stream_media_path(
            path, session_dir
        )
        if not resolved:
            return {"ok": False, "has_audio": has_audio, "error": error}
        real_path = os.path.realpath(resolved)
        if not os.path.isfile(real_path):
            return {
                "ok": False,
                "has_audio": has_audio,
                "error": "File multimediale non trovato.",
            }
        if not _path_under_root(real_path, os.path.realpath(get_session_root())):
            return {
                "ok": False,
                "has_audio": has_audio,
                "error": "Accesso non autorizzato al file multimediale.",
            }
        query = urlencode(
            {
                "path": real_path,
                **({"session_dir": session_dir} if session_dir else {}),
            }
        )
        return {
            "ok": True,
            "has_audio": True,
            "url": f"/api/media/stream?{query}",
        }

    @app.get("/api/preview/html")
    async def preview_html(
        path: Annotated[str, Query()], _: None = Depends(_verify_auth)
    ):
        real_path = os.path.realpath(path)
        if not os.path.exists(real_path) or not os.path.isfile(real_path):
            raise HTTPException(status_code=404, detail="Documento HTML non trovato")
        if not _path_under_root(real_path, os.path.realpath(get_session_root())):
            raise HTTPException(
                status_code=403, detail="Accesso non autorizzato al file"
            )
        return FileResponse(real_path, media_type="text/html")


_MAX_CONSOLE_LINE_LEN = MAX_CONSOLE_LINE_LEN


class _BrowserConsoleTee(LineConsoleTee):
    """Intercept print() calls from Python pipeline and push to browser console."""

    def __init__(self, original, api: JotApi):
        self._api = api
        super().__init__(original, api._push_console, keep_line=self._keep_browser_line)

    @staticmethod
    def _keep_browser_line(line: str) -> bool:
        return not (
            "HTTP/1.1" in line
            or line.startswith("INFO:     127.0.0.1")
            or line.startswith("INFO:     connection")
        )


def create_browser_app(
    session_root: str | None = None,
    scenario: str | None = "success",
    dist_dir: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI browser development application."""

    session_token = secrets.token_urlsafe(32)

    # Set up session root (isolated by default for browser dev/testing)
    owns_session_root = session_root is None
    if session_root:
        effective_root = os.path.abspath(session_root)
    else:
        effective_root = tempfile.mkdtemp(prefix="jot_browser_")
    os.makedirs(effective_root, exist_ok=True)
    set_session_root(effective_root)

    uploads_dir = os.path.join(effective_root, "_browser_uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    ws_dispatcher = WebSocketDispatcher()
    api = JotApi(
        session_root_override=effective_root,
        load_persisted_session_root=False,
        event_dispatcher=ws_dispatcher,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        ws_dispatcher.set_loop(loop)
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = _BrowserConsoleTee(old_stdout, api)
        sys.stderr = _BrowserConsoleTee(old_stderr, api)
        try:
            yield
        finally:
            api._cancel_event.set()
            with app.state.scenario_threads_lock:
                scenario_threads = list(app.state.scenario_threads)
            for scenario_thread in scenario_threads:
                scenario_thread.join(timeout=2.0)
            ws_dispatcher.close()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            try:
                shutil.rmtree(uploads_dir, ignore_errors=True)
            except Exception:
                pass
            if owns_session_root:
                try:
                    shutil.rmtree(effective_root, ignore_errors=True)
                except Exception:
                    pass

    app = FastAPI(title="jot Browser Host", lifespan=lifespan)
    app.state.session_token = session_token
    app.state.api = api
    app.state.ws_dispatcher = ws_dispatcher
    app.state.scenario = scenario or "success"
    app.state.uploads_dir = uploads_dir
    app.state.browser_settings = {
        "has_primary_key": True,
        "configured_fallback_key_count": 0,
        "preferred_model": DEFAULT_MODEL,
        "fallback_models": [],
    }
    app.state.archive_folders = []
    app.state.scenario_threads = set()
    app.state.scenario_threads_lock = threading.Lock()

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_api_routes(app)
    _register_websocket_routes(app)
    _register_file_routes(app)
    _register_media_routes(app)

    resolved_dist = dist_dir
    if not resolved_dist:
        default_dist = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "webui", "dist")
        )
        if os.path.exists(default_dist):
            resolved_dist = default_dist

    if resolved_dist and os.path.exists(resolved_dist):
        app.mount("/", StaticFiles(directory=resolved_dist, html=True), name="static")

    return app
