"""
Suggestions shown on the "Nuova lezione" page before anything is sent to
Gemini: lesson title, book chapter, daily quota and model setup.

Everything here is local (or a free metadata call): no generation requests.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jot.services import book_retrieval, document_service

# ---------------------------------------------------------------------------
# Lesson title
# ---------------------------------------------------------------------------

TITLE_MAX_CHARS = 80

_GENERIC_TITLES = {
    "presentazione standard di powerpoint",
    "presentazione di powerpoint",
    "powerpoint presentation",
    "presentation",
    "presentazione",
    "slide",
    "slides",
    "untitled",
    "senza titolo",
    "document",
    "documento",
    "microsoft word",
}

_NOISE_RE = re.compile(
    r"\b(?:rec(?:ording)?|registrazione|nuova registrazione|new recording|audio|"
    r"voice|memo|vocale|track|traccia|lezione_?audio|img|vid|aud|dji|zoom)\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(?:\d{8}|\d{4}[-_.]\d{1,2}[-_.]\d{1,2}|\d{1,2}[-_.]\d{1,2}[-_.]\d{2,4})"
    r"(?:[-_ T]?\d{4,6})?\b"
)
_TIME_RE = re.compile(r"\b\d{1,2}[.:h]\d{2}(?:[.:]\d{2})?\b")
_ONLY_DIGITS_RE = re.compile(r"^[\d\s#.-]*$")


def _clean_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" -\u2013\u2014_:\u00b7|")
    if len(cleaned) > TITLE_MAX_CHARS:
        cut = cleaned[:TITLE_MAX_CHARS].rsplit(" ", 1)[0]
        cleaned = cut.rstrip(" ,;:-") or cleaned[:TITLE_MAX_CHARS]
    return cleaned


def _usable_title(text: str | None) -> str | None:
    cleaned = _clean_title(text or "")
    if len(cleaned) < 3 or cleaned.lower() in _GENERIC_TITLES:
        return None
    if _ONLY_DIGITS_RE.match(cleaned):
        return None
    if re.search(r"\.(pptx?|pdf|docx?|key)$", cleaned, re.IGNORECASE):
        return None
    return cleaned


def title_from_filename(path: str) -> str | None:
    stem = os.path.splitext(os.path.basename(str(path or "")))[0]
    text = stem.replace("_", " ").replace("+", " ")
    text = _DATE_RE.sub(" ", text)
    text = _TIME_RE.sub(" ", text)
    text = _NOISE_RE.sub(" ", text)
    text = re.sub(r"\s*[-.]\s*", " ", text)
    text = re.sub(r"\(\s*\d*\s*\)", " ", text)
    title = _usable_title(text)
    if not title:
        return None
    return title[0].upper() + title[1:]


def _pdf_title(path: str) -> str | None:
    reader = document_service._open_pdf(path)
    try:
        meta_title = (reader.metadata or {}).get("/Title")
    except Exception:
        meta_title = None
    title = _usable_title(str(meta_title) if meta_title else None)
    if title:
        return title
    try:
        first_page = reader.pages[0].extract_text() or ""
    except Exception:
        return None
    for line in first_page.splitlines():
        title = _usable_title(line)
        if title and len(title) >= 6:
            return title
    return None


def _pptx_title(path: str) -> str | None:
    prs = document_service._open_pptx(path)
    try:
        title = _usable_title(prs.core_properties.title)
    except Exception:
        title = None
    if title:
        return title
    for slide in list(prs.slides)[:2]:
        shape = getattr(slide.shapes, "title", None)
        if shape is not None and getattr(shape, "has_text_frame", False):
            title = _usable_title(shape.text_frame.text)
            if title:
                return title
    return None


def suggest_title(audio_path: str | None, slides_path: str | None) -> str | None:
    """Best guess for the lesson name: slides first, then the file names."""
    if slides_path:
        try:
            ext = document_service.file_ext(slides_path)
            title = (
                _pptx_title(slides_path) if ext == ".pptx" else _pdf_title(slides_path)
            )
            if title:
                return title
        except Exception:
            pass
    for path in (audio_path, slides_path):
        if path:
            title = title_from_filename(path)
            if title:
                return title
    return None


# ---------------------------------------------------------------------------
# Book chapter
# ---------------------------------------------------------------------------

CHAPTER_MIN_SCORE = 1.0
CHAPTER_MARGIN = 1.15
LONG_CHAPTER_PAGES = 80
QUERY_MAX_CHARS = 40_000


@dataclass
class OutlineEntry:
    title: str
    level: int
    start: int  # 1-based page
    end: int = 0  # 1-based, inclusive


def read_outline(path: str) -> list[OutlineEntry]:
    """Flattened PDF bookmarks with the page range each one covers."""
    reader = document_service._open_pdf(path)
    total = len(reader.pages)
    entries: list[OutlineEntry] = []

    def walk(items: Any, level: int) -> None:
        for item in items or []:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                raw_page = reader.get_destination_page_number(item)
            except Exception:
                continue
            if raw_page is None:
                continue
            page = int(raw_page) + 1
            title = _clean_title(str(getattr(item, "title", "") or ""))
            if title and 1 <= page <= total:
                entries.append(OutlineEntry(title=title, level=level, start=page))

    try:
        walk(reader.outline, 0)
    except Exception:
        return []
    for i, entry in enumerate(entries):
        end = total
        for nxt in entries[i + 1 :]:
            if nxt.level <= entry.level:
                end = max(entry.start, nxt.start - 1)
                break
        entry.end = end
    return entries


def _children(
    entries: Sequence[OutlineEntry], parent: OutlineEntry
) -> list[OutlineEntry]:
    return [
        e
        for e in entries
        if e.level == parent.level + 1 and parent.start <= e.start <= parent.end
    ]


def _best(
    candidates: Sequence[OutlineEntry],
    entries: Sequence[OutlineEntry],
    query: list[str],
) -> OutlineEntry | None:
    if not candidates:
        return None
    docs = []
    for cand in candidates:
        titles = [
            e.title
            for e in entries
            if e.level >= cand.level and cand.start <= e.start <= cand.end
        ]
        docs.append(book_retrieval.tokenize(" ".join(titles)))
    scores = [s for s, _shared in book_retrieval.bm25_scores(query, docs)]
    ranked = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
    top = ranked[0]
    if scores[top] < CHAPTER_MIN_SCORE:
        return None
    if len(ranked) > 1 and scores[top] < CHAPTER_MARGIN * scores[ranked[1]]:
        return None
    return candidates[top]


def suggest_chapter(
    book_path: str, slides_path: str | None = None, title: str | None = None
) -> dict[str, Any] | None:
    """Chapter of the book that matches the slides (or the lesson title)."""
    query_text = title or ""
    if slides_path:
        try:
            total = document_service.count_pages(slides_path)
            texts = book_retrieval.slide_block_texts(slides_path, [(1, total)])
            query_text = f"{query_text} {' '.join(texts)}"
        except Exception:
            pass
    query = book_retrieval.tokenize(query_text[:QUERY_MAX_CHARS])
    if not query:
        return None
    try:
        entries = read_outline(book_path)
    except Exception:
        return None
    if not entries:
        return None
    top_level = min(e.level for e in entries)
    best = _best([e for e in entries if e.level == top_level], entries, query)
    if best is None:
        return None
    while best.end - best.start + 1 > LONG_CHAPTER_PAGES:
        child = _best(_children(entries, best), entries, query)
        if child is None:
            break
        best = child
    pages = f"{best.start}-{best.end}" if best.end > best.start else str(best.start)
    return {
        "title": best.title,
        "pages": pages,
        "count": best.end - best.start + 1,
    }


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


def next_quota_reset(now_utc: datetime | None = None) -> datetime:
    """Next midnight in Pacific time (Gemini daily quota reset), in UTC."""
    from jot.utils.pacific_time import to_pacific

    local = to_pacific(now_utc)
    # midnight of the next Pacific day; the offset at that moment may differ
    # (daylight saving), so it is resolved again for the new time
    next_day = (local + timedelta(days=1)).date()
    guess = datetime(
        next_day.year, next_day.month, next_day.day, tzinfo=UTC
    ) + timedelta(hours=8)
    offset = to_pacific(guess).utcoffset() or timedelta(hours=-8)
    return datetime(next_day.year, next_day.month, next_day.day, tzinfo=UTC) - offset


def quota_snapshot(
    preferred_model: str,
    fallback_keys: Sequence[str] = (),
    fallback_models: Sequence[str] = (),
) -> dict[str, Any]:
    """Requests used today and an estimate of what is left on the main key."""
    from jot.services import usage_service

    usage = usage_service.get_daily_usage(
        primary_key=None,
        primary_model=preferred_model,
        fallback_models=list(fallback_models),
    )
    telemetry = usage.get("telemetry") or {}
    used = int(telemetry.get("responses_succeeded", 0) or 0)
    limit = int(usage_service.get_limit_for_model(preferred_model))
    limits = usage.get("project_limits") or {}
    state = str((limits.get(preferred_model) or {}).get("quota_state") or "normal")
    remaining = 0 if state == "rpd_exhausted" else max(0, limit - used)
    extra_keys = len([k for k in fallback_keys if str(k or "").strip()])
    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "exhausted": state == "rpd_exhausted",
        "has_reserve": bool(extra_keys or list(fallback_models)),
        "reset_at": next_quota_reset().isoformat(),
    }


# ---------------------------------------------------------------------------
# Automatic model setup (first run)
# ---------------------------------------------------------------------------


def pick_models(client, candidates: Sequence[str]) -> tuple[str | None, list[str]]:
    """Newest model the key can use plus up to two older ones as fallback.

    Uses models.get (metadata only): it does not consume the daily quota.
    """
    from jot.services.validation_service import _get_model_capabilities

    available: list[str] = []
    for name in candidates:
        try:
            info = client.models.get(model=name)
        except Exception:
            continue
        actions = _get_model_capabilities(info)
        if actions and "generateContent" not in actions:
            continue
        available.append(name)
    if not available:
        return None, []
    return available[0], available[1:3]


__all__ = [
    "OutlineEntry",
    "next_quota_reset",
    "pick_models",
    "quota_snapshot",
    "read_outline",
    "suggest_chapter",
    "suggest_title",
    "title_from_filename",
]
