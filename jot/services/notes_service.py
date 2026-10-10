"""
Phase 1 for the "Slide e appunti" mode: turn blocks of slides (plus an optional
textbook excerpt) into study notes with Gemini.

It mirrors phase1_service.py and reuses the same safety net:
- every Gemini call goes through generation_service.retry_with_quota
  (503 back-off, 429 handling, daily quota key rotation, model fallback);
- every answer goes through detect_degenerate_output plus a notes-specific
  "too short" check, so runaway or summarised output is rejected and retried;
- each block is autosaved as phase1_chunks/chunk_NNN_<first>_<last>.md so a
  stopped run resumes from the first missing block.
"""

from __future__ import annotations

import os
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
from jot.services import document_service, generation_service, usage_service
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
from jot.services.phase1_service import (
    _handle_phase1_chunk_recovery,
    _sanitize_error_detail,
)
from jot.utils.logging_utils import get_logger, redact_secrets

NOTES_PHASE_PREFIX = "Fase 1/3: appunti"

# A block of real slides should produce at least this many characters per
# slide; less means the model summarised instead of explaining.
_MIN_CHARS_PER_SLIDE = 90
_MIN_SLIDES_FOR_LENGTH_CHECK = 4


# ---------------------------------------------------------------------------
# Prompt + guardrails
# ---------------------------------------------------------------------------


def build_notes_chunk_prompt(
    *,
    start: int,
    end: int,
    total: int,
    previous_tail: str = "",
    book_pages_label: str = "",
    is_pptx: bool = False,
) -> str:
    if is_pptx:
        source = (
            f"Qui sotto trovi il contenuto delle slide {start}-{end} (su {total}) "
            "estratto dalla presentazione PowerPoint: testo, note del docente e, in ordine, "
            "le immagini contenute nelle slide."
        )
    else:
        source = (
            f"Il PDF delle slide allegato contiene le slide {start}-{end} (su {total} totali): "
            f"la prima pagina del PDF è la slide {start}."
        )
    prompt = (
        f"{source}\n"
        "Scrivi gli appunti di studio completi di QUESTE slide seguendo rigorosamente le istruzioni di sistema. "
        "Non omettere nessun concetto, dato, formula o esempio presente nelle slide. "
        "Non riassumere: la lunghezza degli appunti deve essere proporzionale alla quantità di contenuto delle slide. "
        f"Nei riferimenti in corsivo usa i numeri di slide reali (da {start} a {end})."
    )
    if book_pages_label:
        prompt += (
            "\n\nÈ allegato anche un estratto del LIBRO di testo "
            f"(pagine {book_pages_label} del libro). Usalo solo per approfondire e spiegare "
            "gli argomenti di queste slide."
        )
    if previous_tail:
        prompt += (
            "\n\nATTENZIONE: stai continuando una dispensa già iniziata. Questo è l'ultimo paragrafo "
            f'scritto per le slide precedenti:\n"...{previous_tail}"\n\n'
            "Prosegui in modo coerente, con la stessa gerarchia di titoli. "
            "Non ripetere concetti già spiegati, a meno che queste slide aggiungano dettagli nuovi."
        )
    return prompt


def detect_notes_too_short(text: str, slide_count: int) -> str | None:
    if int(slide_count) < _MIN_SLIDES_FOR_LENGTH_CHECK:
        return None
    length = len(str(text or "").strip())
    minimum = int(slide_count) * _MIN_CHARS_PER_SLIDE
    if length < minimum:
        return (
            f"appunti troppo brevi ({length} caratteri per {slide_count} slide): "
            "probabile riassunto"
        )
    return None


def validate_notes_output(text: str, slide_count: int) -> None:
    reason = detect_degenerate_output(text) or detect_notes_too_short(text, slide_count)
    if reason:
        raise DegenerateOutputError(reason, text)


def _is_bad_request(error: Exception) -> bool:
    text = str(error)
    lowered = text.lower()
    if any(k in lowered for k in ("quota", "resource_exhausted", "429")):
        return False
    return "400" in text or "invalid_argument" in lowered or "badrequest" in lowered


# ---------------------------------------------------------------------------
# Files API helpers
# ---------------------------------------------------------------------------


def _upload_file(client, path: str, mime_type: str):
    try:
        return client.files.upload(file=path, config={"mime_type": mime_type})
    except TypeError:
        return client.files.upload(path=path, config={"mime_type": mime_type})


