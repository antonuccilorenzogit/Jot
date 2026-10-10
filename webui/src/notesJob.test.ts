import { describe, expect, it } from 'vitest';
import {
  buildNotesJob,
  clampSlidesPerChunk,
  countSlideBlocks,
  estimateNotesRequests,
  parsePageSelection,
} from './notesJob';
import { deserializeQueueFile, serializeQueueFile } from './hooks/useQueuePersistence';

describe('parsePageSelection', () => {
  it('selects the whole book when empty', () => {
    expect(parsePageSelection('  ', 120)).toEqual({ pages: 120 });
  });
  it('counts unique pages across ranges', () => {
    expect(parsePageSelection('10-12, 11; 20\u201321', 50)).toEqual({ pages: 5 });
  });
  it('rejects out of range and garbage', () => {
    expect(parsePageSelection('40-60', 50).error).toContain('fuori dal libro');
    expect(parsePageSelection('capitolo 2', 50).error).toContain('non è valido');
  });
});

describe('slide blocks (mirror of document_service.plan_slide_chunks)', () => {
  it('merges a tiny trailing block', () => {
    expect(countSlideBlocks(25, 12)).toBe(2);
    expect(countSlideBlocks(30, 12)).toBe(3);
    expect(countSlideBlocks(7, 12)).toBe(1);
    expect(countSlideBlocks(0, 12)).toBe(0);
  });
  it('clamps the block size', () => {
    expect(clampSlidesPerChunk(1)).toBe(3);
    expect(clampSlidesPerChunk(99)).toBe(40);
    expect(clampSlidesPerChunk(Number.NaN)).toBe(12);
  });
  it('estimates generation + revision requests', () => {
    expect(estimateNotesRequests(60, 12)).toBe(5 + 3);
    expect(estimateNotesRequests(8, 12)).toBe(2);
  });
});

describe('buildNotesJob', () => {
  const slides = { path: 'C:/l/slide.pdf', name: 'slide.pdf', size: 10, pages: 30, format: 'pdf' };
  const book = { path: 'C:/l/libro.pdf', name: 'libro.pdf', size: 99, pages: 400, format: 'pdf' };

  it('creates a queued notes item with a stable id', () => {
    const job = buildNotesJob(slides, book, ' 10-40 ', 15);
    expect(job).toMatchObject({
      id: 'notes::C:/l/slide.pdf::C:/l/libro.pdf::10-40::auto',
      path: 'C:/l/slide.pdf',
      status: 'queued',
      kind: 'notes',
      notes: { slides: 30, bookPath: 'C:/l/libro.pdf', bookName: 'libro.pdf', bookPages: '10-40', slidesPerChunk: 15, bookMode: 'auto' },
    });
  });

  it('keeps the legacy id and mode when the whole excerpt is requested', () => {
    const job = buildNotesJob(slides, book, '10-40', 15, 'full');
    expect(job.id).toBe('notes::C:/l/slide.pdf::C:/l/libro.pdf::10-40');
    expect(job.notes?.bookMode).toBe('full');
  });

  it('ignores page selection without a book', () => {
    const job = buildNotesJob(slides, null, '10-40', 12);
    expect(job.notes?.bookPages).toBeUndefined();
    expect(job.notes?.bookMode).toBeUndefined();
    expect(job.id).toBe('notes::C:/l/slide.pdf::::');
  });

  it('survives queue persistence', () => {
    const job = buildNotesJob(slides, book, '10-40', 15);
    const restored = deserializeQueueFile(JSON.parse(JSON.stringify(serializeQueueFile(job))), 0);
    expect(restored.kind).toBe('notes');
    expect(restored.notes).toEqual(job.notes);
  });

  it('keeps audio items unchanged in persistence', () => {
    const audio = { id: 'a', name: 'a.mp3', size: 1, duration: 2, status: 'queued' as const, progress: 0, phase: 0 };
    expect(serializeQueueFile(audio)).not.toHaveProperty('kind');
    expect(deserializeQueueFile(audio, 0)).not.toHaveProperty('kind');
  });
});
