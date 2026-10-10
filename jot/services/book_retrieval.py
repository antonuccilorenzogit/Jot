"""
Per-block textbook page selection for the "Slide e appunti" mode.

Instead of sending the whole book excerpt with every block of slides, pick
only the pages that talk about the same topics as that block:

1. Embeddings (preferred): every selected book page and every slide block is
   embedded with a Gemini embedding model; pages are ranked by cosine
   similarity. Works across languages (English slides, Italian book).
   Embedding calls use a separate model and do not consume the daily
   requests of the generation model. Page vectors are cached on disk.
2. Keywords (fallback): local BM25 ranking, no API calls. Used when the
   embedding model is unavailable, rate limited or fails.
3. Full excerpt (safety net): when the book has no text layer (scanned) or
   the excerpt is already small, the previous behaviour is kept.

The result is a BookPlan: one list of original book page numbers per block
(an empty list means "no relevant pages: send the block without the book").
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from jot.services import document_service

BOOK_MODE_AUTO = "auto"
BOOK_MODE_FULL = "full"
BOOK_MODES = (BOOK_MODE_AUTO, BOOK_MODE_FULL)

METHOD_EMBEDDINGS = "embeddings"
METHOD_KEYWORDS = "keywords"
METHOD_FULL = "full"

DEFAULT_MAX_PAGES_PER_BLOCK = 15
# Pages with less text than this are considered empty (figures, blank pages).
MIN_PAGE_CHARS = 200
# Below this share of pages with real text the book is treated as scanned.
MIN_TEXT_PAGE_RATIO = 0.6
# Slide blocks with less text than this cannot be matched reliably.
MIN_BLOCK_CHARS = 60

EMBEDDING_MODELS: tuple[str, ...] = ("gemini-embedding-001", "gemini-embedding-2")
EMBEDDING_DIM = 768
EMBEDDING_BATCH = 100
# ~2000 tokens is the input limit of gemini-embedding-001: stay below it.
MAX_EMBED_CHARS = 6000
INDEX_FILENAME = "book_index.json"

# Embeddings: keep pages close to the best one; below ABS_MIN nothing matches.
COS_MARGIN = 0.10
COS_ABS_MIN = 0.45
# Keywords: keep pages scoring at least this share of the best page.
BM25_RELATIVE_MIN = 0.35
BM25_MIN_SHARED_TERMS = 2
# Neighbour pages (±1) are added around the strongest hits.
NEIGHBOUR_HITS = 3


class EmbeddingUnavailableError(RuntimeError):
    """Embedding model missing, rate limited or failing: use keywords."""


@dataclass
class BookPlan:
    method: str
    blocks: list[list[int]]
    reason: str = ""
    max_pages: int = DEFAULT_MAX_PAGES_PER_BLOCK
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "blocks": [list(map(int, b)) for b in self.blocks],
            "reason": self.reason,
            "max_pages": int(self.max_pages),
        }

    @classmethod
    def from_dict(cls, data: Any, expected_blocks: int) -> BookPlan | None:
        if not isinstance(data, dict):
            return None
        method = str(data.get("method") or "")
        blocks = data.get("blocks")
        if method not in (METHOD_EMBEDDINGS, METHOD_KEYWORDS, METHOD_FULL):
            return None
        if not isinstance(blocks, list) or len(blocks) != int(expected_blocks):
            return None
        try:
            parsed = [[int(p) for p in block] for block in blocks]
        except (TypeError, ValueError):
            return None
        return cls(
            method=method,
            blocks=parsed,
            reason=str(data.get("reason") or ""),
            max_pages=int(data.get("max_pages") or DEFAULT_MAX_PAGES_PER_BLOCK),
        )


def normalize_book_mode(value: Any) -> str:
    """Missing/unknown values mean the legacy behaviour (whole excerpt)."""
    mode = str(value or "").strip().lower()
    return mode if mode in BOOK_MODES else BOOK_MODE_FULL


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_page_texts(pdf_path: str, pages: Sequence[int]) -> dict[int, str]:
    """Text of the given 1-based pages. Unreadable pages map to ""."""
    reader = document_service._open_pdf(pdf_path)
    total = len(reader.pages)
    texts: dict[int, str] = {}
    for page_no in pages:
        number = int(page_no)
        if not 1 <= number <= total:
            continue
        try:
            text = reader.pages[number - 1].extract_text() or ""
        except Exception:
            text = ""
        texts[number] = re.sub(r"\s+", " ", text).strip()
    return texts


def slide_block_texts(slides_path: str, chunks: Sequence[tuple[int, int]]) -> list[str]:
    """Plain text of every block of slides (PDF text layer or PPTX shapes)."""
    ext = document_service.file_ext(slides_path)
    if ext == ".pptx":
        out = []
        for start, end in chunks:
            try:
                out.append(
                    document_service.build_pptx_chunk(slides_path, start, end).text
                )
            except Exception:
                out.append("")
        return out
    pages = [p for start, end in chunks for p in range(int(start), int(end) + 1)]
    try:
        texts = extract_page_texts(slides_path, pages)
    except Exception:
        return ["" for _ in chunks]
    return [
        "\n".join(texts.get(p, "") for p in range(int(start), int(end) + 1)).strip()
        for start, end in chunks
    ]


def has_text_layer(page_texts: dict[int, str]) -> bool:
    if not page_texts:
        return False
    with_text = sum(1 for t in page_texts.values() if len(t) >= MIN_PAGE_CHARS)
    return with_text / len(page_texts) >= MIN_TEXT_PAGE_RATIO


# ---------------------------------------------------------------------------
# Keyword ranking (BM25, local)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    """
    the and for are with that this from have has was were will can not but all
    any its into than then them they their there these those which while what
    when where who why how also such each other more most some only over under
    between about after before during both used using use may one two three
    del della dello delle degli dei nel nella nelle negli nei sul sulla sulle
    sui con per tra fra che non una uno gli alla alle allo agli dal dalla dalle
    dagli come anche più sono essere viene vengono può possono questo questa
    questi queste quello quella quelli quelle cui suo sua suoi sue loro ogni
    altro altra altri altre stesso stessa molto quando dove mentre quindi
    perché però infatti ovvero oppure inoltre cioè slide figura figure capitolo
    chapter page pagina esempio example
    """.split()
)
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
# Light prefix stemming: "protocol"/"protocollo"/"protocols" -> "protoc".
_STEM_LEN = 6


def tokenize(text: str) -> list[str]:
    tokens = []
    for word in _WORD_RE.findall(str(text or "").lower()):
        if word in _STOPWORDS:
            continue
        tokens.append(word[:_STEM_LEN])
    return tokens


def bm25_scores(
    query: Sequence[str],
    documents: Sequence[Sequence[str]],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[tuple[float, int]]:
    """Return (score, shared_distinct_terms) per document."""
    n_docs = len(documents)
    if n_docs == 0:
        return []
    avg_len = sum(len(d) for d in documents) / n_docs or 1.0
    doc_freq: Counter[str] = Counter()
    counters = [Counter(d) for d in documents]
    for counter in counters:
        doc_freq.update(counter.keys())
    query_terms = Counter(query)
    results: list[tuple[float, int]] = []
    for doc, counter in zip(documents, counters, strict=True):
        score = 0.0
        shared = 0
        length_norm = k1 * (1 - b + b * len(doc) / avg_len)
        for term, q_count in query_terms.items():
            tf = counter.get(term, 0)
            if not tf:
                continue
            shared += 1
            df = doc_freq[term]
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            # Repeated query terms (key concepts of the block) weigh more.
            weight = 1 + math.log(q_count)
            score += weight * idf * tf * (k1 + 1) / (tf + length_norm)
        results.append((score, shared))
    return results


# ---------------------------------------------------------------------------
# Embeddings (Gemini)
# ---------------------------------------------------------------------------


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [float(v) / norm for v in vector]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=False)))


def _embedding_input(model: str, kind: str, text: str) -> str:
    clipped = str(text or "")[:MAX_EMBED_CHARS]
    if model == "gemini-embedding-2":
        # This model takes the task as a text prefix instead of task_type.
        if kind == "query":
            return f"task: search result | query: {clipped}"
        return f"title: none | text: {clipped}"
    return clipped


def _is_not_found(exc: Exception) -> bool:
    text = str(exc).lower()
    return "404" in text or "not_found" in text or "not found" in text


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        k in text
        for k in ("429", "resource_exhausted", "503", "500", "unavailable", "timeout")
    )


def embed_texts(
    client,
    model: str,
    texts: Sequence[str],
    kind: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    cancelled: Callable[[], bool] = lambda: False,
) -> list[list[float]]:
    """Embed texts in batches, one normalized vector per text."""
    from google.genai import types

    task_type = None
    if model == "gemini-embedding-001":
        task_type = "RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT"
    config = types.EmbedContentConfig(
        output_dimensionality=EMBEDDING_DIM, task_type=task_type
    )
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH):
        batch = texts[start : start + EMBEDDING_BATCH]
        contents: Any = [
            types.Content(parts=[types.Part(text=_embedding_input(model, kind, t))])
            for t in batch
        ]
        response = None
        for attempt in range(2):
            if cancelled():
                raise EmbeddingUnavailableError("annullato")
            try:
                response = client.models.embed_content(
                    model=model, contents=contents, config=config
                )
                break
            except Exception as exc:
                if attempt == 0 and _is_retryable(exc):
                    sleep(8.0)
                    continue
                raise
        embeddings = list(getattr(response, "embeddings", None) or [])
        if len(embeddings) != len(batch):
            raise EmbeddingUnavailableError(
                f"risposta embedding incompleta ({len(embeddings)}/{len(batch)})"
            )
        for embedding in embeddings:
            values = list(getattr(embedding, "values", None) or [])
            if not values:
                raise EmbeddingUnavailableError("embedding vuoto")
            vectors.append(_normalize(values))
    return vectors


def _load_index(path: str, model: str, pages: Sequence[int]) -> dict[int, list[float]]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    if data.get("model") != model or int(data.get("dim") or 0) != EMBEDDING_DIM:
        return {}
    stored = data.get("pages") or {}
    out: dict[int, list[float]] = {}
    for page in pages:
        vector = stored.get(str(int(page)))
        if isinstance(vector, list) and len(vector) == EMBEDDING_DIM:
            out[int(page)] = [float(v) for v in vector]
    return out


def _save_index(path: str, model: str, vectors: dict[int, list[float]]) -> None:
    payload = {
        "model": model,
        "dim": EMBEDDING_DIM,
        "pages": {str(p): [round(v, 5) for v in vec] for p, vec in vectors.items()},
    }
    tmp = f"{path}.partial"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except Exception:
        pass


def embedding_scores(
    client,
    page_texts: dict[int, str],
    block_texts: Sequence[str],
    *,
    cache_path: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    cancelled: Callable[[], bool] = lambda: False,
    log: Callable[[str], None] = print,
) -> tuple[str, list[dict[int, float]]]:
    """Cosine similarity of every page for every block. Returns (model, scores)."""
    pages = [p for p, t in page_texts.items() if len(t) >= MIN_PAGE_CHARS]
    if not pages:
        raise EmbeddingUnavailableError("nessuna pagina con testo")
    last_error: Exception | None = None
    for model in EMBEDDING_MODELS:
        try:
            cached = _load_index(cache_path, model, pages) if cache_path else {}
            missing = [p for p in pages if p not in cached]
            if missing:
                log(
                    f"   -> Indicizzazione di {len(missing)} pagine del libro ({model})..."
                )
                vectors = embed_texts(
                    client,
                    model,
                    [page_texts[p] for p in missing],
                    "document",
                    sleep=sleep,
                    cancelled=cancelled,
                )
                cached.update(dict(zip(missing, vectors, strict=True)))
                if cache_path:
                    _save_index(cache_path, model, cached)
            queries = [t if len(t) >= MIN_BLOCK_CHARS else "" for t in block_texts]
            to_embed = [i for i, q in enumerate(queries) if q]
            query_vectors = (
                embed_texts(
                    client,
                    model,
                    [queries[i] for i in to_embed],
                    "query",
                    sleep=sleep,
                    cancelled=cancelled,
                )
                if to_embed
                else []
            )
            by_block: dict[int, list[float]] = dict(
                zip(to_embed, query_vectors, strict=True)
            )
            scores: list[dict[int, float]] = []
            for i in range(len(block_texts)):
                vec = by_block.get(i)
                scores.append(
                    {p: _cosine(vec, cached[p]) for p in pages}
                    if vec is not None
                    else {}
                )
            return model, scores
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            last_error = exc
            if _is_not_found(exc):
                continue
            break
    raise EmbeddingUnavailableError(
        str(last_error or "modello embedding non disponibile")
    )


def keyword_scores(
    page_texts: dict[int, str], block_texts: Sequence[str]
) -> list[dict[int, float]]:
    pages = [p for p, t in page_texts.items() if len(t) >= MIN_PAGE_CHARS]
    docs = [tokenize(page_texts[p]) for p in pages]
    out: list[dict[int, float]] = []
    for text in block_texts:
        query = tokenize(text) if len(text) >= MIN_BLOCK_CHARS else []
        if not query or not docs:
            out.append({})
            continue
        ranked = bm25_scores(query, docs)
        out.append(
            {
                p: score
                for p, (score, shared) in zip(pages, ranked, strict=True)
                if shared >= BM25_MIN_SHARED_TERMS and score > 0
            }
        )
    return out


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def select_pages(
    scores: dict[int, float],
    method: str,
    allowed_pages: Sequence[int],
    max_pages: int = DEFAULT_MAX_PAGES_PER_BLOCK,
) -> list[int]:
    """Pick the best pages for one block, plus neighbours of the top hits."""
    if not scores:
        return []
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best = ranked[0][1]
    if method == METHOD_EMBEDDINGS:
        if best < COS_ABS_MIN:
            return []
        threshold = max(COS_ABS_MIN, best - COS_MARGIN)
    else:
        if best <= 0:
            return []
        threshold = best * BM25_RELATIVE_MIN
    hits = [page for page, score in ranked if score >= threshold]
    allowed = set(int(p) for p in allowed_pages)
    chosen: list[int] = []

    def _add(page: int) -> None:
        if page in allowed and page not in chosen and len(chosen) < max_pages:
            chosen.append(page)

    for rank, page in enumerate(hits):
        _add(page)
        if rank < NEIGHBOUR_HITS:
            _add(page - 1)
            _add(page + 1)
        if len(chosen) >= max_pages:
            break
    return sorted(chosen)


def _fill_unmatched_blocks(
    blocks: list[list[int]],
    block_texts: Sequence[str],
    fallback: list[int],
) -> list[str]:
    """Blocks without usable slide text reuse the previous block's pages."""
    notes = []
    for i, text in enumerate(block_texts):
        if len(text) >= MIN_BLOCK_CHARS:
            continue
        previous = blocks[i - 1] if i > 0 else []
        blocks[i] = list(previous) if previous else list(fallback)
        notes.append(
            f"blocco {i + 1}: slide senza testo, "
            + (
                "uso le pagine del blocco precedente"
                if previous
                else "uso l'estratto completo"
            )
        )
    return notes


