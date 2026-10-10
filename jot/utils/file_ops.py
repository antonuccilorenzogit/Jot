"""
File-system helpers shared by the WebView backend.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
import uuid
from typing import Any


def _safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _fsync_dir(path: str) -> None:
    """Best-effort directory fsync after an atomic rename (Linux/macOS only)."""
    try:
        dir_fd = os.open(os.path.dirname(os.path.abspath(path)) or ".", os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _atomic_write_text(path: str, text: str, mode: int | None = None) -> None:
    parent_dir = os.path.dirname(path)
    if parent_dir:
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception:
            pass

    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                fn = f.fileno()
                if isinstance(fn, int):
                    os.fsync(fn)
            except Exception:
                pass
        _replace = os.replace
        if "jot.core.shared" in sys.modules:
            shared_mod = sys.modules["jot.core.shared"]
            if hasattr(shared_mod, "os") and hasattr(shared_mod.os, "replace"):
                if shared_mod.os.replace is not os.replace:
                    _replace = shared_mod.os.replace
        _replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    if mode is not None and platform.system() != "Windows":
        try:
            os.chmod(path, mode)
        except Exception:
            pass

    _fsync_dir(path)


def _atomic_write_json(
    path: str, data: Any, indent: int | None = 2, mode: int | None = None
) -> None:
    parent_dir = os.path.dirname(path)
    if parent_dir:
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception:
            pass

    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            if indent is not None:
                json.dump(data, f, ensure_ascii=False, indent=indent)
            else:
                json.dump(data, f, ensure_ascii=False)
            f.flush()
            try:
                fn = f.fileno()
                if isinstance(fn, int):
                    os.fsync(fn)
            except Exception:
                pass
        _replace = os.replace
        if "jot.core.shared" in sys.modules:
            shared_mod = sys.modules["jot.core.shared"]
            if hasattr(shared_mod, "os") and hasattr(shared_mod.os, "replace"):
                if shared_mod.os.replace is not os.replace:
                    _replace = shared_mod.os.replace
        _replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    if mode is not None and platform.system() != "Windows":
        try:
            os.chmod(path, mode)
        except Exception:
            pass

    _fsync_dir(path)


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_HTML_CACHE_MAX = 200  # FIFO cap for write-lock entries
_HTML_GEN_MAX = (
    500  # separate FIFO cap for generation guards; larger to outlive lock evictions
)
_html_write_locks: dict[str, tuple[threading.Lock, int]] = {}
_html_last_gen: dict[str, int] = {}
_html_write_locks_meta = threading.Lock()


def _replace_with_retry(
    src: str, dst: str, max_retries: int = 5, delay: float = 0.02
) -> None:
    for attempt in range(max_retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)


class HTMLWriteLock:
    def __init__(self, path: str, lock: threading.Lock):
        self.path = path
        self.lock = lock

    def __enter__(self) -> HTMLWriteLock:
        self.lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            self.lock.release()
        finally:
            with _html_write_locks_meta:
                if self.path in _html_write_locks:
                    lock_obj, ref_count = _html_write_locks[self.path]
                    if lock_obj is self.lock:
                        if ref_count <= 1:
                            _html_write_locks[self.path] = (lock_obj, 0)
                        else:
                            _html_write_locks[self.path] = (lock_obj, ref_count - 1)


def _html_write_lock(path: str) -> HTMLWriteLock:
    with _html_write_locks_meta:
        if path not in _html_write_locks:
            # FIFO-like eviction of the first unused entry if at capacity
            if len(_html_write_locks) >= _HTML_CACHE_MAX:
                for oldest in list(_html_write_locks.keys()):
                    lock_obj, ref_count = _html_write_locks[oldest]
                    if ref_count == 0:
                        del _html_write_locks[oldest]
                        _html_last_gen.pop(oldest, None)
                        break
            _html_write_locks[path] = (threading.Lock(), 0)
        lock_obj, ref_count = _html_write_locks[path]
        _html_write_locks[path] = (lock_obj, ref_count + 1)
        return HTMLWriteLock(path, lock_obj)


def evict_html_paths_under(prefix: str) -> None:
    """Remove all lock/generation entries for paths under *prefix*.

    Called by delete_session so that stale entries are not left behind
    after a session folder is removed from disk.
    """
    with _html_write_locks_meta:
        all_keys = set(_html_write_locks) | set(_html_last_gen)
        to_evict = [k for k in all_keys if k.startswith(prefix)]
        for k in to_evict:
            if k in _html_write_locks:
                _lock_obj, ref_count = _html_write_locks[k]
                if ref_count == 0:
                    _html_write_locks.pop(k, None)
            _html_last_gen.pop(k, None)


_ALLOWED_OPEN_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".html",
        ".htm",
        ".docx",
        ".doc",
        ".pdf",
        ".txt",
        ".md",
    }
)


def open_path_with_default_app(path: str) -> None:
    if not isinstance(path, str) or not path:
        raise ValueError("Path non valido.")

    # URLs and mailto bypass filesystem validation entirely
    if (
        path.startswith("http://")
        or path.startswith("https://")
        or path.startswith("mailto:")
    ):
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            import subprocess

            subprocess.Popen(["open", path])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", path])
        return

    real = os.path.realpath(os.path.abspath(path))

    if not os.path.exists(real):
        raise FileNotFoundError(f"Percorso non trovato: {path!r}")

    if os.path.isfile(real):
        ext = os.path.splitext(real)[1].lower()
        if ext not in _ALLOWED_OPEN_EXTENSIONS:
            raise ValueError(f"Tipo di file non consentito: {ext!r}")
    # NOTE: Directories intentionally bypass extension checks.
    # open_file is only called with legitimate session directories from the bridge.

    if sys.platform == "win32":
        os.startfile(real)
        return

    import subprocess

    if sys.platform == "darwin":
        subprocess.Popen(["open", real])
    else:
        subprocess.Popen(["xdg-open", real])


def read_html_content(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError("File non trovato.")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def extract_html_shell(html: str) -> tuple[str, str] | None:
    """Return (open_tag, close_tag) wrapping the <body> of *html*, or None."""
    html_lower = html.lower()
    body_open_end = html_lower.find("<body")
    if body_open_end == -1:
        return None
    body_open_end = html_lower.find(">", body_open_end)
    body_close = html_lower.rfind("</body>")
    if body_open_end == -1 or body_close == -1 or body_close <= body_open_end:
        return None
    return html[: body_open_end + 1], html[body_close:]


def save_html_body_content(
    path: str,
    content: str,
    shell: tuple[str, str] | None = None,
    generation: int | None = None,
) -> bool:
    """Write body content to *path*. Returns False (without writing) if *generation*
    is provided and an equal-or-newer generation has already been committed."""
    if not path or not os.path.exists(path):
        raise FileNotFoundError("File originale non trovato.")

    from jot.utils.html_export import sanitize_html_basic

    body_inner = sanitize_html_basic(str(content or ""))

    tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    with _html_write_lock(path):
        with _html_write_locks_meta:
            if generation is not None and generation <= _html_last_gen.get(path, 0):
                return False
        if shell is not None:
            open_tag, close_tag = shell
        else:
            with open(path, encoding="utf-8") as handle:
                original_html = handle.read()
            extracted = extract_html_shell(original_html)
            if extracted is not None:
                open_tag, close_tag = extracted
            else:
                open_tag = close_tag = ""
        if open_tag and close_tag:
            updated_html = f"{open_tag}\n{body_inner}\n{close_tag}"
        else:
            updated_html = (
                "<!DOCTYPE html>\n"
                '<html>\n<head>\n<meta charset="utf-8">\n</head>\n'
                f"<body>\n{body_inner}\n</body>\n</html>\n"
            )
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(updated_html)
            _replace_with_retry(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        if generation is not None:
            with _html_write_locks_meta:
                _html_last_gen.pop(path, None)
                _html_last_gen[path] = generation
                # Best-effort FIFO eviction so _html_last_gen stays bounded independently of the lock dict.
                if len(_html_last_gen) > _HTML_GEN_MAX:
                    try:
                        _html_last_gen.pop(next(iter(_html_last_gen)))
                    except (StopIteration, KeyError):
                        pass
    return True
