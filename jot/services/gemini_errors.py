"""
Gemini API error inspection, classification, and output guardrails for jot.

Isolates error string extraction, HTTP status parsing, rate limit / quota detection,
and runaway degenerate output verification.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Literal


class QuotaDailyLimitError(Exception):
    """Raised when daily quota is exhausted and no replacement key was provided."""


class PermanentError(Exception):
    """Raised for non-retryable failures (e.g. HTTP 400 / INVALID_ARGUMENT)."""


class DegenerateOutputError(RuntimeError):
    """Raised when a model returns repetitive/runaway text that must be discarded."""

    def __init__(self, reason: str, rejected_text: str = "") -> None:
        super().__init__(reason)
        self.rejected_text: str = (rejected_text or "")[:500]


class AllModelsUnavailableError(RuntimeError):
    """Raised when all models in the fallback chain are 503-unavailable."""


class CircuitBreakerExhaustedError(RuntimeError):
    """Raised when the adaptive circuit breaker retry budget is exhausted and the batch is suspended."""

    def __init__(
        self,
        message: str = "Circuit breaker budget exhausted.",
        *,
        cause_error: str = "",
        model: str = "",
        attempts: int = 4,
        recommended_retry_after_seconds: float = 1800.0,
    ) -> None:
        super().__init__(message)
        self.cause_error = cause_error
        self.model = model
        self.attempts = attempts
        self.recommended_retry_after_seconds = recommended_retry_after_seconds


def _error_text(exc: Exception) -> str:
    """Flatten structured SDK errors into a searchable lowercase string."""
    parts: list[str] = []
    for attr in ("message", "status"):
        value = getattr(exc, attr, None)
        if value:
            parts.append(str(value))
    details = getattr(exc, "details", None)
    if details:
        try:
            parts.append(json.dumps(details, ensure_ascii=False, sort_keys=True))
        except TypeError:
            parts.append(str(details))
    response = getattr(exc, "response", None)
    if response is not None:
        for attr in ("text", "reason_phrase", "reason"):
            value = getattr(response, attr, None)
            if value:
                parts.append(str(value))
    parts.append(str(exc))
    return " ".join(part for part in parts if part).lower()


def _error_code(exc: Exception) -> int | None:
    raw_candidates = [
        getattr(exc, "code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
        getattr(getattr(exc, "response", None), "status", None),
    ]
    for raw in raw_candidates:
        try:
            if raw is None or raw == "":
                continue
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _is_daily_or_key_exhausted(error_text: str, error_code: int | None) -> bool:
    norm_text = _normalize_guardrail_text(error_text)

    # Minute only markers to avoid false positives on daily exhaustion
    minute_only_markers = (
        "per minute",
        "per-minute",
        "per_minute",
        "requests_per_minute",
        "requests per minute",
        "requestsperminute",
        "tokens_per_minute",
        "tokens per minute",
        "tokensperminute",
        "tpm",
        "rpm",
        "generatecontenttokenspermodelperminute",
        "generatecontentrequestspermodelperminute",
    )
    daily_explicit_markers = (
        "per day",
        "per-day",
        "per_day",
        "perday",
        "daily",
        "generaterequestsperday",
        "generate_content_free_tier_requests",
        "requests_per_day",
        "requests per day",
        "exceeded your current quota",
    )

    if any(m in norm_text for m in minute_only_markers) and not any(
        d in norm_text for d in daily_explicit_markers
    ):
        return False

    # 1. Google Gemini specific daily / account quota exhaustion markers
    hard_limit_markers = (
        "per day",
        "per-day",
        "per_day",
        "perday",
        "daily",
        "generaterequestsperday",
        "generate_content_free_tier_requests",
        "generatecontentfreetierrequests",
        "requests_per_day",
        "requests per day",
        "requestsperday",
        "exceeded your current quota",
        "check your plan and billing",
        "plan and billing",
        "insufficient_quota",
        "insufficient quota",
        "insufficient_balance",
        "insufficient balance",
        "billing",
        "credit",
        "balance",
    )
    if any(marker in norm_text for marker in hard_limit_markers):
        return True

    # 2. General token exhaustion markers
    token_markers = ("token", "tokens")
    token_exhaustion_markers = (
        "exhaust",
        "exceeded",
        "finished",
        "ended",
        "insufficient",
        "unavailable",
        "depleted",
    )
    if any(marker in norm_text for marker in token_markers) and any(
        marker in norm_text for marker in token_exhaustion_markers
    ):
        return True

    # 3. Some Gemini quota failures are surfaced as plain HTTP 503 / UNAVAILABLE with resource_exhausted
    if error_code == 503 and "resource_exhausted" in norm_text:
        return True

    return False


def _is_minute_scoped_rate_limit(
    error_text: str, error_code: int | None = None
) -> bool:
    norm_text = _normalize_guardrail_text(error_text)
    if _is_daily_or_key_exhausted(norm_text, error_code):
        return False
    markers = (
        "per minute",
        "per-minute",
        "per_minute",
        "rate limit exceeded",
        "rate_limit_exceeded",
        "requests_per_minute",
        "requests per minute",
        "requestsperminute",
        "tokens_per_minute",
        "tokens per minute",
        "tokensperminute",
        "tpm",
        "rpm",
        "generatecontenttokenspermodelperminute",
        "generatecontentrequestspermodelperminute",
        "retry-after",
        "retry after",
    )
    return any(marker in norm_text for marker in markers)


def _is_model_unavailable(error_text: str, error_code: int | None) -> bool:
    if error_code != 503:
        return False
    markers = (
        "service unavailable",
        "backend error",
        "model is overloaded",
        "overloaded",
        "temporarily unavailable",
    )
    return any(marker in error_text for marker in markers)


def _is_quota_related(error_text: str, error_code: int | None) -> bool:
    return (
        error_code == 429
        or "resource_exhausted" in error_text
        or "quota" in error_text
        or "rate limit" in error_text
        or "too many requests" in error_text
    )


def _is_model_not_found(error_text: str, error_code: int | None) -> bool:
    if error_code != 404:
        return False
    markers = (
        "not_found",
        "not found",
        "not supported for generatecontent",
        "unsupported for generatecontent",
        "models/",
    )
    return any(marker in error_text for marker in markers)


def _is_invalid_key_probe_failure(error_text: str, error_code: int | None) -> bool:
    if error_code in (401, 403):
        return True
    markers = (
        "api key not valid",
        "api_key_invalid",
        "invalid api key",
        "invalid_api_key",
        "malformed api key",
        "unauthenticated",
        "permission_denied",
        "permission denied",
        "forbidden",
        "access denied",
        "does not have permission",
        "not authorized",
        "unauthorized",
    )
    return any(marker in error_text for marker in markers)


def _is_transient_key_probe_failure(
    error_text: str, error_code: int | None, exc: Exception
) -> bool:
    if isinstance(exc, TimeoutError | ConnectionError):
        return True
    if error_code in (408, 429, 500, 502, 503, 504):
        if _is_daily_or_key_exhausted(error_text, error_code):
            return False
        return True
    markers = (
        "timeout",
        "timed out",
        "connection",
        "network",
        "temporary",
        "temporarily",
        "service unavailable",
        "backend error",
        "overloaded",
        "try again",
        "retry-after",
        "retry after",
        "rate limit",
        "too many requests",
        "per minute",
        "per-minute",
        "rpm",
    )
    if any(marker in error_text for marker in markers):
        return not _is_daily_or_key_exhausted(error_text, error_code)
    return False


def classify_429_error(
    exc: Exception,
) -> Literal["rate_limit_exceeded", "quota_exceeded", "unknown_429"]:
    """Classifies a 429 / RESOURCE_EXHAUSTED error into RPM rate limit, RPD daily quota, or unknown."""
    err_text = _error_text(exc)
    err_code = _error_code(exc)

    if _is_daily_or_key_exhausted(err_text, err_code):
        return "quota_exceeded"
    if _is_minute_scoped_rate_limit(err_text, err_code):
        return "rate_limit_exceeded"
    return "unknown_429"


def classify_credential_status(
    exc: Exception,
) -> Literal[
    "invalid", "permission_denied", "request_error", "temporarily_failing", "unknown"
]:
    """Maps API exceptions to operational credential status."""
    err_code = _error_code(exc)
    err_text = _error_text(exc)

    if err_code == 401 or any(
        m in err_text
        for m in (
            "api key not valid",
            "api_key_invalid",
            "invalid api key",
            "invalid_api_key",
            "malformed api key",
            "unauthenticated",
            "not authorized",
            "unauthorized",
        )
    ):
        return "invalid"
    if err_code == 403 or any(
        m in err_text
        for m in (
            "permission_denied",
            "permission denied",
            "forbidden",
            "access denied",
            "does not have permission",
        )
    ):
        return "permission_denied"
    if err_code == 400 or any(
        m in err_text
        for m in (
            "invalid_argument",
            "bad request",
            "request_error",
        )
    ):
        return "request_error"
    if (
        err_code in (408, 429, 500, 502, 503, 504)
        or isinstance(exc, (TimeoutError, ConnectionError))
        or any(
            m in err_text
            for m in (
                "timeout",
                "timed out",
                "service unavailable",
                "backend error",
                "overloaded",
                "temporarily unavailable",
            )
        )
    ):
        return "temporarily_failing"
    return "unknown"


def extract_retry_after_seconds(exc: Exception) -> float | None:
    """Attempts to extract retry-after duration in seconds from response headers or message text."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None)
    if headers is not None:
        raw_val = None
        if hasattr(headers, "get"):
            raw_val = headers.get("retry-after") or headers.get("Retry-After")
        elif isinstance(headers, (list, tuple)):
            for k, v in headers:
                if str(k).lower() == "retry-after":
                    raw_val = v
                    break
        if raw_val is not None:
            try:
                return max(0.0, float(raw_val))
            except (ValueError, TypeError):
                try:
                    from datetime import UTC, datetime
                    from email.utils import parsedate_to_datetime

                    dt = parsedate_to_datetime(str(raw_val))
                    if dt:
                        now = datetime.now(UTC)
                        if dt.tzinfo is None:
                            diff = (
                                dt - datetime.now(UTC).replace(tzinfo=None)
                            ).total_seconds()
                        else:
                            diff = (dt - now).total_seconds()
                        return max(0.0, float(diff))
                except Exception:
                    pass

    text = _error_text(exc)
    patterns = [
        r"retry[\s_-]?after[:\s]+([0-9]+(?:\.[0-9]+)?)s?",
        r"retry in ([0-9]+(?:\.[0-9]+)?)s?",
        r"wait ([0-9]+(?:\.[0-9]+)?)s?",
        r"reset in ([0-9]+(?:\.[0-9]+)?)s?",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:seconds?|s)\s*(?:before retry|to reset)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            try:
                return max(0.0, float(m.group(1)))
            except (ValueError, TypeError):
                pass
    return None


