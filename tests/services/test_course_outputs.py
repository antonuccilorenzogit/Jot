from __future__ import annotations

import glob
import os
import shutil
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from jot.services import course_outputs as co


class NamesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dates(self):
        day = co.parse_lesson_date("2026-10-12")
        self.assertEqual(co.file_date(day), "12-10-2026")
        self.assertEqual(co.text_date(day), "12/10/2026")
        self.assertEqual(co.parse_lesson_date("boh"), date.today())

    def test_course_folders(self):
        paths = co.course_paths("Diritto privato", self.tmp)
        self.assertEqual(
            paths.lessons, os.path.join(self.tmp, "Diritto privato", "Lezioni")
        )
        self.assertEqual(
            paths.summaries, os.path.join(self.tmp, "Diritto privato", "Sintesi")
        )
        self.assertEqual(co.course_paths(None, self.tmp).course, co.NO_COURSE)
        self.assertEqual(co.safe_folder_name('Reti: "corso" A/B'), "Reti corso A B")

    def test_course_root_override(self):
        with patch.dict(os.environ, {"JOT_COURSE_ROOT": self.tmp}):
            self.assertEqual(co.course_root({}), self.tmp)
        with patch.dict(os.environ, {"JOT_COURSE_ROOT": ""}):
            self.assertEqual(co.course_root({"course_root": "/x"}), "/x")
            self.assertTrue(
                co.course_root({}).endswith(os.path.join("Documents", "jot"))
                or co.course_root({}).endswith("jot")
            )

    def test_lesson_numbers_and_unique_names(self):
        self.assertEqual(co.next_lesson_number(self.tmp), 1)
        for name in ("L 01-10-2026.pdf", "L 05-10-2026.html", "note.txt"):
            open(os.path.join(self.tmp, name), "w").close()
        self.assertEqual(co.next_lesson_number(self.tmp), 3)
        self.assertEqual(
            co.unique_stem(self.tmp, "L 01-10-2026", set()), "L 01-10-2026 (2)"
        )
        own = {os.path.normcase(os.path.join(self.tmp, "L 01-10-2026.pdf"))}
        self.assertEqual(co.unique_stem(self.tmp, "L 01-10-2026", own), "L 01-10-2026")
        self.assertEqual(
            co.unique_stem(self.tmp, "L 02-10-2026", set()), "L 02-10-2026"
        )


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_formulas_become_mathml_and_html_is_sanitized(self):
        html = co.markdown_to_print_html(
            "S 12-10-2026",
            "# Titolo\n\nNel testo $v = \\frac{s}{t}$.\n\n$$E = mc^2$$\n\n<script>alert(1)</script>\n\n[[t=120]] fine",
        )
        self.assertIn('display="inline"', html)
        self.assertIn('display="block"', html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("[[t=", html)
        self.assertIn("Georgia", html)

    def test_heading_is_forced(self):
        text = co.ensure_heading(
            "# Altro\n\n## Concetti chiave", "Fisica \u2013 Lezione 2 \u2013 12/10/2026"
        )
        self.assertTrue(text.startswith("# Fisica \u2013 Lezione 2 \u2013 12/10/2026"))
        self.assertTrue(co.ensure_heading("## Concetti", "H").startswith("# H\n"))
        self.assertIn("Lezione 4", co.summary_heading("Fisica", 4, date(2026, 10, 12)))

    def test_html_kept_when_no_pdf_printer(self):
        with patch.dict(os.environ, {"JOT_NO_PDF": "1"}):
            path = co.write_document(
                self.tmp, "L 12-10-2026", "L 12-10-2026", "# L\n\ntesto"
            )
        self.assertTrue(path.endswith("L 12-10-2026.html"))

    @unittest.skipUnless(
        glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome"),
        "no local Chromium",
    )
    def test_pdf_with_a_chromium_browser(self):
        browser = glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome")[0]
        with (
            patch.dict(os.environ, {"JOT_NO_PDF": "0"}),
            patch.object(co, "_browser_candidates", return_value=[browser]),
        ):
            path = co.write_document(
                self.tmp, "S 12-10-2026", "S", "# S\n\n$$a^2+b^2=c^2$$"
            )
        self.assertTrue(path.endswith(".pdf"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "S 12-10-2026.html")))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(4), b"%PDF")


if __name__ == "__main__":
    unittest.main()
