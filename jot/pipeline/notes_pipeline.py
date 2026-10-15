"""
Pipeline for the "Slide e appunti" mode.

Input: lesson slides (PDF/PPTX) and an optional textbook PDF with a page range.
Output: the same *_Sbobina.html document produced by the audio pipeline, so the
queue, the editor, the archive and the revision retry work unchanged.

Stages reuse the audio pipeline contract stored in session.json:
    phase1 -> notes generation per block of slides (notes_service)
    phase2 -> macro-block revision (revision_service, same as audio)
    done   -> HTML exported
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from jot.core.model_registry import build_model_state
from jot.core.prompts import PROMPT_APPUNTI, PROMPT_REVISIONE_APPUNTI
from jot.core.session_store import (
    _session_id_for_file,
    _update_session,
    get_session_root,
)
from jot.pipeline.pipeline import (
    _export_html_and_finish,
    _handle_circuit_breaker_paused,
    _handle_regeneration_flow,
    _make_fallback_key_requester,
    _pipeline_finally_cleanup,
    _run_phase2_revision,
)
from jot.pipeline.pipeline_hooks import PipelineRuntime
from jot.pipeline.pipeline_session import (
    AutosaveFailedError,
    PipelineSessionContext,
    SaveSessionGuard,
    initialize_session_context,
    list_phase1_chunks,
    normalize_stage,
    phase1_has_progress,
    read_text_file,
)
from jot.pipeline.summary_step import run_summary_step
from jot.services import (
    book_retrieval,
    document_service,
    generation_service,
)
from jot.services.gemini_errors import CircuitBreakerExhaustedError
from jot.services.generation_service import (
    create_gemini_client,
    load_fallback_keys,
)
from jot.services.notes_service import NotesSource, process_notes_generation
from jot.utils.logging_utils import (
    attach_file_handler,
    get_logger,
    operation_id,
)

SESSION_KIND_NOTES = "notes"
BOOK_EXCERPT_FILENAME = "book_excerpt.pdf"


def notes_session_dir(
    slides_path: str,
    book_path: str | None = None,
    book_pages: str = "",
    book_mode: str = book_retrieval.BOOK_MODE_FULL,
) -> str:
    """Deterministic session folder for a slides(+book) combination."""
    blob = {
        "kind": SESSION_KIND_NOTES,
        "slides": _session_id_for_file(slides_path),
        "book": _session_id_for_file(book_path) if book_path else "",
        "book_pages": str(book_pages or "").replace(" ", ""),
    }
    # "full" is the original behaviour: leaving it out of the hash keeps the
    # folders of sessions created before page retrieval existed.
    if book_path and book_mode != book_retrieval.BOOK_MODE_FULL:
        blob["book_mode"] = book_mode
    digest = hashlib.sha256(
        json.dumps(blob, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return os.path.join(get_session_root(), f"notes_{digest[:56]}")


def _apply_notes_metadata(session: dict, meta: dict) -> None:
    session["kind"] = SESSION_KIND_NOTES
    raw_existing = session.get("notes")
    existing: dict = raw_existing if isinstance(raw_existing, dict) else {}
    phase1 = session.get("phase1")
    chunks_done = (
        int((phase1 or {}).get("chunks_done", 0) or 0)
        if isinstance(phase1, dict)
        else 0
    )
    merged = dict(meta)
    title = str(merged.pop("title", "") or "").strip()
    course = str(merged.pop("course", "") or "").strip()
    if title:
        session["title"] = title
        session["custom_title"] = title
    if course:
        session["course"] = course
    # Keep the block size of a session that already has generated blocks:
    # changing it mid-way would invalidate them.
    if chunks_done > 0 and existing.get("slides_per_chunk"):
        merged["slides_per_chunk"] = existing["slides_per_chunk"]
    # The book page plan is validated against the block count when reused.
    if existing.get("book_plan") and existing.get("slides_per_chunk") == merged.get(
        "slides_per_chunk"
    ):
        merged["book_plan"] = existing["book_plan"]
    session["notes"] = merged


def _restore_notes_progress(
    session_ctx: PipelineSessionContext, chunks: list[tuple[int, int]]
) -> tuple[int, str, str]:
    """Return (blocks_done, full_text, prev_memory) from the autosaved blocks."""
    done = 0
    texts: list[str] = []
    for idx, start, end, path in list_phase1_chunks(session_ctx.phase1_chunks_dir):
        if done >= len(chunks):
            break
        if idx != done + 1 or (start, end) != tuple(chunks[done]):
            break
        try:
            text = read_text_file(path).strip()
        except Exception:
            break
        if not text:
            break
        texts.append(text)
        done += 1
    full_text = "".join(f"\n\n{t}\n\n" for t in texts)
    prev_memory = texts[-1][-2000:] if texts else ""
    return done, full_text, prev_memory


def _prepare_book_excerpt(
    session_ctx: PipelineSessionContext,
    book_path: str,
    selected_pages: list[int],
) -> str:
    out_path = os.path.join(session_ctx.session_dir, BOOK_EXCERPT_FILENAME)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    print(
        f"[*] Estrazione di {len(selected_pages)} pagine dal libro "
        f"({os.path.basename(book_path)})..."
    )
    document_service.write_book_excerpt(book_path, selected_pages, out_path)
    return out_path


def _validate_documents(
    slides_path: str,
    book_path: str | None,
    book_pages: str,
    runtime: PipelineRuntime,
) -> tuple[int, list[int]] | None:
    """Phase 0: validate slides/book before any API call."""
    runtime.phase("Fase 0/3: preparazione documenti")
    print(f"[*] Analisi delle slide:\n{os.path.basename(slides_path)}")
    try:
        total_slides = document_service.validate_slides(slides_path)
        selected_book_pages: list[int] = []
        if book_path:
            _book_total, selected_book_pages = document_service.validate_book(
                book_path, book_pages
            )
    except document_service.DocumentError as exc:
        print(f"[!] {exc}")
        runtime.console_error(str(exc))
        runtime.set_run_result("failed", str(exc))
        return None
    print(f"[*] Slide trovate: {total_slides}.")
    if book_path:
        print(
            f"[*] Libro: {os.path.basename(book_path)} - pagine "
            f"{document_service.format_page_ranges(selected_book_pages)}."
        )
    return total_slides, selected_book_pages


def _log_book_plan(plan: book_retrieval.BookPlan, chunks, n_selected: int) -> None:
    if plan.method == book_retrieval.METHOD_FULL:
        print(f"[*] Libro: invio l'estratto completo a ogni blocco ({plan.reason}).")
        return
    print(f"[*] Pagine del libro scelte per blocco - metodo: {plan.reason}")
    for i, ((start, end), pages) in enumerate(zip(chunks, plan.blocks, strict=False)):
        label = document_service.format_page_ranges(pages) if pages else "nessuna"
        print(f"    Blocco {i + 1} (slide {start}-{end}) -> libro p. {label}")
    for note in plan.notes:
        print(f"    Nota: {note}")
    sent = sum(len(b) for b in plan.blocks)
    full = n_selected * len(chunks)
    if full > 0:
        saving = 100 - round(100 * sent / full)
        print(
            f"[*] Pagine di libro inviate in totale: {sent} invece di {full} "
            f"(circa {saving}% di token del libro in meno)."
        )


def _resolve_book_plan(
    *,
    client,
    session_ctx: PipelineSessionContext,
    session: dict,
    save_session,
    runtime: PipelineRuntime,
    slides_path: str,
    chunks: list[tuple[int, int]],
    book_path: str,
    selected_book_pages: list[int],
) -> book_retrieval.BookPlan | None:
    """Reuse the saved plan or compute it. None = cancelled."""
    notes = session.get("notes") if isinstance(session.get("notes"), dict) else {}
    saved = book_retrieval.BookPlan.from_dict(
        (notes or {}).get("book_plan"), len(chunks)
    )
    if saved is not None:
        print("[*] Riuso le pagine del libro già scelte per questa lezione.")
        return saved
    runtime.phase("Fase 0/3: preparazione documenti")
    print("[*] Scelta delle pagine del libro pertinenti a ogni blocco di slide...")
    try:
        plan = book_retrieval.plan_book_pages(
            client=client,
            book_path=book_path,
            allowed_pages=selected_book_pages,
            slides_path=slides_path,
            chunks=chunks,
            cache_dir=session_ctx.session_dir,
            cancelled=runtime.cancelled,
            log=print,
        )
    except Exception as exc:
        if runtime.cancelled():
            return None
        print(
            f"   [!] Scelta delle pagine non riuscita ({exc}): uso l'estratto completo."
        )
        plan = book_retrieval.BookPlan(
            book_retrieval.METHOD_FULL,
            [list(selected_book_pages) for _ in chunks],
            reason="errore nella scelta delle pagine",
        )
    _log_book_plan(plan, chunks, len(selected_book_pages))
    session.setdefault("notes", {})["book_plan"] = plan.to_dict()
    save_session()
    return plan


def _run_notes_phase1(
    *,
    client,
    session_ctx: PipelineSessionContext,
    session: dict,
    save_session,
    settings,
    model_state,
    runtime: PipelineRuntime,
    slides_path: str,
    total_slides: int,
    chunks: list[tuple[int, int]],
    book_path: str | None,
    selected_book_pages: list[int],
    book_pages_label: str,
    blocks_done: int,
    full_text: str,
    prev_memory: str,
    fallback_keys: list[str],
    request_fallback_key,
    on_model_switched,
    logger,
    book_mode: str = book_retrieval.BOOK_MODE_FULL,
):
    """Phase 1: notes for every missing block. Returns (client, full_text|None)."""
    book_excerpt = None
    block_book_pages: list[list[int]] | None = None
    if book_path and book_mode == book_retrieval.BOOK_MODE_AUTO:
        plan = _resolve_book_plan(
            client=client,
            session_ctx=session_ctx,
            session=session,
            save_session=save_session,
            runtime=runtime,
            slides_path=slides_path,
            chunks=chunks,
            book_path=book_path,
            selected_book_pages=selected_book_pages,
        )
        if plan is None:
            return client, None
        if plan.method != book_retrieval.METHOD_FULL:
            block_book_pages = plan.blocks
    if book_path and block_book_pages is None:
        runtime.phase("Fase 0/3: preparazione documenti")
        book_excerpt = _prepare_book_excerpt(
            session_ctx, book_path, selected_book_pages
        )
    print(
        f"[*] INIZIO FASE 1: Appunti a blocchi "
        f"({len(chunks)} blocchi da circa {session['notes']['slides_per_chunk']} slide)"
    )
    if blocks_done:
        print(f"[*] Ripresa dal blocco {blocks_done + 1}/{len(chunks)}.")
    runtime.phase("Fase 1/3: appunti")
    client, generated = process_notes_generation(
        client=client,
        source=NotesSource(
            slides_path=slides_path,
            total_slides=total_slides,
            chunks=chunks,
            book_excerpt_path=book_excerpt,
            book_pages_label=book_pages_label,
            book_path=book_path if block_book_pages is not None else None,
            block_book_pages=block_book_pages,
        ),
        model_name=settings.model,
        model_state=model_state,
        temperature=generation_service._phase1_temperature(settings.model),
        cancelled=runtime.cancelled,
        start_chunk_index=blocks_done,
        initial_full_text=full_text,
        initial_prev_memory=prev_memory,
        chunks_dir=session_ctx.phase1_chunks_dir,
        session=session,
        save_session=save_session,
        fallback_keys=fallback_keys,
        request_fallback_key=request_fallback_key,
        system_prompt=PROMPT_APPUNTI,
        runtime=runtime,
        on_model_switched=on_model_switched,
        logger=logger,
    )
    if generated is None:
        return client, None
    _update_session(
        session,
        {"stage": "phase2", "last_error": None, "last_error_detail": None},
    )
    save_session()
    return client, generated


def _remove_book_leftovers(session_dir: str) -> None:
    """Delete the book excerpt and the page index once the notes are done."""
    for leftover in (BOOK_EXCERPT_FILENAME, book_retrieval.INDEX_FILENAME):
        try:
            path = os.path.join(session_dir, leftover)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _build_notes_meta(
    slides_path: str,
    total_slides: int,
    slides_per_chunk: int | None,
    book_path: str | None,
    selected_book_pages: list[int],
    book_mode: str,
) -> dict:
    return {
        "slides_path": os.path.abspath(slides_path),
        "slides_name": os.path.basename(slides_path),
        "total_slides": int(total_slides),
        "slides_per_chunk": document_service.clamp_slides_per_chunk(
            slides_per_chunk or document_service.DEFAULT_SLIDES_PER_CHUNK
        ),
        "book_path": os.path.abspath(book_path) if book_path else None,
        "book_name": os.path.basename(book_path) if book_path else None,
        "book_pages": document_service.format_page_ranges(selected_book_pages),
        "book_pages_count": len(selected_book_pages),
        "book_mode": book_mode if book_path else None,
    }


def _esegui_appunti_impl(
    slides_path: str,
    api_key_value: str,
    app_instance,
    *,
    book_path: str | None = None,
    book_pages: str = "",
    slides_per_chunk: int | None = None,
    resume_session: bool = False,
    allow_completed_destroy: bool = False,
    book_mode: str | None = None,
    title: str | None = None,
    course: str | None = None,
):
    runtime = PipelineRuntime(app_instance)
    runtime.reset_temp_files()
    cancel_event = runtime.cancel_event
    log_handler = None
    logger = get_logger("jot.notes_pipeline")
    start_time = time.monotonic()
    fallback_keys = load_fallback_keys()

    session = None
    session_ctx = None
    client = None
    settings = None
    save_session = None
    regenerate_prompt_timeout_terminal = False
    book_path = str(book_path or "").strip() or None
    book_mode = book_retrieval.normalize_book_mode(book_mode)
    try:
        if not api_key_value or api_key_value.strip() == "":
            runtime.set_run_result("failed", "api_key_mancante")
            print("Errore: Formato API Key non valido o assente.")
            return

        validated = _validate_documents(slides_path, book_path, book_pages, runtime)
        if validated is None:
            return
        total_slides, selected_book_pages = validated

        client = create_gemini_client(api_key_value.strip())
        runtime.set_run_result("failed")
        runtime.set_effective_api_key(api_key_value.strip())

        session_ctx = initialize_session_context(
            slides_path,
            session_dir_hint=notes_session_dir(
                slides_path, book_path, book_pages, book_mode
            ),
            resume_session=resume_session,
            allow_completed_destroy=allow_completed_destroy,
        )
        session = session_ctx.session
        logger = get_logger(
            "jot.notes_pipeline",
            run_id=operation_id(session_ctx.session_dir),
            session_dir=session_ctx.session_dir,
            input_file=os.path.basename(slides_path),
        )
        log_handler = attach_file_handler(
            os.path.join(session_ctx.session_dir, "run.log")
        )
        logger.info("Appunti da slide avviati.", extra={"stage": "startup"})

        notes_meta = _build_notes_meta(
            slides_path,
            total_slides,
            slides_per_chunk,
            book_path,
            selected_book_pages,
            book_mode,
        )
        notes_meta.update(title=title or "", course=course or "")
        _apply_notes_metadata(session, notes_meta)
        session_ctx.save()

        def _on_autosave_fatal(msg: str) -> None:
            print(msg)
            runtime.console_error(msg)
            if isinstance(session, dict):
                session["last_error"] = "autosave_failed"
                session["last_error_detail"] = None

        save_session = SaveSessionGuard(session_ctx.save, _on_autosave_fatal)
        request_fallback_key = _make_fallback_key_requester(
            runtime, session, save_session
        )

        def on_model_switched(previous_model: str, new_model: str):
            assert session is not None
            session.setdefault("settings", {})
            session["settings"]["effective_model"] = new_model
            save_session()
            runtime.update_model(new_model)
            print(f"   [OK] Cambio modello automatico: {previous_model} -> {new_model}")

        settings = session_ctx.settings
        model_state = build_model_state(settings.model, settings.fallback_models)
        runtime.update_model(model_state.current)

        stage = normalize_stage(session)
        chunks = document_service.plan_slide_chunks(
            total_slides, session["notes"]["slides_per_chunk"]
        )
        existing_chunks = list_phase1_chunks(session_ctx.phase1_chunks_dir)
        if phase1_has_progress(session, stage, existing_chunks) and resume_session:
            status, stage, timeout_flag = _handle_regeneration_flow(
                slides_path,
                session_ctx,
                app_instance,
                runtime,
                stage,
                cancel_event,
                save_session,
                logger,
            )
            if timeout_flag:
                regenerate_prompt_timeout_terminal = True
            if status in ("timeout", "early_done"):
                return
            if status == "regenerated":
                session = session_ctx.session
                _apply_notes_metadata(session, notes_meta)
                session_ctx.save()
                settings = session_ctx.settings
                model_state = build_model_state(
                    settings.model, settings.fallback_models
                )
                runtime.update_model(model_state.current)
                chunks = document_service.plan_slide_chunks(
                    total_slides, session["notes"]["slides_per_chunk"]
                )
        if runtime.cancelled():
            return

        blocks_done, full_text, prev_memory = _restore_notes_progress(
            session_ctx, chunks
        )

        if stage == "phase1":
            client, full_text = _run_notes_phase1(
                client=client,
                session_ctx=session_ctx,
                session=session,
                save_session=save_session,
                settings=settings,
                model_state=model_state,
                runtime=runtime,
                slides_path=slides_path,
                total_slides=total_slides,
                chunks=chunks,
                book_path=book_path,
                selected_book_pages=selected_book_pages,
                book_pages_label=notes_meta["book_pages"],
                book_mode=book_mode,
                blocks_done=blocks_done,
                full_text=full_text,
                prev_memory=prev_memory,
                fallback_keys=fallback_keys,
                request_fallback_key=request_fallback_key,
                on_model_switched=on_model_switched,
                logger=logger,
            )
            if full_text is None:
                return

        client, revised_text, should_exit = _run_phase2_revision(
            client=client,
            model_name=settings.model,
            model_state=model_state,
            full_transcript=full_text,
            macro_path=session_ctx.macro_path,
            phase2_revised_dir=session_ctx.phase2_revised_dir,
            session=session,
            save_session=save_session,
            runtime=runtime,
            fallback_keys=fallback_keys,
            request_fallback_key=request_fallback_key,
            on_model_switched=on_model_switched,
            logger=logger,
            settings=settings,
            prompt_revisione=PROMPT_REVISIONE_APPUNTI,
        )
        if should_exit:
            return

        client = run_summary_step(
            client=client,
            session_ctx=session_ctx,
            session=session,
            save_session=save_session,
            model_name=settings.model,
            model_state=model_state,
            phase2_revised_dir=session_ctx.phase2_revised_dir,
            revised_text=revised_text,
            runtime=runtime,
            fallback_keys=fallback_keys,
            request_fallback_key=request_fallback_key,
            on_model_switched=on_model_switched,
            logger=logger,
        )

        if not _export_html_and_finish(
            input_path=slides_path,
            session_ctx=session_ctx,
            session=session,
            save_session=save_session,
            revised_text=revised_text,
            phase2_revised_dir=session_ctx.phase2_revised_dir,
            runtime=runtime,
            app_instance=app_instance,
            logger=logger,
            start_time=start_time,
            title=str(title or "").strip() or None,
        ):
            return

        _remove_book_leftovers(session_ctx.session_dir)

    except CircuitBreakerExhaustedError as e:
        _handle_circuit_breaker_paused(
            e, runtime, session, session_ctx, settings, save_session, logger
        )
    except AutosaveFailedError:
        runtime.set_run_result("failed", "autosave_failed")
    except Exception as e:
        runtime.set_run_result("failed", str(e))
        logger.exception("Errore imprevisto (appunti).", extra={"stage": "fatal"})
        print(f"\n[X] ERRORE IMPREVISTO DURANTE L'ESECUZIONE:\n{e}")
    finally:
        _pipeline_finally_cleanup(
            session_ctx,
            session,
            client,
            app_instance,
            runtime,
            log_handler,
            regenerate_prompt_timeout_terminal,
        )


def esegui_appunti(
    slides_path,
    api_key_value,
    app_instance,
    book_path=None,
    book_pages="",
    slides_per_chunk=None,
    resume_session=False,
    allow_completed_destroy=False,
    book_mode=None,
    title=None,
    course=None,
):
    """Public entry point, mirrors esegui_sbobinatura.

    book_mode: "auto" sends only the book pages relevant to each block of
    slides; "full"/None sends the whole selected excerpt (legacy).
    """
    return _esegui_appunti_impl(
        slides_path,
        api_key_value,
        app_instance,
        book_path=book_path,
        book_pages=book_pages,
        slides_per_chunk=slides_per_chunk,
        resume_session=resume_session,
        allow_completed_destroy=allow_completed_destroy,
        book_mode=book_mode,
        title=title,
        course=course,
    )
