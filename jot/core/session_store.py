"""
Session and autosave helpers for jot.

The pipeline still owns the orchestration, but session persistence, root directory
management, file fingerprinting, storage calculation, and cleanup live here.
"""

from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from jot.core.session_cleanup import (
    _TEMP_CHUNK_AUDIO_EXTS,
    SESSION_CLEANUP_MAX_AGE_DAYS,
    _cleanup_legacy_temp_chunks,
    _cleanup_session_temp_chunks,
    _is_old_enough,
    _resolve_session_html_path,
    _session_cleanup_kind,
    _session_completed_html_exists,
    cleanup_completed_sessions,
    cleanup_orphan_sessions,
    cleanup_orphan_temp_chunks,
)
from jot.core.session_storage import (
    _STORAGE_INFO_TTL,
    PRECONVERTED_AUDIO_PARTIAL,
    _compute_session_storage_info,
    _folder_newest_mtime,
    _folder_size,
    _storage_info_cache,
    _storage_info_cache_time,
    _storage_info_executor,
    _storage_info_future,
    _storage_info_lock,
    get_session_storage_info,
    invalidate_session_storage_cache,
)
from jot.pipeline.pipeline_settings import build_default_pipeline_settings
from jot.services.config_service import USER_HOME
from jot.utils.file_ops import (
    _atomic_write_json,
    _atomic_write_text,
    _fsync_dir,
    _load_json,
    _safe_mkdir,
)

PRECONVERTED_AUDIO_FINAL = "jot_preconverted_mono16k.mp3"
SESSION_SCHEMA_VERSION = 2

_LEGACY_SESSION_ROOT = os.path.join(USER_HOME, ".jot_sessions")
_DEFAULT_LEGACY_SESSION_ROOT = _LEGACY_SESSION_ROOT


def _get_default_session_root(user_home: str) -> str:
    """
    Return the default session-storage root for the current platform.
    - Windows: %LOCALAPPDATA%\\jot\\sessions  (not synced by OneDrive)
    - macOS:   ~/Library/Caches/jot/sessions   (excluded from iCloud)
    - Linux:   ~/.jot_sessions                  (unchanged)
    """
    system = None
    if "jot.core.shared" in sys.modules:
        shared_mod = sys.modules["jot.core.shared"]
        if hasattr(shared_mod, "platform") and hasattr(shared_mod.platform, "system"):
            try:
                system = shared_mod.platform.system()
            except Exception:
                pass
    if system is None:
        system = platform.system()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA") or os.path.join(
            user_home, "AppData", "Local"
        )
        return os.path.join(local_app_data, "jot", "sessions")
    if system == "Darwin":
        return os.path.join(user_home, "Library", "Caches", "jot", "sessions")
    return os.path.join(user_home, ".jot_sessions")


SESSION_ROOT = _get_default_session_root(USER_HOME)
_last_set_session_root = SESSION_ROOT
_last_set_legacy_session_root = _LEGACY_SESSION_ROOT


def get_session_root() -> str:
    """Return the current session-storage root directory (may be overridden at runtime)."""
    global _last_set_session_root
    root = SESSION_ROOT
    if "jot.core.shared" in sys.modules:
        shared_mod = sys.modules["jot.core.shared"]
        shared_root = getattr(shared_mod, "SESSION_ROOT", None)
        if shared_root is not None and shared_root != _last_set_session_root:
            root = shared_root
    if os.path.exists(root):
        try:
            real_root = os.path.realpath(root)
            if real_root != root:
                set_session_root(real_root)
                return real_root
        except Exception:
            pass
    return root


def set_session_root(path: str) -> None:
    """Override the session-storage root directory at runtime."""
    global SESSION_ROOT, _last_set_session_root
    p_str = str(path).strip()
    if os.path.exists(p_str):
        try:
            p_str = os.path.realpath(p_str)
        except Exception:
            pass
    SESSION_ROOT = p_str
    _last_set_session_root = SESSION_ROOT
    if "jot.core.shared" in sys.modules:
        try:
            setattr(sys.modules["jot.core.shared"], "SESSION_ROOT", p_str)  # noqa: B010
        except Exception:
            pass


