"""Tests for jot.services.audio_service."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestAudioService(unittest.TestCase):
    @patch("jot.services.audio_service.get_ffmpeg_exe")
    def test_resolve_ffmpeg(self, mock_get):
        mock_get.return_value = "ffmpeg"
        from jot.services.audio_service import resolve_ffmpeg

        res = resolve_ffmpeg()
        self.assertEqual(res, "ffmpeg")
        mock_get.assert_called_once()

    @patch("jot.services.audio_service.probe_duration_seconds")
    def test_probe_media_duration(self, mock_probe):
        mock_probe.return_value = (12.5, None)
        from jot.services.audio_service import probe_media_duration

        res = probe_media_duration("test.mp3", ffmpeg_exe="ffmpeg")
        self.assertEqual(res, (12.5, None))
        mock_probe.assert_called_once_with("test.mp3", ffmpeg_exe="ffmpeg")

    @patch("jot.services.audio_service.preconvert_to_mono16k_mp3")
    def test_preconvert_media_to_mp3(self, mock_preconvert):
        mock_preconvert.return_value = "out.mp3"
        from jot.services.audio_service import preconvert_media_to_mp3

        res = preconvert_media_to_mp3("in.mp4", "out.mp3", bitrate="64k")
        self.assertEqual(res, "out.mp3")
        mock_preconvert.assert_called_once_with(
            input_path="in.mp4",
            output_path="out.mp3",
            bitrate="64k",
            ffmpeg_exe=None,
            stop_event=None,
        )

    @patch("jot.services.audio_service.cut_chunk_to_mp3")
    def test_cut_audio_chunk_to_mp3(self, mock_cut):
        mock_cut.return_value = "chunk.mp3"
        from jot.services.audio_service import cut_audio_chunk_to_mp3

        res = cut_audio_chunk_to_mp3("in.mp3", "chunk.mp3", 0, 10)
        self.assertEqual(res, "chunk.mp3")
        mock_cut.assert_called_once_with(
            input_path="in.mp3",
            output_path="chunk.mp3",
            start_sec=0,
            duration_sec=10,
            bitrate="48k",
            ffmpeg_exe=None,
            stream_copy=False,
            stop_event=None,
        )


if __name__ == "__main__":
    unittest.main()
