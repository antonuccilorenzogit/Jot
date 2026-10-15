"""
Pipeline execution and cancellation IPC bridge controller.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from jot.bridge.bridge_types import (
    BridgeFileItem,
    FileDonePayload,
    FileFailedPayload,
    LowDiskWarningPayload,
    ProcessDonePayload,
    SetCurrentFilePayload,
)
from jot.bridge.bridge_utils import (
    _normalize_revision_failed_blocks,
    _path_under_root,
    _retry_no_failed_blocks_response,
    _retry_would_overwrite_user_html,
    _retry_zero_retried_response,
    _RetryRuntime,
    _safe_relpath,
    bridge_error,
    bridge_ok,
)
from jot.core.session_store import (
    _compute_session_storage_info,
    _folder_size,
    _session_dir_for_file,
    cleanup_orphan_temp_chunks,
    load_session,
    mark_html_exported,
    resolve_session_paths,
    save_session,
)
from jot.core.shared import (
    DEFAULT_MODEL,
    _atomic_write_json,
    _load_json,
    get_session_root,
    invalidate_session_storage_cache,
)
from jot.pipeline.pipeline_adapter import PipelineAdapter
from jot.pipeline.pipeline_settings import (
    build_default_pipeline_settings,
    load_and_sanitize_settings,
)
from jot.services import network_service
from jot.services.config_service import load_config, save_config
from jot.utils.file_ops import evict_html_paths_under
from jot.utils.logging_utils import redact_secrets

if TYPE_CHECKING:
    from collections import OrderedDict

    import webview


def _build_failure_payload(
    idx: int,
    file_info: BridgeFileItem,
    adapter: PipelineAdapter,
    last_run_status: str,
) -> tuple[FileFailedPayload, bool]:
    error_detail = getattr(adapter, "last_run_error_detail", None) or ""
    error_message = (
        redact_secrets(adapter.last_run_error) or "Elaborazione non completata."
    )
    error_detail = redact_secrets(error_detail)
    ff_payload: FileFailedPayload = {
        "index": idx,
        "id": file_info.get("id", ""),
        "error": error_message,
    }
    if error_detail:
        ff_payload["error_detail"] = error_detail

    is_paused = last_run_status == "paused" or "circuit_breaker" in str(error_message)
    if is_paused:
        ff_payload["retryable"] = True
        ff_payload["retry_reason"] = "circuit_breaker_paused"
        retry_state = getattr(adapter, "last_retry_state", None) or {}
        rec_iso = str(retry_state.get("recommended_retry_at") or "").strip()
        if not rec_iso:
            rec_iso = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
        ff_payload["recommended_retry_at"] = rec_iso
    return ff_payload, is_paused


def _handle_file_completed(
    idx: int,
    file_info: BridgeFileItem,
    adapter: PipelineAdapter,
    last_run_status: str,
) -> tuple[str, bool]:
    if adapter.last_output_html and os.path.exists(adapter.last_output_html):
        revision_failed_blocks = list(adapter.last_revision_failed_blocks or [])
        completion_status = (
            "completed_with_warnings"
            if last_run_status == "completed_with_warnings" or revision_failed_blocks
            else "completed"
        )
        fd_payload: FileDonePayload = {
            "index": idx,
            "id": file_info.get("id", ""),
            "output_html": adapter.last_output_html,
            "output_dir": adapter.last_output_dir or "",
            "completion_status": completion_status,
            "revision_failed_blocks": revision_failed_blocks,
            "primary_model": adapter.last_primary_model or "",
            "effective_model": adapter.last_effective_model or "",
        }
        adapter.emit("fileDone", fd_payload, batched=False)
        return completion_status, True

    ff_payload2: FileFailedPayload = {
        "index": idx,
        "id": file_info.get("id", ""),
        "error": "Output HTML non generato.",
    }
    adapter.emit("fileFailed", ff_payload2, batched=False)
    return "failed", False


def _handle_file_failure(
    idx: int,
    file_info: BridgeFileItem,
    adapter: PipelineAdapter,
    last_run_status: str,
) -> tuple[int, int, bool, bool]:
    payload, is_paused = _build_failure_payload(
        idx, file_info, adapter, last_run_status
    )
    adapter.emit("fileFailed", payload, batched=False)
    quota_exhausted = payload["error"] in {
        "quota_daily_limit_phase1",
        "quota_daily_limit_phase2",
    }
    paused_delta = int(is_paused)
    failed_delta = 1 - paused_delta
    return paused_delta, failed_delta, quota_exhausted, is_paused or quota_exhausted


def _reset_governor_if_needed(files: list[BridgeFileItem], force_retry: bool) -> None:
    if force_retry or any(
        bool(f.get("force_retry")) for f in files if isinstance(f, dict)
    ):
        try:
            from jot.services.generation_service import (
                reset_global_governor,
            )

            reset_global_governor()
        except Exception:
            pass


def _clear_retry_state_if_forced(file_info: BridgeFileItem, force_retry: bool) -> None:
    if not (force_retry or bool(file_info.get("force_retry"))):
        return
    file_path = str(file_info.get("path", "") or "")
    if not file_path:
        return
    try:
        paths = session_paths_for_item(file_info)
        if not os.path.exists(paths.session_path):
            return
        session = load_session(paths.session_path)
        if not isinstance(session, dict):
            return
        session["retry_state"] = None
        if session.get("last_error") == "circuit_breaker_paused":
            session["last_error"] = None
            session["last_error_detail"] = None
        save_session(paths.session_path, session)
    except Exception:
        pass


def lesson_sources_for_item(file_info: BridgeFileItem):
    from jot.services.lesson_context import LessonSources

    return LessonSources(
        slides_path=file_info.get("slides_path"),
        book_path=file_info.get("book_path"),
        book_pages=str(file_info.get("book_pages") or ""),
        title=file_info.get("title"),
        course=file_info.get("course"),
        audio_parts=list(file_info.get("audio_parts") or []),
        lesson_date=file_info.get("lesson_date"),
    )


def session_paths_for_item(file_info: BridgeFileItem):
    """Session paths of an audio queue item (with or without slides/book)."""
    from jot.services.lesson_context import lesson_session_dir

    file_path = str(file_info.get("path", "") or "")
    hint = lesson_session_dir(file_path, lesson_sources_for_item(file_info))
    return resolve_session_paths(file_path, session_dir_hint=hint)


def _resolve_start_api_key(api_key: str) -> str | None:
    key = str(api_key or "").strip()
    if key:
        return key
    cfg = load_config()
    return str(cfg.get("api_key") or "").strip() or None


class PipelineControllerMixin:
    """Mixin providing pipeline execution, cancellation, retry, and low disk IPC methods."""

    _retry_global_lock: ClassVar[threading.Lock] = threading.Lock()
    _retry_locks: ClassVar[dict[str, threading.Lock]] = {}
    _retry_locks_mutex: ClassVar[threading.Lock] = threading.Lock()

    if TYPE_CHECKING:
        _adapter: PipelineAdapter
        _processing_thread: threading.Thread | None
        _cancel_event: threading.Event
        _pipeline_lifecycle_lock: threading.Lock
        _retry_active_count: int
        _active_retry_cancel_event: threading.Event | None
        _force_close: bool
        _window: webview.Window | None
        _move_state: dict
        _move_lock: threading.Lock
        _sessions_cache: dict | None
        _sessions_cache_gen: int
        _sessions_cache_lock: threading.Lock
        _text_cache: OrderedDict[str, tuple[float, str]]
        _text_cache_lock: threading.Lock

        def _get_session_root(self) -> str: ...
        def _push_console(self, msg: str) -> None: ...
        def _existing_html_for_session(
            self, session: dict, session_dir: str
        ) -> str | None: ...
        def _validate_processing_files(self, files: list) -> str | None: ...

    def _resolve_retry_session(self, session_dir: str) -> tuple[str, str]:
        session_root = os.path.realpath(self._get_session_root())
        abs_dir = os.path.realpath(str(session_dir or ""))
        if not _path_under_root(abs_dir, session_root):
            raise ValueError("Sessione non valida.")
        session_path = os.path.join(abs_dir, "session.json")
        if not os.path.isfile(session_path):
            raise FileNotFoundError("Sessione non trovata.")
        return abs_dir, session_path

    def _push_retry_completion_status(
        self, remaining: list, cancelled: bool, quota_exhausted: bool
    ) -> None:
        if not remaining:
            self._push_console(
                "REVISIONE COMPLETATA CON SUCCESSO! ✅ Tutti i blocchi sono stati revisionati."
            )
        else:
            if cancelled:
                self._push_console(
                    "REVISIONE INTERROTTA! ⚠ Operazione annullata dall'utente."
                )
            elif quota_exhausted:
                self._push_console(
                    "REVISIONE INTERROTTA! ⚠ Quota giornaliera API esaurita. Riprova domani."
                )
            else:
                self._push_console(
                    f"REVISIONE COMPLETATA CON AVVISI! ⚠ Rimangono {len(remaining)} blocchi non revisionati."
                )

    def retry_failed_revision_blocks(self, session_dir: str) -> dict:
        """Retry only macro blocks that were included unrevised in a done session."""
        if self._adapter.is_running:
            return bridge_error("Elaborazione in corso: riprova al termine.")
        retry_lock: threading.Lock | None = None
        retry_global_lock_acquired = False
        retry_lock_acquired = False
        _retry_count_incremented = False
        try:
            from jot.services import revision_service

            abs_dir, session_path = self._resolve_retry_session(session_dir)

            retry_global_lock_acquired = self._retry_global_lock.acquire(blocking=False)
            if not retry_global_lock_acquired:
                return bridge_error("Retry gia' in corso: riprova al termine.")

            lock_key = os.path.normcase(abs_dir)
            with self._retry_locks_mutex:
                retry_lock = self._retry_locks.setdefault(lock_key, threading.Lock())
            retry_lock_acquired = retry_lock.acquire(blocking=False)
            if not retry_lock_acquired:
                return bridge_error("Retry gia' in corso per questa sessione.")
            with self._pipeline_lifecycle_lock:
                if self._adapter.is_running:
                    return bridge_error("Elaborazione in corso: riprova al termine.")
                self._retry_active_count += 1
                self._adapter.is_running = True
            _retry_count_incremented = True

            session = _load_json(session_path)
            if not isinstance(session, dict) or session.get("stage") != "done":
                return bridge_error("Sessione non completata.")
            if _retry_would_overwrite_user_html(
                session, self._existing_html_for_session(session, abs_dir)
            ):
                return bridge_error(
                    "HTML modificato dall'utente: retry annullato per evitare sovrascritture.",
                    conflict=True,
                    session_dir=abs_dir,
                )
            failed_blocks = session.get("revision_failed_blocks", [])
            no_failed_blocks = _retry_no_failed_blocks_response(
                session, failed_blocks, abs_dir
            )
            if no_failed_blocks is not None:
                return no_failed_blocks

            cfg = load_config()
            api_key = str(cfg.get("api_key") or "").strip()
            if not api_key:
                return bridge_error("API key mancante: aggiungila nelle impostazioni.")

            if not network_service.check_connectivity():
                return bridge_error(
                    "Nessuna connessione a Internet rilevata. Verifica la tua connessione di rete."
                )

            retry_cancel_event = threading.Event()
            with self._pipeline_lifecycle_lock:
                self._active_retry_cancel_event = retry_cancel_event
            runtime = _RetryRuntime(self._adapter, retry_cancel_event)

            result = revision_service.execute_failed_blocks_retry_workflow(
                session=session,
                session_path=session_path,
                session_dir=abs_dir,
                api_key=api_key,
                runtime=runtime,
                retry_cancel_event=retry_cancel_event,
                on_push_completion_status=self._push_retry_completion_status,
            )

            html_path = result.get("html_path")
            if html_path:
                with self._text_cache_lock:
                    self._text_cache.pop(html_path, None)
            with self._sessions_cache_lock:
                self._sessions_cache = None
                self._sessions_cache_gen += 1

            return result
        except Exception as e:
            return bridge_error(e)
        finally:
            with self._pipeline_lifecycle_lock:
                self._active_retry_cancel_event = None
                if _retry_count_incremented:
                    self._retry_active_count -= 1
                    self._adapter.is_running = False
            if retry_lock is not None and retry_lock_acquired:
                retry_lock.release()
            if retry_global_lock_acquired:
                self._retry_global_lock.release()

    def _start_processing_guard(self, mark_running: bool = False) -> dict | None:
        with self._pipeline_lifecycle_lock:
            if self._adapter.is_running:
                return bridge_error("Elaborazione già in corso")
            if self._retry_active_count > 0:
                return bridge_error("Retry in corso: riprova al termine.")
            if mark_running:
                self._adapter.is_running = True
        return None

    def _low_disk_warning_for_files(
        self, files: list[BridgeFileItem]
    ) -> LowDiskWarningPayload | None:
        from jot.pipeline.pipeline_session import (
            estimate_disk_space,
            normalize_stage,
        )

        try:
            cfg = load_config()
            defaults = build_default_pipeline_settings(cfg)
            default_session = {"settings": defaults}
            default_settings, _changed = load_and_sanitize_settings(default_session)
        except Exception:
            return None

        worst: LowDiskWarningPayload | None = None
        for file_info in files:
            file_path = str(file_info.get("path", "") or "")
            if not file_path or file_info.get("kind") == "notes":
                continue
            try:
                duration = float(file_info.get("duration", 0) or 0)
            except Exception:
                duration = 0.0
            if duration <= 0 and os.path.exists(file_path):
                try:
                    from jot.services.audio_service import (
                        probe_media_duration,
                    )

                    probed_duration, _reason = probe_media_duration(file_path)
                    duration = float(probed_duration or 0)
                except Exception:
                    duration = 0.0
            if duration <= 0:
                continue
            try:
                paths = session_paths_for_item(file_info)
            except Exception:
                continue
            stage = "phase1"
            next_start_sec = 0
            settings = default_settings
            try:
                if os.path.exists(paths.session_path):
                    saved = _load_json(paths.session_path)
                    if isinstance(saved, dict):
                        settings, _changed = load_and_sanitize_settings(saved)
                        stage = normalize_stage(saved)
                        phase1 = saved.get("phase1", {})
                        if isinstance(phase1, dict):
                            next_start_sec = int(phase1.get("next_start_sec", 0) or 0)
            except Exception:
                stage = "phase1"
                next_start_sec = 0
                settings = default_settings
            for estimate in estimate_disk_space(
                paths.session_dir,
                duration,
                settings,
                stage,
                next_start_sec,
            ):
                if not estimate.is_clearly_insufficient:
                    continue
                payload: LowDiskWarningPayload = {
                    "needed_bytes": int(estimate.needed_bytes),
                    "free_bytes": int(estimate.free_bytes),
                    "location": estimate.location,
                    "kind": estimate.kind,
                    "file_name": str(
                        file_info.get("name", "") or os.path.basename(file_path)
                    ),
                }
                if worst is None:
                    worst = payload
                    continue
                worst_deficit = int(worst["needed_bytes"]) - int(worst["free_bytes"])
                deficit = int(payload["needed_bytes"]) - int(payload["free_bytes"])
                if deficit > worst_deficit:
                    worst = payload
        return worst

    def _persist_processing_config(
        self,
        api_key: str,
        preferred_model: str | None,
        fallback_models: list[str] | None,
    ) -> None:
        try:
            save_config(
                api_key,
                preferred_model=preferred_model or None,
                fallback_models=fallback_models
                if isinstance(fallback_models, list)
                else None,
            )
        except OSError as e:
            self._push_console(
                f"[!] Impossibile salvare le impostazioni di configurazione: {e}"
            )
        except Exception as e:
            self._push_console(
                f"[!] Errore imprevisto durante il salvataggio della configurazione: {e}"
            )

    def _low_disk_start_response(
        self, files: list[BridgeFileItem], override_low_disk: bool
    ) -> dict | None:
        if override_low_disk:
            return None
        low_disk_warning = self._low_disk_warning_for_files(files)
        if low_disk_warning is None:
            return None
        return bridge_error(
            "Spazio libero insufficiente.", low_disk_warning=low_disk_warning
        )

    def _prepare_start_processing(
        self,
        files: list[BridgeFileItem],
        api_key: str,
        preferred_model: str | None,
        fallback_models: list[str] | None,
        override_low_disk: bool,
    ) -> dict | None:
        guard_error = self._start_processing_guard()
        if guard_error is not None:
            return guard_error
        validation_error = self._validate_processing_files(files)
        if validation_error is not None:
            return bridge_error(validation_error)

        if not network_service.check_connectivity():
            return bridge_error(
                "Nessuna connessione a Internet rilevata. Verifica la tua connessione di rete prima di avviare la sbobinatura."
            )
        self._persist_processing_config(api_key, preferred_model, fallback_models)
        low_disk_response = self._low_disk_start_response(files, override_low_disk)
        if low_disk_response is not None:
            return low_disk_response
        return self._start_processing_guard(mark_running=True)

    def start_processing(
        self,
        files: list[BridgeFileItem],
        api_key: str,
        resume_session: bool = True,
        preferred_model: str | None = None,
        fallback_models: list[str] | None = None,
        override_low_disk: bool = False,
        force_retry: bool = False,
    ) -> dict:
        """Start the pipeline in a background thread."""
        resolved_key = _resolve_start_api_key(api_key)
        if not files or not resolved_key:
            return bridge_error("File o API key mancanti")
        api_key = resolved_key
        start_error = self._prepare_start_processing(
            files,
            api_key,
            preferred_model,
            fallback_models,
            override_low_disk,
        )
        if start_error is not None:
            return start_error

        _reset_governor_if_needed(files, force_retry)

        try:
            removed = cleanup_orphan_temp_chunks()
            if removed > 0:
                self._push_console(f"[*] Pulizia: rimossi {removed} file temporanei.")
        except Exception:
            pass

        self._cancel_event.clear()
        self._adapter.file_temporanei = []
        self._adapter._run_started_monotonic = time.monotonic()
        self._adapter._step_times = {}
        self._adapter.reset_run_state(api_key)

        def _run():
            from jot.pipeline.pipeline import esegui_sbobinatura

            active_api_key = api_key
            completed_count = 0
            completed_with_warnings_count = 0
            failed_count = 0
            paused_count = 0
            current_index: int | None = None
            current_file_id = ""
            quota_exhausted = False
            try:
                for idx, file_info in enumerate(files):
                    if self._cancel_event.is_set():
                        break
                    try:
                        current_index = idx
                        current_file_id = str(file_info.get("id", "") or "")
                        self._adapter.reset_run_state(active_api_key)
                        file_path = file_info.get("path", "")
                        if not file_path or not os.path.exists(file_path):
                            self._push_console(f"[!] File non trovato: {file_path}")
                            ff_payload: FileFailedPayload = {
                                "index": idx,
                                "id": file_info.get("id", ""),
                                "error": "File non trovato.",
                            }
                            self._adapter.emit("fileFailed", ff_payload, batched=False)
                            failed_count += 1
                            current_index = None
                            current_file_id = ""
                            continue

                        self._push_console(f"\n{'=' * 50}")
                        self._push_console(
                            f"  File {idx + 1}/{len(files)}: {os.path.basename(file_path)}"
                        )
                        self._push_console(f"{'=' * 50}")
                        _clear_retry_state_if_forced(file_info, force_retry)
                        current_payload: SetCurrentFilePayload = {
                            "index": idx,
                            "id": file_info.get("id", ""),
                            "total": len(files),
                        }
                        self._adapter.emit(
                            "setCurrentFile", current_payload, batched=False
                        )
                        file_resume_override = file_info.get("resume_session")
                        file_resume_session = (
                            bool(file_resume_override)
                            if file_resume_override is not None
                            else resume_session
                        )
                        file_allow_completed_destroy = bool(
                            file_info.get("allow_completed_destroy", False)
                        )

                        if file_info.get("kind") == "notes":
                            from jot.pipeline.notes_pipeline import (
                                esegui_appunti,
                            )

                            esegui_appunti(
                                file_path,
                                active_api_key,
                                self._adapter,
                                book_path=file_info.get("book_path") or None,
                                book_pages=str(file_info.get("book_pages") or ""),
                                slides_per_chunk=file_info.get("slides_per_chunk"),
                                book_mode=file_info.get("book_mode"),
                                title=file_info.get("title"),
                                course=file_info.get("course"),
                                lesson_date=file_info.get("lesson_date"),
                                resume_session=file_resume_session,
                                allow_completed_destroy=file_allow_completed_destroy,
                            )
                        else:
                            esegui_sbobinatura(
                                file_path,
                                active_api_key,
                                self._adapter,
                                resume_session=file_resume_session,
                                allow_completed_destroy=file_allow_completed_destroy,
                                lesson=lesson_sources_for_item(file_info),
                            )
                        if self._adapter.effective_api_key:
                            active_api_key = self._adapter.effective_api_key

                        last_run_status = self._adapter.last_run_status
                        if (
                            self._cancel_event.is_set()
                            or last_run_status == "cancelled"
                        ) and last_run_status != "failed":
                            break

                        if last_run_status in ("completed", "completed_with_warnings"):
                            comp_status, ok = _handle_file_completed(
                                idx, file_info, self._adapter, last_run_status
                            )
                            if ok:
                                self._emit_api_usage()
                                if comp_status == "completed_with_warnings":
                                    completed_with_warnings_count += 1
                                else:
                                    completed_count += 1
                            else:
                                failed_count += 1
                        else:
                            (
                                paused_delta,
                                failed_delta,
                                quota_exhausted_now,
                                should_stop_batch,
                            ) = _handle_file_failure(
                                idx, file_info, self._adapter, last_run_status
                            )
                            paused_count += paused_delta
                            failed_count += failed_delta
                            quota_exhausted = quota_exhausted or quota_exhausted_now
                            if should_stop_batch:
                                break
                        current_index = None
                        current_file_id = ""
                    except Exception as e:
                        if current_index is not None:
                            ff_payload4: FileFailedPayload = {
                                "index": current_index,
                                "id": current_file_id,
                                "error": redact_secrets(e) or "Errore fatale.",
                            }
                            self._adapter.emit("fileFailed", ff_payload4, batched=False)
                            failed_count += 1
                        self._push_console(f"[!] Errore su file {idx + 1}: {e}")
                        current_index = None
                        current_file_id = ""
            except Exception as e:
                self._push_console(f"[!] Errore fatale: {e}")
            finally:
                self._adapter.is_running = False
                with self._sessions_cache_lock:
                    self._sessions_cache = None
                    self._sessions_cache_gen += 1
                payload: ProcessDonePayload = {
                    "cancelled": bool(
                        self._cancel_event.is_set()
                        or self._adapter.last_run_status == "cancelled"
                    ),
                    "completed": completed_count,
                    "completed_with_warnings": completed_with_warnings_count,
                    "failed": failed_count,
                    "paused": paused_count,
                    "total": len(files),
                }
                if quota_exhausted:
                    payload["quota_exhausted"] = True
                self._adapter.emit("processDone", payload, batched=False)
                self._emit_api_usage()

        self._processing_thread = threading.Thread(target=_run, daemon=True)
        self._processing_thread.start()
        return bridge_ok()

    def answer_regenerate(self, regenerate: bool | None) -> dict:
        """Called by React when user clicks Use Saved or Regenerate."""
        self._adapter.answer_regenerate(regenerate)
        return bridge_ok()

    def answer_new_key(self, key: str | None) -> dict:
        """Called by React when user submits a replacement API key."""
        self._adapter.answer_new_key(key or "")
        return bridge_ok()

    def _emit_api_usage(self) -> None:
        try:
            from jot.services.config_service import load_config
            from jot.services.usage_service import get_daily_usage

            cfg = load_config()
            usage = get_daily_usage(
                primary_key=cfg.get("api_key"),
                fallback_keys=cfg.get("fallback_keys", []),
                primary_model=cfg.get("preferred_model", "gemini-2.5-flash"),
                fallback_models=cfg.get("fallback_models", []),
            )
            self._adapter.emit("apiUsageUpdated", usage, batched=False)
        except Exception:
            pass

    def stop_processing(self) -> dict:
        """Request cancellation."""
        self._cancel_event.set()
        with self._pipeline_lifecycle_lock:
            if self._active_retry_cancel_event is not None:
                self._active_retry_cancel_event.set()
        self._adapter.cancel_pending_prompts()
        thread = self._processing_thread
        if not self._adapter.is_running and (thread is None or not thread.is_alive()):
            payload: ProcessDonePayload = {
                "cancelled": True,
                "completed": 0,
                "failed": 0,
                "total": 0,
            }
            self._adapter.emit("processDone", payload, batched=False)
        return bridge_ok()

    def is_busy(self) -> bool:
        """Internal helper: return True if a pipeline, retry, or session move is active."""
        lifecycle_lock = getattr(self, "_pipeline_lifecycle_lock", None)
        if lifecycle_lock is not None:
            with lifecycle_lock:
                if getattr(self._adapter, "is_running", False):
                    return True
                if getattr(self, "_retry_active_count", 0) > 0:
                    return True
        else:
            if getattr(self._adapter, "is_running", False):
                return True
            if getattr(self, "_retry_active_count", 0) > 0:
                return True

        move_lock = getattr(self, "_move_lock", None)
        if move_lock is not None:
            with move_lock:
                if getattr(self, "_move_state", {}).get("status") == "moving":
                    return True
        else:
            if getattr(self, "_move_state", {}).get("status") == "moving":
                return True

        thread = getattr(self, "_processing_thread", None)
        if thread is not None and thread.is_alive():
            return True
        return False

    def is_processing_active(self) -> dict:
        """IPC method returning active processing status."""
        return bridge_ok(active=self.is_busy())

    def request_shutdown(self, timeout: float = 1.5) -> None:
        """Cleanly request pipeline/retry cancellation and wait briefly for threads to stop."""
        try:
            self.stop_processing()
        except Exception:
            pass
        lifecycle_lock = getattr(self, "_pipeline_lifecycle_lock", None)
        if lifecycle_lock is not None:
            with lifecycle_lock:
                retry_event = getattr(self, "_active_retry_cancel_event", None)
                if retry_event is not None:
                    try:
                        retry_event.set()
                    except Exception:
                        pass
        else:
            retry_event = getattr(self, "_active_retry_cancel_event", None)
            if retry_event is not None:
                try:
                    retry_event.set()
                except Exception:
                    pass
        thread = getattr(self, "_processing_thread", None)
        if (
            thread is not None
            and thread.is_alive()
            and thread != threading.current_thread()
        ):
            try:
                thread.join(timeout=timeout)
            except Exception:
                pass

    def close_window(self) -> dict:
        """Called by WebUI to force window close after user confirms quitting while busy."""
        self._force_close = True
        self.request_shutdown(timeout=1.5)
        window = getattr(self, "_window", None)
        if window is not None:

            def _destroy():
                try:
                    window.destroy()
                except Exception:
                    pass

            threading.Thread(target=_destroy, daemon=True).start()
        return bridge_ok()
