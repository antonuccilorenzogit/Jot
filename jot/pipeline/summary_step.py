"""
Last step of every lesson: the "sintesi" (one Gemini request).

It never fails the lesson: when something goes wrong the notes are still
exported and the console says why.
"""

from __future__ import annotations

import os
import re
from datetime import date

from jot.core.prompts import PROMPT_SINTESI
from jot.core.shared import _atomic_write_text
from jot.services.export_service import load_revised_blocks
from jot.utils.html_export import build_html_document

SUMMARY_MD = "sintesi.md"
SUMMARY_HTML = "sintesi.html"
PHASE_TEXT = "Sintesi della lezione"
_TIME_MARK_RE = re.compile(r"\[\[\s*t\s*=\s*[\d:]+\s*\]\]\s*")


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def lesson_markdown(phase2_revised_dir: str, fallback: str) -> str:
    try:
        blocks = load_revised_blocks(phase2_revised_dir, _read_text)
    except Exception:
        blocks = []
    text = "\n\n".join(b.strip() for b in blocks if b and b.strip())
    return _TIME_MARK_RE.sub("", text or str(fallback or ""))


def summary_heading(session: dict, today: date | None = None) -> str:
    title = str(session.get("custom_title") or session.get("title") or "").strip()
    if not title:
        source = (session.get("input") or {}).get("path") or ""
        title = os.path.splitext(os.path.basename(str(source)))[0]
    course = str(session.get("course") or "").strip()
    day = (today or date.today()).strftime("%d/%m/%Y")
    parts = [course] if course else []
    if title and title.lower() != course.lower():
        parts.append(title)
    return " · ".join(["Sintesi", *parts, day])


def ensure_heading(summary: str, heading: str) -> str:
    lines = summary.strip().split("\n")
    if lines and lines[0].lstrip().startswith("# "):
        lines[0] = f"# {heading}"
        return "\n".join(lines)
    return f"# {heading}\n\n" + summary.strip()


def generate_summary(
    *,
    client,
    notes: str,
    heading: str,
    model_name: str,
    model_state,
    fallback_keys: list[str],
    request_fallback_key,
    runtime,
    on_model_switched=None,
    logger=None,
):
    """One Gemini request: the lesson notes in, the "sintesi" out."""
    from google.genai import types

    from jot.services.generation_service import (
        current_model_name,
        extract_response_text,
        retry_with_quota,
    )

    system_prompt = PROMPT_SINTESI.replace("{intestazione}", heading)

    def _call(current_client):
        response = current_client.models.generate_content(
            model=current_model_name(model_state, model_name),
            contents=[f"APPUNTI DELLA LEZIONE:\n\n{notes}"],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt, temperature=0.3
            ),
        )
        text = extract_response_text(response)
        if not text or len(text.strip()) < 200:
            raise RuntimeError("Sintesi vuota o troppo corta.")
        return text.strip()

    return retry_with_quota(
        _call,
        client=client,
        fallback_keys=fallback_keys,
        model_name=model_name,
        model_state=model_state,
        cancelled=runtime.cancelled,
        runtime=runtime,
        request_fallback_key=request_fallback_key,
        on_model_switched=on_model_switched,
        logger=logger,
        resume_phase_text=PHASE_TEXT,
    )


def run_summary_step(
    *,
    client,
    session_ctx,
    session: dict,
    save_session,
    model_name: str,
    model_state,
    phase2_revised_dir: str,
    revised_text: str,
    runtime,
    fallback_keys: list[str],
    request_fallback_key,
    on_model_switched=None,
    logger=None,
):
    """Write sintesi.html in the session folder. Returns the (possibly rotated) client."""
    if runtime.cancelled():
        return client
    try:
        notes = lesson_markdown(phase2_revised_dir, revised_text).strip()
        if not notes:
            return client
        heading = summary_heading(session)
        cached = os.path.join(session_ctx.session_dir, SUMMARY_MD)
        summary = ""
        if os.path.isfile(cached):  # resumed lesson: no new request
            summary = _read_text(cached).strip()
        if not summary:
            runtime.phase(PHASE_TEXT)
            print("\n[*] Sintesi della lezione in corso...")
            client, text = generate_summary(
                client=client,
                notes=notes,
                heading=heading,
                model_name=model_name,
                model_state=model_state,
                fallback_keys=fallback_keys,
                request_fallback_key=request_fallback_key,
                runtime=runtime,
                on_model_switched=on_model_switched,
                logger=logger,
            )
            summary = text.strip() if isinstance(text, str) else ""
            if not summary:
                return client
            _atomic_write_text(cached, summary + "\n")
        summary = ensure_heading(summary, heading)
        path = os.path.join(session_ctx.session_dir, SUMMARY_HTML)
        _atomic_write_text(path, build_html_document(heading, summary))
        session.setdefault("outputs", {})["summary_html"] = path
        save_session()
        print(
            "[OK] Sintesi pronta: la trovi in Archivio, menu della lezione > Apri sintesi."
        )
    except Exception as exc:  # the lesson itself is fine: only report
        print(f"[!] Sintesi non creata: {exc}")
        if logger is not None:
            logger.warning("Summary step failed: %s", exc, extra={"stage": "summary"})
    return client