def _is_transient_capacity_or_server_error(
    error_text: str, error_code: int | None, exc: Exception | None = None
) -> bool:
    """Returns True if error is 503, 408, 500, 502, 504, or network timeout/overload."""
    if exc is not None and isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if error_code in (408, 500, 502, 503, 504):
        return True
    markers = (
        "service unavailable",
        "backend error",
        "model is overloaded",
        "overloaded",
        "temporarily unavailable",
        "internal server error",
        "bad gateway",
        "gateway timeout",
        "request timeout",
        "timed out",
        "timeout",
        "deadline exceeded",
    )
    return any(marker in error_text for marker in markers)


def _is_deterministic_client_error(error_text: str, error_code: int | None) -> bool:
    """Returns True if error is 400, 401, 403, invalid argument, permission denied, etc."""
    if error_code in (400, 401, 403):
        return True
    markers = (
        "invalid_argument",
        "bad request",
        "unauthenticated",
        "permission_denied",
        "permission denied",
        "api key not valid",
        "api_key_invalid",
        "invalid api key",
        "forbidden",
        "access denied",
    )
    return any(marker in error_text for marker in markers)


def _normalize_guardrail_text(text: str) -> str:
    normalized = str(text or "").replace("\u00a0", " ").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*([,.;:!?])\s*", r"\1", normalized)
    return normalized


