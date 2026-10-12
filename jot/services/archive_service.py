"""
Archive querying and full-text search domain service for jot.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from jot.bridge.bridge_utils import (
    _candidate_from_relative,
    _normalize_revision_failed_blocks,
)
from jot.utils.file_ops import _atomic_write_json

if TYPE_CHECKING:
    import threading
    from collections import OrderedDict
    from collections.abc import Callable


def find_candidate_audio_path(
    data: dict,
    session_dir: str,
    session_path: str | None = None,
    *,
    write_back: bool = True,
) -> str | None:
    """Find and optionally repair candidate audio path from relative or absolute links."""
    input_data = data.get("input", {})
    if not isinstance(input_data, dict):
        return None
    current_path = str(input_data.get("path", "") or "").strip()
    if current_path and os.path.isfile(current_path):
        return current_path
    candidates: list[str] = []
    session_candidate = _candidate_from_relative(
        session_dir, input_data.get("path_rel_to_session")
    )
    if session_candidate:
        candidates.append(session_candidate)
    html_path = str(data.get("outputs", {}).get("html", "") or "")
    if html_path:
        html_candidate = _candidate_from_relative(
            os.path.dirname(os.path.realpath(html_path)),
            input_data.get("path_rel_to_html"),
        )
        if html_candidate:
            candidates.append(html_candidate)
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        if write_back:
            input_data["path"] = candidate
            input_data["name"] = os.path.basename(candidate)
            try:
                input_data["size"] = os.path.getsize(candidate)
            except Exception:
                pass
            if session_path:
                try:
                    _atomic_write_json(session_path, data)
                except Exception:
                    pass
        return candidate
    return None


def _course_output_fields(data: dict) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    summary = str((data.get("outputs") or {}).get("summary_html") or "")
    if summary and os.path.isfile(summary):
        fields["summary_html"] = summary
    course_output = data.get("course_output")
    if isinstance(course_output, dict):
        folder = str(course_output.get("folder") or "")
        if folder and os.path.isdir(folder):
            fields["course_folder"] = folder
        if course_output.get("number"):
            fields["lesson_number"] = int(course_output["number"])
    if data.get("lesson_date"):
        fields["lesson_date"] = str(data["lesson_date"])
    return fields


def _lesson_sources_summary(data: dict) -> dict[str, Any]:
    raw = data.get("lesson")
    lesson: dict = raw if isinstance(raw, dict) else {}
    slides = str(lesson.get("slides_path") or "")
    book = str(lesson.get("book_path") or "")
    return {
        "slides_name": os.path.basename(slides) if slides else None,
        "book_name": os.path.basename(book) if book else None,
        "book_pages": str(lesson.get("book_pages") or ""),
    }


def list_completed_sessions(
    session_root: str,
    limit: int = 0,
    find_audio_path_fn: Callable[[dict, str, str], str | None] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Scan session_root for completed sessions and return (sessions, total_count)."""
    if not os.path.isdir(session_root):
        return [], 0

    candidates: list[tuple[str, dict[str, Any], str]] = []
    for entry in os.scandir(session_root):
        if not entry.is_dir():
            continue
        session_path = os.path.join(entry.path, "session.json")
        if not os.path.isfile(session_path):
            continue
        try:
            with open(session_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                continue
            if data.get("stage") != "done":
                continue
            html_path = data.get("outputs", {}).get("html", "")
            if not html_path:
                continue
            candidates.append((data.get("updated_at", ""), data, entry.path))
        except Exception:
            continue

    candidates.sort(key=lambda c: c[0], reverse=True)
    total = len(candidates)
    load_all = int(limit) <= 0
    effective_limit = len(candidates) if load_all else max(0, int(limit))

    effective_find_audio = find_audio_path_fn or find_candidate_audio_path
    sessions: list[dict[str, Any]] = []
    for _ts, data, session_dir in candidates[:effective_limit]:
        html_path = data.get("outputs", {}).get("html", "")
        if html_path and not os.path.isfile(str(html_path)):
            session_copy = os.path.join(session_dir, os.path.basename(str(html_path)))
            if not os.path.isfile(session_copy):
                continue
            html_path = session_copy
            try:
                data["outputs"]["html"] = html_path
                _atomic_write_json(os.path.join(session_dir, "session.json"), data)
            except Exception:
                pass

        input_path = (
            effective_find_audio(
                data, session_dir, os.path.join(session_dir, "session.json")
            )
            or data.get("input", {}).get("path", "")
            or ""
        )

        input_size = int(data.get("input", {}).get("size", 0) or 0)
        name = str(data.get("title") or "").strip() or (
            os.path.basename(input_path)
            if input_path
            else os.path.basename(str(html_path))
        )
        effective_model = data.get("settings", {}).get("effective_model", "")
        duration_sec = data.get("phase1", {}).get("duration_seconds")
        revision_failed_blocks = _normalize_revision_failed_blocks(
            data.get("revision_failed_blocks", [])
        )
        raw_status = str(data.get("completion_status") or "")
        completion_status = (
            "completed_with_warnings"
            if raw_status == "completed_with_warnings" or revision_failed_blocks
            else "completed"
        )
        last_opened_at_iso = data.get("last_opened_at", "")
        sessions.append(
            {
                "name": name,
                "completed_at_iso": data.get("updated_at", ""),
                "html_path": str(html_path),
                "effective_model": effective_model,
                "input_path": str(input_path),
                "input_size": input_size,
                "session_dir": str(session_dir),
                "revision_failed_blocks": revision_failed_blocks,
                "completion_status": completion_status,
                "kind": "notes" if data.get("kind") == "notes" else "audio",
                **({"course": str(data["course"])} if data.get("course") else {}),
                **_course_output_fields(data),
                **(
                    {"sources": _lesson_sources_summary(data)}
                    if data.get("lesson")
                    else {}
                ),
                **(
                    {
                        "notes_info": {
                            "total_slides": int(
                                (data.get("notes") or {}).get("total_slides") or 0
                            ),
                            "book_name": (data.get("notes") or {}).get("book_name")
                            or None,
                            "book_pages": (data.get("notes") or {}).get("book_pages")
                            or "",
                        }
                    }
                    if data.get("kind") == "notes"
                    else {}
                ),
                **({"duration_sec": duration_sec} if duration_sec is not None else {}),
                **(
                    {"last_opened_at_iso": str(last_opened_at_iso)}
                    if last_opened_at_iso
                    else {}
                ),
            }
        )

    return sessions, total


def search_completed_sessions(
    session_root: str,
    query: str,
    limit: int = 100,
    text_cache: OrderedDict[str, tuple[float, str]] | None = None,
    text_cache_lock: threading.Lock | None = None,
    text_cache_max: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Perform full-text search across all completed session HTMLs."""
    from jot.services.search_service import (
        extract_text_from_html,
        find_snippets,
    )

    if not os.path.isdir(session_root):
        return [], 0

    results: list[dict[str, Any]] = []
    for entry in os.scandir(session_root):
        if not entry.is_dir():
            continue
        session_path = os.path.join(entry.path, "session.json")
        if not os.path.isfile(session_path):
            continue
        try:
            with open(session_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or data.get("stage") != "done":
                continue
            html_path = str(data.get("outputs", {}).get("html", ""))
            if not html_path or not os.path.isfile(html_path):
                continue

            try:
                mtime = os.path.getmtime(html_path)
            except OSError:
                continue

            text: str | None = None
            if text_cache is not None and text_cache_lock is not None:
                with text_cache_lock:
                    cached = text_cache.get(html_path)
                    if cached is not None and cached[0] == mtime:
                        text_cache.move_to_end(html_path)
                        text = cached[1]

            if text is None:
                with open(html_path, encoding="utf-8", errors="replace") as fh:
                    raw_html = fh.read()
                text = extract_text_from_html(raw_html)
                if text_cache is not None and text_cache_lock is not None:
                    with text_cache_lock:
                        text_cache[html_path] = (mtime, text)
                        if len(text_cache) > text_cache_max:
                            text_cache.popitem(last=False)

            snippets, match_count = find_snippets(text, query)
            if not snippets:
                continue

            input_path = data.get("input", {}).get("path", "")
            name = str(data.get("title") or "").strip() or (
                os.path.basename(str(input_path))
                if input_path
                else os.path.basename(html_path)
            )
            results.append(
                {
                    "session_dir": entry.path,
                    "name": name,
                    "html_path": html_path,
                    "completed_at_iso": data.get("updated_at", ""),
                    "snippets": snippets,
                    "match_count": match_count,
                }
            )
        except Exception:
            continue

    results.sort(key=lambda r: r["match_count"], reverse=True)
    total_matches = len(results)
    try:
        limit_int = int(limit)
    except (ValueError, TypeError):
        limit_int = 100

    limited_results = results[:limit_int] if limit_int > 0 else results
    return limited_results, total_matches
