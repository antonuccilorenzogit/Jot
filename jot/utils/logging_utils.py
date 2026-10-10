"""
Structured logging helpers for jot.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import traceback
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Protocol

LOGGER_NAME = "jot"
_CONTEXT_KEYS = ("boot_id", "run_id", "session_dir", "stage", "input_file")
BOOT_ID = uuid.uuid4().hex
_STARTUP_PREPARED = False
_INCIDENT_LOCK = threading.RLock()
_SECRET_REPLACEMENT = "[API_KEY_REDACTED]"
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAQ\.[0-9A-Za-z_-]{20,}\b"),
    re.compile(
        r"(?i)\b((?:api[_-]?key|key|x-goog-api-key)\s*[:=]\s*)"
        r"([0-9A-Za-z._~+/=-]{8,})"
    ),
    re.compile(
        r"(?i)([?&](?:api[_-]?key|key|x-goog-api-key)=)"
        r"([^&#\s]{8,})"
    ),
)


def redact_secrets(value: object, max_len: int | None = None) -> str:
    text = str(value) if value is not None else ""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(
                lambda match: f"{match.group(1)}{_SECRET_REPLACEMENT}", text
            )
        else:
            text = pattern.sub(_SECRET_REPLACEMENT, text)
    if max_len is not None:
        return text[:max_len]
    return text


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = redact_secrets(super().format(record))
        context_bits: list[str] = []
        for key in _CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value:
                context_bits.append(f"{key}={redact_secrets(value)}")
        if context_bits:
            return f"{base} [{' '.join(context_bits)}]"
        return base


class LogStream(Protocol):
    def write(self, text: str, /) -> object: ...

    def flush(self) -> object: ...


class ConsoleLogFilter(logging.Filter):
    """Keep explicitly diagnostic records in file logs only."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "diagnostic_only", False)


def configure_logging(stream: LogStream | None = None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    configured = getattr(logger, "_jot_configured", False)
    if configured and stream is None:
        return logger

    target = stream if stream is not None else sys.stdout
    # pythonw.exe has no standard streams. File logging can still be configured
    # now; the UI explicitly supplies its console stream once it is available.
    if target is not None:
        handler = next(
            (h for h in logger.handlers if getattr(h, "_el_console_log", False)),
            None,
        )
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(target)
        else:
            handler = logging.StreamHandler(target)
            handler._el_console_log = True  # type: ignore[attr-defined]
            handler.addFilter(ConsoleLogFilter())
            handler.setFormatter(
                StructuredFormatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
            )
            logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._jot_configured = True  # type: ignore[attr-defined]
    return logger


class ContextLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        # Python 3.11's default adapter discards per-call extra (including stage).
        kwargs["extra"] = {**(self.extra or {}), **(kwargs.get("extra") or {})}
        return msg, kwargs


def get_logger(name: str = LOGGER_NAME, **context: str) -> logging.LoggerAdapter:
    base = configure_logging()
    logger = base if name == LOGGER_NAME else logging.getLogger(name)
    if logger is not base:
        logger.setLevel(base.level)
        logger.propagate = True  # propagate to parent; parent has propagate=False
    clean_context = {
        "boot_id": BOOT_ID,
        **{key: value for key, value in context.items() if value},
    }
    return ContextLoggerAdapter(logger, clean_context)


def attach_file_handler(log_path: str) -> logging.Handler | None:
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            StructuredFormatter("%(asctime)s %(levelname)s %(message)s")
        )
        configure_logging().addHandler(handler)
        return handler
    except Exception:
        return None


def detach_file_handler(handler: logging.Handler | None) -> None:
    if handler is None:
        return
    logger = configure_logging()
    try:
        logger.removeHandler(handler)
    except Exception:
        pass
    try:
        handler.close()
    except Exception:
        pass


_GENERAL_LOG_LOCK = threading.Lock()


