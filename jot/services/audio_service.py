"""
Audio workflow helpers for jot.

This module centralizes the FFmpeg-facing operations used by the pipeline and
the WebView bridge so those call sites stay smaller and easier to test.
"""

from __future__ import annotations

from jot.utils.ffmpeg_utils import (
    cut_chunk_to_mp3,
    get_ffmpeg_exe,
    preconvert_to_mono16k_mp3,
    probe_duration_seconds,
)


def resolve_ffmpeg() -> str:
    return get_ffmpeg_exe()


def probe_media_duration(
    path: str, ffmpeg_exe: str | None = None
) -> tuple[float | None, str | None]:
    return probe_duration_seconds(path, ffmpeg_exe=ffmpeg_exe)


def preconvert_media_to_mp3(
    input_path: str,
    output_path: str,
    bitrate: str = "48k",
    ffmpeg_exe: str | None = None,
    stop_event=None,
):
    return preconvert_to_mono16k_mp3(
        input_path=input_path,
        output_path=output_path,
        bitrate=bitrate,
        ffmpeg_exe=ffmpeg_exe,
        stop_event=stop_event,
    )


def cut_audio_chunk_to_mp3(
    input_path: str,
    output_path: str,
    start_sec: int,
    duration_sec: int | float,
    bitrate: str = "48k",
    ffmpeg_exe: str | None = None,
    stream_copy: bool = False,
    stop_event=None,
):
    return cut_chunk_to_mp3(
        input_path=input_path,
        output_path=output_path,
        start_sec=start_sec,
        duration_sec=duration_sec,
        bitrate=bitrate,
        ffmpeg_exe=ffmpeg_exe,
        stream_copy=stream_copy,
        stop_event=stop_event,
    )
