"""
Shared Python-side types for the PyWebView bridge.

Keeping these payload shapes in one place makes the backend/frontend contract
clearer and reduces silent drift when the React app evolves.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


class BridgeFileItem(TypedDict):
    id: str
    path: str
    name: str
    size: NotRequired[int]
    duration: NotRequired[float]
    resume_session: NotRequired[bool | None]
    allow_completed_destroy: NotRequired[bool]
    force_retry: NotRequired[bool]
    # "Slide e appunti" mode: path is the slides file (PDF/PPTX)
    kind: NotRequired[Literal["audio", "notes"]]
    book_path: NotRequired[str | None]
    book_pages: NotRequired[str]
    slides_per_chunk: NotRequired[int]
    book_mode: NotRequired[Literal["auto", "full"]]
    # Audio lesson: optional slides shown in class, title and course
    slides_path: NotRequired[str | None]
    title: NotRequired[str | None]
    course: NotRequired[str | None]
    # Further recordings of the same lesson (merged after `path`)
    audio_parts: NotRequired[list[str]]
    # YYYY-MM-DD, shown in the heading of the sintesi
    lesson_date: NotRequired[str | None]


class RetryStatePayload(TypedDict, total=False):
    state: Literal["idle", "cooling_down", "probing", "exhausted", "paused"]
    reason: str
    model: str
    attempt: int
    max_attempts: int
    next_retry_at: str | None
    seconds_remaining: float | None


class LowDiskWarningPayload(TypedDict):
    needed_bytes: int
    free_bytes: int
    location: str
    kind: str
    file_name: NotRequired[str]


class ProcessDonePayload(TypedDict, total=False):
    cancelled: bool
    completed: int
    completed_with_warnings: int
    failed: int
    paused: NotRequired[int]
    total: int
    quota_exhausted: NotRequired[bool]


class SetCurrentFilePayload(TypedDict):
    index: int
    id: str
    total: int


class FileDonePayload(TypedDict):
    index: int
    id: str
    output_html: str
    output_dir: str
    effective_model: str
    completion_status: NotRequired[Literal["completed", "completed_with_warnings"]]
    revision_failed_blocks: NotRequired[list[int]]
    primary_model: NotRequired[str]


class FileFailedPayload(TypedDict):
    index: int
    id: str
    error: str
    error_detail: NotRequired[str]
    retryable: NotRequired[bool]
    retry_reason: NotRequired[str]
    recommended_retry_at: NotRequired[str]


class WorkTotalsPayload(TypedDict, total=False):
    chunks: int | None
    macro: int | None


class WorkDonePayload(TypedDict, total=False):
    kind: Literal["chunks", "macro"]
    done: int
    total: int | None


class ValidationCheck(TypedDict):
    id: str
    label: str
    status: Literal["ok", "warning", "error"]
    message: str
    details: NotRequired[str]


class ValidationResult(TypedDict):
    ok: bool
    summary: str
    checks: list[ValidationCheck]
    has_warnings: NotRequired[bool]


class UpdateDownloadProgressPayload(TypedDict):
    status: Literal["downloading", "verifying", "installing", "done", "error"]
    bytes_done: int
    bytes_total: int
    error: NotRequired[str]


class ApiUsageModelLimit(TypedDict, total=False):
    model_name: str
    rpd_limit: int | None
    rpm_limit: int | None
    tpm_limit: int | None
    source: Literal["configured", "user_observed", "ai_studio_snapshot", "unknown"]
    quota_state: Literal["normal", "rpd_exhausted", "rate_limited", "unknown"]
    updated_at: str | None


class ApiUsageTelemetry(TypedDict, total=False):
    requests_sent: int
    responses_succeeded: int
    final_failures: int
    retries_total: int
    retries_by_type: dict[str, int]
    last_request_iso: str | None


class ApiUsageWorkStats(TypedDict, total=False):
    chunks_completed: int
    revisions_completed: int
    sbobine_completed: int


class ApiUsageCredentialProfile(TypedDict, total=False):
    id: str
    masked_key: str
    label: str
    is_primary: bool
    operational_status: Literal[
        "unused",
        "active",
        "temporarily_failing",
        "invalid",
        "permission_denied",
        "request_error",
    ]
    key_type: Literal["authorization_key", "standard_legacy", "unknown"]
    project_id: str | None
    last_error_code: int | None
    last_error_message: str | None
    last_error_iso: str | None
    last_used_iso: str | None


class ApiUsageResultPayload(TypedDict, total=False):
    schema_version: int
    quota_date: str
    primary_status: Literal[
        "operational",
        "rate_limited",
        "quota_exhausted",
        "credential_error",
        "degraded",
        "unknown",
    ]
    status_message: str
    retry_after_seconds: float | None
    next_reset_info: str
    project_limits: dict[str, ApiUsageModelLimit]
    work_stats: ApiUsageWorkStats
    telemetry: ApiUsageTelemetry
    credentials: list[ApiUsageCredentialProfile]
    is_degraded_mode: bool
    degraded_reason: str | None
    keys: list[dict[str, Any]]
    total_requests_remaining: int | None
    estimated_sbobine_remaining: int
