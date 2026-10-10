"""Versioned desktop assets and bounded startup recovery, independent of the bridge."""

from __future__ import annotations

import hashlib
import html
import json
import os
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from jot.utils.logging_utils import (
    get_startup_diagnostic,
    record_incident,
    record_startup_diagnostic,
    redact_secrets,
)

_SNAPSHOT_JS = """JSON.stringify({
    url: location.href,
    version: window.__elDesktopVersion || '',
    csp: (document.querySelector('meta[http-equiv="Content-Security-Policy"]') || {}).content || '',
    scripts: Array.from(document.scripts).map(s => s.src).slice(0, 20),
    bridge: !!window.pywebview,
    load_settings: !!(window.pywebview && window.pywebview.api && window.pywebview.api.load_settings),
    save_settings: !!(window.pywebview && window.pywebview.api && window.pywebview.api.save_settings)
})"""


class _DesktopHTTPServer(ThreadingHTTPServer):
    # Windows otherwise permits two HTTPServer listeners on the same address.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DesktopStartupServer:
    """Serve only this build on loopback; never delete WebKit user data."""

    def __init__(self, index_path: str, port: int = 42001):
        self.root = Path(index_path).resolve().parent
        digest = hashlib.sha256()
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                if not path.resolve().is_relative_to(self.root):
                    raise ValueError("Frontend asset outside build directory")
                digest.update(path.relative_to(self.root).as_posix().encode())
                digest.update(b"\0")
                digest.update(path.read_bytes())
        self.build_id = digest.hexdigest()[:24]
        manifest = json.loads((self.root / "desktop-build.json").read_text("utf-8"))
        self.version = str(manifest["version"]).lstrip("v")
        if getattr(sys, "frozen", False):
            from jot.services.diagnostics_service import build_info

            self.version = str(build_info()["version"]).lstrip("v")
        self.token = uuid.uuid4().hex
        self.prefix = f"/ui/{self.build_id}/"
        self.control = f"{self.prefix}_startup/{self.token}/"
        self.attempt = 0
        self.state = "waiting_bridge"
        self.settings_started_at: float | None = None
        self.ready = threading.Event()
        self.failed = threading.Event()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.events: list[dict[str, object]] = []
        self.snapshot: dict[str, object] = {}
        self.failure = "Il collegamento al motore Python non è stato completato."
        self.window: Any = None
        self.port_fallback = False
        try:
            self.httpd = _DesktopHTTPServer(("127.0.0.1", port), self._handler())
        except OSError:
            if port == 0:
                raise
            self.httpd = _DesktopHTTPServer(("127.0.0.1", 0), self._handler())
            self.port_fallback = True
            self.state = "port_conflict"
            self.failed.set()
            self.failure = (
                "La porta locale dell'app è già utilizzata da un'altra istanza "
                "o da un altro programma."
            )
        self.origin = f"http://127.0.0.1:{self.httpd.server_port}"
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self._record("recovery" if self.port_fallback else "loading")

    def entry_url(self) -> str:
        if self.port_fallback:
            return self.origin + self.control + "port-conflict"
        return f"{self.origin}{self.prefix}index.html?attempt={self.attempt}"

    def _record(self, status: str) -> None:
        record_startup_diagnostic(
            **{
                **get_startup_diagnostic(),
                "status": status,
                "pid": os.getpid(),
                "build_id": self.build_id,
                "backend_version": self.version,
                "url": self.entry_url(),
                "attempt": self.attempt,
                "startup_phase": self.state,
                "port_fallback": self.port_fallback,
                "page": self.snapshot,
                "startup_events": list(self.events),
            }
        )

    def receive_event(self, data: dict[str, Any]) -> bool:
        with self.lock:
            if (
                self.port_fallback
                or data.get("attempt") != self.attempt
                or self.state == "failed"
                or self.stop.is_set()
            ):
                return False
            kind = data.get("kind")
            identity_matches = (
                self.version != "unknown"
                and data.get("build_id") == self.build_id
                and data.get("version") == self.version
            )
            if self.state == "ready":
                # A lost ready acknowledgement may restart the entire bootstrap.
                return kind in {"ready", "settings-started"} and identity_matches
            if kind not in {"page", "settings-started", "ready", "error", "mismatch"}:
                return False
            if kind == "settings-started" and not identity_matches:
                return False
            # A full error buffer must not reject a successful recovery handshake.
            if len(self.events) >= 20 and kind not in {"ready", "settings-started"}:
                return False
            self.events.append(
                {
                    "kind": kind,
                    "attempt": self.attempt,
                    "message": redact_secrets(
                        str(data.get("message", "")), max_len=1500
                    ),
                }
            )
            self.events = self.events[-20:]
            if kind == "settings-started":
                if self.settings_started_at is None:
                    self.settings_started_at = time.monotonic()
                self.state = "loading_settings"
            elif kind == "ready":
                if not identity_matches:
                    self.failure = "La versione dell'interfaccia non corrisponde alla build avviata."
                    self.failed.set()
                else:
                    self.state = "ready"
                    self.ready.set()
            elif kind in {"mismatch", "error"}:
                self.failure = "L'interfaccia non è stata caricata correttamente."
                self.failed.set()
            if self.failed.is_set() and self.version == "unknown":
                self.failure = "Impossibile leggere la versione dell'app installata."
            self._record("bridge_ready" if self.ready.is_set() else "loading")
            return True

    def report(self) -> bytes:
        from jot.core.session_store import get_session_root
        from jot.services.diagnostics_service import collect_files

        self._record("bridge_ready" if self.ready.is_set() else "recovery")
        files = collect_files(
            get_session_root(),
            frontend_version=str(self.snapshot.get("version", "unknown")),
        )
        return "\n\n".join(
            f"--- {name} ---\n{content}" for name, content in files.items()
        ).encode("utf-8")

    def failure_html(self) -> bytes:
        heading = (
            "Avvio temporaneamente bloccato"
            if self.port_fallback
            else "Impossibile completare l'avvio"
        )
        next_steps = (
            "Chiudi eventuali altre finestre di jot e riapri l'app. "
            "Se il problema persiste, riavvia il computer e riprova. "
            "Coda, preferenze, chiavi e sbobine sono conservate."
            if self.port_fallback
            else "È già stato effettuato un tentativo automatico di recupero. "
            "Chiavi, impostazioni e sbobine sono conservate."
        )
        return f"""<!doctype html><html lang="it"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>jot — Avvio non riuscito</title>
        <style>body{{font:16px system-ui;background:#161618;color:#f2f1ee;margin:0;padding:48px}}
        main{{max-width:650px;margin:auto}}a{{display:inline-block;color:#c4e3bb;padding:14px 0}}
        p{{line-height:1.6}}small{{color:#aaa}}</style><main>
        <h1>{heading}</h1><p>{html.escape(self.failure)}</p>
        <p>{next_steps}</p>
        <p>Scarica la diagnostica e condividila con chi ti sta aiutando.</p>
        <a href="{self.control}report" target="_blank" rel="noopener">Scarica diagnostica</a>
        <p><small>Versione {html.escape(self.version)} · Build {self.build_id}</small></p>
        </main></html>""".encode()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        return type("Handler", (DesktopAssetHandler,), {"owner": self})

    def observe_page(self) -> None:
        """Raw evaluation does not need pywebview.api or pywebview.stringify."""
        attempt = self.attempt
        try:
            if sys.platform == "darwin":
                self._observe_cocoa_page(attempt)
                return
            data = self.window.gui.evaluate_js(_SNAPSHOT_JS, self.window.uid, True)
            self._store_snapshot(data, attempt)
        except Exception as exc:
            record_incident("desktop-startup", str(exc))

    def _store_snapshot(self, data: Any, attempt: int) -> None:
        with self.lock:
            if (
                not isinstance(data, dict)
                or attempt != self.attempt
                or self.stop.is_set()
            ):
                return
            self.snapshot = {
                key: redact_secrets(str(data.get(key, "")), max_len=1500)
                if key in {"url", "version", "csp"}
                else data.get(key)
                for key in (
                    "url",
                    "version",
                    "csp",
                    "bridge",
                    "load_settings",
                    "save_settings",
                )
            }
            self.snapshot["scripts"] = [
                redact_secrets(str(url), max_len=300)
                for url in data.get("scripts", [])[:20]
            ]
            self._record(
                "bridge_ready"
                if self.ready.is_set()
                else "recovery"
                if self.state == "failed"
                else "loading"
            )

    def _observe_cocoa_page(self, attempt: int) -> None:
        """An asynchronous diagnostic probe; never replace pywebview's evaluator."""
        from webview.platforms import cocoa

        cocoa_module: Any = cocoa
        view = cocoa_module.BrowserView.instances.get(self.window.uid)
        if view is None:
            return

        def handler(result: Any, error: Any) -> None:
            if self.stop.is_set() or attempt != self.attempt:
                return
            if error is not None:
                record_incident("wkwebview-startup-probe", str(error))
                return
            try:
                self._store_snapshot(json.loads(result), attempt)
            except (ValueError, TypeError) as exc:
                record_incident("desktop-startup", str(exc))

        def evaluate_probe() -> None:
            if self.stop.is_set() or attempt != self.attempt:
                return
            try:
                view.webview.evaluateJavaScript_completionHandler_(
                    _SNAPSHOT_JS, handler
                )
            except Exception as exc:
                record_incident("wkwebview-startup-probe", str(exc))

        cocoa_module.AppHelper.callAfter(evaluate_probe)

    def monitor(
        self, window: Any, timeout: float = 15.0, settings_timeout: float = 60.0
    ) -> None:
        if self.port_fallback:
            return
        self.window = window
        bridge_deadline = time.monotonic() + timeout
        while not self.stop.is_set():
            with self.lock:
                deadline = (
                    self.settings_started_at + settings_timeout
                    if self.settings_started_at is not None
                    else bridge_deadline
                )
                waiting = (
                    not self.ready.is_set()
                    and not self.failed.is_set()
                    and time.monotonic() < deadline
                )
            if waiting:
                self.stop.wait(0.1)
                continue
            # Native evaluation can hang in a failed renderer; never block recovery on it.
            observer = threading.Thread(target=self.observe_page, daemon=True)
            observer.start()
            observer.join(timeout=1)
            # Finish any in-flight handshake before deciding to replace its page.
            # Event validation and the attempt transition must share this lock.
            with self.lock:
                if self.stop.is_set():
                    return
                if self.ready.is_set():
                    self._record("bridge_ready")
                    return
                # Settings may have started while the diagnostic probe was running.
                if (
                    not self.failed.is_set()
                    and self.settings_started_at is not None
                    and time.monotonic() < self.settings_started_at + settings_timeout
                ):
                    continue
                if self.attempt == 0:
                    self.attempt = 1
                    self.state = "waiting_bridge"
                    self.settings_started_at = None
                    self.ready.clear()
                    self.failed.clear()
                    next_url = self.entry_url()
                    bridge_deadline = time.monotonic() + timeout
                else:
                    # Commit the terminal state before releasing the event lock.
                    self.state = "failed"
                    self.failed.set()
                    next_url = self.origin + self.control + "failure"
                self._record("recovery")
            # Native navigation may invoke callbacks; do not hold the event lock.
            window.load_url(next_url)
            if self.state == "failed":
                return

    def close(self) -> None:
        self.stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


