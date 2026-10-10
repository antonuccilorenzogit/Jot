# Slide e appunti (notes mode)

Second input mode next to audio: the user selects the lesson **slides** (PDF or
PPTX) and optionally the **textbook** (PDF) with a page range. The result is the
same `*_Sbobina.html` document of the audio pipeline, so the queue, the editor,
the archive, the full-text search and "Riprova revisione" work unchanged.

Entry point: `jot.pipeline.notes_pipeline.esegui_appunti(slides_path, api_key, app, book_path=None, book_pages="", slides_per_chunk=None, resume_session=False, allow_completed_destroy=False)`.

```
┌───────────────────┐  ┌──────────────────────┐  ┌────────────────┐  ┌────────────┐
│ Phase 0           │  │ Phase 1              │  │ Phase 2        │  │ Export     │
│ validate slides   │─▶│ notes per block of   │─▶│ macro-block    │─▶│ Markdown → │
│ + book excerpt    │  │ slides (+ book)      │  │ revision       │  │ HTML       │
└───────────────────┘  └──────────────────────┘  └────────────────┘  └────────────┘
```

## Phase 0 — documents (`services/document_service.py`)

- Slides: `.pdf` (pypdf) or `.pptx` (python-pptx). `.ppt` is rejected with a hint to save as `.pptx`/PDF.
- Book: `.pdf` only. `book_pages` accepts `120-165, 170` (empty = whole book) and is capped at `MAX_BOOK_PAGES` (300) because the excerpt is sent with every block.
- The selected pages are written once to `<session>/book_excerpt.pdf` (deleted when the run completes).

## Phase 1 — notes (`services/notes_service.py`)

- `plan_slide_chunks(total, slides_per_chunk)` splits slides into blocks (default 12; 3–40). A tiny trailing block is merged into the previous one.
- Each block request contains, in order: the book excerpt (uploaded once via the Files API and reused, re-uploaded after key rotation), the slides of the block (a PDF subset inline, uploaded above 14 MB; for PPTX the extracted text, speaker notes and pictures), and the prompt built by `build_notes_chunk_prompt` (real slide numbers, book page label, last ~1000 characters of the previous block).
- System prompt: `PROMPT_APPUNTI` (`core/prompts.py`): slides are the outline and must all be covered, the book is used only to deepen those topics, zero repetitions, impersonal style, `## title` + `_Slide a-b_` reference line, no LaTeX/ASCII diagrams.
- Guardrails: `detect_degenerate_output` (same as audio) **plus** `detect_notes_too_short` (< 90 characters per slide from 4 slides up = summarised output). Both raise `DegenerateOutputError`.
- Transport and recovery are identical to audio phase 1: `retry_with_quota` (503 back-off, 429/RPD handling with fallback keys, model fallback chain) and `_handle_phase1_chunk_recovery` (one extra pass on the primary model, then `phase1_degenerate_output` / `quota_daily_limit_phase1` / `bad_request_phase1` / `phase1_chunk_failed_N`).
- Autosave: `phase1_chunks/chunk_NNN_<first slide>_<last slide>.md`; on resume `_restore_notes_progress` keeps the contiguous prefix matching the current plan and restarts from the first missing block.

## Book page retrieval (`book_mode = "auto"`, `services/book_retrieval.py`)

Default for new jobs from the UI ("Solo le pagine pertinenti a ogni blocco"). Instead of sending the whole selected excerpt with every block, each block gets only the book pages about the same topics (max 15, `DEFAULT_MAX_PAGES_PER_BLOCK`).

1. Text of the selected book pages (pypdf) and of every slide block (PDF text layer or PPTX shapes) is extracted locally.
2. **Embeddings** (`gemini-embedding-001`, task types `RETRIEVAL_DOCUMENT`/`RETRIEVAL_QUERY`, 768 dimensions; `gemini-embedding-2` with text prefixes if the first returns 404). Page vectors are cached in `<session>/book_index.json`, so a resume only embeds the block queries. Pages within `COS_MARGIN` of the best match and above `COS_ABS_MIN` are kept, plus ±1 neighbours of the top 3 hits. Embedding calls use the embedding model's quota, not the daily requests of the generation model.
3. **Keywords fallback** (local BM25 with light prefix stemming and IT/EN stopwords) when the embedding model is missing, rate limited (one retry) or failing.
4. **Whole excerpt** (same as `book_mode = "full"`) when the excerpt already has ≤ 15 pages, the book has no text layer (scanned) or no slide has readable text. Blocks whose slides have no text reuse the previous block's pages.
5. A block with no relevant page is sent without the book.

The plan (`session.notes.book_plan = {method, blocks, reason, max_pages}`) is printed in the console (`Blocco 3 (slide 25-36) -> libro p. 41-47`, total pages sent vs whole excerpt) and reused on resume. Each block's pages are sent as an inline PDF subset (Files API above 14 MB). `book_index.json` and `book_excerpt.pdf` are deleted when the run completes.

`book_mode` is part of the session folder hash only when it is not `"full"`, so sessions created before this feature keep their folder.

## Phase 2 — revision

`pipeline._run_phase2_revision(..., prompt_revisione=PROMPT_REVISIONE_APPUNTI)`: the audio revision prompt plus a rule that keeps/merges the `_Slide a-b_` lines. `retry_failed_revision_blocks` picks the same prompt for sessions with `kind == "notes"`.

## Session

- Folder: `notes_session_dir()` → `<root>/notes_<sha256(slides id, book id, page range)>`, so the same slides with a different book/range get their own session.
- `session.json` adds `"kind": "notes"` and `"notes": {slides_path, slides_name, total_slides, slides_per_chunk, book_path, book_name, book_pages, book_pages_count}`. `slides_per_chunk` is frozen once a block has been generated.
- Stages and `last_error` keys are the audio ones, so the UI error labels and the "Riprendi" flow are reused.

## Bridge / UI

- `BridgeFileItem` gains `kind`, `book_path`, `book_pages`, `slides_per_chunk`, `book_mode`; `start_processing` routes `kind == "notes"` to `esegui_appunti`, validation skips FFmpeg for those items.
- New desktop methods: `ask_document_file(purpose)` and `inspect_document(path, purpose)`.
- `get_completed_sessions` entries carry `kind` and `notes_info`; `stream_media_file` reports `has_audio: false` for slide sources (no "ricollega audio" prompt in the editor).
- React: the "Nuova lezione" page (`components/lesson/LessonComposer.tsx`, helpers in `lessonJob.ts` and `notesJob.ts`) adds a queue item with `kind: 'notes'` when only slides (and book) are chosen; the queue card, processing banner and archive card show notes-specific labels.
