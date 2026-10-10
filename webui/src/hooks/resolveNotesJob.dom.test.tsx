import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DndContext } from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import type { FileItem } from '../appState';
import type { PywebviewApi } from '../bridge';
import { resolveNotesJob } from './useQueueProcessing';
import { QueueFileCard } from '../components/QueueFileCard';
import { ProcessingStatusBanner } from '../components/ProcessingStatusBanner';

const job: FileItem = {
  id: 'notes::s.pdf::b.pdf::1-5',
  name: 's.pdf',
  size: 10,
  duration: 0,
  path: 's.pdf',
  status: 'queued',
  progress: 0,
  phase: 0,
  kind: 'notes',
  notes: { slides: 24, bookPath: 'b.pdf', bookName: 'b.pdf', bookPages: '1-5', slidesPerChunk: 12, bookMode: 'auto' },
};

afterEach(() => vi.restoreAllMocks());

describe('resolveNotesJob', () => {
  it('builds the backend descriptor without media checks', async () => {
    const api: Partial<PywebviewApi> = { check_path_exists: vi.fn(async () => ({ ok: true, exists: true })) };
    const log = vi.fn();
    const res = await resolveNotesJob(job, api as PywebviewApi, log);
    expect(res).toEqual([expect.objectContaining({
      id: job.id,
      path: 's.pdf',
      kind: 'notes',
      book_path: 'b.pdf',
      book_pages: '1-5',
      slides_per_chunk: 12,
      book_mode: 'auto',
      duration: 0,
    })]);
    expect(log).not.toHaveBeenCalled();
  });

  it('stops when the book disappeared', async () => {
    const api: Partial<PywebviewApi> = {
      check_path_exists: vi.fn(async (p: string) => ({ ok: true, exists: p !== 'b.pdf' })),
    };
    const log = vi.fn();
    expect(await resolveNotesJob(job, api as PywebviewApi, log)).toEqual([]);
    expect(log.mock.calls[0][0]).toContain('PDF del libro non trovato');
  });
});

describe('notes UI bits', () => {
  it('queue card shows slides and book info', () => {
    render(
      <DndContext>
        <SortableContext items={[job.id]} strategy={verticalListSortingStrategy}>
          <QueueFileCard file={job} appState="idle" onRemove={vi.fn()} onRetry={vi.fn()} onPreview={vi.fn()} onOpenFile={vi.fn()} />
        </SortableContext>
      </DndContext>,
    );
    expect(screen.getByText('Appunti · 24 slide')).toBeTruthy();
    expect(screen.getByText('Libro p. 1-5 · solo pagine pertinenti')).toBeTruthy();
  });

  it('banner uses notes wording', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Fase 1/3: appunti (chunk 2/3)"
        currentModel="gemini-3.8-flash"
        activeProgress={40}
        workDone={{ chunks: 1, macro: 0 }}
        workTotals={{ chunks: 3, macro: 0 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        mode="notes"
      />,
    );
    expect(screen.getByText('Generazione appunti')).toBeTruthy();
    expect(screen.getByText('Blocco 2 di 3')).toBeTruthy();
    expect(screen.getByText('Appunti')).toBeTruthy();
    expect(screen.getByText('Documenti')).toBeTruthy();
  });
});
