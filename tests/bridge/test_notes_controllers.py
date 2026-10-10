import os
import tempfile
import threading
import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch

from jot.bridge.controllers.media_controller import MediaControllerMixin
from jot.services import archive_service
from tests.services.test_document_service import make_pdf


class _Host(MediaControllerMixin):
    def __init__(self, window=None):
        self._window = window
        self._adapter = cast(Any, MagicMock())
        self.console: list[str] = []

    def _push_console(self, msg: str) -> None:
        self.console.append(msg)


class NotesValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.slides = make_pdf(os.path.join(self.tmp.name, "slide.pdf"), 8)
        self.book = make_pdf(os.path.join(self.tmp.name, "libro.pdf"), 30)
        self.host = _Host()

    def test_notes_item_is_validated_without_ffmpeg(self):
        files: list[Any] = [
            {
                "id": "n1",
                "path": self.slides,
                "name": "slide.pdf",
                "kind": "notes",
                "book_path": self.book,
                "book_pages": "3-9",
            }
        ]
        with patch("jot.services.audio_service.probe_media_duration") as probe:
            self.assertIsNone(self.host._validate_processing_files(files))
            probe.assert_not_called()
        self.assertEqual(files[0]["duration"], 0.0)

    def test_bad_book_range_reported(self):
        files: list[Any] = [
            {
                "id": "n1",
                "path": self.slides,
                "name": "slide.pdf",
                "kind": "notes",
                "book_path": self.book,
                "book_pages": "25-90",
            }
        ]
        error = self.host._validate_processing_files(files)
        self.assertIsNotNone(error)
        self.assertIn("fuori dal documento", str(error))

    def test_missing_slides_reported(self):
        files: list[Any] = [
            {
                "id": "n1",
                "path": os.path.join(self.tmp.name, "x.pdf"),
                "name": "x",
                "kind": "notes",
            }
        ]
        self.assertIn("non trovato", str(self.host._validate_processing_files(files)))

    def test_audio_items_still_use_media_validation(self):
        files: list[Any] = [{"id": "a", "path": self.slides, "name": "slide.pdf"}]
        self.assertIn(
            "Formato non supportato", str(self.host._validate_processing_files(files))
        )

    def test_inspect_document(self):
        res = self.host.inspect_document(self.slides, "slides")
        self.assertTrue(res["ok"])
        self.assertEqual(res["file"]["pages"], 8)
        self.assertEqual(res["file"]["format"], "pdf")
        bad = self.host.inspect_document(self.slides, "book")
        self.assertTrue(bad["ok"])  # a PDF is also a valid book
        pptx_as_book = os.path.join(self.tmp.name, "x.pptx")
        with open(pptx_as_book, "wb") as handle:
            handle.write(b"x")
        self.assertFalse(self.host.inspect_document(pptx_as_book, "book")["ok"])

    def test_inspect_large_book_is_allowed(self):
        big = make_pdf(os.path.join(self.tmp.name, "big.pdf"), 310)
        res = self.host.inspect_document(big, "book")
        self.assertTrue(res["ok"])
        self.assertEqual(res["file"]["pages"], 310)

    def test_ask_document_file_cancel_and_select(self):
        window = MagicMock()
        window.create_file_dialog.return_value = None
        host = _Host(window)
        self.assertTrue(host.ask_document_file("slides").get("cancelled"))
        window.create_file_dialog.return_value = [self.book]
        res = host.ask_document_file("book")
        self.assertTrue(res["ok"])
        self.assertEqual(res["file"]["name"], "libro.pdf")


