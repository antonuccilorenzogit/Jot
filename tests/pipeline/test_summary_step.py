"""The sintesi at the end of a lesson: one request, never breaks the lesson."""

import os
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from jot.pipeline import summary_step
from jot.services.archive_service import _summary_field

SUMMARY = (
    "# x\n\n## Concetti chiave\n- uno\n\n## Formule\n$$CdV = RI + A - RF$$\n"
    + "testo " * 60
)


class _Runtime:
    def __init__(self):
        self.phases = []

    def cancelled(self):
        return False

    def phase(self, text):
        self.phases.append(text)


class SummaryStepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = {"title": "Economia lezione 1", "course": "Economia"}
        self.saved = 0

    def _save(self):
        self.saved += 1

    def _run(self):
        return summary_step.run_summary_step(
            client="client",
            session_ctx=SimpleNamespace(session_dir=self.tmp.name),
            session=self.session,
            save_session=self._save,
            model_name="gemini-2.5-flash",
            model_state=None,
            phase2_revised_dir=os.path.join(self.tmp.name, "nope"),
            revised_text="## Magazzino\n\nIl costo del venduto \\(CdV\\) ...",
            runtime=_Runtime(),
            fallback_keys=[],
            request_fallback_key=lambda: None,
        )

    def test_writes_the_summary_and_links_it_to_the_lesson(self):
        with patch.object(
            summary_step, "generate_summary", return_value=("client2", SUMMARY)
        ) as gen:
            client = self._run()
        self.assertEqual(client, "client2")
        self.assertIn("CdV", gen.call_args.kwargs["notes"])
        path = str(self.session["outputs"]["summary_html"])  # type: ignore[index]
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-math-block="CdV = RI + A - RF"', html)
        self.assertIn("Sintesi · Economia · Economia lezione 1", html)
        self.assertEqual(self.saved, 1)
        self.assertEqual(
            _summary_field({"outputs": {"summary_html": path}}), {"summary_html": path}
        )

    def test_a_resumed_lesson_reuses_the_summary_without_a_new_request(self):
        with patch.object(
            summary_step, "generate_summary", return_value=("c", SUMMARY)
        ):
            self._run()
        with patch.object(summary_step, "generate_summary") as gen:
            self._run()
        gen.assert_not_called()

    def test_a_failed_summary_does_not_stop_the_lesson(self):
        with patch.object(
            summary_step, "generate_summary", side_effect=RuntimeError("503")
        ):
            self.assertEqual(self._run(), "client")
        self.assertNotIn("outputs", self.session)

    def test_heading(self):
        day = date(2026, 10, 13)
        self.assertEqual(
            summary_step.summary_heading(
                {"title": "Lezione 3", "course": "Fisica"}, day
            ),
            "Sintesi · Fisica · Lezione 3 · 13/10/2026",
        )
        self.assertEqual(
            summary_step.summary_heading(
                {"input": {"path": "/a/Economia 13 ott.m4a"}}, day
            ),
            "Sintesi · Economia 13 ott · 13/10/2026",
        )


if __name__ == "__main__":
    unittest.main()