def migrate_legacy_session_root() -> bool:
    """
    On first launch after an upgrade, move ~/.jot_sessions to the new
    platform-appropriate default (LOCALAPPDATA on Windows, Library/Caches on macOS).
    No-op if the legacy path is absent, new default already exists, or both paths
    are identical (Linux). Returns True if migration was performed.
    """
    new_root = get_session_root()
    old_root = _LEGACY_SESSION_ROOT
    if "jot.core.shared" in sys.modules:
        shared_mod = sys.modules["jot.core.shared"]
        shared_legacy = getattr(shared_mod, "_LEGACY_SESSION_ROOT", None)
        if shared_legacy is not None and shared_legacy != _last_set_legacy_session_root:
            old_root = shared_legacy
    if (
        old_root == _last_set_legacy_session_root
        and _LEGACY_SESSION_ROOT != _last_set_legacy_session_root
    ):
        old_root = _LEGACY_SESSION_ROOT
    if os.path.normcase(os.path.normpath(new_root)) == os.path.normcase(
        os.path.normpath(old_root)
    ):
        return False  # Linux: paths are identical, nothing to do
    if not os.path.isdir(old_root):
        return False  # No legacy sessions to migrate
    if os.path.isdir(new_root):
        return False  # New location already exists; previous migration done
    try:
        os.makedirs(os.path.dirname(new_root), exist_ok=True)
        shutil.move(old_root, new_root)
        return True
    except Exception:
        return False


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _file_fingerprint(path: str) -> dict:
    abs_path = os.path.abspath(path)
    st = os.stat(abs_path)
    return {
        "path": abs_path,
        "size": int(getattr(st, "st_size", 0)),
        "mtime": float(getattr(st, "st_mtime", 0.0)),
    }


def _partial_file_hash(path: str, max_bytes: int = 1048576) -> str:
    """
    Calcola SHA256 dei primi max_bytes del file.
    Usato per identificare file identici indipendentemente dal path.
    Leggere solo il primo 1 MB è veloce anche per file multi-gigabyte e riduce
    le collisioni su lezioni molto lunghe rispetto ai precedenti 64 KB.
    """
    try:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            chunk = f.read(max_bytes)
            hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


def _file_tail_hash(path: str, max_bytes: int = 1048576, file_size: int = -1) -> str:
    """
    Calcola SHA256 degli ultimi max_bytes del file.
    Complementa _partial_file_hash per distinguere file con stesso inizio ma
    diversa fine (es. lezioni dello stesso corso con intro identica).
    Per file più piccoli di max_bytes torna l'hash dell'intero file.
    """
    try:
        size = file_size if file_size >= 0 else os.path.getsize(path)
        offset = max(0, size - max_bytes)
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            if offset > 0:
                f.seek(offset)
            chunk = f.read(max_bytes)
            hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


_session_id_cache: dict[tuple, str] = {}
_MAX_SESSION_CACHE_SIZE = 500  # LRU cap: at ~200 bytes per entry this stays well under 100 KB; prevents unbounded growth in long-running processes


