"""Local, bounded support reports. Never upload media or call remote APIs."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from jot.services.config_service import get_config_dir
from jot.utils.logging_utils import operation_id, redact_secrets

MAX_BYTES = 256 * 1024


def read_text(path: Path, *, tail: bool = False) -> str:
    """Read bounded regular files, excluding symlinks and binary attachments."""
    if path.is_symlink() or not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            if tail:
                handle.seek(max(0, path.stat().st_size - MAX_BYTES))
            data = handle.read(MAX_BYTES)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def read_json(path: Path) -> dict:
    try:
        value = json.loads(read_text(path))
        return value if isinstance(value, dict) else {}
    except (ValueError, OSError):
        return {}


def sanitize(text: str, session_dir: str | None = None) -> str:
    text = redact_secrets(text)
    replacements = [
        (get_config_dir(), "<CONFIG>"),
        (os.path.expanduser("~"), "<USER_HOME>"),
    ]
    if session_dir:
        replacements.insert(0, (session_dir, "<SESSION>"))
        data = read_json(Path(session_dir) / "session.json")
        original = (
            data.get("input", {}).get("path")
            if isinstance(data.get("input"), dict)
            else None
        )
        if isinstance(original, str) and original:
            replacements.insert(0, (original, "<MEDIA>"))
            replacements.append((os.path.basename(original), "<MEDIA>"))
    # Cover both plain text paths and JSON-escaped paths, without exporting usernames.
    for original, alias in sorted(
        replacements, key=lambda pair: len(pair[0]), reverse=True
    ):
        if original and original not in (".", "/", "\\"):
            text = re.sub(
                re.escape(original.replace("\\", "\\\\")),
                lambda _, replacement=alias: replacement,
                text,
                flags=re.I,
            )
            text = re.sub(
                re.escape(original),
                lambda _, replacement=alias: replacement,
                text,
                flags=re.I,
            )
    text = re.sub(r"\binput_file=[^\]\r\n]+", "input_file=<MEDIA>", text)
    return text


def validate_session(session_dir: str, root: str) -> Path:
    directory = Path(session_dir).resolve()
    resolved_root = Path(root).resolve()
    if (
        directory == resolved_root
        or resolved_root not in directory.parents
        or not directory.is_dir()
    ):
        raise ValueError("La sbobina deve appartenere all'archivio corrente.")
    return directory


def list_sessions(root: str) -> list[dict]:
    directory = Path(root)
    if not directory.is_dir():
        return []
    candidates = []
    for child in directory.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        data = read_json(child / "session.json")
        if not data:
            continue
        source = data.get("input", {})
        source_name = (
            os.path.basename(str(source.get("path", "")))
            if isinstance(source, dict)
            else ""
        )
        title = str(data.get("title") or "").strip()
        candidates.append(
            {
                "path": str(child),
                "label": title or Path(source_name).stem or child.name,
                "updated_at": str(data.get("updated_at", "")),
            }
        )
    return sorted(candidates, key=lambda item: item["updated_at"], reverse=True)[:100]


def read_build_metadata(data_dir: Path, *, macos_bundle: bool = False) -> dict:
    """Read packaged metadata, allowing only links within its installation root."""
    try:
        # PyInstaller places macOS data in Resources and links it from Frameworks.
        root = (
            data_dir.parent
            if macos_bundle
            and data_dir.name == "Frameworks"
            and data_dir.parent.name == "Contents"
            else data_dir
        ).resolve(strict=True)
        base = data_dir.resolve(strict=True)
        if not base.is_relative_to(root):
            return {}
        metadata = (base / "diagnostic_build.json").resolve(strict=True)
        if not metadata.is_relative_to(root):
            return {}
        data = read_json(metadata)
    except (OSError, RuntimeError):
        return {}
    version = data.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
        version.strip(),
    ):
        return {}
    data["version"] = version.strip().lstrip("v")
    return data


def build_info() -> dict:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    frozen = bool(getattr(sys, "frozen", False))
    data = read_build_metadata(base, macos_bundle=frozen and sys.platform == "darwin")
    if not data:
        data = {
            "version": (
                "unknown"
                if frozen
                else read_json(base / "webui" / "package.json").get(
                    "version", "unknown"
                )
            ),
            "mode": "packaged" if frozen else "source",
        }
    return data


def collect_files(
    root: str, session_dir: str | None = None, frontend_version: str | None = None
) -> dict[str, str]:
    selected = str(validate_session(session_dir, root)) if session_dir else None
    config = Path(get_config_dir())
    settings = read_json(config / "config.json")
    dependencies = {}
    for package in ("pywebview", "pythonnet", "google-genai", "imageio-ffmpeg"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = "unavailable"
    overview = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "build": build_info(),
        "frontend_version": str(frontend_version or "unknown")[:80],
        "os": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "dependencies": dependencies,
        "settings": {
            key: settings.get(key)
            for key in ("preferred_model", "fallback_models", "notifications_enabled")
        },
        "collection": "local; no remote API validation performed",
        "archive_exists": Path(root).is_dir(),
    }
    try:
        overview["disk_free_bytes"] = shutil.disk_usage(
            root if Path(root).exists() else get_config_dir()
        ).free
    except OSError:
        overview["disk_free_bytes"] = None
    files = {"environment.json": json.dumps(overview, ensure_ascii=False, indent=2)}
    for name in (
        "startup_diagnostic.json",
        "startup_failure.json",
        "last_failure.json",
        "incidents.json",
        "last_validation.json",
    ):
        data = read_json(config / name)
        if data:
            files[name] = json.dumps(data, ensure_ascii=False, indent=2)
    for suffix in (".3", ".2", ".1", ""):
        name = "jot.log" + suffix
        text = read_text(config / name, tail=True)
        if text:
            files["logs/" + name] = "\n".join(text.splitlines()[-200:])
    if selected:
        data = read_json(Path(selected) / "session.json")
        summary = {
            key: data.get(key)
            for key in (
                "schema_version",
                "created_at",
                "updated_at",
                "stage",
                "last_error",
                "last_error_detail",
            )
        }
        summary["operation_id"] = operation_id(selected)
        for phase, keys in (
            ("phase1", ("chunks_done", "next_start_sec")),
            ("phase2", ("macro_total", "revised_done")),
            (
                "retry_state",
                (
                    "state",
                    "reason",
                    "model",
                    "attempt",
                    "max_attempts",
                    "next_retry_at",
                ),
            ),
        ):
            value = data.get(phase)
            if isinstance(value, dict):
                summary[phase] = {key: value.get(key) for key in keys}
        source = data.get("input")
        if isinstance(source, dict):
            summary["media"] = {
                "size": source.get("size"),
                "extension": Path(str(source.get("path", ""))).suffix,
            }
        files["session_summary.json"] = json.dumps(
            summary, ensure_ascii=False, indent=2
        )
        run_log = read_text(Path(selected) / "run.log", tail=True)
        if run_log:
            files["logs/selected_run.log"] = "\n".join(run_log.splitlines()[-200:])
    files = {name: sanitize(text, selected) for name, text in files.items()}
    sections = [
        "# Report Diagnostico jot",
        "",
        "Raccolta locale. Nessun audio, trascrizione o configurazione completa allegata.",
    ]
    for name, content in files.items():
        sections.extend(["", "## " + name, "```text", content, "```"])
    files["report.md"] = "\n".join(sections)
    return files


def export_bundle(target: str, files: dict[str, str]) -> str:
    """Publish the archive atomically; never overwrite it with a partial ZIP."""
    destination = Path(target)
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, suffix=".zip", delete=False
        ) as handle:
            temporary = handle.name
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        os.replace(temporary, destination)
        return str(destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save_validation_snapshot(result: Mapping[str, Any]) -> None:
    """Cache explicit checks for local support collection, with bounded fields."""
    try:
        from jot.utils.file_ops import _atomic_write_json

        checks = result.get("checks", [])
        snapshot = {
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ok": bool(result.get("ok")),
            "checks": [
                {
                    key: redact_secrets(check.get(key), max_len=2000)
                    for key in ("id", "status", "label", "message", "details")
                }
                for check in checks[:30]
                if isinstance(check, dict)
            ],
        }
        _atomic_write_json(
            os.path.join(get_config_dir(), "last_validation.json"), snapshot
        )
    except Exception:
        pass