class GeneralLogFilter(logging.Filter):
    """Keep session processing details in their existing run.log files."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            getattr(record, "session_dir", None) or getattr(record, "input_file", None)
        )


def initialize_app_logging() -> str | None:
    """Attach a bounded, sanitized general log once, independently of debug mode."""
    try:
        from jot.services.config_service import get_config_dir

        path = os.path.join(get_config_dir(), "jot.log")
        with _GENERAL_LOG_LOCK:
            logger = configure_logging()
            for handler in list(logger.handlers):
                if getattr(handler, "_el_general_log", False):
                    if getattr(handler, "baseFilename", None) == os.path.abspath(path):
                        return path
                    logger.removeHandler(handler)
                    handler.close()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handler = RotatingFileHandler(
                path, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8"
            )
            handler._el_general_log = True  # type: ignore[attr-defined]
            handler.addFilter(GeneralLogFilter())
            handler.setFormatter(
                StructuredFormatter("%(asctime)s %(levelname)s %(message)s")
            )
            logger.addHandler(handler)
            if not any(
                isinstance(existing, IncidentHandler) for existing in logger.handlers
            ):
                logger.addHandler(IncidentHandler())
        return path
    except Exception:
        return None


def record_startup_diagnostic(**details: object) -> None:
    """Persist the latest startup separately so log rotation cannot hide it."""
    try:
        from jot.services.config_service import get_config_dir
        from jot.utils.file_ops import _atomic_write_json

        initialize_app_logging()
        payload = {
            "boot_id": BOOT_ID,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "executable": redact_secrets(sys.executable),
            **{
                key: redact_secrets(value, max_len=2000)
                if isinstance(value, str)
                else value
                for key, value in details.items()
            },
        }
        _atomic_write_json(
            os.path.join(get_config_dir(), "startup_diagnostic.json"), payload
        )
        if details.get("status") == "recovery":
            _atomic_write_json(
                os.path.join(get_config_dir(), "startup_failure.json"), payload
            )
        get_logger().info(
            "Avvio interfaccia: %s", json.dumps(payload, ensure_ascii=False)
        )
    except Exception:
        # Failure to write diagnostics must never prevent app startup.
        pass


def get_startup_diagnostic() -> dict:
    try:
        from jot.services.config_service import get_config_dir

        path = os.path.join(get_config_dir(), "startup_diagnostic.json")
        with open(path, encoding="utf-8") as handle:
            payload = json.loads(handle.read(16384))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


class IncidentHandler(logging.Handler):
    """Persist bounded warning/error context, including session-scoped failures."""

    def __init__(self):
        super().__init__(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            record_incident(
                record.name,
                record.getMessage(),
                "".join(traceback.format_exception(*record.exc_info))
                if record.exc_info
                else "",
                stage=str(getattr(record, "stage", "")),
                operation=str(getattr(record, "run_id", "")),
                severity=record.levelname,
            )
        except Exception:
            pass


def record_incident(source: str, message: str, stack: str = "", **context: str) -> None:
    try:
        from jot.services.config_service import get_config_dir
        from jot.utils.file_ops import _atomic_write_json

        path = os.path.join(get_config_dir(), "incidents.json")
        with _INCIDENT_LOCK:
            try:
                with open(path, encoding="utf-8") as handle:
                    existing = json.loads(handle.read(256 * 1024))
                events = (
                    existing.get("events", []) if isinstance(existing, dict) else []
                )
                if not isinstance(events, list):
                    events = []
            except (OSError, ValueError):
                events = []
            event = {
                "id": uuid.uuid4().hex,
                "boot_id": BOOT_ID,
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source": redact_secrets(source, max_len=100),
                "message": redact_secrets(message, max_len=3000),
                "stack": redact_secrets(stack, max_len=6000),
                **{
                    key: redact_secrets(value, max_len=200)
                    for key, value in context.items()
                },
            }
            retained = [*events[-19:], event]
            # Keep the file readable by the bounded support collector, including
            # multibyte messages and escaped control characters in tracebacks.
            while (
                len(retained) > 1
                and len(
                    json.dumps(
                        {"events": retained}, ensure_ascii=False, indent=2
                    ).encode("utf-8")
                )
                > 240 * 1024
            ):
                retained.pop(0)
            _atomic_write_json(path, {"events": retained})
            if context.get("severity", "ERROR") in ("ERROR", "CRITICAL"):
                _atomic_write_json(
                    os.path.join(get_config_dir(), "last_failure.json"), event
                )
    except Exception:
        pass


def install_exception_hooks() -> None:
    """Record uncaught Python/thread failures while retaining default behavior."""
    if getattr(sys.excepthook, "_el_diagnostic_hook", False):
        return
    previous_sys = sys.excepthook
    previous_thread = threading.excepthook

    def main_hook(kind, value, tb):
        record_incident(
            "python.uncaught",
            str(value),
            "".join(traceback.format_exception(kind, value, tb)),
        )
        previous_sys(kind, value, tb)

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            record_incident(
                "python.thread",
                str(args.exc_value),
                "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                ),
            )
        previous_thread(args)

    main_hook._el_diagnostic_hook = True  # type: ignore[attr-defined]
    sys.excepthook = main_hook
    threading.excepthook = thread_hook


def operation_id(path: str) -> str:
    return hashlib.sha256(
        os.path.normcase(os.path.realpath(path)).encode()
    ).hexdigest()[:16]


def prepare_startup() -> None:
    global _STARTUP_PREPARED
    if _STARTUP_PREPARED:
        return
    _STARTUP_PREPARED = True
    install_exception_hooks()
    record_startup_diagnostic(status="starting")
    engine = logging.getLogger("pywebview")
    if not any(isinstance(handler, IncidentHandler) for handler in engine.handlers):
        engine.addHandler(IncidentHandler())
