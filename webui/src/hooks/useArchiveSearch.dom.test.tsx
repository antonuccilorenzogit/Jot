import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useArchiveSearch } from './useArchiveSearch';
import type { ArchiveSession } from '../bridge';

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

const makeSession = (name: string, dateIso: string, dir: string): ArchiveSession => ({
  name,
  completed_at_iso: dateIso,
  html_path: `${dir}/index.html`,
  effective_model: 'gemini-2.5-flash',
  input_path: `${dir}/audio.mp3`,
  session_dir: dir,
});

describe('useArchiveSearch', () => {
  beforeEach(() => {
    setPywebview(undefined);
  });

  afterEach(() => {
    setPywebview(undefined);
  });

  it('filters and sorts sessions by name and dates', () => {
    const sessions: ArchiveSession[] = [
      makeSession('Biochimica Lezione 2', '2026-01-02T10:00:00Z', '/dir2'),
      makeSession('Anatomia Lezione 1', '2026-01-01T10:00:00Z', '/dir1'),
    ];

    const { result } = renderHook(() =>
      useArchiveSearch({
        sessions,
        editorSessionsMap: {},
      })
    );

    // Default: newest first
    expect(result.current.allSortedSessions[0].name).toBe('Biochimica Lezione 2');

    act(() => {
      result.current.setSort('name');
    });
    expect(result.current.allSortedSessions[0].name).toBe('Anatomia Lezione 1');

    act(() => {
      result.current.setSearch('Bio');
    });
    expect(result.current.allSortedSessions.length).toBe(1);
    expect(result.current.allSortedSessions[0].name).toBe('Biochimica Lezione 2');
  });

  it('performs debounced full-text search when enabled with >= 3 characters', async () => {
    vi.useFakeTimers();
    try {
      const searchMock = vi.fn().mockResolvedValue({
        ok: true,
        results: [
          {
            session_dir: '/dir1',
            name: 'Anatomia',
            html_path: '/dir1/index.html',
            completed_at_iso: '2026-01-01T10:00:00Z',
            snippets: [{ before: 'il ', match: 'fegato', after: ' produce bile' }],
            match_count: 1,
          },
        ],
        total: 1,
      });
      setPywebview({ search_sessions: searchMock });

      const { result } = renderHook(() =>
        useArchiveSearch({
          sessions: [],
          editorSessionsMap: {},
        })
      );

      act(() => {
        result.current.setFullTextMode(true);
        result.current.setSearch('fegato');
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(450);
      });

      expect(searchMock).toHaveBeenCalledWith('fegato', 100);
      expect(result.current.ftResults?.length).toBe(1);
      expect(result.current.ftTotal).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
