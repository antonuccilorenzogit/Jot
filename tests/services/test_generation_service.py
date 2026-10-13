import threading
import unittest
from typing import Any, ClassVar, cast
from unittest.mock import MagicMock, patch

from jot.core.model_registry import build_model_state
from jot.services.gemini_errors import CircuitBreakerExhaustedError
from jot.services.generation_service import (
    AdaptiveGovernor,
    AllModelsUnavailableError,
    DegenerateOutputError,
    QuotaDailyLimitError,
    _is_model_unavailable,
    create_gemini_client,
    detect_degenerate_output,
    get_governor,
    reset_global_governor,
    retry_with_quota,
    try_rotate_key,
)


class _FakeRuntime:
    def __init__(self):
        self.rotated_keys = []
        self.phase_calls: list[str] = []
        self.retry_states: list[dict[str, Any]] = []

    def phase(self, text):
        self.phase_calls.append(text)

    def set_effective_api_key(self, key):
        self.rotated_keys.append(key)

    def retry_state(self, payload):
        self.retry_states.append(dict(payload))


class _Structured503QuotaError(RuntimeError):
    def __init__(self):
        super().__init__("503 Service Unavailable")
        self.code = 503
        self.status = "RESOURCE_EXHAUSTED"
        self.message = "Token balance exhausted for this API key"
        self.details = {
            "error": {
                "code": 503,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Token balance exhausted for this API key",
            }
        }


class GeminiClientFactoryTests(unittest.TestCase):
    def test_factory_disables_sdk_retries_without_fallback_constructor(self):
        sentinel = object()
        with patch(
            "jot.services.generation_service.genai.Client",
            return_value=sentinel,
        ) as constructor:
            client = create_gemini_client(" test-key ")

        self.assertIs(client, sentinel)
        constructor.assert_called_once()
        kwargs = constructor.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "test-key")
        self.assertEqual(kwargs["http_options"].retry_options.attempts, 1)
        # a stalled connection must not block a lesson forever
        self.assertEqual(kwargs["http_options"].timeout, 480_000)

    def test_request_timeout_can_be_changed_and_is_bounded(self):
        from jot.services.generation_service import request_timeout_ms

        with patch.dict("os.environ", {"JOT_REQUEST_TIMEOUT_S": "120"}):
            self.assertEqual(request_timeout_ms(), 120_000)
        with patch.dict("os.environ", {"JOT_REQUEST_TIMEOUT_S": "5"}):
            self.assertEqual(request_timeout_ms(), 30_000)
        with patch.dict("os.environ", {"JOT_REQUEST_TIMEOUT_S": "abc"}):
            self.assertEqual(request_timeout_ms(), 480_000)

    def test_factory_propagates_configuration_errors(self):
        with (
            patch(
                "jot.services.generation_service.genai.Client",
                side_effect=TypeError("unsupported retry options"),
            ) as constructor,
            self.assertRaisesRegex(TypeError, "unsupported retry options"),
        ):
            create_gemini_client("test-key")

        constructor.assert_called_once()


class TryRotateKeyTests(unittest.TestCase):
    def test_invalid_key_is_discarded(self):
        class _InvalidModels:
            def get(self, model=None, **kwargs):
                err = RuntimeError("API key not valid")
                err.code = 401  # type: ignore[attr-defined]
                raise err

        class _InvalidClient:
            def __init__(self, api_key=None, **kwargs):
                self.api_key = api_key
                self.models = _InvalidModels()

        keys = ["bad-key"]
        with patch("jot.services.generation_service.genai.Client", _InvalidClient):
            client, rotated, key = try_rotate_key(object(), keys, "test-model")

        self.assertFalse(rotated)
        self.assertIsNone(key)
        self.assertEqual(keys, [])
        self.assertIsNotNone(client)

    def test_transient_key_moves_to_back_and_valid_second_key_succeeds(self):
        class _Models:
            def __init__(self, api_key):
                self.api_key = api_key

            def get(self, model=None, **kwargs):
                if self.api_key == "transient-key":
                    err = RuntimeError("503 Service Unavailable")
                    err.code = 503  # type: ignore[attr-defined]
                    raise err
                return {"model": model}

        class _Client:
            def __init__(self, api_key=None, **kwargs):
                self.api_key = api_key
                self.models = _Models(api_key)

        keys = ["transient-key", "valid-key"]
        with patch("jot.services.generation_service.genai.Client", _Client):
            client, rotated, key = try_rotate_key(object(), keys, "test-model")

        self.assertTrue(rotated)
        self.assertEqual(key, "valid-key")
        self.assertEqual(keys, ["transient-key"])
        self.assertEqual(cast(Any, client).api_key, "valid-key")

    def test_all_transient_keys_stop_after_one_pass_without_consuming(self):
        calls = []

        class _TransientModels:
            def __init__(self, api_key):
                self.api_key = api_key

            def get(self, model=None, **kwargs):
                calls.append(self.api_key)
                raise TimeoutError("timed out")

        class _TransientClient:
            def __init__(self, api_key=None, **kwargs):
                self.api_key = api_key
                self.models = _TransientModels(api_key)

        original = object()
        keys = ["k1", "k2"]
        with patch("jot.services.generation_service.genai.Client", _TransientClient):
            client, rotated, key = try_rotate_key(original, keys, "test-model")

        self.assertIs(client, original)
        self.assertFalse(rotated)
        self.assertIsNone(key)
        self.assertEqual(calls, ["k1", "k2"])
        self.assertEqual(keys, ["k1", "k2"])

    def test_transient_validation_print_redacts_key(self):
        secret = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        printed = []

        class _TransientModels:
            def get(self, model=None, **kwargs):
                err = RuntimeError(f"503 temporary key={secret}")
                err.code = 503  # type: ignore[attr-defined]
                raise err

        class _TransientClient:
            def __init__(self, api_key=None, **kwargs):
                self.models = _TransientModels()

        with (
            patch(
                "jot.services.generation_service.genai.Client",
                _TransientClient,
            ),
            patch("builtins.print", side_effect=printed.append),
        ):
            try_rotate_key(object(), ["transient-key"], "test-model")

        joined = "\n".join(printed)
        self.assertNotIn(secret, joined)
        self.assertIn("[API_KEY_REDACTED]", joined)


