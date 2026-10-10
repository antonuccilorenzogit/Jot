"""
Conservative deduplication helpers used before calling the revision model.

These are intentionally conservative to avoid deleting unique content.
"""

from __future__ import annotations

import difflib
import re


def _norm_for_dedup(txt: str) -> str:
    t = (txt or "").replace("\u00a0", " ").strip().lower()
    t = re.sub(r"\s+", " ", t)
    # Normalizza un minimo la punteggiatura per ridurre falsi negativi.
    t = re.sub(r"\s*([,.;:!?])\s*", r"\1", t)
    return t


def local_macro_cleanup(md: str) -> tuple[str, int, int, int, int]:
    # Rimuove SOLO duplicati certi (identici dopo normalizzazione) e near-duplicati adiacenti molto forti.
    # Non riassume e non elimina contenuti "nuovi": e' conservativo per preservare dettaglio.
    src = (md or "").strip()
    if not src:
        return "", 0, 0, 0, 0

    paras = [p.strip() for p in re.split(r"\n\s*\n+", src) if p and p.strip()]
    if not paras:
        return src, 0, 0, 0, 0

    kept = []
    seen = set()
    removed_exact = 0
    removed_adj = 0
    near_adj = 0
    prev_norm = ""

    for p in paras:
        is_heading = bool(re.match(r"^\s*#{1,6}\s+", p))
        # Evita di deduplicare "a vuoto" stringhe minuscole (rischio di falsi positivi).
        min_len = 20 if is_heading else 60
        norm = _norm_for_dedup(p)

        if len(norm) >= min_len and norm in seen:
            removed_exact += 1
            continue

        if prev_norm and len(norm) >= 100 and len(prev_norm) >= 100:
            r = difflib.SequenceMatcher(None, prev_norm, norm).ratio()
            if r >= 0.995:
                removed_adj += 1
                continue
            if r >= 0.975:
                near_adj += 1

        kept.append(p)
        if len(norm) >= min_len:
            seen.add(norm)
        prev_norm = norm

    cleaned = "\n\n".join(kept).strip()
    total = len(paras)
    return cleaned, removed_exact, removed_adj, near_adj, total
