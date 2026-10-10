"""
Orphan and temporary resource cleanup routines for jot.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time

from jot.core.session_storage import (
    _folder_newest_mtime,
    _folder_size,
    invalidate_session_storage_cache,
)
from jot.utils.file_ops import _load_json

SESSION_CLEANUP_MAX_AGE_DAYS = 14
_TEMP_CHUNK_AUDIO_EXTS = (".mp3", ".wav", ".m4a")


def _is_old_enough(path: str, now: float, max_age_seconds: int) -> bool:
    try:
        age = now - float(os.path.getmtime(path))
        return age >= max(0, int(max_age_seconds))
    except Exception:
        return False


def _cleanup_legacy_temp_chunks(tmpdir: str, now: float, max_age_seconds: int) -> int:
    removed = 0
    try:
        for name in os.listdir(tmpdir):
            low = name.lower()
            if not low.startswith("jot_temp_"):
                continue
            if not low.endswith(_TEMP_CHUNK_AUDIO_EXTS):
                continue
            path = os.path.join(tmpdir, name)
            try:
                if not _is_old_enough(path, now, max_age_seconds):
                    continue
                os.remove(path)
                removed += 1
            except Exception:
                pass
    except Exception:
        pass
    return removed


def _cleanup_session_temp_chunks(now: float, max_age_seconds: int) -> int:
    from jot.core.session_store import get_session_root

    removed = 0
    try:
        session_root = get_session_root()
        with os.scandir(session_root) as sessions:
            for session_entry in sessions:
                try:
                    if not session_entry.is_dir():
                        continue
                    temp_chunks_dir = os.path.join(session_entry.path, "temp_chunks")
                    if not os.path.isdir(temp_chunks_dir):
                        continue
                    with os.scandir(temp_chunks_dir) as run_dirs:
                        for run_entry in run_dirs:
                            try:
                                name = run_entry.name.lower()
                                if (
                                    not name.startswith("run_")
                                    or not run_entry.is_dir()
                                ):
                                    continue
                                run_dir_old = _is_old_enough(
                                    run_entry.path,
                                    now,
                                    max_age_seconds,
                                )
                                removed_in_run = 0
                                with os.scandir(run_entry.path) as chunk_files:
                                    for chunk_entry in chunk_files:
                                        try:
                                            chunk_name = chunk_entry.name.lower()
                                            if not chunk_entry.is_file():
                                                continue
                                            if not chunk_name.startswith("chunk_"):
                                                continue
                                            if not chunk_name.endswith(
                                                _TEMP_CHUNK_AUDIO_EXTS
                                            ):
                                                continue
                                            if not _is_old_enough(
                                                chunk_entry.path,
                                                now,
                                                max_age_seconds,
                                            ):
                                                continue
                                            os.remove(chunk_entry.path)
                                            removed += 1
                                            removed_in_run += 1
                                        except Exception:
                                            pass
                                if run_dir_old or removed_in_run > 0:
                                    try:
                                        os.rmdir(run_entry.path)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                except Exception:
                    pass
    except Exception:
        pass
    return removed


def cleanup_orphan_temp_chunks(max_age_seconds: int = 12 * 3600) -> int:
    """
    Best-effort cleanup of temp chunk files left behind by crashes/forced closes.
    """
    now = time.time()
    removed = _cleanup_legacy_temp_chunks(tempfile.gettempdir(), now, max_age_seconds)
    removed += _cleanup_session_temp_chunks(now, max_age_seconds)

    # Clean up orphaned Inno Setup executables from system Temp directory
    try:
        tmpdir = tempfile.gettempdir()
        for name in os.listdir(tmpdir):
            if name.startswith("jot-Setup-") and name.endswith(".exe"):
                path = os.path.join(tmpdir, name)
                if _is_old_enough(path, now, max_age_seconds):
                    try:
                        os.remove(path)
                        removed += 1
                    except Exception:
                        pass
    except Exception:
        pass

    return removed


def _resolve_session_html_path(session_dir: str, html_path: object) -> str:
    value = str(html_path or "").strip()
    if not value:
        return ""
    if os.path.isabs(value):
        return value
    return os.path.join(session_dir, value)


def _session_completed_html_exists(session_dir: str, session: dict) -> bool:
    outputs = session.get("outputs", {})
    html_path = str(outputs.get("html", "") if isinstance(outputs, dict) else "")
    resolved = _resolve_session_html_path(session_dir, html_path)
    if resolved and os.path.isfile(resolved):
        return True
    if html_path:
        fallback = os.path.join(session_dir, os.path.basename(html_path))
        if os.path.isfile(fallback):
            return True
    return False


def _session_cleanup_kind(session_dir: str) -> str:
    session_path = os.path.join(session_dir, "session.json")
    try:
        session = _load_json(session_path)
    except Exception:
        return "incomplete"
    if not isinstance(session, dict):
        return "incomplete"
    if str(session.get("stage", "")).strip().lower() != "done":
        return "incomplete"
    if _session_completed_html_exists(session_dir, session):
        return "completed"
    return "completed_missing_html"


def cleanup_orphan_sessions(
    max_age_days: int = 0,
    *,
    mode: str = "incomplete",
    dry_run: bool = False,
) -> dict:
    """
    Delete selected session folders in SESSION_ROOT. If max_age_days > 0, only folders
    whose newest file mtime is older than max_age_days days are deleted. When max_age_days <= 0,
    all matching folders are deleted regardless of age.
    Returns a summary dict with keys:
      removed     - number of folders successfully deleted
      freed_bytes - total bytes freed
      errors      - number of folders that could not be deleted
    Best-effort: individual folder errors do not abort the whole sweep.
    """
    from jot.core.session_store import get_session_root

    removed = 0
    freed_bytes = 0
    errors = 0
    candidates = 0
    preserved_completed = 0
    missing_completed_html = 0
    deleted_paths: list[str] = []
    mode = str(mode or "incomplete").strip().lower()
    if mode not in {"incomplete", "completed"}:
        raise ValueError("cleanup mode non valida")
    session_root = get_session_root()
    try:
        if not os.path.isdir(session_root):
            return {
                "removed": 0,
                "freed_bytes": 0,
                "errors": 0,
                "candidates": 0,
                "preserved_completed": 0,
                "missing_completed_html": 0,
                "deleted_paths": [],
            }
        now = time.time()
        age_days = max(0, int(max_age_days))
        cutoff = (now - age_days * 86400) if age_days > 0 else None
        for name in os.listdir(session_root):
            session_dir = os.path.join(session_root, name)
            if not os.path.isdir(session_dir):
                continue
            try:
                if cutoff is not None:
                    newest_mtime = _folder_newest_mtime(session_dir)
                    if newest_mtime >= cutoff:
                        continue
                kind = _session_cleanup_kind(session_dir)
                if kind == "completed":
                    if mode == "incomplete":
                        preserved_completed += 1
                        continue
                elif kind == "completed_missing_html":
                    missing_completed_html += 1
                    if mode == "completed":
                        continue
                elif mode == "completed":
                    continue
                candidates += 1
                size = _folder_size(session_dir)
                if dry_run:
                    freed_bytes += size
                    continue
                shutil.rmtree(session_dir)
                removed += 1
                freed_bytes += size
                deleted_paths.append(session_dir)
            except Exception:
                errors += 1
    except Exception:
        pass
    if removed > 0 and not dry_run:
        invalidate_session_storage_cache()
    return {
        "removed": removed,
        "freed_bytes": freed_bytes,
        "errors": errors,
        "candidates": candidates,
        "preserved_completed": preserved_completed,
        "missing_completed_html": missing_completed_html,
        "deleted_paths": deleted_paths,
    }


def cleanup_completed_sessions(
    max_age_days: int = SESSION_CLEANUP_MAX_AGE_DAYS, *, dry_run: bool = False
) -> dict:
    return cleanup_orphan_sessions(
        max_age_days,
        mode="completed",
        dry_run=dry_run,
    )
