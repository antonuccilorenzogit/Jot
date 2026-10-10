import os
import tempfile
import unittest
from unittest.mock import patch

from jot.services.generation_service import QuotaDailyLimitError
from jot.services.revision_service import (
    build_macro_blocks,
    process_macro_revision_phase,
    retry_failed_revision_blocks,
)

# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


class _FakeRuntime:
    def phase(self, *a):
        pass

    def set_work_totals(self, **kw):
        pass

    def update_work_done(self, *a, **kw):
        pass

    def progress(self, v):
        pass

    def register_step_time(self, *a, **kw):
        pass


# ---------------------------------------------------------------------------
# build_macro_blocks
# ---------------------------------------------------------------------------


class TestBuildMacroBlocks(unittest.TestCase):
    def test_heading_aware_split_past_soft_threshold(self):
        char_limit = 1000
        # body must be > 500 chars (has_content guard) AND > 70 % of limit (700 chars)
        body = "A" * 750
        text = body + "\n\n## Nuova Sezione\n\nContenuto della nuova sezione."
        blocks = build_macro_blocks(text, char_limit)
        self.assertEqual(len(blocks), 2, "H2 heading past 70 % should open a new block")
        self.assertTrue(
            blocks[1].strip().startswith("## Nuova Sezione"),
            "new block must start with the heading, not trail behind it",
        )

    def test_no_premature_split_before_soft_threshold(self):
        char_limit = 1000
        # Heading appears at only 200 chars — well below the 70 % (700 char) threshold
        text = "A" * 200 + "\n\n## Titolo Anticipato\n\nAltra roba qui."
        blocks = build_macro_blocks(text, char_limit)
        self.assertEqual(
            len(blocks),
            1,
            "heading appearing before 70 % of the limit must NOT trigger a split",
        )