class NotesArchiveTests(unittest.TestCase):
    def test_archive_exposes_kind_and_notes_info(self):
        import json

        with tempfile.TemporaryDirectory() as root:
            session_dir = os.path.join(root, "notes_abc")
            os.makedirs(session_dir)
            html = os.path.join(session_dir, "Lezione_Sbobina.html")
            with open(html, "w", encoding="utf-8") as handle:
                handle.write("<html></html>")
            data = {
                "stage": "done",
                "kind": "notes",
                "notes": {
                    "total_slides": 40,
                    "book_name": "Libro.pdf",
                    "book_pages": "1-9",
                },
                "input": {"path": os.path.join(root, "Lezione.pdf"), "size": 10},
                "outputs": {"html": html},
                "updated_at": "2026-10-10T10:00:00Z",
            }
            with open(
                os.path.join(session_dir, "session.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(data, handle)
            sessions, total = archive_service.list_completed_sessions(root, limit=0)
            self.assertEqual(total, 1)
            self.assertEqual(sessions[0]["kind"], "notes")
            self.assertEqual(
                sessions[0]["notes_info"],
                {"total_slides": 40, "book_name": "Libro.pdf", "book_pages": "1-9"},
            )


class NotesPipelineDispatchTests(unittest.TestCase):
    def test_start_processing_routes_notes_items(self):
        from jot.app_webview import JotApi

        with tempfile.TemporaryDirectory() as td:
            slides = make_pdf(os.path.join(td, "slide.pdf"), 4)
            api = JotApi()
            done = threading.Event()
            calls: list[tuple] = []

            def fake_appunti(*args, **kwargs):
                calls.append((args, kwargs))
                api._adapter.last_run_status = "completed"
                done.set()

            with (
                patch(
                    "jot.pipeline.notes_pipeline.esegui_appunti",
                    side_effect=fake_appunti,
                ),
                patch("jot.pipeline.pipeline.esegui_sbobinatura") as audio,
                patch(
                    "jot.bridge.controllers.pipeline_controller.network_service.check_connectivity",
                    return_value=True,
                ),
                patch("jot.bridge.controllers.pipeline_controller.save_config"),
                patch(
                    "jot.bridge.controllers.pipeline_controller._handle_file_completed",
                    return_value=("completed", True),
                ),
            ):
                res = api.start_processing(
                    [
                        {
                            "id": "n1",
                            "path": slides,
                            "name": "slide.pdf",
                            "kind": "notes",
                            "book_pages": "",
                            "slides_per_chunk": 10,
                        }
                    ],
                    "AIzaTEST_KEY_1234567890123456",
                )
                self.assertTrue(res["ok"], res)
                self.assertTrue(done.wait(5))
                thread = api._processing_thread
                if thread is not None:
                    thread.join(5)
                audio.assert_not_called()
            self.assertEqual(len(calls), 1)
            args, kwargs = calls[0]
            self.assertEqual(args[0], slides)
            self.assertIsNone(kwargs["book_path"])
            self.assertEqual(kwargs["slides_per_chunk"], 10)


if __name__ == "__main__":
    unittest.main()


class NotesStreamTests(unittest.TestCase):
    def test_slides_source_reports_no_audio(self):
        with tempfile.TemporaryDirectory() as td:
            slides = make_pdf(os.path.join(td, "slide.pdf"), 2)
            host = _Host()
            path, has_audio, error = host._resolve_stream_media_path(slides)
            self.assertIsNone(path)
            self.assertFalse(has_audio)
            self.assertIn("slide", str(error))


class LessonControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.slides = make_pdf(os.path.join(self.tmp.name, "slide.pdf"), 8)
        self.book = make_pdf(os.path.join(self.tmp.name, "libro.pdf"), 30)
        self.host = _Host()

    def test_audio_lesson_documents_are_validated(self):
        item: Any = {"book_path": self.book, "book_pages": "25-90"}
        self.assertIn(
            "fuori dal documento", str(self.host._validate_lesson_documents(item))
        )
        item = {"slides_path": os.path.join(self.tmp.name, "manca.pdf")}
        self.assertIn("non trovato", str(self.host._validate_lesson_documents(item)))
        item = {"slides_path": self.slides, "book_path": self.book, "book_pages": "1-5"}
        self.assertIsNone(self.host._validate_lesson_documents(item))

    def test_suggest_lesson_uses_file_names(self):
        audio = os.path.join(self.tmp.name, "Reti_lezione_5.m4a")
        with open(audio, "wb") as handle:
            handle.write(b"x")
        res = self.host.suggest_lesson(audio, None, None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["title"], "Reti lezione 5")
        self.assertIsNone(res["chapter"])

    def test_lesson_items_get_their_own_session_folder(self):
        from jot.bridge.controllers.pipeline_controller import (
            session_paths_for_item,
        )

        audio = os.path.join(self.tmp.name, "a.m4a")
        with open(audio, "wb") as handle:
            handle.write(b"x")
        plain = session_paths_for_item(cast(Any, {"path": audio}))
        with_slides = session_paths_for_item(
            cast(Any, {"path": audio, "slides_path": self.slides})
        )
        self.assertNotEqual(plain.session_dir, with_slides.session_dir)
        self.assertTrue(os.path.basename(with_slides.session_dir).startswith("lesson_"))
