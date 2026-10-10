import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSettingsStorage } from './useSettingsStorage';

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

describe('useSettingsStorage', () => {
  beforeEach(() => {
    setPywebview(undefined);
  });

  afterEach(() => {
    setPywebview(undefined);
  });

  it('initializes with default states', () => {
    const appendConsole = vi.fn();
    const { result } = renderHook(() =>
      useSettingsStorage({
        isOpen: false,
        activeTab: 'general',
        appendConsole,
      })
    );

    expect(result.current.sessionInfo).toBeNull();
    expect(result.current.isLoadingSessionInfo).toBe(false);
    expect(result.current.isMoveInProgress).toBe(false);
    expect(result.current.showMoveConfirm).toBe(false);
    expect(result.current.showCleanupConfirm).toBe(false);
  });

  it('fetches session storage info when open on advanced tab', async () => {
    const mockInfo = {
      ok: true,
      total_bytes: 2048,
      total_sessions: 5,
      session_root: '/path/to/sessions',
    };
    const getStorageInfo = vi.fn().mockResolvedValue(mockInfo);
    setPywebview({ get_session_storage_info: getStorageInfo });

    const appendConsole = vi.fn();
    const { result } = renderHook(() =>
      useSettingsStorage({
        isOpen: true,
        activeTab: 'advanced',
        appendConsole,
      })
    );

    await act(async () => {
      result.current.fetchSessionStorageInfo();
    });

    expect(result.current.sessionInfo).toEqual({
      total_bytes: 2048,
      total_sessions: 5,
      session_root: '/path/to/sessions',
    });
  });

  it('handles folder move dialog and cancel move', async () => {
    const askFolder = vi.fn().mockResolvedValue({ ok: true, path: '/new/folder' });
    setPywebview({ ask_session_folder: askFolder });

    const appendConsole = vi.fn();
    const { result } = renderHook(() =>
      useSettingsStorage({
        isOpen: true,
        activeTab: 'advanced',
        appendConsole,
      })
    );

    await act(async () => {
      await result.current.handleAskMoveFolder();
    });

    expect(result.current.pendingMovePath).toBe('/new/folder');
    expect(result.current.showMoveConfirm).toBe(true);

    act(() => {
      result.current.handleCancelMove();
    });

    expect(result.current.pendingMovePath).toBeNull();
    expect(result.current.showMoveConfirm).toBe(false);
  });

  it('handles incomplete sessions cleanup preview and cleanup', async () => {
    const cleanupOld = vi.fn()
      .mockResolvedValueOnce({ ok: true, removed: 2, freed_bytes: 1024, candidates: 2 })
      .mockResolvedValueOnce({ ok: true, removed: 2, freed_bytes: 1024, candidates: 2 });
    const getStorageInfo = vi.fn().mockResolvedValue({ ok: true, total_bytes: 0, total_sessions: 0 });
    setPywebview({
      cleanup_old_sessions: cleanupOld,
      get_session_storage_info: getStorageInfo,
    });

    const appendConsole = vi.fn();
    const { result } = renderHook(() =>
      useSettingsStorage({
        isOpen: true,
        activeTab: 'advanced',
        appendConsole,
      })
    );

    await act(async () => {
      await result.current.handleAskCleanup();
    });

    expect(result.current.cleanupPreview).toEqual({
      removed: 2,
      freed_bytes: 1024,
      candidates: 2,
    });
    expect(result.current.showCleanupConfirm).toBe(true);

    await act(async () => {
      await result.current.handleCleanupSessions();
    });

    expect(result.current.showCleanupConfirm).toBe(false);
    expect(result.current.cleanupResult?.removed).toBe(2);
  });
});
