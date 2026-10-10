# Nuova lezione: audio, slide e libro

One page (`components/lesson/LessonComposer.tsx`) with three dials. The combination decides the pipeline:

| Sources | Pipeline | Requests (2h30 lesson) |
| --- | --- | --- |
| Audio | classic sbobinatura | ~11 blocks + ~4 revisions |
| Audio + slides and/or book | classic sbobinatura with extra context | same as audio only |
| Slides (+ book) | notes mode (`docs/notes_mode.md`) | blocks of slides + revisions |
| Book alone | not allowed | — |

## Audio + slides (`services/lesson_context.py`)

- `SlideTracker` attaches to each 15-minute audio block a window of slides (8–30, sized on slides per block × 1.8).
- The model ends every block with a hidden `[[ULTIMA_SLIDE: n]]`; the next window starts two slides before it. If the marker is missing or outside the window, the middle of the window is used. Positions are saved in `session.json` (`phase1.slide_positions`) for resume.
- PDF windows are sent as a small PDF (or as text above 14 MB); PPTX as text plus up to 16 images.
- `PROMPT_REGOLE_SLIDE`: audio is the source; slides only fix terms, acronyms, numbers and formulas and may add a definition inline; slides the teacher does not explain are ignored.

## Audio + book

- During revision (`revision_service`) every macro block gets up to 15 book pages chosen by embeddings (keyword fallback) — no generation requests are added.
- `PROMPT_REGOLE_LIBRO_REVISIONE`: the book only clarifies or defines concepts already present, 1–2 sentences inline, no new topics.
- A revision with the book shorter than 75% of its input is rejected as degenerate and retried; after the retries the block is kept unrevised.

## Minutes and formulas

- Every `##`/`###` heading starts with `[[t=MM:SS]]` relative to its block; it becomes absolute seconds and then `data-t` in the HTML. The editor shows a chip with the minute: click it (or Alt+click a paragraph) and the audio player jumps there.
- Formulas are LaTeX (`$…$`, `$$…$$`) and become KaTeX nodes in the editor. "Esporta PDF" prints a clean page; "Copia per Google Docs" turns formulas into readable text.

## Suggestions (`services/lesson_planning.py`, no generation requests)

- Name: PDF/PPTX title or first line of the slides, else a cleaned file name.
- Chapter: PDF bookmarks scored with BM25 against the slides text (or the name); long chapters are narrowed to the best section. Applied automatically and editable.
- Quota: today's successful requests vs the model limit; lessons stopped by the daily quota resume ~5 minutes after the reset (00:00 Pacific).
- First run: `recommend_models` uses `models.get` (free) to pick the newest available model plus two fallbacks.
- Busy hours (15–21): the page offers to start at 21:30.

## Sessions

Audio-only lessons keep their historical session folder. With slides or book the folder is `lesson_<hash>` of audio + documents + pages; `session.json` stores `lesson`, `title`, `custom_title` and `course`.