class RetryWithQuotaTests(unittest.TestCase):
    def setUp(self):
        reset_global_governor()

    def tearDown(self):
        reset_global_governor()

    def _run(self, fn, *, max_attempts=2):
        return retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="test-model",
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=max_attempts,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0, 0.0, 0.0),
            rate_limit_sleep_seconds=0.0,
        )

    def test_a_request_that_times_out_is_retried(self):
        import httpx

        calls = []

        def fn(_client):
            calls.append(1)
            if len(calls) == 1:
                raise httpx.ReadTimeout("The read operation timed out")
            return "ok"

        with patch(
            "jot.services.network_service.is_network_offline_error", return_value=False
        ):
            _client, result = self._run(fn, max_attempts=3)
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 2)

    def test_an_overloaded_model_hands_over_to_the_fallback(self):
        # the log of 13 October: gemini-3.8-flash answered 503 "high demand" four times
        # and the lesson failed although 3.7 and 3.6 were configured as fallbacks
        model_state = build_model_state(
            "gemini-3.8-flash",
            ["gemini-3.7-flash", "gemini-3.6-flash"],
            "gemini-3.8-flash",
        )
        seen, switched = [], []

        def fn(_client):
            seen.append(model_state.current)
            if model_state.current == "gemini-3.8-flash":
                err = RuntimeError(
                    "503 UNAVAILABLE. This model is currently experiencing high demand."
                )
                err.code = 503  # type: ignore[attr-defined]
                raise err
            return "ok"

        _client, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="gemini-3.8-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=3,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0, 0.0, 0.0),
            rate_limit_sleep_seconds=0.0,
            on_model_switched=lambda old, new: switched.append((old, new)),
        )
        self.assertEqual(result, "ok")
        self.assertEqual(model_state.current, "gemini-3.7-flash")
        self.assertEqual(switched, [("gemini-3.8-flash", "gemini-3.7-flash")])
        self.assertEqual(seen.count("gemini-3.8-flash"), 1)

    def test_every_model_overloaded_still_stops(self):
        model_state = build_model_state(
            "gemini-3.8-flash", ["gemini-3.7-flash"], "gemini-3.8-flash"
        )

        def fn(_client):
            err = RuntimeError("503 UNAVAILABLE. high demand")
            err.code = 503  # type: ignore[attr-defined]
            raise err

        with self.assertRaises(CircuitBreakerExhaustedError):
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-3.8-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=3,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                rate_limit_sleep_seconds=0.0,
            )
        self.assertEqual(model_state.current, "gemini-3.7-flash")

    def test_plain_503_retries_without_model_switch(self):
        primary_client = object()
        model_state = build_model_state(
            "gemini-2.5-flash",
            [],  # one model only: the backoff on the same model
            "gemini-2.5-flash",
        )
        switched = []
        call_count = 0

        def fn(current_client):
            nonlocal call_count
            call_count += 1
            if current_client is primary_client and call_count >= 2:
                return "ok"
            err = RuntimeError("503 Service Unavailable")
            err.code = 503  # type: ignore[attr-defined]
            raise err

        client, result = retry_with_quota(
            fn,
            client=primary_client,
            fallback_keys=[],
            model_name="gemini-2.5-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=2,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0, 0.0),
            rate_limit_sleep_seconds=0.0,
            on_model_switched=lambda old, new: switched.append((old, new)),
        )

        self.assertIs(client, primary_client)
        self.assertEqual(result, "ok")
        self.assertEqual(model_state.current, "gemini-2.5-flash")
        self.assertEqual(switched, [])

    def test_model_404_switches_immediately_without_sleep(self):
        model_state = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash"],
            "gemini-2.5-flash",
        )
        switched = []
        call_models = []

        def fn(_client):
            call_models.append(model_state.current)
            if model_state.current == "gemini-3.6-flash":
                return "ok"
            err = RuntimeError("404 NOT_FOUND model unsupported for generateContent")
            err.code = 404  # type: ignore[attr-defined]
            raise err

        with patch(
            "jot.services.generation_service.sleep_with_cancel",
            side_effect=AssertionError("404 must not sleep before switching model"),
        ):
            _client, result = retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=1,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                rate_limit_sleep_seconds=0.0,
                on_model_switched=lambda old, new: switched.append((old, new)),
            )

        self.assertEqual(result, "ok")
        self.assertEqual(call_models, ["gemini-2.5-flash", "gemini-3.6-flash"])
        self.assertEqual(switched, [("gemini-2.5-flash", "gemini-3.6-flash")])

    def test_degenerate_output_switches_model_without_consuming_attempts(self):
        model_state = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash"],
            "gemini-2.5-flash",
        )
        switched = []
        call_models = []

        def fn(_client):
            call_models.append(model_state.current)
            if model_state.current == "gemini-3.6-flash":
                return "ok"
            raise DegenerateOutputError("frase ripetuta 8 volte")

        _client, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="gemini-2.5-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=1,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0, 0.0),
            rate_limit_sleep_seconds=0.0,
            on_model_switched=lambda old, new: switched.append((old, new)),
        )

        self.assertEqual(result, "ok")
        self.assertEqual(call_models, ["gemini-2.5-flash", "gemini-3.6-flash"])
        self.assertEqual(switched, [("gemini-2.5-flash", "gemini-3.6-flash")])

    def test_degenerate_output_exhausted_chain_re_raises_degenerate_error(self):
        model_state = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash"],
            "gemini-2.5-flash",
        )

        def fn(_client):
            raise DegenerateOutputError("frase ripetuta 8 volte")

        with self.assertRaises(DegenerateOutputError) as ctx:
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=1,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                rate_limit_sleep_seconds=0.0,
            )

        self.assertIn("output degenerato", str(ctx.exception).lower())

    def test_plain_503_exhausted_chain_raises_clear_error(self):
        model_state = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash"],
            "gemini-2.5-flash",
        )

        def fn(_client):
            err = RuntimeError("503 Service Unavailable")
            err.code = 503  # type: ignore[attr-defined]
            raise err

        with self.assertRaises(CircuitBreakerExhaustedError):
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                rate_limit_sleep_seconds=0.0,
            )

    def test_plain_503_retry_that_becomes_429_does_not_switch_model(self):
        model_state = build_model_state(
            "gemini-2.5-flash",
            [],  # one model only: the backoff on the same model
            "gemini-2.5-flash",
        )
        call_count = 0

        def fn(_client):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                err = RuntimeError("503 Service Unavailable")
                err.code = 503  # type: ignore[attr-defined]
                raise err
            raise RuntimeError("429 resource_exhausted per minute")

        with self.assertRaises(CircuitBreakerExhaustedError):
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                rate_limit_sleep_seconds=0.0,
            )

        self.assertEqual(model_state.current, "gemini-2.5-flash")

    def test_rate_limit_exhausted_raises_original_not_quota_daily(self):
        """Persistent per-minute 429s must NOT raise QuotaDailyLimitError
        and must not trigger fallback-key acquisition."""
        fallback_key_calls = []

        def fn(_client):
            raise RuntimeError("429 resource_exhausted per minute threshold")

        with self.assertRaises(CircuitBreakerExhaustedError) as ctx:
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="test-model",
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: fallback_key_calls.append(1) or None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                rate_limit_sleep_seconds=0.0,
            )
        self.assertNotIsInstance(ctx.exception, QuotaDailyLimitError)
        self.assertEqual(
            fallback_key_calls,
            [],
            "request_fallback_key must not be called for minute-scoped rate limits",
        )

    def test_daily_quota_still_raises_quota_daily_limit_error(self):
        """True daily-quota errors must still raise QuotaDailyLimitError."""

        def fn(_client):
            raise RuntimeError("429 quota exceeded daily limit per day")

        with self.assertRaises(QuotaDailyLimitError):
            self._run(fn)

    def test_rate_limit_retries_before_giving_up(self):
        """Rate-limit path must probe once then raise CircuitBreakerExhaustedError."""
        call_count = 0

        def fn(_client):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("429 resource_exhausted per minute")

        with self.assertRaises(CircuitBreakerExhaustedError):
            self._run(fn, max_attempts=3)
        self.assertEqual(call_count, 2)

    def test_structured_503_exhausted_key_rotates_to_fallback_without_sleep_retry(self):
        runtime = _FakeRuntime()
        call_clients = []

        class _FakeModels:
            def get(self, model=None, **_):
                return True

        class _FakeClient:
            def __init__(self, api_key=None, **_):
                self.api_key = api_key
                self.models = _FakeModels()

        rotated_client = _FakeClient(api_key="fallback-key")

        def fn(current_client):
            call_clients.append(current_client)
            if current_client is rotated_client:
                return "ok"
            raise _Structured503QuotaError()

        request_mock = MagicMock(
            side_effect=AssertionError(
                "request_fallback_key must not be called when fallback key is available"
            )
        )

        with (
            patch(
                "jot.services.generation_service.genai.Client",
                return_value=rotated_client,
            ),
            patch(
                "jot.services.generation_service.sleep_with_cancel",
                side_effect=AssertionError(
                    "503 exhausted-key path must rotate immediately, not sleep-retry"
                ),
            ),
        ):
            client, result = retry_with_quota(
                fn,
                client=object(),
                fallback_keys=["fallback-key"],
                model_name="test-model",
                cancelled=lambda: False,
                runtime=runtime,
                request_fallback_key=request_mock,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                rate_limit_sleep_seconds=0.0,
            )

        self.assertIs(client, rotated_client)
        self.assertEqual(result, "ok")
        self.assertEqual(runtime.rotated_keys, ["fallback-key"])
        self.assertEqual(len(call_clients), 2)
        request_mock.assert_not_called()

    def test_structured_503_exhausted_key_without_fallback_raises_quota_error(self):
        with self.assertRaises(QuotaDailyLimitError):
            retry_with_quota(
                lambda _client: (_ for _ in ()).throw(_Structured503QuotaError()),
                client=object(),
                fallback_keys=[],
                model_name="test-model",
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                rate_limit_sleep_seconds=0.0,
            )

    def test_plain_503_without_quota_signal_uses_generic_retry(self):
        call_count = 0

        def fn(_client):
            nonlocal call_count
            call_count += 1
            err = RuntimeError("503 Service Unavailable")
            err.code = 503  # type: ignore[attr-defined]
            raise err

        with patch("jot.services.generation_service.try_rotate_key") as mock_rotate:
            with self.assertRaises(CircuitBreakerExhaustedError):
                self._run(fn, max_attempts=2)

        self.assertEqual(call_count, 4)
        mock_rotate.assert_not_called()

    def test_cancelled_quota_error_does_not_rotate_or_request_new_key(self):
        runtime = _FakeRuntime()
        client = object()
        cancel_event = __import__("threading").Event()
        fallback_keys = ["fallback-key-1", "fallback-key-2"]
        fallback_key_calls = []

        def fn(_client):
            cancel_event.set()
            raise RuntimeError("429 quota exceeded daily limit per day")

        with patch(
            "jot.services.generation_service.try_rotate_key",
            side_effect=AssertionError(
                "La rotazione non deve partire dopo l'annullamento"
            ),
        ):
            returned_client, result = retry_with_quota(
                fn,
                client=client,
                fallback_keys=fallback_keys,
                model_name="test-model",
                cancelled=cancel_event.is_set,
                runtime=runtime,
                request_fallback_key=lambda: fallback_key_calls.append(1) or None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                rate_limit_sleep_seconds=0.0,
            )

        self.assertIs(returned_client, client)
        self.assertIsNone(result)
        self.assertEqual(runtime.rotated_keys, [])
        self.assertEqual(fallback_key_calls, [])
        self.assertEqual(fallback_keys, ["fallback-key-1", "fallback-key-2"])

    def test_cancel_during_fallback_validation_keeps_key_available(self):
        runtime = _FakeRuntime()
        client = object()
        cancel_event = threading.Event()
        fallback_keys = ["fallback-key-1"]

        class _ValidModels:
            def get(self, model=None, **kwargs):
                cancel_event.set()
                return {"model": model}

        class _ValidClient:
            def __init__(self, api_key=None, **kwargs):
                self.api_key = api_key
                self.models = _ValidModels()

        def fn(_client):
            raise RuntimeError("429 quota exceeded daily limit per day")

        with patch("jot.services.generation_service.genai.Client", _ValidClient):
            returned_client, result = retry_with_quota(
                fn,
                client=client,
                fallback_keys=fallback_keys,
                model_name="test-model",
                cancelled=cancel_event.is_set,
                runtime=runtime,
                request_fallback_key=lambda: "fallback-key-1",
                max_attempts=2,
                retry_sleep_seconds=0.0,
                rate_limit_sleep_seconds=0.0,
            )

        self.assertIs(returned_client, client)
        self.assertIsNone(result)
        self.assertEqual(runtime.rotated_keys, [])
        self.assertEqual(fallback_keys, ["fallback-key-1"])

    def test_detect_degenerate_output_flags_repeated_paragraphs(self):
        paragraph = "La ventilazione alveolare regola gli scambi gassosi in modo continuo durante tutta la respirazione."
        text = "\n\n".join([paragraph] * 4)
        self.assertIn("paragrafo ripetuto", detect_degenerate_output(text) or "")

    def test_detect_degenerate_output_flags_repeated_sentences(self):
        sentence = "E allora l'emoglobina cede piu facilmente l'ossigeno."
        text = " ".join([sentence] * 8)
        self.assertIn("frase ripetuta", detect_degenerate_output(text) or "")

    def test_503_phase_restored_after_switch_to_fallback(self):
        """503 retry 1/2 then retry 2/2: each wait is followed by phase restore."""
        model_state = build_model_state(
            "gemini-2.5-flash", ["gemini-3.6-flash"], "gemini-2.5-flash"
        )
        rt = _FakeRuntime()

        def fn(current_client):
            err = RuntimeError("503 Service Unavailable")
            err.code = 503  # type: ignore[attr-defined]
            raise err

        with self.assertRaises(CircuitBreakerExhaustedError):
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=rt,
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                resume_phase_text="Fase 1/3: trascrizione (chunk 1/5)",
            )

        resume_text = "Fase 1/3: trascrizione (chunk 1/5)"
        wait_msg = "Server Gemini occupato — riprovo tra 0s"
        self.assertTrue(any(wait_msg in c for c in rt.phase_calls))
        self.assertIn(resume_text, rt.phase_calls)
        first_wait = next(i for i, c in enumerate(rt.phase_calls) if wait_msg in c)
        first_resume = rt.phase_calls.index(resume_text)
        self.assertGreater(
            first_resume,
            first_wait,
            "resume phase must appear after first wait message",
        )

    def test_rate_limit_phase_restored_after_wait(self):
        """After rate-limit sleep, runtime.phase() receives the resume text
        before the next callable_fn() attempt."""
        rt = _FakeRuntime()
        call_count = [0]

        def fn(current_client):
            call_count[0] += 1
            if call_count[0] == 1:
                err = RuntimeError("429 Too Many Requests per minute")
                err.code = 429  # type: ignore[attr-defined]
                raise err
            return "ok"

        _, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="test-model",
            cancelled=lambda: False,
            runtime=rt,
            request_fallback_key=lambda: None,
            max_attempts=3,
            retry_sleep_seconds=0.0,
            rate_limit_sleep_seconds=0.0,
            resume_phase_text="Fase 2/3: revisione (1/4)",
        )

        self.assertEqual(result, "ok")
        self.assertTrue(any("Rate limit: attesa" in c for c in rt.phase_calls))
        self.assertIn("Fase 2/3: revisione (1/4)", rt.phase_calls)
        wait_idx = next(
            i for i, c in enumerate(rt.phase_calls) if "Rate limit: attesa" in c
        )
        resume_idx = rt.phase_calls.index("Fase 2/3: revisione (1/4)")
        self.assertGreater(resume_idx, wait_idx)

    def test_503_third_attempt_succeeds_without_model_switch(self):
        """503x2 (original + retry 1) -> success on retry 2: no model switch, 3 total calls."""
        model_state = build_model_state(
            "gemini-2.5-flash",
            [],  # one model only: the backoff on the same model
            "gemini-2.5-flash",
        )
        switched = []
        call_count = [0]

        def fn(_client):
            call_count[0] += 1
            if call_count[0] <= 2:
                err = RuntimeError("503 Service Unavailable")
                err.code = 503  # type: ignore
                raise err
            return "ok"

        _client, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="gemini-2.5-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=2,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0, 0.0),
            rate_limit_sleep_seconds=0.0,
            on_model_switched=lambda old, new: switched.append((old, new)),
        )

        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 3)
        self.assertEqual(model_state.current, "gemini-2.5-flash")
        self.assertEqual(
            switched,
            [],
            "no model switch must occur when success before retry budget exhausted",
        )

    def test_503_all_retries_exhausted_raises_circuit_breaker_exhausted(self):
        """Every model overloaded: the first 503 moves to the fallback at once, the last
        model is retried with the backoff, then the circuit breaker stops."""
        model_state = build_model_state(
            "gemini-2.5-flash", ["gemini-3.6-flash"], "gemini-2.5-flash"
        )
        switched = []
        call_count = [0]

        def fn(_client):
            call_count[0] += 1
            err = RuntimeError("503 Service Unavailable")
            err.code = 503  # type: ignore[attr-defined]
            raise err

        with self.assertRaises(CircuitBreakerExhaustedError):
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                rate_limit_sleep_seconds=0.0,
                on_model_switched=lambda old, new: switched.append((old, new)),
            )

        self.assertEqual(
            call_count[0], 4, "1 on the first model, 1 + 2 retries on the last"
        )
        self.assertEqual(model_state.current, "gemini-3.6-flash")
        self.assertEqual(switched, [("gemini-2.5-flash", "gemini-3.6-flash")])

    def test_503_two_waits_phase_restore_interleaved(self):
        """With two retry delays the phase sequence must be:
        wait1 → restore → wait2 → restore → success."""
        model_state = build_model_state(
            "gemini-2.5-flash",
            [],  # one model only: the backoff on the same model
            "gemini-2.5-flash",
        )
        rt = _FakeRuntime()
        call_count = [0]

        def fn(_client):
            call_count[0] += 1
            if call_count[0] <= 2:
                err = RuntimeError("503 Service Unavailable")
                err.code = 503  # type: ignore[attr-defined]
                raise err
            return "ok"

        retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="gemini-2.5-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=rt,
            request_fallback_key=lambda: None,
            max_attempts=2,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0, 0.0),
            rate_limit_sleep_seconds=0.0,
            resume_phase_text="Fase 1/3: trascrizione (chunk 3/10)",
        )

        wait_indices = [
            i
            for i, c in enumerate(rt.phase_calls)
            if "Server Gemini occupato — riprovo tra" in c
        ]
        restore_indices = [
            i
            for i, c in enumerate(rt.phase_calls)
            if c == "Fase 1/3: trascrizione (chunk 3/10)"
        ]
        self.assertEqual(len(wait_indices), 2)
        self.assertEqual(len(restore_indices), 2)
        self.assertLess(wait_indices[0], restore_indices[0])
        self.assertLess(restore_indices[0], wait_indices[1])
        self.assertLess(wait_indices[1], restore_indices[1])

    def test_503_cancel_during_second_retry_sleep_returns_none_no_switch(self):
        """If cancel fires during the second 503 sleep, returns (client, None) without switching model."""
        model_state = build_model_state(
            "gemini-2.5-flash",
            [],  # one model only: the backoff on the same model
            "gemini-2.5-flash",
        )
        switched = []
        sleep_call = [0]
        original_client = object()

        def fn(_client):
            err = RuntimeError("503 Service Unavailable")
            err.code = 503  # type: ignore[attr-defined]
            raise err

        def mock_sleep(cancelled_fn, seconds):
            sleep_call[0] += 1
            if sleep_call[0] >= 2:
                return False
            return True

        with patch(
            "jot.services.generation_service.sleep_with_cancel",
            side_effect=mock_sleep,
        ):
            returned_client, result = retry_with_quota(
                fn,
                client=original_client,
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                rate_limit_sleep_seconds=0.0,
                on_model_switched=lambda old, new: switched.append((old, new)),
            )

        self.assertIsNone(result)
        self.assertIs(returned_client, original_client)
        self.assertEqual(
            switched, [], "model must not switch when cancel fires during sleep"
        )
        self.assertEqual(model_state.current, "gemini-2.5-flash")

    def test_503_inner_retry_raises_429_reraises_429_not_503(self):
        """Regression: when the inner 503-model-unavailable retry loop encounters a
        minute-scoped 429 and breaks, the terminal exception must surface the 429,
        not the original outer 503."""
        model_state = build_model_state(
            "gemini-2.5-flash",
            [],  # one model only: the backoff on the same model
            "gemini-2.5-flash",
        )
        call_count = [0]

        def fn(_client):
            call_count[0] += 1
            if call_count[0] == 1:
                err = RuntimeError("503 Service Unavailable")
                err.code = 503  # type: ignore[attr-defined]
                raise err
            err = RuntimeError("429 Too Many Requests per minute")
            err.code = 429  # type: ignore[attr-defined]
            raise err

        with self.assertRaises(CircuitBreakerExhaustedError) as ctx:
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0,),
                rate_limit_sleep_seconds=0.0,
            )

        self.assertNotIsInstance(ctx.exception, QuotaDailyLimitError)
        self.assertIn(
            "429", str(ctx.exception) + " " + getattr(ctx.exception, "cause_error", "")
        )
        self.assertNotIn("503", str(ctx.exception))
        self.assertEqual(model_state.current, "gemini-2.5-flash")

    def test_degenerate_output_switch_resets_attempts_for_fallback(self):
        """Bug B1: attempts not reset after DegenerateOutputError model-switch.
        Primary drains one attempt via a generic error, then raises DegenerateOutputError
        → model switch.  Without the fix, fallback only gets one try (attempts=1 < 2);
        with the fix, fallback gets a fresh budget and can retry once before succeeding."""
        model_state = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash"],
            "gemini-2.5-flash",
        )
        primary_calls = [0]
        fallback_calls = [0]

        def fn(_client):
            if model_state.current == "gemini-2.5-flash":
                primary_calls[0] += 1
                if primary_calls[0] == 1:
                    raise RuntimeError("generic transient error")
                raise DegenerateOutputError("frase ripetuta")
            fallback_calls[0] += 1
            if fallback_calls[0] == 1:
                raise RuntimeError("transient error on fallback")
            return "ok"

        _, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="gemini-2.5-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=2,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0,),
            rate_limit_sleep_seconds=0.0,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(
            fallback_calls[0],
            2,
            "fallback must get full retry budget after degenerate-output switch",
        )

    def test_model_not_found_switch_resets_attempts_for_fallback(self):
        """Bug B2: attempts not reset after model-not-found (404) switch.
        Primary drains one attempt via a generic error, then raises 404 → model switch.
        Fallback must get a fresh budget and be able to retry before succeeding."""
        model_state = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash"],
            "gemini-2.5-flash",
        )
        primary_calls = [0]
        fallback_calls = [0]

        def fn(_client):
            if model_state.current == "gemini-2.5-flash":
                primary_calls[0] += 1
                if primary_calls[0] == 1:
                    raise RuntimeError("generic transient error")
                err = RuntimeError(
                    "404 NOT_FOUND model unsupported for generateContent"
                )
                err.code = 404  # type: ignore[attr-defined]
                raise err
            fallback_calls[0] += 1
            if fallback_calls[0] == 1:
                raise RuntimeError("transient error on fallback")
            return "ok"

        _, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="gemini-2.5-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=2,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0,),
            rate_limit_sleep_seconds=0.0,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(
            fallback_calls[0], 2, "fallback must get full retry budget after 404 switch"
        )

    def test_503_switches_to_the_fallback_at_once(self):
        """With a fallback, a 503 is not retried on the overloaded model (every retry
        costs a request of the daily quota): the next model takes over at once."""
        model_state = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash"],
            "gemini-2.5-flash",
        )
        primary_calls = [0]
        fallback_calls = [0]

        def fn(_client):
            if model_state.current == "gemini-2.5-flash":
                primary_calls[0] += 1
                err = RuntimeError("503 Service Unavailable")
                err.code = 503  # type: ignore[attr-defined]
                raise err
            fallback_calls[0] += 1
            return "ok"

        _client, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="gemini-2.5-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=2,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0, 0.0),
            rate_limit_sleep_seconds=0.0,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(primary_calls[0], 1, "no retries on the overloaded model")
        self.assertEqual(model_state.current, "gemini-3.6-flash")
        self.assertEqual(fallback_calls[0], 1)