class UploadedFileCache:
    """Upload a local file once per client and reuse the reference.

    Gemini files belong to the Google project of the key that uploaded them,
    so the cache is invalidated when retry_with_quota rotates the API key.
    """

    def __init__(self, path: str, mime_type: str, cancelled: Callable[[], bool]):
        self.path = path
        self.mime_type = mime_type
        self._cancelled = cancelled
        self._file = None
        self._client = None

    def part(self, client):
        if self._file is None or self._client is not client:
            self.release()
            print(
                f"   -> Caricamento sui server Google: {os.path.basename(self.path)}..."
            )
            uploaded = _upload_file(client, self.path, self.mime_type)
            uploaded = generation_service.wait_for_file_ready(
                client, uploaded, self._cancelled
            )
            if uploaded is None:
                return None
            self._file = uploaded
            self._client = client
        uri = getattr(self._file, "uri", None)
        if uri:
            return types.Part.from_uri(
                file_uri=uri,
                mime_type=getattr(self._file, "mime_type", None) or self.mime_type,
            )
        return self._file

    def release(self) -> None:
        if self._file is not None and self._client is not None:
            try:
                self._client.files.delete(name=self._file.name)
            except Exception:
                pass
        self._file = None
        self._client = None


# ---------------------------------------------------------------------------
# Single block
# ---------------------------------------------------------------------------


def _pdf_part(
    data: bytes,
    *,
    key: str,
    filename: str,
    client,
    temp_dir: str,
    upload_cache: dict[str, UploadedFileCache],
    cancelled: Callable[[], bool],
):
    """Inline PDF part, or a Files API reference above INLINE_MAX_BYTES."""
    if len(data) <= document_service.INLINE_MAX_BYTES:
        return types.Part.from_bytes(data=data, mime_type="application/pdf")
    cache = upload_cache.get(key)
    if cache is None:
        os.makedirs(temp_dir, exist_ok=True)
        tmp_path = os.path.join(temp_dir, filename)
        with open(tmp_path, "wb") as handle:
            handle.write(data)
        cache = UploadedFileCache(tmp_path, "application/pdf", cancelled)
        upload_cache[key] = cache
    return cache.part(client)


def _slide_parts(
    payload: document_service.SlideChunkPayload,
    client,
    temp_dir: str,
    upload_cache: dict[str, UploadedFileCache],
    cancelled: Callable[[], bool],
) -> list[Any] | None:
    parts: list[Any] = []
    if payload.pdf_bytes is not None:
        uploaded = _pdf_part(
            payload.pdf_bytes,
            key="slides",
            filename=f"slides_{payload.start}_{payload.end}.pdf",
            client=client,
            temp_dir=temp_dir,
            upload_cache=upload_cache,
            cancelled=cancelled,
        )
        if uploaded is None:
            return None
        parts.append(uploaded)
    if payload.text:
        parts.append(payload.text)
    for data, mime in payload.images:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    return parts


@dataclass(slots=True)
class BlockBook:
    """Book pages chosen for one block (retrieval mode)."""

    pdf_bytes: bytes
    pages_label: str


def _call_notes_chunk_api(
    *,
    client,
    payload: document_service.SlideChunkPayload,
    chunk_idx: int,
    total_chunks: int,
    total_slides: int,
    prev_memory: str,
    book_cache: UploadedFileCache | None,
    book_pages_label: str,
    is_pptx: bool,
    system_prompt: str,
    block_book: BlockBook | None = None,
    model_name: str,
    model_state: ModelState | None,
    temperature: float,
    temp_dir: str,
    runtime,
    cancelled: Callable[[], bool],
    fallback_keys: list,
    request_fallback_key: Callable[[], str | None],
    on_model_switched=None,
    logger=None,
) -> tuple[Any, str | None]:
    slide_count = payload.end - payload.start + 1
    prompt = build_notes_chunk_prompt(
        start=payload.start,
        end=payload.end,
        total=total_slides,
        previous_tail=(prev_memory or "")[-1000:],
        book_pages_label=(
            block_book.pages_label
            if block_book is not None
            else book_pages_label
            if book_cache is not None
            else ""
        ),
        is_pptx=is_pptx,
    )
    upload_cache: dict[str, UploadedFileCache] = {}

    def _on_key_rotated(_new_client):
        if book_cache is not None:
            book_cache.release()
        for cache in upload_cache.values():
            cache.release()
        print("   Ricarico i documenti con la nuova chiave...")

    def _call(current_client):
        contents: list[Any] = []
        if block_book is not None:
            book_part = _pdf_part(
                block_book.pdf_bytes,
                key="book",
                filename=f"book_block_{chunk_idx:03}.pdf",
                client=current_client,
                temp_dir=temp_dir,
                upload_cache=upload_cache,
                cancelled=cancelled,
            )
            if book_part is None:
                return None
            contents.append(book_part)
        elif book_cache is not None:
            book_part = book_cache.part(current_client)
            if book_part is None:
                return None
            contents.append(book_part)
        slide_parts = _slide_parts(
            payload, current_client, temp_dir, upload_cache, cancelled
        )
        if slide_parts is None:
            return None
        contents.extend(slide_parts)
        contents.append(prompt)
        print("   -> Generazione appunti in corso...")
        try:
            response = current_client.models.generate_content(
                model=current_model_name(model_state, model_name),
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                ),
            )
        except Exception as exc:
            if _is_bad_request(exc):
                raise PermanentError(str(exc)) from exc
            raise
        text = extract_response_text(response)
        if not text:
            raise RuntimeError("Risposta vuota dal modello (text=None)")
        validate_notes_output(text, slide_count)
        return text

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
            resume_phase_text=f"{NOTES_PHASE_PREFIX} (chunk {chunk_idx}/{total_chunks})",
        )
    finally:
        for cache in upload_cache.values():
            cache.release()
            try:
                os.remove(cache.path)
            except Exception:
                pass


