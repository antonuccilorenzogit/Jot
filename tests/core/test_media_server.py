"""Regression tests for LocalMediaServer."""

import os
import re
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from jot.core.media_server import (
    LocalMediaServer,
    detect_media_content_type,
)


def _fake_server():
    srv = MagicMock()
    srv.server_address = ("127.0.0.1", 0)
    return srv


class EvictOldestTests(unittest.TestCase):
    def setUp(self):
        LocalMediaServer._servers.clear()

    def tearDown(self):
        LocalMediaServer._servers.clear()

    def test_no_error_at_capacity(self):
        """_evict_oldest_if_needed must not raise TypeError when _servers is a plain dict."""
        for i in range(LocalMediaServer.MAX_ENTRIES):
            LocalMediaServer._servers[f"/fake/path_{i}.mp3"] = (
                _fake_server(),
                9000 + i,
                "tok",
            )

        try:
            LocalMediaServer._evict_oldest_if_needed()
        except TypeError as exc:
            self.fail(f"_evict_oldest_if_needed raised TypeError: {exc}")

    def test_removes_first_inserted(self):
        """The oldest (first-inserted) entry is the one evicted."""
        paths = [f"/fake/path_{i}.mp3" for i in range(LocalMediaServer.MAX_ENTRIES)]
        for i, p in enumerate(paths):
            LocalMediaServer._servers[p] = (_fake_server(), 9000 + i, "tok")

        LocalMediaServer._evict_oldest_if_needed()

        self.assertNotIn(paths[0], LocalMediaServer._servers)
        for p in paths[1:]:
            self.assertIn(p, LocalMediaServer._servers)

    def test_noop_below_capacity(self):
        """No eviction occurs when below MAX_ENTRIES."""
        for i in range(LocalMediaServer.MAX_ENTRIES - 1):
            LocalMediaServer._servers[f"/fake/path_{i}.mp3"] = (
                _fake_server(),
                9000 + i,
                "tok",
            )

        LocalMediaServer._evict_oldest_if_needed()

        self.assertEqual(
            len(LocalMediaServer._servers), LocalMediaServer.MAX_ENTRIES - 1
        )

    def test_evict_calls_shutdown(self):
        """Evicted server's shutdown and server_close are called."""
        oldest = _fake_server()
        LocalMediaServer._servers["/fake/oldest.mp3"] = (oldest, 9000, "tok")
        for i in range(1, LocalMediaServer.MAX_ENTRIES):
            LocalMediaServer._servers[f"/fake/path_{i}.mp3"] = (
                _fake_server(),
                9000 + i,
                "tok",
            )

        LocalMediaServer._evict_oldest_if_needed()

        threading.Event().wait(0.1)
        oldest.shutdown.assert_called_once()
        oldest.server_close.assert_called_once()

    def test_cache_hit_survives_eviction(self):
        """A cache hit moves an entry to MRU so the next-oldest item is evicted."""
        paths = [f"/fake/path_{i}.mp3" for i in range(LocalMediaServer.MAX_ENTRIES - 1)]
        for i, path in enumerate(paths):
            LocalMediaServer._servers[path] = (_fake_server(), 9000 + i, "tok")

        entry = LocalMediaServer._servers.pop(paths[0])
        LocalMediaServer._servers[paths[0]] = entry

        LocalMediaServer._servers["/fake/new.mp3"] = (_fake_server(), 9099, "tok")
        LocalMediaServer._evict_oldest_if_needed()

        self.assertIn(paths[0], LocalMediaServer._servers)
        self.assertNotIn(paths[1], LocalMediaServer._servers)


