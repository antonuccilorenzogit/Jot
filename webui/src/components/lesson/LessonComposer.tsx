import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AppStatus, AudioPart, FileDescriptor, FileItem } from '../../appState';
import type { DocumentDescriptor, LessonSuggestion, QuotaSnapshot } from '../../bridge';
import { MAX_BOOK_PAGES, parsePageSelection } from '../../notesJob';
import {
  buildLessonJob,
  estimateLessonRequests,
  todayIso,
  totalAudioSeconds,
  formatClock,
  isBusyHour,
  lessonMode,
  nextQuietStart,
} from '../../lessonJob';
import { SourceDial } from './Dial';

export interface ScheduledLesson {
  at: number;
  name: string;
}

export interface LessonComposerProps {
  apiReady: boolean;
  appState: AppStatus;
  queuedIds: ReadonlySet<string>;
  courses: string[];
  quota: QuotaSnapshot | null;
  scheduled: ScheduledLesson | null;
  onStart: (job: FileItem) => void;
  onSchedule: (job: FileItem, at: number) => void;
  onCancelSchedule: () => void;
  appendConsole?: (msg: string) => void;
  /** Override for tests. */
  now?: () => Date;
}

function audioClock(seconds: number): { value: string; unit: string } {
  const total = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return { value: `${h}:${String(m).padStart(2, '0')}`, unit: h === 1 && m === 0 ? 'ora' : 'ore' };
  return { value: String(Math.max(1, m)), unit: 'min' };
}

function bookRangeLabel(pages: string, total: number): { value: string; unit: string } {
  const clean = pages.trim();
  if (!clean) return { value: String(total), unit: 'pagine' };
  const single = clean.match(/^(\d+)\s*[-–]\s*(\d+)$/);
  if (single) return { value: `${single[1]}–${single[2]}`, unit: 'pagine' };
  const parsed = parsePageSelection(clean, total);
  return { value: String(parsed.pages ?? '–'), unit: 'pagine' };
}

function describeReset(iso: string | undefined): string {
  if (!iso) return 'domani mattina';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'domani mattina';
  return `alle ${formatClock(date)}`;
}

