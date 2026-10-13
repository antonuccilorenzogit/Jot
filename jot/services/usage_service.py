"""
Service for tracking and persisting Google Gemini API project quotas, network telemetry,
credential operational statuses, and completed application work in jot.

Key architectural invariants:
- Quota is tracked at the Google Cloud Project and Model level (not multiplied per API key).
- Telemetry records every API attempt, success, final failure, and retry breakdown orchestrated
  by the application layer.
- Credentials track operational status (active, invalid, permission_denied, temporarily_failing, etc.)
  along with best-effort metadata (project_id, key_type).
- State-first primary status (operational, rate_limited, quota_exhausted, credential_error).
- ACID safety via sentinel file lock (api_usage.json.lock) + temp file + os.replace().
- Schema v2 with automatic in-place migration from legacy v1 files.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo

from jot.core.model_registry import SUPPORTED_MODELS
from jot.services.config_service import get_config_dir

# ---------------------------------------------------------------------------
# Constants & Model Limits (Google AI Studio Free Tier Official Limits)
# ---------------------------------------------------------------------------

try:
    PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
    PACIFIC_TZ_OK = True
except Exception:
    # without tzdata (Windows) jot.utils.pacific_time applies the US daylight-saving rule
    PACIFIC_TZ = timezone(timedelta(hours=-7))
    PACIFIC_TZ_OK = False

SCHEMA_VERSION: int = 2

DEFAULT_FLASH_RPD: int = 20
DEFAULT_FLASH_RPM: int = 5
DEFAULT_FLASH_TPM: int = 250000

DEFAULT_FLASH_LITE_RPD: int = 500
DEFAULT_FLASH_LITE_RPM: int = 15
DEFAULT_FLASH_LITE_TPM: int = 1000000

MODEL_RPD_LIMITS: dict[str, int] = {
    "gemini-2.5-flash": 20,
    "gemini-3.6-flash": 20,
    "gemini-3.8-flash": 20,
    "gemini-3.7-flash": 20,
    "gemini-3.5-flash": 20,
}

MODEL_RPM_LIMITS: dict[str, int] = {
    "gemini-2.5-flash": 5,
    "gemini-3.6-flash": 5,
    "gemini-3.8-flash": 5,
    "gemini-3.7-flash": 5,
    "gemini-3.5-flash": 5,
}

AVG_CHUNKS_PER_SBOBINA: int = 12
AVG_REVISIONS_PER_SBOBINA: int = 7
COST_PER_SBOBINA: int = AVG_CHUNKS_PER_SBOBINA + AVG_REVISIONS_PER_SBOBINA  # ~19 per 3h


_USAGE_THREAD_LOCK = threading.RLock()
_USAGE_FILE_NAME = "api_usage.json"
_LOCK_FILE_NAME = "api_usage.json.lock"

# Cached authoritative server time offset in seconds (Google Server Date - Local Date)
_SERVER_TIME_OFFSET_SECONDS: float = 0.0
_HAS_SERVER_TIME: bool = False

# Ephemeral runtime retry-after state
_RUNTIME_RETRY_AFTER_EXPIRY_UTC: datetime | None = None
_RUNTIME_RETRY_AFTER_SECONDS: float | None = None


# ---------------------------------------------------------------------------
# Types (Schema v2)
# ---------------------------------------------------------------------------


class ProjectModelLimit(TypedDict):
    model_name: str
    rpd_limit: int | None
    rpm_limit: int | None
    tpm_limit: int | None
    source: Literal["configured", "user_observed", "ai_studio_snapshot", "unknown"]
    quota_state: Literal["normal", "rpd_exhausted", "rate_limited", "unknown"]
    updated_at: str | None


class TelemetryStats(TypedDict):
    requests_sent: int
    responses_succeeded: int
    final_failures: int
    retries_total: int
    retries_by_type: dict[str, int]
    last_request_iso: str | None


class WorkStats(TypedDict):
    chunks_completed: int
    revisions_completed: int
    sbobine_completed: int


class CredentialProfile(TypedDict):
    id: str
    masked_key: str
    is_primary: bool
    label: str
    operational_status: Literal[
        "unused",
        "active",
        "temporarily_failing",
        "permission_denied",
        "invalid",
        "request_error",
    ]
    key_type: Literal["authorization_key", "standard_legacy", "unknown"]
    project_id: str | None
    last_error_code: int | None
    last_error_message: str | None
    last_error_iso: str | None
    last_used_iso: str | None
    exhausted_models: list[str]


class ApiUsageResultPayload(TypedDict):
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
    project_limits: dict[str, ProjectModelLimit]
    work_stats: WorkStats
    telemetry: TelemetryStats
    credentials: list[CredentialProfile]
    is_degraded_mode: bool
    degraded_reason: str | None
    # Backwards compatibility fields for older UI / bridge callers
    keys: list[dict[str, Any]]
    total_requests_remaining: int | None
    estimated_sbobine_remaining: int


# ---------------------------------------------------------------------------
# Cross-Platform Sentinel File Locking
# ---------------------------------------------------------------------------


def _get_usage_file_path() -> str:
    return os.path.join(get_config_dir(), _USAGE_FILE_NAME)


def _get_lock_file_path() -> str:
    return os.path.join(get_config_dir(), _LOCK_FILE_NAME)


@contextmanager
def _interprocess_lock():
    """Acquires a process-exclusive lock on the sentinel file (api_usage.json.lock).

    Crucial: Locking the sentinel file leaves api_usage.json unlocked so that
    atomic replacement via os.replace() works reliably without PermissionError
    on Windows.
    """
    lock_path = _get_lock_file_path()
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)

    with _USAGE_THREAD_LOCK:
        lock_file = open(lock_path, "a+b")
        try:
            if platform.system() == "Windows":
                import msvcrt

                file_fd = lock_file.fileno()
                locked = False
                for _ in range(50):
                    try:
                        lock_file.seek(0)
                        msvcrt.locking(file_fd, msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError:
                        import time

                        time.sleep(0.02)
                if not locked:
                    try:
                        msvcrt.locking(file_fd, msvcrt.LK_LOCK, 1)
                        locked = True
                    except Exception:
                        pass
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            yield
        finally:
            try:
                if platform.system() == "Windows":
                    import msvcrt

                    try:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                else:
                    import fcntl

                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                try:
                    lock_file.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Time & Reset Helpers
# ---------------------------------------------------------------------------


def update_authoritative_server_time(http_date_str: str | None) -> None:
    """Updates the reference time offset from Google HTTP response 'Date' header."""
    global _SERVER_TIME_OFFSET_SECONDS, _HAS_SERVER_TIME
    if not http_date_str:
        return
    try:
        from email.utils import parsedate_to_datetime

        server_dt = parsedate_to_datetime(http_date_str)
        if server_dt:
            local_now = datetime.now(UTC)
            _SERVER_TIME_OFFSET_SECONDS = (server_dt - local_now).total_seconds()
            _HAS_SERVER_TIME = True
    except Exception:
        pass


def get_current_authoritative_utc() -> datetime:
    """Returns the current UTC time adjusted by authoritative Google server offset."""
    local_utc = datetime.now(UTC)
    if _HAS_SERVER_TIME:
        from datetime import timedelta

        return local_utc + timedelta(seconds=_SERVER_TIME_OFFSET_SECONDS)
    return local_utc


def get_pacific_date_string(dt_utc: datetime | None = None) -> str:
    """Returns YYYY-MM-DD in Google's America/Los_Angeles timezone (midnight reset = 09:00 CEST)."""
    from jot.utils.pacific_time import to_pacific

    utc = dt_utc or get_current_authoritative_utc()
    if PACIFIC_TZ_OK:
        return utc.astimezone(PACIFIC_TZ).strftime("%Y-%m-%d")
    return to_pacific(utc).strftime("%Y-%m-%d")


