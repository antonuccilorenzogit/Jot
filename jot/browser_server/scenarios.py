"""
Deterministic pipeline scenarios for jot browser server.

Allows rapid, offline, reproducible visual and end-to-end testing without
invoking external Gemini APIs or requiring real audio files.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

from jot.bridge.bridge_dispatcher import EventDispatcher
from jot.core.shared import (
    _atomic_write_json,
    _atomic_write_text,
    get_session_root,
)

SAMPLE_HTML_NOTE = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>Fisiologia - Sistema Cardiovascolare</title>
</head>
<body>
<h1>Fisiologia - Sistema Cardiovascolare</h1>
<p>Questa è una lezione simulata per il testing automatico dell'interfaccia e dell'editor TipTap.</p>
<h2>1. Ciclo Cardiaco</h2>
<p>Il ciclo cardiaco si suddivide in due fasi principali: <strong>sistole</strong> e <strong>diastole</strong>.</p>
<blockquote>
<p>La gittata cardiaca è definita come il prodotto tra frequenza cardiaca e volume sistolico:</p>
<p>$$GC = FC \\times VS$$</p>
</blockquote>
<h2>2. Pressioni e Resistenze</h2>
<table border="1">
<thead>
<tr><th>Distretto</th><th>Pressione Media (mmHg)</th><th>Funzione</th></tr>
</thead>
<tbody>
<tr><td>Aorta</td><td>100</td><td>Distribuzione sistemica ad alta pressione</td></tr>
<tr><td>Capillari</td><td>25</td><td>Scambio gassoso e metabolico tissutale</td></tr>
<tr><td>Vena Cava</td><td>2-4</td><td>Ritorno venoso atriale destro</td></tr>
</tbody>
</table>
<p>Tutti i blocchi sono stati revisionati con successo.</p>
</body>
</html>
"""


def run_deterministic_scenario(
    scenario: str,
    dispatcher: EventDispatcher,
    cancel_event: threading.Event,
    file_item: dict[str, Any] | None = None,
    speed_factor: float = 1.0,
    on_session_written: Callable[[], None] | None = None,
) -> None:
    """Execute a simulated scenario emitting real pipeline events."""
    delay = 0.3 * speed_factor
    file_id = str(file_item.get("id") if file_item else "test-file-1")
    file_name = str(file_item.get("name") if file_item else "lezione_fisiologia.mp3")

    session_root = get_session_root()
    session_dir = os.path.join(session_root, "simulated_session")
    os.makedirs(session_dir, exist_ok=True)
    html_path = os.path.join(session_dir, "output.html")

    input_path = str(file_item.get("path") or "") if file_item else ""
    title = file_name.rsplit(".", 1)[0].replace("_", " ").title()
    note_content = SAMPLE_HTML_NOTE.replace(
        "Fisiologia - Sistema Cardiovascolare", title
    )

    _atomic_write_text(html_path, note_content)
    _atomic_write_json(
        os.path.join(session_dir, "session.json"),
        {
            "session_id": "simulated_session",
            "source_file": file_name,
            "title": title,
            "stage": "done",
            "created_at": "2026-09-17T12:00:00Z",
            "updated_at": "2026-09-17T12:05:00Z",
            "input": {
                "path": input_path,
                "size": int(file_item.get("size", 0) if file_item else 0),
            },
            "html_path": html_path,
            "outputs": {"html": html_path},
            "phase1": {"duration_seconds": 3.0},
        },
    )
    if on_session_written is not None:
        on_session_written()

    if scenario == "regenerate":
        dispatcher.emit(
            "askRegenerate",
            {
                "filename": file_name,
                "mode": "completed",
                "sessionDir": session_dir,
            },
            batched=False,
        )
        dispatcher.flush()
        return

    dispatcher.emit("updatePhase", "Inizializzazione simulazione...", batched=False)
    dispatcher.emit(
        "setCurrentFile",
        {"index": 0, "id": file_id, "name": file_name, "total": 1},
        batched=False,
    )
    dispatcher.flush()

    if cancel_event.is_set():
        dispatcher.emit(
            "processDone",
            {"completed": 0, "failed": 0, "cancelled": True},
            batched=False,
        )
        dispatcher.flush()
        return

    time.sleep(delay)
    if cancel_event.is_set():
        dispatcher.emit(
            "processDone",
            {"completed": 0, "failed": 0, "cancelled": True},
            batched=False,
        )
        dispatcher.flush()
        return

    if scenario == "failure":
        dispatcher.emit("updateProgress", 0.35, batched=False)
        time.sleep(delay)
        dispatcher.emit(
            "fileFailed",
            {
                "index": 0,
                "id": file_id,
                "error": "Errore simulato: file audio danneggiato o non leggibile.",
                "error_detail": "FFmpeg exit code 1: Invalid data found when processing input",
            },
            batched=False,
        )
        dispatcher.emit(
            "processDone",
            {"completed": 0, "failed": 1, "cancelled": False},
            batched=False,
        )
        dispatcher.flush()
        return

    if scenario == "quota":
        dispatcher.emit("updateProgress", 0.45, batched=False)
        time.sleep(delay)
        dispatcher.emit("askNewKey", None, batched=False)
        dispatcher.flush()
        return

    if scenario == "paused":
        dispatcher.emit("updateProgress", 0.50, batched=False)
        time.sleep(delay)
        dispatcher.emit(
            "fileFailed",
            {
                "index": 0,
                "id": file_id,
                "error": "Pausa circuit-breaker: troppe richieste consecutive.",
                "retryable": True,
                "retry_reason": "circuit_breaker_paused",
                "recommended_retry_at": "2026-09-17T12:30:00Z",
            },
            batched=False,
        )
        dispatcher.emit(
            "processDone",
            {"completed": 0, "failed": 1, "cancelled": False},
            batched=False,
        )
        dispatcher.flush()
        return

    # Scenario: success
    dispatcher.emit("updateProgress", 0.20, batched=False)
    dispatcher.emit("updatePhase", "Trascrizione chunk 1/2...", batched=False)
    dispatcher.flush()
    time.sleep(delay)

    if cancel_event.is_set():
        dispatcher.emit(
            "processDone",
            {"completed": 0, "failed": 0, "cancelled": True},
            batched=False,
        )
        dispatcher.flush()
        return

    dispatcher.emit("updateProgress", 0.60, batched=False)
    dispatcher.emit("updatePhase", "Revisione macro-blocchi...", batched=False)
    dispatcher.flush()
    time.sleep(delay)

    if cancel_event.is_set():
        dispatcher.emit(
            "processDone",
            {"completed": 0, "failed": 0, "cancelled": True},
            batched=False,
        )
        dispatcher.flush()
        return

    dispatcher.emit("updateProgress", 1.0, batched=False)
    dispatcher.emit("updatePhase", "Completato!", batched=False)
    dispatcher.emit(
        "fileDone",
        {
            "index": 0,
            "id": file_id,
            "name": file_name,
            "html_path": html_path,
            "output_html": html_path,
            "session_dir": session_dir,
            "output_dir": session_dir,
            "effective_model": "gemini-2.5-flash",
        },
        batched=False,
    )
    dispatcher.emit(
        "processDone",
        {"completed": 1, "failed": 0, "cancelled": False},
        batched=False,
    )
    dispatcher.flush()