def _session_id_for_file(path: str) -> str:
    """
    Genera ID sessione basato su size, head hash e tail hash.
    Il tail hash distingue file con intro identica ma contenuto diverso.
    mtime_ns partecipa solo alla cache process-local, non all'ID durevole.
    """
    abs_path = os.path.abspath(path)
    st = os.stat(abs_path)
    size = int(getattr(st, "st_size", 0))
    mtime_ns = int(getattr(st, "st_mtime_ns", 0)) or int(st.st_mtime * 1_000_000_000)

    cache_key = (abs_path, size, mtime_ns)
    _cached = _session_id_cache.get(cache_key)
    if _cached is not None:
        return _cached

    # LRU eviction: remove oldest entry if at capacity
    if len(_session_id_cache) >= _MAX_SESSION_CACHE_SIZE:
        _session_id_cache.pop(next(iter(_session_id_cache)))

    head_hash = _partial_file_hash(abs_path)
    tail_hash = (
        head_hash if size <= 1048576 else _file_tail_hash(abs_path, file_size=size)
    )
    blob = json.dumps(
        {
            "size": size,
            "head_hash": head_hash,
            "tail_hash": tail_hash,
        },
        sort_keys=True,
    ).encode("utf-8", errors="ignore")
    result = hashlib.sha256(blob).hexdigest()
    _session_id_cache[cache_key] = result
    return result


def _session_dir_for_file(path: str) -> str:
    return os.path.join(get_session_root(), _session_id_for_file(path))


class SessionCollisionError(Exception):
    """Raised when initialize_session_context would silently destroy a completed session.

    Occurs when resume_session=False and the computed session directory already
    contains a finished sbobina (stage=='done' + existing HTML output).  This
    protects against the fingerprint-collision scenario where two different
    recordings resolve to the same session ID and the newer file would wipe the
    older completed work without any user confirmation.
    """

    def __init__(self, session_dir: str) -> None:
        self.session_dir = session_dir
        super().__init__("session_collision")


@dataclass(frozen=True)
class SessionPaths:
    session_dir: str
    session_path: str
    phase1_chunks_dir: str
    phase2_revised_dir: str
    macro_path: str


def resolve_session_paths(
    input_path: str, session_dir_hint: str | None = None
) -> SessionPaths:
    try:
        _safe_mkdir(get_session_root())
    except Exception:
        pass

    try:
        session_dir = (
            os.path.abspath(session_dir_hint)
            if session_dir_hint
            else _session_dir_for_file(input_path)
        )
    except Exception:
        session_dir = os.path.join(tempfile.gettempdir(), "jot_session_fallback")

    return SessionPaths(
        session_dir=session_dir,
        session_path=os.path.join(session_dir, "session.json"),
        phase1_chunks_dir=os.path.join(session_dir, "phase1_chunks"),
        phase2_revised_dir=os.path.join(session_dir, "phase2_revised"),
        macro_path=os.path.join(session_dir, "phase2_macro_blocks.json"),
    )


def ensure_session_dirs(paths: SessionPaths) -> None:
    _safe_mkdir(paths.session_dir)
    _safe_mkdir(paths.phase1_chunks_dir)
    _safe_mkdir(paths.phase2_revised_dir)


def _completed_html_output_exists(paths: SessionPaths) -> bool:
    try:
        session = load_session(paths.session_path)
        if str(session.get("stage", "")).strip().lower() != "done":
            return False
        outputs = session.get("outputs", {})
        html_path = str(outputs.get("html", "") if isinstance(outputs, dict) else "")
        return bool(html_path and os.path.exists(html_path))
    except Exception:
        return False


def reset_session_dirs(
    paths: SessionPaths, *, allow_completed_destroy: bool = False
) -> None:
    if (
        not allow_completed_destroy
        and os.path.exists(paths.session_dir)
        and _completed_html_output_exists(paths)
    ):
        raise SessionCollisionError(paths.session_dir)
    if os.path.exists(paths.session_dir):
        import shutil

        shutil.rmtree(paths.session_dir, ignore_errors=True)
    ensure_session_dirs(paths)


def load_session(session_path: str):
    return _load_json(session_path)


def save_session(session_path: str, session: dict) -> None:
    session["updated_at"] = _now_iso()
    _atomic_write_json(session_path, session)


def _update_session(session: dict, updates: dict) -> dict:
    """Return a deep copy of the session before applying updates."""
    snapshot = copy.deepcopy(session)
    session.update(updates)
    return snapshot


def mark_html_exported(session: dict) -> dict:
    return _update_session(session, {"user_edited": False})


