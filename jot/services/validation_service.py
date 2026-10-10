"""
Environment validation helpers and diagnostic reporting.

Used by the WebUI "validate environment" action, build/release smoke checks,
and 1-click diagnostic support reports.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from google import genai

from jot.bridge.bridge_types import ValidationCheck, ValidationResult
from jot.core.model_registry import (
    DEFAULT_FALLBACK_MODELS,
    sanitize_fallback_models,
    sanitize_model_name,
)
from jot.core.shared import DEFAULT_MODEL, get_session_root
from jot.services.audio_service import resolve_ffmpeg
from jot.services.config_service import CONFIG_FILE, get_config_dir
from jot.services.generation_service import create_gemini_client
from jot.utils.logging_utils import redact_secrets

MIN_FREE_DISK_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB minimum


def _format_bytes(bytes_count: int) -> str:
    gb = bytes_count / (1024 * 1024 * 1024)
    if gb >= 1.0:
        return f"{gb:.1f} GB"
    mb = bytes_count / (1024 * 1024)
    return f"{mb:.0f} MB"


def _check_writable_dir(path: str) -> tuple[bool, str]:
    probe_name = os.path.join(path, ".jot_write_test")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe_name, "w", encoding="utf-8") as handle:
            handle.write("ok")
    except Exception as exc:
        return False, redact_secrets(exc)
    try:
        os.remove(probe_name)
    except Exception:
        pass
    return True, "Scrittura consentita."


def _get_model_capabilities(model_info: Any) -> list[str] | None:
    for field_name in ("supported_actions", "supported_generation_methods"):
        try:
            if isinstance(model_info, dict):
                value = model_info.get(field_name)
            else:
                value = getattr(model_info, field_name, None)
        except Exception:
            value = None
        if isinstance(value, list | tuple):
            return [str(item).strip() for item in value if str(item).strip()]
    return None


def _check_ffmpeg_execution(ffmpeg_path: str) -> tuple[bool, str]:
    try:
        creation_flags = (
            subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )
        res = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
            creationflags=creation_flags,
        )
        if res.returncode == 0 and res.stdout:
            first_line = res.stdout.splitlines()[0].strip()
            return True, first_line
        err = (res.stderr or res.stdout or "").strip()[:200]
        return False, f"FFmpeg ha restituito codice {res.returncode}: {err}"
    except Exception as exc:
        return False, redact_secrets(exc)


def _check_disk_space(path: str) -> tuple[str, str, str]:
    """Returns (status, message, details) for disk space at path."""
    try:
        os.makedirs(path, exist_ok=True)
        usage = shutil.disk_usage(path)
        free_formatted = _format_bytes(usage.free)
        total_formatted = _format_bytes(usage.total)

        if usage.free < MIN_FREE_DISK_BYTES:
            return (
                "warning",
                f"Spazio su disco quasi esaurito: rimasti solo {free_formatted} liberi.",
                f"Spazio libero: {free_formatted} / {total_formatted} su {path}\n"
                "Rimedio: libera almeno 2 GB di spazio prima di elaborare audio o video lunghi.",
            )
        return (
            "ok",
            f"Spazio su disco sufficiente: {free_formatted} liberi.",
            f"Spazio libero: {free_formatted} su {total_formatted} totali ({path})",
        )
    except Exception as exc:
        return (
            "warning",
            "Impossibile verificare lo spazio libero su disco.",
            redact_secrets(exc),
        )


def validate_environment(
    api_key: str | None = None,
    validate_api_key: bool = False,
    preferred_model: str | None = None,
    fallback_models: list[str] | None = None,
) -> ValidationResult:
    checks: list[ValidationCheck] = []

    # 1. API Key & Models Check (Cost-zero metadata validation via models.get)
    if validate_api_key:
        cleaned = str(api_key or "").strip()
        primary_model = sanitize_model_name(preferred_model, DEFAULT_MODEL)
        sanitized_fallbacks = sanitize_fallback_models(
            fallback_models,
            primary_model,
            DEFAULT_FALLBACK_MODELS,
        )
        if not cleaned:
            checks.append(
                {
                    "id": "api_key",
                    "label": "API Key Gemini",
                    "status": "warning",
                    "message": "API key assente: controllo remoto saltato.",
                    "details": "Inserisci una chiave se vuoi verificare l'accesso al modello.",
                }
            )
        else:
            try:
                client = create_gemini_client(cleaned)
            except Exception as exc:
                checks.append(
                    {
                        "id": "api_key",
                        "label": "API Key Gemini",
                        "status": "error",
                        "message": "API key non valida o formato non corretto.",
                        "details": redact_secrets(exc),
                    }
                )
            else:
                model_chain = [primary_model, *sanitized_fallbacks]
                for idx, model_name in enumerate(model_chain):
                    check_id = "api_key" if idx == 0 else f"api_model_{idx}"
                    check_label = (
                        "API Key Gemini" if idx == 0 else f"Fallback modello {idx}"
                    )
                    try:
                        model_info = client.models.get(model=model_name)
                        capabilities = _get_model_capabilities(model_info)

                        if capabilities is not None and "generatecontent" not in {
                            str(item or "").strip().lower() for item in capabilities
                        }:
                            raise RuntimeError(
                                f"{model_name} non supporta generateContent"
                            )
                        checks.append(
                            {
                                "id": check_id,
                                "label": check_label,
                                "status": "ok",
                                "message": f"Accesso disponibile per {model_name}.",
                                "details": model_name,
                            }
                        )
                    except Exception as exc:
                        checks.append(
                            {
                                "id": check_id,
                                "label": check_label,
                                "status": "error",
                                "message": (
                                    "Modello primario non accessibile."
                                    if idx == 0
                                    else f"Modello fallback {idx} non accessibile con questa chiave."
                                ),
                                "details": redact_secrets(f"{model_name}: {exc}"),
                            }
                        )

    # 2. FFmpeg Functional Check
    try:
        ffmpeg_path = resolve_ffmpeg()
        ok_exec, ffmpeg_detail = _check_ffmpeg_execution(ffmpeg_path)
        checks.append(
            {
                "id": "ffmpeg",
                "label": "FFmpeg",
                "status": "ok" if ok_exec else "error",
                "message": "FFmpeg disponibile ed eseguibile."
                if ok_exec
                else "FFmpeg non trovato o non utilizzabile.",
                "details": f"{ffmpeg_path}\n{ffmpeg_detail}"
                if ok_exec
                else ffmpeg_detail,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "id": "ffmpeg",
                "label": "FFmpeg",
                "status": "error",
                "message": "FFmpeg non trovato o non utilizzabile.",
                "details": redact_secrets(exc),
            }
        )

    # 3. Config Directory Permissions
    config_dir = get_config_dir()
    ok_config, msg_config = _check_writable_dir(config_dir)
    checks.append(
        {
            "id": "config",
            "label": "Config locale",
            "status": "ok" if ok_config else "error",
            "message": "Cartella config scrivibile."
            if ok_config
            else "Impossibile scrivere la config.",
            "details": config_dir if ok_config else msg_config,
        }
    )

    # 4. Disk Space & Permissions (Session Folder)
    session_output_dir = get_session_root()
    ok_output, msg_output = _check_writable_dir(session_output_dir)
    disk_status, disk_msg, disk_details = _check_disk_space(session_output_dir)

    if not ok_output:
        checks.append(
            {
                "id": "output",
                "label": "Cartella sessioni/output",
                "status": "error",
                "message": "Cartella sessioni/output non scrivibile.",
                "details": (
                    f"Percorso: {session_output_dir}\n"
                    f"Errore: {msg_output}\n"
                    "Rimedio: scegli una cartella sessioni scrivibile dalle impostazioni "
                    "o correggi i permessi della cartella."
                ),
            }
        )
    elif disk_status == "warning":
        checks.append(
            {
                "id": "output",
                "label": "Cartella sessioni/output",
                "status": "warning",
                "message": disk_msg,
                "details": disk_details,
            }
        )
    else:
        checks.append(
            {
                "id": "output",
                "label": "Cartella sessioni/output",
                "status": "ok",
                "message": "Cartella sessioni/output scrivibile.",
                "details": session_output_dir,
            }
        )

    # 5. Keyring (non-Windows only)
    if platform.system() != "Windows":
        keyring_ok = False
        keyring_detail = ""
        try:
            import keyring  # type: ignore

            keyring.get_password("__jot_probe__", "__probe__")
            keyring_ok = True
        except Exception as exc:
            keyring_detail = redact_secrets(exc)
        checks.append(
            {
                "id": "keyring",
                "label": "Keyring",
                "status": "ok" if keyring_ok else "warning",
                "message": "Keyring disponibile: chiave API protetta."
                if keyring_ok
                else "Keyring non disponibile: la chiave API sarà salvata in chiaro.",
                "details": "" if keyring_ok else keyring_detail,
            }
        )

    has_errors = any(check["status"] == "error" for check in checks)
    has_warnings = any(check["status"] == "warning" for check in checks)
    ok = not has_errors
    if has_errors:
        summary = "Ambiente incompleto: correggi gli errori segnalati."
    elif has_warnings:
        summary = "Ambiente pronto con avvisi: verifica le segnalazioni."
    else:
        summary = "Ambiente pronto."
    return {
        "ok": ok,
        "summary": summary,
        "checks": checks,
        "has_warnings": has_warnings,
    }


def get_recent_log_tail(max_lines: int = 40) -> list[str]:
    """Reads the last N lines from the local jot.log file."""
    config_dir = get_config_dir()
    log_path = os.path.join(config_dir, "jot.log")
    if not os.path.exists(log_path):
        return ["Nessun log recente registrato."]
    try:
        with open(log_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

            return [redact_secrets(line.rstrip()) for line in lines[-max_lines:]]
    except Exception as exc:
        return [f"Errore lettura log: {redact_secrets(exc)}"]


def generate_diagnostic_report(
    api_key: str | None = None,
    fallback_keys: list[str] | None = None,
    preferred_model: str | None = None,
    fallback_models: list[str] | None = None,
    session_dir: str | None = None,
    frontend_version: str | None = None,
) -> str:
    """Compatibility entry point for an entirely local support report."""
    from jot.services.diagnostics_service import collect_files

    return collect_files(get_session_root(), session_dir, frontend_version)["report.md"]