def _record_notes_chunk(
    *,
    chunks_dir: str,
    chunk_idx: int,
    start: int,
    end: int,
    total_chunks: int,
    text: str,
    full_text: str,
    session: dict,
    save_session: Callable[[], bool],
    runtime,
    step_t0: float,
) -> tuple[bool, str, str, str | None]:
    out_path = os.path.join(chunks_dir, f"chunk_{chunk_idx:03}_{start}_{end}.md")
    try:
        _atomic_write_text(out_path, text + "\n")
        print(f"   [autosave] Blocco salvato: {os.path.basename(out_path)}")
    except Exception as err:
        print(f"   [!] Autosave blocco fallito: {err}")
        return False, full_text, "", _sanitize_error_detail(err)

    new_full = full_text + f"\n\n{text}\n\n"
    new_memory = text[-2000:]
    _update_session(
        session,
        {
            "stage": "phase1",
            "phase1": {
                **session.get("phase1", {}),
                "chunks_done": int(chunk_idx),
                "next_start_sec": int(end),
                "memoria_precedente": new_memory,
            },
            "last_error": None,
            "last_error_detail": None,
        },
    )
    save_session()
    usage_service.record_work_completed("chunks", 1)
    runtime.update_work_done("chunks", chunk_idx, total=total_chunks)
    runtime.progress(0.7 * chunk_idx / max(1, total_chunks))
    record_step_metric(
        session,
        "chunks",
        max(0.0, time.monotonic() - float(step_t0)),
        done=chunk_idx,
        total=total_chunks,
    )
    return True, new_full, new_memory, None


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class NotesSource:
    slides_path: str
    total_slides: int
    chunks: list[tuple[int, int]]
    book_excerpt_path: str | None = None
    book_pages_label: str = ""
    # Retrieval mode: original book + the pages chosen for every block.
    book_path: str | None = None
    block_book_pages: list[list[int]] | None = None


def _block_book(source: NotesSource, position: int) -> BlockBook | None:
    """PDF with the book pages chosen for this block (retrieval mode only)."""
    if source.block_book_pages is None or not source.book_path:
        return None
    pages = (
        source.block_book_pages[position]
        if position < len(source.block_book_pages)
        else []
    )
    if not pages:
        print(
            "   -> Libro: nessuna pagina pertinente per queste slide (blocco senza libro)."
        )
        return None
    label = document_service.format_page_ranges(pages)
    print(f"   -> Libro: {len(pages)} pagine pertinenti ({label}).")
    return BlockBook(
        pdf_bytes=document_service.build_pdf_subset(source.book_path, pages),
        pages_label=label,
    )