def new_session(input_path: str, settings: dict | None = None) -> dict:
    try:
        fp = _file_fingerprint(input_path)
    except Exception:
        fp = {"path": os.path.abspath(input_path), "size": None, "mtime": None}

    return {
        "schema_version": SESSION_SCHEMA_VERSION,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "stage": "phase1",
        "input": fp,
        "settings": settings or build_default_pipeline_settings(),
        "phase1": {"next_start_sec": 0, "chunks_done": 0, "memoria_precedente": ""},
        "phase2": {"macro_total": 0, "revised_done": 0},
        "outputs": {},
        "last_error": None,
        "last_error_detail": None,
        "retry_state": None,
    }


def migrate_session(session: dict) -> tuple[dict, bool]:
    """Apply pending schema migrations in-place and return (session, was_changed).

    Migrations run sequentially so a session at any older version is always
    brought up to SESSION_SCHEMA_VERSION.  Callers own the deep-copy if needed.

    Adding a new migration: bump SESSION_SCHEMA_VERSION in shared.py and add an
    ``if version < N:`` block here that transforms/defaults the new fields.
    """
    try:
        version = int(session.get("schema_version", 0) or 0)
    except (ValueError, TypeError):
        version = 0
    changed = False

    if version < 1:
        # v0 (pre-versioning) → v1: fill in all required top-level keys.
        session.setdefault("stage", "phase1")
        session.setdefault("phase1", {})
        session.setdefault("phase2", {})
        session.setdefault("outputs", {})
        session.setdefault("last_error", None)
        session.setdefault("last_error_detail", None)
        session["schema_version"] = 1
        changed = True

    if version < 2:
        session.setdefault("retry_state", None)
        session["schema_version"] = 2
        changed = True

    # Future migrations go here:
    # if version < 3:
    #     session.setdefault("new_field", default_value)
    #     session["schema_version"] = 3
    #     changed = True

    return session, changed


def clone_session_settings(session: dict) -> dict:
    try:
        return json.loads(json.dumps(session.get("settings", {}), ensure_ascii=False))
    except Exception:
        return dict(session.get("settings", {}))


__all__ = [
    "PRECONVERTED_AUDIO_FINAL",
    "PRECONVERTED_AUDIO_PARTIAL",
    "SESSION_CLEANUP_MAX_AGE_DAYS",
    "SESSION_ROOT",
    "SESSION_SCHEMA_VERSION",
    "_MAX_SESSION_CACHE_SIZE",
    "_STORAGE_INFO_TTL",
    "_TEMP_CHUNK_AUDIO_EXTS",
    "SessionCollisionError",
    "SessionPaths",
    "_cleanup_legacy_temp_chunks",
    "_cleanup_session_temp_chunks",
    "_completed_html_output_exists",
    "_compute_session_storage_info",
    "_file_fingerprint",
    "_file_tail_hash",
    "_folder_newest_mtime",
    "_folder_size",
    "_get_default_session_root",
    "_is_old_enough",
    "_now_iso",
    "_partial_file_hash",
    "_resolve_session_html_path",
    "_session_cleanup_kind",
    "_session_completed_html_exists",
    "_session_dir_for_file",
    "_session_id_cache",
    "_session_id_for_file",
    "_storage_info_cache",
    "_storage_info_cache_time",
    "_storage_info_executor",
    "_storage_info_future",
    "_storage_info_lock",
    "_update_session",
    "cleanup_completed_sessions",
    "cleanup_orphan_sessions",
    "cleanup_orphan_temp_chunks",
    "clone_session_settings",
    "ensure_session_dirs",
    "get_session_root",
    "get_session_storage_info",
    "invalidate_session_storage_cache",
    "load_session",
    "mark_html_exported",
    "migrate_legacy_session_root",
    "migrate_session",
    "new_session",
    "reset_session_dirs",
    "resolve_session_paths",
    "save_session",
    "set_session_root",
]
