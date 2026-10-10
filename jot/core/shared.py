"""
Shared utilities/constants façade for jot.

This module re-exports constants, session management, file operations, and
model registry definitions to maintain 100% backward compatibility for external
scripts, existing tests, and legacy shims.

Actual implementations reside in:
- jot.utils.file_ops (atomic writes, fsync, safe_mkdir, load_json)
- jot.core.session_store (session root, fingerprinting, storage metrics, cleanup)
- jot.core.model_registry (default model constants)
"""

from __future__ import annotations

import os
import platform
import sys

from jot.core.model_registry import (
    DEFAULT_FALLBACK_MODELS,
    DEFAULT_MODEL,
)
from jot.core.session_store import (
    _LEGACY_SESSION_ROOT,
    _MAX_SESSION_CACHE_SIZE,
    _STORAGE_INFO_TTL,
    _TEMP_CHUNK_AUDIO_EXTS,
    PRECONVERTED_AUDIO_FINAL,
    PRECONVERTED_AUDIO_PARTIAL,
    SESSION_CLEANUP_MAX_AGE_DAYS,
    SESSION_ROOT,
    SESSION_SCHEMA_VERSION,
    SessionCollisionError,
    SessionPaths,
    _cleanup_legacy_temp_chunks,
    _cleanup_session_temp_chunks,
    _completed_html_output_exists,
    _compute_session_storage_info,
    _file_fingerprint,
    _file_tail_hash,
    _folder_newest_mtime,
    _folder_size,
    _get_default_session_root,
    _is_old_enough,
    _now_iso,
    _partial_file_hash,
    _resolve_session_html_path,
    _session_cleanup_kind,
    _session_completed_html_exists,
    _session_dir_for_file,
    _session_id_cache,
    _session_id_for_file,
    _storage_info_cache,
    _storage_info_cache_time,
    _storage_info_executor,
    _storage_info_future,
    _storage_info_lock,
    _update_session,
    cleanup_completed_sessions,
    cleanup_orphan_sessions,
    cleanup_orphan_temp_chunks,
    clone_session_settings,
    ensure_session_dirs,
    get_session_root,
    get_session_storage_info,
    invalidate_session_storage_cache,
    load_session,
    mark_html_exported,
    migrate_legacy_session_root,
    migrate_session,
    new_session,
    reset_session_dirs,
    resolve_session_paths,
    save_session,
    set_session_root,
)
from jot.utils.file_ops import (
    _atomic_write_json,
    _atomic_write_text,
    _fsync_dir,
    _load_json,
    _safe_mkdir,
)

__all__ = [
    "DEFAULT_FALLBACK_MODELS",
    "DEFAULT_MODEL",
    "PRECONVERTED_AUDIO_FINAL",
    "PRECONVERTED_AUDIO_PARTIAL",
    "SESSION_CLEANUP_MAX_AGE_DAYS",
    "SESSION_ROOT",
    "SESSION_SCHEMA_VERSION",
    "_LEGACY_SESSION_ROOT",
    "SessionCollisionError",
    "SessionPaths",
    "_atomic_write_json",
    "_atomic_write_text",
    "_file_fingerprint",
    "_file_tail_hash",
    "_fsync_dir",
    "_load_json",
    "_now_iso",
    "_partial_file_hash",
    "_safe_mkdir",
    "_session_dir_for_file",
    "_session_id_for_file",
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


def __getattr__(name: str):
    """Dynamic fallback to session_store, file_ops, or model_registry."""
    from jot.core import model_registry, session_store
    from jot.utils import file_ops

    if hasattr(session_store, name):
        return getattr(session_store, name)
    if hasattr(file_ops, name):
        return getattr(file_ops, name)
    if hasattr(model_registry, name):
        return getattr(model_registry, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
