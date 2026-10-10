"""Full-text search helpers for the session archive.

Pure functions — no I/O, no side effects — so they are easy to unit-test
and can be called from the bridge layer with any caching strategy.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup  # type: ignore[import-untyped]


def extract_text_from_html(html: str) -> str:
    """Return plain text from an HTML string using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")
    return re.sub(r"\s{2,}", " ", text).strip()


def count_matches(text: str, query: str) -> int:
    """Return the total number of case-insensitive occurrences of *query* in *text*."""
    if not query or not text:
        return 0
    return text.lower().count(query.lower())


def find_snippets(
    text: str,
    query: str,
    max_snippets: int = 3,
    context_chars: int = 120,
) -> tuple[list[dict[str, str]], int]:
    """Find up to *max_snippets* occurrences of *query* inside *text*.

    Returns a ``(snippets, total_count)`` tuple.  ``snippets`` is a list of
    dicts with keys ``before``, ``match``, ``after`` so the UI can render the
    match highlighted without any HTML-injection risk.  ``total_count`` is the
    total number of matches in the full text (counted in the same pass).

    The search is case-insensitive.  ``before`` / ``after`` are trimmed to the
    nearest word boundary (space) to avoid cutting mid-word.
    """
    if not query or not text:
        return [], 0

    query_lower = query.lower()
    text_lower = text.lower()
    results: list[dict[str, str]] = []
    total = 0
    search_start = 0

    while True:
        idx = text_lower.find(query_lower, search_start)
        if idx == -1:
            break

        total += 1
        match_end = idx + len(query)

        if len(results) < max_snippets:
            # --- before context ---
            before_start = max(0, idx - context_chars)
            before_raw = text[before_start:idx]
            if before_start > 0:
                space = before_raw.find(" ")
                if space != -1:
                    before_raw = before_raw[space + 1 :]
            before = before_raw.strip()

            # --- after context ---
            after_end = min(len(text), match_end + context_chars)
            after_raw = text[match_end:after_end]
            if after_end < len(text):
                last_space = after_raw.rfind(" ")
                if last_space != -1:
                    after_raw = after_raw[:last_space]
            after = after_raw.strip()

            results.append(
                {
                    "before": before,
                    "match": text[idx:match_end],
                    "after": after,
                }
            )
        search_start = match_end

    return results, total
