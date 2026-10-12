"""
Audio + slides + book through the real pipeline (real FFmpeg, fake Gemini).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from jot.pipeline.pipeline import esegui_sbobinatura
from jot.pipeline.pipeline_adapter import PipelineAdapter
from jot.services.lesson_context import LessonSources
from tests.pipeline.test_pipeline_e2e_synthetic import _generate_synthetic_wav
from tests.services.test_book_retrieval import make_text_pdf, topic_page

TRANSCRIPT = (
    "## [[t=00:01]] Il protocollo TCP\n\n"
    "Il **TCP** garantisce la consegna ordinata dei segmenti con la formula "
    "$RTT = 2 \\cdot d$.\n\n"
    "### Controllo di flusso\n\n"
    "La finestra di ricezione limita i dati in volo, spiegata con cura dal docente.\n"
    "[[ULTIMA_SLIDE: 3]]"
)


SUMMARY = (
    "# Titolo provvisorio\n\n## Concetti chiave\n- Il TCP consegna i segmenti in ordine.\n"
    "- La finestra di ricezione limita i dati in volo.\n\n## Definizioni\n- **RTT:** tempo di andata e ritorno.\n\n"
    "## Formule\n$$RTT = 2 \\cdot d$$\nTempo di andata e ritorno.\n\n## Esempio tipo\nNessun esempio svolto in questa lezione.\n\n"
    "## Autoverifica\n1. Cosa garantisce il TCP?\n\n### Risposte\n1. La consegna ordinata.\n"
)


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


def _part_kinds(contents) -> list[str]:
    kinds = []
    for item in contents:
        if isinstance(item, str):
            kinds.append("text")
        elif getattr(getattr(item, "inline_data", None), "mime_type", None):
            kinds.append(item.inline_data.mime_type)
        elif getattr(item, "file_data", None) is not None:
            kinds.append("file")
        else:
            kinds.append(type(item).__name__)
    return kinds


class LessonPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.audio = _generate_synthetic_wav(
            os.path.join(self.tmp, "lezione.wav"), duration_sec=2.0
        )
        self.slides = make_text_pdf(
            os.path.join(self.tmp, "slide.pdf"),
            [f"Slide {i} TCP finestra segmenti" for i in range(1, 6)],
        )
        self.book = make_text_pdf(
            os.path.join(self.tmp, "libro.pdf"),
            [topic_page("tcp", i) for i in range(8)],
        )
        self.session_dir = os.path.join(self.tmp, "session")
        self.adapter = PipelineAdapter(
            window=MagicMock(), cancel_event=threading.Event()
        )
        self.adapter.ask_regenerate = (
            lambda filename, callback, mode="resume", session_dir="": callback(
                {"regenerate": False}
            )
        )
        self.calls: list[dict] = []
        self.summary_calls: list = []
        self.courses = os.path.join(self.tmp, "corsi")
        env = patch.dict(os.environ, {"JOT_COURSE_ROOT": self.courses})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _client(self, revision_text: str | None = None):
        client = MagicMock()
        client.api_key = "test-key"

        def generate(model, contents, config):
            system = str(getattr(config, "system_instruction", "") or "")
            is_revision = "revisore editoriale" in system
            if "tutor universitario" in system:
                self.summary_calls.append(contents)
                return _FakeResponse(SUMMARY)
            self.calls.append(
                {
                    "revision": is_revision,
                    "system": system,
                    "kinds": _part_kinds(contents),
                    "texts": [c for c in contents if isinstance(c, str)],
                }
            )
            if is_revision:
                block = contents[-1]
                return _FakeResponse(revision_text or block)
            return _FakeResponse(TRANSCRIPT)

        client.models.generate_content.side_effect = generate
        return client

    def _run(self, lesson: LessonSources, client) -> dict:
        with patch("google.genai.Client", return_value=client):
            esegui_sbobinatura(
                input_path=self.audio,
                api_key_value="test-key",
                app_instance=self.adapter,
                session_dir_hint=self.session_dir,
                lesson=lesson,
            )
        with open(
            os.path.join(self.session_dir, "session.json"), encoding="utf-8"
        ) as f:
            return json.load(f)

    def test_audio_slides_and_book(self):
        session = self._run(
            LessonSources(
                slides_path=self.slides,
                book_path=self.book,
                title="Reti — Lezione 5",
                course="Reti di calcolatori",
                lesson_date="2026-10-12",
            ),
            self._client(),
        )
        self.assertEqual(self.adapter.last_run_status, "completed")
        # the summary is one more request
        self.assertEqual(len(self.summary_calls), 1)
        transcription = [c for c in self.calls if not c["revision"]]
        revision = [c for c in self.calls if c["revision"]]
        # one request per audio block plus one per revision block: no extras
        self.assertEqual(len(transcription), 1)
        self.assertEqual(len(revision), 1)

        self.assertIn("REGOLA 5", transcription[0]["system"])
        self.assertIn("application/pdf", transcription[0]["kinds"])
        self.assertTrue(any("ULTIMA_SLIDE" in t for t in transcription[0]["texts"]))

        self.assertIn("ESTRATTO DEL LIBRO", revision[0]["system"])
        self.assertEqual(revision[0]["kinds"][0], "application/pdf")
        self.assertTrue(revision[0]["texts"][0].startswith("ESTRATTO DEL LIBRO"))

        self.assertEqual(session["title"], "Reti — Lezione 5")
        self.assertEqual(session["course"], "Reti di calcolatori")
        self.assertEqual(session["lesson"]["slides_path"], self.slides)
        self.assertEqual(session["phase1"]["slide_positions"], {"1": 3})

        html_path = self.adapter.last_output_html
        assert html_path is not None
        self.assertTrue(os.path.basename(html_path).startswith("Reti — Lezione 5"))
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn('data-t="1"', html)
        self.assertIn("data-math=", html)
        self.assertNotIn("ULTIMA_SLIDE", html)
        self.assertNotIn("[[t=", html)
        self.assertFalse(
            os.path.exists(os.path.join(self.session_dir, "book_index.json"))
        )

        # course folder: Lezioni/L <date> and Sintesi/S <date>
        course_dir = os.path.join(self.courses, "Reti di calcolatori")
        lesson_file = os.path.join(course_dir, "Lezioni", "L 12-10-2026.html")
        summary_file = os.path.join(course_dir, "Sintesi", "S 12-10-2026.html")
        self.assertTrue(os.path.isfile(lesson_file))
        self.assertTrue(os.path.isfile(summary_file))
        with open(summary_file, encoding="utf-8") as f:
            summary_html = f.read()
        self.assertIn(
            "Reti di calcolatori \u2013 Lezione 1 \u2013 12/10/2026", summary_html
        )
        self.assertIn("<math", summary_html)
        self.assertNotIn("Titolo provvisorio", summary_html)
        with open(lesson_file, encoding="utf-8") as f:
            lesson_html = f.read()
        self.assertIn("L 12-10-2026", lesson_html)
        self.assertIn("<math", lesson_html)
        self.assertEqual(session["course_output"]["number"], 1)
        self.assertTrue(os.path.isfile(session["outputs"]["summary_html"]))

    def test_two_audio_parts_become_one_lesson(self):
        second = _generate_synthetic_wav(
            os.path.join(self.tmp, "lezione_parte2.wav"), duration_sec=2.0
        )
        session = self._run(
            LessonSources(audio_parts=[second], course="Analisi 2"), self._client()
        )
        self.assertEqual(self.adapter.last_run_status, "completed")
        merged = session["input"]["path"]
        self.assertTrue(merged.endswith("audio_unito.mp3"))
        from jot.services.audio_service import probe_media_duration

        duration, _reason = probe_media_duration(merged)
        assert duration is not None
        self.assertGreater(duration, 3.5)
        self.assertEqual(session["lesson"]["audio_parts"], [second])
        self.assertTrue(
            os.path.isdir(os.path.join(self.courses, "Analisi 2", "Lezioni"))
        )

    def test_a_failing_summary_does_not_fail_the_lesson(self):
        client = self._client()
        original = client.models.generate_content.side_effect

        def generate(model, contents, config):
            if "tutor universitario" in str(getattr(config, "system_instruction", "")):
                raise ValueError("400 INVALID_ARGUMENT")
            return original(model, contents, config)

        client.models.generate_content.side_effect = generate
        session = self._run(LessonSources(course="Fisica"), client)
        self.assertEqual(self.adapter.last_run_status, "completed")
        lessons = os.path.join(self.courses, "Fisica", "Lezioni")
        self.assertEqual(len(os.listdir(lessons)), 1)
        self.assertFalse(os.path.isdir(os.path.join(self.courses, "Fisica", "Sintesi")))
        self.assertNotIn("summary_html", session.get("outputs", {}))

    def test_book_revision_that_drops_content_is_rejected(self):
        self._run(
            LessonSources(book_path=self.book),
            self._client(revision_text="## Corto"),
        )
        revision = [c for c in self.calls if c["revision"]]
        # the short answer is retried and the block ends up unrevised
        self.assertGreater(len(revision), 1)
        self.assertEqual(self.adapter.last_run_status, "completed_with_warnings")

    def test_audio_only_is_unchanged(self):
        self._run(LessonSources(), self._client())
        transcription = [c for c in self.calls if not c["revision"]]
        self.assertNotIn("REGOLA 5", transcription[0]["system"])
        self.assertNotIn("application/pdf", transcription[0]["kinds"])
        revision = [c for c in self.calls if c["revision"]]
        self.assertNotIn("ESTRATTO DEL LIBRO", revision[0]["system"])

    def test_missing_slides_fail_before_any_request(self):
        with patch("google.genai.Client", return_value=self._client()):
            esegui_sbobinatura(
                input_path=self.audio,
                api_key_value="test-key",
                app_instance=self.adapter,
                session_dir_hint=self.session_dir,
                lesson=LessonSources(slides_path=os.path.join(self.tmp, "manca.pdf")),
            )
        self.assertEqual(self.adapter.last_run_status, "failed")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
