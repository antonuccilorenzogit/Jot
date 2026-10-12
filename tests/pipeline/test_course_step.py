"""The course step reuses a saved sintesi (used again after a block retry)."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jot.pipeline.course_step import SUMMARY_MD, run_course_step


class _Runtime:
    def cancelled(self) -> bool:
        return False

    def phase(self, _text: str) -> None:
        pass


class CourseStepTests(unittest.TestCase):
    def test_refresh_reuses_the_saved_sintesi_and_the_same_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = os.path.join(tmp, "session")
            revised = os.path.join(session_dir, "phase2_revised")
            os.makedirs(revised)
            with open(os.path.join(revised, "rev_001.md"), "w", encoding="utf-8") as f:
                f.write("## Contratto\n\nIl contratto e' un accordo.\n")
            with open(
                os.path.join(session_dir, SUMMARY_MD), "w", encoding="utf-8"
            ) as f:
                f.write("## Concetti chiave\n- Il contratto e' un accordo.\n" * 10)
            session = {"course": "Diritto privato", "lesson_date": "2026-10-12"}
            client = MagicMock()
            kwargs = dict(
                client=client,
                session_ctx=SimpleNamespace(session_dir=session_dir),
                session=session,
                save_session=lambda: True,
                model_name="m",
                model_state=None,
                phase2_revised_dir=revised,
                revised_text="",
                runtime=_Runtime(),
                fallback_keys=[],
                request_fallback_key=lambda: None,
            )
            with patch.dict(os.environ, {"JOT_COURSE_ROOT": os.path.join(tmp, "jot")}):
                run_course_step(**kwargs)
                first = dict(session["course_output"])
                with open(
                    os.path.join(revised, "rev_001.md"), "w", encoding="utf-8"
                ) as f:
                    f.write("## Contratto\n\nTesto rivisto dopo il retry.\n")
                run_course_step(**kwargs)

            client.models.generate_content.assert_not_called()
            self.assertEqual(session["course_output"], first)
            lessons = os.path.join(tmp, "jot", "Diritto privato", "Lezioni")
            self.assertEqual(os.listdir(lessons), ["L 12-10-2026.html"])
            with open(first["lesson_file"], encoding="utf-8") as f:
                self.assertIn("Testo rivisto dopo il retry", f.read())
            summaries = os.path.join(tmp, "jot", "Diritto privato", "Sintesi")
            self.assertEqual(os.listdir(summaries), ["S 12-10-2026.html"])


if __name__ == "__main__":
    unittest.main()
