import json
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from jot.core import session_store
from jot.pipeline import notes_pipeline
from jot.services import generation_service, notes_service
from jot.services.generation_service import DegenerateOutputError
from tests.services.test_book_retrieval import (
    TOPICS,
    FakeEmbedClient,
    build_book,
    build_slides,
)
from tests.services.test_document_service import make_pdf, make_pptx


def _notes_text(tag: str, slides: int) -> str:
    paragraphs = [f"## Argomento {tag}\n_Slide {tag}_"]
    for n in range(slides):
        paragraphs.append(
            f"Paragrafo {tag}-{n}: spiegazione completa e approfondita del concetto "
            f"numero {n} con definizioni, esempi e collegamenti logici unici ({tag})."
        )
    return "\n\n".join(paragraphs)


class _FakeFiles:
    def __init__(self, log):
        self.log = log
        self.counter = 0

    def upload(self, file=None, path=None, config=None):
        self.counter += 1
        self.log.append(("upload", os.path.basename(file or path or ""), config))
        return SimpleNamespace(
            name=f"files/{self.counter}",
            uri=f"https://files.test/{self.counter}",
            mime_type="application/pdf",
            state="ACTIVE",
        )

    def get(self, name=None):
        return SimpleNamespace(
            name=name, uri="u", mime_type="application/pdf", state="ACTIVE"
        )

    def delete(self, name=None):
        self.log.append(("delete", name, None))


class _FakeModels:
    def __init__(self, log, responder):
        self.log = log
        self.responder = responder
        self.embed_content: Any = None

    def generate_content(self, model=None, contents=None, config=None):
        self.log.append(("generate", model, contents, config))
        return SimpleNamespace(text=self.responder(model, contents, config))


class _FakeClient:
    def __init__(self, responder, log):
        self.api_key = "AIzaTEST_KEY_1234567890123456"
        self.files = _FakeFiles(log)
        self.models = _FakeModels(log, responder)
        embedder = FakeEmbedClient()
        self.embed_calls = embedder.calls

        def _embed(model=None, contents=None, config=None):
            log.append(("embed", model, None, None))
            return embedder.models.embed_content(
                model=model, contents=contents, config=config
            )

        self.models.embed_content = _embed


class _App:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.file_temporanei = []
        self.last_run_status = "idle"
        self.last_run_error = None
        self.last_run_error_detail = None
        self.effective_api_key = None
        self.phases = []
        self.outputs = []

    def winfo_exists(self):
        return True

    def aggiorna_progresso(self, value):
        return None

    def aggiorna_fase(self, text):
        self.phases.append(text)

    def imposta_output_html(self, path, output_dir=None):
        self.outputs.append(path)

    def processo_terminato(self):
        return None


def _default_responder(model, contents, config):
    prompt = contents[-1]
    if isinstance(prompt, str) and "slide" in prompt and "su " in prompt:
        # extract "slide a-b"
        import re

        match = re.search(r"slide (\d+)-(\d+)", prompt)
        start, end = (int(match.group(1)), int(match.group(2))) if match else (1, 1)
        return _notes_text(f"{start}-{end}", (end - start + 1) * 2)
    # revision call: echo the block back
    return str(contents[0])


class NotesPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "sessions")
        os.makedirs(self.root)
        previous_root = session_store.get_session_root()
        session_store.set_session_root(self.root)
        self.addCleanup(session_store.set_session_root, previous_root)
        generation_service.reset_global_governor()
        self.log = []
        patcher = patch.object(notes_service, "sleep_with_cancel", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, slides, responder=_default_responder, **kwargs):
        app = _App()
        client = _FakeClient(responder, self.log)
        with (
            patch.object(notes_pipeline, "create_gemini_client", return_value=client),
            patch.object(notes_pipeline, "load_fallback_keys", return_value=[]),
        ):
            notes_pipeline.esegui_appunti(
                slides, "AIzaTEST_KEY_1234567890123456", app, **kwargs
            )
        return app

    def _session(self, slides, book=None, pages="", mode="full"):
        session_dir = notes_pipeline.notes_session_dir(slides, book, pages, mode)
        with open(
            os.path.join(session_dir, "session.json"), encoding="utf-8"
        ) as handle:
            return session_dir, json.load(handle)

    def test_pdf_slides_with_book_end_to_end(self):
        slides = make_pdf(os.path.join(self.tmp.name, "Lezione 3.pdf"), 26)
        book = make_pdf(os.path.join(self.tmp.name, "Libro.pdf"), 40)
        app = self._run(slides, book_path=book, book_pages="10-14", slides_per_chunk=12)

        self.assertEqual(app.last_run_status, "completed", app.last_run_error)
        self.assertEqual(len(app.outputs), 1)
        self.assertTrue(app.outputs[0].endswith("_Sbobina.html"))
        session_dir, session = self._session(slides, book, "10-14")
        self.assertEqual(session["kind"], "notes")
        self.assertEqual(session["stage"], "done")
        self.assertEqual(session["notes"]["total_slides"], 26)
        self.assertEqual(session["notes"]["book_pages"], "10-14")
        self.assertEqual(session["notes"]["book_pages_count"], 5)

        generations = [e for e in self.log if e[0] == "generate"]
        notes_calls = [e for e in generations if "Scrivi gli appunti" in str(e[2][-1])]
        # 26 slides / 12 -> (1-12), (13-26): small tail merged
        self.assertEqual(len(notes_calls), 2)
        for call in notes_calls:
            config = call[3]
            self.assertIn("Autore di Dispense Universitarie", config.system_instruction)
            self.assertIn("pagine 10-14 del libro", call[2][-1])
        # book uploaded once and deleted at the end; excerpt removed when done
        uploads = [e for e in self.log if e[0] == "upload"]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0][1], notes_pipeline.BOOK_EXCERPT_FILENAME)
        self.assertTrue(any(e[0] == "delete" for e in self.log))
        self.assertFalse(
            os.path.exists(
                os.path.join(session_dir, notes_pipeline.BOOK_EXCERPT_FILENAME)
            )
        )
        with open(app.outputs[0], encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("Argomento 1-12", html)
        self.assertIn("Argomento 13-26", html)
        self.assertTrue(
            any(p.startswith("Fase 1/3: appunti (chunk 2/2)") for p in app.phases)
        )
        # revision ran with the notes revision prompt
        revision_calls = [e for e in generations if e not in notes_calls]
        self.assertTrue(revision_calls)
        self.assertIn("_Slide 4-7_", revision_calls[0][3].system_instruction)

    def test_pptx_slides_without_book(self):
        slides = make_pptx(os.path.join(self.tmp.name, "lezione.pptx"), 6)
        app = self._run(slides)
        self.assertEqual(app.last_run_status, "completed", app.last_run_error)
        call = next(e for e in self.log if e[0] == "generate")
        contents = call[2]
        self.assertIn("### Slide 1: Titolo 1", contents[0])
        self.assertIn("presentazione PowerPoint", contents[-1])
        self.assertNotIn("LIBRO", contents[-1])
        self.assertFalse(any(e[0] == "upload" for e in self.log))

    def test_degenerate_output_is_retried_then_resumable(self):
        slides = make_pdf(os.path.join(self.tmp.name, "slide.pdf"), 24)
        state = {"calls": 0}

        def responder(model, contents, config):
            state["calls"] += 1
            prompt = str(contents[-1])
            if "slide 13-24" in prompt:
                return "Riassunto breve."  # too short for 12 slides
            return _default_responder(model, contents, config)

        app = self._run(slides, responder=responder)
        self.assertNotEqual(app.last_run_status, "completed")
        session_dir, session = self._session(slides)
        self.assertEqual(session["stage"], "phase1")
        self.assertEqual(session["last_error"], "phase1_degenerate_output")
        self.assertEqual(session["phase1"]["chunks_done"], 1)
        chunks = sorted(os.listdir(os.path.join(session_dir, "phase1_chunks")))
        self.assertEqual(chunks, ["chunk_001_1_12.md"])
        # second block was attempted twice (normal + recovery pass)
        too_short = [
            e for e in self.log if e[0] == "generate" and "slide 13-24" in str(e[2][-1])
        ]
        self.assertEqual(len(too_short), 2)

        # Resume: only the missing block is regenerated
        self.log.clear()
        app2 = self._run(slides, resume_session=True)
        self.assertEqual(app2.last_run_status, "completed", app2.last_run_error)
        notes_calls = [
            e
            for e in self.log
            if e[0] == "generate" and "Scrivi gli appunti" in str(e[2][-1])
        ]
        self.assertEqual(len(notes_calls), 1)
        self.assertIn("slide 13-24", notes_calls[0][2][-1])
        self.assertIn("stai continuando", notes_calls[0][2][-1])

    def test_invalid_slides_fail_fast_without_api_calls(self):
        bad = os.path.join(self.tmp.name, "slide.ppt")
        with open(bad, "wb") as handle:
            handle.write(b"x")
        app = self._run(bad)
        self.assertEqual(app.last_run_status, "failed")
        self.assertIn(".pptx", str(app.last_run_error))
        self.assertEqual(self.log, [])

    def test_auto_book_mode_sends_only_relevant_pages(self):
        from pypdf import PdfReader

        book = build_book(os.path.join(self.tmp.name, "book.pdf"))
        topics = ["dns"] * 12 + ["routing"] * 12
        slides = build_slides(os.path.join(self.tmp.name, "slides.pdf"), topics)
        app = self._run(slides, book_path=book, book_mode="auto", slides_per_chunk=12)
        self.assertEqual(app.last_run_status, "completed", app.last_run_error)

        session_dir, session = self._session(slides, book, "", "auto")
        plan = session["notes"]["book_plan"]
        self.assertEqual(plan["method"], "embeddings")
        self.assertEqual(session["notes"]["book_mode"], "auto")
        self.assertTrue(set(plan["blocks"][0]) <= set(range(10, 22)))
        self.assertTrue(set(plan["blocks"][1]) <= set(range(30, 41)))

        notes_calls = [
            e
            for e in self.log
            if e[0] == "generate" and "Scrivi gli appunti" in str(e[2][-1])
        ]
        self.assertEqual(len(notes_calls), 2)
        for call, pages in zip(notes_calls, plan["blocks"], strict=True):
            book_part = call[2][0]
            data = book_part.inline_data.data
            sub = os.path.join(self.tmp.name, "sub.pdf")
            with open(sub, "wb") as handle:
                handle.write(data)
            self.assertEqual(len(PdfReader(sub).pages), len(pages))
            self.assertIn("del libro", call[2][-1])
        self.assertFalse(any(e[0] == "upload" for e in self.log))
        # index and excerpt are cleaned up when the notes are done
        self.assertFalse(os.path.exists(os.path.join(session_dir, "book_index.json")))

        # Regenerating from a saved plan does not call the embedding model again.
        self.log.clear()
        session["stage"] = "phase1"
        session["phase1"] = {"chunks_done": 0}
        for name in os.listdir(os.path.join(session_dir, "phase1_chunks")):
            os.remove(os.path.join(session_dir, "phase1_chunks", name))
        with open(
            os.path.join(session_dir, "session.json"), "w", encoding="utf-8"
        ) as handle:
            json.dump(session, handle)
        with patch.object(
            notes_pipeline,
            "_handle_regeneration_flow",
            return_value=("proceed", "phase1", False),
        ):
            app2 = self._run(
                slides,
                book_path=book,
                book_mode="auto",
                slides_per_chunk=12,
                resume_session=True,
            )
        self.assertEqual(app2.last_run_status, "completed", app2.last_run_error)
        self.assertFalse(any(e[0] == "embed" for e in self.log))

    def test_auto_mode_without_relevant_pages_skips_the_book(self):
        book = build_book(os.path.join(self.tmp.name, "book.pdf"))
        slides = make_pdf(os.path.join(self.tmp.name, "blank.pdf"), 12)
        app = self._run(slides, book_path=book, book_mode="auto")
        self.assertEqual(app.last_run_status, "completed", app.last_run_error)
        _dir, session = self._session(slides, book, "", "auto")
        # Slides without any text: matching is impossible, whole excerpt is used.
        self.assertEqual(session["notes"]["book_plan"]["method"], "full")
        self.assertTrue(TOPICS)

    def test_session_dir_depends_on_book_and_pages(self):
        slides = make_pdf(os.path.join(self.tmp.name, "slide.pdf"), 5)
        book = make_pdf(os.path.join(self.tmp.name, "libro.pdf"), 5)
        a = notes_pipeline.notes_session_dir(slides)
        b = notes_pipeline.notes_session_dir(slides, book, "1-2")
        c = notes_pipeline.notes_session_dir(slides, book, "1 - 2")
        d = notes_pipeline.notes_session_dir(slides, book, "3")
        self.assertNotEqual(a, b)
        self.assertEqual(b, c)
        self.assertNotEqual(b, d)
        self.assertTrue(os.path.basename(a).startswith("notes_"))
        # legacy "full" mode keeps the folder of existing sessions
        self.assertEqual(
            b, notes_pipeline.notes_session_dir(slides, book, "1-2", "full")
        )
        self.assertNotEqual(
            b, notes_pipeline.notes_session_dir(slides, book, "1-2", "auto")
        )
        self.assertEqual(a, notes_pipeline.notes_session_dir(slides, None, "", "auto"))


class NotesGuardrailTests(unittest.TestCase):
    def test_too_short_detection(self):
        self.assertIsNone(notes_service.detect_notes_too_short("x", 2))
        self.assertIsNotNone(notes_service.detect_notes_too_short("x" * 100, 10))
        self.assertIsNone(notes_service.detect_notes_too_short("x" * 1000, 10))

    def test_repeated_paragraph_rejected(self):
        para = "Questo paragrafo ripetuto descrive sempre la stessa cosa in modo identico e lungo."
        text = "\n\n".join([para] * 5)
        with self.assertRaises(DegenerateOutputError):
            notes_service.validate_notes_output(text, 1)

    def test_prompt_mentions_real_slide_numbers(self):
        prompt = notes_service.build_notes_chunk_prompt(
            start=13, end=24, total=40, previous_tail="fine", book_pages_label="5-9"
        )
        self.assertIn("slide 13-24 (su 40 totali)", prompt)
        self.assertIn("la prima pagina del PDF è la slide 13", prompt)
        self.assertIn("pagine 5-9 del libro", prompt)
        self.assertIn('"...fine"', prompt)


if __name__ == "__main__":
    unittest.main()
