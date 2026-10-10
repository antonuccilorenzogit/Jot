"""
End-to-end integration tests for the jot pipeline.

Exercises the real execution lifecycle:
  synthetic WAV generation -> real FFmpeg probe & pre-conversion -> chunk cut
  -> mocked Gemini transport -> atomic session persistence -> final HTML export.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import struct
import tempfile
import threading
import unittest
import wave
from unittest.mock import MagicMock, patch

from jot.pipeline.pipeline import esegui_sbobinatura
from jot.pipeline.pipeline_adapter import PipelineAdapter


def _generate_synthetic_wav(
    filepath: str,
    duration_sec: float = 2.0,
    sample_rate: int = 16000,
    freq: float = 440.0,
) -> str:
    """Generate a valid PCM 16-bit mono WAV audio file with a test tone."""
    total_frames = int(sample_rate * duration_sec)
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(total_frames):
            val = int(32767.0 * 0.5 * math.sin(2.0 * math.pi * freq * i / sample_rate))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(frames)
    return filepath


class MockGeminiResponse:
    """Minimal mock response conforming to extract_response_text."""

    def __init__(self, text: str):
        self.text = text


class PipelineSyntheticE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.wav_path = os.path.join(self.temp_dir, "synthetic_lesson.wav")
        self.session_dir = os.path.join(self.temp_dir, "session")
        os.makedirs(self.session_dir, exist_ok=True)

        # Generate a real 2-second WAV file
        _generate_synthetic_wav(self.wav_path, duration_sec=2.0)

        self.mock_window = MagicMock()
        self.cancel_event = threading.Event()
        self.adapter = PipelineAdapter(
            window=self.mock_window, cancel_event=self.cancel_event
        )

        def auto_answer_regenerate(filename, callback, mode="resume", session_dir=""):
            callback({"regenerate": False})

        self.adapter.ask_regenerate = auto_answer_regenerate

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _build_mock_client(self, transcript_text: str | None = None) -> MagicMock:
        client = MagicMock()
        client.api_key = "test-synthetic-key"
        client.models.get.return_value = {"model": "gemini-2.5-flash"}

        default_text = (
            "# Sintesi della Lezione Sintetica\n\n"
            "Questa lezione introduce i concetti chiave di complessita' computazionale.\n\n"
            "## Notazione Asintotica\n\n"
            "La notazione O-grande descrive il limite superiore asintotico.\n\n"
            "* O(1): tempo costante\n"
            "* O(n): tempo lineare\n"
            "* O(n log n): tempo logaritmico-lineare\n\n"
            "## Considerazioni Pratiche\n\n"
            "Gli algoritmi con tempo quadratico vanno evitati per grandi dataset."
        )

        resp = MockGeminiResponse(transcript_text or default_text)
        client.models.generate_content.return_value = resp
        return client

    def test_full_pipeline_synthetic_audio_e2e(self):
        """Verify the full pipeline lifecycle with real FFmpeg and mocked Gemini."""
        mock_client = self._build_mock_client()

        with patch("google.genai.Client", return_value=mock_client):
            esegui_sbobinatura(
                input_path=self.wav_path,
                api_key_value="test-synthetic-key",
                app_instance=self.adapter,
                session_dir_hint=self.session_dir,
            )

        # 1. Verify adapter run status
        self.assertEqual(self.adapter.last_run_status, "completed")
        self.assertIsNone(self.adapter.last_run_error)
        self.assertIsNotNone(self.adapter.last_output_html)
        assert self.adapter.last_output_html is not None
        self.assertTrue(os.path.exists(self.adapter.last_output_html))

        # 2. Verify window evaluate_js was dispatched
        self.assertGreater(self.mock_window.evaluate_js.call_count, 0)

        # 3. Verify session.json persistence and stage
        session_json_path = os.path.join(self.session_dir, "session.json")
        self.assertTrue(os.path.exists(session_json_path))
        with open(session_json_path, encoding="utf-8") as f:
            session_data = json.load(f)

        self.assertEqual(session_data.get("stage"), "done")
        self.assertIn("outputs", session_data)
        self.assertEqual(
            os.path.normpath(session_data["outputs"].get("html")),
            os.path.normpath(self.adapter.last_output_html),
        )

        # 4. Verify metrics were tracked
        self.assertIn("metrics", session_data)
        metrics = session_data["metrics"]
        self.assertIn("chunks", metrics)
        self.assertIn("macro", metrics)

        # 5. Verify chunk files and revision files exist on disk
        phase1_dir = os.path.join(self.session_dir, "phase1_chunks")
        self.assertTrue(os.path.exists(phase1_dir))
        phase1_files = os.listdir(phase1_dir)
        self.assertGreater(len(phase1_files), 0)
        self.assertTrue(
            any(f.startswith("chunk_") and f.endswith(".md") for f in phase1_files)
        )

        phase2_dir = os.path.join(self.session_dir, "phase2_revised")
        self.assertTrue(os.path.exists(phase2_dir))
        phase2_files = os.listdir(phase2_dir)
        self.assertGreater(len(phase2_files), 0)
        self.assertTrue(
            any(f.startswith("rev_") and f.endswith(".md") for f in phase2_files)
        )

        # 6. Verify exported HTML content is well-formed and sanitized
        with open(self.adapter.last_output_html, encoding="utf-8") as f:
            html_content = f.read()

        self.assertIn("<!DOCTYPE html>", html_content)
        self.assertIn("<title>", html_content)
        self.assertIn("Notazione Asintotica", html_content)
        self.assertIn("tempo costante", html_content)
        # Verify Content Security Policy header exists in generated HTML document
        self.assertIn("Content-Security-Policy", html_content)

    def test_pipeline_synthetic_audio_resume_from_phase1(self):
        """Verify that a session with completed Phase 1 can be resumed into Phase 2."""
        mock_client = self._build_mock_client()

        # Step 1: Run complete Phase 1 and stop before phase 2
        # We simulate this by running normally first
        with patch("google.genai.Client", return_value=mock_client):
            esegui_sbobinatura(
                input_path=self.wav_path,
                api_key_value="test-synthetic-key",
                app_instance=self.adapter,
                session_dir_hint=self.session_dir,
            )

        # Step 2: Now reset stage to 'phase2' and remove outputs to test resume
        session_json_path = os.path.join(self.session_dir, "session.json")
        with open(session_json_path, encoding="utf-8") as f:
            session_data = json.load(f)

        session_data["stage"] = "phase2"
        session_data.pop("html_exported", None)
        session_data["outputs"] = {}
        with open(session_json_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f)

        # Re-run with resume_session=True
        new_adapter = PipelineAdapter(
            window=self.mock_window, cancel_event=threading.Event()
        )

        def auto_answer_regenerate(filename, callback, mode="resume", session_dir=""):
            callback({"regenerate": False})

        new_adapter.ask_regenerate = auto_answer_regenerate
        with patch("google.genai.Client", return_value=mock_client):
            esegui_sbobinatura(
                input_path=self.wav_path,
                api_key_value="test-synthetic-key",
                app_instance=new_adapter,
                session_dir_hint=self.session_dir,
                resume_session=True,
            )

        self.assertEqual(new_adapter.last_run_status, "completed")
        self.assertIsNotNone(new_adapter.last_output_html)
        assert new_adapter.last_output_html is not None
        self.assertTrue(os.path.exists(new_adapter.last_output_html))
