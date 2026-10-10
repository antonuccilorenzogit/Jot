"""
Revision helpers extracted from the main pipeline.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google.genai import types

from jot.core.model_registry import ModelState
from jot.core.session_store import _update_session
from jot.core.shared import _atomic_write_text
from jot.pipeline.pipeline_session import record_step_metric
from jot.services import usage_service
from jot.services.gemini_errors import DegenerateOutputError
from jot.services.generation_service import (
    QuotaDailyLimitError,
    create_gemini_client,
    current_model_name,
    extract_response_text,
    retry_with_quota,
    sleep_with_cancel,
)
from jot.services.lesson_context import (
    REVISION_MIN_LENGTH_RATIO,
    book_revision_note,
)
from jot.utils.dedup_utils import local_macro_cleanup
from jot.utils.logging_utils import get_logger


@dataclass(slots=True)
class MacroBlockProcessResult:
    """Result of processing a single macro block in Phase 2."""

    client: Any
    appended_text: str | None
    revised_done: int
    pending_retry: tuple[int, str, str] | None = None
    should_abort: bool = False


def _normalize_block_indexes(value) -> list[int]:
    indexes: list[int] = []
    seen: set[int] = set()
    if not isinstance(value, list | tuple | set):
        return indexes
    for item in value:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if idx <= 0 or idx in seen:
            continue
        seen.add(idx)
        indexes.append(idx)
    indexes.sort()
    return indexes


def build_macro_blocks(text: str, macro_char_limit: int) -> list[str]:
    paragraphs = text.split("\n\n")
    blocks: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    _h_re = re.compile(r"^\s*#{1,3}\s+\S")
    for paragraph in paragraphs:
        seg = paragraph + "\n\n"
        is_h = bool(_h_re.match(paragraph))
        past_soft = current_len > macro_char_limit * 0.70
        has_content = current_len > 500
        if current_len + len(paragraph) > macro_char_limit and current_parts:
            blocks.append("".join(current_parts))
            current_parts = [seg]
            current_len = len(seg)
        elif is_h and past_soft and has_content and current_parts:
            blocks.append("".join(current_parts))
            current_parts = [seg]
            current_len = len(seg)
        else:
            current_parts.append(seg)
            current_len += len(seg)
    if current_parts:
        joined = "".join(current_parts)
        if joined.strip():
            blocks.append(joined)
    return blocks


def _revise_single_macro_block(
    *,
    client,
    block_text: str,
    prompt_revisione: str,
    book_context=None,
    model_name: str,
    model_state: ModelState | None,
    fallback_keys: list[str],
    request_fallback_key: Callable[[], str | None],
    runtime,
    cancelled: Callable[[], bool],
    on_model_switched=None,
    logger=None,
    resume_phase_text: str,
) -> tuple[object, str | None]:
    """Call Gemini to revise a single text macro block."""
    book = None
    if book_context is not None:
        try:
            book = book_context.for_block(block_text, client)
        except Exception as exc:
            print(
                f"   [!] Pagine del libro non disponibili ({exc}): revisione senza libro."
            )
            book = None

    def _call(current_client):
        contents: list = [block_text]
        if book is not None:
            contents = [
                types.Part.from_bytes(data=book.pdf_bytes, mime_type="application/pdf"),
                book_revision_note(book.label),
                block_text,
            ]
        response = current_client.models.generate_content(
            model=current_model_name(model_state, model_name),
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=prompt_revisione,
                temperature=0.1,
            ),
        )
        current_text = extract_response_text(response)
        if not current_text:
            raise RuntimeError("Risposta vuota dal modello in revisione.")
        if book is not None and len(
            current_text.strip()
        ) < REVISION_MIN_LENGTH_RATIO * len(block_text.strip()):
            raise DegenerateOutputError(
                "revisione con il libro troppo corta: contenuto perso", current_text
            )
        return current_text

    return retry_with_quota(
        _call,
        client=client,
        fallback_keys=fallback_keys,
        model_name=model_name,
        model_state=model_state,
        cancelled=cancelled,
        runtime=runtime,
        request_fallback_key=request_fallback_key,
        retry_sleep_seconds=20.0,
        on_model_switched=on_model_switched,
        logger=logger,
        resume_phase_text=resume_phase_text,
    )


def _run_macro_retry_pass(
    *,
    client,
    pending_retry: list[tuple[int, str, str]],
    macro_total: int,
    revised_done: int,
    session: dict,
    save_session: Callable[[], bool],
    runtime,
    cancelled: Callable[[], bool],
    fallback_keys: list[str],
    request_fallback_key: Callable[[], str | None],
    prompt_revisione: str,
    book_context=None,
    model_name: str,
    model_state: ModelState | None,
    on_model_switched=None,
    logger=None,
) -> tuple[object, list[int], int, bool]:
    """Run second-attempt revision on provisionally failed macro blocks."""
    failed_blocks: list[int] = []
    if not pending_retry:
        return client, failed_blocks, revised_done, False

    print(
        f"\n[*] Retry pass: {len(pending_retry)} blocco/i senza revisione. Riprovo..."
    )
    _update_session(
        session, {"revision_pending_blocks": [idx for idx, _, _ in pending_retry]}
    )
    save_session()

    for index, raw_path, rev_path in pending_retry:
        if cancelled():
            print("   [*] Operazione annullata dall'utente (retry pass).")
            return client, failed_blocks, revised_done, True

        try:
            with open(raw_path, encoding="utf-8") as _fh:
                block_src = _fh.read().rstrip("\n")
        except Exception:
            block_src = ""

        if not block_src:
            _atomic_write_text(rev_path, "")
            try:
                os.remove(raw_path)
            except Exception:
                pass
            revised_done += 1
            _update_session(
                session,
                {
                    "stage": "phase2",
                    "phase2": {
                        **session.get("phase2", {}),
                        "revised_done": int(revised_done),
                    },
                },
            )
            save_session()
            failed_blocks.append(index)
            continue

        block_local, _, _, _, _ = local_macro_cleanup(block_src)
        block_for_ai_retry = (block_local or block_src).strip()

        runtime.phase(f"Fase 2/3: retry revisione (blocco {index}/{macro_total})")
        print(f"   -> Retry revisione blocco {index}/{macro_total}...")
        step_t0 = time.monotonic()
        retry_success = False

        try:
            client, current_text = _revise_single_macro_block(
                client=client,
                block_text=block_for_ai_retry,
                prompt_revisione=prompt_revisione,
                book_context=book_context,
                model_name=model_name,
                model_state=model_state,
                fallback_keys=fallback_keys,
                request_fallback_key=request_fallback_key,
                runtime=runtime,
                cancelled=cancelled,
                on_model_switched=on_model_switched,
                logger=logger,
                resume_phase_text=f"Fase 2/3: retry revisione (blocco {index}/{macro_total})",
            )
            if current_text is None:
                return client, failed_blocks, revised_done, True
            _atomic_write_text(rev_path, current_text + "\n")
            try:
                os.remove(raw_path)
            except Exception:
                pass
            print(f"   [OK] Retry blocco {index}: revisione completata.")
            retry_success = True
            revised_done += 1
            _update_session(
                session,
                {
                    "stage": "phase2",
                    "phase2": {
                        **session.get("phase2", {}),
                        "revised_done": int(revised_done),
                    },
                    "last_error": None,
                    "last_error_detail": None,
                },
            )
            save_session()
            usage_service.record_work_completed("revisions", 1)
            _macro_secs = max(0.0, time.monotonic() - float(step_t0))
            record_step_metric(
                session, "macro", _macro_secs, done=revised_done, total=macro_total
            )
        except QuotaDailyLimitError:
            print("   Interruzione: quota giornaliera raggiunta durante retry pass.")
            session["last_error"] = "quota_daily_limit_phase2"
            if session.get("last_error_detail") != "api_key_prompt_timeout":
                session["last_error_detail"] = None
            save_session()
            return client, failed_blocks, revised_done, True
        except Exception as exc:
            if logger is not None:
                logger.warning(
                    "Retry revisione blocco %d/%d fallita: %s",
                    index,
                    macro_total,
                    exc,
                    extra={"stage": "phase2"},
                )

        if not retry_success:
            print(
                f"   [!!] Blocco {index}: revisione definitivamente fallita. Incluso non revisionato."
            )
            try:
                with open(raw_path, encoding="utf-8") as _fh:
                    _raw_content = _fh.read().rstrip("\n")
                _atomic_write_text(rev_path, _raw_content + "\n")
            except Exception:
                _atomic_write_text(rev_path, block_src + "\n")
            failed_blocks.append(index)
            revised_done += 1
            _update_session(
                session,
                {
                    "stage": "phase2",
                    "phase2": {
                        **session.get("phase2", {}),
                        "revised_done": int(revised_done),
                    },
                },
            )
            save_session()
            _macro_secs = max(0.0, time.monotonic() - float(step_t0))
            record_step_metric(
                session, "macro", _macro_secs, done=revised_done, total=macro_total
            )

        runtime.progress(0.7 + 0.2 * (revised_done / max(1, macro_total)))

    return client, failed_blocks, revised_done, False


def _process_macro_block_item(
    *,
    index: int,
    block: str,
    macro_total: int,
    revised_done: int,
    phase2_revised_dir: str,
    client,
    model_name: str,
    model_state: ModelState | None,
    prompt_revisione: str,
    book_context=None,
    fallback_keys: list[str],
    request_fallback_key: Callable[[], str | None],
    session: dict,
    save_session: Callable[[], bool],
    runtime,
    cancelled: Callable[[], bool],
    on_model_switched=None,
    logger=None,
) -> MacroBlockProcessResult:
    """Process a single macro block in Phase 2."""
    runtime.phase(f"Fase 2/3: revisione ({index}/{macro_total})")
    rev_path = os.path.join(phase2_revised_dir, f"rev_{index:03}.md")
    raw_path = os.path.join(phase2_revised_dir, f"rev_{index:03}.raw.md")

    if os.path.exists(rev_path):
        try:
            with open(rev_path, encoding="utf-8") as _fh:
                existing = _fh.read().strip()
        except Exception:
            existing = ""
        if existing:
            new_revised_done = revised_done + 1
            runtime.update_work_done("macro", new_revised_done, total=macro_total)
            _update_session(
                session,
                {
                    "stage": "phase2",
                    "phase2": {
                        **session.get("phase2", {}),
                        "revised_done": int(new_revised_done),
                    },
                    "last_error": None,
                    "last_error_detail": None,
                },
            )
            save_session()
            runtime.progress(0.7 + 0.2 * (new_revised_done / max(1, macro_total)))
            return MacroBlockProcessResult(
                client=client,
                appended_text=f"\n\n{existing}\n\n",
                revised_done=new_revised_done,
            )

    if os.path.exists(raw_path):
        return MacroBlockProcessResult(
            client=client,
            appended_text=None,
            revised_done=revised_done,
            pending_retry=(index, raw_path, rev_path),
        )

    block_src = (block or "").strip()
    block_local, removed_exact, removed_adj, _, _ = local_macro_cleanup(block_src)
    block_for_ai = (block_local or block_src).strip()
    if removed_exact or removed_adj:
        print(
            f"   -> Pre-clean locale ({index}/{macro_total}): {removed_exact + removed_adj} duplicati rimossi."
        )

    step_t0 = time.monotonic()
    print(f"   -> Revisione Macro-blocco {index}/{macro_total}...")
    success = False

    try:
        client, current_text = _revise_single_macro_block(
            client=client,
            block_text=block_for_ai,
            prompt_revisione=prompt_revisione,
            book_context=book_context,
            model_name=model_name,
            model_state=model_state,
            fallback_keys=fallback_keys,
            request_fallback_key=request_fallback_key,
            runtime=runtime,
            cancelled=cancelled,
            on_model_switched=on_model_switched,
            logger=logger,
            resume_phase_text=f"Fase 2/3: revisione ({index}/{macro_total})",
        )
        if current_text is None:
            return MacroBlockProcessResult(
                client=client,
                appended_text=None,
                revised_done=revised_done,
                should_abort=True,
            )

        _atomic_write_text(rev_path, current_text + "\n")
        print(f"   [autosave] Revisione salvata: {os.path.basename(rev_path)}")

        new_revised_done = revised_done + 1
        _update_session(
            session,
            {
                "stage": "phase2",
                "phase2": {
                    **session.get("phase2", {}),
                    "revised_done": int(new_revised_done),
                },
                "last_error": None,
                "last_error_detail": None,
            },
        )
        save_session()
        usage_service.record_work_completed("revisions", 1)

        success = True
        runtime.progress(0.7 + 0.2 * (new_revised_done / max(1, macro_total)))
        _macro_secs = max(0.0, time.monotonic() - float(step_t0))
        record_step_metric(
            session, "macro", _macro_secs, done=new_revised_done, total=macro_total
        )
        return MacroBlockProcessResult(
            client=client,
            appended_text=f"\n\n{current_text}\n\n",
            revised_done=new_revised_done,
        )

    except QuotaDailyLimitError:
        print("   Interruzione: progressi salvati. Potrai riprendere più tardi.")
        session["last_error"] = "quota_daily_limit_phase2"
        if session.get("last_error_detail") != "api_key_prompt_timeout":
            session["last_error_detail"] = None
        save_session()
        return MacroBlockProcessResult(
            client=client,
            appended_text=None,
            revised_done=revised_done,
            should_abort=True,
        )

    except Exception as exc:
        if logger is not None:
            logger.warning(
                "Errore revisione blocco %d/%d: %s",
                index,
                macro_total,
                exc,
                extra={"stage": "phase2"},
            )

    if not success:
        print(
            f"   [!] Revisione blocco {index} fallita. Salvo provvisoriamente come raw (sarà riprovato)."
        )
        _atomic_write_text(raw_path, block_src + "\n")
        _macro_secs = max(0.0, time.monotonic() - float(step_t0))
        record_step_metric(
            session, "macro", _macro_secs, done=revised_done, total=macro_total
        )
        runtime.progress(0.7 + 0.2 * (revised_done / max(1, macro_total)))
        return MacroBlockProcessResult(
            client=client,
            appended_text=None,
            revised_done=revised_done,
            pending_retry=(index, raw_path, rev_path),
        )

    return MacroBlockProcessResult(
        client=client, appended_text=None, revised_done=revised_done
    )


def process_macro_revision_phase(
    *,
    client,
    model_name: str,
    model_state: ModelState | None = None,
    macro_blocks: list[str],
    phase2_revised_dir: str,
    session: dict,
    save_session: Callable[[], bool],
    runtime,
    cancelled: Callable[[], bool],
    fallback_keys: list[str],
    request_fallback_key: Callable[[], str | None],
    prompt_revisione: str,
    book_context=None,
    on_model_switched=None,
    logger=None,
) -> tuple[object, str]:
    log = logger or get_logger("jot.revision", stage="phase2")
    revised_text = ""
    macro_total = len(macro_blocks)
    revised_done = 0
    pending_retry: list[tuple[int, str, str]] = []

    runtime.set_work_totals(macro_total=macro_total)
    try:
        initial_macro_done = int(session.get("phase2", {}).get("revised_done", 0) or 0)
        runtime.update_work_done(
            "macro",
            initial_macro_done,
            total=macro_total,
        )
        if initial_macro_done > 0 and macro_total > 0:
            runtime.progress(0.7 + 0.2 * (initial_macro_done / max(1, macro_total)))
    except Exception:
        pass

    for index, block in enumerate(macro_blocks, 1):
        if cancelled():
            print("   [*] Operazione annullata dall'utente.")
            return client, revised_text

        res = _process_macro_block_item(
            index=index,
            block=block,
            macro_total=macro_total,
            revised_done=revised_done,
            phase2_revised_dir=phase2_revised_dir,
            client=client,
            model_name=model_name,
            model_state=model_state,
            prompt_revisione=prompt_revisione,
            book_context=book_context,
            fallback_keys=fallback_keys,
            request_fallback_key=request_fallback_key,
            session=session,
            save_session=save_session,
            runtime=runtime,
            cancelled=cancelled,
            on_model_switched=on_model_switched,
            logger=log,
        )
        client = res.client
        revised_done = res.revised_done
        if res.appended_text:
            revised_text += res.appended_text
        if res.pending_retry is not None:
            pending_retry.append(res.pending_retry)
        if res.should_abort:
            return client, revised_text

        if not sleep_with_cancel(cancelled, 5):
            print("   [*] Operazione annullata dall'utente.")
            return client, revised_text

    # ---- RETRY PASS: second attempt on provisionally-failed blocks ----
    client, failed_blocks, revised_done, aborted = _run_macro_retry_pass(
        client=client,
        pending_retry=pending_retry,
        macro_total=macro_total,
        revised_done=revised_done,
        session=session,
        save_session=save_session,
        runtime=runtime,
        cancelled=cancelled,
        fallback_keys=fallback_keys,
        request_fallback_key=request_fallback_key,
        prompt_revisione=prompt_revisione,
        book_context=book_context,
        model_name=model_name,
        model_state=model_state,
        on_model_switched=on_model_switched,
        logger=log,
    )
    if aborted:
        return client, revised_text

    if failed_blocks:
        print(
            f"\n[!!] ATTENZIONE: i seguenti blocchi sono stati inclusi non revisionati: {failed_blocks}"
        )

    session_update: dict = {
        "revision_pending_blocks": [],
        "revision_failed_blocks": failed_blocks,
        "completion_status": "completed_with_warnings"
        if failed_blocks
        else "completed",
    }
    if not failed_blocks:
        session_update["last_error"] = None
        session_update["last_error_detail"] = None
    _update_session(session, session_update)
    save_session()

    # Rebuild revised_text from all final .md files (authoritative source of truth)
    revised_text = ""
    for idx in range(1, macro_total + 1):
        rpath = os.path.join(phase2_revised_dir, f"rev_{idx:03}.md")
        if os.path.exists(rpath):
            try:
                with open(rpath, encoding="utf-8") as _fh:
                    content = _fh.read().strip()
                if content:
                    revised_text += f"\n\n{content}\n\n"
            except Exception:
                pass

    return client, revised_text


def retry_failed_revision_blocks(
    *,
    client,
    model_name: str,
    model_state: ModelState | None = None,
    phase2_revised_dir: str,
    session: dict,
    save_session: Callable[[], bool],
    runtime,
    cancelled: Callable[[], bool],
    fallback_keys: list[str],
    request_fallback_key: Callable[[], str | None],
    prompt_revisione: str,
    book_context=None,
    on_model_switched=None,
    logger=None,
) -> tuple[object, dict]:
    """Retry only blocks previously shipped as unrevised raw markdown.

    The normal pipeline deliberately keeps ``rev_NNN.raw.md`` for failed blocks
    after this fix. For older sessions that only have ``rev_NNN.md``, we fall
    back to that file so users still have a recovery path.
    """

    log = logger or get_logger("jot.revision_retry", stage="phase2")
    failed_blocks = _normalize_block_indexes(session.get("revision_failed_blocks"))
    if not failed_blocks:
        return client, {
            "retried_blocks": [],
            "failed_blocks": [],
            "cancelled": False,
            "quota_exhausted": False,
        }

    try:
        macro_total = int(session.get("phase2", {}).get("macro_total", 0) or 0)
    except (TypeError, ValueError):
        macro_total = 0
    macro_total = max(macro_total, max(failed_blocks))

    retried_blocks: list[int] = []
    remaining_blocks: list[int] = []
    was_cancelled = False
    quota_exhausted = False

    try:
        runtime.set_work_totals(macro_total=macro_total)
    except Exception:
        pass

    for position, index in enumerate(failed_blocks, 1):
        if cancelled():
            was_cancelled = True
            remaining_blocks.extend(failed_blocks[position - 1 :])
            break

        raw_path = os.path.join(phase2_revised_dir, f"rev_{index:03}.raw.md")
        rev_path = os.path.join(phase2_revised_dir, f"rev_{index:03}.md")
        source_path = raw_path if os.path.exists(raw_path) else rev_path
        try:
            with open(source_path, encoding="utf-8") as _fh:
                block_src = _fh.read().rstrip("\n")
        except Exception:
            block_src = ""

        if not block_src.strip():
            remaining_blocks.append(index)
            continue

        block_local, _removed_exact, _removed_adj, _near_adj, _ = local_macro_cleanup(
            block_src
        )
        block_for_ai_retry = (block_local or block_src).strip()

        try:
            runtime.phase(
                f"Fase 2/3: retry blocchi mancanti ({position}/{len(failed_blocks)})"
            )
            runtime.progress(float(position - 1) / max(1, len(failed_blocks)))
            runtime.update_work_done("macro", position - 1, total=len(failed_blocks))
        except Exception:
            pass
        log.info(
            "Retry blocco non revisionato %d/%d.",
            index,
            macro_total,
            extra={"stage": "phase2_retry_failed_blocks"},
        )

        try:
            client, current_text = _revise_single_macro_block(
                client=client,
                block_text=block_for_ai_retry,
                prompt_revisione=prompt_revisione,
                book_context=book_context,
                model_name=model_name,
                model_state=model_state,
                fallback_keys=fallback_keys,
                request_fallback_key=request_fallback_key,
                runtime=runtime,
                cancelled=cancelled,
                on_model_switched=on_model_switched,
                logger=log,
                resume_phase_text=f"Fase 2/3: retry blocchi mancanti ({position}/{len(failed_blocks)})",
            )
            if current_text is None:
                if cancelled():
                    was_cancelled = True
                remaining_blocks.append(index)
                remaining_blocks.extend(failed_blocks[position:])
                break
            _atomic_write_text(rev_path, current_text + "\n")
            try:
                if os.path.exists(raw_path):
                    os.remove(raw_path)
            except Exception:
                pass
            retried_blocks.append(index)
            try:
                runtime.progress(float(position) / max(1, len(failed_blocks)))
                runtime.update_work_done("macro", position, total=len(failed_blocks))
            except Exception:
                pass
            log.info(
                "Blocco %d: revisione recuperata.",
                index,
                extra={"stage": "phase2_retry_failed_blocks"},
            )
        except QuotaDailyLimitError:
            quota_exhausted = True
            session["last_error"] = "quota_daily_limit_phase2"
            if session.get("last_error_detail") != "api_key_prompt_timeout":
                session["last_error_detail"] = None
            remaining_blocks.append(index)
            remaining_blocks.extend(failed_blocks[position:])
            save_session()
            break
        except Exception as exc:
            log.warning(
                "Retry manuale blocco %d/%d fallito: %s",
                index,
                macro_total,
                exc,
                extra={"stage": "phase2_retry_failed_blocks"},
            )
            remaining_blocks.append(index)

    try:
        if not remaining_blocks:
            runtime.progress(1.0)
            runtime.update_work_done(
                "macro", len(failed_blocks), total=len(failed_blocks)
            )
    except Exception:
        pass

    session_update = {
        "revision_failed_blocks": remaining_blocks,
        "revision_pending_blocks": [],
        "completion_status": "completed_with_warnings"
        if remaining_blocks
        else "completed",
    }
    if not remaining_blocks:
        session_update["last_error"] = None
        session_update["last_error_detail"] = None
    _update_session(session, session_update)
    save_session()

    return client, {
        "retried_blocks": retried_blocks,
        "failed_blocks": remaining_blocks,
        "cancelled": was_cancelled,
        "quota_exhausted": quota_exhausted,
    }


def _retry_revision_setup(session: dict, session_dir: str, base_prompt: str):
    """Book rules and pages for retries of an audio lesson with a book."""
    from jot.core.prompts import PROMPT_REGOLE_LIBRO_REVISIONE
    from jot.services import document_service
    from jot.services.lesson_context import RevisionBookContext

    lesson = session.get("lesson") if isinstance(session, dict) else None
    book_path = str((lesson or {}).get("book_path") or "").strip()
    if not book_path or not os.path.isfile(book_path):
        return base_prompt, None
    try:
        _total, pages = document_service.validate_book(
            book_path, str((lesson or {}).get("book_pages") or "")
        )
    except Exception:
        return base_prompt, None
    return base_prompt + PROMPT_REGOLE_LIBRO_REVISIONE, RevisionBookContext(
        book_path=book_path, allowed_pages=pages, cache_dir=session_dir
    )


def execute_failed_blocks_retry_workflow(
    *,
    session: dict,
    session_path: str,
    session_dir: str,
    api_key: str,
    runtime,
    retry_cancel_event,
    on_push_completion_status: Callable[[list[int], bool, bool], None] | None = None,
) -> dict:
    """Orchestrate the end-to-end failed revision blocks retry workflow."""
    from google import genai

    from jot.core.model_registry import build_model_state
    from jot.core.prompts import PROMPT_REVISIONE, PROMPT_REVISIONE_APPUNTI
    from jot.core.session_store import (
        mark_html_exported,
    )
    from jot.core.session_store import (
        save_session as save_session_file,
    )
    from jot.core.shared import (
        DEFAULT_MODEL,
        invalidate_session_storage_cache,
    )
    from jot.pipeline.pipeline_session import read_text_file
    from jot.services import export_service, generation_service
    from jot.services.config_service import load_config, safe_output_basename
    from jot.utils.file_ops import evict_html_paths_under

    cfg = load_config()
    settings = session.get("settings", {}) if isinstance(session, dict) else {}
    primary_model = str(
        settings.get("model") or cfg.get("preferred_model") or DEFAULT_MODEL
    ).strip()
    fallback_models = settings.get("fallback_models") or cfg.get("fallback_models", [])
    model_state = build_model_state(primary_model, fallback_models)
    client = generation_service.create_gemini_client(api_key)
    fallback_keys = generation_service.load_fallback_keys()

    def _save_session() -> bool:
        try:
            save_session_file(session_path, session)
            return True
        except Exception:
            return False

    def _request_fallback_key() -> str | None:
        key = generation_service.request_new_api_key(runtime, runtime.cancelled)
        if not key or not str(key).strip():
            retry_cancel_event.set()
        return key

    def _on_model_switched(_old: str, new: str) -> None:
        session.setdefault("settings", {})
        session["settings"]["effective_model"] = new
        _save_session()

    phase2_revised_dir = os.path.join(session_dir, "phase2_revised")
    prompt_revisione, book_context = _retry_revision_setup(
        session,
        session_dir,
        PROMPT_REVISIONE_APPUNTI
        if isinstance(session, dict) and session.get("kind") == "notes"
        else PROMPT_REVISIONE,
    )
    client, retry_result = retry_failed_revision_blocks(
        client=client,
        model_name=primary_model,
        model_state=model_state,
        phase2_revised_dir=phase2_revised_dir,
        session=session,
        save_session=_save_session,
        runtime=runtime,
        cancelled=runtime.cancelled,
        fallback_keys=fallback_keys,
        request_fallback_key=_request_fallback_key,
        prompt_revisione=prompt_revisione,
        book_context=book_context,
        on_model_switched=_on_model_switched,
    )

    retried_blocks = list(retry_result.get("retried_blocks", []))
    remaining = list(retry_result.get("failed_blocks", []))
    cancelled = bool(retry_result.get("cancelled"))
    quota_exhausted = bool(retry_result.get("quota_exhausted"))

    from jot.bridge.bridge_utils import _retry_zero_retried_response

    zero_response = _retry_zero_retried_response(
        retried_blocks=retried_blocks,
        remaining=remaining,
        cancelled=cancelled,
        quota_exhausted=quota_exhausted,
        session_dir=session_dir,
        html_path=str(session.get("outputs", {}).get("html", "") or ""),
    )
    if zero_response is not None:
        return zero_response

    input_path = str(session.get("input", {}).get("path", "") or "")
    _title, html_path = export_service.export_final_html_document(
        input_path=input_path,
        phase2_revised_dir=phase2_revised_dir,
        fallback_body="",
        read_text=read_text_file,
        output_dir=session_dir,
        fallback_output_dir=session_dir,
        safe_output_basename=safe_output_basename,
        revision_failed_blocks=remaining,
        title=str(session.get("custom_title") or "").strip() or None,
    )
    session.setdefault("outputs", {})
    session["outputs"]["html"] = html_path
    session.setdefault("settings", {})
    session["settings"]["effective_model"] = model_state.current
    mark_html_exported(session)
    _save_session()
    invalidate_session_storage_cache()
    evict_html_paths_under(session_dir + os.sep)

    if on_push_completion_status is not None:
        on_push_completion_status(remaining, cancelled, quota_exhausted)

    return {
        "ok": True,
        "retried_blocks": retried_blocks,
        "remaining_failed_blocks": remaining,
        "completion_status": "completed_with_warnings" if remaining else "completed",
        "html_path": html_path,
        "session_dir": session_dir,
        "effective_model": model_state.current,
        "cancelled": cancelled,
        "quota_exhausted": quota_exhausted,
    }
