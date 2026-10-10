# Pipeline

The pipeline turns one input audio/video file into one `*_Sbobina.html` document. It runs sequentially inside a worker thread and reports progress to the UI through `PipelineRuntime` (see [`bridge_protocol.md`](./bridge_protocol.md)).

Entry point: `jot.pipeline.esegui_sbobinatura(input_path, api_key_value, app_instance, session_dir_hint=None, resume_session=False)`.

## Overview

```
┌──────────────┐  ┌──────────────┐  ┌────────────────┐  ┌────────────┐
│   Phase 0    │  │   Phase 1    │  │    Phase 2     │  │   Export   │
│ pre-convert  │─▶│ chunked      │─▶│ macro-block    │─▶│ Markdown → │
│ mono 16 kHz  │  │ transcription│  │ revision       │  │ HTML       │
│ (optional)   │  │ (Gemini)     │  │ (Gemini)       │  │            │
└──────────────┘  └──────────────┘  └────────────────┘  └────────────┘
```

Stage is persisted in `session.json` under `stage ∈ {"phase1", "phase2", "done"}`. Resuming simply re-enters the pipeline at the current stage (see [`session_model.md`](./session_model.md)).

## Phase 0 — Pre-conversion (optional)

File: `pipeline_session.ensure_preconverted_audio`.

- Only runs when `settings.preconvert_audio = True` (default) and `stage == "phase1"`.
- Output: `<session_dir>/jot_preconverted_mono16k.mp3` (constant `PRECONVERTED_AUDIO_FINAL`).
- Partial output: `jot_preconverted_mono16k.partial.mp3` (constant `PRECONVERTED_AUDIO_PARTIAL`). Renamed atomically on completion.
- Implemented by `ffmpeg_utils.preconvert_to_mono16k_mp3` — mono, 16 kHz, configurable bitrate (default `"48k"`).
- **Why**: subsequent phase-1 chunks can then be cut via FFmpeg `-c:a copy` (stream copy) which is 5–10× faster than re-encoding from the original container on every chunk.
- Deleted at the end of a successful run to reclaim disk space.

## Phase 1 — Chunked transcription

File: `phase1_service.process_phase1_transcription`.

### Loop

For each chunk in `range(start_sec, total_duration_sec, step_seconds)`:

1. **FFmpeg cut** (`_cut_chunk_to_path`) — tries stream-copy from the preconverted MP3 first; falls back to a full re-encode of the original file on failure.
2. **Input preparation** — inline `Part.from_bytes(mime="audio/mpeg")` when the chunk is ≤ `settings.inline_audio_max_mb` (default 6 MB); otherwise upload via `client.files.upload` and wait for `ACTIVE` state (`wait_for_file_ready`, 15-minute ceiling, 3 s poll).
3. **Gemini call** — `generate_content(model=<active>, contents=[prompt, audio], config=GenerateContentConfig(system_instruction=PROMPT_SISTEMA, temperature=_phase1_temperature(<active>)))`. Prompt is built by `generation_service.build_chunk_prompt(prev_memory)` and includes the last ~1000 characters of the previous chunk so the model continues fluently across overlaps.
4. **Guardrail** — `detect_degenerate_output(generated_text)` rejects runs of repeated paragraphs, oversized paragraphs (> 12 000 chars), and long under-segmented blobs.
5. **Autosave** — `chunk_{NNN:03}_{start}_{end}.md` (atomic write) and session update `{chunks_done, next_start_sec, memoria_precedente}`.
6. **Prefetch** — next chunk's FFmpeg cut runs in a daemon thread while the current chunk is in flight (gated by `settings.prefetch_next_chunk`).

### Transient / permanent errors

| Error | Handling |
|---|---|
| 400 / INVALID_ARGUMENT | `PermanentError` → `last_error = "bad_request_phase1"`, abort. |
| Inline audio rejected (size/400) | Automatic fallback to upload, no quota consumed. |
| `DegenerateOutputError` | One retry on the next model in the chain. If the chain is already exhausted: **chain-exhaustion recovery** resets to the primary model for one extra pass. If that also fails → `last_error = "phase1_degenerate_output"`. |
| `AllModelsUnavailableError` (503 on every model) | Same chain-exhaustion recovery as above. On second failure → `last_error = "phase1_all_models_unavailable"`. |
| `QuotaDailyLimitError` | `last_error = "quota_daily_limit_phase1"`, abort. If the replacement-key popup times out, also set `last_error_detail = "api_key_prompt_timeout"`. |
| Other exceptions after `_MAX_RETRY_ATTEMPTS` | `last_error = f"phase1_chunk_failed_{N}"`, `last_error_detail` captures the final exception summary, abort. |

