"""
Course folder outputs: every finished lesson is also saved, together with a
short "sintesi", in a folder per course:

    Documenti/jot/<Corso>/Lezioni/L 12-10-2026.pdf
    Documenti/jot/<Corso>/Sintesi/S 12-10-2026.pdf

Formulas are written as MathML, so the files show real formulas offline. The
PDF is printed by the browser already installed on the computer (Edge on
Windows, Chrome/Edge on macOS); when that is not possible the HTML file is
kept instead.
"""

from __future__ import annotations

import html as _html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jot.services.lesson_context import strip_timestamps

LESSONS_DIR = "Lezioni"
SUMMARIES_DIR = "Sintesi"
NO_COURSE = "Senza corso"
PDF_TIMEOUT_SECONDS = 90

PROMPT_SINTESI = """Sei un tutor universitario. Ricevi gli appunti completi di una lezione e scrivi una SINTESI per ripassare, in italiano.

Rispondi SOLO con la sintesi in Markdown, con esattamente questa struttura:

# {intestazione}

## Concetti chiave
Da 5 a 8 concetti, in una frase ciascuno, con parole semplici (elenco puntato).

## Definizioni
Solo i termini tecnici usati nella lezione, ciascuno con una definizione di una riga (elenco puntato, termine in grassetto).

## Formule
Le formule della lezione in LaTeX: nel testo tra $...$, quelle importanti su una riga a sé tra $$...$$. Ogni formula con una riga che spiega cosa rappresenta. Se la lezione non ha formule, scrivi "Nessuna formula in questa lezione."

## Esempio tipo
Un esempio o esercizio svolto della lezione, in 3-5 righe. Se non c'è, scrivi "Nessun esempio svolto in questa lezione."

## Autoverifica
3 domande numerate a cui si risponde senza appunti.

### Risposte
Le risposte alle 3 domande, numerate, separate dalle domande.

Regole:
- Non copiare frasi dal professore: scrivi con parole tue.
- Ignora le digressioni e gli aneddoti che non servono all'esame.
- Se un concetto negli appunti non è chiaro o manca, segnalalo tra parentesi quadre [così] invece di inventarlo.
- Niente frasi introduttive o conclusive fuori dalla struttura.
"""


# ---------------------------------------------------------------------------
# Places and names
# ---------------------------------------------------------------------------


