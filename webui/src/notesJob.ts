/** Helpers for "Slide e appunti" jobs (mirror of jot/services/document_service.py). */
import type { BookMode, FileItem } from './appState';
import type { DocumentDescriptor } from './bridge';

export const DEFAULT_SLIDES_PER_CHUNK = 12;
export const MIN_SLIDES_PER_CHUNK = 3;
export const MAX_SLIDES_PER_CHUNK = 40;
export const MAX_BOOK_PAGES = 300;
/** Mirror of book_retrieval.DEFAULT_MAX_PAGES_PER_BLOCK. */
export const MAX_BOOK_PAGES_PER_BLOCK = 15;
export const FREE_TIER_DAILY_REQUESTS = 20;
/** The revision step works on ~22k characters: roughly 2 blocks of notes each. */
const NOTES_BLOCKS_PER_REVISION = 2;

export type PageSelection = { pages: number; error?: undefined } | { pages?: undefined; error: string };

/** Client-side mirror of document_service.parse_page_ranges (count only). */
export function parsePageSelection(spec: string, totalPages: number): PageSelection {
  const text = spec.trim();
  if (!text) return { pages: totalPages };
  const pages = new Set<number>();
  for (const raw of text.split(/[,;]/)) {
    const part = raw.trim();
    if (!part) continue;
    const range = part.match(/^(\d+)\s*[-–—]\s*(\d+)$/);
    let first: number;
    let last: number;
    if (range) {
      first = Number(range[1]);
      last = Number(range[2]);
    } else if (/^\d+$/.test(part)) {
      first = last = Number(part);
    } else {
      return { error: `"${part}" non è valido: usa un formato come 120-165, 170` };
    }
    if (first > last) [first, last] = [last, first];
    if (first < 1 || last > totalPages) {
      return { error: `Pagine ${first}-${last} fuori dal libro (${totalPages} pagine)` };
    }
    for (let p = first; p <= last; p += 1) pages.add(p);
  }
  if (pages.size === 0) return { error: 'Nessuna pagina selezionata' };
  return { pages: pages.size };
}

export function clampSlidesPerChunk(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_SLIDES_PER_CHUNK;
  return Math.min(MAX_SLIDES_PER_CHUNK, Math.max(MIN_SLIDES_PER_CHUNK, Math.round(value)));
}

/** Mirror of document_service.plan_slide_chunks (block count only). */
export function countSlideBlocks(totalSlides: number, slidesPerChunk: number): number {
  const size = clampSlidesPerChunk(slidesPerChunk);
  if (totalSlides <= 0) return 0;
  let blocks = Math.ceil(totalSlides / size);
  const tail = totalSlides - (blocks - 1) * size;
  if (blocks >= 2 && tail < Math.max(2, Math.floor(size / 3))) blocks -= 1;
  return blocks;
}

export function estimateNotesRequests(totalSlides: number, slidesPerChunk: number): number {
  const blocks = countSlideBlocks(totalSlides, slidesPerChunk);
  if (blocks === 0) return 0;
  return blocks + Math.max(1, Math.ceil(blocks / NOTES_BLOCKS_PER_REVISION));
}

export function buildNotesJob(
  slides: DocumentDescriptor,
  book: DocumentDescriptor | null,
  bookPages: string,
  slidesPerChunk: number,
  bookMode: BookMode = 'auto',
): FileItem {
  const pages = book ? bookPages.trim() : '';
  const mode: BookMode | undefined = book ? bookMode : undefined;
  return {
    id: `notes::${slides.path}::${book?.path ?? ''}::${pages}${mode === 'auto' ? '::auto' : ''}`,
    name: slides.name,
    size: slides.size,
    duration: 0,
    path: slides.path,
    status: 'queued',
    progress: 0,
    phase: 0,
    kind: 'notes',
    notes: {
      slides: slides.pages,
      bookPath: book?.path,
      bookName: book?.name,
      bookPages: pages || undefined,
      slidesPerChunk: clampSlidesPerChunk(slidesPerChunk),
      ...(mode ? { bookMode: mode } : {}),
    },
  };
}