class QuotaModelFallbackTests(unittest.TestCase):
    """When quota is exhausted and no replacement key is provided, retry_with_quota
    must raise QuotaDailyLimitError without automatic model switching."""

    def test_quota_exhaustion_without_replacement_key_raises_quota_error(self):
        """Quota exhaustion with no replacement key must raise QuotaDailyLimitError and not switch model."""
        model_state = build_model_state("gemini-2.5-flash", ["gemini-3.6-flash"])
        switched = []

        def fn(_client):
            if model_state.current == "gemini-2.5-flash":
                raise RuntimeError("429 quota exceeded daily limit per day")
            return "ok"

        with self.assertRaises(QuotaDailyLimitError):
            self._run(
                fn,
                model_state=model_state,
                on_model_switched=lambda old, new: switched.append((old, new)),
            )
        self.assertEqual(model_state.current, "gemini-2.5-flash")
        self.assertEqual(switched, [])

    def test_all_keys_exhausted_no_fallback_raises_quota_error(self):
        """No fallback model in chain → QuotaDailyLimitError (regression guard)."""
        model_state = build_model_state("gemini-2.5-flash", [])

        def fn(_client):
            raise RuntimeError("429 quota exceeded daily limit per day")

        with self.assertRaises(QuotaDailyLimitError):
            self._run(fn, model_state=model_state)

    def test_all_keys_exhausted_no_model_state_raises_quota_error(self):
        """model_state=None → QuotaDailyLimitError (no chain to cascade through)."""

        def fn(_client):
            raise RuntimeError("429 quota exceeded daily limit per day")

        with self.assertRaises(QuotaDailyLimitError):
            self._run(fn, model_state=None)

    def _run(
        self,
        fn,
        model_state=None,
        fallback_keys=None,
        max_attempts=2,
        on_model_switched=None,
    ):
        return retry_with_quota(
            fn,
            client=object(),
            fallback_keys=fallback_keys if fallback_keys is not None else [],
            model_name="gemini-2.5-flash",
            model_state=model_state,
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=max_attempts,
            retry_sleep_seconds=0.0,
            model_unavailable_retry_delays=(0.0, 0.0),
            rate_limit_sleep_seconds=0.0,
            on_model_switched=on_model_switched,
        )