class DesktopAssetHandler(BaseHTTPRequestHandler):
    owner: DesktopStartupServer

    def log_message(self, format: str, *args: object) -> None:
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _trusted(self) -> bool:
        return (
            self.headers.get("Host") == urlsplit(self.owner.origin).netloc
            and self.headers.get("Origin", self.owner.origin) == self.owner.origin
            and self.headers.get("Sec-Fetch-Site", "same-origin") != "cross-site"
        )

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        import mimetypes

        if not self._trusted():
            self._send(403, b"Forbidden", "text/plain")
            return
        path = unquote(urlsplit(self.path).path)
        if path == self.owner.control + "report":
            try:
                body = self.owner.report()
            except Exception:
                body = json.dumps(
                    {
                        "version": self.owner.version,
                        "build_id": self.owner.build_id,
                        "events": self.owner.events,
                    }
                ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="jot-avvio.txt"',
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        if path == self.owner.control + "failure":
            self._send(200, self.owner.failure_html(), "text/html; charset=utf-8")
            return
        if self.owner.port_fallback:
            # The temporary origin is recovery-only: mounting React here would
            # hide the queue and preferences stored under the stable origin.
            if path == self.owner.control + "port-conflict":
                self._send(200, self.owner.failure_html(), "text/html; charset=utf-8")
            else:
                self._send(503, b"Desktop port unavailable", "text/plain")
            return
        if not path.startswith(self.owner.prefix):
            self._send(404, b"Not found", "text/plain")
            return
        asset = (self.owner.root / path[len(self.owner.prefix) :]).resolve()
        if not asset.is_relative_to(self.owner.root) or not asset.is_file():
            self._send(404, b"Not found", "text/plain")
            return
        body = asset.read_bytes()
        if asset == self.owner.root / "index.html":
            config = html.escape(
                json.dumps(
                    {
                        "build_id": self.owner.build_id,
                        "version": self.owner.version,
                        "attempt": self.owner.attempt,
                        "event_url": self.owner.control + "event",
                    }
                ),
                quote=True,
            )
            body = body.replace(
                b"<head>",
                f'<head><meta name="jot-startup" content="{config}">'.encode(),
                1,
            )
        ctype = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
        if asset.suffix in {".js", ".mjs"}:
            ctype = "application/javascript"
        self._send(200, body, ctype)

    def do_POST(self) -> None:
        if (
            not self._trusted()
            or urlsplit(self.path).path != self.owner.control + "event"
        ):
            self._send(403, b"Forbidden", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError("Invalid size")
            self.connection.settimeout(2)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not self.owner.receive_event(data):
                raise ValueError("Invalid event")
        except (ValueError, OSError):
            self._send(400, b"Invalid event", "text/plain")
            return
        self._send(200, b'{"ok":true}', "application/json")
