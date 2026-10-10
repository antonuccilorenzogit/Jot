"""
Offline smoke test for jot.

Runs the full pipeline end-to-end without calling real Gemini:
- Generates a short synthetic MP3 via FFmpeg (imageio-ffmpeg)
- Monkeypatches jot.pipeline.pipeline.genai with a fake client
- Verifies autosave artifacts and final HTML output

Usage:
  python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import imageio_ffmpeg

# Allow running as `python scripts/smoke_test.py` from the repo root.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import jot.pipeline.pipeline as pipe


class DummyResponse:
    def __init__(self, text: str):
        self.text = text


class FakeModels:
    def get(self, model=None, **kwargs):
        return {"model": model}

    def generate_content(self, model=None, contents=None, config=None, **kwargs):
        # Small delay so FFmpeg prefetch has time to overlap.
        time.sleep(0.2)
        md = (
            "## Titolo di prova\n\n"
            "Questo è un contenuto di test generato dal client finto. "
            "Serve solo per verificare che la pipeline (chunk → macro → HTML) funzioni.\n\n"
            "- **Punto:** Spiegazione completa in testo normale.\n"
        )
        return DummyResponse(md)


class FakeFiles:
    def upload(self, *args, **kwargs):
        raise RuntimeError(
            "Upload non previsto nello smoke test (dovrebbe usare inline audio)."
        )


class FakeClient:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.models = FakeModels()
        self.files = FakeFiles()


class DummyApp:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.file_temporanei: list[str] = []

    def winfo_exists(self):
        return False

    def after(self, *args, **kwargs):
        return None


def make_test_mp3(path: str, seconds: int = 65) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=880:duration={int(seconds)}",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "48k",
        path,
    ]
    subprocess.check_call(cmd)


def main() -> int:
    root = tempfile.mkdtemp(prefix="jot_smoke_")
    try:
        mp3_path = os.path.join(root, "test_audio.mp3")
        make_test_mp3(mp3_path, seconds=130)

        # Monkeypatch: avoid network + write outputs inside the temp dir
        pipe.genai.Client = FakeClient
        pipe.get_desktop_dir = lambda: root  # type: ignore[attr-defined]

        # Precreate a session with small chunks to exercise multiple iterations (and FFmpeg prefetch).
        session_dir = os.path.join(root, "session")
        os.makedirs(session_dir, exist_ok=True)
        session_path = os.path.join(session_dir, "session.json")
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "schema_version": 1,
                    "stage": "phase1",
                    "settings": {
                        "chunk_minutes": 1,
                        "overlap_seconds": 5,
                        "macro_char_limit": 8000,
                        "preconvert_audio": True,
                        "prefetch_next_chunk": True,
                        "inline_audio_max_mb": 6,
                        "audio": {"bitrate": "48k"},
                    },
                    "phase1": {
                        "next_start_sec": 0,
                        "chunks_done": 0,
                        "memoria_precedente": "",
                    },
                    "phase2": {},
                    "boundary": {},
                    "outputs": {},
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        ok = True
        try:
            pipe.esegui_sbobinatura(
                mp3_path,
                "fake_key",
                DummyApp(),
                session_dir_hint=session_dir,
                resume_session=True,
            )
        except Exception as e:
            ok = False
            print("SMOKE_EXCEPTION:", repr(e))

        must_exist = [
            os.path.join(session_dir, "session.json"),
            os.path.join(session_dir, "phase1_chunks"),
            os.path.join(session_dir, "phase2_revised"),
        ]
        for p in must_exist:
            if not os.path.exists(p):
                ok = False
                print("MISSING:", p)

        htmls = [
            fname
            for dirpath, _dirs, files in os.walk(root)
            for fname in files
            if fname.lower().endswith(".html")
        ]
        if not htmls:
            ok = False
            print("MISSING: html output")

        print("smoke_ok=", ok)
        return 0 if ok else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