class CircuitBreakerExhaustedErrorTests(unittest.TestCase):
    """503 circuit-breaker exhaustion path raises CircuitBreakerExhaustedError."""

    def _make_503(self):
        err = RuntimeError("503 Service Unavailable")
        err.code = 503  # type: ignore[attr-defined]
        return err

    def test_all_models_503_raises_circuit_breaker_exhausted_error(self):
        """When 503 retries are exhausted, retry_with_quota raises CircuitBreakerExhaustedError."""
        model_state = build_model_state(
            "gemini-2.5-flash",
            ["gemini-3.6-flash"],
            "gemini-2.5-flash",
        )

        def fn(_client):
            raise self._make_503()

        with self.assertRaises(CircuitBreakerExhaustedError):
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0,),
                rate_limit_sleep_seconds=0.0,
            )


class IsModelUnavailableTests(unittest.TestCase):
    def _yes(self, text):
        self.assertTrue(
            _is_model_unavailable(text, 503),
            f"expected True for: {text!r}",
        )

    def _no(self, text, code=503):
        self.assertFalse(
            _is_model_unavailable(text, code),
            f"expected False for: {text!r} (code={code})",
        )

    def test_service_unavailable_matches(self):
        self._yes("503 service unavailable")

    def test_temporarily_unavailable_matches(self):
        self._yes("the model is temporarily unavailable, please retry")

    def test_backend_error_matches(self):
        self._yes("backend error encountered")

    def test_model_is_overloaded_matches(self):
        self._yes("model is overloaded")

    def test_overloaded_matches(self):
        self._yes("overloaded")

    def test_token_unavailable_does_not_match(self):
        """Regression: bare 'unavailable' was removed; 'token unavailable' must not trigger model switch."""
        self._no("token unavailable")

    def test_feature_unavailable_does_not_match(self):
        """Regression: bare 'unavailable' was removed; 'feature unavailable' must not trigger model switch."""
        self._no("feature unavailable")

    def test_non_503_code_never_matches(self):
        self._no("service unavailable", code=500)
        self._no("overloaded", code=429)


