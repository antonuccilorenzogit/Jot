"""
Phase 1 (chunked transcription) extracted from the main pipeline.

Mirrors the structure of revision_service.py: a single public function
process_phase1_transcription() that contains all chunk-loop logic.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google.genai import types

from jot.core.model_registry import ModelState
from jot.core.session_store import _update_session
from jot.core.shared import _atomic_write_text
from jot.pipeline.pipeline_session import record_step_metric
from jot.services import generation_service, usage_service
from jot.services.audio_service import cut_audio_chunk_to_mp3
from jot.services.config_service import debug_log
from jot.services.gemini_errors import CircuitBreakerExhaustedError
from jot.services.generation_service import (
    AllModelsUnavailableError,
    DegenerateOutputError,
    PermanentError,
    QuotaDailyLimitError,
    current_model_name,
    detect_degenerate_output,
    extract_response_text,
    retry_with_quota,
    sleep_with_cancel,
)
from jot.services.lesson_context import absolutize_timestamps
from jot.utils.logging_utils import get_logger, redact_secrets


@dataclass(slots=True)
class Phase1ChunkIterationResult:
    """Result of a single Phase 1 chunk transcription iteration."""

    client: Any
    full_transcript: str
    prev_memory: str
    success: bool
    should_retry: bool
    should_abort: bool
    next_cut: dict | None = None


def _sanitize_error_detail(error: object, max_len: int = 500) -> str:
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}"
    else:
        text = str(error or "")
    text = " ".join(text.split())
    return redact_secrets(text, max_len=max_len)


def _phase1_temp_run_dir(phase1_chunks_dir: str) -> str:
    session_dir = os.path.dirname(os.path.abspath(phase1_chunks_dir))
    run_name = f"run_{os.getpid()}_{uuid.uuid4().hex}"
    return os.path.join(session_dir, "temp_chunks", run_name)


def _phase1_chunk_temp_path(
    temp_run_dir: str, chunk_idx: int, start_s: int, end_s: float
) -> str:
    os.makedirs(temp_run_dir, exist_ok=True)
    return os.path.join(
        temp_run_dir,
        f"chunk_{int(chunk_idx):03}_{int(start_s)}_{int(end_s)}.mp3",
    )


def _cleanup_phase1_temp_run_dir(temp_run_dir: str) -> None:
    import shutil

    try:
        shutil.rmtree(temp_run_dir, ignore_errors=True)
    except Exception:
        pass


def process_phase1_transcription(
    *,
    client,
    model_name: str,
    model_state: ModelState | None = None,
    input_path: str,
    preconv_used_path: str | None,
    ffmpeg_exe: str,
    cancel_event,
    cancelled: Callable[[], bool],
    start_sec: int,
    total_duration_sec: float,
    step_seconds: int,
    chunk_seconds: int,
    bitrate: str,
    inline_max_bytes,
    prefetch_enabled: bool,
    initial_full_transcript: str = "",
    initial_prev_memory: str = "",
    phase1_chunks_dir: str,
    session: dict,
    save_session: Callable[[], bool],
    fallback_keys: list,
    request_fallback_key: Callable[[], str | None],
    system_prompt: str,
    runtime,
    on_model_switched=None,
    logger=None,
    slide_context=None,
) -> tuple[object, str | None, str]:
    temp_run_dir = _phase1_temp_run_dir(phase1_chunks_dir)
    try:
        return _process_phase1_transcription_impl(
            client=client,
            model_name=model_name,
            model_state=model_state,
            input_path=input_path,
            preconv_used_path=preconv_used_path,
            ffmpeg_exe=ffmpeg_exe,
            cancel_event=cancel_event,
            cancelled=cancelled,
            start_sec=start_sec,
            total_duration_sec=total_duration_sec,
            step_seconds=step_seconds,
            chunk_seconds=chunk_seconds,
            bitrate=bitrate,
            inline_max_bytes=inline_max_bytes,
            prefetch_enabled=prefetch_enabled,
            initial_full_transcript=initial_full_transcript,
            initial_prev_memory=initial_prev_memory,
            phase1_chunks_dir=phase1_chunks_dir,
            session=session,
            save_session=save_session,
            fallback_keys=fallback_keys,
            request_fallback_key=request_fallback_key,
            system_prompt=system_prompt,
            runtime=runtime,
            on_model_switched=on_model_switched,
            logger=logger,
            temp_run_dir=temp_run_dir,
            slide_context=slide_context,
        )
    finally:
        _cleanup_phase1_temp_run_dir(temp_run_dir)


def _cut_phase1_audio_chunk(
    *,
    chunk_start_sec: int,
    chunk_end_sec: float,
    chunk_path: str,
    bitrate: str,
    preconv_used_path: str | None,
    input_path: str,
    ffmpeg_exe: str,
    cancel_event,
    next_cut: dict | None,
) -> tuple[bool, str | None, dict | None]:
    """Extract audio chunk using prefetch result or synchronous FFmpeg cut."""
    skip_cut = False
    if (
        next_cut is not None
        and int(next_cut.get("start", -1)) == int(chunk_start_sec)
        and int(next_cut.get("end", -1)) == int(chunk_end_sec)
    ):
        t = next_cut.get("thread")
        if t is not None:
            try:
                t.join()
            except Exception:
                pass
        try:
            r = next_cut.get("result") or {}
            if (
                bool(r.get("ok"))
                and os.path.exists(chunk_path)
                and os.path.getsize(chunk_path) > 1024
            ):
                skip_cut = True
            else:
                debug_log(f"prefetch chunk failed; will cut sync: {r.get('err')}")
        except Exception as e:
            debug_log(f"prefetch join/check error: {e}")
        next_cut = None

    if not skip_cut:
        duration = float(chunk_end_sec) - float(chunk_start_sec)
        if duration <= 0:
            return False, "durata_chunk_non_valida", next_cut
        if preconv_used_path and os.path.exists(preconv_used_path):
            ok, err = cut_audio_chunk_to_mp3(
                input_path=preconv_used_path,
                output_path=chunk_path,
                start_sec=chunk_start_sec,
                duration_sec=duration,
                ffmpeg_exe=ffmpeg_exe,
                stream_copy=True,
                bitrate=bitrate,
                stop_event=cancel_event,
            )
            if ok:
                return True, None, next_cut
            debug_log(f"cut(stream_copy) failed; fallback reencode: {err}")
        ok, err = cut_audio_chunk_to_mp3(
            input_path=input_path,
            output_path=chunk_path,
            start_sec=chunk_start_sec,
            duration_sec=duration,
            ffmpeg_exe=ffmpeg_exe,
            stream_copy=False,
            bitrate=bitrate,
            stop_event=cancel_event,
        )
        if not ok:
            return False, err, next_cut

    return True, None, next_cut


def _generate_chunk_content_with_fallback(
    *,
    current_client,
    model_name: str,
    model_state: ModelState | None,
    system_prompt: str,
    chunk_prompt: str,
    audio_inline,
    ensure_uploaded_audio_fn,
    extra_parts: list | None = None,
) -> str | None:
    audio_mode = "inline" if audio_inline is not None else "upload"
    tried_upload_fallback = False
    while True:
        try:
            if audio_mode == "inline" and audio_inline is not None:
                audio_input = audio_inline
            else:
                audio_input = ensure_uploaded_audio_fn(current_client)
                if audio_input is None:
                    return None
            print("   -> (3/3) Generazione sbobina in corso...")
            _active_model = current_model_name(model_state, model_name)
            response = current_client.models.generate_content(
                model=_active_model,
                contents=[*(extra_parts or []), chunk_prompt, audio_input],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=generation_service._phase1_temperature(_active_model),
                ),
            )
            generated_text = extract_response_text(response)
            if not generated_text:
                raise RuntimeError("Risposta vuota dal modello (text=None)")
            degenerate_reason = detect_degenerate_output(generated_text)
            if degenerate_reason:
                raise DegenerateOutputError(degenerate_reason, generated_text)
            return generated_text
        except Exception as e:
            err_txt = str(e)
            err_lower = err_txt.lower()
            if (
                audio_mode == "inline"
                and not tried_upload_fallback
                and any(
                    k in err_lower
                    for k in (
                        "invalid_argument",
                        "badrequest",
                        "400",
                        "payload",
                        "too large",
                        "size",
                    )
                )
                and not any(
                    k in err_lower for k in ("quota", "resource_exhausted", "429")
                )
            ):
                tried_upload_fallback = True
                audio_mode = "upload"
                print(
                    "      [Inline audio non accettato. Fallback a upload del chunk...]"
                )
                continue
            if (
                "400" in err_txt
                or "BadRequest" in err_txt
                or "INVALID_ARGUMENT" in err_txt
            ):
                raise PermanentError(err_txt)
            raise


def _call_chunk_transcription_api(
    *,
    client,
    chunk_path: str,
    chunk_idx: int,
    total_chunks: int,
    prev_memory: str,
    system_prompt: str,
    model_name: str,
    model_state: ModelState | None,
    inline_max_bytes,
    runtime,
    cancelled: Callable[[], bool],
    fallback_keys: list,
    request_fallback_key: Callable[[], str | None],
    on_model_switched=None,
    logger=None,
    slide_window=None,
) -> tuple[object, str | None]:
    """Call Gemini to transcribe a single audio chunk with automatic inline/upload fallback."""
    audio_inline = generation_service.make_inline_audio_part(
        chunk_path, max_bytes=inline_max_bytes
    )
    if audio_inline is not None:
        print("   -> (2/3) Preparazione audio (inline)...")

    chunk_prompt = generation_service.build_chunk_prompt(prev_memory)
    extra_parts = None
    if slide_window is not None:
        chunk_prompt += slide_window.prompt
        extra_parts = list(slide_window.parts)
    audio_file = None
    file_client = None

    def _ensure_uploaded_audio_input(current_client):
        nonlocal audio_file, file_client
        if audio_file is not None:
            try:
                if getattr(audio_file, "uri", None):
                    return types.Part.from_uri(
                        file_uri=audio_file.uri,
                        mime_type=(
                            getattr(audio_file, "mime_type", None) or "audio/mpeg"
                        ),
                    )
            except Exception:
                return audio_file
            return audio_file
        print("   -> (2/3) Caricamento sicuro nei server di google...")
        audio_file = generation_service.upload_audio_path(
            current_client,
            chunk_path,
        )
        file_client = current_client
        audio_file = generation_service.wait_for_file_ready(
            current_client, audio_file, cancelled
        )
        if audio_file is None:
            print("   [*] Operazione annullata dall'utente.")
            return None
        try:
            if getattr(audio_file, "uri", None):
                return types.Part.from_uri(
                    file_uri=audio_file.uri,
                    mime_type=(getattr(audio_file, "mime_type", None) or "audio/mpeg"),
                )
        except Exception:
            pass
        return audio_file

    def _on_key_rotated(_new_client):
        nonlocal audio_file, file_client
        if audio_file is not None and file_client is not None:
            try:
                file_client.files.delete(name=audio_file.name)
            except Exception:
                pass
            audio_file = None
            file_client = None
            print("   Ricarico questo blocco con la nuova chiave...")
        else:
            print("   Ripresa automatica (inline audio).")

    def _call(current_client):
        return _generate_chunk_content_with_fallback(
            current_client=current_client,
            model_name=model_name,
            model_state=model_state,
            system_prompt=system_prompt,
            chunk_prompt=chunk_prompt,
            audio_inline=audio_inline,
            ensure_uploaded_audio_fn=_ensure_uploaded_audio_input,
            extra_parts=extra_parts,
        )

    try:
        return retry_with_quota(
            _call,
            client=client,
            fallback_keys=fallback_keys,
            model_name=model_name,
            model_state=model_state,
            runtime=runtime,
            cancelled=cancelled,
            request_fallback_key=request_fallback_key,
            retry_sleep_seconds=30.0,
            on_key_rotated=_on_key_rotated,
            on_model_switched=on_model_switched,
            logger=logger,
            resume_phase_text=f"Fase 1/3: trascrizione (chunk {chunk_idx}/{total_chunks})",
        )
    finally:
        if audio_file is not None and file_client is not None:
            try:
                file_client.files.delete(name=audio_file.name)
            except Exception:
                pass


def _record_chunk_success(
    *,
    phase1_chunks_dir: str,
    chunk_idx: int,
    chunk_start_sec: int,
    chunk_end_sec: float,
    total_chunks: int,
    step_seconds: int,
    generated_text: str,
    full_transcript: str,
    session: dict,
    save_session: Callable[[], bool],
    runtime,
    chunk_step_t0: float,
) -> tuple[bool, str, str, str | None]:
    """Save chunk output markdown, update session state, and record metrics."""
    out_chunk_md = os.path.join(
        phase1_chunks_dir,
        f"chunk_{chunk_idx:03}_{chunk_start_sec}_{int(chunk_end_sec)}.md",
    )
    try:
        _atomic_write_text(out_chunk_md, generated_text + "\n")
        print(f"   [autosave] Chunk salvato: {os.path.basename(out_chunk_md)}")
    except Exception as save_err:
        last_failure_detail = _sanitize_error_detail(save_err)
        print(f"   [!] Autosave chunk fallito: {save_err}")
        return False, full_transcript, "", last_failure_detail

    new_full_transcript = full_transcript + f"\n\n{generated_text}\n\n"
    new_prev_memory = generated_text[-2000:]
    _update_session(
        session,
        {
            "stage": "phase1",
            "phase1": {
                **session.get("phase1", {}),
                "chunks_done": int(chunk_idx),
                "next_start_sec": int(chunk_start_sec + step_seconds),
                "memoria_precedente": new_prev_memory,
            },
            "last_error": None,
            "last_error_detail": None,
        },
    )
    save_session()
    usage_service.record_work_completed("chunks", 1)
    runtime.progress(0.7 * chunk_idx / total_chunks)
    _step_secs = max(0.0, time.monotonic() - float(chunk_step_t0))
    record_step_metric(
        session,
        "chunks",
        _step_secs,
        done=chunk_idx,
        total=total_chunks,
    )
    return True, new_full_transcript, new_prev_memory, None


def _handle_phase1_chunk_recovery(
    exc: Exception,
    *,
    chain_exhaustion_recovery_used: bool,
    model_state: ModelState | None,
    model_name: str,
    on_model_switched,
    chunk_idx: int,
    session: dict,
    save_session: Callable[[], bool],
) -> tuple[bool, bool]:
    """Handle model errors and return (should_retry_pass, should_abort)."""
    if isinstance(exc, QuotaDailyLimitError):
        session["last_error"] = "quota_daily_limit_phase1"
        if session.get("last_error_detail") != "api_key_prompt_timeout":
            session["last_error_detail"] = None
        save_session()
        print("[*] Interruzione: progressi salvati. Potrai riprendere piu' tardi.")
        return False, True

    if isinstance(exc, PermanentError):
        print(f"   [!] Richiesta non valida (400). Dettagli:\n{exc}")
        session["last_error"] = "bad_request_phase1"
        session["last_error_detail"] = None
        save_session()
        return False, True

    if isinstance(exc, DegenerateOutputError):
        if not chain_exhaustion_recovery_used:
            if model_state is not None:
                old_model = model_state.current
                model_state.current = model_state.chain[0]
                if on_model_switched is not None and old_model != model_state.current:
                    on_model_switched(old_model, model_state.current)
            print(
                f"   [Recovery automatica] chunk={chunk_idx}: catena modelli esaurita ({exc}) - un ulteriore pass dal modello primario ({model_state.current if model_state is not None else model_name})..."
            )
            return True, False
        _excerpt = getattr(exc, "rejected_text", "")
        _excerpt_log = f"\n      excerpt: {_excerpt[:400]}" if _excerpt else ""
        print(
            f'   [!] Output degenerato nel blocco {chunk_idx}: anche il pass di recovery ha fallito reason="{exc}"{_excerpt_log}'
        )
        session["last_error"] = "phase1_degenerate_output"
        session["last_error_detail"] = None
        save_session()
        return False, True

    if isinstance(exc, AllModelsUnavailableError):
        if not chain_exhaustion_recovery_used:
            if model_state is not None:
                old_model = model_state.current
                model_state.current = model_state.chain[0]
                if on_model_switched is not None and old_model != model_state.current:
                    on_model_switched(old_model, model_state.current)
            print(
                f"   [Recovery automatica] chunk={chunk_idx}: tutti i modelli indisponibili ({exc}) - un ulteriore pass dal modello primario ({model_state.current if model_state is not None else model_name})..."
            )
            return True, False
        session["last_error"] = "phase1_all_models_unavailable"
        session["last_error_detail"] = None
        save_session()
        return False, True

    return False, False


def _postprocess_chunk_text(
    text: str,
    *,
    chunk_idx: int,
    chunk_start_sec: int,
    chunk_seconds: int,
    slide_context,
    slide_window,
    session: dict,
) -> str:
    """Strip the slide marker and turn block-relative times into absolute ones."""
    if slide_context is not None:
        text = slide_context.observe(chunk_idx, text, slide_window)
        session.setdefault("phase1", {})["slide_positions"] = slide_context.to_dict()
    return absolutize_timestamps(text, int(chunk_start_sec), int(chunk_seconds))


def _process_single_phase1_chunk_iteration(
    *,
    temp_run_dir: str,
    chunk_idx: int,
    chunk_start_sec: int,
    chunk_end_sec: float,
    total_chunks: int,
    step_seconds: int,
    chunk_seconds: int,
    bitrate: str,
    preconv_used_path: str | None,
    input_path: str,
    ffmpeg_exe: str,
    cancel_event,
    cancelled: Callable[[], bool],
    next_cut: dict | None,
    prefetch_enabled: bool,
    total_duration_sec: float,
    client,
    prev_memory: str,
    system_prompt: str,
    model_name: str,
    model_state: ModelState | None,
    inline_max_bytes,
    runtime,
    fallback_keys: list,
    request_fallback_key: Callable[[], str | None],
    on_model_switched,
    logger,
    phase1_chunks_dir: str,
    full_transcript: str,
    session: dict,
    save_session: Callable[[], bool],
    chain_exhaustion_recovery_used: bool,
    start_prefetch_fn: Callable[[int, int, float, str], dict | None],
    slide_context=None,
) -> Phase1ChunkIterationResult:
    """Execute one attempt of a Phase 1 chunk transcription."""
    chunk_step_t0 = time.monotonic()
    chunk_path = _phase1_chunk_temp_path(
        temp_run_dir, chunk_idx, chunk_start_sec, chunk_end_sec
    )
    runtime.track_temp_file(chunk_path)

    success = False
    last_failure_detail: str | None = None
    retry_exhausted_message: str | None = None

    try:
        print("   -> (1/3) Estrazione e taglio in corso...")
        cut_ok, cut_err, next_cut = _cut_phase1_audio_chunk(
            chunk_start_sec=chunk_start_sec,
            chunk_end_sec=chunk_end_sec,
            chunk_path=chunk_path,
            bitrate=bitrate,
            preconv_used_path=preconv_used_path,
            input_path=input_path,
            ffmpeg_exe=ffmpeg_exe,
            cancel_event=cancel_event,
            next_cut=next_cut,
        )
        if not cut_ok:
            if str(cut_err or "").strip().lower() == "cancelled" or cancelled():
                print("   [*] Operazione annullata dall'utente.")
                return Phase1ChunkIterationResult(
                    client=client,
                    full_transcript=full_transcript,
                    prev_memory=prev_memory,
                    success=False,
                    should_retry=False,
                    should_abort=True,
                    next_cut=next_cut,
                )
            raise RuntimeError(
                f"FFmpeg ha fallito l'estrazione audio:\n{cut_err}"
                if cut_err
                else "FFmpeg ha fallito l'estrazione audio."
            )

        # Prefetch next chunk
        try:
            next_start = int(chunk_start_sec + step_seconds)
            if (
                next_cut is None
                and prefetch_enabled
                and next_start < int(total_duration_sec)
            ):
                next_end = min(
                    float(next_start + chunk_seconds), float(total_duration_sec)
                )
                next_cut = start_prefetch_fn(
                    chunk_idx + 1, next_start, next_end, bitrate
                )
        except Exception as e:
            debug_log(f"prefetch schedule error: {e}")

        slide_window = (
            slide_context.context(chunk_idx, chunk_start_sec)
            if slide_context is not None
            else None
        )
        try:
            client, generated_text = _call_chunk_transcription_api(
                slide_window=slide_window,
                client=client,
                chunk_path=chunk_path,
                chunk_idx=chunk_idx,
                total_chunks=total_chunks,
                prev_memory=prev_memory,
                system_prompt=system_prompt,
                model_name=model_name,
                model_state=model_state,
                inline_max_bytes=inline_max_bytes,
                runtime=runtime,
                cancelled=cancelled,
                fallback_keys=fallback_keys,
                request_fallback_key=request_fallback_key,
                on_model_switched=on_model_switched,
                logger=logger,
            )
            if generated_text is not None:
                generated_text = _postprocess_chunk_text(
                    generated_text,
                    chunk_idx=chunk_idx,
                    chunk_start_sec=chunk_start_sec,
                    chunk_seconds=chunk_seconds,
                    slide_context=slide_context,
                    slide_window=slide_window,
                    session=session,
                )
                (
                    saved_ok,
                    full_transcript,
                    prev_memory,
                    last_failure_detail,
                ) = _record_chunk_success(
                    phase1_chunks_dir=phase1_chunks_dir,
                    chunk_idx=chunk_idx,
                    chunk_start_sec=chunk_start_sec,
                    chunk_end_sec=chunk_end_sec,
                    total_chunks=total_chunks,
                    step_seconds=step_seconds,
                    generated_text=generated_text,
                    full_transcript=full_transcript,
                    session=session,
                    save_session=save_session,
                    runtime=runtime,
                    chunk_step_t0=chunk_step_t0,
                )
                success = saved_ok

        except (
            QuotaDailyLimitError,
            PermanentError,
            DegenerateOutputError,
            AllModelsUnavailableError,
        ) as recovery_err:
            should_retry, should_abort = _handle_phase1_chunk_recovery(
                recovery_err,
                chain_exhaustion_recovery_used=chain_exhaustion_recovery_used,
                model_state=model_state,
                model_name=model_name,
                on_model_switched=on_model_switched,
                chunk_idx=chunk_idx,
                session=session,
                save_session=save_session,
            )
            if should_retry:
                return Phase1ChunkIterationResult(
                    client=client,
                    full_transcript=full_transcript,
                    prev_memory=prev_memory,
                    success=False,
                    should_retry=True,
                    should_abort=False,
                    next_cut=next_cut,
                )
            if should_abort:
                return Phase1ChunkIterationResult(
                    client=client,
                    full_transcript=full_transcript,
                    prev_memory=prev_memory,
                    success=False,
                    should_retry=False,
                    should_abort=True,
                    next_cut=next_cut,
                )

        except CircuitBreakerExhaustedError as e:
            last_failure_detail = _sanitize_error_detail(e)
            retry_exhausted_message = redact_secrets(e, max_len=500)
            if logger is not None:
                logger.warning(
                    "Tentativi esauriti nel chunk %d: %s",
                    chunk_idx,
                    e,
                    exc_info=True,
                    extra={"diagnostic_only": True},
                )

        except Exception as e:
            last_failure_detail = _sanitize_error_detail(e)
            if logger is not None:
                logger.warning(
                    "Errore non gestito nel chunk %d: %s",
                    chunk_idx,
                    e,
                    exc_info=True,
                )

    except Exception as e:
        last_failure_detail = _sanitize_error_detail(e)
        print(f"   [!] Errore durante l'elaborazione del blocco: {e}")

    finally:
        if os.path.exists(chunk_path):
            try:
                os.remove(chunk_path)
            except Exception:
                pass

    if not success:
        session["last_error"] = f"phase1_chunk_failed_{chunk_idx}"
        session["last_error_detail"] = (
            last_failure_detail or "Errore sconosciuto durante il blocco."
        )
        save_session()
        if retry_exhausted_message is not None:
            print(
                f"   [!] {retry_exhausted_message} "
                "Elaborazione interrotta, progressi salvati. Potrai riprendere piu' tardi."
            )
        else:
            print(
                "   [!] Errore critico durante l'elaborazione del blocco. Interrompo (progressi salvati)."
            )
        return Phase1ChunkIterationResult(
            client=client,
            full_transcript=full_transcript,
            prev_memory=prev_memory,
            success=False,
            should_retry=False,
            should_abort=True,
            next_cut=next_cut,
        )

    return Phase1ChunkIterationResult(
        client=client,
        full_transcript=full_transcript,
        prev_memory=prev_memory,
        success=True,
        should_retry=False,
        should_abort=False,
        next_cut=next_cut,
    )


def _process_phase1_transcription_impl(
    *,
    temp_run_dir: str,
    client,
    model_name: str,
    model_state: ModelState | None = None,
    input_path: str,
    preconv_used_path: str | None,
    ffmpeg_exe: str,
    cancel_event,
    cancelled: Callable[[], bool],
    start_sec: int,
    total_duration_sec: float,
    step_seconds: int,
    chunk_seconds: int,
    bitrate: str,
    inline_max_bytes,
    prefetch_enabled: bool,
    initial_full_transcript: str = "",
    initial_prev_memory: str = "",
    phase1_chunks_dir: str,
    session: dict,
    save_session: Callable[[], bool],
    fallback_keys: list,
    request_fallback_key: Callable[[], str | None],
    system_prompt: str,
    runtime,
    on_model_switched=None,
    logger=None,
    slide_context=None,
) -> tuple[object, str | None, str]:
    """Run the Phase 1 chunk transcription loop."""
    log = logger or get_logger("jot.phase1")

    def _finish(
        result: tuple[object, str | None, str],
    ) -> tuple[object, str | None, str]:
        return result

    full_transcript = initial_full_transcript
    prev_memory = initial_prev_memory

    dur_int = int(total_duration_sec)
    total_chunks = 0 if dur_int <= 0 else (dur_int + step_seconds - 1) // step_seconds
    start_int = int(start_sec)
    chunk_idx = 0 if start_int <= 0 else (start_int + step_seconds - 1) // step_seconds

    runtime.set_work_totals(chunks_total=total_chunks)
    runtime.update_work_done("chunks", chunk_idx, total=total_chunks)
    if chunk_idx > 0 and total_chunks > 0:
        runtime.progress(0.7 * chunk_idx / total_chunks)

    next_cut = None

    def _start_prefetch(
        next_chunk_idx: int, next_start_s: int, next_end_s: float, brate: str
    ) -> dict | None:
        if not prefetch_enabled or next_start_s is None or next_end_s is None:
            return None
        try:
            path_next = _phase1_chunk_temp_path(
                temp_run_dir, next_chunk_idx, next_start_s, next_end_s
            )
        except Exception:
            return None
        runtime.track_temp_file(path_next)
        result = {"ok": False, "err": None}

        def worker():
            ok, err, _ = _cut_phase1_audio_chunk(
                chunk_start_sec=int(next_start_s),
                chunk_end_sec=float(next_end_s),
                chunk_path=path_next,
                bitrate=brate,
                preconv_used_path=preconv_used_path,
                input_path=input_path,
                ffmpeg_exe=ffmpeg_exe,
                cancel_event=cancel_event,
                next_cut=None,
            )
            result["ok"] = bool(ok)
            result["err"] = err

        t = threading.Thread(target=worker, daemon=True)
        scheduled = {
            "start": int(next_start_s),
            "end": int(next_end_s),
            "path": path_next,
            "thread": t,
            "result": result,
        }
        t.start()
        return scheduled

    for chunk_start_sec in range(int(start_sec), int(total_duration_sec), step_seconds):
        chunk_idx += 1
        chunk_end_sec = min(chunk_start_sec + chunk_seconds, total_duration_sec)

        print(f"\n--------------------------------------")
        print(
            f"-> Blocco Audio {chunk_idx}/{total_chunks} ({chunk_start_sec}s -> {int(chunk_end_sec)}s)"
        )
        runtime.phase(f"Fase 1/3: trascrizione (chunk {chunk_idx}/{total_chunks})")

        if cancelled():
            print("   [*] Operazione annullata dall'utente.")
            return _finish((client, None, prev_memory))

        chain_exhaustion_recovery_used = False

        while True:
            chunk_res = _process_single_phase1_chunk_iteration(
                temp_run_dir=temp_run_dir,
                chunk_idx=chunk_idx,
                chunk_start_sec=chunk_start_sec,
                chunk_end_sec=chunk_end_sec,
                total_chunks=total_chunks,
                step_seconds=step_seconds,
                chunk_seconds=chunk_seconds,
                bitrate=bitrate,
                preconv_used_path=preconv_used_path,
                input_path=input_path,
                ffmpeg_exe=ffmpeg_exe,
                cancel_event=cancel_event,
                cancelled=cancelled,
                next_cut=next_cut,
                prefetch_enabled=prefetch_enabled,
                total_duration_sec=total_duration_sec,
                client=client,
                prev_memory=prev_memory,
                system_prompt=system_prompt,
                model_name=model_name,
                model_state=model_state,
                inline_max_bytes=inline_max_bytes,
                runtime=runtime,
                fallback_keys=fallback_keys,
                request_fallback_key=request_fallback_key,
                on_model_switched=on_model_switched,
                logger=log,
                phase1_chunks_dir=phase1_chunks_dir,
                full_transcript=full_transcript,
                session=session,
                save_session=save_session,
                chain_exhaustion_recovery_used=chain_exhaustion_recovery_used,
                start_prefetch_fn=_start_prefetch,
                slide_context=slide_context,
            )
            client = chunk_res.client
            full_transcript = chunk_res.full_transcript
            prev_memory = chunk_res.prev_memory
            next_cut = chunk_res.next_cut
            if chunk_res.should_abort:
                return _finish((client, None, prev_memory))
            if chunk_res.should_retry:
                chain_exhaustion_recovery_used = True
                continue
            if chunk_res.success:
                break

        if chunk_start_sec + step_seconds < int(total_duration_sec):
            if not sleep_with_cancel(cancelled, 5):
                print("   [*] Operazione annullata dall'utente.")
                return _finish((client, None, prev_memory))

    return _finish((client, full_transcript, prev_memory))