The `chain_exhaustion_recovery_used` flag (per chunk) ensures the extra primary-model pass can only happen once, so we never loop forever.

## Phase 2 — Macro-block revision

File: `revision_service.process_macro_revision_phase`. Prompt: `PROMPT_REVISIONE`.

### Block building (`build_macro_blocks`)

Splits the concatenated phase-1 text into blocks bounded by `macro_char_limit` (model-dependent, see table below). The splitter:

- Hard-splits when adding the next paragraph would exceed the limit.
- Soft-splits at `##`/`###` headings once the current block is already past 70 % of the limit and holds at least 500 characters of content. This keeps section breaks aligned with the editorial structure rather than with arbitrary character counts.

### Two-pass retry architecture

For each block `index`:

1. If `rev_{NNN}.md` already exists and is non-empty, reuse it (resume-safe).
2. If `rev_{NNN}.raw.md` exists, skip the main pass and queue the block for the retry pass.
3. Otherwise, run `local_macro_cleanup` (conservative, text-only dedup) and call Gemini with `temperature=0.1`.
4. On success → write `rev_{NNN}.md` atomically and bump `phase2.revised_done`.
5. On failure → write `rev_{NNN}.raw.md` containing the untouched block source and add the index to `pending_retry`.

After the main loop:

- `revision_pending_blocks` is written to the session for observability.
- Each `.raw.md` is re-attempted (fresh `local_macro_cleanup`, fresh Gemini call). Success → `rev_{NNN}.md` and delete `.raw.md`. Final failure → rename `.raw.md` → `.md` so the block is included unrevised, and add the index to `revision_failed_blocks`.
- `QuotaDailyLimitError` during retry → break with `last_error = "quota_daily_limit_phase2"`; the `.raw.md` file is kept so the next run can pick up where we stopped.

Downstream consumers (`export_service.load_revised_blocks`) match `^rev_\d{3}\.md$` exactly, so `.raw.md` files are never accidentally exported.

## Export

File: `export_service.export_final_html_document`.