class Phase1TemperatureTests(unittest.TestCase):
    def setUp(self):
        from jot.services.generation_service import _phase1_temperature

        self._t = _phase1_temperature

    def test_temperature_for_supported_models(self):
        self.assertEqual(self._t("gemini-3.5-flash"), 0.35)
        self.assertEqual(self._t("gemini-2.5-flash"), 0.35)
        self.assertEqual(self._t("gemini-3.6-flash"), 0.35)

    def test_unknown_model_falls_back_to_035(self):
        self.assertEqual(self._t("gemini-unknown-model"), 0.35)

    def test_derives_from_model_options(self):
        from unittest.mock import patch

        from jot.core.model_registry import MODEL_OPTIONS

        patched = tuple(
            {**opt, "phase1_temperature": 0.99}
            if opt["id"] == "gemini-2.5-flash"
            else opt
            for opt in MODEL_OPTIONS
        )
        with patch("jot.services.generation_service.MODEL_OPTIONS", patched):
            self.assertEqual(self._t("gemini-2.5-flash"), 0.99)


if __name__ == "__main__":
    unittest.main()


# ============================================================
# Helper-function unit tests
# ============================================================


class ErrorHelperTests(unittest.TestCase):
    """_error_text, _error_code, _is_daily_or_key_exhausted"""

    def test_error_text_details_typeerror_fallback(self):
        from jot.services.generation_service import _error_text

        exc = RuntimeError("boom")
        exc.details = {"bad": {1, 2, 3}}  # type: ignore[attr-defined]
        result = _error_text(exc)
        self.assertIn("boom", result)
        self.assertIn("bad", result)

    def test_error_text_includes_response_text(self):
        from jot.services.generation_service import _error_text

        class _FakeResponse:
            text = "too many requests"

        exc = RuntimeError("err")
        exc.response = _FakeResponse()  # type: ignore[attr-defined]
        result = _error_text(exc)
        self.assertIn("too many requests", result)

    def test_error_code_non_numeric_returns_none(self):
        from jot.services.generation_service import _error_code

        exc = RuntimeError("err")
        exc.code = "NOT_A_NUMBER"  # type: ignore[attr-defined]
        self.assertIsNone(_error_code(exc))

    def test_is_daily_exhausted_token_markers(self):
        from jot.services.generation_service import _is_daily_or_key_exhausted

        self.assertTrue(_is_daily_or_key_exhausted("token balance exhausted", None))
        self.assertTrue(_is_daily_or_key_exhausted("tokens exceeded", None))

    def test_is_daily_exhausted_503_resource_exhausted(self):
        from jot.services.generation_service import _is_daily_or_key_exhausted

        self.assertTrue(_is_daily_or_key_exhausted("resource_exhausted", 503))

    def test_is_daily_not_exhausted_for_minute_rate_limit(self):
        from jot.services.generation_service import _is_daily_or_key_exhausted

        self.assertFalse(_is_daily_or_key_exhausted("rate limit per minute", 429))

    def test_is_daily_exhausted_google_free_tier_official_error(self):
        from jot.services.generation_service import (
            _is_daily_or_key_exhausted,
            _is_minute_scoped_rate_limit,
        )

        err_msg = (
            "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, "
            "please check your plan and billing details. ... Quota exceeded for metric: "
            "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-2.5-flash "
            "Please retry in 3.13297873s.', 'details': [{'violations': [{'quotaMetric': "
            "'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
            "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '20'}]}]}}"
        )
        self.assertTrue(_is_daily_or_key_exhausted(err_msg, 429))
        self.assertFalse(_is_minute_scoped_rate_limit(err_msg, 429))


class ExtractClientApiKeyTests(unittest.TestCase):
    def test_nested_api_client_path(self):
        from jot.services.generation_service import extract_client_api_key

        class _Inner:
            api_key = "inner-key-xyz"

        class _Outer:
            api_key = None
            _api_client = _Inner()

        self.assertEqual(extract_client_api_key(_Outer()), "inner-key-xyz")

    def test_exception_returns_none(self):
        from jot.services.generation_service import extract_client_api_key

        class _BadClient:
            @property
            def api_key(self):
                raise RuntimeError("no attr")

            @property
            def _api_client(self):
                raise RuntimeError("no attr")

        self.assertIsNone(extract_client_api_key(_BadClient()))


class LoadFallbackKeysTests(unittest.TestCase):
    def test_returns_keys_from_config(self):
        from jot.services.generation_service import load_fallback_keys

        with patch(
            "jot.services.generation_service.load_config",
            return_value={"fallback_keys": ["key1", "key2", ""]},
        ):
            self.assertEqual(load_fallback_keys(), ["key1", "key2"])

    def test_returns_empty_on_exception(self):
        from jot.services.generation_service import load_fallback_keys

        with patch(
            "jot.services.generation_service.load_config",
            side_effect=RuntimeError("no config"),
        ):
            self.assertEqual(load_fallback_keys(), [])


