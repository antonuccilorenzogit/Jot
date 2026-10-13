from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from pypdf import PdfReader, PdfWriter

from jot.services import lesson_planning as lp
from tests.services.test_book_retrieval import (
    TOPICS,
    build_book,
    make_text_pdf,
)

CHAPTERS = [
    (
        "Capitolo 1 Il livello di trasporto TCP",
        0,
        ["Segmenti e finestra", "Controllo di congestione"],
    ),
    ("Capitolo 2 Il sistema DNS", 10, ["Risoluzione dei nomi", "Server autoritativi"]),
    ("Capitolo 3 Il protocollo HTTP", 20, ["Richieste e risposte", "Cookie e cache"]),
    ("Capitolo 4 Instradamento", 30, ["Link state e Dijkstra", "Distance vector"]),
]


def build_book_with_outline(path: str) -> str:
    plain = build_book(path + ".plain.pdf")
    writer = PdfWriter(clone_from=PdfReader(plain))
    for title, start, sections in CHAPTERS:
        parent = writer.add_outline_item(title, start)
        for i, section in enumerate(sections):
            writer.add_outline_item(section, start + 1 + i * 4, parent=parent)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


class TitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_filename_cleanup(self):
        self.assertEqual(
            lp.title_from_filename("/x/Reti_di_calcolatori_lezione_5_20261010.m4a"),
            "Reti di calcolatori lezione 5",
        )
        self.assertEqual(
            lp.title_from_filename("Registrazione 2026-10-10 09.32.mp3"), None
        )
        self.assertEqual(lp.title_from_filename("New Recording 12.m4a"), None)
        self.assertEqual(
            lp.title_from_filename("analisi 2 - integrali doppi.mp3"),
            "Analisi 2 integrali doppi",
        )

    def test_slides_first_line_wins_over_audio_name(self):
        slides = make_text_pdf(
            os.path.join(self.tmp, "s.pdf"),
            ["Il protocollo TCP: controllo di flusso", "altro"],
        )
        title = lp.suggest_title(os.path.join(self.tmp, "REC_0001.m4a"), slides)
        self.assertEqual(title, "Il protocollo TCP: controllo di flusso")

    def test_falls_back_to_audio_name(self):
        self.assertEqual(
            lp.suggest_title("/x/Fisiologia - cuore.mp3", None), "Fisiologia cuore"
        )
        self.assertIsNone(lp.suggest_title("/x/REC_0001.mp3", None))

    def test_long_titles_are_cut_on_a_word(self):
        title = lp._usable_title("parola " * 30)
        assert title is not None
        self.assertLessEqual(len(title), lp.TITLE_MAX_CHARS)
        self.assertTrue(title.endswith("parola"))


class ChapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.book = build_book_with_outline(os.path.join(self.tmp, "libro.pdf"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_outline_ranges(self):
        entries = lp.read_outline(self.book)
        top = [e for e in entries if e.level == 0]
        self.assertEqual(
            [(e.start, e.end) for e in top], [(1, 10), (11, 20), (21, 30), (31, 40)]
        )
        child = next(e for e in entries if e.title == "Segmenti e finestra")
        self.assertEqual((child.level, child.start), (1, 2))

    def test_chapter_matching_the_slides(self):
        slides = make_text_pdf(
            os.path.join(self.tmp, "slides.pdf"),
            ["Risoluzione dei nomi DNS", "Server autoritativi e resolver"],
        )
        chapter = lp.suggest_chapter(self.book, slides)
        assert chapter is not None
        self.assertEqual(chapter["pages"], "11-20")
        self.assertIn("DNS", chapter["title"])

    def test_title_alone_can_suggest(self):
        chapter = lp.suggest_chapter(
            self.book, None, "Instradamento: Dijkstra e distance vector"
        )
        assert chapter is not None
        self.assertEqual(chapter["pages"], "31-40")

    def test_no_outline_no_suggestion(self):
        plain = build_book(os.path.join(self.tmp, "plain.pdf"))
        self.assertIsNone(lp.suggest_chapter(plain, None, TOPICS["dns"]))

    def test_ambiguous_query_gives_nothing(self):
        self.assertIsNone(lp.suggest_chapter(self.book, None, "lezione introduttiva"))


class QuotaTests(unittest.TestCase):
    def test_next_reset_is_pacific_midnight(self):
        reset = lp.next_quota_reset(datetime(2026, 10, 10, 12, 0, tzinfo=UTC))
        # 00:00 PDT = 07:00 UTC
        self.assertEqual(reset, datetime(2026, 10, 11, 7, 0, tzinfo=UTC))

    def test_snapshot_counts_every_request_on_every_key_and_model(self):
        from jot.services import usage_service

        usage_service.reset_daily_usage_for_tests()
        try:
            # 3 requests sent on the main key, one failed: all of them count
            for _ in range(3):
                usage_service.record_request_attempt("AIza-main", "gemini-2.5-flash")
            usage_service.record_request_success("AIza-main", "gemini-2.5-flash")
            snap = lp.quota_snapshot("gemini-2.5-flash", primary_key="AIza-main")
            self.assertEqual(
                (snap["used"], snap["limit"], snap["remaining"]), (3, 20, 17)
            )
            self.assertFalse(snap["exhausted"])
            # two keys x two models = four pairs of 20
            snap = lp.quota_snapshot(
                "gemini-2.5-flash",
                ["AIza-reserve"],
                ["gemini-3.6-flash"],
                primary_key="AIza-main",
            )
            self.assertEqual(
                (snap["used"], snap["limit"], snap["remaining"]), (3, 80, 77)
            )
            self.assertEqual(snap["keys"], 2)
            self.assertEqual(
                [(m["model"], m["remaining"]) for m in snap["per_model"]],
                [("gemini-2.5-flash", 37), ("gemini-3.6-flash", 40)],
            )
        finally:
            usage_service.reset_daily_usage_for_tests()


class PickModelsTests(unittest.TestCase):
    def test_newest_available_first(self):
        allowed = {"gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"}

        def get(model):
            if model not in allowed:
                raise RuntimeError("404 NOT_FOUND")
            return SimpleNamespace(supported_actions=["generateContent"])

        client = SimpleNamespace(models=SimpleNamespace(get=get))
        preferred, fallbacks = lp.pick_models(
            client,
            [
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash",
                "gemini-2.5-flash",
            ],
        )
        self.assertEqual(preferred, "gemini-3.6-flash")
        self.assertEqual(fallbacks, ["gemini-3.5-flash", "gemini-2.5-flash"])

    def test_none_available(self):
        def get(model):
            raise RuntimeError("403")

        client = SimpleNamespace(models=SimpleNamespace(get=get))
        self.assertEqual(lp.pick_models(client, ["a", "b"]), (None, []))


if __name__ == "__main__":
    unittest.main()