1. `load_revised_blocks` reads every `rev_*.md` in order.
2. `build_final_markdown` prepends `# <Title>` and runs `normalize_inline_star_lists` to fix bullet quirks common in LLM output.
3. `build_html_document` (in `html_export.py`) normalizes headings to `h1`–`h5`, renders via `python-markdown` (`extra` + `sane_lists`), sanitizes via `nh3`, and wraps the body in a CSP-locked HTML5 shell (`default-src 'none'; img-src data:; style-src 'unsafe-inline'`).
4. Output path: `<session_dir>/<SafeTitle>_Sbobina.html` (name derived from the input file's basename via `safe_output_basename`). On failure to compute a title, falls back to `Sbobina_Definitiva.html`.

On success the pipeline sets `session["stage"] = "done"`, writes `outputs.html` to the session, and reports `runtime.output_html(path)` to the UI. The pre-conversion file is then deleted to save disk.

## Gemini transport (`generation_service.retry_with_quota`)

All Gemini calls in every phase go through `retry_with_quota(callable_fn, ...)`, a single retry loop that handles:

| Condition | Behaviour |
|---|---|
| HTTP 408/500/502/503/504, timeout, or "model unavailable" | At most four calls: initial request, then retries after 15 s, 30 s, and 60 s, each with positive jitter up to 10%. The model never changes for capacity errors; after the last failure the circuit breaker pauses the current file and stops the batch. Every attempt and retry is recorded in single-authority telemetry. |
| HTTP 429 rate limit (`rate_limit_exceeded`) | Minute/token-scoped quota: extracts `Retry-After` or uses 65 s, then makes one probe. A failed probe exhausts the circuit breaker and pauses the batch. |
| HTTP 429 daily quota (`quota_exceeded`) | Day-scoped (RPD) exhaustion on Google project: marks model quota state as `rpd_exhausted`, automatically rotates to the next available fallback key via `try_rotate_key(fallback_keys)`, and prompts the UI via `request_new_api_key` only if all fallback keys are exhausted. If prompt times out or cancelled, aborts with quota error. |
| HTTP 429 unknown | Defaults to minute-scoped rate limit backoff (65 s) before escalating to daily quota exhaustion if repeated. |
| HTTP 404 model-not-found | Switch model; if no fallback left, re-raise. |
| `DegenerateOutputError` | Switch model; if no fallback left, re-raise. |
| `PermanentError` | Re-raise immediately (no retry). |
| Any other exception | Sleep `retry_sleep_seconds`, retry up to `_MAX_RETRY_ATTEMPTS`. |


Side effects are routed through callbacks so phases can react:

- `on_key_rotated(new_client)` — phase 1 uses this to refresh the uploaded file reference after key rotation.
- `on_model_switched(prev, new)` — pipeline persists `settings.effective_model` and updates the UI model badge.
- `resume_phase_text` — brought back after any sleep so the UI doesn't stay stuck on "Rate limit: attesa 65s…".

### Temperature

`generation_service._phase1_temperature(model_name)` reads the per-model `phase1_temperature` from `MODEL_OPTIONS` (see the table below). Phase 2 always uses `temperature=0.1`.

## Model registry

Source: `jot/model_registry.py`.

| Model id | Default chunk min | Default macro char limit | Phase-1 temperature |
|---|---|---|---|
| `gemini-3.8-flash` | 15 | 22 000 | 0.35 |
| `gemini-3.7-flash` | 15 | 22 000 | 0.35 |
| `gemini-3.6-flash` | 15 | 22 000 | 0.35 |
| `gemini-3.5-flash` | 15 | 22 000 | 0.35 |
| `gemini-2.5-flash` (default primary) | 15 | 22 000 | 0.35 |

The `ModelState` dataclass tracks the ordered chain and the currently active model. `build_model_state(primary, fallbacks)` always resets `current` to the primary on resume — the previous run's `effective_model` is persisted for observability only.
New sessions start with no fallback models unless the user explicitly adds them in settings.

## `last_error` reference

All failure modes write a machine-readable string to `session["last_error"]` before returning. Some paths also write `session["last_error_detail"]` for UI copy and diagnostics. The React UI maps these to Italian strings via `webui/src/utils.ts` (`errorLabel`).

| `last_error` | Meaning | UI string (`errorLabel`) |
|---|---|---|
| `api_key_mancante` | API key absent at job start | "API key mancante o non valida." |
| `quota_daily_limit_phase1` | Daily quota exhausted during transcription | "Quota giornaliera API esaurita durante la trascrizione." With `last_error_detail = "api_key_prompt_timeout"`: "Attesa chiave API scaduta. Sessione salvata — riprendi quando vuoi." |
| `bad_request_phase1` | HTTP 400 while transcribing a chunk | "Richiesta non valida durante la trascrizione (errore 400)." |
| `phase1_degenerate_output` | Degenerate output even after chain-exhaustion recovery | "Trascrizione interrotta: testo non valido anche dopo il retry automatico." |
| `phase1_all_models_unavailable` | Every model 503-unavailable; recovery also failed | Falls through to the raw string. |
| `regenerate_prompt_timeout` | The regenerate/resume prompt was left unanswered for 120 seconds | "Nessuna scelta ricevuta sulla ripresa entro 120 secondi. Sessione salvata: clicca Riprendi per continuare." |
| `session_collision` | A fresh/regenerate path tried to overwrite a completed session with existing HTML without explicit confirmation | "Questo file sembra corrispondere a una sbobina gia completata ma con contenuto diverso. Apri Impostazioni -> Sessioni per risolvere." |
| `phase1_chunk_failed_<N>` | Non-quota exception after all retries on chunk `N`; detail stores the final exception summary | "Errore al blocco `<N>` dopo 4 tentativi. Dettaglio: `<last_error_detail>`. Clicca Riprendi per continuare dal blocco `<N>`." |
| `quota_daily_limit_phase2` | Daily quota during macro revision (main or retry pass) | "Quota giornaliera API esaurita durante la revisione." With `last_error_detail = "api_key_prompt_timeout"`: "Attesa chiave API scaduta. Sessione salvata — riprendi quando vuoi." |
| `html_export_failed` | HTML assembly raised | "Errore durante il salvataggio del file di output." |
| `html_export_missing` | Output file not present after write | "File di output non trovato dopo il salvataggio." |
| `processing_failed` | Generic fallback when nothing more specific was set | "Elaborazione non completata." |

Additional observability-only session keys (not a hard error, but surfaced to the UI):

- `revision_pending_blocks` — indexes queued for the phase-2 retry pass.
- `revision_failed_blocks` — indexes that ultimately stayed unrevised (run finishes with a warning, not an error).

## Error classes

Source: `jot/generation_service.py`.

| Class | Purpose |
|---|---|
| `QuotaDailyLimitError(Exception)` | Daily quota exhausted on the active key with no fallback available. Stops the current phase; progress is saved. |
| `PermanentError(Exception)` | HTTP 400 / INVALID_ARGUMENT — never retried. |
| `DegenerateOutputError(RuntimeError)` | Model produced repetitive / runaway text. Carries `rejected_text` (capped at 500 chars) for diagnostics. |
| `AllModelsUnavailableError(RuntimeError)` | Every model in the fallback chain returned 503 after all back-offs. Triggers phase-1 chain-exhaustion recovery. |

See [`session_model.md`](./session_model.md) for how these interact with the resume contract.