def documents_dir() -> str:
    """The user's Documents folder (also when OneDrive moved it)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5, SHGFP_TYPE_CURRENT = 0
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # type: ignore[attr-defined]
                if buf.value:
                    return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def course_root(config: dict | None = None) -> str:
    custom = (
        os.environ.get("JOT_COURSE_ROOT", "").strip()
        or str((config or {}).get("course_root") or "").strip()
    )
    return custom or os.path.join(documents_dir(), "jot")


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe_folder_name(name: str | None) -> str:
    clean = _UNSAFE.sub(" ", str(name or "")).strip().strip(".")
    clean = re.sub(r"\s+", " ", clean)
    return clean[:80] or NO_COURSE


def parse_lesson_date(value: str | None) -> date:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return date.today()


def file_date(day: date) -> str:
    return day.strftime("%d-%m-%Y")


def text_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")


@dataclass
class CoursePaths:
    course: str
    lessons: str
    summaries: str


def course_paths(course: str | None, root: str) -> CoursePaths:
    name = safe_folder_name(course)
    base = os.path.join(root, name)
    return CoursePaths(
        course=name,
        lessons=os.path.join(base, LESSONS_DIR),
        summaries=os.path.join(base, SUMMARIES_DIR),
    )


def next_lesson_number(lessons_dir: str) -> int:
    """1 + the lessons already in the folder (one per date name)."""
    if not os.path.isdir(lessons_dir):
        return 1
    stems = {
        os.path.splitext(f)[0]
        for f in os.listdir(lessons_dir)
        if f.startswith("L ") and f.lower().endswith((".pdf", ".html"))
    }
    return len(stems) + 1


def unique_stem(folder: str, stem: str, own: set[str]) -> str:
    """ "L 12-10-2026", or "L 12-10-2026 (2)" when another lesson has that day."""
    candidate, n = stem, 2
    while True:
        taken = [
            os.path.join(folder, candidate + ext)
            for ext in (".pdf", ".html")
            if os.path.exists(os.path.join(folder, candidate + ext))
        ]
        if not taken or all(os.path.normcase(p) in own for p in taken):
            return candidate
        candidate = f"{stem} ({n})"
        n += 1


# ---------------------------------------------------------------------------
# Markdown -> printable HTML (MathML) -> PDF
# ---------------------------------------------------------------------------

_PRINT_CSS = """
@page { size: A4; margin: 20mm 18mm; }
html { background: #fff; }
body {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 11pt; line-height: 1.55; color: #141416;
  max-width: 720px; margin: 0 auto; padding: 32px 20px;
}
h1, h2, h3, h4 { font-family: Georgia, "Times New Roman", serif; font-weight: 700; line-height: 1.25; color: #141416; break-after: avoid; }
h1 { font-size: 21pt; margin: 0 0 6pt; }
h2 { font-size: 15pt; margin: 20pt 0 6pt; }
h3 { font-size: 12.5pt; margin: 14pt 0 4pt; }
p { margin: 0 0 8pt; }
ul, ol { margin: 0 0 8pt; padding-left: 20pt; }
li { margin: 2pt 0; }
.meta { color: #6b6c71; font-style: italic; margin: 0 0 16pt; }
table { border-collapse: collapse; margin: 8pt 0 12pt; width: 100%; break-inside: avoid; }
th, td { border: none; padding: 4pt 8pt 4pt 0; text-align: left; vertical-align: top; }
thead th { border-bottom: 0.75pt solid #9a9a9f; font-weight: 700; }
tbody tr + tr td { border-top: 0.5pt solid #e3e1db; }
math[display="block"] { display: block math; margin: 10pt 0; font-size: 118%; text-align: center; }
math { font-size: 105%; }
blockquote { margin: 0 0 8pt; padding-left: 10pt; border-left: 2pt solid #f5b700; color: #3d3e43; }
code { font-family: Consolas, monospace; font-size: 95%; }
"""


def _latex_to_mathml(latex: str, display: bool) -> str:
    try:
        from latex2mathml.converter import convert

        return convert(latex, display="block" if display else "inline")
    except Exception:
        text = _html.escape(latex)
        return f'<code class="formula">{text}</code>'


def markdown_to_print_html(title: str, markdown_text: str) -> str:
    import markdown

    from jot.utils.html_export import (
        _protect_math,
        normalize_heading_levels,
        normalize_inline_star_lists,
        sanitize_html_basic,
    )

    md = normalize_inline_star_lists(strip_timestamps(markdown_text or ""))
    md = normalize_heading_levels(md)
    protected, found = _protect_math(md)
    body = markdown.markdown(protected, extensions=["extra", "sane_lists"])
    body = sanitize_html_basic(body)
    for index, (kind, latex) in enumerate(found):
        token = f"SBOBMATH{index}X"
        rendered = _latex_to_mathml(latex, kind == "block")
        if kind == "block":
            body = body.replace(f"<p>{token}</p>", rendered)
        body = body.replace(token, rendered)
    safe_title = _html.escape(title or "jot")
    return (
        '<!DOCTYPE html>\n<html lang="it">\n<head>\n<meta charset="utf-8" />\n'
        f"<title>{safe_title}</title>\n<style>{_PRINT_CSS}</style>\n</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def _running_as_root() -> bool:
    try:
        return hasattr(os, "geteuid") and os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:
        return False


def _browser_candidates() -> list[str]:
    found: list[str] = []
    if sys.platform == "win32":
        for base in (
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            for rel in (
                r"Microsoft\Edge\Application\msedge.exe",
                r"Google\Chrome\Application\chrome.exe",
            ):
                if base and os.path.isfile(os.path.join(base, rel)):
                    found.append(os.path.join(base, rel))
    elif sys.platform == "darwin":
        for app in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ):
            if os.path.isfile(app):
                found.append(app)
    else:
        for name in ("chromium", "chromium-browser", "google-chrome", "msedge"):
            path = shutil.which(name)
            if path:
                found.append(path)
    return found


def html_to_pdf(html_path: str, pdf_path: str) -> bool:
    """Print an HTML file to PDF with a locally installed Chromium browser."""
    if os.environ.get("JOT_NO_PDF") == "1":
        return False
    for browser in _browser_candidates():
        profile = tempfile.mkdtemp(prefix="jot_pdf_")
        try:
            cmd = [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile}",
                *(["--no-sandbox"] if _running_as_root() else []),
                "--no-pdf-header-footer",
                "--print-to-pdf-no-header",
                f"--print-to-pdf={pdf_path}",
                Path(html_path).resolve().as_uri(),
            ]
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PDF_TIMEOUT_SECONDS,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                check=False,
            )
            if os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 800:
                return True
        except Exception:
            continue
        finally:
            shutil.rmtree(profile, ignore_errors=True)
    return False


def write_document(folder: str, stem: str, title: str, markdown_text: str) -> str:
    """Write <stem>.pdf (or <stem>.html when no PDF printer is available)."""
    os.makedirs(folder, exist_ok=True)
    html_doc = markdown_to_print_html(title, markdown_text)
    html_path = os.path.join(folder, stem + ".html")
    pdf_path = os.path.join(folder, stem + ".pdf")
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(html_doc)
    if html_to_pdf(html_path, pdf_path):
        try:
            os.remove(html_path)
        except OSError:
            pass
        return pdf_path
    return html_path


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summary_heading(course: str, number: int, day: date) -> str:
    dash = "\u2013"
    return f"{course} {dash} Lezione {number} {dash} {text_date(day)}"


def generate_summary(
    *,
    client,
    lesson_markdown: str,
    heading: str,
    model_name: str,
    model_state,
    fallback_keys: list[str],
    request_fallback_key: Callable[[], str | None],
    runtime,
    cancelled: Callable[[], bool],
    on_model_switched=None,
    logger=None,
) -> tuple[object, str | None]:
    """One Gemini request: the lesson notes in, the "sintesi" out."""
    from google.genai import types

    from jot.services.generation_service import (
        current_model_name,
        extract_response_text,
        retry_with_quota,
    )

    notes = strip_timestamps(lesson_markdown).strip()
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
        cancelled=cancelled,
        runtime=runtime,
        request_fallback_key=request_fallback_key,
        on_model_switched=on_model_switched,
        logger=logger,
        resume_phase_text="Fase 3/3: sintesi",
    )


def ensure_heading(summary: str, heading: str) -> str:
    """The first line is always "# <Materia> - Lezione <n> - <data>"."""
    lines = summary.strip().split("\n")
    if lines and lines[0].lstrip().startswith("# "):
        lines[0] = f"# {heading}"
        return "\n".join(lines)
    return f"# {heading}\n\n" + summary.strip()


__all__ = [
    "LESSONS_DIR",
    "NO_COURSE",
    "PROMPT_SINTESI",
    "SUMMARIES_DIR",
    "CoursePaths",
    "course_paths",
    "course_root",
    "documents_dir",
    "ensure_heading",
    "file_date",
    "generate_summary",
    "html_to_pdf",
    "markdown_to_print_html",
    "next_lesson_number",
    "parse_lesson_date",
    "safe_folder_name",
    "summary_heading",
    "text_date",
    "unique_stem",
    "write_document",
]
