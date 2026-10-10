import json
import math
import os
import tempfile
import unittest
from types import SimpleNamespace

from jot.services import book_retrieval as br


def make_text_pdf(path: str, page_texts: list[str]) -> str:
    """Write a minimal PDF whose pages contain the given (ASCII) text."""

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects: list[bytes] = []
    n = len(page_texts)
    font_id = 3
    first_page_id = 4
    kids = " ".join(f"{first_page_id + 2 * i} 0 R" for i in range(n))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(page_texts):
        page_id = first_page_id + 2 * i
        content_id = page_id + 1
        words = text.split()
        lines, line = [], ""
        for word in words:
            if len(line) + len(word) + 1 > 80:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            lines.append(line)
        body = (
            "BT /F1 10 Tf 40 750 Td 12 TL "
            + " ".join(f"({esc(item)}) Tj T*" for item in lines)
            + " ET"
        )
        stream = body.encode("latin-1")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as handle:
        handle.write(bytes(out))
    return path


TOPICS = {
    "tcp": "transport protocol tcp segments acknowledgement retransmission congestion window sender receiver",
    "dns": "dns resolver domain names hierarchy root servers caching records lookup authoritative",
    "http": "http web browser requests responses cookies persistent connections status codes",
    "routing": "routing algorithms link state distance vector dijkstra shortest path forwarding tables",
}


def topic_page(topic: str, n: int) -> str:
    base = TOPICS[topic]
    return f"Section {n}. " + " ".join([base] * 4)


def build_book(path: str) -> str:
    pages = []
    for topic in ("tcp", "dns", "http", "routing"):
        pages.extend(topic_page(topic, i) for i in range(10))
    return make_text_pdf(path, pages)


def build_slides(path: str, topics: list[str]) -> str:
    return make_text_pdf(path, [f"Slide about {TOPICS[t]}" for t in topics])


class FakeEmbedClient:
    """Embeds text as normalized topic-count vectors (deterministic, offline)."""

    def __init__(self, fail_models=(), error="404 NOT_FOUND"):
        self.calls: list[tuple[str, int, str | None, list[str]]] = []
        self.fail_models = set(fail_models)
        self.error = error
        self.models = SimpleNamespace(embed_content=self._embed)

    @staticmethod
    def vector(text: str) -> list[float]:
        vec = [0.0] * br.EMBEDDING_DIM
        vec[0] = 0.3  # shared baseline so unrelated texts are not orthogonal
        lowered = text.lower()
        for i, topic in enumerate(TOPICS):
            vec[1 + i] = float(sum(lowered.count(w) for w in TOPICS[topic].split()[:4]))
        return vec

    def _embed(self, model, contents, config):
        texts = [c.parts[0].text for c in contents]
        self.calls.append(
            (model, len(texts), getattr(config, "task_type", None), texts)
        )
        if model in self.fail_models:
            raise RuntimeError(self.error)
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=self.vector(t)) for t in texts]
        )


class TokenizeAndRankTests(unittest.TestCase):
    def test_tokenize_stems_and_drops_stopwords(self):
        tokens = br.tokenize("I protocolli TCP e i protocols della rete, 2026")
        self.assertIn("protoc", tokens)
        self.assertEqual(tokens.count("protoc"), 2)
        self.assertNotIn("della", tokens)
        self.assertNotIn("e", tokens)
        self.assertNotIn("2026", tokens)

    def test_bm25_prefers_matching_document(self):
        docs = [br.tokenize(TOPICS["dns"]), br.tokenize(TOPICS["tcp"])]
        scores = br.bm25_scores(br.tokenize("tcp congestion window"), docs)
        self.assertGreater(scores[1][0], scores[0][0])
        self.assertEqual(scores[0], (0.0, 0))
        self.assertGreaterEqual(scores[1][1], 3)

    def test_has_text_layer(self):
        self.assertTrue(br.has_text_layer({1: "x" * 300, 2: "y" * 300}))
        self.assertFalse(br.has_text_layer({1: "", 2: "", 3: "x" * 300}))
        self.assertFalse(br.has_text_layer({}))


class SelectPagesTests(unittest.TestCase):
    def test_embedding_threshold_and_neighbours(self):
        scores = {10: 0.9, 11: 0.86, 30: 0.82, 50: 0.6}
        pages = br.select_pages(scores, br.METHOD_EMBEDDINGS, range(1, 61))
        self.assertEqual(pages, [9, 10, 11, 12, 29, 30, 31])

    def test_cap_and_allowed_pages(self):
        scores = {p: 0.9 - p * 0.001 for p in range(1, 40)}
        pages = br.select_pages(scores, br.METHOD_EMBEDDINGS, range(5, 40), max_pages=4)
        self.assertEqual(len(pages), 4)
        self.assertTrue(all(5 <= p < 40 for p in pages))

    def test_nothing_relevant(self):
        self.assertEqual(
            br.select_pages({1: 0.3, 2: 0.2}, br.METHOD_EMBEDDINGS, [1, 2]), []
        )
        self.assertEqual(br.select_pages({}, br.METHOD_KEYWORDS, [1]), [])

    def test_keyword_relative_threshold(self):
        scores = {3: 10.0, 7: 5.0, 9: 2.0}
        pages = br.select_pages(scores, br.METHOD_KEYWORDS, range(1, 20))
        self.assertIn(3, pages)
        self.assertIn(7, pages)
        self.assertNotIn(9, pages)


