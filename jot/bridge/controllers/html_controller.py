"""
HTML preview and fallback generation IPC bridge controller.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from jot.bridge.bridge_utils import (
    _normalize_revision_failed_blocks,
    _path_under_root,
    bridge_error,
    bridge_ok,
)
from jot.core.session_store import save_session
from jot.core.shared import _atomic_write_json, _load_json
from jot.services import config_service
from jot.utils import file_ops
from jot.utils.logging_utils import redact_secrets

if TYPE_CHECKING:
    import logging
    import threading


class HtmlControllerMixin:
    """Mixin providing HTML preview, save, and fallback generation methods."""

    if TYPE_CHECKING:
        _logger: logging.Logger
        _resolved_cache_lock: threading.Lock
        _resolved_path_cache: dict[str, str]
        _html_shell_cache: dict[str, tuple[str, str]]
        _sessions_cache_lock: threading.Lock
        _sessions_cache: dict | None
        _sessions_cache_gen: int

        def _get_session_root(self) -> str: ...

    def read_html_content(self, path: str) -> dict:
        """Legge ed estrae il contenuto di un file HTML per l'anteprima."""
        if not isinstance(path, str) or not path.lower().endswith(".html"):
            return bridge_error("Path non valido: deve essere un file .html.")
        real_path = os.path.realpath(path)
        allowed_roots = [
            os.path.realpath(
                config_service.get_desktop_dir()
            ),  # Desktop / OneDrive Desktop
            os.path.realpath(self._get_session_root()),  # Session storage
        ]
        path_is_allowed = any(
            _path_under_root(real_path, root) for root in allowed_roots
        )
        if not path_is_allowed and os.path.isfile(real_path):
            return bridge_error("Accesso negato: path fuori dai percorsi consentiti.")
        requested_real_path = real_path
        if not path_is_allowed or not os.path.isfile(real_path):
            _basename = os.path.basename(real_path)
            with self._resolved_cache_lock:
                cached_resolution = self._resolved_path_cache.get(requested_real_path)
                if cached_resolution and os.path.isfile(cached_resolution):
                    fallback = cached_resolution
                else:
                    fallback = self._find_html_in_session_dirs(_basename)
                    if not fallback:
                        fallback = self._rebuild_html_from_session(_basename)
                if fallback and os.path.isfile(fallback):
                    real_path = fallback
                    if not any(
                        _path_under_root(real_path, root) for root in allowed_roots
                    ):
                        return bridge_error(
                            "Accesso negato: path fuori dai percorsi consentiti."
                        )
                    self._resolved_path_cache[requested_real_path] = real_path
                else:
                    return bridge_error("File non trovato.")
        else:
            with self._resolved_cache_lock:
                self._resolved_path_cache[requested_real_path] = real_path
        try:
            content = file_ops.read_html_content(real_path)
            shell = file_ops.extract_html_shell(content)
            if shell is not None:
                with self._resolved_cache_lock:
                    self._html_shell_cache[real_path] = shell
            return bridge_ok(content=content)
        except Exception as e:
            return bridge_error(e)

    def _find_html_in_session_dirs(self, basename: str) -> str | None:
        """Cerca un file HTML con lo stesso nome nelle cartelle di sessione."""
        session_root = self._get_session_root()
        if not os.path.isdir(session_root):
            return None
        candidates: list[tuple[float, str]] = []
        try:
            for entry in os.scandir(session_root):
                if not entry.is_dir():
                    continue
                candidate = os.path.join(entry.path, basename)
                try:
                    st = os.stat(candidate)
                    candidates.append((st.st_mtime, os.path.realpath(candidate)))
                except (FileNotFoundError, OSError):
                    continue
        except Exception:
            return None
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    def _rebuild_html_from_session(self, html_basename: str) -> str | None:
        """Ricostruisce l'HTML dai blocchi .md della sessione come ultimo fallback."""
        from jot.pipeline.pipeline_session import read_text_file
        from jot.services.config_service import safe_output_basename
        from jot.services.export_service import export_final_html_document

        session_root = self._get_session_root()
        if not os.path.isdir(session_root):
            return None
        try:
            candidates: list[tuple[float, str, dict]] = []
            for entry in os.scandir(session_root):
                if not entry.is_dir():
                    continue
                session_path = os.path.join(entry.path, "session.json")
                if not os.path.isfile(session_path):
                    continue
                try:
                    with open(session_path, encoding="utf-8") as fh:
                        session_data = json.load(fh)
                    existing_html = session_data.get("outputs", {}).get("html", "")
                    if not existing_html:
                        continue
                    if os.path.basename(str(existing_html)) != html_basename:
                        continue
                    phase2_revised_dir = os.path.join(entry.path, "phase2_revised")
                    if not os.path.isdir(phase2_revised_dir):
                        continue
                    if not session_data.get("input", {}).get("path", ""):
                        continue
                    if session_data.get("stage") != "done":
                        continue
                    mtime = os.path.getmtime(session_path)
                    candidates.append((mtime, entry.path, session_data))
                except Exception:
                    continue
            candidates.sort(key=lambda c: c[0], reverse=True)
            for _mtime, entry_path, session_data in candidates:
                session_path = os.path.join(entry_path, "session.json")
                phase2_revised_dir = os.path.join(entry_path, "phase2_revised")
                input_path = session_data["input"]["path"]
                try:
                    _, html_path = export_final_html_document(
                        input_path=input_path,
                        phase2_revised_dir=phase2_revised_dir,
                        fallback_body="",
                        read_text=read_text_file,
                        output_dir=entry_path,
                        fallback_output_dir=entry_path,
                        safe_output_basename=safe_output_basename,
                        revision_failed_blocks=_normalize_revision_failed_blocks(
                            session_data.get("revision_failed_blocks")
                        ),
                    )
                    if not os.path.isfile(html_path):
                        continue
                    if os.path.basename(html_path) != html_basename:
                        canonical_path = os.path.join(
                            os.path.dirname(html_path), html_basename
                        )
                        os.replace(html_path, canonical_path)
                        html_path = canonical_path
                    try:
                        session_data["outputs"]["html"] = html_path
                        _atomic_write_json(session_path, session_data)
                    except Exception:
                        pass
                    return os.path.realpath(html_path)
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def _existing_html_for_session(self, session: dict, session_dir: str) -> str | None:
        """Return an existing HTML path for a session without rebuilding it."""
        html_path = str(session.get("outputs", {}).get("html", "") or "")
        if html_path and os.path.isfile(html_path):
            return os.path.realpath(html_path)

        try:
            if not os.path.isdir(session_dir):
                return None
            html_basename = os.path.basename(html_path) if html_path else ""
            if html_basename:
                session_copy = os.path.join(session_dir, html_basename)
                if os.path.isfile(session_copy):
                    return os.path.realpath(session_copy)
            for entry in os.scandir(session_dir):
                if entry.is_file() and entry.name.lower().endswith(".html"):
                    return os.path.realpath(entry.path)
        except Exception:
            return None
        return None

    def _mark_session_user_edited_for_html(self, real_path: str) -> None:
        try:
            session_path = os.path.join(os.path.dirname(real_path), "session.json")
            if not os.path.isfile(session_path):
                return
            session = _load_json(session_path)
            if not isinstance(session, dict) or bool(session.get("user_edited", False)):
                return
            session["user_edited"] = True
            save_session(session_path, session)
            with self._sessions_cache_lock:
                self._sessions_cache = None
                self._sessions_cache_gen += 1
        except Exception as exc:
            self._logger.debug(
                "Impossibile marcare sessione come modificata dall'utente: %s",
                exc,
            )

    def save_html_content(
        self, path: str, content: str, generation: int | None = None
    ) -> dict:
        """Aggiorna solo il contenuto del <body>, preservando head, stile e CSP dell'export originale."""
        if not isinstance(path, str) or not path.lower().endswith(".html"):
            return bridge_error("Path non valido: deve essere un file .html.")
        real_path = os.path.realpath(path)
        original_real_path = real_path
        allowed_roots = [
            os.path.realpath(
                config_service.get_desktop_dir()
            ),  # Desktop / OneDrive Desktop
            os.path.realpath(self._get_session_root()),  # Session storage
        ]
        path_is_allowed = any(
            _path_under_root(real_path, root) for root in allowed_roots
        )
        if not path_is_allowed and os.path.isfile(real_path):
            return bridge_error("Accesso negato: path fuori dai percorsi consentiti.")
        if not path_is_allowed or not os.path.isfile(real_path):
            _basename = os.path.basename(real_path)
            with self._resolved_cache_lock:
                cached_resolution = self._resolved_path_cache.get(original_real_path)
                if cached_resolution and os.path.isfile(cached_resolution):
                    fallback = cached_resolution
                else:
                    fallback = self._find_html_in_session_dirs(_basename)
                    if not fallback:
                        fallback = self._rebuild_html_from_session(_basename)
                if fallback and os.path.isfile(fallback):
                    real_path = fallback
                    if not any(
                        _path_under_root(real_path, root) for root in allowed_roots
                    ):
                        return bridge_error(
                            "Accesso negato: path fuori dai percorsi consentiti."
                        )
                    self._resolved_path_cache[original_real_path] = real_path
                else:
                    return bridge_error("File non trovato.")
        try:
            with self._resolved_cache_lock:
                shell = self._html_shell_cache.get(
                    real_path
                ) or self._html_shell_cache.get(original_real_path)
            gen = int(generation) if generation is not None else None
            saved = file_ops.save_html_body_content(
                real_path, content, shell=shell, generation=gen
            )
            if saved:
                self._mark_session_user_edited_for_html(real_path)
                return bridge_ok(saved=True)
            return bridge_error(
                "Salvataggio ignorato perché più vecchio dell'ultima versione.",
                saved=False,
            )
        except Exception as e:
            return bridge_error(e)