def detect_degenerate_output(text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    paragraphs = [
        segment.strip()
        for segment in re.split(r"\n\s*\n+", raw)
        if segment and segment.strip()
    ]
    if not paragraphs:
        return None

    if any(len(paragraph) > 12000 for paragraph in paragraphs):
        longest = max(len(paragraph) for paragraph in paragraphs)
        return f"paragrafo troppo lungo ({longest} caratteri)"

    normalized_paragraphs = [
        _normalize_guardrail_text(paragraph) for paragraph in paragraphs
    ]
    paragraph_candidates = [
        paragraph for paragraph in normalized_paragraphs if len(paragraph) >= 80
    ]
    if paragraph_candidates:
        paragraph_counts = Counter(paragraph_candidates)
        repeated_paragraph = max(paragraph_counts.values(), default=0)
        if repeated_paragraph >= 4:
            return f"paragrafo ripetuto {repeated_paragraph} volte"
        duplicate_paragraphs = sum(
            count - 1 for count in paragraph_counts.values() if count > 1
        )
        if (
            duplicate_paragraphs >= 8
            and duplicate_paragraphs / max(1, len(paragraph_candidates)) >= 0.20
        ):
            return f"troppi paragrafi duplicati ({duplicate_paragraphs} duplicati)"

    sentence_candidates: list[str] = []
    for paragraph in paragraphs:
        parts = re.split(r"(?<=[.!?])\s+|\n+", paragraph)
        for sentence in parts:
            normalized = _normalize_guardrail_text(sentence)
            if len(normalized) >= 40:
                sentence_candidates.append(normalized)
    if sentence_candidates:
        sentence_counts = Counter(sentence_candidates)
        repeated_sentence = max(sentence_counts.values(), default=0)
        if repeated_sentence >= 8:
            return f"frase ripetuta {repeated_sentence} volte"

    if len(raw) > 120000 and len(paragraphs) <= 5:
        return f"output eccessivo e poco segmentato ({len(raw)} caratteri)"

    return None
