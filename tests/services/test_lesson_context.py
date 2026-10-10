from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from jot.services import lesson_context as lc
from tests.services.test_book_retrieval import (
    FakeEmbedClient,
    build_book,
    make_text_pdf,
    topic_page,
)


class SlideMarkerTests(unittest.TestCase):
    def test_extracts_last_marker_and_cleans_text(self):
        text = "## Titolo\n\nTesto.\n[[ULTIMA_SLIDE: 12]]\n"
        clean, last = lc.extract_last_slide(text)
        self.assertEqual(last, 12)
        self.assertNotIn("ULTIMA", clean)
        self.assertTrue(clean.endswith("Testo."))

    def test_zero_or_missing_marker_is_none(self):
        self.assertIsNone(lc.extract_last_slide("x [[ULTIMA_SLIDE: 0]]")[1])
        self.assertIsNone(lc.extract_last_slide("solo testo")[1])

    def test_marker_variants(self):
        self.assertEqual(lc.extract_last_slide("[[ ultima slide : 7 ]]")[1], 7)


class TimestampTests(unittest.TestCase):
    def test_relative_markers_become_absolute(self):
        text = "## [[t=01:30]] Primo\n\ntesto\n\n### [[t=10:05]] Secondo"
        out = lc.absolutize_timestamps(text, 900, 930)
        self.assertIn("## [[t=990]] Primo", out)
        self.assertIn("### [[t=1505]] Secondo", out)

    def test_relative_marker_is_clamped_to_block(self):
        out = lc.absolutize_timestamps("## [[t=99:00]] X", 0, 900)
        self.assertIn("[[t=900]]", out)

    def test_missing_markers_anchor_first_heading(self):
        out = lc.absolutize_timestamps("Intro\n\n## Primo\n\n## Secondo", 1800, 930)
        self.assertIn("## [[t=1800]] Primo", out)
        self.assertNotIn("[[t=1800]] Secondo", out)

    def test_strip_timestamps(self):
        self.assertEqual(lc.strip_timestamps("## [[t=12]] Titolo"), "## Titolo")


class SlideTrackerTests(unittest.TestCase):
    def setUp(self):
        self.calls: list[tuple[int, int]] = []

    def _build(self, _path, start, end):
        self.calls.append((start, end))
        return SimpleNamespace(pdf_bytes=b"", text=f"slide {start}-{end}", images=[])

    def tracker(self, total=60, duration=9000.0):
        return lc.SlideTracker(
            slides_path="lezione.pdf",
            total_slides=total,
            total_duration_sec=duration,
            chunk_seconds=900,
            build_chunk=self._build,
            log=lambda _msg: None,
        )

    def test_window_size_scales_with_density(self):
        # 60 slides in 10 blocks: 6 per block, 1.8x -> 11
        self.assertEqual(self.tracker().window_size(), 11)
        self.assertEqual(self.tracker(total=10).window_size(), lc.MIN_WINDOW)
        self.assertEqual(self.tracker(total=600).window_size(), lc.MAX_WINDOW)

    def test_first_window_is_proportional(self):
        tracker = self.tracker()
        self.assertEqual(tracker.window(0, 0), (1, 11))
        start, end = tracker.window(5, 4500)
        self.assertLessEqual(start, 30)
        self.assertGreaterEqual(end, 30)

    def test_marker_moves_next_window(self):
        tracker = self.tracker()
        window = tracker.context(0, 0)
        assert window is not None
        self.assertIn("[[ULTIMA_SLIDE: n]]", window.prompt)
        cleaned = tracker.observe(0, "Testo\n[[ULTIMA_SLIDE: 9]]", window)
        self.assertEqual(cleaned, "Testo")
        self.assertEqual(tracker.window(1, 900)[0], 9 - lc.BACKTRACK)

    def test_implausible_marker_falls_back_to_window_middle(self):
        tracker = self.tracker()
        window = tracker.context(0, 0)
        assert window is not None
        tracker.observe(0, "Testo [[ULTIMA_SLIDE: 55]]", window)
        self.assertEqual(tracker.positions[0], (window.start + window.end) // 2)

    def test_window_never_exceeds_deck(self):
        tracker = self.tracker(total=20)
        tracker.positions[3] = 20
        start, end = tracker.window(4, 3600)
        self.assertEqual(end, 20)
        self.assertGreaterEqual(start, 1)

    def test_positions_roundtrip(self):
        tracker = self.tracker()
        tracker.positions = {0: 8, 1: 15}
        other = self.tracker()
        other.load(tracker.to_dict())
        self.assertEqual(other.positions, {0: 8, 1: 15})

    def test_unreadable_slides_give_no_context(self):
        def broken(_p, _s, _e):
            raise RuntimeError("rotto")

        tracker = self.tracker()
        tracker.build_chunk = broken
        self.assertIsNone(tracker.context(0, 0))


class RevisionBookContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.book = build_book(os.path.join(self.tmp, "libro.pdf"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_picks_pages_of_the_block_topic(self):
        ctx = lc.RevisionBookContext(
            book_path=self.book,
            allowed_pages=list(range(1, 41)),
            cache_dir=self.tmp,
            log=lambda _m: None,
        )
        block = "## DNS\n\n" + topic_page("dns", 0)
        pages = ctx.for_block(block, FakeEmbedClient())
        assert pages is not None
        self.assertTrue(pages.pdf_bytes.startswith(b"%PDF"))
        self.assertTrue(all(10 <= p <= 21 for p in pages.pages), pages.pages)

    def test_small_selection_is_sent_whole(self):
        ctx = lc.RevisionBookContext(
            book_path=self.book, allowed_pages=[1, 2, 3], log=lambda _m: None
        )
        pages = ctx.for_block("qualsiasi testo", client=None)
        assert pages is not None
        self.assertEqual(pages.pages, [1, 2, 3])
        self.assertEqual(pages.label, "1-3")

    def test_scanned_book_is_skipped(self):
        scanned = make_text_pdf(os.path.join(self.tmp, "scan.pdf"), ["", "", ""])
        ctx = lc.RevisionBookContext(
            book_path=scanned, allowed_pages=[1, 2, 3], log=lambda _m: None
        )
        self.assertIsNone(ctx.for_block("testo", client=None))


class LessonSourcesTests(unittest.TestCase):
    def test_normalizes_and_detects_documents(self):
        sources = lc.LessonSources(slides_path="  ", book_pages=" 1-3, 5 ", title=" ")
        self.assertFalse(sources.has_documents)
        self.assertEqual(sources.book_pages, "1-3,5")
        self.assertIsNone(sources.title)
        self.assertTrue(lc.LessonSources(book_path="libro.pdf").has_documents)

    def test_audio_only_keeps_default_session_folder(self):
        self.assertIsNone(lc.lesson_session_dir("a.mp3", lc.LessonSources()))

    def test_documents_change_session_folder(self):
        tmp = tempfile.mkdtemp()
        try:
            audio = os.path.join(tmp, "a.mp3")
            slides = os.path.join(tmp, "s.pdf")
            for path in (audio, slides):
                with open(path, "wb") as handle:
                    handle.write(b"x" * 10)
            first = lc.lesson_session_dir(audio, lc.LessonSources(slides_path=slides))
            second = lc.lesson_session_dir(
                audio, lc.LessonSources(slides_path=slides, book_pages="")
            )
            assert first is not None
            self.assertEqual(first, second)
            self.assertTrue(os.path.basename(first).startswith("lesson_"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