class TryRotateKeyEdgeCaseTests(unittest.TestCase):
    def test_empty_key_skipped_then_valid_key_rotated(self):
        from jot.services.generation_service import try_rotate_key

        keys = ["", "valid-key"]

        class _FakeModels:
            def get(self, model=None, **_):
                return True

        class _FakeClient:
            def __init__(self, api_key=None, **_):
                self.models = _FakeModels()

        with patch("jot.services.generation_service.genai.Client", _FakeClient):
            _, rotated, key = try_rotate_key(object(), keys, "test-model")

        self.assertTrue(rotated)
        self.assertEqual(key, "valid-key")
        self.assertEqual(keys, [])

    def test_cancel_at_loop_start_returns_original(self):
        from jot.services.generation_service import try_rotate_key

        cancel = threading.Event()
        cancel.set()
        original = object()
        returned, rotated, key = try_rotate_key(
            original, ["some-key"], "test-model", cancelled=cancel.is_set
        )
        self.assertIs(returned, original)
        self.assertFalse(rotated)
        self.assertIsNone(key)

    def test_cancel_after_validation_returns_original(self):
        from jot.services.generation_service import try_rotate_key

        cancel = threading.Event()

        class _FakeModels:
            def get(self, model=None, **_):
                cancel.set()
                return True

        class _FakeClient:
            def __init__(self, api_key=None, **_):
                self.models = _FakeModels()

        with patch("jot.services.generation_service.genai.Client", _FakeClient):
            _returned, rotated, key = try_rotate_key(
                object(), ["valid-key"], "test-model", cancelled=cancel.is_set
            )
        self.assertFalse(rotated)
        self.assertIsNone(key)


class WaitForFileReadyTests(unittest.TestCase):
    def test_timeout_raises_timeout_error(self):
        from jot.services.generation_service import wait_for_file_ready

        class _PendingFile:
            state = "PENDING"
            name = "files/x"

        from unittest.mock import MagicMock

        client = MagicMock()
        client.files.get.return_value = _PendingFile()
        with patch(
            "jot.services.generation_service.sleep_with_cancel",
            return_value=True,
        ):
            with self.assertRaises(TimeoutError):
                wait_for_file_ready(
                    client,
                    _PendingFile(),
                    lambda: False,
                    max_wait_seconds=0,
                    poll_seconds=1,
                )

    def test_failed_state_raises_runtime_error(self):
        from jot.services.generation_service import wait_for_file_ready

        class _FailedFile:
            state = "FAILED"
            name = "files/x"

        with self.assertRaises(RuntimeError) as ctx:
            wait_for_file_ready(
                object(),
                _FailedFile(),
                lambda: False,
            )
        self.assertIn("FAILED", str(ctx.exception))

    def test_cancel_during_poll_returns_none(self):
        from jot.services.generation_service import wait_for_file_ready

        class _PendingFile:
            state = "PENDING"
            name = "files/x"

        with patch(
            "jot.services.generation_service.sleep_with_cancel",
            return_value=False,
        ):
            result = wait_for_file_ready(
                object(),
                _PendingFile(),
                lambda: True,
                max_wait_seconds=9999,
                poll_seconds=1,
            )
        self.assertIsNone(result)


class UploadMakeInlineTests(unittest.TestCase):
    def test_upload_audio_path_typeerror_fallback(self):
        from unittest.mock import MagicMock

        from jot.services.generation_service import upload_audio_path

        client = MagicMock()
        client.files.upload.side_effect = [TypeError("no path kwarg"), "uploaded"]
        result = upload_audio_path(client, "/fake/path.mp3")
        self.assertEqual(result, "uploaded")
        self.assertEqual(client.files.upload.call_count, 2)

    def test_make_inline_audio_part_size_exceeded_returns_none(self):
        from jot.services.generation_service import make_inline_audio_part

        with patch("os.path.getsize", return_value=10_000_000):
            result = make_inline_audio_part("/fake/file.mp3", max_bytes=5_000_000)
        self.assertIsNone(result)

    def test_make_inline_audio_part_open_exception_returns_none(self):
        from jot.services.generation_service import make_inline_audio_part

        with patch("builtins.open", side_effect=FileNotFoundError("no file")):
            result = make_inline_audio_part("/nonexistent.mp3")
        self.assertIsNone(result)


class RequestNewApiKeyTests(unittest.TestCase):
    def test_returns_key_when_provided(self):
        from jot.services.generation_service import request_new_api_key

        class _FakeRuntime:
            def ask_new_api_key(self, callback):
                callback({"key": "new-key-123"})
                return True

        result = request_new_api_key(_FakeRuntime(), lambda: False)
        self.assertEqual(result, "new-key-123")

    def test_returns_none_when_ask_returns_false(self):
        from jot.services.generation_service import request_new_api_key

        class _FakeRuntime:
            def ask_new_api_key(self, callback):
                return False

        self.assertIsNone(request_new_api_key(_FakeRuntime(), lambda: False))

    def test_returns_none_when_cancelled_before_event(self):
        from jot.services.generation_service import request_new_api_key

        cancel = threading.Event()
        cancel.set()

        class _FakeRuntime:
            def ask_new_api_key(self, callback):
                return True

        self.assertIsNone(request_new_api_key(_FakeRuntime(), cancel.is_set))

    def test_returns_none_and_marks_timeout(self):
        from jot.services.generation_service import request_new_api_key

        timeout_called = threading.Event()

        class _FakeRuntime:
            dismissed = False

            def ask_new_api_key(self, callback):
                return True

            def dismiss_new_api_key_prompt(self):
                self.dismissed = True

        runtime = _FakeRuntime()
        result = request_new_api_key(
            runtime,
            lambda: False,
            timeout_seconds=0.01,
            on_timeout=timeout_called.set,
        )

        self.assertIsNone(result)
        self.assertTrue(timeout_called.is_set())
        self.assertTrue(runtime.dismissed)


class ExtractResponseTextMoreTests(unittest.TestCase):
    def test_text_none_returns_empty(self):
        from jot.services.generation_service import extract_response_text

        class _Resp:
            text = None

        self.assertEqual(extract_response_text(_Resp()), "")

    def test_text_non_string_coerced(self):
        from jot.services.generation_service import extract_response_text

        class _Resp:
            text = 42

        self.assertEqual(extract_response_text(_Resp()), "42")

    def test_candidates_fallback_when_text_empty(self):
        from jot.services.generation_service import extract_response_text

        class _Part:
            text = "Candidate text content"

        class _Content:
            parts: ClassVar = [_Part()]

        class _Candidate:
            content = _Content()

        class _Resp:
            text = ""
            candidates: ClassVar = [_Candidate()]

        self.assertEqual(extract_response_text(_Resp()), "Candidate text content")


class BuildChunkPromptTests(unittest.TestCase):
    def test_with_previous_tail_includes_continuation(self):
        from jot.services.generation_service import build_chunk_prompt

        prompt = build_chunk_prompt("...ultimi chars del blocco precedente")
        self.assertIn("ATTENZIONE", prompt)
        self.assertIn("continuando", prompt)
        self.assertIn("ultimi chars del blocco precedente", prompt)

    def test_without_previous_tail_no_continuation(self):
        from jot.services.generation_service import build_chunk_prompt

        prompt = build_chunk_prompt("")
        self.assertNotIn("ATTENZIONE", prompt)
        self.assertIn("Trascrivi", prompt)


class DetectDegenerateMoreTests(unittest.TestCase):
    def test_whitespace_only_returns_none(self):
        self.assertIsNone(detect_degenerate_output("   \n\n  "))

    def test_empty_string_returns_none(self):
        self.assertIsNone(detect_degenerate_output(""))

    def test_long_paragraph_flagged(self):
        long_para = "parola " * 2000
        result = detect_degenerate_output(long_para)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("troppo lungo", result)

    def test_duplicate_paragraph_ratio_threshold(self):
        para = "A " * 50
        other = "B " * 50
        text = "\n\n".join([para.strip()] * 9 + [other.strip()])
        result = detect_degenerate_output(text)
        self.assertIsNotNone(result)

    def test_eccessivo_output_flagged(self):
        one_big = "A " * 25000
        text = "\n\n".join([one_big.strip()] * 5)
        result = detect_degenerate_output(text)
        self.assertIsNotNone(result)