def get_limit_for_model(model_name: str) -> int:
    cleaned = str(model_name or "").strip()
    if cleaned in MODEL_RPD_LIMITS:
        return MODEL_RPD_LIMITS[cleaned]
    if "lite" in cleaned.lower():
        return DEFAULT_FLASH_LITE_RPD
    return DEFAULT_FLASH_RPD


def get_rpm_limit_for_model(model_name: str) -> int:
    cleaned = str(model_name or "").strip()
    if cleaned in MODEL_RPM_LIMITS:
        return MODEL_RPM_LIMITS[cleaned]
    if "lite" in cleaned.lower():
        return DEFAULT_FLASH_LITE_RPM
    return DEFAULT_FLASH_RPM


def hash_key(api_key: str) -> str:
    cleaned = str(api_key or "").strip()
    if not cleaned:
        return "anonymous"
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def mask_key(api_key: str) -> str:
    cleaned = str(api_key or "").strip()
    if not cleaned:
        return "Chiave assente"
    if len(cleaned) <= 8:
        return f"{cleaned[:2]}...{cleaned[-2:]}"
    return f"{cleaned[:6]}...{cleaned[-4:]}"


# ---------------------------------------------------------------------------
# Storage, Schema v2 Defaults & Migration
# ---------------------------------------------------------------------------


def _empty_telemetry_dict() -> dict[str, Any]:
    return {
        "requests_sent": 0,
        "responses_succeeded": 0,
        "final_failures": 0,
        "retries_total": 0,
        "retries_by_type": {
            "503": 0,
            "429": 0,
            "5xx": 0,
            "timeout": 0,
            "network": 0,
            "other": 0,
        },
        "last_request_iso": None,
    }