class BookPlanTests(unittest.TestCase):
    def test_roundtrip_and_validation(self):
        plan = br.BookPlan(br.METHOD_EMBEDDINGS, [[1, 2], []], reason="x")
        restored = br.BookPlan.from_dict(json.loads(json.dumps(plan.to_dict())), 2)
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.blocks, [[1, 2], []])
        self.assertIsNone(br.BookPlan.from_dict(plan.to_dict(), 3))
        self.assertIsNone(br.BookPlan.from_dict({"method": "magic", "blocks": []}, 0))
        self.assertIsNone(br.BookPlan.from_dict(None, 0))

    def test_normalize_book_mode(self):
        self.assertEqual(br.normalize_book_mode("AUTO"), "auto")
        self.assertEqual(br.normalize_book_mode(None), "full")
        self.assertEqual(br.normalize_book_mode("boh"), "full")


class PlanBookPagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = build_book(os.path.join(self.tmp.name, "book.pdf"))
        self.slides = build_slides(
            os.path.join(self.tmp.name, "slides.pdf"),
            ["dns", "dns", "dns", "routing", "routing", "routing"],
        )
        self.chunks = [(1, 3), (4, 6)]
        self.allowed = list(range(1, 41))

    def _plan(self, client, **kwargs):
        return br.plan_book_pages(
            client=client,
            book_path=self.book,
            allowed_pages=kwargs.pop("allowed", self.allowed),
            slides_path=kwargs.pop("slides", self.slides),
            chunks=kwargs.pop("chunks", self.chunks),
            cache_dir=self.tmp.name,
            sleep=lambda _s: None,
            log=lambda _m: None,
            **kwargs,
        )

    def test_extracts_real_pdf_text(self):
        texts = br.extract_page_texts(self.book, [1, 12])
        self.assertIn("congestion", texts[1])
        self.assertIn("resolver", texts[12])
        blocks = br.slide_block_texts(self.slides, self.chunks)
        self.assertIn("dns", blocks[0])
        self.assertIn("dijkstra", blocks[1])

    def test_embeddings_pick_the_right_chapter(self):
        client = FakeEmbedClient()
        plan = self._plan(client)
        self.assertEqual(plan.method, br.METHOD_EMBEDDINGS)
        self.assertIn("gemini-embedding-001", plan.reason)
        self.assertTrue(plan.blocks[0])
        self.assertTrue(set(plan.blocks[0]) <= set(range(10, 22)), plan.blocks[0])
        self.assertTrue(set(plan.blocks[1]) <= set(range(30, 41)), plan.blocks[1])
        self.assertLessEqual(
            max(len(b) for b in plan.blocks), br.DEFAULT_MAX_PAGES_PER_BLOCK
        )
        task_types = {c[2] for c in client.calls}
        self.assertEqual(task_types, {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"})
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, br.INDEX_FILENAME)))

        # Second plan: page vectors come from the cache, only queries are embedded.
        client2 = FakeEmbedClient()
        self._plan(client2)
        self.assertEqual([c[2] for c in client2.calls], ["RETRIEVAL_QUERY"])

    def test_falls_back_to_second_model_on_404(self):
        client = FakeEmbedClient(fail_models={"gemini-embedding-001"})
        plan = self._plan(client)
        self.assertEqual(plan.method, br.METHOD_EMBEDDINGS)
        self.assertIn("gemini-embedding-2", plan.reason)
        used = [c for c in client.calls if c[0] == "gemini-embedding-2"]
        self.assertTrue(used[0][3][0].startswith("title: none | text:"))
        self.assertIsNone(used[0][2])

    def test_falls_back_to_keywords_when_rate_limited(self):
        client = FakeEmbedClient(
            fail_models=set(br.EMBEDDING_MODELS), error="429 RESOURCE_EXHAUSTED"
        )
        plan = self._plan(client)
        self.assertEqual(plan.method, br.METHOD_KEYWORDS)
        self.assertTrue(set(plan.blocks[0]) <= set(range(10, 22)), plan.blocks[0])
        self.assertTrue(set(plan.blocks[1]) <= set(range(30, 41)), plan.blocks[1])
        # one retry on the first model, no second model for non-404 errors
        self.assertEqual(len(client.calls), 2)

    def test_small_excerpt_is_sent_whole(self):
        plan = self._plan(FakeEmbedClient(), allowed=list(range(11, 21)))
        self.assertEqual(plan.method, br.METHOD_FULL)
        self.assertEqual(plan.blocks, [list(range(11, 21))] * 2)

    def test_scanned_book_is_sent_whole(self):
        scanned = make_text_pdf(os.path.join(self.tmp.name, "scan.pdf"), ["x"] * 30)
        plan = br.plan_book_pages(
            client=FakeEmbedClient(),
            book_path=scanned,
            allowed_pages=list(range(1, 31)),
            slides_path=self.slides,
            chunks=self.chunks,
            log=lambda _m: None,
        )
        self.assertEqual(plan.method, br.METHOD_FULL)
        self.assertIn("scansione", plan.reason)

    def test_block_without_text_reuses_previous_pages(self):
        slides = make_text_pdf(
            os.path.join(self.tmp.name, "img.pdf"),
            [f"Slide about {TOPICS['http']}", "", ""],
        )
        plan = self._plan(FakeEmbedClient(), slides=slides, chunks=[(1, 1), (2, 3)])
        self.assertTrue(plan.blocks[0])
        self.assertEqual(plan.blocks[1], plan.blocks[0])
        self.assertTrue(plan.notes)

    def test_cosine_of_normalized_vectors(self):
        a = br._normalize([3.0, 4.0])
        self.assertTrue(math.isclose(br._cosine(a, a), 1.0))


if __name__ == "__main__":
    unittest.main()
