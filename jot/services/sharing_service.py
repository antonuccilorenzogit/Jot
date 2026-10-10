"""
Sharing and Export/Import service for jot.

Handles packaging sessions into compressed `.sbobina` archives (or zip files)
and safe extraction and import into local storage.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
import zipfile
from typing import Literal

from jot.core.shared import (
    _atomic_write_json,
    _load_json,
    _now_iso,
    _safe_mkdir,
)
from jot.utils.file_ops import _atomic_write_text
from jot.utils.html_export import normalize_imported_html

MAX_FILE_COUNT = 500
MAX_TOTAL_UNCOMPRESSED_SIZE = 1500 * 1024 * 1024  # 1.5 GB
MAX_JSON_SIZE = 1024 * 1024
# Macro blocks contain the full transcript, rather than small session metadata.
MAX_TRANSCRIPT_JSON_SIZE = 32 * 1024 * 1024
MAX_HTML_SIZE = 32 * 1024 * 1024
EXTRACTION_BLOCK_SIZE = 64 * 1024
DISK_SPACE_MARGIN = 64 * 1024 * 1024


def _archive_destination(name: str, target_dir: str) -> str:
    portable = name.replace("\\", "/")
    parts = portable.rstrip("/").split("/")
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or part.endswith((".", " "))
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
            or re.fullmatch(
                r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", part
            )
        ):
            raise ValueError(f"Attacco Zip Slip rilevato o nome non consentito: {name}")
    destination = os.path.realpath(os.path.join(target_dir, *parts))
    root = os.path.realpath(target_dir)
    if os.path.commonpath([root, destination]) != root:
        raise ValueError(f"Attacco Zip Slip rilevato per il file: {name}")
    return destination


def _member_size_limit(name: str) -> int:
    if name.replace("\\", "/").casefold() == "phase2_macro_blocks.json":
        return MAX_TRANSCRIPT_JSON_SIZE
    suffix = os.path.splitext(name)[1].lower()
    if suffix == ".json":
        return MAX_JSON_SIZE
    if suffix in {".html", ".htm"}:
        return MAX_HTML_SIZE
    return MAX_TOTAL_UNCOMPRESSED_SIZE


def _safe_zip_extract(zip_file: zipfile.ZipFile, target_dir: str) -> None:
    """Extract zip archive safely preventing zip-slip, symlinks, and resource exhaustion."""
    resolved_target = os.path.realpath(target_dir)
    infolist = zip_file.infolist()

    if len(infolist) > MAX_FILE_COUNT:
        raise ValueError(
            f"Archivio non valido: numero file ({len(infolist)}) supera il limite consentito ({MAX_FILE_COUNT})."
        )

    total_uncompressed_size = 0
    destinations: set[str] = set()
    members: list[tuple[zipfile.ZipInfo, str]] = []

    for member in infolist:
        # 1. Rifiuto Symlink (is_symlink() su Python 3.13+ o bitmask POSIX)
        is_symlink = False
        is_symlink_fn = getattr(member, "is_symlink", None)
        if callable(is_symlink_fn) and is_symlink_fn():
            is_symlink = True
        elif (member.external_attr >> 16) & 0o170000 == 0o120000:
            is_symlink = True

        if is_symlink:
            raise ValueError(
                f"Link simbolici non consentiti nel pacchetto: {member.filename}"
            )

        # 2. Controllo dimensione decompressa totale
        total_uncompressed_size += member.file_size
        if total_uncompressed_size > MAX_TOTAL_UNCOMPRESSED_SIZE:
            raise ValueError(
                "Dimensione decompressa totale eccede la soglia massima consentita."
            )
        if member.file_size > _member_size_limit(member.filename):
            raise ValueError(
                f"File eccede la soglia massima consentita: {member.filename}"
            )

        # 3. Path Traversal Check
        destination_path = _archive_destination(member.filename, target_dir)
        if (
            not destination_path.startswith(resolved_target + os.sep)
            and destination_path != resolved_target
        ):
            raise ValueError(
                f"Attacco Zip Slip rilevato per il file: {member.filename}"
            )
        identity = destination_path.replace("\\", "/").casefold()
        if identity in destinations:
            raise ValueError(f"Destinazione duplicata nel pacchetto: {member.filename}")
        destinations.add(identity)
        members.append((member, destination_path))

    if shutil.disk_usage(target_dir).free < total_uncompressed_size + DISK_SPACE_MARGIN:
        raise ValueError("Spazio su disco insufficiente per importare il pacchetto.")
    actual_total = 0
    for member, destination in members:
        if member.is_dir() or member.filename.endswith(("/", "\\")):
            os.makedirs(destination, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        actual_member = 0
        with zip_file.open(member) as source, open(destination, "xb") as output:
            while block := source.read(EXTRACTION_BLOCK_SIZE):
                actual_member += len(block)
                actual_total += len(block)
                if (
                    actual_total > MAX_TOTAL_UNCOMPRESSED_SIZE
                    or actual_member > _member_size_limit(member.filename)
                ):
                    raise ValueError(
                        "Dimensione decompressa effettiva eccede la soglia massima consentita."
                    )
                output.write(block)


def _load_package_metadata(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, "rb") as handle:
        raw = handle.read(MAX_JSON_SIZE + 1)
    if len(raw) > MAX_JSON_SIZE:
        raise ValueError("Metadati del pacchetto troppo grandi.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("I metadati del pacchetto devono essere un oggetto JSON.")
    return value


def find_audio_for_session(session_dir: str, session_data: dict) -> str | None:
    """Locate the source audio file for a session if it exists on disk."""
    input_data = session_data.get("input", {})
    if isinstance(input_data, dict):
        current_path = str(input_data.get("path", "") or "").strip()
        if current_path and os.path.isfile(current_path):
            return current_path

        # Check inside session directory (e.g. imported or copied audio)
        rel_path = input_data.get("path_rel_to_session")
        if rel_path:
            candidate = os.path.realpath(os.path.join(session_dir, str(rel_path)))
            if candidate.startswith(os.path.realpath(session_dir)) and os.path.isfile(
                candidate
            ):
                return candidate

    # Search for any audio file directly inside audio/ subdirectory or session_dir
    for candidate_dir in [os.path.join(session_dir, "audio"), session_dir]:
        if os.path.isdir(candidate_dir):
            for entry in os.listdir(candidate_dir):
                ext = os.path.splitext(entry)[1].lower()
                if ext in {
                    ".mp3",
                    ".m4a",
                    ".wav",
                    ".ogg",
                    ".flac",
                    ".aac",
                    ".mkv",
                    ".webm",
                }:
                    full_p = os.path.join(candidate_dir, entry)
                    if os.path.isfile(full_p):
                        return full_p
    return None


def create_sbobina_package(
    session_dir: str,
    target_zip_path: str,
    include_mode: Literal["full", "text_only", "audio_only"] = "full",
    audio_path_override: str | None = None,
) -> dict:
    """Pack a session into a `.sbobina` zip archive according to include_mode."""
    if not os.path.isdir(session_dir):
        return {"ok": False, "error": f"Cartella sessione non trovata: {session_dir}"}

    session_path = os.path.join(session_dir, "session.json")
    session_data = _load_json(session_path) if os.path.isfile(session_path) else {}

    audio_file = audio_path_override or find_audio_for_session(
        session_dir, session_data
    )
    audio_included = False

    if include_mode == "audio_only" and (
        not audio_file or not os.path.isfile(audio_file)
    ):
        return {"ok": False, "error": "File audio sorgente non trovato sul PC."}

    # Ensure parent dir of target_zip_path exists
    _safe_mkdir(os.path.dirname(os.path.abspath(target_zip_path)))

    session_name = session_data.get("input", {}).get("name") or os.path.basename(
        session_dir
    )
    if audio_file:
        session_name = os.path.basename(audio_file)

    manifest = {
        "app": "jot",
        "version": 1,
        "created_at": _now_iso(),
        "include_mode": include_mode,
        "session_name": session_name,
        "audio_filename": os.path.basename(audio_file) if audio_file else None,
    }

    with zipfile.ZipFile(target_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

        if include_mode in ("full", "text_only"):
            # Add session.json
            if os.path.isfile(session_path):
                zf.write(session_path, "session.json")

            # Add output HTML if available
            outputs = session_data.get("outputs", {})
            html_path = outputs.get("html") if isinstance(outputs, dict) else None
            if html_path and os.path.isfile(html_path):
                zf.write(html_path, "Sbobina.html")
            elif os.path.isfile(os.path.join(session_dir, "Sbobina.html")):
                zf.write(os.path.join(session_dir, "Sbobina.html"), "Sbobina.html")
            else:
                # Search for any *.html in session_dir
                for item in os.listdir(session_dir):
                    if item.endswith(".html") and os.path.isfile(
                        os.path.join(session_dir, item)
                    ):
                        zf.write(os.path.join(session_dir, item), "Sbobina.html")
                        break

            # Add macro blocks JSON
            macro_p = os.path.join(session_dir, "phase2_macro_blocks.json")
            if os.path.isfile(macro_p):
                zf.write(macro_p, "phase2_macro_blocks.json")

            # Add subdirectories phase1_chunks and phase2_revised
            for sub_dir in ["phase1_chunks", "phase2_revised"]:
                full_sub = os.path.join(session_dir, sub_dir)
                if os.path.isdir(full_sub):
                    for root, _dirs, files in os.walk(full_sub):
                        for f in files:
                            abs_f = os.path.join(root, f)
                            rel_f = os.path.relpath(abs_f, session_dir)
                            zf.write(abs_f, rel_f)

        if (
            include_mode in ("full", "audio_only")
            and audio_file
            and os.path.isfile(audio_file)
        ):
            audio_arcname = os.path.join("audio", os.path.basename(audio_file))
            zf.write(audio_file, audio_arcname)
            audio_included = True

    size_bytes = os.path.getsize(target_zip_path)
    return {
        "ok": True,
        "target_path": target_zip_path,
        "include_mode": include_mode,
        "audio_included": audio_included,
        "size_bytes": size_bytes,
    }


def _normalize_package_html(
    new_session_dir: str, manifest: dict, session_data: dict
) -> None:
    title = str(
        manifest.get("session_name") or session_data.get("title") or "Sbobina importata"
    )
    for root, _dirs, files in os.walk(new_session_dir):
        for name in files:
            if os.path.splitext(name)[1].lower() in {".html", ".htm"}:
                path = os.path.join(root, name)
                with open(path, "rb") as handle:
                    raw_html = handle.read(MAX_HTML_SIZE + 1)
                if len(raw_html) > MAX_HTML_SIZE:
                    raise ValueError("Documento HTML troppo grande.")
                _atomic_write_text(
                    path, normalize_imported_html(title, raw_html.decode("utf-8"))
                )


def unpack_and_import_package(package_path: str, session_root: str) -> dict:
    """Extract a `.sbobina` package into a new session directory inside session_root."""
    if not os.path.isfile(package_path):
        return {"ok": False, "error": f"File pacchetto non trovato: {package_path}"}

    if not zipfile.is_zipfile(package_path):
        return {
            "ok": False,
            "error": "Il file selezionato non è un pacchetto .sbobina valido (formato ZIP corrotto o errato).",
        }

    # Create a new unique session directory to prevent collisions
    session_id = f"imported_{uuid.uuid4().hex[:12]}"
    new_session_dir = os.path.join(session_root, session_id)
    _safe_mkdir(new_session_dir)

    try:
        with zipfile.ZipFile(package_path, "r") as zf:
            _safe_zip_extract(zf, new_session_dir)

        # Inspect manifest
        manifest_path = os.path.join(new_session_dir, "manifest.json")
        manifest = _load_package_metadata(manifest_path)

        session_path = os.path.join(new_session_dir, "session.json")
        session_data = _load_package_metadata(session_path)

        _normalize_package_html(new_session_dir, manifest, session_data)

        # Locate extracted audio
        audio_dir = os.path.join(new_session_dir, "audio")
        extracted_audio_path: str | None = None
        if os.path.isdir(audio_dir):
            for entry in os.listdir(audio_dir):
                candidate = os.path.join(audio_dir, entry)
                if os.path.isfile(candidate):
                    extracted_audio_path = candidate
                    break

        # Locate HTML output
        html_path = os.path.join(new_session_dir, "Sbobina.html")
        if not os.path.isfile(html_path):
            # Check for any .html in new_session_dir
            for entry in os.listdir(new_session_dir):
                if entry.lower().endswith(".html"):
                    html_path = os.path.join(new_session_dir, entry)
                    break

        # Normalize session.json
        if not session_data:
            session_data = {
                "schema_version": 1,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "stage": "done",
                "input": {},
                "outputs": {},
            }

        session_data["stage"] = "done"
        session_data["updated_at"] = _now_iso()
        session_data["imported_at"] = _now_iso()

        if not isinstance(session_data.get("outputs"), dict):
            session_data["outputs"] = {}
        session_data["outputs"].pop("html", None)
        if os.path.isfile(html_path):
            session_data["outputs"]["html"] = html_path

        if extracted_audio_path and os.path.isfile(extracted_audio_path):
            if "input" not in session_data or not isinstance(
                session_data["input"], dict
            ):
                session_data["input"] = {}
            session_data["input"]["path"] = extracted_audio_path
            session_data["input"]["name"] = os.path.basename(extracted_audio_path)
            session_data["input"]["path_rel_to_session"] = os.path.relpath(
                extracted_audio_path, new_session_dir
            )
            try:
                session_data["input"]["size"] = os.path.getsize(extracted_audio_path)
            except Exception:
                pass
        else:
            # Se il pacchetto non contiene audio (es. text_only), azzeriamo i vecchi path del creatore
            if "input" in session_data and isinstance(session_data["input"], dict):
                session_data["input"]["path"] = None
                session_data["input"]["path_rel_to_session"] = None

        _atomic_write_json(session_path, session_data)

        session_name = (
            manifest.get("session_name")
            or session_data.get("input", {}).get("name")
            or (
                os.path.basename(html_path)
                if os.path.isfile(html_path)
                else "Sbobina Importata"
            )
        )

        return {
            "ok": True,
            "session_dir": new_session_dir,
            "name": session_name,
            "html_path": html_path if os.path.isfile(html_path) else None,
            "has_audio": bool(
                extracted_audio_path and os.path.isfile(extracted_audio_path)
            ),
        }

    except Exception as e:
        # Cleanup incomplete directory on failure
        shutil.rmtree(new_session_dir, ignore_errors=True)
        return {
            "ok": False,
            "error": f"Errore durante l'importazione del pacchetto: {e!s}",
        }
