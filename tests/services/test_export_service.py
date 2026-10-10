import os
import tempfile
import unittest

from jot.services.export_service import (
    REVISION_WARNING_TEXT,
    export_final_html_document,
    resolve_output_html_path,
)


class ExportServiceTests(unittest.TestCase):
    def test_resolve_output_html_path_uses_audio_name(self):
        titolo, html_path = resolve_output_html_path(
            input_path="lesson.mp3",
            output_dir="C:/tmp",
            fallback_output_dir="C:/fallback",
            safe_output_basename=lambda value: value,
        )
        self.assertEqual(titolo, "lesson")
        self.assertTrue(html_path.endswith("lesson_Sbobina.html"))

    def test_export_final_html_document_writes_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            revised_dir = os.path.join(tmpdir, "revised")
            os.makedirs(revised_dir, exist_ok=True)
            with open(
                os.path.join(revised_dir, "rev_001.md"), "w", encoding="utf-8"
            ) as handle:
                handle.write("## Titolo\n\nCorpo di test")

            def read_text(path: str) -> str:
                with open(path, encoding="utf-8") as handle:
                    return handle.read()

            _, html_path = export_final_html_document(
                input_path="lesson.mp3",
                phase2_revised_dir=revised_dir,
                fallback_body="fallback",
                read_text=read_text,
                output_dir=tmpdir,
                fallback_output_dir=tmpdir,
                safe_output_basename=lambda value: value,
            )

            self.assertTrue(os.path.exists(html_path))

    def test_export_final_html_document_includes_warning_banner_for_failed_revisions(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            revised_dir = os.path.join(tmpdir, "revised")
            os.makedirs(revised_dir, exist_ok=True)
            with open(
                os.path.join(revised_dir, "rev_001.md"), "w", encoding="utf-8"
            ) as handle:
                handle.write("Corpo non completamente revisionato")

            def read_text(path: str) -> str:
                with open(path, encoding="utf-8") as handle:
                    return handle.read()

            _, html_path = export_final_html_document(
                input_path="lesson.mp3",
                phase2_revised_dir=revised_dir,
                fallback_body="fallback",
                read_text=read_text,
                output_dir=tmpdir,
                fallback_output_dir=tmpdir,
                safe_output_basename=lambda value: value,
                revision_failed_blocks=[1],
            )

            with open(html_path, encoding="utf-8") as handle:
                html = handle.read()
            self.assertIn(REVISION_WARNING_TEXT, html)
            self.assertIn("revision-warning-banner", html)


class LoadRevisedBlocksTests(unittest.TestCase):
    def _write_rev(self, directory, name, content):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def _read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_blocks_returned_in_numeric_order(self):
        from jot.services.export_service import load_revised_blocks

        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_rev(tmpdir, "rev_003.md", "third")
            self._write_rev(tmpdir, "rev_001.md", "first")
            self._write_rev(tmpdir, "rev_002.md", "second")
            blocks = load_revised_blocks(tmpdir, self._read)

        self.assertEqual(blocks, ["first", "second", "third"])

    def test_raw_md_files_excluded(self):
        from jot.services.export_service import load_revised_blocks

        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_rev(tmpdir, "rev_001.md", "good")
            self._write_rev(tmpdir, "rev_002.raw.md", "should-be-excluded")
            blocks = load_revised_blocks(tmpdir, self._read)

        self.assertEqual(blocks, ["good"])

    def test_empty_dir_returns_empty_list(self):
        from jot.services.export_service import load_revised_blocks

        with tempfile.TemporaryDirectory() as tmpdir:
            blocks = load_revised_blocks(tmpdir, self._read)

        self.assertEqual(blocks, [])

    def test_missing_dir_returns_empty_list(self):
        from jot.services.export_service import load_revised_blocks

        blocks = load_revised_blocks("/no/such/dir", self._read)
        self.assertEqual(blocks, [])


class BuildFinalMarkdownTests(unittest.TestCase):
    def test_empty_blocks_uses_fallback_body(self):
        from jot.services.export_service import build_final_markdown

        result = build_final_markdown("Titolo", [], "fallback content")
        self.assertIn("fallback content", result)

    def test_title_included_in_output(self):
        from jot.services.export_service import build_final_markdown

        result = build_final_markdown("Lezione 1", ["## Intro\n\nTesto"], "")
        self.assertIn("Lezione 1", result)


class ResolveOutputHtmlPathTests(unittest.TestCase):
    def test_empty_input_path_uses_fallback_filename(self):
        from jot.services.export_service import resolve_output_html_path

        _, html_path = resolve_output_html_path(
            input_path="",
            output_dir="/out",
            fallback_output_dir="/fallback",
            safe_output_basename=lambda v: v,
        )
        self.assertIn("Sbobina_Definitiva.html", html_path)


if __name__ == "__main__":
    unittest.main()
