"""
Media and file selection IPC bridge controller.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, ClassVar

import webview

from jot.bridge.bridge_types import BridgeFileItem
from jot.bridge.bridge_utils import (
    _candidate_from_relative,
    bridge_error,
    bridge_ok,
)
from jot.core.media_server import LocalMediaServer
from jot.core.shared import _atomic_write_json, _load_json
from jot.pipeline.pipeline_adapter import _drain_dnd_paths
from jot.services.archive_service import find_candidate_audio_path
from jot.utils.logging_utils import redact_secrets

if TYPE_CHECKING:
    from jot.pipeline.pipeline_adapter import PipelineAdapter


class MediaControllerMixin:
    """Mixin providing file selection, drag-and-drop, and media streaming IPC methods."""

    _ALLOWED_MEDIA_EXTS: ClassVar[set[str]] = {
        ".mp3",
        ".m4a",
        ".wav",
        ".ogg",
        ".flac",
        ".aac",
        ".mp4",
        ".mkv",
        ".webm",
        ".opus",
        ".mov",
        ".3gp",
    }
    _SUPPORTED_MEDIA_LABEL: ClassVar[str] = (
        "MP3, M4A, WAV, OGG, FLAC, AAC, MP4, MKV, OPUS, MOV o 3GP"
    )
    _UNSUPPORTED_MEDIA_ERROR: ClassVar[str] = (
        "Formato non supportato. Seleziona un file audio/video: "
        f"{_SUPPORTED_MEDIA_LABEL}."
    )
    _UNREADABLE_MEDIA_ERROR: ClassVar[str] = (
        "Impossibile leggere la durata del file. Seleziona un file audio/video "
        f"valido: {_SUPPORTED_MEDIA_LABEL}."
    )
    _KNOWN_NON_MEDIA_EXTS: ClassVar[set[str]] = {
        ".pdf",
        ".docx",
        ".doc",
        ".txt",
        ".rtf",
        ".odt",
        ".zip",
        ".tar",
        ".gz",
        ".7z",
        ".rar",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".webp",
        ".svg",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".json",
        ".xml",
        ".csv",
        ".py",
        ".exe",
        ".dll",
        ".so",
        ".dmg",
        ".iso",
    }
    _SLIDES_EXTS: ClassVar[set[str]] = {".pdf", ".pptx"}
    _ALLOWED_DROP_EXTS: ClassVar[set[str]] = _ALLOWED_MEDIA_EXTS
    _ALLOWED_STREAM_EXTS: ClassVar[set[str]] = _ALLOWED_MEDIA_EXTS

    if TYPE_CHECKING:
        _window: webview.Window | None
        _adapter: PipelineAdapter

        def _push_console(self, msg: str) -> None: ...
        def _resolve_retry_session(self, session_dir: str) -> tuple[str, str]: ...

    def _find_candidate_audio_path(
        self,
        data: dict,
        session_dir: str,
        session_path: str | None = None,
        *,
        write_back: bool = True,
    ) -> str | None:
        return find_candidate_audio_path(
            data,
            session_dir,
            session_path,
            write_back=write_back,
        )

    def _resolve_completed_session_audio_path(
        self, data: dict, session_dir: str, session_path: str | None = None
    ) -> str | None:
        candidate = self._find_candidate_audio_path(
            data, session_dir, session_path, write_back=False
        )
        if candidate is None:
            return None
        ext = os.path.splitext(candidate)[1].lower()
        if ext not in self._ALLOWED_STREAM_EXTS:
            if ext in self._KNOWN_NON_MEDIA_EXTS:
                return None
            ok, _err, _dur = self._validate_media_path(candidate, require_duration=True)
            if not ok:
                return None
        return candidate

    @staticmethod
    def _build_file_descriptor(
        path: str, duration: float | None = None
    ) -> BridgeFileItem:
        try:
            size = os.path.getsize(path)
        except Exception:
            size = 0
        if duration is None:
            try:
                from jot.services.audio_service import probe_media_duration

                dur_val, _reason = probe_media_duration(path)
                duration = dur_val if dur_val else 0
            except Exception:
                duration = 0
        return {
            "id": path,
            "path": path,
            "name": os.path.basename(path),
            "size": size,
            "duration": duration,
        }

    @classmethod
    def _validate_media_path(
        cls, path: str, *, require_duration: bool = False
    ) -> tuple[bool, str, float | None]:
        normalized_path = str(path or "").strip()
        if not normalized_path or not os.path.isfile(normalized_path):
            return (
                False,
                "File non trovato. Seleziona un file audio/video esistente.",
                None,
            )
        ext = os.path.splitext(normalized_path)[1].lower()
        if ext in cls._ALLOWED_MEDIA_EXTS:
            if not require_duration:
                return True, "", None
            try:
                from jot.services.audio_service import probe_media_duration

                duration, _reason = probe_media_duration(normalized_path)
                duration_value = float(duration or 0)
            except Exception:
                duration_value = 0.0
            if duration_value <= 0:
                return False, cls._UNREADABLE_MEDIA_ERROR, None
            return True, "", duration_value

        if ext in cls._KNOWN_NON_MEDIA_EXTS:
            # Il file ha un'estensione non multimediale nota (es. .pdf, .docx, .txt)
            return False, cls._UNSUPPORTED_MEDIA_ERROR, None

        # Per file senza estensione o con pseudo-estensioni (es. date o numeri nel nome),
        # verifica tramite FFmpeg se contengono uno stream multimediale decodificabile.
        try:
            from jot.services.audio_service import probe_media_duration

            duration, _reason = probe_media_duration(normalized_path)
            duration_value = float(duration or 0)
        except Exception:
            duration_value = 0.0
        if duration_value <= 0:
            return False, cls._UNSUPPORTED_MEDIA_ERROR, None
        return True, "", duration_value

    def _build_valid_media_descriptor(self, path: str) -> BridgeFileItem | None:
        ok, error, probed_duration = self._validate_media_path(path)
        if not ok:
            self._push_console(f"⚠ {error}")
            return None
        return self._build_file_descriptor(path, duration=probed_duration)

    def _validate_processing_files(self, files: list[BridgeFileItem]) -> str | None:
        for file_info in files:
            file_path = str(file_info.get("path", "") or "").strip()
            if file_info.get("kind") == "notes":
                error = self._validate_notes_item(file_info)
                if error:
                    return error
                file_info["duration"] = 0.0
                continue
            ok, error, probed_duration = self._validate_media_path(
                file_path, require_duration=True
            )
            if not ok:
                return error
            error = self._validate_lesson_documents(file_info)
            if error:
                return error
            file_info["duration"] = float(probed_duration or 0)
        return None

    def ask_files(self) -> list[BridgeFileItem]:
        """Open native file dialog and return file info."""
        if not self._window:
            return []
        try:
            file_paths = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=(
                    "Audio (*.mp3;*.m4a;*.wav;*.ogg;*.flac;*.aac;*.opus)",
                    "Video (*.mp4;*.mkv;*.webm;*.mov;*.3gp)",
                    "Tutti i file (*.*)",
                ),
            )
        except Exception:
            file_paths = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
            )
        if not file_paths:
            return []
        selected_paths = (
            [str(p) for p in file_paths]
            if isinstance(file_paths, list | tuple)
            else [str(file_paths)]
        )
        descriptors = []
        for path in selected_paths:
            descriptor = self._build_valid_media_descriptor(path)
            if descriptor is not None:
                descriptors.append(descriptor)
        return descriptors

    def ask_media_file(self) -> BridgeFileItem | None:
        """Open a native file dialog for a single media file."""
        if not self._window:
            return None
        try:
            file_paths = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "Audio (*.mp3;*.m4a;*.wav;*.ogg;*.flac;*.aac;*.opus)",
                    "Video (*.mp4;*.mkv;*.webm;*.mov;*.3gp)",
                    "Tutti i file (*.*)",
                ),
            )
        except Exception:
            file_paths = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
            )
        if not file_paths:
            return None
        selected_path = str(
            file_paths[0] if isinstance(file_paths, list | tuple) else file_paths
        )
        return self._build_valid_media_descriptor(selected_path)

    @staticmethod
    def _validate_notes_item(file_info: BridgeFileItem) -> str | None:
        from jot.services import document_service

        slides_path = str(file_info.get("path", "") or "").strip()
        if not slides_path or not os.path.isfile(slides_path):
            return "File delle slide non trovato. Selezionalo di nuovo."
        try:
            document_service.validate_slides(slides_path)
            book_path = str(file_info.get("book_path") or "").strip()
            if book_path:
                if not os.path.isfile(book_path):
                    return "PDF del libro non trovato. Selezionalo di nuovo."
                document_service.validate_book(
                    book_path, str(file_info.get("book_pages") or "")
                )
        except document_service.DocumentError as exc:
            return str(exc)
        return None

    @staticmethod
    def _validate_lesson_documents(file_info: BridgeFileItem) -> str | None:
        """Slides and book attached to an audio lesson (both optional)."""
        from jot.services import document_service

        slides_path = str(file_info.get("slides_path") or "").strip()
        book_path = str(file_info.get("book_path") or "").strip()
        try:
            if slides_path:
                if not os.path.isfile(slides_path):
                    return "File delle slide non trovato. Selezionalo di nuovo."
                document_service.validate_slides(slides_path)
            if book_path:
                if not os.path.isfile(book_path):
                    return "PDF del libro non trovato. Selezionalo di nuovo."
                document_service.validate_book(
                    book_path, str(file_info.get("book_pages") or "")
                )
        except document_service.DocumentError as exc:
            return str(exc)
        return None

    def suggest_lesson(
        self,
        audio_path: str | None = None,
        slides_path: str | None = None,
        book_path: str | None = None,
    ) -> dict:
        """Lesson name and book chapter guessed from the chosen files."""
        from jot.services import lesson_planning

        def _existing(path: str | None) -> str | None:
            clean = str(path or "").strip()
            return clean if clean and os.path.isfile(clean) else None

        audio, slides, book = (
            _existing(audio_path),
            _existing(slides_path),
            _existing(book_path),
        )
        try:
            title = lesson_planning.suggest_title(audio, slides)
        except Exception:
            title = None
        chapter = None
        if book and (slides or title):
            try:
                chapter = lesson_planning.suggest_chapter(book, slides, title)
            except Exception:
                chapter = None
        return bridge_ok(title=title, chapter=chapter)

    def ask_document_file(self, purpose: str = "slides") -> dict:
        """Pick the slides (PDF/PPTX) or the textbook (PDF) for the notes mode."""
        from jot.services import document_service

        if not self._window:
            return bridge_error("Finestra non disponibile.")
        is_book = str(purpose or "") == "book"
        file_types = (
            ("Libro PDF (*.pdf)", "Tutti i file (*.*)")
            if is_book
            else (
                "Slide (*.pdf;*.pptx)",
                "PDF (*.pdf)",
                "PowerPoint (*.pptx)",
                "Tutti i file (*.*)",
            )
        )
        try:
            file_paths = self._window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types
            )
        except Exception:
            file_paths = self._window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False
            )
        if not file_paths:
            return bridge_ok(cancelled=True)
        selected = str(
            file_paths[0] if isinstance(file_paths, list | tuple) else file_paths
        )
        return self.inspect_document(selected, purpose)

    def inspect_document(self, path: str, purpose: str = "slides") -> dict:
        """Validate a slides/book file and return its descriptor (pages, size)."""
        from jot.services import document_service

        normalized = str(path or "").strip()
        is_book = str(purpose or "") == "book"
        try:
            if is_book:
                pages, _selected = document_service.validate_book(normalized, "")
            else:
                pages = document_service.validate_slides(normalized)
        except document_service.DocumentError as exc:
            if not (is_book and "massimo" in str(exc)):
                return bridge_error(str(exc))
            # Large books are fine: the user narrows them with a page range.
            pages = document_service.count_pages(normalized)
        try:
            size = os.path.getsize(normalized)
        except Exception:
            size = 0
        return bridge_ok(
            file={
                "path": normalized,
                "name": os.path.basename(normalized),
                "size": size,
                "pages": int(pages),
                "format": document_service.file_ext(normalized).lstrip("."),
            }
        )

    def check_path_exists(self, path: str) -> dict:
        """Check whether a persisted source path still exists on disk."""
        normalized_path = str(path or "").strip()
        return bridge_ok(
            exists=bool(normalized_path and os.path.exists(normalized_path))
        )

    def collect_dropped_files(self, names: list) -> dict:
        """Called by JS after postMessageWithAdditionalObjects('FilesDropped') to retrieve OS paths."""
        name_set = {str(n) for n in (names or [])}
        descriptors = []
        for _basename, fullpath in _drain_dnd_paths(name_set):
            if not os.path.isfile(fullpath):
                continue
            ext = os.path.splitext(fullpath)[1].lower()
            if ext in self._ALLOWED_DROP_EXTS:
                descriptors.append(self._build_file_descriptor(fullpath))
            elif ext not in self._KNOWN_NON_MEDIA_EXTS:
                descriptor = self._build_valid_media_descriptor(fullpath)
                if descriptor is not None:
                    descriptors.append(descriptor)
        if descriptors:
            self._adapter.emit("filesDropped", descriptors, batched=False)
        return bridge_ok()

    def _resolve_stream_media_path(
        self, file_path: str, session_dir: str | None = None
    ) -> tuple[str | None, bool, str | None]:
        """Resolve and validate media using the same rules for desktop and browser."""
        resolved_file_path = str(file_path or "").strip()
        has_audio = bool(resolved_file_path)
        if session_dir and (
            not resolved_file_path or not os.path.isfile(resolved_file_path)
        ):
            try:
                abs_dir, session_path = self._resolve_retry_session(str(session_dir))
                data = _load_json(session_path)
                if isinstance(data, dict):
                    input_data = data.get("input", {})
                    if isinstance(input_data, dict):
                        input_p = str(input_data.get("path") or "").strip()
                        input_n = str(input_data.get("name") or "").strip()
                        input_rel = str(
                            input_data.get("path_rel_to_session") or ""
                        ).strip()
                        if input_p or input_n or input_rel:
                            has_audio = True
                    fallback = self._resolve_completed_session_audio_path(
                        data, abs_dir, session_path
                    )
                    if fallback:
                        resolved_file_path = fallback
            except Exception:
                pass
            if not resolved_file_path or not os.path.isfile(resolved_file_path):
                return (
                    None,
                    has_audio,
                    "Nessun file audio trovato per questa sessione.",
                )
        if not resolved_file_path:
            return (
                None,
                has_audio,
                "Nessun file audio trovato per questa sessione.",
            )
        ext = os.path.splitext(resolved_file_path)[1].lower()
        if ext in self._SLIDES_EXTS:
            # "Slide e appunti" sessions: the source is a document, not audio.
            return None, False, "Appunti generati da slide: nessun audio."
        if ext not in self._ALLOWED_STREAM_EXTS:
            if ext in self._KNOWN_NON_MEDIA_EXTS:
                return None, has_audio, "Tipo di file non supportato per lo streaming."
            ok, _err, _dur = self._validate_media_path(
                resolved_file_path, require_duration=True
            )
            if not ok:
                return None, has_audio, "Tipo di file non supportato per lo streaming."
        return resolved_file_path, True, None

    def stream_media_file(self, file_path: str, session_dir: str | None = None) -> dict:
        """Avvia o riavvia un micro-server HTTP per inviare l'audio nativo a React via streaming byte-range."""
        resolved_file_path, has_audio, error = self._resolve_stream_media_path(
            file_path, session_dir
        )
        if not resolved_file_path:
            return bridge_error(
                error or "Nessun file audio trovato.", has_audio=has_audio
            )
        try:
            return bridge_ok(
                url=LocalMediaServer.stream_url_for_file(resolved_file_path),
                has_audio=True,
            )
        except Exception as e:
            return bridge_error(e)
