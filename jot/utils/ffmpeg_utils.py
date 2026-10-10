"""
FFmpeg helpers used by both UI and pipeline.

Centralizza:
- probe durata (Duration) in modo robusto
- pre-conversione audio (mono 16kHz mp3)
- taglio chunk (stream copy da preconvertito oppure re-encode da file originale)
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
import time

import imageio_ffmpeg


@functools.lru_cache(maxsize=1)
def get_ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _is_cancelled(stop_event) -> bool:
    try:
        return stop_event is not None and bool(stop_event.is_set())
    except Exception:
        return False


def _run_cancellable(cmd, *, stop_event=None) -> tuple[int, str, str, bool]:
    """
    Runs a subprocess, periodically checking stop_event.
    Returns (returncode, stdout, stderr, was_cancelled).
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        creationflags=_creation_flags(),
    )
    cancelled = False
    out, err = "", ""
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.15)
                break
            except subprocess.TimeoutExpired:
                if _is_cancelled(stop_event):
                    cancelled = True
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    # Give a short grace period then hard kill.
                    t0 = time.time()
                    while proc.poll() is None and (time.time() - t0) < 2.0:
                        time.sleep(0.05)
                    if proc.poll() is None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    try:
                        out, err = proc.communicate(timeout=2)
                    except Exception:
                        out, err = "", ""
                    break
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            out, err = proc.communicate(timeout=2)
        except Exception:
            out, err = "", ""
    return (
        int(getattr(proc, "returncode", 1) or 0),
        str(out or ""),
        str(err or ""),
        bool(cancelled),
    )


def probe_duration_seconds(
    path: str, ffmpeg_exe: str | None = None
) -> tuple[float | None, str | None]:
    """
    Returns (seconds, reason).
    - seconds: float if parsed, else None
    - reason: short debug reason if seconds is None
    """
    try:
        p = os.path.abspath(str(path or "").strip())
        if not p or not os.path.exists(p):
            return None, "file_non_trovato"

        exe = ffmpeg_exe or get_ffmpeg_exe()
        res = subprocess.run(
            [exe, "-hide_banner", "-i", p],
            capture_output=True,
            creationflags=_creation_flags(),
            timeout=15,
        )
        raw = (res.stderr or b"") + b"\n" + (res.stdout or b"")
        try:
            out = raw.decode("utf-8", errors="replace")
        except Exception:
            out = raw.decode(errors="replace")

        if "Duration: N/A" in out:
            return None, "duration_NA"

        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:[.,]\d+)?)", out)
        if not m:
            tail = "\n".join([ln for ln in (out or "").splitlines() if ln.strip()][-6:])
            reason = (
                tail.strip()
                or f"ffmpeg_returncode_{getattr(res, 'returncode', 'unknown')}"
            )
            return None, reason
        h = float(m.group(1))
        mi = float(m.group(2))
        se = float(m.group(3).replace(",", "."))
        return (h * 3600.0) + (mi * 60.0) + se, None
    except Exception:
        return None, "eccezione_ffmpeg"


def preconvert_to_mono16k_mp3(
    *,
    input_path: str,
    output_path: str,
    bitrate: str = "48k",
    ffmpeg_exe: str | None = None,
    stop_event=None,
) -> tuple[bool, str | None]:
    exe = ffmpeg_exe or get_ffmpeg_exe()
    cmd = [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        str(bitrate or "48k"),
        "-map",
        "a:0",
        "-f",
        "mp3",
        output_path,
    ]
    rc, _out, err, was_cancelled = _run_cancellable(cmd, stop_event=stop_event)
    if was_cancelled:
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return False, "cancelled"
    if rc == 0:
        try:
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return True, None
        except Exception:
            pass
        return False, "preconvert_output_missing"

    stderr = (err or "").strip()
    if stderr:
        stderr = "\n".join(stderr.splitlines()[-12:])
    return False, stderr or "preconvert_failed"


def cut_chunk_to_mp3(
    *,
    input_path: str,
    output_path: str,
    start_sec: float,
    duration_sec: float,
    ffmpeg_exe: str | None = None,
    stream_copy: bool = False,
    bitrate: str = "48k",
    stop_event=None,
) -> tuple[bool, str | None]:
    exe = ffmpeg_exe or get_ffmpeg_exe()
    if stream_copy:
        cmd = [
            exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(start_sec),
            "-t",
            str(duration_sec),
            "-i",
            input_path,
            "-vn",
            "-c:a",
            "copy",
            "-map",
            "a:0",
            "-reset_timestamps",
            "1",
            "-avoid_negative_ts",
            "make_zero",
            output_path,
        ]
    else:
        cmd = [
            exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            input_path,
            "-ss",
            str(start_sec),
            "-t",
            str(duration_sec),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            str(bitrate or "48k"),
            "-map",
            "a:0",
            output_path,
        ]

    rc, _out, err, was_cancelled = _run_cancellable(cmd, stop_event=stop_event)
    if was_cancelled:
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return False, "cancelled"
    if rc == 0:
        try:
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return True, None
        except Exception:
            pass
        return False, "chunk_output_missing"

    stderr = (err or "").strip()
    if stderr:
        stderr = "\n".join(stderr.splitlines()[-12:])
    return False, stderr or "cut_failed"
