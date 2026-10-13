"""
Session/bootstrap helpers for the main pipeline.

These helpers isolate autosave, resume, pre-conversion and per-phase metadata so
the core generation loop can stay focused on the Gemini workflow.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

from jot.core.session_store import (
    SessionCollisionError,
    SessionPaths,
    ensure_session_dirs,
    migrate_session,
    new_session,
    reset_session_dirs,
    resolve_session_paths,
)
from jot.core.session_store import (
    load_session as load_saved_session,
)
from jot.core.session_store import (
    save_session as save_session_data,
)
from jot.core.shared import (
    PRECONVERTED_AUDIO_FINAL,
    PRECONVERTED_AUDIO_PARTIAL,
    invalidate_session_storage_cache,
)
from jot.pipeline.pipeline_settings import (
    PipelineSettings,
    build_default_pipeline_settings,
    load_and_sanitize_settings,
)
from jot.services.audio_service import preconvert_media_to_mp3
from jot.services.config_service import load_config

CHUNK_MD_RE = re.compile(r"^chunk_(\d{3})_(\d+)_(\d+)\.md$", re.IGNORECASE)
ChunkEntry = tuple[int, int, int, str]


class AutosaveFailedError(BaseException):
    """Raised by SaveSessionGuard when session autosave fails consecutively."""


class SaveSessionGuard:
    """Wraps a save callable and raises AutosaveFailedError after THRESHOLD consecutive failures.

    Tracks consecutive save failures.  On the first failure it returns ``False``
    silently (existing behaviour).  After *THRESHOLD* consecutive failures it
    calls *on_fatal* with a descriptive message, sets an internal fatal flag so
    that every subsequent call also raises immediately (without attempting the
    underlying save again), and then raises ``AutosaveFailedError``.
    """

    THRESHOLD: int = 5
    BACKOFF_DELAYS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0)

    def __init__(
        self,
        save_fn: Callable[[], bool],
        on_fatal: Callable[[str], None],
        sleep_fn: Callable[[float], None] = time.sleep,
        backoff_delays: tuple[float, ...] = BACKOFF_DELAYS,
    ) -> None:
        self._save_fn = save_fn
        self._on_fatal = on_fatal
        self._sleep_fn = sleep_fn
        self._backoff_delays = backoff_delays
        self._consecutive_failures: int = 0
        self._fatal: bool = False

    def __call__(self) -> bool:
        if self._fatal:
            raise AutosaveFailedError("autosave_failed")
        ok = self._save_fn()
        if ok:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.THRESHOLD:
                self._fatal = True
                msg = (
                    f"[!!] ERRORE CRITICO: autosalvataggio sessione fallito "
                    f"{self.THRESHOLD} volte di seguito. "
                    "Disco pieno o directory non scrivibile? Elaborazione interrotta."
                )
                self._on_fatal(msg)
                raise AutosaveFailedError("autosave_failed")
            delay_idx = min(
                self._consecutive_failures - 1, len(self._backoff_delays) - 1
            )
            delay = self._backoff_delays[delay_idx] if self._backoff_delays else 0.0
            if delay > 0:
                self._sleep_fn(delay)
        return ok


@dataclass
class PipelineSessionContext:
    input_path: str
    session_dir_hint: str | None
    resume_session: bool
    session_paths: SessionPaths
    session: dict
    settings: PipelineSettings
    settings_changed: bool

    @property
    def session_dir(self) -> str:
        return self.session_paths.session_dir

    @property
    def session_path(self) -> str:
        return self.session_paths.session_path

    @property
    def phase1_chunks_dir(self) -> str:
        return self.session_paths.phase1_chunks_dir

    @property
    def phase2_revised_dir(self) -> str:
        return self.session_paths.phase2_revised_dir

    @property
    def macro_path(self) -> str:
        return self.session_paths.macro_path

    def save(self) -> bool:
        try:
            save_session_data(self.session_path, self.session)
            return True
        except Exception as exc:
            print(f"   [!] Autosave sessione fallito: {exc}")
            return False


@dataclass(frozen=True)
class Phase1RestoreState:
    existing_chunks: list[ChunkEntry]
    start_sec: int
    full_transcript: str
    prev_memory: str


def read_text_file(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def list_phase1_chunks(phase1_chunks_dir: str) -> list[ChunkEntry]:
    items: list[ChunkEntry] = []
    try:
        for name in os.listdir(phase1_chunks_dir):
            match = CHUNK_MD_RE.match(name)
            if not match:
                continue
            idx = int(match.group(1))
            start_sec = int(match.group(2))
            end_sec = int(match.group(3))
            items.append(
                (idx, start_sec, end_sec, os.path.join(phase1_chunks_dir, name))
            )
    except Exception:
        return []
    return sorted(items, key=lambda item: (item[0], item[1], item[2]))


def load_phase1_text(phase1_chunks_dir: str) -> str:
    parts: list[str] = []
    for _, _, _, path in list_phase1_chunks(phase1_chunks_dir):
        try:
            text = read_text_file(path).strip()
        except Exception:
            continue
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def initialize_session_context(
    input_path: str,
    session_dir_hint: str | None = None,
    resume_session: bool = False,
    allow_completed_destroy: bool = False,
) -> PipelineSessionContext:
    session_paths = resolve_session_paths(input_path, session_dir_hint=session_dir_hint)

    if not resume_session and os.path.exists(session_paths.session_dir):
        # SessionCollisionError is intentionally allowed to propagate: callers
        # must decide how to handle an attempted overwrite of a completed session.
        try:
            reset_session_dirs(
                session_paths, allow_completed_destroy=allow_completed_destroy
            )
        except SessionCollisionError:
            raise
        except Exception:
            pass
    else:
        try:
            ensure_session_dirs(session_paths)
        except Exception:
            pass

    session = None
    _migrated = False
    if resume_session and os.path.exists(session_paths.session_path):
        try:
            session = load_saved_session(session_paths.session_path)
        except Exception:
            session = None

    if session is None:
        session = new_session(input_path)
        try:
            save_session_data(session_paths.session_path, session)
        except Exception:
            pass
    else:
        session, _migrated = migrate_session(session)
        try:
            current_defaults = build_default_pipeline_settings(load_config())
            if not isinstance(session.get("settings"), dict):
                session["settings"] = {}
            # If this is a resume of an empty/cancelled session with no chunks transcribed yet,
            # update its model settings to match the user's current configuration preferences.
            # This ensures that changing preferred model after a cancel/immediate stop is honored.
            is_phase1 = str(session.get("stage", "phase1")).strip().lower() == "phase1"
            phase1_state = session.get("phase1") or {}
            chunks_done = int(phase1_state.get("chunks_done", 0) or 0)
            if is_phase1 and chunks_done == 0:
                session["settings"]["model"] = current_defaults["model"]
                session["settings"]["fallback_models"] = current_defaults[
                    "fallback_models"
                ]
                session["settings"]["effective_model"] = current_defaults[
                    "effective_model"
                ]
                session["settings"]["chunk_minutes"] = current_defaults["chunk_minutes"]
                session["settings"]["macro_char_limit"] = current_defaults[
                    "macro_char_limit"
                ]
            else:
                # Work already done: the block length stays (the saved blocks must keep
                # lining up), but the models are the ones chosen now in the settings,
                # so changing model also applies to a lesson that is resumed.
                session["settings"]["model"] = current_defaults["model"]
                session["settings"]["fallback_models"] = current_defaults[
                    "fallback_models"
                ]
                session["settings"]["effective_model"] = current_defaults[
                    "effective_model"
                ]
        except Exception:
            pass

    settings, settings_changed = load_and_sanitize_settings(session)
    context = PipelineSessionContext(
        input_path=input_path,
        session_dir_hint=session_dir_hint,
        resume_session=resume_session,
        session_paths=session_paths,
        session=session,
        settings=settings,
        settings_changed=settings_changed,
    )
    if settings_changed or _migrated:
        context.save()
    return context


def normalize_stage(session: dict) -> str:
    stage = str(session.get("stage", "phase1")).strip().lower()
    if stage not in ("phase1", "phase2", "boundary", "done"):
        stage = "phase1"
        session["stage"] = "phase1"
    return stage


def phase1_has_progress(
    session: dict, stage: str, existing_chunks: list[ChunkEntry]
) -> bool:
    phase1_state = (
        session.get("phase1", {}) if isinstance(session.get("phase1"), dict) else {}
    )
    outputs_state = (
        session.get("outputs", {}) if isinstance(session.get("outputs"), dict) else {}
    )
    return (
        stage != "phase1"
        or bool(existing_chunks)
        or int(phase1_state.get("chunks_done", 0) or 0) > 0
        or int(phase1_state.get("next_start_sec", 0) or 0) > 0
        or bool(str(outputs_state.get("html") or "").strip())
    )


def reset_for_regeneration(context: PipelineSessionContext) -> None:
    try:
        reset_session_dirs(context.session_paths, allow_completed_destroy=True)
    except Exception:
        pass
    fresh_settings = build_default_pipeline_settings(load_config())
    context.session = new_session(context.input_path, settings=fresh_settings)
    context.settings, context.settings_changed = load_and_sanitize_settings(
        context.session
    )
    context.save()


def persist_phase1_metadata(
    context: PipelineSessionContext, duration_seconds: float, step_seconds: int
) -> None:
    context.session.setdefault("phase1", {})
    context.session["phase1"]["duration_seconds"] = float(duration_seconds)
    context.session["phase1"]["step_seconds"] = int(step_seconds)
    context.save()


def restore_phase1_progress(
    context: PipelineSessionContext, stage: str, step_seconds: int
) -> Phase1RestoreState:
    session = context.session
    existing_chunks = list_phase1_chunks(context.phase1_chunks_dir)
    start_sec = int(session.get("phase1", {}).get("next_start_sec", 0) or 0)

    if existing_chunks:
        try:
            last_start = max(start for _, start, _, _ in existing_chunks)
            start_sec = max(start_sec, int(last_start + step_seconds))
        except Exception:
            pass
        full_transcript = load_phase1_text(context.phase1_chunks_dir)
        try:
            _, _, _, last_path = existing_chunks[-1]
            prev_memory = read_text_file(last_path).strip()[-2000:]
        except Exception:
            prev_memory = full_transcript[-2000:]
    elif stage != "phase1":
        full_transcript = load_phase1_text(context.phase1_chunks_dir)
        prev_memory = full_transcript[-2000:]
    else:
        full_transcript = ""
        prev_memory = str(session.get("phase1", {}).get("memoria_precedente", "") or "")

    return Phase1RestoreState(
        existing_chunks=existing_chunks,
        start_sec=start_sec,
        full_transcript=full_transcript,
        prev_memory=prev_memory,
    )


def ensure_preconverted_audio(
    context: PipelineSessionContext,
    input_path: str,
    stage: str,
    ffmpeg_exe: str,
    cancel_event,
    cancelled,
    phase_callback,
) -> tuple[bool, str | None]:
    preconv_enabled = bool(context.settings.preconvert_audio)
    preconv_path = os.path.join(context.session_dir, PRECONVERTED_AUDIO_FINAL)
    partial_path = os.path.join(context.session_dir, PRECONVERTED_AUDIO_PARTIAL)
    if not preconv_enabled or stage != "phase1":
        return preconv_enabled, None

    def _cleanup_partial() -> None:
        try:
            if os.path.exists(partial_path):
                os.remove(partial_path)
        except Exception:
            pass

    try:
        if os.path.exists(preconv_path) and os.path.getsize(preconv_path) > 1024:
            print("[*] Pre-conversione: file gia' presente. Riutilizzo.")
            return preconv_enabled, preconv_path
    except Exception:
        pass

    _cleanup_partial()

    phase_callback("Fase 0/3: pre-conversione audio")
    print("[*] Pre-conversione unica dell'audio (mono, 16kHz) in corso...")
    ok, err = preconvert_media_to_mp3(
        input_path=input_path,
        output_path=partial_path,
        bitrate=str(context.settings.audio_bitrate or "48k"),
        ffmpeg_exe=ffmpeg_exe,
        stop_event=cancel_event,
    )
    if not ok:
        _cleanup_partial()
        if str(err or "").strip().lower() == "cancelled" or cancelled():
            print("   [*] Operazione annullata dall'utente.")
            return preconv_enabled, None
        print("[!] Pre-conversione fallita. Continuo senza pre-conversione.")
        if err:
            print(err)
        return False, None

    try:
        if os.path.exists(partial_path) and os.path.getsize(partial_path) > 1024:
            os.replace(partial_path, preconv_path)
            print("[*] Pre-conversione completata.")
            context.session.setdefault("phase1", {})
            context.session["phase1"]["preconverted_path"] = preconv_path
            context.session["phase1"]["preconverted_done"] = True
            context.save()
            invalidate_session_storage_cache()
            return preconv_enabled, preconv_path
    except Exception:
        _cleanup_partial()
    return False, None


def _parse_bitrate_bps(audio_bitrate: str) -> float:
    """Parse a bitrate string like '48k', '128k', '1.5m' to bits per second."""
    raw = str(audio_bitrate or "48k").lower().strip()
    try:
        if raw.endswith("k"):
            bps = float(raw[:-1]) * 1_000
        elif raw.endswith("m"):
            bps = float(raw[:-1]) * 1_000_000
        else:
            bps = float(raw)
        if bps <= 0:
            raise ValueError("non-positive")
    except (ValueError, AttributeError):
        bps = 48_000.0
    return bps


def _fmt_bytes(n: int) -> str:
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.1f} GB"
    return f"{n / 1_048_576:.0f} MB"


def _disk_usage_target(path: str) -> str:
    current = os.path.abspath(path or tempfile.gettempdir())
    while current and not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return current if current and os.path.exists(current) else tempfile.gettempdir()


@dataclass(frozen=True)
class DiskSpaceEstimate:
    needed_bytes: int
    free_bytes: int
    location: str
    kind: str

    @property
    def is_clearly_insufficient(self) -> bool:
        return self.needed_bytes > 0 and self.free_bytes < int(self.needed_bytes * 0.9)


def estimate_disk_space(
    session_dir: str,
    total_duration_sec: float,
    settings: PipelineSettings,
    stage: str,
    next_start_sec: int = 0,
) -> list[DiskSpaceEstimate]:
    if stage != "phase1":
        return []

    bytes_per_sec = _parse_bitrate_bps(settings.audio_bitrate) / 8.0

    session_needed = 0
    if settings.preconvert_audio:
        preconv_path = os.path.join(session_dir, PRECONVERTED_AUDIO_FINAL)
        if not os.path.exists(preconv_path):
            session_needed = int(total_duration_sec * bytes_per_sec)

    concurrent_chunks = 2 if settings.prefetch_next_chunk else 1
    remaining_duration = max(0.0, total_duration_sec - next_start_sec)
    if remaining_duration > 0:
        remaining_chunks = math.ceil(remaining_duration / settings.chunk_seconds)
        effective_concurrent = min(concurrent_chunks, remaining_chunks)
    else:
        effective_concurrent = 0
    temp_needed = int(settings.chunk_seconds * bytes_per_sec) * effective_concurrent

    tmp_dir = tempfile.gettempdir()
    session_usage_dir = _disk_usage_target(session_dir)
    try:
        same_fs = os.stat(session_usage_dir).st_dev == os.stat(tmp_dir).st_dev
    except Exception:
        same_fs = True

    estimates: list[DiskSpaceEstimate] = []
    if same_fs:
        total_needed = session_needed + temp_needed
        if total_needed == 0:
            return []
        try:
            free = shutil.disk_usage(session_usage_dir).free
        except Exception:
            return []
        estimates.append(
            DiskSpaceEstimate(
                needed_bytes=total_needed,
                free_bytes=free,
                location=session_dir,
                kind="combined",
            )
        )
        return estimates

    if session_needed > 0:
        try:
            free_sess = shutil.disk_usage(session_usage_dir).free
            estimates.append(
                DiskSpaceEstimate(
                    needed_bytes=session_needed,
                    free_bytes=free_sess,
                    location=session_dir,
                    kind="session",
                )
            )
        except Exception:
            pass
    if temp_needed > 0:
        try:
            free_tmp = shutil.disk_usage(tmp_dir).free
            estimates.append(
                DiskSpaceEstimate(
                    needed_bytes=temp_needed,
                    free_bytes=free_tmp,
                    location=tmp_dir,
                    kind="temp",
                )
            )
        except Exception:
            pass
    return estimates


def check_disk_space(
    session_dir: str,
    total_duration_sec: float,
    settings: PipelineSettings,
    stage: str,
    next_start_sec: int = 0,
) -> None:
    """Probe available disk space and print a warning if estimated usage may exceed free space.

    Only active when stage == 'phase1'. Never raises — warnings only.
    """
    for estimate in estimate_disk_space(
        session_dir,
        total_duration_sec,
        settings,
        stage,
        next_start_sec,
    ):
        if estimate.free_bytes >= estimate.needed_bytes:
            continue
        if estimate.kind == "combined":
            print(
                f"[!] ATTENZIONE — Spazio su disco potenzialmente insufficiente.\n"
                f"    Stimato necessario (audio pre-convertito + chunk temporanei): ~{_fmt_bytes(estimate.needed_bytes)}\n"
                f"    Disponibile: {_fmt_bytes(estimate.free_bytes)}\n"
                f"    Libera spazio prima di continuare per evitare errori durante l'elaborazione."
            )
        elif estimate.kind == "session":
            print(
                f"[!] ATTENZIONE — Spazio insufficiente per la pre-conversione audio.\n"
                f"    Stimato: ~{_fmt_bytes(estimate.needed_bytes)} · Disponibile in {estimate.location}: {_fmt_bytes(estimate.free_bytes)}\n"
                f"    Libera spazio prima di continuare."
            )
        else:
            print(
                f"[!] ATTENZIONE — Spazio insufficiente nella cartella temporanea ({estimate.location}).\n"
                f"    Stimato per i chunk audio: ~{_fmt_bytes(estimate.needed_bytes)} · Disponibile: {_fmt_bytes(estimate.free_bytes)}\n"
                f"    Libera spazio prima di continuare."
            )


def record_step_metric(
    session: dict | None,
    kind: str,
    seconds: float,
    done: int | None = None,
    total: int | None = None,
) -> None:
    if not isinstance(session, dict):
        return

    metrics = session.setdefault("metrics", {})
    entry = metrics.setdefault(
        str(kind or "unknown"),
        {
            "count": 0,
            "elapsed_seconds": 0.0,
            "last_seconds": 0.0,
            "done": 0,
            "total": 0,
        },
    )

    try:
        value = max(0.0, float(seconds))
    except Exception:
        value = 0.0

    if value > 0:
        entry["count"] = int(entry.get("count", 0) or 0) + 1
        entry["elapsed_seconds"] = (
            float(entry.get("elapsed_seconds", 0.0) or 0.0) + value
        )
        entry["last_seconds"] = value
        entry["avg_seconds"] = entry["elapsed_seconds"] / max(1, entry["count"])

    if done is not None:
        entry["done"] = int(done)
    if total is not None:
        entry["total"] = int(total)