def _empty_work_stats_dict() -> dict[str, Any]:
    return {
        "chunks_completed": 0,
        "revisions_completed": 0,
        "sbobine_completed": 0,
    }


def _create_model_limit_entry(model_name: str) -> dict[str, Any]:
    cleaned = str(model_name or "gemini-2.5-flash").strip()
    rpd = get_limit_for_model(cleaned)
    rpm = get_rpm_limit_for_model(cleaned)
    tpm = DEFAULT_FLASH_LITE_TPM if "lite" in cleaned.lower() else DEFAULT_FLASH_TPM
    return {
        "model_name": cleaned,
        "rpd_limit": rpd,
        "rpm_limit": rpm,
        "tpm_limit": tpm,
        "source": "configured",
        "quota_state": "normal",
        "updated_at": get_current_authoritative_utc().isoformat(),
    }


def _create_credential_entry(
    api_key: str, is_primary: bool = True, label: str = "Chiave API"
) -> dict[str, Any]:
    key_id = hash_key(api_key)
    return {
        "id": key_id,
        "masked_key": mask_key(api_key),
        "is_primary": is_primary,
        "label": label,
        "operational_status": "unused",
        "key_type": "unknown",
        "project_id": None,
        "last_error_code": None,
        "last_error_message": None,
        "last_error_iso": None,
        "last_used_iso": None,
        "exhausted_models": [],
    }


