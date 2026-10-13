"""
Gemini-centric helpers for the transcription pipeline.

This keeps transport/retry/prompt helpers out of pipeline.py so the remaining
module can focus more on orchestration.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from google import genai
from google.genai import types

from jot.core.model_registry import (
    MODEL_OPTIONS,
    ModelState,
    next_model_in_chain,
)
from jot.services import network_service, usage_service
from jot.services.config_service import load_config
from jot.services.gemini_errors import (
    AllModelsUnavailableError,
    CircuitBreakerExhaustedError,
    DegenerateOutputError,
    PermanentError,
    QuotaDailyLimitError,
    _error_code,
    _error_text,
    _is_daily_or_key_exhausted,
    _is_deterministic_client_error,
    _is_invalid_key_probe_failure,
    _is_minute_scoped_rate_limit,
    _is_model_not_found,
    _is_model_unavailable,
    _is_quota_related,
    _is_transient_capacity_or_server_error,
    _is_transient_key_probe_failure,
    _normalize_guardrail_text,
    classify_429_error,
    classify_credential_status,
    detect_degenerate_output,
    extract_retry_after_seconds,
)
from jot.utils.logging_utils import get_logger, redact_secrets

# ---------------------------------------------------------------------------
# Module-level constants & Adaptive Governor
# ---------------------------------------------------------------------------

_FILE_UPLOAD_TIMEOUT_SECONDS: int = (
    900  # 15-minute ceiling for Google to finish processing an uploaded audio file
)
_FILE_UPLOAD_POLL_SECONDS: int = (
    3  # How often (seconds) to re-query file state while waiting
)

_MAX_RETRY_ATTEMPTS: int = (
    4  # Maximum Gemini API call attempts before suspending/propagating the error
)
_RETRY_SLEEP_SECONDS: float = 30.0  # Back-off pause between generic transient errors
_MODEL_UNAVAILABLE_RETRY_DELAYS: tuple[float, ...] = (
    15.0,
    30.0,
    60.0,
)  # Initial call, then three bounded probes with exponential backoff.
# Gemini enforces a per-minute request quota that resets after ~60 s; sleeping
# 65 s adds a small buffer to ensure the window has fully elapsed before retry.
_RATE_LIMIT_SLEEP_SECONDS: float = 65.0
_NEW_API_KEY_TIMEOUT_SECONDS: float = 600.0


# Longest wait for one request (upload, transcription of a 15-minute block,
# revision). Without a limit a connection that stalls half-way (Wi-Fi change,
# PC waking up, a hiccup on Google's side) leaves the lesson stuck on the same
# block forever; with it the request fails as a timeout and the usual retry
# and model-fallback logic takes over. Overridable with JOT_REQUEST_TIMEOUT_S.
_DEFAULT_REQUEST_TIMEOUT_SECONDS: int = 480


def request_timeout_ms() -> int:
    raw = os.environ.get("JOT_REQUEST_TIMEOUT_S", "")
    try:
        seconds = int(float(raw)) if raw.strip() else _DEFAULT_REQUEST_TIMEOUT_SECONDS
    except ValueError:
        seconds = _DEFAULT_REQUEST_TIMEOUT_SECONDS
    return max(30, min(seconds, 3600)) * 1000


def create_gemini_client(api_key: str) -> genai.Client:
    """Instantiate a Google GenAI Client with SDK-level retries explicitly disabled.

    generation_service is the sole retry authority to guarantee deterministic timings
    and exact telemetry counting. Every request has a time limit (see above).
    """
    cleaned_key = str(api_key or "").strip()
    http_opts = types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=1),
        timeout=request_timeout_ms(),
    )
    return genai.Client(api_key=cleaned_key, http_options=http_opts)


@dataclass
class AdaptiveGovernor:
    """Reactive timing governor and circuit breaker for rate limiting, backoff, and shared cooldown across chunks."""

    next_allowed_at: float = 0.0
    consecutive_503: int = 0
    consecutive_429: int = 0
    attempt: int = 1
    max_attempts: int = 4
    state: str = "idle"
    reason: str = ""
    model: str = ""
    last_error: str = ""
    recommended_retry_at_iso: str | None = None

    def wait_if_needed(
        self, cancelled: Callable[[], bool], runtime: Any = None
    ) -> bool:
        """Wait if cooldown or backoff is active. Returns False if cancelled."""
        remaining = self.next_allowed_at - time.monotonic()
        if remaining <= 0:
            if self.state in ("cooling_down", "probing"):
                self.state = "idle"
                self.reason = ""
            return True
        if runtime is not None and hasattr(runtime, "retry_state"):
            try:
                runtime.retry_state(self.get_state_payload())
            except Exception:
                pass
        return sleep_with_cancel(cancelled, remaining)

    def on_success(self) -> None:
        """Reset consecutive error counters without shortening active residual cooldowns."""
        self.consecutive_503 = 0
        self.consecutive_429 = 0
        self.attempt = 1
        self.state = "idle"
        self.reason = ""
        self.last_error = ""
        self.recommended_retry_at_iso = None

    def on_503(
        self,
        base_delay: float = 15.0,
        max_delay: float = 60.0,
        jitter_range: tuple[float, float] | None = None,
        model: str = "",
        attempt: int | None = None,
    ) -> float:
        """Record a 503/transient capacity error and compute backoff with positive jitter up to 10%."""
        self.consecutive_503 += 1
        self.model = model or self.model
        if attempt is not None:
            self.attempt = attempt
        else:
            self.attempt = min(self.max_attempts, self.consecutive_503 + 1)
        self.state = "cooling_down"
        self.reason = "503_service_unavailable"

        if base_delay <= 0.0:
            self.next_allowed_at = 0.0
            return 0.0

        if jitter_range is not None:
            jitter = random.uniform(*jitter_range)
        else:
            jitter = random.uniform(0.0, 0.10 * base_delay)

        delay = min(base_delay, max_delay) + jitter
        self.next_allowed_at = max(self.next_allowed_at, time.monotonic() + delay)
        return delay

    def on_429(
        self,
        retry_after: float | None = None,
        default_delay: float = 65.0,
        jitter_range: tuple[float, float] | None = None,
        model: str = "",
    ) -> float:
        """Record a 429 Rate Limit error and set cooldown for a single probe."""
        self.consecutive_429 += 1
        self.model = model or self.model
        self.attempt = 2
        self.state = "cooling_down"
        self.reason = "429_rate_limit_exceeded"

        base = (
            retry_after
            if retry_after is not None and retry_after > 0
            else default_delay
        )
        if base <= 0.0:
            self.next_allowed_at = 0.0
            return 0.0

        if jitter_range is not None:
            jitter = random.uniform(*jitter_range)
        else:
            jitter = random.uniform(0.0, 0.10 * base)

        delay = base + jitter
        self.next_allowed_at = max(self.next_allowed_at, time.monotonic() + delay)
        return delay

    def reset(self) -> None:
        """Hard reset of all state, including pending cooldowns and error counters."""
        self.next_allowed_at = 0.0
        self.consecutive_503 = 0
        self.consecutive_429 = 0
        self.attempt = 1
        self.state = "idle"
        self.reason = ""
        self.model = ""
        self.last_error = ""
        self.recommended_retry_at_iso = None

    def get_state_payload(self) -> dict[str, Any]:
        remaining = max(0.0, self.next_allowed_at - time.monotonic())
        next_retry_at = (
            (datetime.now(UTC) + timedelta(seconds=remaining)).isoformat()
            if remaining > 0
            else None
        )
        return {
            "state": self.state,
            "reason": self.reason,
            "model": self.model,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "next_retry_at": next_retry_at,
            "seconds_remaining": remaining if remaining > 0 else 0.0,
        }


_GLOBAL_GOVERNOR: AdaptiveGovernor = AdaptiveGovernor()


def get_governor() -> AdaptiveGovernor:
    """Return the global AdaptiveGovernor instance."""
    return _GLOBAL_GOVERNOR


def reset_global_governor() -> None:
    """Reset the global AdaptiveGovernor instance state."""
    _GLOBAL_GOVERNOR.reset()
    reset_model_overload()


# ---------------------------------------------------------------------------
# Which model and which key for the next request
# ---------------------------------------------------------------------------
# A model that answers 503 (overloaded) is put on hold for a while: the next
# requests go straight to the next model of the chain instead of being retried
# on it (every retry costs a request of the daily quota). When the pause is
# over, the better model is tried again with a single request.
MODEL_OVERLOAD_PAUSE_SECONDS: float = 20 * 60
_model_overloaded_until: dict[str, float] = {}
_model_back_from_pause: set[str] = set()
_overload_lock = threading.Lock()


def mark_model_overloaded(model: str, seconds: float | None = None) -> None:
    with _overload_lock:
        _model_overloaded_until[str(model)] = time.monotonic() + (
            MODEL_OVERLOAD_PAUSE_SECONDS if seconds is None else seconds
        )


def model_overloaded(model: str) -> bool:
    with _overload_lock:
        until = _model_overloaded_until.get(str(model))
        if until is None:
            return False
        if time.monotonic() >= until:
            _model_overloaded_until.pop(str(model), None)
            _model_back_from_pause.add(str(model))
            return False
        return True


def _take_back_from_pause(model: str) -> bool:
    """True once when ``model`` has just finished its pause (worth one new try)."""
    model_overloaded(model)
    with _overload_lock:
        if str(model) in _model_back_from_pause:
            _model_back_from_pause.discard(str(model))
            return True
        return False


def reset_model_overload() -> None:
    with _overload_lock:
        _model_overloaded_until.clear()
        _model_back_from_pause.clear()


def configured_keys() -> list[str]:
    """Main key first, then the reserve keys, as set in the settings."""
    try:
        cfg = load_config()
    except Exception:
        return []
    keys: list[str] = []
    for key in [cfg.get("api_key"), *(cfg.get("fallback_keys") or [])]:
        cleaned = str(key or "").strip()
        if cleaned and cleaned not in keys:
            keys.append(cleaned)
    return keys


def _key_with_quota(model: str, current_key: str, keys: list[str]) -> str | None:
    """The key to use for ``model``: the current one while it has requests left,
    then the others in order. A pair Google refused for quota is skipped; a pair
    that is full only by the local count is kept as a last resort."""
    last_resort = None
    for key in [current_key, *[k for k in keys if k != current_key]]:
        remaining, refused = usage_service.remaining_for(key, model)
        if refused:
            continue
        if remaining > 0:
            return key
        last_resort = last_resort or key
    return last_resort


def select_route(
    client,
    model_state: ModelState | None,
    *,
    on_model_switched=None,
    on_key_rotated=None,
    runtime=None,
):
    """Best model of the chain that is not on hold, with a key that still has
    requests for it. Returns the client to use (a new one when the key changes).
    With every model on hold, nothing changes: the normal retry logic decides."""
    if model_state is None:
        return client
    current_key = extract_client_api_key(client) or ""
    keys = configured_keys()
    use_keys = bool(current_key) and current_key in keys

    def usable(model: str) -> str | None:
        if model_overloaded(model):
            return None
        if not use_keys:
            return current_key or "-"
        return _key_with_quota(model, current_key, keys)

    chain = list(model_state.chain)
    current = model_state.current
    position = chain.index(current) if current in chain else len(chain)
    chosen: tuple[str, str] | None = None
    # a better model whose pause has just ended gets one new try
    for model in chain[:position]:
        if _take_back_from_pause(model):
            key = usable(model)
            if key:
                chosen = (model, key)
                break
    if chosen is None:
        key = usable(current)
        if key:
            chosen = (current, key)
    if chosen is None:
        # current model on hold or out of requests: the best one that can take over
        for model in chain:
            key = usable(model)
            if key:
                chosen = (model, key)
                break
    if chosen is None:
        return client
    model, key = chosen
    if key == "-":
        key = current_key
    if model != model_state.current:
        old = model_state.current
        model_state.current = model
        print(f"      [Modello] {old} -> {model}")
        if on_model_switched is not None:
            on_model_switched(old, model)
    if use_keys and key and key != current_key:
        client = create_gemini_client(key)
        print(f"      [Chiave] passo a {usage_service.mask_key(key)} per {model}")
        if runtime is not None and hasattr(runtime, "set_effective_api_key"):
            runtime.set_effective_api_key(key)
        if on_key_rotated is not None:
            on_key_rotated(client)
    return client


def _ready_to_send(cancelled, gov, runtime) -> bool:
    """False when the user stopped the work (also while waiting for the governor)."""
    if cancelled():
        return False
    if not gov.wait_if_needed(cancelled, runtime=runtime):
        print("   [*] Operazione annullata dall'utente.")
        return False
    return True


def _move_off_overloaded_model(
    client,
    model_state: ModelState | None,
    current_model: str,
    *,
    on_model_switched=None,
    on_key_rotated=None,
    runtime=None,
    applies: bool = True,
):
    """First 503 on a model: put it on hold and continue at once on the next one.
    Returns the new client, or None when no other model can take over."""
    if not applies or model_state is None or len(model_state.chain) < 2:
        return None
    mark_model_overloaded(current_model)
    new_client = select_route(
        client,
        model_state,
        on_model_switched=on_model_switched,
        on_key_rotated=on_key_rotated,
        runtime=runtime,
    )
    if model_state.current == current_model:
        return None
    usage_service.record_retry_event("503")
    print(
        f"      [Modello {current_model} sovraccarico (503): in pausa per"
        f" {int(MODEL_OVERLOAD_PAUSE_SECONDS // 60)} minuti, continuo con {model_state.current}]"
    )
    return new_client


def current_model_name(model_state: ModelState | None, default_model: str) -> str:
    if model_state is None:
        return str(default_model or "").strip()
    current = str(getattr(model_state, "current", "") or "").strip()
    return current or str(default_model or "").strip()


def extract_client_api_key(client_obj) -> str | None:
    try:
        direct = getattr(client_obj, "api_key", None) or getattr(
            client_obj, "_api_key", None
        )
        if direct:
            return str(direct).strip() or None
    except Exception:
        pass
    try:
        api_client = getattr(client_obj, "_api_client", None)
        nested = getattr(api_client, "api_key", None) or getattr(
            api_client, "_api_key", None
        )
        if nested:
            return str(nested).strip() or None
    except Exception:
        pass
    return None


def sleep_with_cancel(
    cancelled: Callable[[], bool], seconds: float, step: float = 0.2
) -> bool:
    deadline = time.monotonic() + float(seconds)
    while time.monotonic() < deadline:
        if cancelled():
            return False
        time.sleep(min(step, deadline - time.monotonic()))
    return True


def load_fallback_keys() -> list[str]:
    try:
        config = load_config()
        raw = config.get("fallback_keys", [])
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
    except Exception:
        pass
    return []


def try_rotate_key(
    current_client,
    fallback_keys: list[str],
    model_name: str,
    logger=None,
    cancelled: Callable[[], bool] | None = None,
):
    """Validate and rotate to a fallback key from a provided list."""
    log = logger or get_logger("jot.generation")
    pass_limit = len([str(item).strip() for item in fallback_keys if str(item).strip()])
    checked = 0
    while fallback_keys and checked < pass_limit:
        if cancelled is not None and cancelled():
            return current_client, False, None
        key = fallback_keys[0].strip()
        if not key:
            fallback_keys.pop(0)
            continue
        checked += 1
        try:
            new_client = create_gemini_client(key)
            new_client.models.get(model=model_name)
            if cancelled is not None and cancelled():
                return current_client, False, None
            fallback_keys.pop(0)

            log.info(
                "Chiave di fallback valida, rotazione completata.",
                extra={"stage": "key_rotation"},
            )
            print(f"   [OK] Chiave di riserva valida! ({len(fallback_keys)} rimanenti)")
            return new_client, True, key
        except Exception as err:
            error = _error_text(err)
            error_code = _error_code(err)
            safe_err = redact_secrets(err)
            if _is_transient_key_probe_failure(error, error_code, err):
                fallback_keys.append(fallback_keys.pop(0))
                log.warning(
                    "Validazione chiave di fallback temporaneamente non riuscita.",
                    extra={"stage": "key_rotation"},
                )
                print(
                    "   [!] Validazione temporanea fallita per chiave di riserva: "
                    f"{safe_err}"
                )
                continue
            fallback_keys.pop(0)
            if _is_invalid_key_probe_failure(
                error, error_code
            ) or _is_daily_or_key_exhausted(error, error_code):
                log.warning(
                    "Chiave di fallback non utilizzabile.",
                    extra={"stage": "key_rotation"},
                )
                print(f"   [!] Chiave di riserva non utilizzabile: {safe_err}")
            else:
                log.warning(
                    "Chiave di fallback non valida.", extra={"stage": "key_rotation"}
                )
                print(f"   [!] Chiave di riserva non valida: {safe_err}")
    return current_client, False, None


def wait_for_file_ready(
    client_for_file,
    file_obj,
    cancelled: Callable[[], bool],
    max_wait_seconds: int = _FILE_UPLOAD_TIMEOUT_SECONDS,
    poll_seconds: int = _FILE_UPLOAD_POLL_SECONDS,
):
    start_time = time.monotonic()
    while True:
        state = str(getattr(file_obj, "state", "")).upper()
        if "ACTIVE" not in state and "FAILED" not in state:
            if time.monotonic() - start_time > max_wait_seconds:
                raise TimeoutError(
                    "Timeout durante l'elaborazione del file audio sui server Google."
                )
            if not sleep_with_cancel(cancelled, poll_seconds):
                return None
            file_obj = client_for_file.files.get(name=file_obj.name)
            continue
        if "FAILED" in state:
            raise RuntimeError(f"Caricamento fallito (state={state}).")
        return file_obj


def upload_audio_path(client_for_upload, path_str: str):
    try:
        return client_for_upload.files.upload(path=path_str)
    except TypeError:
        return client_for_upload.files.upload(file=path_str)


def make_inline_audio_part(path_str: str, max_bytes: int | None = None):
    try:
        if max_bytes is not None:
            try:
                size = int(os.path.getsize(path_str))
                if size > int(max_bytes):
                    return None
            except Exception:
                pass
        with open(path_str, "rb") as handle:
            data = handle.read()
        return types.Part.from_bytes(data=data, mime_type="audio/mpeg")
    except Exception:
        return None


def request_new_api_key(
    runtime,
    cancelled: Callable[[], bool],
    *,
    timeout_seconds: float | None = _NEW_API_KEY_TIMEOUT_SECONDS,
    on_timeout: Callable[[], None] | None = None,
):
    print("   [In attesa di una nuova chiave API dall'utente nel popup...]")
    event = threading.Event()
    result = {"new_key": None}
    deadline = (
        time.monotonic() + float(timeout_seconds)
        if timeout_seconds is not None and float(timeout_seconds) >= 0
        else None
    )

    def handler(response):
        result["new_key"] = response.get("key", None)
        event.set()

    if not runtime.ask_new_api_key(handler):
        print("ERRORE: Funzione webview non trovata per il popup.")
        return None

    while not event.is_set():
        if cancelled():
            return None
        wait_seconds = 0.2
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                try:
                    runtime.dismiss_new_api_key_prompt()
                except Exception:
                    pass
                if on_timeout is not None:
                    on_timeout()
                print("   [!] Attesa nuova API Key scaduta.")
                return None
            wait_seconds = min(wait_seconds, remaining)
        event.wait(wait_seconds)
    return result["new_key"]


def _switch_to_next_model(
    model_state: ModelState,
    *,
    on_model_switched,
    error_message: str,
    cause: Exception,
    exc_type: type[Exception] = RuntimeError,
) -> None:
    next_model = next_model_in_chain(model_state)
    if next_model:
        old_model = model_state.current
        model_state.current = next_model
        print(f"      [Fallback modello] {old_model} -> {next_model}")
        if on_model_switched is not None:
            on_model_switched(old_model, next_model)
        return
    tried = ", ".join(model_state.chain)
    raise exc_type(
        f"{error_message} Ho provato tutti i fallback configurati: {tried}."
    ) from cause


def _phase1_temperature(model_name: str) -> float:
    for opt in MODEL_OPTIONS:
        if opt["id"] == model_name:
            return float(opt.get("phase1_temperature", 0.35))
    return 0.35


def _retry_on_model_unavailable(
    callable_fn,
    client,
    model_state: ModelState | None,
    current_model: str,
    cancelled,
    runtime,
    restore_phase,
    model_unavailable_retry_delays: tuple[float, ...],
    on_model_switched,
    governor: AdaptiveGovernor | None = None,
) -> tuple[bool, Any, Any, Exception | None]:
    """Execute circuit breaker retry loop for transient 503 / capacity errors without switching model.

    Returns (switched=False, client, result, last_exc).
    """
    gov = governor or _GLOBAL_GOVERNOR
    total_retries = len(model_unavailable_retry_delays)
    gov.max_attempts = total_retries + 1
    for retry_idx, base_wait in enumerate(model_unavailable_retry_delays, start=1):
        wait = gov.on_503(
            base_delay=base_wait,
            max_delay=60.0,
            model=current_model,
            attempt=retry_idx + 1,
        )
        usage_service.record_retry_event("503")
        print(
            f"      [Modello {current_model} temporaneamente occupato (503)."
            f" Riprovo tra {int(wait)}s... (tentativo {retry_idx + 1}/{total_retries + 1})]"
        )
        if runtime is not None:
            runtime.phase(
                f"Server Gemini occupato — riprovo tra {int(wait)}s (tentativo {retry_idx + 1}/{total_retries + 1})"
            )
            if hasattr(runtime, "retry_state"):
                runtime.retry_state(gov.get_state_payload())
        if not sleep_with_cancel(cancelled, wait):
            print("   [*] Operazione annullata dall'utente.")
            return False, client, None, None
        restore_phase()
        gov.state = "probing"
        if runtime is not None and hasattr(runtime, "retry_state"):
            runtime.retry_state(gov.get_state_payload())
        try:
            _record_attempt_usage(client, current_model, model_state)
            result = callable_fn(client)
            gov.on_success()
            _record_success_usage(client, current_model, model_state)
            if runtime is not None and hasattr(runtime, "retry_state"):
                runtime.retry_state(gov.get_state_payload())
            return False, client, result, None
        except Exception as retry_exc:
            if cancelled():
                print("   [*] Operazione annullata dall'utente.")
                return False, client, None, None
            retry_error = _error_text(retry_exc)
            retry_code = _error_code(retry_exc)
            if _is_model_unavailable(
                retry_error, retry_code
            ) or _is_transient_capacity_or_server_error(
                retry_error, retry_code, retry_exc
            ):
                if retry_idx == total_retries:
                    gov.state = "exhausted"
                    return False, client, None, retry_exc
            else:
                return False, client, None, retry_exc
    return False, client, None, None


def _retry_on_quota(
    exc: Exception,
    *,
    client,
    fallback_keys: list,
    current_model: str,
    model_state: ModelState | None,
    cancelled,
    runtime,
    request_fallback_key,
    on_key_rotated,
    on_model_switched,
    attempts: int,
    max_attempts: int,
    rate_limit_sleep_seconds: float,
    error: str,
    error_code: int | None,
    log,
    restore_phase,
    governor: AdaptiveGovernor | None = None,
) -> tuple[bool, Any]:
    """Handle minute rate limits (single probe), daily quota exhaustion, and key rotation."""
    gov = governor or _GLOBAL_GOVERNOR
    kind_429 = classify_429_error(exc)
    retry_after = extract_retry_after_seconds(exc)
    is_exhausted_key = (kind_429 == "quota_exceeded") or _is_daily_or_key_exhausted(
        error, error_code
    )
    is_minute_rate_limit = (kind_429 == "rate_limit_exceeded") or (
        _is_minute_scoped_rate_limit(error, error_code) and not is_exhausted_key
    )

    if (
        (is_minute_rate_limit or kind_429 in ("rate_limit_exceeded", "unknown_429"))
        and not is_exhausted_key
        and gov.consecutive_429 == 0
        and attempts < max_attempts - 1
    ):
        sleep_dur = gov.on_429(
            retry_after=retry_after,
            default_delay=rate_limit_sleep_seconds,
            model=current_model,
        )
        display_dur = int(sleep_dur)
        phase_msg = f"⏳ Rate limit: attesa {display_dur}s prima della sonda..."

        usage_service.mark_rate_limited(
            current_model, sleep_dur if sleep_dur > 0 else 65.0
        )
        usage_service.record_retry_event("429")
        print(
            f"      [Rilevato rate limit ({kind_429}). Attesa di {display_dur}s per il reset quota...]"
        )
        if runtime is not None:
            runtime.phase(phase_msg)
            if hasattr(runtime, "retry_state"):
                runtime.retry_state(gov.get_state_payload())
        if not sleep_with_cancel(cancelled, sleep_dur):
            print("   [*] Operazione annullata dall'utente.")
            return False, client
        restore_phase()
        gov.state = "probing"
        if runtime is not None and hasattr(runtime, "retry_state"):
            runtime.retry_state(gov.get_state_payload())

        return True, client
    if (
        is_minute_rate_limit or kind_429 in ("rate_limit_exceeded", "unknown_429")
    ) and not is_exhausted_key:
        old_key = extract_client_api_key(client) or ""
        usage_service.record_request_failure(
            old_key, current_model, reason="rate_limit_exceeded", is_final=True
        )
        gov.state = "exhausted"
        if runtime is not None and hasattr(runtime, "retry_state"):
            runtime.retry_state(gov.get_state_payload())
        raise CircuitBreakerExhaustedError(
            f"Rate limit persistente per il modello {current_model}.",
            cause_error=error,
            model=current_model,
            attempts=attempts + 1,
            recommended_retry_after_seconds=1800.0,
        ) from exc

    print("\n[!!] CHIAVE API ESAURITA O QUOTA GIORNALIERA RAGGIUNTA!")

    old_key = extract_client_api_key(client) or ""
    if is_exhausted_key or kind_429 == "quota_exceeded":
        usage_service.mark_quota_exhausted(current_model, api_key=old_key)
        usage_service.record_request_failure(
            old_key, current_model, reason="quota_exceeded", is_final=True
        )
    if cancelled():
        print("   [*] Operazione annullata dall'utente.")
        return False, client

    # another key with requests left for this model, or the next model with any key
    routed = select_route(
        client,
        model_state,
        on_model_switched=on_model_switched,
        on_key_rotated=on_key_rotated,
        runtime=runtime,
    )
    if routed is not client or (
        model_state is not None and model_state.current != current_model
    ):
        return True, routed

    new_c, rotated, rotated_key = try_rotate_key(
        client,
        fallback_keys,
        current_model,
        logger=log,
        cancelled=cancelled,
    )
    if rotated:
        client = new_c
        if runtime is not None and hasattr(runtime, "set_effective_api_key"):
            runtime.set_effective_api_key(rotated_key)
        if on_key_rotated is not None:
            on_key_rotated(client)
        return True, client

    if cancelled():
        print("   [*] Operazione annullata dall'utente.")
        return False, client

    # Explicit user-driven key replacement on quota exhaustion if fallback keys are exhausted.
    new_api_key = request_fallback_key() if request_fallback_key else None
    if new_api_key and new_api_key.strip():
        try:
            test_c = create_gemini_client(new_api_key.strip())
            test_c.models.get(model=current_model)
            if cancelled():
                print("   [*] Operazione annullata dall'utente.")
                return False, client
            client = test_c
            if runtime is not None and hasattr(runtime, "set_effective_api_key"):
                runtime.set_effective_api_key(new_api_key.strip())
            if on_key_rotated is not None:
                on_key_rotated(client)
            print("   [OK] Nuova API Key valida! Ripresa confermata dall'utente...")
            return True, client
        except Exception as err:
            print(f"   [!] Chiave non valida fornita: {redact_secrets(err)}")

    raise QuotaDailyLimitError(str(exc)) from exc


def _record_attempt_usage(
    client, model_name: str, model_state: ModelState | None
) -> None:
    cur_key = extract_client_api_key(client) or ""
    try:
        usage_service.record_request_attempt(
            cur_key, current_model_name(model_state, model_name)
        )
    except Exception:
        pass


def _record_success_usage(
    client, model_name: str, model_state: ModelState | None
) -> None:
    cur_key = extract_client_api_key(client) or ""
    try:
        usage_service.record_request_success(
            cur_key, current_model_name(model_state, model_name)
        )
    except Exception:
        pass


def _handle_credential_error_recording(
    exc: Exception, cur_key: str, current_model: str, error_code: int | None
) -> str:
    cred_status = classify_credential_status(exc)
    if cred_status in ("invalid", "permission_denied", "request_error"):
        usage_service.mark_credential_status(
            cur_key,
            cred_status,
            error_msg=str(exc),
            code=error_code,
        )
        usage_service.record_request_failure(
            cur_key, current_model, reason=cred_status, is_final=True
        )
    return cred_status


def _handle_model_error(
    exc: Exception,
    error: str,
    error_code: int | None,
    current_model: str,
    model_state: ModelState | None,
    on_model_switched: Any,
) -> bool:
    if model_state is None:
        return False
    if isinstance(exc, DegenerateOutputError):
        _rejected_len = len(getattr(exc, "rejected_text", ""))
        print(
            f'      [Output degenerato] model={current_model} reason="{exc}" ({_rejected_len} chars) - provo fallback...'
        )
        _switch_to_next_model(
            model_state,
            on_model_switched=on_model_switched,
            error_message="Tutti i modelli della chain hanno prodotto output degenerato o non valido.",
            cause=exc,
            exc_type=DegenerateOutputError,
        )
        return True
    if _is_model_not_found(error, error_code):
        print(
            f"      [Modello {current_model} non supportato o non trovato. Provo il fallback successivo...]"
        )
        _switch_to_next_model(
            model_state,
            on_model_switched=on_model_switched,
            error_message="Modello Gemini non supportato o non trovato.",
            cause=exc,
        )
        return True
    return False


def _handle_offline_network(
    cancelled,
    runtime,
    restore_phase,
) -> bool:
    """Returns True to continue main retry loop, False if cancelled."""
    usage_service.record_retry_event("network")
    print(
        "      [Connessione assente: impossibile raggiungere i server Google. In attesa di rete (controllo ogni 10s)...]"
    )
    if runtime is not None:
        runtime.phase(
            "Connessione assente — verifica rete in corso (riprovo ogni 10s)..."
        )
    while not network_service.is_network_online():
        if not sleep_with_cancel(cancelled, 10.0):
            print("   [*] Operazione annullata dall'utente.")
            return False
    restore_phase()
    return True


def _check_deterministic_client_error(
    exc: Exception,
    error: str,
    error_code: int | None,
    cred_status: str,
    cur_key: str,
    current_model: str,
    is_quota_related: bool,
) -> None:
    if (
        isinstance(exc, PermanentError)
        or cred_status in ("invalid", "permission_denied", "request_error")
        or (_is_deterministic_client_error(error, error_code) and not is_quota_related)
    ):
        usage_service.record_request_failure(
            cur_key,
            current_model,
            reason=cred_status or "client_error",
            is_final=True,
        )
        raise exc


class _SwitchedModel(Exception):
    """Internal signal: the current model stayed overloaded, the next one in the chain is now active."""


def _handle_transient_capacity(
    callable_fn,
    client,
    model_state,
    current_model: str,
    cancelled,
    runtime,
    restore_phase,
    delays: tuple[float, ...],
    on_model_switched,
    gov: AdaptiveGovernor,
    cur_key: str,
    exc: Exception,
    error: str,
) -> tuple[bool, Any, Any, Exception | None]:
    """Execute model unavailable retry loop.

    Returns (done, client, result, other_exc).
    """
    _switched, client, result, other_exc = _retry_on_model_unavailable(
        callable_fn,
        client,
        model_state,
        current_model,
        cancelled,
        runtime,
        restore_phase,
        delays,
        on_model_switched,
        governor=gov,
    )
    if result is not None or other_exc is None:
        return True, client, result, None

    if other_exc is not None:
        other_err = _error_text(other_exc)
        other_c = _error_code(other_exc)
        if not (
            _is_model_unavailable(other_err, other_c)
            or _is_transient_capacity_or_server_error(other_err, other_c, other_exc)
        ):
            return False, client, None, other_exc

    actual_max_attempts = len(delays) + 1
    # the model is still overloaded after every retry: move to the next model of the
    # chain (the fallbacks chosen in the settings) instead of failing the lesson
    if model_state is not None and next_model_in_chain(model_state):
        print(
            f"      [Modello {current_model} ancora sovraccarico dopo {actual_max_attempts} tentativi."
            " Passo al modello di riserva...]"
        )
        _switch_to_next_model(
            model_state,
            on_model_switched=on_model_switched,
            error_message="Server Gemini indisponibile.",
            cause=other_exc or exc,
        )
        gov.on_success()  # the new model starts with a clean slate
        return False, client, None, _SwitchedModel(current_model)
    gov.state = "exhausted"
    if runtime is not None and hasattr(runtime, "retry_state"):
        runtime.retry_state(gov.get_state_payload())
    usage_service.record_request_failure(
        cur_key, current_model, reason="circuit_breaker_exhausted", is_final=True
    )
    raise CircuitBreakerExhaustedError(
        f"Server Gemini temporaneamente indisponibile dopo {actual_max_attempts} tentativi ({current_model}).",
        cause_error=error,
        model=current_model,
        attempts=actual_max_attempts,
        recommended_retry_after_seconds=1800.0,
    ) from (other_exc or exc)


def _process_transient_capacity_fallback(
    other_exc: Exception,
    cur_key: str,
    current_model: str,
    model_state: ModelState | None,
    on_model_switched,
) -> tuple[bool, Exception, str, int | None, bool]:
    """Returns (model_switched, exc, error, error_code, is_quota_related)."""
    if isinstance(other_exc, _SwitchedModel):  # already moved to the next model
        return True, other_exc, "", None, False
    error = _error_text(other_exc)
    error_code = _error_code(other_exc)
    is_quota_related = _is_quota_related(error, error_code)
    cred_status = _handle_credential_error_recording(
        other_exc, cur_key, current_model, error_code
    )
    if _handle_model_error(
        other_exc,
        error,
        error_code,
        current_model,
        model_state,
        on_model_switched,
    ):
        return True, other_exc, error, error_code, is_quota_related
    _check_deterministic_client_error(
        other_exc,
        error,
        error_code,
        cred_status,
        cur_key,
        current_model,
        is_quota_related,
    )
    return False, other_exc, error, error_code, is_quota_related


def _handle_generic_transient_retry(
    exc: Exception,
    cur_key: str,
    current_model: str,
    attempts: int,
    max_attempts: int,
    retry_sleep_seconds: float,
    cancelled,
) -> bool:
    """Returns True if sleep succeeded and should continue retry loop, False if cancelled.

    Raises original exception if max_attempts exceeded.
    """
    if attempts >= max_attempts:
        usage_service.record_request_failure(
            cur_key,
            current_model,
            reason="max_attempts_exceeded",
            is_final=True,
        )
        raise exc

    usage_service.record_retry_event("other")
    print(
        f"      [Errore: {redact_secrets(exc)}. Riprovo in {int(retry_sleep_seconds)}s...]"
    )
    if not sleep_with_cancel(cancelled, retry_sleep_seconds):
        print("   [*] Operazione annullata dall'utente.")
        return False
    return True


def retry_with_quota(
    callable_fn,
    *,
    client,
    fallback_keys: list,
    model_name: str,
    model_state: ModelState | None = None,
    cancelled,
    runtime,
    request_fallback_key,
    max_attempts: int = _MAX_RETRY_ATTEMPTS,
    retry_sleep_seconds: float = _RETRY_SLEEP_SECONDS,
    model_unavailable_retry_delays: tuple[float, ...] = _MODEL_UNAVAILABLE_RETRY_DELAYS,
    rate_limit_sleep_seconds: float = _RATE_LIMIT_SLEEP_SECONDS,
    on_key_rotated=None,
    on_model_switched=None,
    logger=None,
    resume_phase_text: str | None = None,
    governor: AdaptiveGovernor | None = None,
):
    """Execute callable_fn(client) with adaptive circuit breaker backoff and shared cooldown.

    Returns (new_client, result) where result is the return value of callable_fn(client).
    Raises QuotaDailyLimitError if daily quota is exhausted.
    Raises CircuitBreakerExhaustedError when automatic retry budget (4 attempts) is exhausted.
    Raises original exception for non-retryable client errors.
    """
    log = logger or get_logger("jot.generation")
    gov = governor or _GLOBAL_GOVERNOR

    def _restore_phase() -> None:
        if runtime is not None and resume_phase_text:
            runtime.phase(resume_phase_text)

    attempts = 0
    while attempts < max_attempts:
        if not _ready_to_send(cancelled, gov, runtime):
            return client, None
        # best model not on hold, with a key that still has requests for it
        client = select_route(
            client,
            model_state,
            on_model_switched=on_model_switched,
            on_key_rotated=on_key_rotated,
            runtime=runtime,
        )

        current_model = current_model_name(model_state, model_name)
        cur_key = extract_client_api_key(client) or ""

        try:
            _record_attempt_usage(client, current_model, model_state)
            result = callable_fn(client)
            gov.on_success()
            _record_success_usage(client, current_model, model_state)
            if runtime is not None and hasattr(runtime, "retry_state"):
                runtime.retry_state(gov.get_state_payload())
            return client, result
        except Exception as exc:
            if cancelled():
                print("   [*] Operazione annullata dall'utente.")
                return client, None
            error = _error_text(exc)
            error_code = _error_code(exc)
            is_quota_related = _is_quota_related(error, error_code)

            cred_status = _handle_credential_error_recording(
                exc, cur_key, current_model, error_code
            )

            # 1. Deterministic model issues (404 Not Found, Degenerate runaway text)
            if _handle_model_error(
                exc,
                error,
                error_code,
                current_model,
                model_state,
                on_model_switched,
            ):
                attempts = 0
                continue

            # 2. Deterministic client errors (400, 401, 403, PermanentError) -> Fail immediately
            _check_deterministic_client_error(
                exc,
                error,
                error_code,
                cred_status,
                cur_key,
                current_model,
                is_quota_related,
            )

            # 3. Offline network -> Poll connectivity without consuming API attempt budget
            if network_service.is_network_offline_error(exc):
                if not _handle_offline_network(cancelled, runtime, _restore_phase):
                    return client, None
                continue

            # 4. Transient capacity & server errors (503, 500, 502, 504, 408, Timeout)
            is_capacity = not is_quota_related and (
                _is_model_unavailable(error, error_code)
                or _is_transient_capacity_or_server_error(error, error_code, exc)
            )
            # first overload on a model: no retries on it, the next model takes over at once
            moved = _move_off_overloaded_model(
                client,
                model_state,
                current_model,
                on_model_switched=on_model_switched,
                on_key_rotated=on_key_rotated,
                runtime=runtime,
                applies=is_capacity,
            )
            if moved is not None:
                client = moved
                attempts = 0
                continue
            if is_capacity:
                done, client, result, other_exc = _handle_transient_capacity(
                    callable_fn,
                    client,
                    model_state,
                    current_model,
                    cancelled,
                    runtime,
                    _restore_phase,
                    model_unavailable_retry_delays,
                    on_model_switched,
                    gov,
                    cur_key,
                    exc,
                    error,
                )
                if done:
                    return client, result
                if other_exc is not None:
                    switched, exc, error, error_code, is_quota_related = (
                        _process_transient_capacity_fallback(
                            other_exc,
                            cur_key,
                            current_model,
                            model_state,
                            on_model_switched,
                        )
                    )
                    if switched:
                        attempts = 0
                        continue

            # 5. 429 Quota & Rate Limit handling
            if is_quota_related:
                should_retry, client = _retry_on_quota(
                    exc,
                    client=client,
                    fallback_keys=fallback_keys,
                    current_model=current_model,
                    model_state=model_state,
                    cancelled=cancelled,
                    runtime=runtime,
                    request_fallback_key=request_fallback_key,
                    on_key_rotated=on_key_rotated,
                    on_model_switched=on_model_switched,
                    attempts=attempts,
                    max_attempts=max_attempts,
                    rate_limit_sleep_seconds=rate_limit_sleep_seconds,
                    error=error,
                    error_code=error_code,
                    log=log,
                    restore_phase=_restore_phase,
                    governor=gov,
                )
                if should_retry:
                    if _is_daily_or_key_exhausted(error, error_code):
                        attempts = 0
                    else:
                        attempts += 1
                    continue
                return client, None

            # 6. Generic transient error retry
            attempts += 1
            if not _handle_generic_transient_retry(
                exc,
                cur_key,
                current_model,
                attempts,
                max_attempts,
                retry_sleep_seconds,
                cancelled,
            ):
                return client, None
    return client, None


def extract_response_text(response) -> str:
    raw = getattr(response, "text", None)
    if raw is None:
        text = ""
    elif isinstance(raw, str):
        text = raw.strip()
    else:
        text = str(raw).strip()

    if text:
        return text

    try:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            merged = "\n".join(
                [str(getattr(part, "text", "") or "") for part in parts]
            ).strip()
            if merged:
                return merged
    except Exception:
        pass
    return ""


def build_chunk_prompt(previous_tail: str) -> str:
    prompt = (
        "Trascrivi TUTTO il contenuto di questo blocco audio seguendo rigorosamente le istruzioni di sistema. "
        "Non omettere nessun concetto, esempio, cifra o termine tecnico. "
        "Non riassumere: la lunghezza dell'output deve essere proporzionale a quella dell'audio. "
        "Ogni paragrafo generato deve essere unico: non ripetere mai lo stesso paragrafo o frase."
    )
    if previous_tail:
        prompt += (
            "\n\nATTENZIONE: Stai continuando una stesura. Questo è l'ultimo paragrafo che hai generato nel blocco precedente:\n"
            f'"...{previous_tail}"\n\n'
            "Riprendi il discorso da qui IN MODO FLUIDO. Usa la stessa grandezza per i titoli. "
            "Se all'inizio di questo blocco c'è sovrapposizione, NON ripetere testualmente le frasi già dette, "
            "ma se compare anche solo un dettaglio nuovo includilo."
        )
    return prompt
