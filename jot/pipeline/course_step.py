"""
Last step of every lesson: the "sintesi" (one Gemini request) and the copies
in the course folder (Lezioni / Sintesi). It never fails the lesson: when
something goes wrong the notes are still exported and the console says why.
"""

from __future__ import annotations

import html
import os

from jot.core.shared import _atomic_write_text
from jot.services import course_outputs as co
from jot.services.export_service import load_revised_blocks
from jot.utils.html_export import build_html_document

SUMMARY_MD = "sintesi.md"
SUMMARY_HTML = "sintesi.html"


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _lesson_markdown(phase2_revised_dir: str, fallback: str) -> str:
    try:
        blocks = load_revised_blocks(phase2_revised_dir, _read_text)
    except Exception:
        blocks = []
    text = "\n\n".join(b.strip() for b in blocks if b and b.strip())
    return text or str(fallback or "")


def _remove_if_moved(old: str | None, new: str) -> None:
    if old and os.path.normcase(old) != os.path.normcase(new) and os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass


def _summary_text(*, session_dir: str, generate) -> str | None:
    """Reuse the summary of a resumed session, otherwise ask Gemini."""
    cached = os.path.join(session_dir, SUMMARY_MD)
    if os.path.isfile(cached):
        try:
            text = _read_text(cached).strip()
            if text:
                return text
        except OSError:
            pass
    text = generate()
    if text:
        _atomic_write_text(cached, text + "\n")
    return text


def run_course_step(
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
    """Write L/S files for the lesson. Returns the (possibly rotated) client."""
    if runtime.cancelled():
        return client
    holder = {"client": client}
    try:
        _publish(
            holder=holder,
            session_ctx=session_ctx,
            session=session,
            save_session=save_session,
            model_name=model_name,
            model_state=model_state,
            phase2_revised_dir=phase2_revised_dir,
            revised_text=revised_text,
            runtime=runtime,
            fallback_keys=fallback_keys,
            request_fallback_key=request_fallback_key,
            on_model_switched=on_model_switched,
            logger=logger,
        )
    except Exception as exc:  # the lesson itself is fine: only report
        print(f"[!] Sintesi o cartella del corso non create: {exc}")
        if logger is not None:
            logger.warning("Course step failed: %s", exc, extra={"stage": "course"})
    return holder["client"]


def _publish(
    *,
    holder: dict,
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
    on_model_switched,
    logger,
) -> None:
    from jot.services.config_service import load_config

    lesson_md = _lesson_markdown(phase2_revised_dir, revised_text)
    if not lesson_md.strip():
        return
    course = str(session.get("course") or "").strip()
    title = str(session.get("custom_title") or session.get("title") or "").strip()
    day = co.parse_lesson_date(session.get("lesson_date"))
    paths = co.course_paths(course or None, co.course_root(load_config()))
    stored = session.get("course_output")
    previous: dict = stored if isinstance(stored, dict) else {}
    number = int(previous.get("number") or co.next_lesson_number(paths.lessons))
    heading = co.summary_heading(course or title or co.NO_COURSE, number, day)

    # 1. Sintesi (one request)
    runtime.phase("Fase 3/3: sintesi")
    print("\n[*] Sintesi della lezione in corso...")

    def _generate() -> str | None:
        new_client, text = co.generate_summary(
            client=holder["client"],
            lesson_markdown=lesson_md,
            heading=heading,
            model_name=model_name,
            model_state=model_state,
            fallback_keys=fallback_keys,
            request_fallback_key=request_fallback_key,
            runtime=runtime,
            cancelled=runtime.cancelled,
            on_model_switched=on_model_switched,
            logger=logger,
        )
        holder["client"] = new_client
        return text if isinstance(text, str) else None

    try:
        summary = _summary_text(session_dir=session_ctx.session_dir, generate=_generate)
    except Exception as exc:
        print(f"[!] Sintesi non riuscita ({exc}): salvo solo la lezione.")
        summary = None
    if summary:
        summary = co.ensure_heading(summary, heading)

    # 2. Course folder
    own = {
        os.path.normcase(str(p))
        for p in (previous.get("lesson_file"), previous.get("summary_file"))
        if p
    }
    stem = co.file_date(day)
    lesson_stem = co.unique_stem(paths.lessons, f"L {stem}", own)
    lesson_doc = (
        f"# L {stem}\n\n"
        f'<p class="meta">{html.escape(heading)}'
        f"{' &middot; ' + html.escape(title) if title else ''}</p>\n\n"
        f"{lesson_md}"
    )
    lesson_file = co.write_document(paths.lessons, lesson_stem, f"L {stem}", lesson_doc)
    _remove_if_moved(previous.get("lesson_file"), lesson_file)
    print(f"[OK] Lezione salvata: {lesson_file}")

    summary_file = previous.get("summary_file")
    if summary:
        summary_stem = co.unique_stem(paths.summaries, f"S {stem}", own)
        summary_file = co.write_document(
            paths.summaries, summary_stem, f"S {stem}", summary
        )
        _remove_if_moved(previous.get("summary_file"), summary_file)
        in_app = os.path.join(session_ctx.session_dir, SUMMARY_HTML)
        _atomic_write_text(in_app, build_html_document(f"S {stem}", summary))
        session.setdefault("outputs", {})["summary_html"] = in_app
        print(f"[OK] Sintesi salvata: {summary_file}")

    session["course_output"] = {
        "number": number,
        "folder": os.path.dirname(paths.lessons),
        "lesson_file": lesson_file,
        "summary_file": summary_file,
    }
    save_session()