def _create_empty_v2_storage() -> dict[str, Any]:
    limits = {m: _create_model_limit_entry(m) for m in SUPPORTED_MODELS}
    return {
        "schema_version": SCHEMA_VERSION,
        "quota_date": get_pacific_date_string(),
        "project_limits": limits,
        "telemetry": _empty_telemetry_dict(),
        "work_stats": _empty_work_stats_dict(),
        "credentials": {},
    }


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Migrates a v1 usage structure to schema v2, preserving credentials while cleaning legacy counters."""
    migrated = _create_empty_v2_storage()
    migrated["quota_date"] = data.get("quota_date", get_pacific_date_string())

    old_keys = data.get("keys", {})
    if isinstance(old_keys, dict):
        for k_id, old_profile in old_keys.items():
            if isinstance(old_profile, dict):
                masked = str(old_profile.get("masked_key", ""))
                is_prim = bool(old_profile.get("is_primary", False))
                # Check if this key had any activity
                had_usage = False
                for _m, q in old_profile.get("models", {}).items():
                    if isinstance(q, dict) and int(q.get("used_today", 0)) > 0:
                        had_usage = True
                        break

                cred = {
                    "id": k_id,
                    "masked_key": masked or k_id,
                    "is_primary": is_prim,
                    "label": "Chiave Principale" if is_prim else "Chiave Riserva",
                    "operational_status": "active" if had_usage else "unused",
                    "key_type": "unknown",
                    "project_id": None,
                    "last_error_code": None,
                    "last_error_message": None,
                    "last_error_iso": None,
                    "last_used_iso": None,
                    "exhausted_models": [],
                }
                migrated["credentials"][k_id] = cred

    return migrated


def _load_raw_usage_unlocked() -> dict[str, Any]:
    path = _get_usage_file_path()
    if not os.path.exists(path):
        return _create_empty_v2_storage()
    data = None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _create_empty_v2_storage()

    if isinstance(data, dict):
        # Detect v1 schema and perform safe migration
        if data.get("schema_version") != SCHEMA_VERSION:
            migrated = _migrate_v1_to_v2(data)
            _save_raw_usage_unlocked(migrated)
            return migrated

        # Validate required v2 sections & sanitize project limits against SUPPORTED_MODELS
        raw_limits = data.get("project_limits")
        existing_limits: dict[str, Any] = (
            raw_limits if isinstance(raw_limits, dict) else {}
        )
        cleaned_limits: dict[str, Any] = {}
        for m in SUPPORTED_MODELS:
            entry = existing_limits.get(m)
            if isinstance(entry, dict):
                cleaned_limits[m] = entry
            else:
                cleaned_limits[m] = _create_model_limit_entry(m)
        data["project_limits"] = cleaned_limits

        if "telemetry" not in data or not isinstance(data["telemetry"], dict):
            data["telemetry"] = _empty_telemetry_dict()
        if "work_stats" not in data or not isinstance(data["work_stats"], dict):
            data["work_stats"] = _empty_work_stats_dict()
        if "credentials" not in data or not isinstance(data["credentials"], dict):
            data["credentials"] = {}
        return data

    return _create_empty_v2_storage()


def _save_raw_usage_unlocked(data: dict[str, Any]) -> None:
    path = _get_usage_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    temp_fd, temp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix="api_usage_", suffix=".tmp"
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        raise


def _check_and_reset_unlocked(data: dict[str, Any]) -> bool:
    """Synchronizes daily quotas with Pacific Time midnight reset (09:00 CEST)."""
    current_pacific_date = get_pacific_date_string()
    saved_date = data.get("quota_date", "")
    changed = False

    if saved_date != current_pacific_date:
        data["quota_date"] = current_pacific_date

        # Reset daily work stats and telemetry for the new day
        data["work_stats"] = _empty_work_stats_dict()
        data["telemetry"] = _empty_telemetry_dict()

        # Reset model quota states from rpd_exhausted back to normal
        for _m_name, model_limit in data.get("project_limits", {}).items():
            if model_limit.get("quota_state") in ("rpd_exhausted", "rate_limited"):
                model_limit["quota_state"] = "normal"
                model_limit["updated_at"] = get_current_authoritative_utc().isoformat()
                changed = True

        # Reset transiently failing credentials back to active/unused and clear exhausted_models
        for _k_id, cred in data.get("credentials", {}).items():
            cred["exhausted_models"] = []
            if cred.get("operational_status") == "temporarily_failing":
                cred["operational_status"] = (
                    "active" if cred.get("last_used_iso") else "unused"
                )
                cred["last_error_code"] = None
                cred["last_error_message"] = None
                changed = True

        # Clean legacy keys dictionary if present
        if "keys" in data and isinstance(data["keys"], dict):
            for _k_id, k_entry in data["keys"].items():
                if isinstance(k_entry, dict) and "models" in k_entry:
                    for _m, m_entry in k_entry.get("models", {}).items():
                        if isinstance(m_entry, dict):
                            m_entry["used_today"] = 0
                            m_entry["is_exhausted"] = False

        changed = True

    return changed


def _get_or_create_credential_unlocked(
    data: dict[str, Any],
    api_key: str,
    is_primary: bool = True,
    label: str | None = None,
) -> dict[str, Any]:
    key_id = hash_key(api_key)
    creds = data.setdefault("credentials", {})
    if key_id not in creds:
        default_label = label or (
            "Chiave Principale" if is_primary else "Chiave Riserva"
        )
        creds[key_id] = _create_credential_entry(
            api_key, is_primary=is_primary, label=default_label
        )
    profile = creds[key_id]
    profile["is_primary"] = is_primary
    profile["masked_key"] = mask_key(api_key)
    if label:
        profile["label"] = label
    if "exhausted_models" not in profile or not isinstance(
        profile["exhausted_models"], list
    ):
        profile["exhausted_models"] = []
    return profile


def _get_or_create_project_limit_unlocked(
    data: dict[str, Any], model_name: str
) -> dict[str, Any]:
    cleaned = str(model_name or "gemini-2.5-flash").strip()
    limits = data.setdefault("project_limits", {})
    if cleaned not in limits:
        limits[cleaned] = _create_model_limit_entry(cleaned)
    return limits[cleaned]


# ---------------------------------------------------------------------------
# Public Telemetry & Work API
# ---------------------------------------------------------------------------


def record_request_attempt(api_key: str, model_name: str) -> None:
    """Records an API request attempt emitted by generation_service."""
    cleaned_key = str(api_key or "").strip()
    cleaned_model = str(model_name or "gemini-2.5-flash").strip()
    now_iso = get_current_authoritative_utc().isoformat()

    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        _check_and_reset_unlocked(data)

        # Update telemetry
        telem = data.setdefault("telemetry", _empty_telemetry_dict())
        telem["requests_sent"] = int(telem.get("requests_sent", 0)) + 1
        telem["last_request_iso"] = now_iso

        # Update credential status
        if cleaned_key:
            cred = _get_or_create_credential_unlocked(data, cleaned_key)
            if cred.get("operational_status") in ("unused", "temporarily_failing"):
                cred["operational_status"] = "active"
            cred["last_used_iso"] = now_iso

        _get_or_create_project_limit_unlocked(data, cleaned_model)
        _save_raw_usage_unlocked(data)


def record_request_success(api_key: str, model_name: str) -> None:
    """Records a successful response returned normally by the Google GenAI SDK."""
    cleaned_key = str(api_key or "").strip()
    cleaned_model = str(model_name or "gemini-2.5-flash").strip()
    now_iso = get_current_authoritative_utc().isoformat()

    global _RUNTIME_RETRY_AFTER_EXPIRY_UTC, _RUNTIME_RETRY_AFTER_SECONDS
    _RUNTIME_RETRY_AFTER_EXPIRY_UTC = None
    _RUNTIME_RETRY_AFTER_SECONDS = None

    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        _check_and_reset_unlocked(data)

        telem = data.setdefault("telemetry", _empty_telemetry_dict())
        telem["responses_succeeded"] = int(telem.get("responses_succeeded", 0)) + 1

        if cleaned_key:
            cred = _get_or_create_credential_unlocked(data, cleaned_key)
            cred["operational_status"] = "active"
            cred["last_used_iso"] = now_iso
            exhausted = cred.setdefault("exhausted_models", [])
            if cleaned_model in exhausted:
                exhausted.remove(cleaned_model)

        model_limit = _get_or_create_project_limit_unlocked(data, cleaned_model)
        if model_limit.get("quota_state") in ("rate_limited", "rpd_exhausted"):
            model_limit["quota_state"] = "normal"
            model_limit["updated_at"] = now_iso

        _save_raw_usage_unlocked(data)


def record_request_failure(
    api_key: str, model_name: str, reason: str = "other", is_final: bool = True
) -> None:
    """Records a request failure. If is_final is True, increments final_failures count."""
    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        _check_and_reset_unlocked(data)

        telem = data.setdefault("telemetry", _empty_telemetry_dict())
        if is_final:
            telem["final_failures"] = int(telem.get("final_failures", 0)) + 1

        _save_raw_usage_unlocked(data)


def record_retry_event(error_type: str = "503") -> None:
    """Records a retry attempt categorized by error type (503, 429, 5xx, timeout, network, other)."""
    cleaned_type = str(error_type or "other").strip()
    if cleaned_type not in ("503", "429", "5xx", "timeout", "network", "other"):
        cleaned_type = "other"

    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        _check_and_reset_unlocked(data)

        telem = data.setdefault("telemetry", _empty_telemetry_dict())
        telem["retries_total"] = int(telem.get("retries_total", 0)) + 1
        retries_by_type = telem.setdefault(
            "retries_by_type",
            {"503": 0, "429": 0, "5xx": 0, "timeout": 0, "network": 0, "other": 0},
        )
        retries_by_type[cleaned_type] = int(retries_by_type.get(cleaned_type, 0)) + 1

        _save_raw_usage_unlocked(data)


def record_work_completed(
    kind: Literal["chunks", "macro", "sbobine", "revisions"], count: int = 1
) -> None:
    """Records completed application work (chunks, macro revisions, full sbobine)."""
    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        _check_and_reset_unlocked(data)

        work = data.setdefault("work_stats", _empty_work_stats_dict())
        if kind in ("chunks", "chunk"):
            work["chunks_completed"] = int(work.get("chunks_completed", 0)) + count
        elif kind in ("macro", "revisions", "revision"):
            work["revisions_completed"] = (
                int(work.get("revisions_completed", 0)) + count
            )
        elif kind in ("sbobine", "sbobina"):
            work["sbobine_completed"] = int(work.get("sbobine_completed", 0)) + count

        _save_raw_usage_unlocked(data)


def mark_quota_exhausted(model_name: str, api_key: str | None = None) -> None:
    """Marks daily quota (RPD) as exhausted for a specific model and optionally key."""
    cleaned_model = str(model_name or "gemini-2.5-flash").strip()
    cleaned_key = str(api_key or "").strip()
    now_iso = get_current_authoritative_utc().isoformat()

    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        _check_and_reset_unlocked(data)

        if cleaned_key:
            cred = _get_or_create_credential_unlocked(data, cleaned_key)
            exhausted = cred.setdefault("exhausted_models", [])
            if cleaned_model not in exhausted:
                exhausted.append(cleaned_model)
            cred["operational_status"] = "temporarily_failing"
            cred["last_error_code"] = 429
            cred["last_error_message"] = (
                f"Quota giornaliera (RPD) esaurita per {cleaned_model}"
            )
            cred["last_error_iso"] = now_iso
        else:
            # Mark all existing credentials as having exhausted this model
            for _k, cred in data.get("credentials", {}).items():
                exhausted = cred.setdefault("exhausted_models", [])
                if cleaned_model not in exhausted:
                    exhausted.append(cleaned_model)

        limit = _get_or_create_project_limit_unlocked(data, cleaned_model)
        limit["quota_state"] = "rpd_exhausted"
        limit["updated_at"] = now_iso

        _save_raw_usage_unlocked(data)


def mark_rate_limited(
    model_name: str, retry_after_seconds: float | None = None
) -> None:
    """Marks project as rate-limited (RPM/TPM) and sets temporary retry-after window."""
    cleaned_model = str(model_name or "gemini-2.5-flash").strip()
    now_iso = get_current_authoritative_utc().isoformat()

    global _RUNTIME_RETRY_AFTER_EXPIRY_UTC, _RUNTIME_RETRY_AFTER_SECONDS
    if retry_after_seconds and retry_after_seconds > 0:
        _RUNTIME_RETRY_AFTER_SECONDS = float(retry_after_seconds)
        _RUNTIME_RETRY_AFTER_EXPIRY_UTC = datetime.now(UTC) + timedelta(
            seconds=float(retry_after_seconds)
        )

    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        _check_and_reset_unlocked(data)

        limit = _get_or_create_project_limit_unlocked(data, cleaned_model)
        if limit.get("quota_state") != "rpd_exhausted":
            limit["quota_state"] = "rate_limited"
            limit["updated_at"] = now_iso

        _save_raw_usage_unlocked(data)


def mark_credential_status(
    api_key: str,
    status: Literal[
        "unused",
        "active",
        "temporarily_failing",
        "permission_denied",
        "invalid",
        "request_error",
    ],
    error_msg: str | None = None,
    code: int | None = None,
    key_type: Literal["authorization_key", "standard_legacy", "unknown"] | None = None,
    project_id: str | None = None,
) -> None:
    """Updates operational status and last error info for a specific credential."""
    cleaned_key = str(api_key or "").strip()
    if not cleaned_key:
        return
    now_iso = get_current_authoritative_utc().isoformat()

    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        _check_and_reset_unlocked(data)

        cred = _get_or_create_credential_unlocked(data, cleaned_key)
        cred["operational_status"] = status
        if error_msg or code:
            cred["last_error_code"] = code
            cred["last_error_message"] = (error_msg or "")[:200]
            cred["last_error_iso"] = now_iso
        if key_type:
            cred["key_type"] = key_type
        if project_id:
            cred["project_id"] = project_id

        _save_raw_usage_unlocked(data)


# ---------------------------------------------------------------------------
# Aggregated State / Bridge Query
# ---------------------------------------------------------------------------


def _build_ordered_project_limits(
    data: dict[str, Any], credentials_list: list[dict[str, Any]]
) -> dict[str, ProjectModelLimit]:
    ordered_project_limits: dict[str, ProjectModelLimit] = {}
    primary_cred = next((c for c in credentials_list if c.get("is_primary")), None)
    primary_exhausted = (
        set(primary_cred.get("exhausted_models", [])) if primary_cred else set()
    )
    fb_creds = [
        c
        for c in credentials_list
        if not c.get("is_primary")
        and c.get("operational_status") not in ("invalid", "permission_denied")
    ]

    for m_name in SUPPORTED_MODELS:
        raw_lim = data.get("project_limits", {}).get(
            m_name, _create_model_limit_entry(m_name)
        )
        model_lim = dict(raw_lim)

        has_available_fb = any(
            m_name not in c.get("exhausted_models", []) for c in fb_creds
        )

        if m_name in primary_exhausted:
            if has_available_fb:
                model_lim["quota_state"] = "normal"
            else:
                model_lim["quota_state"] = "rpd_exhausted"
        elif any(m_name in c.get("exhausted_models", []) for c in fb_creds):
            if model_lim.get("quota_state") != "rate_limited":
                model_lim["quota_state"] = "normal"

        ordered_project_limits[m_name] = model_lim  # type: ignore

    return ordered_project_limits


def _determine_primary_status(
    credentials_list: list[dict[str, Any]],
    ordered_project_limits: dict[str, ProjectModelLimit],
    clean_primary_model: str,
    remaining_retry_after: float | None,
) -> tuple[
    Literal[
        "operational",
        "rate_limited",
        "quota_exhausted",
        "credential_error",
        "degraded",
        "unknown",
    ],
    str,
    bool,
    str | None,
]:
    primary_model_limit = ordered_project_limits.get(
        clean_primary_model, _create_model_limit_entry(clean_primary_model)
    )
    quota_state = primary_model_limit.get("quota_state", "normal")

    has_perm_denied = any(
        c.get("operational_status") == "permission_denied" for c in credentials_list
    )
    has_invalid = any(
        c.get("operational_status") == "invalid" for c in credentials_list
    )
    has_active = any(
        c.get("operational_status") in ("active", "unused") for c in credentials_list
    )

    if not credentials_list:
        return "unknown", "Nessuna chiave API configurata.", False, None
    if has_invalid and not has_active:
        return (
            "credential_error",
            "Chiave API non valida (HTTP 401). Verifica le impostazioni.",
            False,
            None,
        )
    if has_perm_denied and not has_active:
        return (
            "credential_error",
            "Permessi insufficienti sul progetto Google (HTTP 403).",
            False,
            None,
        )

    primary_cred = next((c for c in credentials_list if c.get("is_primary")), None)
    is_primary_exhausted = (
        primary_cred is not None
        and clean_primary_model in primary_cred.get("exhausted_models", [])
    )
    fb_creds = [c for c in credentials_list if not c.get("is_primary")]
    has_fb_key_for_primary_model = any(
        c.get("operational_status") not in ("invalid", "permission_denied")
        and clean_primary_model not in c.get("exhausted_models", [])
        for c in fb_creds
    )

    if is_primary_exhausted or quota_state == "rpd_exhausted":
        if has_fb_key_for_primary_model:
            return (
                "degraded",
                "Modalità riserva: elaborazione su chiave di riserva.",
                True,
                "Chiave principale esaurita per oggi. Il lavoro prosegue automaticamente sulla chiave di riserva.",
            )
        return (
            "quota_exhausted",
            "Quota giornaliera (RPD) esaurita. Reset alle ore 09:00 (ora italiana / 00:00 PT).",
            False,
            None,
        )
    if quota_state == "rate_limited" or remaining_retry_after is not None:
        if remaining_retry_after and remaining_retry_after > 0:
            msg = f"In attesa per rate limit temporaneo. Ripresa tra {remaining_retry_after:.0f}s."
        else:
            msg = "In attesa per rate limit temporaneo (RPM/TPM)."
        return "rate_limited", msg, False, None

    return "operational", "API Google Gemini operative.", False, None


def _probe_primary_credential(
    clean_primary: str, clean_primary_model: str
) -> tuple[str | None, int | None, str | None]:
    """Probe key validity via Google Gemini API outside the interprocess lock."""
    if not clean_primary:
        return None, None, None
    try:
        from google import genai

        probe_client = genai.Client(api_key=clean_primary)
        probe_client.models.get(model=clean_primary_model)
        return "active", None, None
    except Exception as exc:
        from jot.services.gemini_errors import (
            _error_code,
            _error_text,
            classify_credential_status,
        )

        status = classify_credential_status(exc)
        if status in ("invalid", "permission_denied"):
            return status, _error_code(exc), _error_text(exc)[:200]
        return None, None, None


def _handle_force_refresh_unlocked(
    data: dict[str, Any],
    clean_primary: str,
    probe_result: tuple[str | None, int | None, str | None] | None = None,
) -> bool:
    """Resets transient rate limits and applies probe results without wiping daily quota exhaustion."""
    changed = False
    for _m_name, model_limit in data.get("project_limits", {}).items():
        if model_limit.get("quota_state") == "rate_limited":
            model_limit["quota_state"] = "normal"
            model_limit["updated_at"] = get_current_authoritative_utc().isoformat()
            changed = True

    for _k_id, cred in data.get("credentials", {}).items():
        # Only clear temporarily_failing if it wasn't an exhausted model failure
        if cred.get("operational_status") == "temporarily_failing" and not cred.get(
            "exhausted_models"
        ):
            cred["operational_status"] = (
                "active" if cred.get("last_used_iso") else "unused"
            )
            cred["last_error_code"] = None
            cred["last_error_message"] = None
            changed = True

    if clean_primary and probe_result is not None:
        status, code, message = probe_result
        if status:
            primary_id = hash_key(clean_primary)
            if primary_id in data.get("credentials", {}):
                p_cred = data["credentials"][primary_id]
                if status == "active" and p_cred.get("operational_status") in (
                    "invalid",
                    "permission_denied",
                ):
                    p_cred["operational_status"] = (
                        "active" if p_cred.get("last_used_iso") else "unused"
                    )
                    p_cred["last_error_code"] = None
                    p_cred["last_error_message"] = None
                    changed = True
                elif status in ("invalid", "permission_denied"):
                    p_cred["operational_status"] = status
                    p_cred["last_error_code"] = code
                    p_cred["last_error_message"] = message
                    changed = True
    return changed


def get_daily_usage(
    primary_key: str | None = None,
    fallback_keys: list[str] | None = None,
    primary_model: str = "gemini-2.5-flash",
    fallback_models: list[str] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Retrieves aggregated state, primary status, project limits, telemetry, and credentials."""
    all_keys: list[tuple[str, bool, str]] = []
    seen_keys: set[str] = set()

    clean_primary = str(primary_key or "").strip()
    if clean_primary:
        all_keys.append((clean_primary, True, "Chiave Principale"))
        seen_keys.add(clean_primary)

    for idx, fk in enumerate(fallback_keys or []):
        clean_fk = str(fk or "").strip()
        if clean_fk and clean_fk not in seen_keys:
            seen_keys.add(clean_fk)
            all_keys.append((clean_fk, False, f"Chiave Riserva {idx + 1}"))

    clean_primary_model = str(primary_model or "gemini-2.5-flash").strip()
    relevant_models: list[str] = [clean_primary_model]
    for fm in fallback_models or []:
        cfm = str(fm or "").strip()
        if cfm and cfm not in relevant_models:
            relevant_models.append(cfm)

    probe_result = (
        _probe_primary_credential(clean_primary, clean_primary_model)
        if force_refresh
        else None
    )

    with _interprocess_lock():
        data = _load_raw_usage_unlocked()
        changed = _check_and_reset_unlocked(data)

        if force_refresh:
            if _handle_force_refresh_unlocked(data, clean_primary, probe_result):
                changed = True

        if changed:
            _save_raw_usage_unlocked(data)

        # Ensure project limits exist for all supported models
        for m_name in SUPPORTED_MODELS:
            _get_or_create_project_limit_unlocked(data, m_name)

        # Ensure credentials exist in storage
        credentials_list: list[dict[str, Any]] = []
        for key_str, is_primary, label in all_keys:
            cred = _get_or_create_credential_unlocked(
                data, key_str, is_primary=is_primary, label=label
            )
            credentials_list.append(cred)

        # Evaluate retry_after remaining seconds
        global _RUNTIME_RETRY_AFTER_EXPIRY_UTC, _RUNTIME_RETRY_AFTER_SECONDS
        remaining_retry_after: float | None = None
        if _RUNTIME_RETRY_AFTER_EXPIRY_UTC is not None:
            now_utc = datetime.now(UTC)
            diff = (_RUNTIME_RETRY_AFTER_EXPIRY_UTC - now_utc).total_seconds()
            if diff > 0:
                remaining_retry_after = round(diff, 1)
            else:
                _RUNTIME_RETRY_AFTER_EXPIRY_UTC = None
                _RUNTIME_RETRY_AFTER_SECONDS = None

        ordered_project_limits = _build_ordered_project_limits(data, credentials_list)

        (
            primary_status,
            status_message,
            is_degraded,
            degraded_reason,
        ) = _determine_primary_status(
            credentials_list,
            ordered_project_limits,
            clean_primary_model,
            remaining_retry_after,
        )

        telemetry_dict = data.get("telemetry", _empty_telemetry_dict())
        work_stats_dict = data.get("work_stats", _empty_work_stats_dict())

        # Backwards compatibility key list structure for older UI/tests
        legacy_keys_list: list[dict[str, Any]] = []
        for cred in credentials_list:
            legacy_keys_list.append(
                {
                    "id": cred["id"],
                    "label": cred.get("label", "Chiave API"),
                    "masked_key": cred["masked_key"],
                    "is_primary": cred["is_primary"],
                    "operational_status": cred.get("operational_status", "unused"),
                    "models": {},
                }
            )

        return {
            "schema_version": SCHEMA_VERSION,
            "quota_date": data.get("quota_date", get_pacific_date_string()),
            "primary_status": primary_status,
            "status_message": status_message,
            "retry_after_seconds": remaining_retry_after,
            "next_reset_info": "Reset quote: ore 09:00 (ora italiana / 00:00 PT)",
            "project_limits": ordered_project_limits,
            "work_stats": work_stats_dict,
            "telemetry": telemetry_dict,
            "credentials": credentials_list,
            "is_degraded_mode": is_degraded,
            "degraded_reason": degraded_reason,
            "keys": legacy_keys_list,
            "total_requests_remaining": None,
            "estimated_sbobine_remaining": 0,
        }


# ---------------------------------------------------------------------------
# Backwards Compatibility Aliases
# ---------------------------------------------------------------------------


def record_request(api_key: str, model_name: str, count: int = 1) -> None:
    """Legacy alias: records request attempt and success."""
    record_request_attempt(api_key, model_name)
    record_request_success(api_key, model_name)


def mark_model_exhausted(api_key: str, model_name: str) -> None:
    """Legacy alias: marks quota exhausted for the model."""
    mark_quota_exhausted(model_name)


def reset_daily_usage_for_tests() -> None:
    """Helper used in test suites to clear stored usage data and runtime state."""
    global \
        _SERVER_TIME_OFFSET_SECONDS, \
        _HAS_SERVER_TIME, \
        _RUNTIME_RETRY_AFTER_EXPIRY_UTC, \
        _RUNTIME_RETRY_AFTER_SECONDS
    _SERVER_TIME_OFFSET_SECONDS = 0.0
    _HAS_SERVER_TIME = False
    _RUNTIME_RETRY_AFTER_EXPIRY_UTC = None
    _RUNTIME_RETRY_AFTER_SECONDS = None
    with _interprocess_lock():
        path = _get_usage_file_path()
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        lock_path = _get_lock_file_path()
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except Exception:
                pass
