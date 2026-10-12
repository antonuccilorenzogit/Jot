/** "Nuova lezione": audio, slides and book in any sensible combination. */
import type { AudioPart, FileDescriptor, FileItem } from './appState';
import type { DocumentDescriptor } from './bridge';
import { DEFAULT_SLIDES_PER_CHUNK, buildNotesJob, estimateNotesRequests } from './notesJob';

/** Mirrors pipeline_settings: 15 minute blocks with 30 s overlap. */
export const CHUNK_SECONDS = 15 * 60;
export const OVERLAP_SECONDS = 30;
/** Revision blocks are ~22k characters; a lesson gives ~520 characters a minute. */
const REVISION_CHARS = 22_000;
const CHARS_PER_MINUTE = 520;

export type LessonSources = {
  audio: FileDescriptor | null;
  slides: DocumentDescriptor | null;
  book: DocumentDescriptor | null;
  /** Further recordings of the same lesson (second part after the break...). */
  parts?: AudioPart[];
};

/** One more request writes the "sintesi" of every lesson. */
export const SUMMARY_REQUESTS = 1;

export function totalAudioSeconds(sources: Pick<LessonSources, 'audio' | 'parts'>): number {
  const main = Number(sources.audio?.duration || 0);
  return main + (sources.parts ?? []).reduce((sum, p) => sum + Number(p.duration || 0), 0);
}

/** Today in the user's time zone, YYYY-MM-DD. */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export type LessonMode = 'audio' | 'notes' | 'invalid' | 'empty';

export function lessonMode({ audio, slides, book }: LessonSources): LessonMode {
  if (audio) return 'audio';
  if (slides) return 'notes';
  if (book) return 'invalid';
  return 'empty';
}

export function estimateAudioRequests(durationSec: number): { chunks: number; revisions: number; total: number } {
  const duration = Math.max(0, Math.round(durationSec || 0));
  if (duration <= 0) return { chunks: 0, revisions: 0, total: 0 };
  const step = CHUNK_SECONDS - OVERLAP_SECONDS;
  const chunks = Math.ceil(duration / step);
  const revisions = Math.max(1, Math.ceil((duration / 60) * CHARS_PER_MINUTE / REVISION_CHARS));
  return { chunks, revisions, total: chunks + revisions };
}

export function estimateLessonRequests(sources: LessonSources): number {
  const mode = lessonMode(sources);
  if (mode === 'audio') return estimateAudioRequests(totalAudioSeconds(sources)).total + SUMMARY_REQUESTS;
  if (mode === 'notes' && sources.slides) {
    return estimateNotesRequests(sources.slides.pages, DEFAULT_SLIDES_PER_CHUNK) + SUMMARY_REQUESTS;
  }
  return 0;
}

export function lessonJobId(sources: LessonSources, bookPages: string): string {
  const { audio, slides, book, parts = [] } = sources;
  if (!audio) return '';
  if (!slides && !book && parts.length === 0) return audio.id || audio.path || audio.name;
  const extra = parts.length ? `::+${parts.map(p => p.path).join('+')}` : '';
  return `lesson::${audio.path}::${slides?.path ?? ''}::${book?.path ?? ''}::${book ? bookPages.trim() : ''}${extra}`;
}

export function buildLessonJob(
  sources: LessonSources,
  options: { bookPages: string; title: string; course: string; lessonDate?: string },
): FileItem | null {
  const { audio, slides, book, parts = [] } = sources;
  const title = options.title.trim();
  const course = options.course.trim();
  const extra = {
    ...(title ? { title } : {}),
    ...(course ? { course } : {}),
    ...(options.lessonDate ? { lessonDate: options.lessonDate } : {}),
  };
  const mode = lessonMode(sources);
  if (mode === 'notes' && slides) {
    const job = buildNotesJob(slides, book, options.bookPages, DEFAULT_SLIDES_PER_CHUNK, 'auto');
    return { ...job, ...extra, name: title || job.name };
  }
  if (mode !== 'audio' || !audio) return null;
  const pages = book ? options.bookPages.trim() : '';
  return {
    id: lessonJobId(sources, options.bookPages),
    name: title || audio.name,
    size: audio.size + parts.reduce((sum, p) => sum + Number(p.size || 0), 0),
    duration: totalAudioSeconds(sources),
    path: audio.path,
    status: 'queued',
    progress: 0,
    phase: 0,
    kind: 'audio',
    ...extra,
    ...(slides || book || parts.length
      ? {
          lesson: {
            ...(slides ? { slidesPath: slides.path, slidesName: slides.name, slidesCount: slides.pages } : {}),
            ...(book ? { bookPath: book.path, bookName: book.name, ...(pages ? { bookPages: pages } : {}) } : {}),
            ...(parts.length ? { audioParts: parts.map(p => ({ ...p })) } : {}),
          },
        }
      : {}),
  };
}

/** Hours in which Google's servers are usually busiest (afternoon in Italy). */
export const BUSY_HOURS = { from: 15, to: 21 } as const;
export const QUIET_START = { hour: 21, minute: 30 } as const;

export function isBusyHour(date: Date): boolean {
  const h = date.getHours();
  return h >= BUSY_HOURS.from && h < BUSY_HOURS.to;
}

export function nextQuietStart(now: Date): Date {
  const at = new Date(now);
  at.setHours(QUIET_START.hour, QUIET_START.minute, 0, 0);
  if (at.getTime() <= now.getTime()) at.setDate(at.getDate() + 1);
  return at;
}

export function formatClock(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.round((total % 3600) / 60);
  if (h <= 0) return `${m} min`;
  return m > 0 ? `${h} h ${m} min` : `${h} h`;
}