class RangeRequestTests(unittest.TestCase):
    def setUp(self):
        LocalMediaServer.shutdown_all()
        LocalMediaServer._servers.clear()
        self._tmp_path = None

    def tearDown(self):
        LocalMediaServer.shutdown_all()
        LocalMediaServer._servers.clear()
        if self._tmp_path and os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)

    def _make_url(self, data: bytes) -> str:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        try:
            tmp.write(data)
        finally:
            tmp.close()
        self._tmp_path = tmp.name
        return LocalMediaServer.stream_url_for_file(self._tmp_path)

    def test_url_contains_secret_token(self):
        """Returned URL must embed a hex token in the path."""
        url = self._make_url(b"hello")
        path = url.split("?", 1)[0]
        self.assertRegex(path, r"http://127\.0\.0\.1:\d+/stream-[0-9a-f]{32}/media")

    def test_wrong_token_returns_404(self):
        """A request with a different token in the path must return 404."""
        url = self._make_url(b"hello")
        wrong_url = re.sub(
            r"/stream-[0-9a-f]+/", "/stream-deadbeef0000000000000000deadbeef/", url
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(wrong_url, timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_root_path_returns_404(self):
        """A bare request to / must return 404."""
        url = self._make_url(b"hello")
        m = re.match(r"http://127\.0\.0\.1:\d+", url)
        self.assertIsNotNone(m, f"URL did not match expected pattern: {url!r}")
        assert m is not None
        base = m.group(0)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{base}/", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_cache_hit_returns_same_token(self):
        """A second call for the same file must reuse the same token (cache hit)."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        try:
            tmp.write(b"data")
        finally:
            tmp.close()
        self._tmp_path = tmp.name
        url1 = LocalMediaServer.stream_url_for_file(self._tmp_path)
        url2 = LocalMediaServer.stream_url_for_file(self._tmp_path)
        m1 = re.search(r"/stream-([0-9a-f]+)/", url1)
        m2 = re.search(r"/stream-([0-9a-f]+)/", url2)
        self.assertIsNotNone(m1, f"url1 missing stream token: {url1!r}")
        self.assertIsNotNone(m2, f"url2 missing stream token: {url2!r}")
        assert m1 is not None
        assert m2 is not None
        token1 = m1.group(1)
        token2 = m2.group(1)
        self.assertEqual(token1, token2)

    def test_unsatisfiable_range_returns_416(self):
        """bytes=50-60 on a 10-byte file must return 416."""
        url = self._make_url(b"0123456789")
        req = urllib.request.Request(url, headers={"Range": "bytes=50-60"})

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 416)
        self.assertEqual(ctx.exception.headers.get("Content-Range"), "bytes */10")

    def test_suffix_range_returns_last_bytes(self):
        """bytes=-4 must return the final four bytes as partial content."""
        url = self._make_url(b"0123456789")
        req = urllib.request.Request(url, headers={"Range": "bytes=-4"})

        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers.get("Content-Range"), "bytes 6-9/10")
            self.assertEqual(response.read(), b"6789")


class ShutdownTests(unittest.TestCase):
    def _assert_shutdown_with_open_client(self, *, stream_body: bool) -> None:
        LocalMediaServer.shutdown_all()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "track.mp3")
            with open(path, "wb") as handle:
                handle.truncate(64 * 1024 * 1024 if stream_body else 10)
            url = urlsplit(LocalMediaServer.stream_url_for_file(path))
            server = LocalMediaServer._servers[path][0]
            request_started = threading.Event()
            request_threads: list[threading.Thread] = []
            original_process_request = server.process_request_thread

            def process_request(request, client_address):
                request_threads.append(threading.current_thread())
                request_started.set()
                original_process_request(request, client_address)

            client = socket.socket()
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            client.settimeout(5)
            closer = threading.Thread(target=LocalMediaServer.shutdown_all, daemon=True)
            with patch.object(server, "process_request_thread", process_request):
                try:
                    client.connect(server.server_address)
                    request = f"GET {url.path} HTTP/1.1\r\n"
                    if stream_body:
                        request += "Host: localhost\r\nConnection: close\r\n\r\n"
                    client.sendall(request.encode("ascii"))
                    self.assertTrue(request_started.wait(5), "Request was not accepted")
                    if stream_body:
                        headers = b""
                        while not headers.endswith(b"\r\n\r\n"):
                            byte = client.recv(1)
                            self.assertTrue(
                                byte, "Connection closed before the headers"
                            )
                            headers += byte
                        self.assertTrue(headers.startswith(b"HTTP/1.0 200"))
                        # Keep the body unread, as with a full player buffer or pause.

                    closer.start()
                    closer.join(timeout=1)
                    self.assertFalse(
                        closer.is_alive(), "Shutdown waited for the open audio request"
                    )
                    self.assertEqual(LocalMediaServer._servers, {})
                    with self.assertRaises(OSError):
                        with socket.create_connection(
                            ("127.0.0.1", server.server_address[1]), timeout=1
                        ):
                            self.fail("Audio listener is still accepting connections")
                finally:
                    # Release blocked requests even when testing the broken behavior.
                    try:
                        client.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    client.close()
                    if closer.ident is not None:
                        closer.join(timeout=5)
                        self.assertFalse(closer.is_alive(), "Shutdown did not clean up")
                    else:
                        LocalMediaServer.shutdown_all()
                    for request_thread in request_threads:
                        request_thread.join(timeout=5)
                        self.assertFalse(
                            request_thread.is_alive(), "Audio request did not clean up"
                        )

    def test_shutdown_does_not_wait_for_unread_audio_body(self):
        self._assert_shutdown_with_open_client(stream_body=True)

    def test_shutdown_does_not_wait_for_incomplete_request_headers(self):
        self._assert_shutdown_with_open_client(stream_body=False)


class DetectContentTypeTests(unittest.TestCase):
    def test_detects_by_extension_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            p_mp3 = os.path.join(td, "track.mp3")
            with open(p_mp3, "wb") as f:
                f.write(b"any data")
            self.assertEqual(detect_media_content_type(p_mp3), "audio/mpeg")

    def test_detects_m4a_magic_bytes_without_extension(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "lecture_recording")
            with open(p, "wb") as f:
                f.write(b"\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00M4A isommp42")
            self.assertEqual(detect_media_content_type(p), "audio/mp4")

    def test_detects_mp4_magic_bytes_without_extension(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "video_recording")
            with open(p, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
            self.assertEqual(detect_media_content_type(p), "video/mp4")

    def test_detects_audio_magic_headers(self):
        cases = [
            (b"ID3\x04\x00\x00\x00\x00\x00\x00", "audio/mpeg"),
            (b"\xff\xfb\x90\x44\x00\x00\x00\x00", "audio/mpeg"),
            (b"RIFF\x24\x00\x00\x00WAVEfmt ", "audio/wav"),
            (b"OggS\x00\x02\x00\x00\x00\x00\x00", "audio/ogg"),
            (b"fLaC\x00\x00\x00\x22\x00\x00\x00", "audio/flac"),
            (b"\x1a\x45\xdf\xa3\x93\x42\x82\x88", "video/webm"),
            (b"plain text without magic bytes", "audio/mpeg"),
        ]
        with tempfile.TemporaryDirectory() as td:
            for idx, (header, expected_mime) in enumerate(cases):
                p = os.path.join(td, f"file_{idx}")
                with open(p, "wb") as f:
                    f.write(header)
                self.assertEqual(
                    detect_media_content_type(p),
                    expected_mime,
                    f"Failed for header: {header!r}",
                )


if __name__ == "__main__":
    unittest.main()