class RetryWithQuotaEdgeTests(unittest.TestCase):
    def setUp(self):
        reset_global_governor()

    def tearDown(self):
        reset_global_governor()

    def test_cancelled_at_start_skips_fn(self):
        called = []

        def fn(c):
            called.append(1)

        _, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="test",
            cancelled=lambda: True,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=3,
            retry_sleep_seconds=0.0,
        )
        self.assertIsNone(result)
        self.assertEqual(called, [])

    def test_zero_max_attempts_returns_none(self):
        called = []

        def fn(c):
            called.append(1)

        _, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="test",
            cancelled=lambda: False,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=0,
            retry_sleep_seconds=0.0,
        )
        self.assertIsNone(result)
        self.assertEqual(called, [])

    def test_permanent_error_propagates_immediately(self):
        from jot.services.generation_service import PermanentError

        def fn(_c):
            raise PermanentError("400 INVALID_ARGUMENT")

        with self.assertRaises(PermanentError):
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="test",
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=3,
                retry_sleep_seconds=0.0,
            )

    def test_cancel_before_key_rotation_returns_none(self):
        calls = [0]

        def cancel_fn():
            calls[0] += 1
            return calls[0] >= 3

        def fn(_c):
            raise RuntimeError("429 quota exceeded daily limit per day")

        _, result = retry_with_quota(
            fn,
            client=object(),
            fallback_keys=[],
            model_name="test",
            cancelled=cancel_fn,
            runtime=_FakeRuntime(),
            request_fallback_key=lambda: None,
            max_attempts=2,
            retry_sleep_seconds=0.0,
            rate_limit_sleep_seconds=0.0,
        )
        self.assertIsNone(result)

    def test_on_key_rotated_called_after_successful_rotation(self):
        rotated = []

        class _FakeModels:
            def get(self, model=None, **_):
                return True

        class _FakeClient:
            def __init__(self, api_key=None, **_):
                self.models = _FakeModels()

        call_count = [0]

        def fn(_c):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("quota exceeded daily limit per day")
            return "ok"

        rotated_client = _FakeClient(api_key="rotated-key")
        request_mock = MagicMock(
            side_effect=AssertionError(
                "request_fallback_key must not be called when fallback key rotates automatically"
            )
        )

        with patch(
            "jot.services.generation_service.genai.Client",
            return_value=rotated_client,
        ):
            _, result = retry_with_quota(
                fn,
                client=object(),
                fallback_keys=["rotated-key"],
                model_name="test",
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=request_mock,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                rate_limit_sleep_seconds=0.0,
                on_key_rotated=lambda c: rotated.append(c),
            )

        self.assertEqual(result, "ok")
        self.assertEqual(len(rotated), 1)
        request_mock.assert_not_called()

    def test_new_api_key_valid_continues(self):
        from unittest.mock import MagicMock

        key_provided = ["new-valid-key"]
        call_count = [0]

        def fn(_c):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("429 quota exceeded daily limit per day")
            return "ok"

        class _FakeModels:
            def get(self, model=None, **_):
                return True

        class _FakeClient:
            def __init__(self, api_key=None, **_):
                self.models = _FakeModels()

        def request_key():
            return key_provided.pop(0) if key_provided else None

        with patch("jot.services.generation_service.genai.Client", _FakeClient):
            _, result = retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="test",
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=request_key,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                rate_limit_sleep_seconds=0.0,
            )

        self.assertEqual(result, "ok")

    def test_new_api_key_invalid_falls_through_to_quota_error(self):
        def fn(_c):
            raise RuntimeError("429 quota exceeded daily limit per day")

        class _BadModels:
            def get(self, model=None, **_):
                raise RuntimeError("invalid key")

        class _BadClient:
            def __init__(self, api_key=None, **_):
                self.models = _BadModels()

        with patch("jot.services.generation_service.genai.Client", _BadClient):
            with self.assertRaises(QuotaDailyLimitError):
                retry_with_quota(
                    fn,
                    client=object(),
                    fallback_keys=[],
                    model_name="test",
                    cancelled=lambda: False,
                    runtime=_FakeRuntime(),
                    request_fallback_key=lambda: "bad-key",
                    max_attempts=2,
                    retry_sleep_seconds=0.0,
                    rate_limit_sleep_seconds=0.0,
                )

    def test_cancel_during_rate_limit_sleep_returns_none(self):
        def fn(_c):
            err = RuntimeError("429 Too Many Requests per minute")
            err.code = 429  # type: ignore[attr-defined]
            raise err

        with patch(
            "jot.services.generation_service.sleep_with_cancel",
            return_value=False,
        ):
            _, result = retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="test",
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=3,
                retry_sleep_seconds=0.0,
                rate_limit_sleep_seconds=0.0,
            )
        self.assertIsNone(result)

    def test_cancel_during_generic_retry_sleep_returns_none(self):
        call_count = [0]

        def fn(_c):
            call_count[0] += 1
            raise RuntimeError("transient network error")

        with patch(
            "jot.services.generation_service.sleep_with_cancel",
            return_value=False,
        ):
            _, result = retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="test",
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=3,
                retry_sleep_seconds=0.0,
            )

        self.assertIsNone(result)
        self.assertEqual(call_count[0], 1)

    def test_cancel_during_503_inner_retry_attempt(self):
        """Cancel fires inside the inner-retry callable (line 561 path), not just the outer catch."""
        model_state = build_model_state(
            "gemini-2.5-flash", ["gemini-3.6-flash"], "gemini-2.5-flash"
        )
        cancel = threading.Event()
        call_count = [0]
        original_client = object()

        def fn(_c):
            call_count[0] += 1
            if call_count[0] == 1:
                err = RuntimeError("503 Service Unavailable")
                err.code = 503  # type: ignore[attr-defined]
                raise err
            cancel.set()
            raise RuntimeError("inner retry error")

        with patch(
            "jot.services.generation_service.sleep_with_cancel",
            return_value=True,
        ):
            returned_client, result = retry_with_quota(
                fn,
                client=original_client,
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                model_state=model_state,
                cancelled=cancel.is_set,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0,),
                rate_limit_sleep_seconds=0.0,
            )

        self.assertIsNone(result)
        self.assertIs(returned_client, original_client)
        self.assertEqual(call_count[0], 2)


