"""
Shared utilities for the jot PyWebView bridge controllers.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Any

from jot.utils.logging_utils import redact_secrets

if TYPE_CHECKING:
    from jot.pipeline.pipeline_adapter import PipelineAdapter


def bridge_ok(**kwargs: Any) -> dict[str, Any]:
    """Construct a standardized successful IPC bridge response."""
    return {"ok": True, **kwargs}


def bridge_error(error: Exception | str, **kwargs: Any) -> dict[str, Any]:
    """Construct a standardized failed IPC bridge response with secrets redacted."""
    return {"ok": False, "error": redact_secrets(error), **kwargs}


def _path_under_root(path: str, root: str) -> bool:
    """Return True if *path* equals or is nested under *root*.

    Uses os.path.normcase so the comparison is case-insensitive on Windows
    (where realpath does not canonicalise drive/folder casing).
    Both arguments must already be fully resolved (os.path.realpath) by the
    caller.
    """
    nc_path = os.path.normcase(path)
    nc_root = os.path.normcase(root)
    if nc_path == nc_root:
        return True
    if not nc_root.endswith(os.sep):
        nc_root += os.sep
    return nc_path.startswith(nc_root)


def _safe_relpath(path: str, start: str) -> str | None:
    try:
        return os.path.relpath(path, start)
    except (OSError, ValueError):
        return None


def _candidate_from_relative(base_dir: str, rel_path: object) -> str | None:
    rel = str(rel_path or "").strip()
    if not rel or os.path.isabs(rel):
        return None
    return os.path.realpath(os.path.join(base_dir, rel))


def _normalize_revision_failed_blocks(value: object) -> list[int]:
    if not isinstance(value, list | tuple | set):
        return []
    return [int(idx) for idx in value if str(idx).strip().isdigit()]


class _RetryRuntime:
    def __init__(self, adapter: PipelineAdapter, cancel_event: threading.Event):
        self._adapter = adapter
        self._cancel_event = cancel_event
        self.effective_api_key: str | None = None

    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def phase(self, text: str) -> None:
        try:
            self._adapter.aggiorna_fase(text)
        except Exception:
            pass

    def progress(self, value: float) -> None:
        try:
            self._adapter.aggiorna_progresso(value)
        except Exception:
            pass

    def set_work_totals(
        self,
        chunks_total: int | None = None,
        macro_total: int | None = None,
        **_kwargs,
    ) -> None:
        try:
            self._adapter.set_work_totals(
                chunks_total=chunks_total, macro_total=macro_total
            )
        except Exception:
            pass

    def update_work_done(
        self,
        kind: str = "macro",
        done: int = 0,
        total: int | None = None,
        **_kwargs,
    ) -> None:
        try:
            self._adapter.update_work_done(kind, done, total=total)
        except Exception:
            pass

    def register_step_time(self, *_args, **_kwargs) -> None:
        return None

    def set_effective_api_key(self, api_key: str | None) -> None:
        self.effective_api_key = str(api_key or "").strip() or None

    def ask_new_api_key(self, callback) -> bool:
        try:
            self._adapter.ask_new_api_key(callback)
            return True
        except Exception:
            return False

    def dismiss_new_api_key_prompt(self) -> None:
        try:
            self._adapter.dismiss_new_api_key_prompt()
        except Exception:
            pass


def _retry_zero_retried_response(
    *,
    retried_blocks: list,
    remaining: list,
    cancelled: bool,
    quota_exhausted: bool,
    session_dir: str,
    html_path: str,
) -> dict | None:
    if retried_blocks:
        return None
    if cancelled:
        error = "Operazione annullata."
    elif quota_exhausted:
        error = "Quota giornaliera esaurita: riprova domani."
    elif remaining:
        error = "Nessun blocco recuperato. Riprova piu tardi."
    else:
        return {
            "ok": True,
            "remaining_failed_blocks": remaining,
            "retried_blocks": retried_blocks,
            "html_path": html_path,
            "session_dir": session_dir,
        }
    return {
        "ok": False,
        "error": error,
        "remaining_failed_blocks": remaining,
        "retried_blocks": retried_blocks,
        "session_dir": session_dir,
        "cancelled": cancelled,
        "quota_exhausted": quota_exhausted,
    }


def _retry_would_overwrite_user_html(session: dict, existing_html: str | None) -> bool:
    user_edited = session.get("user_edited")
    return user_edited is True or (user_edited is None and existing_html is not None)


def _retry_no_failed_blocks_response(
    session: dict, failed_blocks: object, session_dir: str
) -> dict | None:
    if isinstance(failed_blocks, list) and failed_blocks:
        return None
    return {
        "ok": True,
        "retried_blocks": [],
        "remaining_failed_blocks": [],
        "html_path": session.get("outputs", {}).get("html", ""),
        "session_dir": session_dir,
    }


_ALLOWED_URL_PREFIXES: tuple[str, ...] = (
    "https://github.com/",
    "https://aistudio.google.com/",
)
