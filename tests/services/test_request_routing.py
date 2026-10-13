"""Which model and which key: every key x model pair has its own daily quota."""

import unittest
from typing import Any
from unittest.mock import patch

from jot.core.model_registry import build_model_state
from jot.services import generation_service, usage_service
from jot.services.generation_service import (
    mark_model_overloaded,
    reset_global_governor,
    retry_with_quota,
    select_route,
)

KEY_A = "AIzaSyKEY_A_0000000000000000000000000"
KEY_B = "AIzaSyKEY_B_0000000000000000000000000"


class _Client:
    def __init__(self, key):
        self.api_key = key


class _Runtime:
    def __init__(self):
        self.keys = []

    def phase(self, _text):
        pass

    def set_effective_api_key(self, key):
        self.keys.append(key)


def _quota_error():
    err = RuntimeError(
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generate_content_free_tier_requests, limit: 20 per day"
    )
    err.code = 429  # type: ignore[attr-defined]
    return err


class RequestMatrixTests(unittest.TestCase):
    def setUp(self):
        usage_service.reset_daily_usage_for_tests()
        reset_global_governor()

    def test_every_request_sent_counts_also_the_failed_ones(self):
        for _ in range(3):
            usage_service.record_request_attempt(KEY_A, "gemini-3.8-flash")
        usage_service.record_request_success(KEY_A, "gemini-3.8-flash")
        m = usage_service.request_matrix(
            [KEY_A, KEY_B], ["gemini-3.8-flash", "gemini-3.7-flash"]
        )
        self.assertEqual(m["used"], 3)
        self.assertEqual(m["capacity"], 80)  # 2 keys x 2 models x 20
        self.assertEqual(m["remaining"], 77)

    def test_a_pair_refused_by_google_counts_as_empty(self):
        usage_service.record_request_attempt(KEY_A, "gemini-3.8-flash")
        usage_service.mark_quota_exhausted("gemini-3.8-flash", api_key=KEY_A)
        m = usage_service.request_matrix(
            [KEY_A], ["gemini-3.8-flash", "gemini-3.7-flash"]
        )
        self.assertEqual(m["remaining"], 20)  # only 3.7 is left on that key
        cell = next(c for c in m["cells"] if c["model"] == "gemini-3.8-flash")
        self.assertTrue(cell["exhausted"])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        usage_service.reset_daily_usage_for_tests()
        reset_global_governor()
        self.keys = patch.object(
            generation_service, "configured_keys", return_value=[KEY_A, KEY_B]
        )
        self.keys.start()
        self.addCleanup(self.keys.stop)
        self.factory = patch.object(
            generation_service, "create_gemini_client", side_effect=_Client
        )
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def _state(self):
        return build_model_state(
            "gemini-3.8-flash",
            ["gemini-3.7-flash", "gemini-3.6-flash"],
            "gemini-3.8-flash",
        )

    def test_a_key_out_of_quota_for_a_model_hands_over_to_the_next_key(self):
        state = self._state()
        usage_service.mark_quota_exhausted("gemini-3.8-flash", api_key=KEY_A)
        runtime = _Runtime()
        client: Any = select_route(_Client(KEY_A), state, runtime=runtime)
        self.assertEqual(client.api_key, KEY_B)
        self.assertEqual(state.current, "gemini-3.8-flash")
        self.assertEqual(runtime.keys, [KEY_B])

    def test_every_key_out_of_quota_for_a_model_moves_to_the_next_model(self):
        state = self._state()
        for key in (KEY_A, KEY_B):
            usage_service.mark_quota_exhausted("gemini-3.8-flash", api_key=key)
        client: Any = select_route(_Client(KEY_B), state)
        self.assertEqual(state.current, "gemini-3.7-flash")
        self.assertEqual(client.api_key, KEY_B)

    def test_a_model_on_hold_is_skipped_and_tried_again_after_the_pause(self):
        state = self._state()
        mark_model_overloaded("gemini-3.8-flash")
        select_route(_Client(KEY_A), state)
        self.assertEqual(state.current, "gemini-3.7-flash")
        # still on hold: stays on 3.7
        select_route(_Client(KEY_A), state)
        self.assertEqual(state.current, "gemini-3.7-flash")
        # the pause is over: one new try on the better model
        mark_model_overloaded("gemini-3.8-flash", seconds=-1)
        select_route(_Client(KEY_A), state)
        self.assertEqual(state.current, "gemini-3.8-flash")

    def test_daily_quota_on_one_key_continues_on_the_other_without_stopping(self):
        state = self._state()
        calls = []

        def fn(client):
            calls.append((client.api_key, state.current))
            if client.api_key == KEY_A:
                raise _quota_error()
            return "ok"

        client: Any
        client, result = retry_with_quota(
            fn,
            client=_Client(KEY_A),
            fallback_keys=[KEY_B],
            model_name="gemini-3.8-flash",
            model_state=state,
            cancelled=lambda: False,
            runtime=_Runtime(),
            request_fallback_key=lambda: None,
            max_attempts=3,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0,),
            rate_limit_sleep_seconds=0.0,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(client.api_key, KEY_B)
        self.assertEqual(
            calls, [(KEY_A, "gemini-3.8-flash"), (KEY_B, "gemini-3.8-flash")]
        )

    def test_first_503_goes_to_the_next_model_and_the_next_blocks_skip_it(self):
        state = self._state()
        seen = []

        def fn(client):
            seen.append(state.current)
            if state.current == "gemini-3.8-flash":
                err = RuntimeError("503 UNAVAILABLE. high demand")
                err.code = 503  # type: ignore[attr-defined]
                raise err
            return "ok"

        for _ in range(3):  # three blocks of a lesson
            retry_with_quota(
                fn,
                client=_Client(KEY_A),
                fallback_keys=[],
                model_name="gemini-3.8-flash",
                model_state=state,
                cancelled=lambda: False,
                runtime=_Runtime(),
                request_fallback_key=lambda: None,
                max_attempts=3,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0,),
                rate_limit_sleep_seconds=0.0,
            )
        # one single request lost on the overloaded model, in the whole lesson
        self.assertEqual(
            seen,
            [
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.7-flash",
                "gemini-3.7-flash",
            ],
        )


if __name__ == "__main__":
    unittest.main()