class AdaptiveGovernorTests(unittest.TestCase):
    def setUp(self):
        reset_global_governor()

    def tearDown(self):
        reset_global_governor()

    def test_governor_normal_flow_zero_latency(self):
        gov = AdaptiveGovernor()
        sleep_called = []
        with patch(
            "jot.services.generation_service.sleep_with_cancel",
            lambda cb, dur: sleep_called.append(dur) or True,
        ):
            self.assertTrue(gov.wait_if_needed(lambda: False))
        self.assertEqual(sleep_called, [])

    def test_governor_on_503_exponential_backoff_and_jitter(self):
        gov = AdaptiveGovernor()
        fixed_time = [100.0]
        with patch("time.monotonic", lambda: fixed_time[0]):
            delay1 = gov.on_503(
                base_delay=15.0, max_delay=60.0, jitter_range=(0.5, 0.5)
            )
            self.assertEqual(gov.consecutive_503, 1)
            self.assertAlmostEqual(delay1, 15.5)
            self.assertAlmostEqual(gov.next_allowed_at, 115.5)

            delay2 = gov.on_503(
                base_delay=30.0, max_delay=60.0, jitter_range=(1.0, 1.0)
            )
            self.assertEqual(gov.consecutive_503, 2)
            self.assertAlmostEqual(delay2, 31.0)
            self.assertAlmostEqual(gov.next_allowed_at, 131.0)

            delay3 = gov.on_503(
                base_delay=60.0, max_delay=60.0, jitter_range=(2.0, 2.0)
            )
            self.assertEqual(gov.consecutive_503, 3)
            self.assertAlmostEqual(delay3, 62.0)
            self.assertAlmostEqual(gov.next_allowed_at, 162.0)

    def test_governor_on_429_uses_retry_after_or_default(self):
        gov = AdaptiveGovernor()
        fixed_time = [100.0]
        with patch("time.monotonic", lambda: fixed_time[0]):
            delay1 = gov.on_429(
                retry_after=42.0, default_delay=65.0, jitter_range=(0.5, 0.5)
            )
            self.assertEqual(gov.consecutive_429, 1)
            self.assertAlmostEqual(delay1, 42.5)
            self.assertAlmostEqual(gov.next_allowed_at, 142.5)

            delay2 = gov.on_429(
                retry_after=None, default_delay=65.0, jitter_range=(0.5, 0.5)
            )
            self.assertEqual(gov.consecutive_429, 2)
            self.assertAlmostEqual(delay2, 65.5)
            self.assertAlmostEqual(gov.next_allowed_at, 165.5)

    def test_governor_on_success_resets_counters_preserves_active_cooldown(self):
        gov = AdaptiveGovernor(
            next_allowed_at=150.0, consecutive_503=3, consecutive_429=2
        )
        gov.on_success()
        self.assertEqual(gov.consecutive_503, 0)
        self.assertEqual(gov.consecutive_429, 0)
        self.assertEqual(gov.next_allowed_at, 150.0)

    def test_governor_reset_clears_all(self):
        gov = AdaptiveGovernor(
            next_allowed_at=150.0, consecutive_503=3, consecutive_429=2
        )
        gov.reset()
        self.assertEqual(gov.consecutive_503, 0)
        self.assertEqual(gov.consecutive_429, 0)
        self.assertEqual(gov.next_allowed_at, 0.0)

    def test_governor_cancellation(self):
        gov = AdaptiveGovernor(next_allowed_at=200.0)
        with patch("time.monotonic", return_value=100.0):
            # When cancelled() returns True, sleep_with_cancel returns False
            res = gov.wait_if_needed(lambda: True)
            self.assertFalse(res)

    def test_golden_flow_chunk3_error_and_chunk4_residual_cooldown(self):
        """Golden Test:

        T0: Chunk 3 gets 503 -> sets next_allowed_at = T0 + 15s.
        T0 + 5s: Chunk 3 retry succeeds -> governor preserves next_allowed_at = T0 + 15s.
        T0 + 6s: Chunk 4 starts -> wait_if_needed() enforces 9s remaining wait.
        T0 + 15s: Chunk 4 executes -> succeeds -> resets consecutive counters.
        """
        gov = AdaptiveGovernor()
        cur_time = [100.0]  # T0
        sleeps_recorded: list[float] = []

        def fake_sleep(_cb, duration):
            sleeps_recorded.append(duration)
            cur_time[0] += duration
            return True

        with (
            patch("time.monotonic", lambda: cur_time[0]),
            patch(
                "jot.services.generation_service.sleep_with_cancel",
                fake_sleep,
            ),
        ):
            # T0: Chunk 3 first attempt fails with 503
            delay = gov.on_503(base_delay=14.5, jitter_range=(0.5, 0.5))
            self.assertAlmostEqual(delay, 15.0)
            self.assertAlmostEqual(gov.next_allowed_at, 115.0)  # T0 + 15s

            # Chunk 3 retry happens at T0 + 5s
            cur_time[0] = 105.0  # T0 + 5s
            # Chunk 3 retry succeeds
            gov.on_success()
            self.assertEqual(gov.consecutive_503, 0)
            self.assertAlmostEqual(gov.next_allowed_at, 115.0)  # Preserved

            # T0 + 6s: Chunk 4 starts
            cur_time[0] = 106.0  # T0 + 6s
            allowed = gov.wait_if_needed(lambda: False)
            self.assertTrue(allowed)
            # Must have slept for 9.0s (115.0 - 106.0)
            self.assertEqual(len(sleeps_recorded), 1)
            self.assertAlmostEqual(sleeps_recorded[0], 9.0)
            self.assertAlmostEqual(cur_time[0], 115.0)

            # Chunk 4 succeeds
            gov.on_success()
            self.assertEqual(gov.consecutive_503, 0)
            self.assertEqual(gov.consecutive_429, 0)

            # Subsequent call at 115.0s proceeds without sleep
            allowed_subsequent = gov.wait_if_needed(lambda: False)
            self.assertTrue(allowed_subsequent)
            self.assertEqual(len(sleeps_recorded), 1)  # No extra sleep

    def test_governor_get_state_payload(self):
        gov = AdaptiveGovernor()
        gov.model = "gemini-2.5-flash"
        with patch("time.monotonic", return_value=100.0):
            gov.on_503(
                base_delay=15.0,
                jitter_range=(0.0, 0.0),
                model="gemini-2.5-flash",
                attempt=2,
            )
            payload = gov.get_state_payload()
            self.assertEqual(payload["state"], "cooling_down")
            self.assertEqual(payload["reason"], "503_service_unavailable")
            self.assertEqual(payload["model"], "gemini-2.5-flash")
            self.assertEqual(payload["attempt"], 2)
            self.assertEqual(payload["max_attempts"], 4)
            self.assertIsInstance(payload["next_retry_at"], str)
            self.assertTrue(str(payload["next_retry_at"]).endswith("+00:00"))
            self.assertEqual(payload["seconds_remaining"], 15.0)

    def test_persistent_503_uses_four_total_calls_and_15_30_60_backoff(self):
        calls = 0
        sleeps: list[float] = []
        runtime = _FakeRuntime()

        def fn(_client):
            nonlocal calls
            calls += 1
            err = RuntimeError("503 Service Unavailable")
            err.code = 503  # type: ignore[attr-defined]
            raise err

        with (
            patch(
                "jot.services.generation_service.random.uniform",
                return_value=0.0,
            ),
            patch(
                "jot.services.generation_service.sleep_with_cancel",
                side_effect=lambda _cancelled, delay: sleeps.append(delay) or True,
            ),
            self.assertRaises(CircuitBreakerExhaustedError) as raised,
        ):
            retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                cancelled=lambda: False,
                runtime=runtime,
                request_fallback_key=lambda: None,
            )

        self.assertEqual(calls, 4)
        self.assertEqual(sleeps, [15.0, 30.0, 60.0])
        self.assertEqual(raised.exception.attempts, 4)
        self.assertEqual(
            [state["state"] for state in runtime.retry_states],
            [
                "cooling_down",
                "probing",
                "cooling_down",
                "probing",
                "cooling_down",
                "probing",
                "exhausted",
            ],
        )

    def test_governor_thread_safety(self):
        gov = AdaptiveGovernor()
        errors = []

        def worker():
            try:
                for _ in range(50):
                    gov.on_503(base_delay=0.01, jitter_range=(0.0, 0.0))
                    gov.get_state_payload()
                    gov.on_success()
                    gov.reset()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    def test_offline_network_polling_does_not_consume_attempts(self):
        call_count = [0]

        def is_offline(exc):
            return "offline" in str(exc).lower()

        def fn(_c):
            call_count[0] += 1
            if call_count[0] <= 3:
                raise RuntimeError("Network offline: unreachable host")
            return "recovered"

        with (
            patch(
                "jot.services.network_service.is_network_offline_error",
                side_effect=is_offline,
            ),
            patch(
                "jot.services.generation_service.sleep_with_cancel",
                return_value=True,
            ),
        ):
            _, result = retry_with_quota(
                fn,
                client=object(),
                fallback_keys=[],
                model_name="gemini-2.5-flash",
                cancelled=lambda: False,
                runtime=_FakeRuntime(),
                request_fallback_key=lambda: None,
                max_attempts=2,
                retry_sleep_seconds=0.0,
                model_unavailable_retry_delays=(0.0, 0.0),
                rate_limit_sleep_seconds=0.0,
            )

        self.assertEqual(result, "recovered")
        self.assertEqual(call_count[0], 4)
