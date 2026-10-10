import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import type { FileItem } from '../../appState';
import type { QuotaSnapshot } from '../../bridge';
import { LessonComposer, type LessonComposerProps } from './LessonComposer';

const audio = { id: 'a1', name: 'Reti_lezione_5.m4a', size: 1000, duration: 2 * 3600 + 28 * 60, path: 'C:\\Reti_lezione_5.m4a' };
const slides = { path: 'C:\\slide.pdf', name: 'slide.pdf', size: 2048, pages: 104, format: 'pdf' };
const book = { path: 'C:\\libro.pdf', name: 'Kurose.pdf', size: 4096, pages: 600, format: 'pdf' };

function mockApi(extra: Record<string, unknown> = {}) {
  const api = {
    ask_media_file: vi.fn(async () => audio),
    ask_document_file: vi.fn(async (purpose: 'slides' | 'book') => ({ ok: true, file: purpose === 'slides' ? slides : book })),
    suggest_lesson: vi.fn(async () => ({ ok: true, title: 'Reti lezione 5', chapter: { title: 'Capitolo 3 Il livello di trasporto', pages: '97-176', count: 80 } })),
    ...extra,
  };
  (window as unknown as { pywebview: { api: typeof api } }).pywebview = { api };
  return api;
}

function setup(props: Partial<LessonComposerProps> = {}) {
  const onStart = vi.fn<(job: FileItem) => void>();
  const onSchedule = vi.fn<(job: FileItem, at: number) => void>();
  render(
    <LessonComposer
      apiReady
      appState="idle"
      queuedIds={new Set()}
      courses={['Reti di calcolatori', 'Analisi 2']}
      quota={null}
      scheduled={null}
      onStart={onStart}
      onSchedule={onSchedule}
      onCancelSchedule={vi.fn()}
      now={() => new Date(2026, 9, 10, 10, 0)}
      {...props}
    />,
  );
  return { onStart, onSchedule };
}

async function click(name: string) {
  await act(async () => { fireEvent.click(screen.getByRole('button', { name })); });
}

afterEach(() => {
  delete (window as unknown as { pywebview?: unknown }).pywebview;
  vi.restoreAllMocks();
});

describe('LessonComposer', () => {
  it('starts empty and explains what is needed', () => {
    mockApi();
    setup();
    expect(screen.getByRole('heading', { name: 'Nuova lezione' })).toBeTruthy();
    expect(screen.getByText('Aggiungi l’audio o le slide')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Avvia' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('refuses the book alone', async () => {
    mockApi();
    setup();
    await click('Aggiungi libro, facoltativo');
    expect(screen.getByText('Il libro va insieme all’audio o alle slide')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Avvia' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('builds an audio lesson with slides, book chapter, name and course', async () => {
    const api = mockApi();
    const { onStart } = setup();
    await click('Aggiungi audio');
    await click('Aggiungi slide');
    await click('Aggiungi libro, facoltativo');
    expect(api.suggest_lesson).toHaveBeenCalledWith(audio.path, slides.path, book.path);
    expect(screen.getByText('2:28')).toBeTruthy();
    expect((screen.getByLabelText('Nome della lezione') as HTMLInputElement).value).toBe('Reti lezione 5');
    // 2h28 = 11 blocks + 4 revisions
    expect(screen.getByText('Circa 15 richieste su 20 oggi')).toBeTruthy();

    // the suggested chapter is applied at once and can still be changed
    expect((screen.getByLabelText('Pagine del libro') as HTMLInputElement).value).toBe('97-176');
    expect(screen.getByText('97–176')).toBeTruthy();
    expect(screen.getByText(/Ho scelto il capitolo/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Pagine del libro'), { target: { value: '100-120' } });
    await click('Usa queste pagine');
    expect((screen.getByLabelText('Pagine del libro') as HTMLInputElement).value).toBe('97-176');

    fireEvent.change(screen.getByLabelText('Corso'), { target: { value: 'Reti di calcolatori' } });
    await click('Avvia');
    expect(onStart).toHaveBeenCalledTimes(1);
    const job = onStart.mock.calls[0][0];
    expect(job).toMatchObject({
      kind: 'audio',
      path: audio.path,
      name: 'Reti lezione 5',
      title: 'Reti lezione 5',
      course: 'Reti di calcolatori',
      lesson: { slidesPath: slides.path, slidesCount: 104, bookPath: book.path, bookPages: '97-176' },
    });
    expect(job.id.startsWith('lesson::')).toBe(true);
    // the page is ready for the next lesson
    expect(screen.getByRole('button', { name: 'Aggiungi audio' })).toBeTruthy();
  });

  it('slides alone become a notes job', async () => {
    mockApi({ suggest_lesson: vi.fn(async () => ({ ok: true, title: null, chapter: null })) });
    const { onStart } = setup();
    await click('Aggiungi slide');
    await click('Avvia');
    expect(onStart.mock.calls[0][0]).toMatchObject({ kind: 'notes', path: slides.path });
  });

  it('warns when today\'s quota is not enough', async () => {
    mockApi();
    const quota: QuotaSnapshot = { used: 12, limit: 20, remaining: 8, exhausted: false, has_reserve: false, reset_at: '2026-10-11T07:00:00Z' };
    setup({ quota });
    await click('Aggiungi audio');
    expect(screen.getByText(/oggi ne restano 8\. Il resto riparte da solo alle \d\d:\d\d/)).toBeTruthy();
  });

  it('suggests a quieter start in the afternoon', async () => {
    mockApi();
    const { onSchedule, onStart } = setup({ now: () => new Date(2026, 9, 10, 16, 0) });
    await click('Aggiungi audio');
    expect(screen.getByText(/spesso carichi/)).toBeTruthy();
    await click('Avvia alle 21:30');
    expect(onStart).not.toHaveBeenCalled();
    expect(onSchedule).toHaveBeenCalledTimes(1);
    const at = new Date(onSchedule.mock.calls[0][1]);
    expect([at.getHours(), at.getMinutes()]).toEqual([21, 30]);
  });

  it('shows a scheduled lesson with a way to cancel it', () => {
    mockApi();
    const onCancel = vi.fn();
    setup({ scheduled: { at: new Date(2026, 9, 10, 21, 30).getTime(), name: 'Reti 5' }, onCancelSchedule: onCancel });
    expect(screen.getByText('Partenza alle 21:30 · Reti 5')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Annulla' }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('adds to the queue while another lesson is running', async () => {
    mockApi();
    setup({ appState: 'processing' });
    await click('Aggiungi audio');
    expect(screen.getByRole('button', { name: 'Aggiungi alla coda' })).toBeTruthy();
  });
});