class TestProcessMacroRevisionPhase(unittest.TestCase):
    def _make_session(self):
        return {"phase2": {"revised_done": 0}, "stage": "phase2", "last_error": None}

    def _run(self, macro_blocks, phase2_dir, session, rq_side_effect):
        """Run process_macro_revision_phase with mocked retry_with_quota and sleep."""
        with (
            patch(
                "jot.services.revision_service.retry_with_quota",
                side_effect=rq_side_effect,
            ),
            patch(
                "jot.services.revision_service.sleep_with_cancel",
                return_value=True,
            ),
        ):
            _, revised_text = process_macro_revision_phase(
                client=object(),
                model_name="test-model",
                macro_blocks=macro_blocks,
                phase2_revised_dir=phase2_dir,
                session=session,
                save_session=lambda: True,
                runtime=_FakeRuntime(),
                cancelled=lambda: False,
                fallback_keys=[],
                request_fallback_key=lambda: None,
                prompt_revisione="Revisiona.",
            )
        return revised_text

    def test_main_pass_success_writes_md_and_increments_revised_done(self):
        """Happy path: retry_with_quota succeeds → .md created, revised_done=1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def success(fn, *, client, **kw):
                return client, "Testo revisionato"

            self._run(["Blocco."], tmpdir, session, success)

            self.assertTrue(os.path.exists(os.path.join(tmpdir, "rev_001.md")))
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "rev_001.raw.md")))
            self.assertEqual(session["phase2"]["revised_done"], 1)
            self.assertEqual(session.get("revision_failed_blocks", []), [])

    def test_clean_main_pass_clears_stale_failed_blocks_and_warning_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()
            session.update(
                {
                    "revision_pending_blocks": [1],
                    "revision_failed_blocks": [1],
                    "completion_status": "completed_with_warnings",
                    "last_error": "stale_error",
                    "last_error_detail": "stale detail",
                }
            )

            def success(fn, *, client, **kw):
                return client, "Testo revisionato"

            self._run(["Blocco."], tmpdir, session, success)

            self.assertEqual(session.get("revision_pending_blocks"), [])
            self.assertEqual(session.get("revision_failed_blocks"), [])
            self.assertEqual(session.get("completion_status"), "completed")
            self.assertIsNone(session.get("last_error"))
            self.assertIsNone(session.get("last_error_detail"))

    def test_main_pass_failure_writes_raw_md_not_md(self):
        """Main pass fail → .raw.md written (not .md), retry pass also fails →
        finalized to .md with raw content, block in revision_failed_blocks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def always_fail(fn, *, client, **kw):
                raise RuntimeError("network error")

            self._run(["Blocco grezzo."], tmpdir, session, always_fail)

            self.assertTrue(os.path.exists(os.path.join(tmpdir, "rev_001.raw.md")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "rev_001.md")))
            self.assertIn(1, session.get("revision_failed_blocks", []))

    def test_resume_with_raw_md_goes_to_retry_pass_not_skipped_as_done(self):
        """On resume, a pre-existing .raw.md must trigger the retry pass,
        not be silently skipped like a completed block."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "rev_001.raw.md")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("Contenuto raw originale.\n")

            session = self._make_session()
            call_count = [0]

            def track_calls(fn, *, client, **kw):
                call_count[0] += 1
                return client, "Testo revisionato dal retry"

            self._run(["Contenuto raw originale."], tmpdir, session, track_calls)

            self.assertEqual(
                call_count[0],
                1,
                "retry_with_quota must be called exactly once (retry pass)",
            )
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "rev_001.md")))
            self.assertFalse(os.path.exists(raw_path))
            self.assertEqual(session.get("revision_failed_blocks", []), [])

    def test_retry_pass_success_removes_raw_md_and_creates_md(self):
        """Main pass fails → .raw.md; retry pass succeeds → .md created,
        .raw.md deleted, NOT in revision_failed_blocks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()
            calls = [0]

            def first_fail_then_success(fn, *, client, **kw):
                calls[0] += 1
                if calls[0] == 1:
                    raise RuntimeError("main pass fail")
                return client, "Testo dal retry"

            revised_text = self._run(
                ["Blocco."], tmpdir, session, first_fail_then_success
            )

            self.assertFalse(os.path.exists(os.path.join(tmpdir, "rev_001.raw.md")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "rev_001.md")))
            self.assertEqual(session.get("revision_failed_blocks", []), [])
            self.assertIn("Testo dal retry", revised_text)

    def test_retry_pass_definitive_failure_finalizes_to_md_and_records_failed_blocks(
        self,
    ):
        """Both main pass and retry pass fail → .raw.md renamed to .md (raw content preserved),
        block index recorded in session revision_failed_blocks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def always_fail(fn, *, client, **kw):
                raise RuntimeError("always fails")

            self._run(["Contenuto grezzo."], tmpdir, session, always_fail)

            rev_path = os.path.join(tmpdir, "rev_001.md")
            self.assertTrue(os.path.exists(rev_path))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "rev_001.raw.md")))
            self.assertIn(1, session.get("revision_failed_blocks", []))
            self.assertEqual(
                session.get("completion_status"), "completed_with_warnings"
            )

    def test_quota_in_retry_pass_leaves_raw_md_and_does_not_finalize(self):
        """Main pass fails (RuntimeError) → .raw.md written.
        Retry pass raises QuotaDailyLimitError → early return,
        .raw.md must remain on disk, last_error set, .md must NOT exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()
            calls = [0]

            def main_fail_retry_quota(fn, *, client, **kw):
                calls[0] += 1
                if calls[0] == 1:
                    raise RuntimeError("main pass fail")
                raise QuotaDailyLimitError("quota in retry")

            with (
                patch(
                    "jot.services.revision_service.retry_with_quota",
                    side_effect=main_fail_retry_quota,
                ),
                patch(
                    "jot.services.revision_service.sleep_with_cancel",
                    return_value=True,
                ),
            ):
                process_macro_revision_phase(
                    client=object(),
                    model_name="test-model",
                    macro_blocks=["Blocco."],
                    phase2_revised_dir=tmpdir,
                    session=session,
                    save_session=lambda: True,
                    runtime=_FakeRuntime(),
                    cancelled=lambda: False,
                    fallback_keys=[],
                    request_fallback_key=lambda: None,
                    prompt_revisione="Revisiona.",
                )

            self.assertTrue(
                os.path.exists(os.path.join(tmpdir, "rev_001.raw.md")),
                ".raw.md must remain when quota interrupts retry pass",
            )
            self.assertFalse(
                os.path.exists(os.path.join(tmpdir, "rev_001.md")),
                ".md must NOT be created if retry was interrupted",
            )
            self.assertEqual(session.get("last_error"), "quota_daily_limit_phase2")


