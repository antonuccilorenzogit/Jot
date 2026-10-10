"""
RPC allowlist and invocation handler for the jot browser server.

Filters, sanitizes, and forwards JS API calls from React to JotApi,
ensuring private methods cannot be invoked and secrets are never leaked.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Complete set of callable bridge methods
ALLOWED_RPC_METHODS: frozenset[str] = frozenset(
    {
        "load_settings",
        "save_settings",
        "check_path_exists",
        "start_processing",
        "stop_processing",
        "is_processing_active",
        "answer_regenerate",
        "answer_new_key",
        "read_html_content",
        "save_html_content",
        "stream_media_file",
        "validate_environment",
        "get_session_storage_info",
        "cleanup_old_sessions",
        "cleanup_completed_sessions",
        "get_completed_sessions",
        "delete_session",
        "update_session_input_path",
        "remove_session_audio",
        "touch_session_opened",
        "get_archive_folders",
        "save_archive_folders",
        "search_sessions",
        "retry_failed_revision_blocks",
        "get_api_usage",
        "get_diagnostic_report",
        "list_diagnostic_sessions",
        "export_diagnostics",
        "record_frontend_event",
        "save_theme_preference",
        "export_sbobina_package",
        "import_sbobina_package",
        # Desktop-only methods that safely return no-op or desktop disclaimer
        "open_file",
        "open_url",
        "show_notification",
        "flash_window",
        "close_window",
        "open_session_folder",
        "ask_session_folder",
        "move_session_root",
        "get_session_move_status",
        "download_and_install_update",
        "open_logs_folder",
    }
)

DESKTOP_ONLY_RESPONSES: dict[str, Any] = {
    "export_diagnostics": {"ok": False, "error": "Disponibile nell'app desktop"},
    "record_frontend_event": {"ok": True},
    "open_file": {"ok": False, "error": "Disponibile nell'app desktop"},
    "open_url": {"ok": True},
    "show_notification": {"ok": True},
    "flash_window": {"ok": True},
    "close_window": {"ok": True},
    "open_session_folder": {"ok": False, "error": "Disponibile nell'app desktop"},
    "ask_session_folder": {"ok": False, "error": "Disponibile nell'app desktop"},
    "move_session_root": {"ok": False, "error": "Disponibile nell'app desktop"},
    "get_session_move_status": {
        "status": "idle",
        "error": "Disponibile nell'app desktop",
    },
    "download_and_install_update": {
        "ok": False,
        "error": "Disponibile nell'app desktop",
    },
    "open_logs_folder": {"ok": False, "error": "Disponibile nell'app desktop"},
}


def sanitize_settings_for_browser(
    settings: dict[str, Any], has_scenario: bool = False
) -> dict[str, Any]:
    """Ensure stored API keys are never leaked to the browser over the network."""
    sanitized = dict(settings)
    has_key = bool(
        sanitized.get("api_key") or sanitized.get("has_protected_key") or has_scenario
    )
    sanitized["has_protected_key"] = has_key
    sanitized["api_key"] = ""
    fallback_keys = sanitized.get("fallback_keys")
    sanitized["configuredFallbackKeyCount"] = (
        sum(1 for key in fallback_keys if str(key).strip())
        if isinstance(fallback_keys, list)
        else 0
    )
    sanitized["fallback_keys"] = []
    return sanitized


def invoke_rpc(
    api: Any, method_name: str, args: list[Any], has_scenario: bool = False
) -> Any:
    """Execute an allowed RPC method on api, returning the sanitized result."""
    if method_name.startswith("_") or method_name not in ALLOWED_RPC_METHODS:
        raise PermissionError(f"RPC method {method_name!r} is not allowed")

    if method_name in DESKTOP_ONLY_RESPONSES:
        return DESKTOP_ONLY_RESPONSES[method_name]

    func: Callable[..., Any] | None = getattr(api, method_name, None)
    if not callable(func):
        raise AttributeError(f"API object has no callable method {method_name!r}")

    result = func(*args)

    if method_name == "load_settings" and isinstance(result, dict):
        result = sanitize_settings_for_browser(result, has_scenario=has_scenario)

    return result