def plan_book_pages(
    *,
    client,
    book_path: str,
    allowed_pages: Sequence[int],
    slides_path: str,
    chunks: Sequence[tuple[int, int]],
    cache_dir: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES_PER_BLOCK,
    sleep: Callable[[float], None] = time.sleep,
    cancelled: Callable[[], bool] = lambda: False,
    log: Callable[[str], None] = print,
) -> BookPlan:
    allowed = [int(p) for p in allowed_pages]
    full = BookPlan(METHOD_FULL, [list(allowed) for _ in chunks], max_pages=max_pages)
    if len(allowed) <= max_pages:
        full.reason = f"l'estratto ha già solo {len(allowed)} pagine"
        return full
    page_texts = extract_page_texts(book_path, allowed)
    if not has_text_layer(page_texts):
        full.reason = "il PDF del libro non ha testo selezionabile (scansione?)"
        return full
    block_texts = slide_block_texts(slides_path, chunks)
    if not any(len(t) >= MIN_BLOCK_CHARS for t in block_texts):
        full.reason = "le slide non contengono testo leggibile (solo immagini?)"
        return full

    method = METHOD_EMBEDDINGS
    reason = ""
    try:
        model, scores = embedding_scores(
            client,
            page_texts,
            block_texts,
            cache_path=os.path.join(cache_dir, INDEX_FILENAME) if cache_dir else None,
            sleep=sleep,
            cancelled=cancelled,
            log=log,
        )
        reason = f"similarità semantica ({model})"
    except EmbeddingUnavailableError as exc:
        if cancelled():
            raise
        log(f"   [!] Embedding non disponibili ({exc}): uso le parole chiave.")
        method = METHOD_KEYWORDS
        scores = keyword_scores(page_texts, block_texts)
        reason = "parole chiave (BM25)"

    blocks = [select_pages(s, method, allowed, max_pages) for s in scores]
    notes = _fill_unmatched_blocks(blocks, block_texts, list(allowed))
    return BookPlan(method, blocks, reason=reason, max_pages=max_pages, notes=notes)