def process_notes_generation(
    *,
    client,
    source: NotesSource,
    model_name: str,
    model_state: ModelState | None,
    temperature: float,
    cancelled: Callable[[], bool],
    start_chunk_index: int,
    initial_full_text: str,
    initial_prev_memory: str,
    chunks_dir: str,
    session: dict,
    save_session: Callable[[], bool],
    fallback_keys: list,
    request_fallback_key: Callable[[], str | None],
    system_prompt: str,
    runtime,
    on_model_switched=None,
    logger=None,
) -> tuple[Any, str | None]:
    """Generate notes for every block from start_chunk_index (0-based).

    Returns (client, full_text) or (client, None) when the run stops early
    (cancelled, quota, permanent error...). session["last_error"] explains why.
    """
    log = logger or get_logger("jot.notes")
    session_dir = os.path.dirname(os.path.abspath(chunks_dir))
    temp_dir = os.path.join(
        session_dir, "temp_chunks", f"notes_{os.getpid()}_{uuid.uuid4().hex}"
    )
    is_pptx = document_service.file_ext(source.slides_path) == ".pptx"
    total_chunks = len(source.chunks)
    full_text = initial_full_text
    prev_memory = initial_prev_memory

    book_cache = (
        UploadedFileCache(source.book_excerpt_path, "application/pdf", cancelled)
        if source.book_excerpt_path
        else None
    )

    runtime.set_work_totals(chunks_total=total_chunks)
    runtime.update_work_done("chunks", start_chunk_index, total=total_chunks)
    if start_chunk_index > 0 and total_chunks > 0:
        runtime.progress(0.7 * start_chunk_index / total_chunks)

    try:
        for position in range(int(start_chunk_index), total_chunks):
            chunk_idx = position + 1
            start, end = source.chunks[position]
            print("\n--------------------------------------")
            print(f"-> Blocco {chunk_idx}/{total_chunks}: slide {start}-{end}")
            runtime.phase(f"{NOTES_PHASE_PREFIX} (chunk {chunk_idx}/{total_chunks})")
            if cancelled():
                print("   [*] Operazione annullata dall'utente.")
                return client, None

            step_t0 = time.monotonic()
            try:
                payload = document_service.build_slide_chunk(
                    source.slides_path, start, end
                )
                block_book = _block_book(source, position)
            except Exception as exc:
                session["last_error"] = f"phase1_chunk_failed_{chunk_idx}"
                session["last_error_detail"] = _sanitize_error_detail(exc)
                save_session()
                print(f"   [!] Impossibile leggere le slide {start}-{end}: {exc}")
                return client, None

            recovery_used = False
            while True:
                failure_detail: str | None = None
                exhausted_message: str | None = None
                try:
                    client, text = _call_notes_chunk_api(
                        client=client,
                        payload=payload,
                        chunk_idx=chunk_idx,
                        total_chunks=total_chunks,
                        total_slides=source.total_slides,
                        prev_memory=prev_memory,
                        book_cache=book_cache,
                        book_pages_label=source.book_pages_label,
                        is_pptx=is_pptx,
                        system_prompt=system_prompt,
                        block_book=block_book,
                        model_name=model_name,
                        model_state=model_state,
                        temperature=temperature,
                        temp_dir=temp_dir,
                        runtime=runtime,
                        cancelled=cancelled,
                        fallback_keys=fallback_keys,
                        request_fallback_key=request_fallback_key,
                        on_model_switched=on_model_switched,
                        logger=log,
                    )
                    if text is None:
                        if cancelled():
                            print("   [*] Operazione annullata dall'utente.")
                            return client, None
                        failure_detail = "Nessuna risposta valida dal modello."
                    else:
                        ok, full_text, prev_memory, failure_detail = (
                            _record_notes_chunk(
                                chunks_dir=chunks_dir,
                                chunk_idx=chunk_idx,
                                start=start,
                                end=end,
                                total_chunks=total_chunks,
                                text=text,
                                full_text=full_text,
                                session=session,
                                save_session=save_session,
                                runtime=runtime,
                                step_t0=step_t0,
                            )
                        )
                        if ok:
                            break
                except (
                    QuotaDailyLimitError,
                    PermanentError,
                    DegenerateOutputError,
                    AllModelsUnavailableError,
                ) as recovery_err:
                    should_retry, should_abort = _handle_phase1_chunk_recovery(
                        recovery_err,
                        chain_exhaustion_recovery_used=recovery_used,
                        model_state=model_state,
                        model_name=model_name,
                        on_model_switched=on_model_switched,
                        chunk_idx=chunk_idx,
                        session=session,
                        save_session=save_session,
                    )
                    if should_retry:
                        recovery_used = True
                        continue
                    if should_abort:
                        return client, None
                    failure_detail = _sanitize_error_detail(recovery_err)
                except CircuitBreakerExhaustedError as exc:
                    # Same contract as audio phase 1: stop with a resumable
                    # per-block error, progress already saved.
                    failure_detail = _sanitize_error_detail(exc)
                    exhausted_message = redact_secrets(exc, max_len=500)
                except Exception as exc:
                    failure_detail = _sanitize_error_detail(exc)
                    exhausted_message = redact_secrets(exc, max_len=500)
                    log.warning(
                        "Errore nel blocco appunti %d: %s",
                        chunk_idx,
                        exc,
                        exc_info=True,
                    )

                session["last_error"] = f"phase1_chunk_failed_{chunk_idx}"
                session["last_error_detail"] = (
                    failure_detail or "Errore sconosciuto durante il blocco."
                )
                save_session()
                print(
                    f"   [!] {exhausted_message or failure_detail} "
                    "Elaborazione interrotta, progressi salvati."
                )
                return client, None

            if position + 1 < total_chunks and not sleep_with_cancel(cancelled, 3):
                print("   [*] Operazione annullata dall'utente.")
                return client, None
    finally:
        if book_cache is not None:
            book_cache.release()
        try:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

    return client, full_text
