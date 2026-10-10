"""
Extra context for audio lessons: slides during transcription, book pages
during revision, and timestamps that link each section to the audio.

Nothing here adds Gemini generation requests:
- SlideTracker attaches to every 15-minute audio block the slides the
  teacher is probably showing. The window follows the lesson thanks to a
  hidden marker the model writes at the end of each block
  ("[[ULTIMA_SLIDE: 27]]"), with a proportional estimate as fallback.
- RevisionBookContext picks, for every revision block, the book pages
  closest to that text (embeddings, keyword fallback) and sends them as a
  small PDF with the block.
- Timestamps: the model starts each heading with "[[t=MM:SS]]" relative to
  the block; they are converted to absolute seconds "[[t=2610]]" so the
  editor can jump the audio player to that section.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from jot.services import book_retrieval, document_service

# ---------------------------------------------------------------------------
# Slide marker
# ---------------------------------------------------------------------------

_SLIDE_MARKER_RE = re.compile(
    r"\[\[\s*ULTIMA[ _]SLIDE\s*:\s*(\d+)\s*\]\]", re.IGNORECASE
)


def extract_last_slide(text: str) -> tuple[str, int | None]:
    """Remove every slide marker. Returns (clean_text, last reported slide)."""
    found = [int(m.group(1)) for m in _SLIDE_MARKER_RE.finditer(text or "")]
    cleaned = _SLIDE_MARKER_RE.sub("", text or "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned).rstrip()
    last = found[-1] if found else None
    return cleaned, (last if last and last > 0 else None)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_REL_TIME_RE = re.compile(
    r"\[\[\s*t\s*=\s*(\d{1,3})\s*:\s*(\d{1,2})\s*\]\]", re.IGNORECASE
)
_ABS_TIME_RE = re.compile(r"\[\[\s*t\s*=\s*(\d+)\s*\]\]", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def absolutize_timestamps(text: str, chunk_start_sec: int, chunk_seconds: int) -> str:
    """Turn "[[t=MM:SS]]" (relative to the block) into "[[t=<abs seconds>]]".

    The first heading without a marker gets the block start, so every block
    keeps at least one anchor even when the model forgets the markers.
    """
    start = int(chunk_start_sec)
    limit = max(0, int(chunk_seconds))

    def _to_abs(match: re.Match) -> str:
        rel = int(match.group(1)) * 60 + int(match.group(2))
        rel = max(0, min(rel, limit))
        return f"[[t={start + rel}]]"

    converted = _REL_TIME_RE.sub(_to_abs, text or "")
    if _ABS_TIME_RE.search(converted):
        return converted
    lines = converted.split("\n")
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) >= 2:
            lines[i] = f"{m.group(1)} [[t={start}]] {m.group(2)}"
            break
    return "\n".join(lines)


def strip_timestamps(text: str) -> str:
    cleaned = _ABS_TIME_RE.sub("", _REL_TIME_RE.sub("", text or ""))
    return re.sub(r"(#{1,6}) {2,}", r"\1 ", cleaned)


# ---------------------------------------------------------------------------
# Slides during transcription
# ---------------------------------------------------------------------------

MIN_WINDOW = 8
MAX_WINDOW = 30
BACKTRACK = 2


@dataclass
class SlideWindow:
    start: int
    end: int
    parts: list[Any]
    prompt: str


def slide_window_prompt(start: int, end: int, total: int, is_pptx: bool) -> str:
    where = (
        "il contenuto delle slide qui sopra"
        if is_pptx
        else f"il PDF allegato (la sua prima pagina è la slide {start})"
    )
    return (
        f"\n\nSLIDE DELLA LEZIONE: {where} contiene le slide {start}-{end} su {total}, "
        "quelle che il docente dovrebbe mostrare in questo blocco. Segui le regole sulle slide. "
        "Alla fine della risposta, su una riga a sé, scrivi [[ULTIMA_SLIDE: n]] con il numero "
        "dell'ultima slide di cui il docente ha parlato in questo blocco "
        "(scrivi [[ULTIMA_SLIDE: 0]] se non riesci a capirlo)."
    )


@dataclass
class SlideTracker:
    """Chooses the slides attached to every audio block."""

    slides_path: str
    total_slides: int
    total_duration_sec: float
    chunk_seconds: int
    positions: dict[int, int] = field(default_factory=dict)
    build_chunk: Callable[[str, int, int], Any] = document_service.build_slide_chunk
    log: Callable[[str], None] = print

    @property
    def is_pptx(self) -> bool:
        return document_service.file_ext(self.slides_path) == ".pptx"

    def _expected(self, at_sec: float) -> int:
        if self.total_duration_sec <= 0:
            return 1
        ratio = max(0.0, min(1.0, float(at_sec) / float(self.total_duration_sec)))
        return max(1, min(self.total_slides, round(ratio * self.total_slides) or 1))

    def window_size(self) -> int:
        if self.total_duration_sec <= 0:
            return MIN_WINDOW
        per_chunk = self.total_slides * self.chunk_seconds / self.total_duration_sec
        return max(MIN_WINDOW, min(MAX_WINDOW, round(per_chunk * 1.8)))

    def window(self, chunk_idx: int, chunk_start_sec: float) -> tuple[int, int]:
        size = self.window_size()
        previous = self.positions.get(int(chunk_idx) - 1)
        if previous is not None:
            start = previous - BACKTRACK
        else:
            # proportional estimate, centred a little before the expected slide
            start = self._expected(chunk_start_sec) - size // 4
        start = max(1, min(int(start), max(1, self.total_slides - size + 1)))
        end = min(self.total_slides, start + size - 1)
        return start, end

    def context(self, chunk_idx: int, chunk_start_sec: float) -> SlideWindow | None:
        from google.genai import types

        start, end = self.window(chunk_idx, chunk_start_sec)
        try:
            payload = self.build_chunk(self.slides_path, start, end)
        except Exception as exc:
            self.log(
                f"   [!] Slide {start}-{end} non leggibili ({exc}): blocco senza slide."
            )
            return None
        parts: list[Any] = []
        pdf_bytes = getattr(payload, "pdf_bytes", None)
        if pdf_bytes:
            if len(pdf_bytes) <= document_service.INLINE_MAX_BYTES:
                parts.append(
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                )
            else:
                text = "\n".join(
                    book_retrieval.extract_page_texts(
                        self.slides_path, range(start, end + 1)
                    ).values()
                )
                if text.strip():
                    parts.append(f"TESTO DELLE SLIDE {start}-{end}:\n{text}")
        text = getattr(payload, "text", "")
        if text:
            parts.append(text)
        for data, mime in getattr(payload, "images", []) or []:
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        if not parts:
            return None
        self.log(f"   -> Slide allegate: {start}-{end}")
        return SlideWindow(
            start=start,
            end=end,
            parts=parts,
            prompt=slide_window_prompt(start, end, self.total_slides, self.is_pptx),
        )

    def observe(self, chunk_idx: int, text: str, window: SlideWindow | None) -> str:
        """Strip the marker and remember where the teacher arrived."""
        cleaned, last = extract_last_slide(text)
        if window is None:
            return cleaned
        accepted = None
        if last is not None and window.start - BACKTRACK <= last <= window.end:
            accepted = last
        if accepted is None:
            # marker missing or implausible: assume the window was covered
            # up to its middle so the next block does not stall.
            accepted = (window.start + window.end) // 2
        previous = self.positions.get(int(chunk_idx) - 1, 0)
        self.positions[int(chunk_idx)] = max(int(accepted), int(previous) - BACKTRACK)
        if last is not None:
            self.log(f"   -> Il docente è arrivato alla slide {last}.")
        return cleaned

    def to_dict(self) -> dict[str, int]:
        return {str(k): int(v) for k, v in self.positions.items()}

    def load(self, data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                try:
                    self.positions[int(key)] = int(value)
                except (TypeError, ValueError):
                    continue


# ---------------------------------------------------------------------------
# Book during revision
# ---------------------------------------------------------------------------

REVISION_SEGMENT_CHARS = book_retrieval.MAX_EMBED_CHARS
REVISION_MAX_SEGMENTS = 4
# A revision with the book may add a few sentences; it must never drop
# much of the original text.
REVISION_MIN_LENGTH_RATIO = 0.75


@dataclass
class BookPages:
    pdf_bytes: bytes
    label: str
    pages: list[int]


def _segments(text: str) -> list[str]:
    clean = strip_timestamps(text or "")
    if len(clean) <= REVISION_SEGMENT_CHARS:
        return [clean]
    step = max(1, len(clean) // REVISION_MAX_SEGMENTS)
    return [clean[i : i + REVISION_SEGMENT_CHARS] for i in range(0, len(clean), step)][
        :REVISION_MAX_SEGMENTS
    ]


@dataclass
class RevisionBookContext:
    """Selects and packs the book pages relevant to a revision block."""

    book_path: str
    allowed_pages: list[int]
    cache_dir: str | None = None
    max_pages: int = book_retrieval.DEFAULT_MAX_PAGES_PER_BLOCK
    log: Callable[[str], None] = print
    _page_texts: dict[int, str] | None = None
    _usable: bool | None = None
    _method_note_shown: bool = False

    def _texts(self) -> dict[int, str]:
        if self._page_texts is None:
            try:
                self._page_texts = book_retrieval.extract_page_texts(
                    self.book_path, self.allowed_pages
                )
            except Exception:
                self._page_texts = {}
            self._usable = book_retrieval.has_text_layer(self._page_texts)
            if not self._usable:
                self.log(
                    "   [!] Il libro non ha testo selezionabile: la revisione procede senza libro."
                )
        return self._page_texts

    def _scores(self, client, segments: Sequence[str]) -> tuple[str, dict[int, float]]:
        texts = self._texts()
        try:
            _model, per_segment = book_retrieval.embedding_scores(
                client,
                texts,
                segments,
                cache_path=(
                    os.path.join(self.cache_dir, book_retrieval.INDEX_FILENAME)
                    if self.cache_dir
                    else None
                ),
                log=self.log,
            )
            method = book_retrieval.METHOD_EMBEDDINGS
        except book_retrieval.EmbeddingUnavailableError as exc:
            if not self._method_note_shown:
                self.log(
                    f"   [!] Embedding non disponibili ({exc}): uso le parole chiave."
                )
                self._method_note_shown = True
            per_segment = book_retrieval.keyword_scores(texts, segments)
            method = book_retrieval.METHOD_KEYWORDS
        merged: dict[int, float] = {}
        for scores in per_segment:
            for page, score in scores.items():
                merged[page] = max(merged.get(page, float("-inf")), score)
        return method, merged

    def for_block(self, block_text: str, client) -> BookPages | None:
        texts = self._texts()
        if not self._usable or not texts:
            return None
        if len(self.allowed_pages) <= self.max_pages:
            pages = list(self.allowed_pages)
        else:
            method, merged = self._scores(client, _segments(block_text))
            pages = book_retrieval.select_pages(
                merged, method, self.allowed_pages, self.max_pages
            )
        if not pages:
            self.log("   -> Libro: nessuna pagina pertinente per questa parte.")
            return None
        label = document_service.format_page_ranges(pages)
        self.log(f"   -> Libro: pagine {label}")
        return BookPages(
            pdf_bytes=document_service.build_pdf_subset(self.book_path, pages),
            label=label,
            pages=pages,
        )


def book_revision_note(label: str) -> str:
    return (
        f"ESTRATTO DEL LIBRO allegato (pagine {label}): usalo solo come indicato nelle regole "
        "sul libro. Qui sotto il testo da revisionare."
    )


# ---------------------------------------------------------------------------
# Sources of a lesson (audio + optional slides and book)
# ---------------------------------------------------------------------------


@dataclass
class LessonSources:
    """Optional material attached to an audio lesson."""

    slides_path: str | None = None
    book_path: str | None = None
    book_pages: str = ""
    title: str | None = None
    course: str | None = None

    def __post_init__(self) -> None:
        self.slides_path = str(self.slides_path or "").strip() or None
        self.book_path = str(self.book_path or "").strip() or None
        self.book_pages = str(self.book_pages or "").replace(" ", "")
        self.title = str(self.title or "").strip() or None
        self.course = str(self.course or "").strip() or None

    @classmethod
    def ensure(cls, value: LessonSources | None) -> LessonSources:
        return value if isinstance(value, LessonSources) else cls()

    @property
    def has_documents(self) -> bool:
        return bool(self.slides_path or self.book_path)

    def to_session(self) -> dict[str, Any]:
        return {
            "slides_path": self.slides_path,
            "book_path": self.book_path,
            "book_pages": self.book_pages,
        }


def lesson_session_dir(audio_path: str, sources: LessonSources) -> str | None:
    """Session folder for audio + documents; None keeps the audio-only folder.

    Audio-only lessons keep their historical folder, so existing sessions
    resume as before. Adding slides or a book is a different job and gets
    its own folder.
    """
    if not sources.has_documents:
        return None
    import hashlib
    import json

    from jot.core.session_store import (
        _session_id_for_file,
        get_session_root,
    )

    blob = {
        "kind": "lesson",
        "audio": _session_id_for_file(audio_path),
        "slides": _session_id_for_file(sources.slides_path)
        if sources.slides_path
        else "",
        "book": _session_id_for_file(sources.book_path) if sources.book_path else "",
        "book_pages": sources.book_pages,
    }
    digest = hashlib.sha256(
        json.dumps(blob, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return os.path.join(get_session_root(), f"lesson_{digest[:56]}")
