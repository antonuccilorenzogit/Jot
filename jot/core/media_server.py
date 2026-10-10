"""
Small local HTTP media streamer for the React audio player.
"""

from __future__ import annotations

import http.server
import mimetypes
import os
import re
import socketserver
import threading
import time
import uuid
from typing import ClassVar


def detect_media_content_type(path: str) -> str:
    """Detect media MIME content-type using mimetypes or container magic bytes."""
    ctype, _ = mimetypes.guess_type(path)
    if ctype:
        return ctype
    try:
        with open(path, "rb") as handle:
            header = handle.read(64)
        if len(header) >= 8:
            if header[4:8] == b"ftyp":
                brand = header[8:12].strip()
                if brand in (b"M4A", b"M4B", b"M4P"):
                    return "audio/mp4"
                return "video/mp4"
            if header[:3] == b"ID3" or (
                header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
            ):
                return "audio/mpeg"
            if header[:4] == b"RIFF" and len(header) >= 12 and header[8:12] == b"WAVE":
                return "audio/wav"
            if header[:4] == b"OggS":
                return "audio/ogg"
            if header[:4] == b"fLaC":
                return "audio/flac"
            if header[:4] == b"\x1a\x45\xdf\xa3":
                return "video/webm"
    except Exception:
        pass
    return "audio/mpeg"


class LocalMediaServer:
    _servers: ClassVar[dict[str, tuple[socketserver.ThreadingTCPServer, int, str]]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()
    MAX_ENTRIES = 5  # LRU cap to prevent port exhaustion

    @classmethod
    def _evict_oldest_if_needed(cls):
        """Shutdown and remove oldest server if over MAX_ENTRIES."""
        if len(cls._servers) < cls.MAX_ENTRIES:
            return
        # Pop oldest entry (dict preserves insertion order in Python 3.7+)
        oldest_path = next(iter(cls._servers))
        oldest_server, _, _ = cls._servers.pop(oldest_path)
        threading.Thread(
            target=lambda: (oldest_server.shutdown(), oldest_server.server_close()),
            daemon=True,
        ).start()

    @classmethod
    def stream_url_for_file(cls, file_path: str) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError("File audio non trovato.")

        with cls._lock:
            if file_path in cls._servers:
                entry = cls._servers.pop(file_path)
                cls._servers[file_path] = entry
                _, port, token = entry
                return f"http://127.0.0.1:{port}/stream-{token}/media?t={time.time()}"

            served_path = file_path
            token = uuid.uuid4().hex

            class MediaHandler(http.server.BaseHTTPRequestHandler):
                def end_headers(self):
                    origin = self.headers.get("Origin", "")
                    # In production (pywebview), Origin is typically empty or a file:// URL.
                    # In dev mode (Vite), it's http://localhost:3000.
                    # Only allow the specific dev server origin, not arbitrary localhost ports.
                    if origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
                        self.send_header("Access-Control-Allow-Origin", origin)
                    super().end_headers()

                def do_GET(self):
                    if self.path.split("?", 1)[0] != f"/stream-{token}/media":
                        self.send_error(404)
                        return
                    try:
                        path = served_path
                        if not os.path.exists(path):
                            self.send_error(404, "File not found")
                            return

                        size = os.path.getsize(path)
                        start, end = 0, size - 1
                        status_code = 200
                        range_header = self.headers.get("Range")
                        if range_header:
                            stripped = range_header.strip()
                            suffix_match = re.fullmatch(r"bytes=-(\d+)", stripped)
                            start_match = re.fullmatch(r"bytes=(\d+)-(\d*)", stripped)
                            if suffix_match:
                                suffix_len = int(suffix_match.group(1))
                                if suffix_len == 0 or size == 0:
                                    self.send_response(416)
                                    self.send_header("Content-Range", f"bytes */{size}")
                                    self.end_headers()
                                    return
                                start = max(0, size - suffix_len)
                                end = size - 1
                                status_code = 206
                            elif start_match:
                                start = int(start_match.group(1))
                                if start >= size:
                                    self.send_response(416)
                                    self.send_header("Content-Range", f"bytes */{size}")
                                    self.end_headers()
                                    return
                                if start_match.group(2):
                                    end = min(int(start_match.group(2)), size - 1)
                                else:
                                    end = size - 1
                                if end < start:
                                    self.send_response(416)
                                    self.send_header("Content-Range", f"bytes */{size}")
                                    self.end_headers()
                                    return
                                status_code = 206

                        length = end - start + 1
                        self.send_response(status_code)
                        ctype = detect_media_content_type(path)
                        self.send_header("Content-Type", ctype)
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Length", str(length))
                        if status_code == 206:
                            self.send_header(
                                "Content-Range", f"bytes {start}-{end}/{size}"
                            )
                        self.end_headers()

                        with open(path, "rb") as handle:
                            handle.seek(start)
                            remaining = length
                            while remaining > 0:
                                chunk = handle.read(min(remaining, 65536))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                    except Exception:
                        pass

                def log_message(self, format, *args):
                    pass

            cls._evict_oldest_if_needed()

            server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), MediaHandler)
            # An open player connection must not block window or process shutdown.
            server.daemon_threads = True
            port = server.server_address[1]
            cls._servers[file_path] = (server, port, token)
        threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.05), daemon=True
        ).start()
        return f"http://127.0.0.1:{port}/stream-{token}/media?t={time.time()}"

    @classmethod
    def shutdown_all(cls):
        """Shutdown all servers. Called on app exit."""
        with cls._lock:
            for server, _, _ in cls._servers.values():
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
            cls._servers.clear()