export const LessonComposer = memo(function LessonComposer({
  apiReady,
  appState,
  queuedIds,
  courses,
  quota,
  scheduled,
  onStart,
  onSchedule,
  onCancelSchedule,
  appendConsole,
  now = () => new Date(),
}: LessonComposerProps) {
  const [audio, setAudio] = useState<FileDescriptor | null>(null);
  const [parts, setParts] = useState<AudioPart[]>([]);
  const [lessonDate, setLessonDate] = useState(() => todayIso(now()));
  const [slides, setSlides] = useState<DocumentDescriptor | null>(null);
  const [book, setBook] = useState<DocumentDescriptor | null>(null);
  const [bookPages, setBookPages] = useState('');
  const [title, setTitle] = useState('');
  const [titleTouched, setTitleTouched] = useState(false);
  const [course, setCourse] = useState('');
  const [chapter, setChapter] = useState<LessonSuggestion['chapter'] | null>(null);
  const [chapterApplied, setChapterApplied] = useState(false);
  const [pagesTouched, setPagesTouched] = useState(false);
  const [picking, setPicking] = useState<'audio' | 'slides' | 'book' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const suggestSeq = useRef(0);

  const sources = useMemo(() => ({ audio, slides, book, parts }), [audio, slides, book, parts]);
  const mode = lessonMode(sources);
  const hasAny = Boolean(audio || slides || book);

  // Lesson name and book chapter, guessed locally from the files.
  useEffect(() => {
    const api = window.pywebview?.api;
    if (!api?.suggest_lesson || !hasAny) return;
    const seq = ++suggestSeq.current;
    void api.suggest_lesson(audio?.path ?? null, slides?.path ?? null, book?.path ?? null)
      .then(res => {
        if (seq !== suggestSeq.current || !res?.ok) return;
        if (!titleTouched) setTitle(res.title || '');
        setChapter(res.chapter ?? null);
        // The suggested chapter is used right away; the pages stay editable.
        if (res.chapter && !pagesTouched) {
          setBookPages(res.chapter.pages);
          setChapterApplied(true);
        }
      })
      .catch(() => {});
  }, [audio?.path, slides?.path, book?.path, hasAny, titleTouched, pagesTouched]);

  /** Second (third...) recording of the same lesson: one set of notes at the end. */
  const addPart = useCallback(async () => {
    const api = window.pywebview?.api;
    if (!api?.ask_media_file) return;
    setError(null);
    setPicking('audio');
    try {
      const file = await api.ask_media_file();
      if (file?.path) {
        setParts(prev => (prev.some(p => p.path === file.path) || file.path === audio?.path
          ? prev
          : [...prev, { path: file.path as string, name: file.name, size: file.size, duration: Number(file.duration || 0) }]));
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPicking(null);
    }
  }, [audio?.path]);

  const pick = useCallback(async (kind: 'audio' | 'slides' | 'book') => {
    const api = window.pywebview?.api;
    setError(null);
    if (kind === 'audio') {
      if (!api?.ask_media_file) { setError('Selezione file disponibile solo nell\'app desktop.'); return; }
      setPicking('audio');
      try {
        const file = await api.ask_media_file();
        if (file?.path) setAudio(file);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setPicking(null);
      }
      return;
    }
    if (!api?.ask_document_file) { setError('Selezione file disponibile solo nell\'app desktop.'); return; }
    setPicking(kind);
    try {
      const res = await api.ask_document_file(kind);
      if (res?.cancelled) return;
      if (!res?.ok || !res.file) { setError(res?.error || 'Impossibile leggere il file selezionato.'); return; }
      if (kind === 'slides') setSlides(res.file);
      else { setBook(res.file); setBookPages(''); setChapterApplied(false); setPagesTouched(false); }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPicking(null);
    }
  }, []);

  const selection = book ? parsePageSelection(bookPages, book.pages) : null;
  const bookError = selection?.error
    ?? (selection?.pages !== undefined && selection.pages > MAX_BOOK_PAGES
      ? `Al massimo ${MAX_BOOK_PAGES} pagine: indica solo i capitoli della lezione.`
      : null);

  const requests = estimateLessonRequests(sources);
  const job = useMemo(
    () => buildLessonJob(sources, { bookPages, title, course, lessonDate }),
    [sources, bookPages, title, course, lessonDate],
  );
  const alreadyQueued = job ? queuedIds.has(job.id) : false;
  const isBusy = appState === 'processing' || appState === 'canceling';
  const canStart = Boolean(job) && !bookError && !alreadyQueued && apiReady && picking === null && appState !== 'canceling' && !scheduled;

  const reset = useCallback(() => {
    setAudio(null); setParts([]); setSlides(null); setBook(null); setBookPages('');
    setTitle(''); setTitleTouched(false); setChapter(null); setChapterApplied(false); setPagesTouched(false); setError(null);
  }, []);

  const handleStart = useCallback(() => {
    if (!job || !canStart) return;
    onStart(job);
    appendConsole?.(`Lezione "${job.title || job.name}" ${isBusy ? 'aggiunta alla coda' : 'avviata'}.`);
    reset();
  }, [appendConsole, canStart, isBusy, job, onStart, reset]);

  const current = now();
  const quiet = nextQuietStart(current);
  const showScheduleHint = canStart && !isBusy && isBusyHour(current);
  const handleSchedule = useCallback(() => {
    if (!job || !canStart) return;
    onSchedule(job, quiet.getTime());
    appendConsole?.(`Lezione "${job.title || job.name}" programmata per le ${formatClock(quiet)}.`);
    reset();
  }, [appendConsole, canStart, job, onSchedule, quiet, reset]);

  let summary: string;
  if (mode === 'empty') summary = 'Aggiungi l’audio o le slide';
  else if (mode === 'invalid') summary = 'Il libro va insieme all’audio o alle slide';
  else if (quota && requests > quota.remaining && !quota.has_reserve) {
    summary = quota.remaining > 0
      ? `Circa ${requests} richieste: oggi ne restano ${quota.remaining}. Il resto riparte da solo ${describeReset(quota.reset_at)}, con l’app aperta.`
      : `Quota di oggi finita: parte da sola ${describeReset(quota.reset_at)}, con l’app aperta.`;
  } else if (quota) {
    summary = `Questa lezione: circa ${requests} ${requests === 1 ? 'richiesta' : 'richieste'} · oggi ne restano ${quota.remaining} su ${quota.limit}`;
  } else {
    summary = `Questa lezione: circa ${requests} ${requests === 1 ? 'richiesta' : 'richieste'}`;
  }

  const audioFace = audio ? audioClock(totalAudioSeconds(sources)) : null;
  const bookFace = book ? bookRangeLabel(bookPages, book.pages) : null;
  const sourcesReady = mode === 'audio' || mode === 'notes';

  return (
    <section className="lesson-composer" aria-labelledby="lesson-title">
      <h1 id="lesson-title" className="lesson-heading">Nuova lezione</h1>

      <div className="lesson-dials">
        <div className="lesson-source">
          <SourceDial
            label="Audio"
            ariaLabel={audio ? `Audio: ${audio.name}${parts.length ? ` e altre ${parts.length} parti` : ''}. Clicca per cambiarlo` : 'Aggiungi audio'}
            filled={Boolean(audio)}
            value={audioFace?.value}
            unit={audioFace?.unit}
            busy={picking === 'audio'}
            disabled={!apiReady || picking !== null}
            onClick={() => void pick('audio')}
          />
          <span className="lesson-source-label">Audio</span>
          {audio ? (
            <>
              <span className="lesson-source-file" title={audio.path}>{audio.name}</span>
              {parts.map((part, index) => (
                <span key={part.path} className="lesson-source-part">
                  <span className="lesson-source-file" title={part.path}>+ {part.name}</span>
                  <button
                    type="button"
                    className="lesson-link is-small"
                    aria-label={`Rimuovi parte ${index + 2}`}
                    onClick={() => setParts(prev => prev.filter(p => p.path !== part.path))}
                  >
                    ×
                  </button>
                </span>
              ))}
              <span className="lesson-source-actions">
                {parts.length < 3 && (
                  <button type="button" className="lesson-link" onClick={() => void addPart()} disabled={picking !== null}>
                    {parts.length === 0 ? '+ Seconda parte' : '+ Un’altra parte'}
                  </button>
                )}
                <button type="button" className="lesson-link" onClick={() => { setAudio(null); setParts([]); }}>Rimuovi</button>
              </span>
            </>
          ) : <span className="lesson-source-file">Registrazione della lezione</span>}
        </div>

        <div className="lesson-source">
          <SourceDial
            label="Slide"
            ariaLabel={slides ? `Slide: ${slides.name}, ${slides.pages} slide. Clicca per cambiarle` : 'Aggiungi slide'}
            filled={Boolean(slides)}
            value={slides?.pages}
            unit="slide"
            busy={picking === 'slides'}
            disabled={!apiReady || picking !== null}
            onClick={() => void pick('slides')}
          />
          <span className="lesson-source-label">Slide</span>
          {slides ? (
            <>
              <span className="lesson-source-file" title={slides.path}>{slides.name}</span>
              <button type="button" className="lesson-link" onClick={() => setSlides(null)}>Rimuovi</button>
            </>
          ) : <span className="lesson-source-file">PDF o PowerPoint</span>}
        </div>

        <div className="lesson-source">
          <SourceDial
            label="Libro"
            ariaLabel={book ? `Libro: ${book.name}. Clicca per cambiarlo` : 'Aggiungi libro, facoltativo'}
            filled={Boolean(book)}
            ringMuted={!sourcesReady}
            value={bookFace?.value}
            unit={bookFace?.unit}
            busy={picking === 'book'}
            disabled={!apiReady || picking !== null}
            onClick={() => void pick('book')}
          />
          <span className="lesson-source-label">Libro</span>
          {book ? (
            <>
              <span className="lesson-source-file" title={book.path}>{book.name}</span>
              <button type="button" className="lesson-link" onClick={() => { setBook(null); setBookPages(''); setChapterApplied(false); setPagesTouched(false); }}>Rimuovi</button>
            </>
          ) : <span className="lesson-source-file">Facoltativo</span>}
        </div>
      </div>

      {hasAny && (
        <div className="lesson-details">
          <label className="lesson-field">
            <span className="lesson-field-label">Nome</span>
            <input
              className="lesson-input"
              value={title}
              placeholder={audio?.name || slides?.name || 'Nome della lezione'}
              onChange={e => { setTitle(e.target.value); setTitleTouched(true); }}
              maxLength={120}
              aria-label="Nome della lezione"
            />
          </label>
          <label className="lesson-field is-date">
            <span className="lesson-field-label">Data</span>
            <input
              className="lesson-input"
              type="date"
              value={lessonDate}
              max={todayIso(now())}
              onChange={e => setLessonDate(e.target.value || todayIso(now()))}
              aria-label="Data della lezione"
            />
          </label>
          <label className="lesson-field">
            <span className="lesson-field-label">Corso</span>
            <input
              className="lesson-input"
              value={course}
              placeholder="Facoltativo"
              list="lesson-courses"
              onChange={e => setCourse(e.target.value)}
              maxLength={80}
              aria-label="Corso"
            />
            <datalist id="lesson-courses">
              {courses.map(c => <option key={c} value={c} />)}
            </datalist>
          </label>
          {book && (
            <label className="lesson-field">
              <span className="lesson-field-label">Pagine</span>
              <input
                className="lesson-input"
                value={bookPages}
                placeholder={`Tutto il libro (${book.pages})`}
                onChange={e => { setBookPages(e.target.value); setChapterApplied(false); setPagesTouched(true); }}
                aria-label="Pagine del libro"
                aria-invalid={Boolean(bookError)}
              />
            </label>
          )}
          {book && chapter && chapterApplied && bookPages.trim() === chapter.pages && (
            <p className="lesson-hint">
              Ho scelto il capitolo <strong>{chapter.title}</strong>: puoi cambiare le pagine.
            </p>
          )}
          {book && chapter && !chapterApplied && bookPages.trim() !== chapter.pages && (
            <p className="lesson-hint">
              Sembra il capitolo <strong>{chapter.title}</strong> (pagine {chapter.pages.replace('-', '–')}).{' '}
              <button type="button" className="lesson-link is-inline" onClick={() => { setBookPages(chapter.pages); setChapterApplied(true); }}>
                Usa queste pagine
              </button>
            </p>
          )}
          {bookError && <p className="lesson-hint is-error" role="alert">{bookError}</p>}
        </div>
      )}

      {error && <p className="lesson-hint is-error" role="alert">{error}</p>}

      <div className="lesson-start">
        {scheduled ? (
          <>
            <span className="lesson-scheduled">Partenza alle {formatClock(new Date(scheduled.at))} · {scheduled.name}</span>
            <button type="button" className="pill-button is-quiet" onClick={onCancelSchedule}>Annulla</button>
          </>
        ) : (
          <button type="button" className="pill-button is-primary is-large" disabled={!canStart} onClick={handleStart}>
            {alreadyQueued ? 'Già in coda' : isBusy ? 'Aggiungi alla coda' : 'Avvia'}
          </button>
        )}
        <span className="lesson-summary" aria-live="polite">{summary}</span>
        {sourcesReady && (
          <span className="lesson-summary is-soft">
            Lezione e sintesi finiranno in Documenti › jot › {course.trim() || 'Senza corso'}
          </span>
        )}
        {showScheduleHint && (
          <span className="lesson-summary is-soft">
            Nel pomeriggio i server di Google sono spesso carichi.{' '}
            <button type="button" className="lesson-link is-inline" onClick={handleSchedule}>
              Avvia alle {formatClock(quiet)}
            </button>
          </span>
        )}
      </div>
    </section>
  );
});
