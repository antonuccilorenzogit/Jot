# Session model

jot persists every run under a session directory so the pipeline can be resumed at a chunk / macro-block granularity after the user closes the app, loses power, or runs out of daily API quota. This doc describes the actual on-disk layout used by the current desktop app.

## Identity

- **Root**: `SESSION_ROOT` is the platform-specific default session-storage root directory (preventing unwanted cloud sync via OneDrive/iCloud, see `shared.SESSION_ROOT` and `shared._get_default_session_root`):
  * **Windows**: `%LOCALAPPDATA%\jot\sessions` (typically `C:\Users\<user>\AppData\Local\jot\sessions`)
  * **macOS**: `~/Library/Caches/jot/sessions`
  * **Linux / Legacy fallback**: `~/.jot_sessions/`
  *(Note: The auto-migration helper `migrate_legacy_session_root` automatically moves old session directories from `~/.jot_sessions` to the platform-appropriate location on first run after upgrade).*
- **Session directory**: `SESSION_ROOT/<fingerprint>/`, where `<fingerprint>` is produced by `shared._session_id_for_file(path)`.

### Fingerprint

```python
fingerprint = SHA256({
    "size": <os.stat size in bytes>,
    "head_hash": SHA256(first 1 MB of the file),
    "tail_hash": SHA256(last 1 MB of the file)
})
```

This means the session is keyed by **content identity** (including sampled content hashes), not by absolute path or metadata — moving, renaming, or timestamp-only changes to the audio file do not invalidate the session. Results are cached in a process-local LRU (`_session_id_cache`, capped at 500 entries) keyed by absolute path, size, and `mtime_ns` so recomputing the partial hashes is amortized without making the durable ID metadata-sensitive.

A second helper, `_session_dir_for_file(path)`, joins `SESSION_ROOT` with the fingerprint.

## Lifecycle

| Function | Purpose |
|---|---|
| `pipeline_session.initialize_session_context(input_path, session_dir_hint, resume_session)` | Resolves `SessionPaths`, decides whether to load or create, sanitizes settings, returns a `PipelineSessionContext`. |
| `session_store.resolve_session_paths(input_path, session_dir_hint)` | Builds the `SessionPaths` dataclass (session dir + subfolders). |
| `session_store.new_session(input_path, settings=None)` | Creates a fresh in-memory session dict (schema version 1) and a file fingerprint. |
| `session_store.load_session(session_path)` | Reads `session.json`. |
| `session_store.save_session(session_path, session)` | Writes atomically, updates `updated_at`. |
| `session_store.ensure_session_dirs(paths)` | `mkdir -p` for all subfolders. |
| `session_store.reset_session_dirs(paths, allow_completed_destroy=False)` | `rmtree` + recreate, but refuses completed sessions with existing HTML unless explicit destruction is allowed. |
| `pipeline_session.reset_for_regeneration(ctx)` | Wipes the directory, creates a brand-new session, overwrites settings with the defaults derived from the current config. |
| `shared.cleanup_orphan_sessions(max_age_days=0)` | Deletes incomplete session folders (default: all incomplete sessions, or older than `max_age_days`). |
| `shared.get_session_storage_info()` | Returns `{total_bytes, total_sessions}` with a 30 s cache and a 10 s timeout. Used by the Settings modal. |

## On-disk layout

```
<SESSION_ROOT>/<fingerprint>/
├── session.json                              # primary state (see schema below)
├── run.log                                   # structured per-run log (StructuredFormatter)
├── jot_preconverted_mono16k.mp3    # optional; deleted on success
├── jot_preconverted_mono16k.partial.mp3  # in-flight; cleaned up automatically
├── phase1_chunks/
│   ├── chunk_001_0_900.md
│   ├── chunk_002_870_1800.md
│   └── ...
├── phase2_revised/
│   ├── rev_001.md                             # authoritative — included in the final HTML
│   ├── rev_002.md
│   ├── rev_003.raw.md                         # provisional — awaiting retry pass
│   └── ...
├── phase2_macro_blocks.json                  # {"limit_chars": int, "blocks": [...]}
└── <SafeTitle>_Sbobina.html                  # final output (written on completion)
```

## File naming conventions

| File | Regex | Parsed fields |
|---|---|---|
| Phase 1 chunk | `^chunk_(\d{3})_(\d+)_(\d+)\.md$` | `(index, start_sec, end_sec)` |
| Revised block (final) | `^rev_\d{3}\.md$` | `index` |
| Revised block (provisional) | `^rev_(\d{3})\.raw\.md$` | `index` — **not matched** by the final regex |

`export_service.load_revised_blocks` uses the strict `rev_\d{3}\.md$` match so that `.raw.md` files are never exported into the final HTML.

## `session.json` schema

`SESSION_SCHEMA_VERSION = 1` (constant in `shared.py`).

