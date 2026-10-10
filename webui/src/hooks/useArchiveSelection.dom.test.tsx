import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useArchiveSelection } from './useArchiveSelection';
import type { ArchiveFolder, ArchiveSession } from '../bridge';

const makeSession = (name: string, dir: string): ArchiveSession => ({
  name,
  completed_at_iso: '2026-01-01T10:00:00Z',
  html_path: `${dir}/index.html`,
  effective_model: 'gemini-2.5-flash',
  input_path: `${dir}/audio.mp3`,
  session_dir: dir,
});

describe('useArchiveSelection', () => {
  it('manages single and multi-selection of sessions', () => {
    const sessions = [makeSession('S1', '/s1'), makeSession('S2', '/s2')];
    const folders: ArchiveFolder[] = [{ id: 'f1', name: 'Folder 1', color: 'blue', session_dirs: [] }];
    const onFoldersChange = vi.fn();
    const setDeleteMultipleConfirm = vi.fn();

    const { result } = renderHook(() =>
      useArchiveSelection({
        sessions,
        folders,
        onFoldersChange,
        sessionPageData: sessions,
        setDeleteMultipleConfirm,
      })
    );

    expect(result.current.selectedSessionDirs.size).toBe(0);

    act(() => {
      result.current.toggleSelectSession('/s1');
    });
    expect(result.current.selectedSessionDirs.has('/s1')).toBe(true);

    act(() => {
      result.current.selectAllSessions();
    });
    expect(result.current.selectedSessionDirs.size).toBe(2);

    act(() => {
      result.current.handleDeselectOrRestore();
    });
    // Should restore previous manual selection (/s1)
    expect(result.current.selectedSessionDirs.size).toBe(1);
    expect(result.current.selectedSessionDirs.has('/s1')).toBe(true);

    act(() => {
      result.current.clearSelection();
    });
    expect(result.current.selectedSessionDirs.size).toBe(0);
  });

  it('performs bulk folder assignments and removals', () => {
    const sessions = [makeSession('S1', '/s1')];
    const folders: ArchiveFolder[] = [{ id: 'f1', name: 'Folder 1', color: 'blue', session_dirs: [] }];
    const onFoldersChange = vi.fn();
    const setDeleteMultipleConfirm = vi.fn();

    const { result } = renderHook(() =>
      useArchiveSelection({
        sessions,
        folders,
        onFoldersChange,
        sessionPageData: sessions,
        setDeleteMultipleConfirm,
      })
    );

    act(() => {
      result.current.bulkAssignToFolder('f1', ['/s1']);
    });

    expect(onFoldersChange).toHaveBeenCalledWith([
      { id: 'f1', name: 'Folder 1', color: 'blue', session_dirs: ['/s1'] },
    ]);
  });
});