class _ThrowingRuntime(_FakeRuntime):
    def update_work_done(self, *a, **kw):
        raise RuntimeError("UI gone")


class TestRevisionEdgeCases(unittest.TestCase):
    def _make_session(self):
        return {"phase2": {"revised_done": 0}, "stage": "phase2", "last_error": None}

    def _run_with_patches(
        self,
        macro_blocks,
        phase2_dir,
        session,
        rq_side_effect,
        *,
        cancelled=lambda: False,
        sleep_return=True,
        runtime=None,
    ):
        with (
            patch(
                "jot.services.revision_service.retry_with_quota",
                side_effect=rq_side_effect,
            ),
            patch(
                "jot.services.revision_service.sleep_with_cancel",
                return_value=sleep_return,
            ),
        ):
            _, revised_text = process_macro_revision_phase(
                client=object(),
                model_name="test-model",
                macro_blocks=macro_blocks,
                phase2_revised_dir=phase2_dir,
                session=session,
                save_session=lambda: True,
                runtime=runtime or _FakeRuntime(),
                cancelled=cancelled,
                fallback_keys=[],
                request_fallback_key=lambda: None,
                prompt_revisione="Revisiona.",
            )
        return revised_text

    def test_update_work_done_exception_swallowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def success(fn, *, client, **kw):
                return client, "Testo ok"

            result = self._run_with_patches(
                ["Blocco."],
                tmpdir,
                session,
                success,
                runtime=_ThrowingRuntime(),
            )
            self.assertIn("Testo ok", result)

    def test_cancelled_at_loop_start_returns_early(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()
            called = [0]

            def track(fn, *, client, **kw):
                called[0] += 1
                return client, "X"

            result = self._run_with_patches(
                ["Blocco A.", "Blocco B."],
                tmpdir,
                session,
                track,
                cancelled=lambda: True,
            )
            self.assertEqual(called[0], 0, "fn must not be called when cancelled")
            self.assertEqual(result, "")

    def test_resume_with_existing_md_skips_and_appends(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rev_path = os.path.join(tmpdir, "rev_001.md")
            with open(rev_path, "w", encoding="utf-8") as fh:
                fh.write("Testo già revisionato.\n")

            session = self._make_session()
            called = [0]

            def track(fn, *, client, **kw):
                called[0] += 1
                return client, "Blocco 2"

            result = self._run_with_patches(
                ["Blocco 1.", "Blocco 2."],
                tmpdir,
                session,
                track,
            )
            self.assertEqual(called[0], 1, "only the missing block should be processed")
            self.assertIn("Testo già revisionato.", result)
            self.assertIn("Blocco 2", result)
            self.assertEqual(session["phase2"]["revised_done"], 2)

    def test_call_body_executed_via_fn_calling_side_effect(self):
        """Verify the _call nested function body (lines 143-155) is exercised."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            class _FakeResp:
                text = "Testo generato dal modello"

            class _FakeModels:
                def generate_content(self, **_kw):
                    return _FakeResp()

            class _FakeClient:
                models = _FakeModels()

            def call_fn(fn, *, client, **kw):
                result = fn(_FakeClient())
                return _FakeClient(), result

            result = self._run_with_patches(["Blocco."], tmpdir, session, call_fn)
            self.assertIn("Testo generato dal modello", result)

    def test_current_text_none_in_main_pass_returns_early(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def returns_none(fn, *, client, **kw):
                return client, None

            result = self._run_with_patches(
                ["Blocco A.", "Blocco B."],
                tmpdir,
                session,
                returns_none,
            )
            self.assertEqual(result, "")

    def test_quota_in_main_pass_sets_last_error_and_returns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def raise_quota(fn, *, client, **kw):
                raise QuotaDailyLimitError("quota")

            result = self._run_with_patches(["Blocco."], tmpdir, session, raise_quota)
            self.assertEqual(session.get("last_error"), "quota_daily_limit_phase2")
            self.assertEqual(result, "")

    def test_sleep_cancel_after_main_pass_returns_early(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def success(fn, *, client, **kw):
                return client, "ok"

            self._run_with_patches(
                ["Blocco A.", "Blocco B."],
                tmpdir,
                session,
                success,
                sleep_return=False,
            )
            rev1 = os.path.join(tmpdir, "rev_001.md")
            self.assertTrue(os.path.exists(rev1))
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "rev_002.md")))

    def test_cancelled_in_retry_pass_returns_without_finalizing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "rev_001.raw.md")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("Contenuto raw.\n")

            session = self._make_session()

            # False on the first call (main-loop guard) so the pre-existing .raw.md
            # is found and added to pending_retry.  True from the second call onward
            # so the retry-pass guard fires immediately without finalizing the block.
            call_count = [0]

            def cancel_after_main_loop():
                call_count[0] += 1
                return call_count[0] > 1

            def never_called(fn, *, client, **kw):
                raise AssertionError("should not be called")

            with (
                patch(
                    "jot.services.revision_service.retry_with_quota",
                    side_effect=never_called,
                ),
                patch(
                    "jot.services.revision_service.sleep_with_cancel",
                    return_value=True,
                ),
            ):
                process_macro_revision_phase(
                    client=object(),
                    model_name="test-model",
                    macro_blocks=["Contenuto raw."],
                    phase2_revised_dir=tmpdir,
                    session=session,
                    save_session=lambda: True,
                    runtime=_FakeRuntime(),
                    cancelled=cancel_after_main_loop,
                    fallback_keys=[],
                    request_fallback_key=lambda: None,
                    prompt_revisione="Revisiona.",
                )

            self.assertTrue(
                os.path.exists(raw_path), ".raw.md must stay when cancelled"
            )
            self.assertFalse(
                os.path.exists(os.path.join(tmpdir, "rev_001.md")),
                ".md must NOT be created when retry pass is cancelled",
            )

    def test_exception_reading_raw_path_gives_empty_block_src(self):
        """If open(raw_path) raises, block_src becomes "" and block is finalized empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "rev_001.raw.md")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("Contenuto raw.\n")

            session = self._make_session()
            _real_open = open

            def selective_open_fail_raw(path, *args, **kwargs):
                basename = os.path.basename(str(path))
                mode = args[0] if args else kwargs.get("mode", "r")
                if basename.endswith(".raw.md") and "w" not in str(mode):
                    raise OSError("perm denied")
                return _real_open(path, *args, **kwargs)

            def never_called(fn, *, client, **kw):
                raise AssertionError(
                    "retry_with_quota should not be called for empty block"
                )

            with (
                patch(
                    "jot.services.revision_service.retry_with_quota",
                    side_effect=never_called,
                ),
                patch(
                    "jot.services.revision_service.sleep_with_cancel",
                    return_value=True,
                ),
                patch("builtins.open", side_effect=selective_open_fail_raw),
            ):
                process_macro_revision_phase(
                    client=object(),
                    model_name="test-model",
                    macro_blocks=["Contenuto raw."],
                    phase2_revised_dir=tmpdir,
                    session=session,
                    save_session=lambda: True,
                    runtime=_FakeRuntime(),
                    cancelled=lambda: False,
                    fallback_keys=[],
                    request_fallback_key=lambda: None,
                    prompt_revisione="Revisiona.",
                )

            self.assertIn(1, session.get("revision_failed_blocks", []))

    def test_call_retry_body_executed_via_fn_calling_side_effect(self):
        """Verify _call_retry (lines 288-300) is exercised."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "rev_001.raw.md")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("Contenuto raw da riprovare.\n")

            session = self._make_session()

            class _FakeResp:
                text = "Testo dal retry con _call_retry"

            class _FakeModels:
                def generate_content(self, **_kw):
                    return _FakeResp()

            class _FakeClient:
                models = _FakeModels()

            def call_fn(fn, *, client, **kw):
                result = fn(_FakeClient())
                return _FakeClient(), result

            result = self._run_with_patches(
                ["Contenuto raw da riprovare."],
                tmpdir,
                session,
                call_fn,
            )
            self.assertIn("Testo dal retry con _call_retry", result)
            self.assertFalse(os.path.exists(raw_path))

    def test_current_text_none_in_retry_pass_returns_early(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "rev_001.raw.md")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("Contenuto raw.\n")

            session = self._make_session()

            def returns_none(fn, *, client, **kw):
                return client, None

            result = self._run_with_patches(
                ["Contenuto raw."],
                tmpdir,
                session,
                returns_none,
            )
            self.assertEqual(result, "")

    def test_os_rename_failure_falls_back_to_atomic_write(self):
        """When os.rename raises in retry fail path, _atomic_write_text is used instead."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def always_fail(fn, *, client, **kw):
                raise RuntimeError("always fails")

            with (
                patch(
                    "jot.services.revision_service.retry_with_quota",
                    side_effect=always_fail,
                ),
                patch(
                    "jot.services.revision_service.sleep_with_cancel",
                    return_value=True,
                ),
                patch("os.rename", side_effect=OSError("cross-device")),
            ):
                process_macro_revision_phase(
                    client=object(),
                    model_name="test-model",
                    macro_blocks=["Blocco."],
                    phase2_revised_dir=tmpdir,
                    session=session,
                    save_session=lambda: True,
                    runtime=_FakeRuntime(),
                    cancelled=lambda: False,
                    fallback_keys=[],
                    request_fallback_key=lambda: None,
                    prompt_revisione="Revisiona.",
                )

            rev_path = os.path.join(tmpdir, "rev_001.md")
            self.assertTrue(os.path.exists(rev_path))
            self.assertIn(1, session.get("revision_failed_blocks", []))

    def test_exception_reading_final_md_skipped_gracefully(self):
        """If open raises during the final rebuild loop, the block is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session()

            def success(fn, *, client, **kw):
                return client, "Testo ok"

            original_open = open

            def selective_open(path, *args, **kwargs):
                fname = os.path.basename(str(path))
                mode = args[0] if args else kwargs.get("mode", "r")
                if fname == "rev_001.md" and "w" not in str(mode):
                    raise OSError("read error in rebuild")
                return original_open(path, *args, **kwargs)

            with (
                patch(
                    "jot.services.revision_service.retry_with_quota",
                    side_effect=success,
                ),
                patch(
                    "jot.services.revision_service.sleep_with_cancel",
                    return_value=True,
                ),
                patch("builtins.open", side_effect=selective_open),
            ):
                _, result = process_macro_revision_phase(
                    client=object(),
                    model_name="test-model",
                    macro_blocks=["Blocco."],
                    phase2_revised_dir=tmpdir,
                    session=session,
                    save_session=lambda: True,
                    runtime=_FakeRuntime(),
                    cancelled=lambda: False,
                    fallback_keys=[],
                    request_fallback_key=lambda: None,
                    prompt_revisione="Revisiona.",
                )

            self.assertEqual(result, "")


class TestRetryFailedRevisionBlocks(unittest.TestCase):
    def _make_session(self, failed_blocks, macro_total=3):
        return {
            "phase2": {"macro_total": macro_total, "revised_done": 2},
            "revision_failed_blocks": list(failed_blocks),
            "revision_pending_blocks": [],
            "last_error": None,
        }

    def _run(self, session, phase2_dir, rq_side_effect, cancelled=lambda: False):
        with patch(
            "jot.services.revision_service.retry_with_quota",
            side_effect=rq_side_effect,
        ):
            _, result = retry_failed_revision_blocks(
                client=object(),
                model_name="test-model",
                phase2_revised_dir=phase2_dir,
                session=session,
                save_session=lambda: True,
                runtime=_FakeRuntime(),
                cancelled=cancelled,
                fallback_keys=[],
                request_fallback_key=lambda: None,
                prompt_revisione="Revisiona.",
            )
        return result

    def test_empty_failed_blocks_returns_immediately(self):
        """No revision_failed_blocks → early return with empty result, AI never called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = self._make_session([])
            called = [0]

            def track(fn, *, client, **kw):
                called[0] += 1
                return client, "X"

            result = self._run(session, tmpdir, track)

            self.assertEqual(called[0], 0)
            self.assertEqual(result["retried_blocks"], [])
            self.assertEqual(result["failed_blocks"], [])
            self.assertFalse(result["cancelled"])
            self.assertFalse(result["quota_exhausted"])

    def test_happy_path_raw_md_source(self):
        """Block in revision_failed_blocks with .raw.md → AI succeeds →
        .md written, .raw.md deleted, retried_blocks=[idx], session cleared."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "rev_001.raw.md")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("Blocco da recuperare.\n")

            session = self._make_session([1])

            def success(fn, *, client, **kw):
                return client, "Testo recuperato"

            result = self._run(session, tmpdir, success)

            rev_path = os.path.join(tmpdir, "rev_001.md")
            self.assertTrue(os.path.exists(rev_path))
            with open(rev_path, encoding="utf-8") as fh:
                self.assertIn("Testo recuperato", fh.read())
            self.assertFalse(os.path.exists(raw_path))
            self.assertEqual(result["retried_blocks"], [1])
            self.assertEqual(result["failed_blocks"], [])
            self.assertEqual(session["revision_failed_blocks"], [])
            self.assertIsNone(session.get("last_error"))

    def test_legacy_rev_md_fallback_when_no_raw_md(self):
        """If .raw.md is absent, source falls back to existing .md (legacy sessions)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rev_path = os.path.join(tmpdir, "rev_002.md")
            with open(rev_path, "w", encoding="utf-8") as fh:
                fh.write("Contenuto grezzo salvato come md.\n")

            session = self._make_session([2])

            def success(fn, *, client, **kw):
                return client, "Testo riprocessato"

            result = self._run(session, tmpdir, success)

            with open(rev_path, encoding="utf-8") as fh:
                self.assertIn("Testo riprocessato", fh.read())
            self.assertEqual(result["retried_blocks"], [2])
            self.assertEqual(result["failed_blocks"], [])

    def test_partial_failure_remaining_blocks_preserved_in_session(self):
        """2 blocks: block 1 succeeds, block 2 raises RuntimeError →
        retried=[1], failed=[2], session revised_failed_blocks=[2]."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for idx in [1, 2]:
                with open(
                    os.path.join(tmpdir, f"rev_{idx:03}.raw.md"), "w", encoding="utf-8"
                ) as fh:
                    fh.write(f"Blocco {idx} grezzo.\n")

            session = self._make_session([1, 2])
            calls = [0]

            def first_ok_second_fail(fn, *, client, **kw):
                calls[0] += 1
                if calls[0] == 1:
                    return client, "Blocco 1 ok"
                raise RuntimeError("network error on block 2")

            result = self._run(session, tmpdir, first_ok_second_fail)

            self.assertEqual(result["retried_blocks"], [1])
            self.assertEqual(result["failed_blocks"], [2])
            self.assertFalse(result["cancelled"])
            self.assertFalse(result["quota_exhausted"])
            self.assertEqual(session["revision_failed_blocks"], [2])

    def test_quota_after_partial_sets_quota_exhausted_and_last_error(self):
        """Block 1 succeeds, block 2 raises QuotaDailyLimitError →
        quota_exhausted=True, last_error set, failed_blocks=[2]."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for idx in [1, 2]:
                with open(
                    os.path.join(tmpdir, f"rev_{idx:03}.raw.md"), "w", encoding="utf-8"
                ) as fh:
                    fh.write(f"Blocco {idx}.\n")

            session = self._make_session([1, 2])
            calls = [0]

            def first_ok_then_quota(fn, *, client, **kw):
                calls[0] += 1
                if calls[0] == 1:
                    return client, "Blocco 1 ok"
                raise QuotaDailyLimitError("quota giornaliera")

            result = self._run(session, tmpdir, first_ok_then_quota)

            self.assertTrue(result["quota_exhausted"])
            self.assertEqual(result["failed_blocks"], [2])
            self.assertEqual(result["retried_blocks"], [1])
            self.assertEqual(session.get("last_error"), "quota_daily_limit_phase2")

    def test_cancellation_before_first_block(self):
        """cancelled() returns True immediately → all blocks preserved, was_cancelled=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for idx in [1, 2]:
                with open(
                    os.path.join(tmpdir, f"rev_{idx:03}.raw.md"), "w", encoding="utf-8"
                ) as fh:
                    fh.write(f"Blocco {idx}.\n")

            session = self._make_session([1, 2])
            called = [0]

            def never_called(fn, *, client, **kw):
                raise AssertionError("should not be called when cancelled at start")

            result = self._run(session, tmpdir, never_called, cancelled=lambda: True)

            self.assertTrue(result["cancelled"])
            self.assertEqual(result["retried_blocks"], [])
            self.assertEqual(sorted(result["failed_blocks"]), [1, 2])
            self.assertEqual(called[0], 0)

    def test_cancellation_mid_pass_preserves_remaining_blocks(self):
        """Block 1 processed successfully, then cancelled →
        retried=[1], failed=[2], was_cancelled=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for idx in [1, 2]:
                with open(
                    os.path.join(tmpdir, f"rev_{idx:03}.raw.md"), "w", encoding="utf-8"
                ) as fh:
                    fh.write(f"Blocco {idx}.\n")

            session = self._make_session([1, 2])
            cancel_calls = [0]

            def cancel_after_first():
                cancel_calls[0] += 1
                return cancel_calls[0] > 1

            def success(fn, *, client, **kw):
                return client, "Blocco ok"

            result = self._run(session, tmpdir, success, cancelled=cancel_after_first)

            self.assertTrue(result["cancelled"])
            self.assertEqual(result["retried_blocks"], [1])
            self.assertEqual(result["failed_blocks"], [2])
            self.assertEqual(session["revision_failed_blocks"], [2])

    def test_current_text_none_breaks_and_preserves_remaining(self):
        """retry_with_quota returning (client, None) → remaining blocks kept,
        result includes all unprocessed indexes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for idx in [1, 2]:
                with open(
                    os.path.join(tmpdir, f"rev_{idx:03}.raw.md"), "w", encoding="utf-8"
                ) as fh:
                    fh.write(f"Blocco {idx}.\n")

            session = self._make_session([1, 2])

            def returns_none(fn, *, client, **kw):
                return client, None

            result = self._run(session, tmpdir, returns_none)

            self.assertEqual(result["retried_blocks"], [])
            self.assertEqual(sorted(result["failed_blocks"]), [1, 2])

    def test_empty_block_src_skipped_without_ai_call(self):
        """If source file contains only whitespace, block goes to remaining_blocks
        without calling retry_with_quota."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "rev_001.raw.md")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("   \n")

            session = self._make_session([1])
            called = [0]

            def track(fn, *, client, **kw):
                called[0] += 1
                return client, "X"

            result = self._run(session, tmpdir, track)

            self.assertEqual(called[0], 0, "AI must not be called for empty block")
            self.assertEqual(result["retried_blocks"], [])
            self.assertIn(1, result["failed_blocks"])

    def test_macro_total_inferred_from_max_failed_when_session_missing(self):
        """When session has no phase2.macro_total, macro_total is inferred as
        max(failed_blocks) — function must not crash and must process the block."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "rev_005.raw.md")
            with open(raw_path, "w", encoding="utf-8") as fh:
                fh.write("Blocco 5.\n")

            session = {"revision_failed_blocks": [5], "last_error": None}

            def success(fn, *, client, **kw):
                return client, "Blocco 5 ok"

            result = self._run(session, tmpdir, success)

            self.assertEqual(result["retried_blocks"], [5])
            self.assertEqual(result["failed_blocks"], [])


class Phase2ResumeProgressTests(unittest.TestCase):
    def test_resume_emits_initial_progress(self):
        progress_calls: list[float] = []

        class _ProgressRuntime(_FakeRuntime):
            def progress(self, v):
                progress_calls.append(v)

        session = {"stage": "phase2", "phase2": {"revised_done": 2}, "last_error": None}
        runtime = _ProgressRuntime()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create existing files for blocks 1 and 2
            with open(os.path.join(tmpdir, "rev_001.md"), "w", encoding="utf-8") as fh:
                fh.write("block 1")
            with open(os.path.join(tmpdir, "rev_002.md"), "w", encoding="utf-8") as fh:
                fh.write("block 2")

            with (
                patch(
                    "jot.services.revision_service.retry_with_quota",
                    return_value=(object(), "block rev"),
                ),
                patch(
                    "jot.services.revision_service.sleep_with_cancel",
                    return_value=True,
                ),
            ):
                process_macro_revision_phase(
                    client=object(),
                    model_name="test",
                    macro_blocks=["b1", "b2", "b3", "b4"],
                    phase2_revised_dir=tmpdir,
                    session=session,
                    save_session=lambda: True,
                    runtime=runtime,
                    cancelled=lambda: False,
                    fallback_keys=[],
                    request_fallback_key=lambda: None,
                    prompt_revisione="prompt",
                )

        self.assertTrue(len(progress_calls) >= 1)
        self.assertAlmostEqual(progress_calls[0], 0.8)


if __name__ == "__main__":
    unittest.main()
