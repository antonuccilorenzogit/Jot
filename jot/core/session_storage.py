"""
Session storage footprint calculation and metrics caching for jot.
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
import threading
import time

PRECONVERTED_AUDIO_PARTIAL = "jot_preconverted_mono16k.partial.mp3"

_storage_info_cache: dict | None = None
_storage_info_cache_time: float = 0.0
_storage_info_future: concurrent.futures.Future[dict] | None = None
_STORAGE_INFO_TTL: float = 30.0
_storage_info_lock = threading.Lock()
_storage_info_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="storage_info"
)


def _folder_size(path: str) -> int:
    """Recursively compute folder size in bytes. Best-effort: skips unreadable files."""
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for fname in filenames:
                if fname == PRECONVERTED_AUDIO_PARTIAL:
                    continue
                try:
                    total += os.path.getsize(os.path.join(dirpath, fname))
                except Exception:
                    pass
    except Exception:
        pass
    return total


def _folder_newest_mtime(path: str) -> float:
    """
    Return the newest mtime of any file inside the folder (recursive).
    Falls back to the directory mtime itself if no files found.
    Cross-platform: on Windows, directory mtime is NOT updated when files inside
    change, so scanning file mtimes is necessary for correctness.
    """
    newest = 0.0
    try:
        for dirpath, _, filenames in os.walk(path):
            for fname in filenames:
                try:
                    mtime = os.path.getmtime(os.path.join(dirpath, fname))
                    if mtime > newest:
                        newest = mtime
                except Exception:
                    pass
        if newest == 0.0:
            try:
                newest = os.path.getmtime(path)
            except Exception:
                pass
    except Exception:
        pass
    return newest


def _compute_session_storage_info() -> dict:
    """
    Blocking FS traversal - call via get_session_storage_info() which caches
    the result and offloads the work to a background thread.
    """
    from jot.core.session_store import get_session_root

    total_bytes = 0
    total_sessions = 0
    root = get_session_root()
    try:
        if not os.path.isdir(root):
            return {"total_bytes": 0, "total_sessions": 0}
        for name in os.listdir(root):
            session_dir = os.path.join(root, name)
            if not os.path.isdir(session_dir):
                continue
            total_sessions += 1
            total_bytes += _folder_size(session_dir)
    except Exception:
        pass
    return {"total_bytes": total_bytes, "total_sessions": total_sessions}


def get_session_storage_info() -> dict:
    """
    Return total size in bytes and count of session folders in SESSION_ROOT.
    Result is cached for _STORAGE_INFO_TTL seconds.  The FS traversal runs in
    a dedicated single-worker thread so the caller is never blocked for longer
    than the OS I/O takes (bounded by a 10-second timeout).
    """
    global _storage_info_cache, _storage_info_cache_time, _storage_info_future
    now = time.time()
    with _storage_info_lock:
        if (
            _storage_info_cache is not None
            and (now - _storage_info_cache_time) < _STORAGE_INFO_TTL
        ):
            return dict(_storage_info_cache)
        compute_fn = _compute_session_storage_info
        if "jot.core.shared" in sys.modules:
            shared_mod = sys.modules["jot.core.shared"]
            if hasattr(shared_mod, "_compute_session_storage_info"):
                if (
                    shared_mod._compute_session_storage_info
                    is not _compute_session_storage_info
                ):
                    compute_fn = shared_mod._compute_session_storage_info
        if _storage_info_future is None or _storage_info_future.done():
            _storage_info_future = _storage_info_executor.submit(compute_fn)
        future = _storage_info_future
    try:
        result = future.result(timeout=10.0)
    except Exception:
        result = {"total_bytes": 0, "total_sessions": 0}
    with _storage_info_lock:
        _storage_info_cache = result
        _storage_info_cache_time = time.time()
    return dict(result)


def invalidate_session_storage_cache() -> None:
    """Bust the get_session_storage_info cache (call after deleting sessions)."""
    global _storage_info_cache, _storage_info_cache_time, _storage_info_future
    with _storage_info_lock:
        _storage_info_cache = None
        _storage_info_cache_time = 0.0
        _storage_info_future = None