```json
{
  "schema_version": 1,
  "created_at": "YYYY-MM-DD HH:MM:SS",
  "updated_at": "YYYY-MM-DD HH:MM:SS",
  "stage": "phase1 | phase2 | done",
  "input": {
    "path": "<absolute path at time of creation>",
    "size": 123456789,
    "mtime": 1700000000.0
  },
  "settings": {
    "model": "gemini-2.5-flash",
    "fallback_models": [],
    "effective_model": "gemini-2.5-flash",
    "chunk_minutes": 15,
    "overlap_seconds": 30,
    "macro_char_limit": 22000,
    "preconvert_audio": true,
    "prefetch_next_chunk": true,
    "inline_audio_max_mb": 6.0,
    "audio": { "bitrate": "48k" }
  },
  "phase1": {
    "next_start_sec": 0,
    "chunks_done": 0,
    "memoria_precedente": "",
    "duration_seconds": null,
    "step_seconds": null,
    "preconverted_done": false,
    "preconverted_path": null
  },
  "phase2": {
    "macro_total": 0,
    "revised_done": 0
  },
  "outputs": {
    "html": "<absolute path to the exported HTML>"
  },
  "metrics": {
    "chunks": { "count": 0, "elapsed_seconds": 0.0, "last_seconds": 0.0, "avg_seconds": 0.0, "done": 0, "total": 0 },
    "macro":  { ... }
  },
  "last_error": null,
  "last_error_detail": null,
  "revision_pending_blocks": [],
  "revision_failed_blocks": []
}
```

Notes:

- `"stage"` is one of `"phase1"`, `"phase2"`, or `"done"` for sessions created by the current pipeline. Sessions written by older versions may contain `"boundary"`, which is accepted by `normalize_stage` and promoted to `"done"` when export completes — it is never written by the current pipeline.
- `input.path` is captured once at creation. Since identity is derived from size + mtime + partial hash (not from the path), the stored value is informational — moving the file does not break resume.
- `settings.effective_model` records the model that was active when the previous run last persisted. On resume the pipeline always resets `ModelState.current` back to `settings.model` (the primary) and lets the fallback chain re-degrade if needed.
- `metrics.*` entries are maintained by `pipeline_session.record_step_metric(session, kind, seconds, done, total)`. `avg_seconds` is recomputed as `elapsed_seconds / count`; the UI uses a 40/60 EMA of `last_seconds` for live ETA.
- `last_error` and `last_error_detail` are cleared (`null`) whenever a phase completes cleanly. `last_error_detail` is optional diagnostic context, currently used for replacement-key prompt timeouts and Phase 1 chunk-failure details. See [`pipeline.md`](./pipeline.md) for the full list of possible values.
- `revision_pending_blocks` / `revision_failed_blocks` are populated by `revision_service.process_macro_revision_phase` and consumed only for observability.

## Settings sanitization (`pipeline_settings.load_and_sanitize_settings`)

Called on every resume. Ensures `session["settings"]` is a dict and:

- Clamps `chunk_minutes` into `[1, 180]`; defaults per-model via `default_chunk_minutes_for_model`.
- Clamps `overlap_seconds` into `[0, chunk_seconds - 1]`.
- Clamps `macro_char_limit` into `[6 000, 90 000]`.
- Clamps `inline_audio_max_mb` into `[0, 25]`.
- Validates `model` / `fallback_models` against `SUPPORTED_MODELS`; unknown entries are dropped.
- Recomputes `effective_model`: keeps the stored value only if it belongs to the current `{model} ∪ fallback_models` set; otherwise resets to `model`.
- Ensures `audio.bitrate` is a non-empty string (defaults to `"48k"`).
- **Legacy model migration**: removed model identifiers are sanitized to the current default model, while unsupported fallback entries are discarded. Explicit chunk and macro limits remain preserved unless they match a known obsolete default.

The function also returns a `changed` flag so `initialize_session_context` can save the sanitized values back to disk idempotently.

## Resume contract

Different phases have different granularities:

| Phase | Granularity | Authoritative artifact | Resume function |
|---|---|---|---|
| Phase 0 (pre-conv) | File-level | `jot_preconverted_mono16k.mp3` + `phase1.preconverted_done` | `ensure_preconverted_audio` |
| Phase 1 | Chunk-level | `chunk_{NNN}_*.md` + `phase1.{next_start_sec, chunks_done, memoria_precedente}` | `restore_phase1_progress` |
| Phase 2 | Block-level | `rev_{NNN}.md` (final) and `rev_{NNN}.raw.md` (provisional) + `phase2.revised_done` | inline in `process_macro_revision_phase` (skips when `.md` exists, queues when `.raw.md` exists) |

On resume, `normalize_stage(session)` snaps `stage` back to `"phase1"` if it's unrecognized, and `phase1_has_progress` decides whether to prompt the user with the "regenerate?" modal (only for resumes that already have work).

## Regeneration

If the user answers "rigenera" to the resume prompt, `pipeline.reset_for_regeneration(ctx)` wipes the session directory with `allow_completed_destroy=True` and creates a fresh session seeded with the current default settings (`build_default_pipeline_settings(load_config())`). All prior progress is lost by design only after that explicit confirmation.

## Cross-reference

- [`pipeline.md`](./pipeline.md) — which exceptions produce which `last_error` value.
- [`architecture.md`](./architecture.md) — where these helpers live in the module tree.
