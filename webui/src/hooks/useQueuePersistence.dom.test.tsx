import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Dispatch } from 'react';
import type { ProcessingAction, FileItem } from '../appState';
import { useQueuePersistence } from './useQueuePersistence';

const QUEUE_KEY = 'jot.queue.v1';

function makeFile(overrides: Partial<FileItem> = {}): FileItem {
  return {
    id: 'f1', name: 'test.mp3', size: 1000, duration: 60, status: 'queued', progress: 0, phase: 0,
    ...overrides,
  };
}

beforeEach(() => { localStorage.clear(); });
afterEach(() => { localStorage.clear(); });

describe('useQueuePersistence hook', () => {
  it('restores queue from localStorage on mount', () => {
    const dispatch = vi.fn() as unknown as Dispatch<ProcessingAction>;
    const appendConsole = vi.fn();
    localStorage.setItem(QUEUE_KEY, JSON.stringify([{ id: 'a', name: 'a.mp3', size: 100, duration: 30, status: 'queued' }]));
    renderHook(() => useQueuePersistence([], 0, dispatch, appendConsole));
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: 'queue/add' }));
    expect(appendConsole).toHaveBeenCalledWith(expect.stringContaining('Coda ripristinata'));
  });

  it('does nothing when localStorage is empty', () => {
    const dispatch = vi.fn() as unknown as Dispatch<ProcessingAction>;
    renderHook(() => useQueuePersistence([], 0, dispatch, vi.fn()));
    expect(dispatch).not.toHaveBeenCalled();
  });

  it('does nothing when localStorage has empty array', () => {
    const dispatch = vi.fn() as unknown as Dispatch<ProcessingAction>;
    localStorage.setItem(QUEUE_KEY, JSON.stringify([]));
    renderHook(() => useQueuePersistence([], 0, dispatch, vi.fn()));
    expect(dispatch).not.toHaveBeenCalled();
  });

  it('persists queue to localStorage when structuralVersion changes', () => {
    const file = makeFile();
    const { rerender } = renderHook(
      ({ files, version }: { files: FileItem[]; version: number }) =>
        useQueuePersistence(files, version, vi.fn() as unknown as Dispatch<ProcessingAction>, vi.fn()),
      { initialProps: { files: [file], version: 0 } },
    );
    act(() => { rerender({ files: [file], version: 1 }); });
    const stored = localStorage.getItem(QUEUE_KEY);
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored!);
    expect(parsed[0].name).toBe('test.mp3');
  });

  it('removes queue from localStorage when files become empty', () => {
    localStorage.setItem(QUEUE_KEY, JSON.stringify([{ id: 'a', name: 'a.mp3' }]));
    const { rerender } = renderHook(
      ({ files, version }: { files: FileItem[]; version: number }) =>
        useQueuePersistence(files, version, vi.fn() as unknown as Dispatch<ProcessingAction>, vi.fn()),
      { initialProps: { files: [makeFile()], version: 1 } },
    );
    act(() => { rerender({ files: [], version: 2 }); });
    expect(localStorage.getItem(QUEUE_KEY)).toBeNull();
  });

  it('skips persist on structuralVersion 0 (initial mount)', () => {
    localStorage.removeItem(QUEUE_KEY);
    renderHook(() => useQueuePersistence([makeFile()], 0, vi.fn() as unknown as Dispatch<ProcessingAction>, vi.fn()));
    expect(localStorage.getItem(QUEUE_KEY)).toBeNull();
  });
});
