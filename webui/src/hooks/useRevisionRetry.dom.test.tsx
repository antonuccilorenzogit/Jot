import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useRevisionRetry } from './useRevisionRetry';
import { type FileItem, type FileDonePayload } from '../appState';
import { type ArchiveSession, type PywebviewApi } from '../bridge';

describe('useRevisionRetry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it('triggers retry_failed_revision_blocks for an active file and updates store on success', async () => {
    const retryMock = vi.fn().mockResolvedValue({
      ok: true,
      session_dir: '/sessions/session_1',
      html_path: '/sessions/session_1/output.html',
      effective_model: 'gemini-2.5-flash',
      remaining_failed_blocks: [],
    });
    window.pywebview = {
      api: {
        retry_failed_revision_blocks: retryMock,
      } as unknown as PywebviewApi,
    };

    const files: FileItem[] = [
      { id: 'f1', path: '/test/audio.mp3', name: 'audio.mp3', size: 1000, duration: 10, status: 'done', progress: 100, phase: 3 },
    ];
    const filesRef = { current: files };
    const archiveSessions: ArchiveSession[] = [];
    const archiveSessionsRef = { current: archiveSessions };
    const normalizeSessionDir = (d: string) => d.replace(/\\/g, '/').toLowerCase();
    const dispatch = vi.fn();
    const setArchiveSessions = vi.fn();
    const refreshArchiveSessions = vi.fn().mockResolvedValue(undefined);
    const addNotification = vi.fn();
    const setConfirmAction = vi.fn();

    const { result } = renderHook(() =>
      useRevisionRetry({
        filesRef,
        archiveSessionsRef,
        normalizeSessionDir,
        dispatch,
        setArchiveSessions,
        refreshArchiveSessions,
        addNotification,
        setConfirmAction,
      }),
    );

    await act(async () => {
      await result.current.handleRetryFailedRevisionBlocks('/sessions/session_1', 'f1');
    });

    expect(retryMock).toHaveBeenCalledWith('/sessions/session_1');
    expect(dispatch).toHaveBeenCalledWith({ type: 'queue/set_retrying_blocks', id: 'f1', value: true });
    expect(dispatch).toHaveBeenCalledWith({ type: 'app/set_status', status: 'processing' });
    expect(dispatch).toHaveBeenCalledWith({
      type: 'queue/update_revision_failed_blocks',
      fileId: 'f1',
      sessionDir: '/sessions/session_1',
      blocks: [],
      htmlPath: '/sessions/session_1/output.html',
      effectiveModel: 'gemini-2.5-flash',
    });
    expect(dispatch).toHaveBeenCalledWith({ type: 'queue/set_retrying_blocks', id: 'f1', value: false });
    expect(dispatch).toHaveBeenCalledWith({ type: 'app/set_status', status: 'idle' });
    expect(addNotification).toHaveBeenCalledWith('Elaborazione completata', 'Blocchi mancanti revisionati e HTML aggiornato.', 'success', 'processing');
  });

  it('notifies warning when revision fails partially', () => {
    const filesRef = { current: [] };
    const archiveSessionsRef = { current: [] };
    const normalizeSessionDir = (d: string) => d.replace(/\\/g, '/').toLowerCase();
    const dispatch = vi.fn();
    const setArchiveSessions = vi.fn();
    const refreshArchiveSessions = vi.fn().mockResolvedValue(undefined);
    const addNotification = vi.fn();
    const setConfirmAction = vi.fn();

    const { result } = renderHook(() =>
      useRevisionRetry({
        filesRef,
        archiveSessionsRef,
        normalizeSessionDir,
        dispatch,
        setArchiveSessions,
        refreshArchiveSessions,
        addNotification,
        setConfirmAction,
      }),
    );

    act(() => {
      const payload: FileDonePayload = {
        index: 0,
        id: 'f1',
        output_html: '/sessions/session_1/output.html',
        output_dir: '/sessions/session_1',
        revision_failed_blocks: [1, 2],
      };
      result.current.handleRevisionWarning(payload);
    });

    expect(addNotification).toHaveBeenCalledWith(
      'Completata con avvisi',
      'Completata con avvisi: 2 sezioni sono state incluse senza revisione AI.',
      'warning',
      'processing',
      expect.objectContaining({
        actionType: 'retry_failed_revision_blocks',
      }),
    );
  });

  it('does not send notification when retry is cancelled with 0 blocks retried', async () => {
    const retryMock = vi.fn().mockResolvedValue({
      ok: false,
      cancelled: true,
      error: 'Operazione annullata.',
      remaining_failed_blocks: [1, 2],
    });
    window.pywebview = {
      api: {
        retry_failed_revision_blocks: retryMock,
      } as unknown as PywebviewApi,
    };

    const files: FileItem[] = [
      { id: 'f1', path: '/test/audio.mp3', name: 'audio.mp3', size: 1000, duration: 10, status: 'done', progress: 100, phase: 3, revisionFailedBlocks: [1, 2] },
    ];
    const filesRef = { current: files };
    const archiveSessions: ArchiveSession[] = [];
    const archiveSessionsRef = { current: archiveSessions };
    const normalizeSessionDir = (d: string) => d.replace(/\\/g, '/').toLowerCase();
    const dispatch = vi.fn();
    const setArchiveSessions = vi.fn();
    const refreshArchiveSessions = vi.fn().mockResolvedValue(undefined);
    const addNotification = vi.fn();
    const setConfirmAction = vi.fn();

    const { result } = renderHook(() =>
      useRevisionRetry({
        filesRef,
        archiveSessionsRef,
        normalizeSessionDir,
        dispatch,
        setArchiveSessions,
        refreshArchiveSessions,
        addNotification,
        setConfirmAction,
      }),
    );

    await act(async () => {
      await result.current.handleRetryFailedRevisionBlocks('/sessions/session_1', 'f1');
    });

    expect(retryMock).toHaveBeenCalledWith('/sessions/session_1');
    expect(addNotification).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalledWith({ type: 'queue/set_retrying_blocks', id: 'f1', value: false });
    expect(dispatch).toHaveBeenCalledWith({ type: 'app/set_status', status: 'idle' });
  });

  it('does not send notification when retry is cancelled with remaining blocks', async () => {
    const retryMock = vi.fn().mockResolvedValue({
      ok: true,
      cancelled: true,
      session_dir: '/sessions/session_1',
      html_path: '/sessions/session_1/output.html',
      effective_model: 'gemini-2.5-flash',
      retried_blocks: [1],
      remaining_failed_blocks: [2],
    });
    window.pywebview = {
      api: {
        retry_failed_revision_blocks: retryMock,
      } as unknown as PywebviewApi,
    };

    const files: FileItem[] = [
      { id: 'f1', path: '/test/audio.mp3', name: 'audio.mp3', size: 1000, duration: 10, status: 'done', progress: 100, phase: 3, revisionFailedBlocks: [1, 2] },
    ];
    const filesRef = { current: files };
    const archiveSessions: ArchiveSession[] = [];
    const archiveSessionsRef = { current: archiveSessions };
    const normalizeSessionDir = (d: string) => d.replace(/\\/g, '/').toLowerCase();
    const dispatch = vi.fn();
    const setArchiveSessions = vi.fn();
    const refreshArchiveSessions = vi.fn().mockResolvedValue(undefined);
    const addNotification = vi.fn();
    const setConfirmAction = vi.fn();

    const { result } = renderHook(() =>
      useRevisionRetry({
        filesRef,
        archiveSessionsRef,
        normalizeSessionDir,
        dispatch,
        setArchiveSessions,
        refreshArchiveSessions,
        addNotification,
        setConfirmAction,
      }),
    );

    await act(async () => {
      await result.current.handleRetryFailedRevisionBlocks('/sessions/session_1', 'f1');
    });

    expect(retryMock).toHaveBeenCalledWith('/sessions/session_1');
    expect(dispatch).toHaveBeenCalledWith({
      type: 'queue/update_revision_failed_blocks',
      fileId: 'f1',
      sessionDir: '/sessions/session_1',
      blocks: [2],
      htmlPath: '/sessions/session_1/output.html',
      effectiveModel: 'gemini-2.5-flash',
    });
    expect(addNotification).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalledWith({ type: 'queue/set_retrying_blocks', id: 'f1', value: false });
    expect(dispatch).toHaveBeenCalledWith({ type: 'app/set_status', status: 'idle' });
  });
});
