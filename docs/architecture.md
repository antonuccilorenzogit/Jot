# Architecture

jot is a Windows/macOS desktop application that turns audio lectures into structured Italian study notes. The backend is a Python pipeline that talks to the Google Gemini API; the frontend is a React/TypeScript SPA hosted inside a [pywebview](https://pywebview.flowrl.com/) window. There is no server component — everything runs locally, and API calls go directly from the user's machine to Google.

## Repository layout

| Path | What it contains |
|---|---|
| `jot/` | Python package: pipeline, Gemini integration, pywebview backend, configuration, FFmpeg wrappers |
| `webui/` | React + TypeScript frontend (Vite, Tailwind, TipTap, dnd-kit) |
| `launchers/` | PyInstaller entrypoint (`jot_WebUI.pyw`) |
| `packaging/` | Inno Setup script (Windows), `create-dmg` wrapper (macOS), double-click build scripts |
| `scripts/` | `build_release.py` (single source of truth for deps/check/build), `smoke_test.py` |
| `requirements/` | Pinned (`requirements.lock`), runtime (`requirements.txt`), dev (`requirements-dev.txt`) |
| `tests/` | `unittest` suite for the Python package |
| `tools/` | Dev utilities (e.g. `profile_imports.py`) |
| `docs/` | Developer documentation (this file, `pipeline.md`, `session_model.md`, `bridge_protocol.md`) |
| `.github/` | Issue/PR templates, GitHub Actions build workflow |
| `assets/` | Platform icons (`.ico`, `.icns`) |

## Python architecture and package map (`jot/`)

The Python backend is organized into five modular subpackages under `jot/`, cleanly separating IPC bridge controllers, core domain persistence, the multi-phase pipeline, external services, and low-level utilities.

### Entrypoints & API Facade

| Module | Responsibility | Key symbols |
|---|---|---|
| `app_webview.py` | Primary pywebview entrypoint. Hosts `JotApi`, which composes domain controller mixins (`Settings`, `Session`, `Pipeline`, `Export`, `System`, `Media`, `Html`) to form the single JS-callable API boundary. | `main`, `JotApi` |
| `app.py` | Legacy compatibility shim — delegates to `app_webview.main`. | `main`, `JotApp` |
| `webview_entry.py` | WebView2 runtime detection on Windows, fallback installation dialog, and window instantiation. | `has_webview2_runtime`, `main` |

### `bridge/` — PyWebView IPC Layer

| Module | Responsibility | Key symbols |
|---|---|---|
| `bridge/bridge_dispatcher.py` | Buffered event emitter flushing events via `evaluate_js` with event collapsing, batching, and ~80 ms throttling. | `_BridgeDispatcher` |
| `bridge/bridge_types.py` | Shared `TypedDict` payload schemas (`WorkTotalsPayload`, `FileDonePayload`, `ValidationResult`, …). | — |
| `bridge/bridge_utils.py` | Shared bridge helpers and containment checks (`_path_under_root`, `_safe_relpath`, `_ALLOWED_URL_PREFIXES`). | `_path_under_root`, `_safe_relpath` |
| `bridge/controllers/` | Domain controller mixins composed into `JotApi` (`ExportControllerMixin`, `HtmlControllerMixin`, `MediaControllerMixin`, `PipelineControllerMixin`, `SessionControllerMixin`, `SettingsControllerMixin`, `SystemControllerMixin`). | `*ControllerMixin` |

### `pipeline/` — Transcription & Revision Orchestration

| Module | Responsibility | Key symbols |
|---|---|---|
| `pipeline/pipeline.py` | Core pipeline runner (`esegui_sbobinatura`): orchestrates probe, phase 1 chunks, phase 2 revision, boundary passes, and final HTML export. | `esegui_sbobinatura`, `_esegui_sbobinatura_impl` |
| `pipeline/pipeline_adapter.py` | Bridges pipeline events and worker lifecycle to `_BridgeDispatcher` for UI event broadcasting. | `PipelineAdapter` |
| `pipeline/pipeline_hooks.py` | Duck-typed runtime wrapper decoupling pipeline execution from the concrete UI host. | `PipelineRuntime` |
| `pipeline/pipeline_session.py` | Context bootstrap, stage normalization, crash resume, progress restore, pre-conversion management. | `initialize_session_context`, `PipelineSessionContext`, `restore_phase1_progress` |
| `pipeline/pipeline_settings.py` | Settings sanitization, validation, per-model parameter clamping, and legacy migration. | `PipelineSettings`, `load_and_sanitize_settings` |

### `services/` — Business Logic & External Integrations

| Module | Responsibility | Key symbols |
|---|---|---|
| `services/generation_service.py` | Gemini transport: `retry_with_quota`, fallback model rotation, automatic fallback key rotation on exhaustion, and degenerate output guardrail. | `retry_with_quota`, `try_rotate_key`, `detect_degenerate_output` |
| `services/gemini_errors.py` | Domain error hierarchy distinguishing transient rate limits, daily quota exhaustion, model unavailability, and unrecoverable errors. | `DegenerateOutputError`, `QuotaDailyLimitError`, `AllModelsUnavailableError`, `PermanentError` |
| `services/phase1_service.py` | Chunked transcription loop with background FFmpeg prefetching and model chain fallback. | `process_phase1_transcription` |
| `services/revision_service.py` | Phase 2 macro-revision with two-pass retry via `.raw.md`, and phase 3 boundary stitching. | `build_macro_blocks`, `process_macro_revision_phase`, `process_boundary_revision_phase` |
| `services/audio_service.py` | Audio processing facade over FFmpeg (`probe_media_duration`, `preconvert_media_to_mp3`, `cut_audio_chunk_to_mp3`). | `probe_media_duration`, `resolve_ffmpeg` |
| `services/export_service.py` | Assembles revised markdown blocks into the final titled document and coordinates HTML output. | `export_final_html_document`, `resolve_output_html_path` |
| `services/archive_service.py` | Local session indexing, metadata aggregation, and full-text search integration across sessions. | `list_archived_sessions`, `query_archive` |
| `services/search_service.py` | Full-text search snippet generation and keyword match counting in study notes. | `extract_text_from_html`, `find_snippets` |
| `services/folders_service.py` | Folder organization and categorisation persisted in `folders.json`. | `get_folders`, `save_folders` |
| `services/sharing_service.py` | Packaging and extraction of `.sbobina` archives and zip files with zip-slip and symlink defense. | `export_sbobina_package`, `import_sbobina_package` |
| `services/config_service.py` | Config file persistence, desktop path resolution, safe filename sanitization. | `load_config`, `save_config`, `safe_output_basename` |
| `services/network_service.py` | Connectivity monitoring and online/offline status checks. | `check_connectivity` |
| `services/usage_service.py` | Token usage, cost estimation, and request metric tracking. | `record_usage`, `get_usage_summary` |
| `services/validation_service.py` | Pre-flight runtime validation (FFmpeg presence, write permissions, key validity). | `validate_environment` |

### `core/` — Domain Foundations & State Management

| Module | Responsibility | Key symbols |
|---|---|---|
| `core/shared.py` | Fingerprint-based session IDs, atomic file write utilities (`_atomic_write_json`, `_atomic_write_text`), default paths. | `_session_id_for_file`, `_atomic_write_json`, `_atomic_write_text` |
| `core/session_store.py` | On-disk session layout: `SessionPaths`, `new_session`, `load_session`, `save_session`. | `SessionPaths`, `load_session`, `save_session` |
| `core/session_storage.py` | Storage metrics computation with cached sizing calculations. | `get_session_storage_info`, `invalidate_session_storage_cache` |
| `core/session_cleanup.py` | Automatic purge of orphan chunks, incomplete sessions, and legacy data roots. | `cleanup_orphan_temp_chunks`, `cleanup_orphan_sessions` |
| `core/model_registry.py` | Supported Gemini models, per-model chunk defaults, fallback chains. | `MODEL_OPTIONS`, `ModelState`, `build_model_state` |
| `core/credentials.py` | Secure API key storage using Windows DPAPI or macOS Keychain / Secret Service. | `store_credential`, `retrieve_credential` |
| `core/prompts.py` | Prompt templates for transcription, macro-revision, and boundary stitching. | `PROMPT_SISTEMA`, `PROMPT_REVISIONE`, `PROMPT_REVISIONE_CONFINE` |
| `core/media_server.py` | Local streaming HTTP server with Range request support for audio playback in the editor. | `LocalMediaServer` |
| `core/updater.py` | In-app release download, SHA-256 verification, and installer launch. | `download_and_install_update` |

### `utils/` — System & File Helpers

| Module | Responsibility | Key symbols |
|---|---|---|
| `utils/ffmpeg_utils.py` | FFmpeg subprocess execution with cancellation support, audio probing, mono-16 kHz conversion, and chunk slicing. | `get_ffmpeg_exe`, `probe_duration_seconds`, `preconvert_to_mono16k_mp3`, `cut_chunk_to_mp3` |
| `utils/html_export.py` | Markdown-to-HTML compilation with `nh3` sanitization, list normalization, and CSP-protected document shell. | `build_html_document`, `sanitize_html_basic` |
| `utils/file_ops.py` | Concurrency-guarded HTML body saving (`save_html_body_content`) and OS default application launcher. | `open_path_with_default_app`, `save_html_body_content` |
| `utils/logging_utils.py` | Structured logger with automatic API key / secret redaction and per-session log files. | `get_logger`, `configure_logging`, `redact_secrets` |
| `utils/dedup_utils.py` | Conservative duplicate text suppression prior to LLM revision. | `local_macro_cleanup` |

## Frontend module map (`webui/src/`)

| Path | Responsibility |
|---|---|
| `main.tsx` | React entrypoint + `RootErrorBoundary` |
| `App.tsx` | Top-level app shell: queue, drag-and-drop, processing banner, modal wiring, confetti |
| `appState.ts` | `processingReducer` + `ProcessingState`/`ProcessingAction` types (single source of truth for queue + progress state) |
| `bridge.ts` | `PywebviewApi` interface (JS → Python) and `BridgeCallbacks` (Python → JS) with `createBridge` factory |
| `RichTextEditor.tsx` | TipTap editor inside page shell |
| `AudioPlayer.tsx` | Editor audio player with range scruber control and bookmarks |
| `FloatingImage.tsx` | Resize/align/layout affordances for editor-embedded images |
| `previewHtml.ts` | Normalize preview HTML before loading into the editor |
| `editorSessions.ts` | Per-file editor-session persistence (scroll, audio position) via `localStorage` |
| `duplicateDetection.ts` | Archive-lookup helpers used by the "already processed" modal |
| `branding.ts` | Constants for GitHub/releases URLs |
| `utils.ts` | `errorLabel` mapping (Python `last_error` → Italian UI string), formatters |
| `index.css` | Tailwind v4 base + custom theme design tokens (including editor, sidebar, and modals) |
| `components/NavSidebar.tsx` | Main lateral navigation bar switching between Queue, Archivio, and Setup pages |
| `components/ArchivePage.tsx` | Main archive search dashboard, layout structure, search logic |
| `components/archive/*` | Modularized archive subcomponents (`FolderCard`, `FolderDetailView`, `SessionCard`, `SortMenu`, `FolderModals`, `FullTextResults`) |
| `components/ConsolePanel.tsx` | Embedded expandable system output/log console panel |
| `components/DropZone.tsx` | Drag and drop files intake zone with SVG marching ants animation |
| `components/EditorFindReplace.tsx` | Advanced find/replace popup bar inside the text editor |
| `components/EditorFullPage.tsx` | Fullscreen modal page hosting TipTap editor, TOC, sidebar, and player |
| `components/EditorToolbar.tsx` / `components/EditorToolbarControls.tsx` | Standard document styling controls and formatting actions |
| `components/FolderChip.tsx` / `components/KebabMenu.tsx` / `components/Toast.tsx` | Micro-components for folder tags, action triggers, and brief toast alerts |
| `components/NavSidebar.tsx` | Main lateral navigation bar switching between Queue, Archivio, and Setup pages |
| `components/ProcessingStatusBanner.tsx` | Top-of-screen banner while a batch is running (ETA, phase, model badge) |
| `components/QueueFileCard.tsx` | Queue item card (pending + completed variants) |
| `components/QueueSection.tsx` | Queue container holding intake dropzone and queue lists |
| `components/SetupPage.tsx` | Step-by-step walkthrough settings wizard on first run |
| `components/WelcomeDashboard.tsx` | Warm entrance dashboard when queue is empty |
| `components/modals/*.tsx` | `SettingsModal`, `RegenerateModal`, `NewKeyModal`, `DuplicateFileModal`, `ConfirmActionModal` |
| `hooks/useApiReady.ts` | Polls `window.pywebview.api` until ready, then binds the bridge |
| `hooks/useBridgeCallbacks.ts` | Wires `BridgeCallbacks` onto `window.jotBridge` |
| `hooks/useQueuePersistence.ts` | Persists the file queue across app restarts |
| `hooks/useConsole.ts` | Captures `appendConsole` messages for the in-app terminal |
| `hooks/useTheme.ts` | Light/dark theme toggle |
| `hooks/useUpdateChecker.ts` | Polls GitHub releases for update notifications |
| `hooks/useBodyScrollLock.ts` | Scroll-lock when a modal is open |
| `hooks/usePreview.ts` | Complete preview session management (loading, scroll position, audio sync, audio relinking) |

## Runtime flow

```
packaged exe / python  launchers/jot_WebUI.pyw
         │
         ▼
jot.app_webview.main()
         │
         ├─ detect WebView2 runtime (Windows) → fallback HTML if missing
         ├─ create pywebview window  ◄──────  js_api = JotApi
         ├─ spawn LocalMediaServer on demand
         └─ webview.start()
                 │
                 │  user clicks "Avvia"
                 ▼
     JotApi.start_processing(...)
                 │  worker thread (one per batch)
                 ▼
     for each file:
       pipeline.esegui_sbobinatura(...)
           │                                  (duck-typed app_instance
           ▼                                   = PipelineAdapter)
       PipelineRuntime(app_instance)
           │
           ├─► phase1_service.process_phase1_transcription
           │       FFmpeg cut → Gemini generate → autosave chunk_NNN.md
           │
           ├─► revision_service.process_macro_revision_phase
           │       build_macro_blocks → AI revise → rev_NNN.md (+ .raw.md retry pass)
           │
           ├─► revision_service.process_boundary_revision_phase
           │       local similarity gate → AI stitch → boundary_NNN.done
           │
           └─► export_service.export_final_html_document
                   rev_NNN.md → build_html_document → <Title>_Sbobina.html
```

All pipeline → UI updates go through `PipelineRuntime` (`jot/pipeline/pipeline_hooks.py`), which forwards to `PipelineAdapter` methods on the adapter. The adapter buffers them through `_BridgeDispatcher`, which calls `window.evaluate_js("window.jotBridge.<event>(<json>)")` roughly every 80 ms. React's `processingReducer` then consumes the events. See [`bridge_protocol.md`](./bridge_protocol.md) for the full event/API tables.

## Threading model

- **UI thread** — owned by pywebview / WebView2. Receives all JS API calls.
- **Pipeline worker** — one background thread per batch (started by `JotApi.start_processing`). Runs `esegui_sbobinatura` sequentially per file.
- **FFmpeg prefetch thread** — inside phase 1, each iteration may spawn a daemon thread that cuts the *next* chunk while the current one is being sent to Gemini (controlled by `PipelineSettings.prefetch_next_chunk`).
- **`_BridgeDispatcher` timer** — single shared `threading.Timer` that flushes queued UI events.
- **`LocalMediaServer` threads** — one `ThreadingTCPServer` per actively streamed audio file (LRU-capped at 5).
- **Session-storage info thread** — one long-lived `ThreadPoolExecutor` worker in `core/session_storage.py` that recomputes total session size / count on demand (with a 30 s cache).

## Further reading

- [`pipeline.md`](./pipeline.md) — phase-by-phase walk-through, error classes, `last_error` values, model fallback.
- [`session_model.md`](./session_model.md) — on-disk session layout and `session.json` schema.
- [`bridge_protocol.md`](./bridge_protocol.md) — Python ↔ JS event and API contracts.
