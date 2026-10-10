import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import {
  formatUpdateInstallError,
  formatUpdateInstallStatus,
  useUpdateInstaller,
  UPDATE_INSTALL_IDLE,
  type UpdateInstallState,
} from './useUpdateInstaller';
import type { PywebviewApi } from '../bridge';

describe('formatUpdateInstallError', () => {
  it('formats uac_denied error appropriately', () => {
    expect(formatUpdateInstallError('uac_denied')).toContain('la richiesta UAC è stata rifiutata');
  });

  it('formats permission_denied error appropriately', () => {
    expect(formatUpdateInstallError('permission_denied')).toContain('Permesso negato per /Applications');
  });

  it('formats checksum errors', () => {
    expect(formatUpdateInstallError('checksum mismatch')).toContain('checksum mismatch');
  });

  it('returns fallback for empty error', () => {
    expect(formatUpdateInstallError('')).toBe('Aggiornamento fallito.');
  });
});

describe('formatUpdateInstallStatus', () => {
  it('formats downloading state with percentage', () => {
    const state: UpdateInstallState = {
      version: '1.2.0',
      status: 'downloading',
      bytesDone: 50,
      bytesTotal: 100,
      error: null,
    };
    expect(formatUpdateInstallStatus(state)).toBe('Download aggiornamento 50%…');
  });

  it('formats verifying, installing, done, and error states', () => {
    expect(formatUpdateInstallStatus({ ...UPDATE_INSTALL_IDLE, status: 'verifying' })).toContain('Verifica');
    expect(formatUpdateInstallStatus({ ...UPDATE_INSTALL_IDLE, status: 'installing' })).toContain('Installazione');
    expect(formatUpdateInstallStatus({ ...UPDATE_INSTALL_IDLE, status: 'done' })).toContain('Installer avviato');
    expect(formatUpdateInstallStatus({ ...UPDATE_INSTALL_IDLE, status: 'error', error: 'Network error' })).toContain('Network error');
    expect(formatUpdateInstallStatus(UPDATE_INSTALL_IDLE)).toBe('');
  });
});

describe('useUpdateInstaller', () => {
  const appendConsole = vi.fn();
  const upsertNotification = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    delete window.pywebview;
  });

  it('handles bridge unavailable when calling installUpdate', async () => {
    const { result } = renderHook(() =>
      useUpdateInstaller({
        latestVersion: '1.2.0',
        appendConsole,
        upsertNotification,
      }),
    );

    await act(async () => {
      try {
        await result.current.installUpdate('1.2.0');
      } catch (err: unknown) {
        expect(err).toBeInstanceOf(Error);
      }
    });

    expect(result.current.updateInstallState.status).toBe('error');
    expect(upsertNotification).toHaveBeenCalledWith(
      'Installazione aggiornamento',
      'Aggiornamento non riuscito: Bridge aggiornamenti non disponibile.',
      'warning',
      'update',
      expect.anything(),
    );
  });

  it('handles download progress transitions', () => {
    const { result } = renderHook(() =>
      useUpdateInstaller({
        latestVersion: '1.2.0',
        appendConsole,
        upsertNotification,
      }),
    );

    act(() => {
      result.current.handleDownloadProgress({
        status: 'downloading',
        bytes_done: 200,
        bytes_total: 1000,
      });
    });

    expect(result.current.updateInstallState.status).toBe('downloading');
    expect(result.current.updateInstallState.bytesDone).toBe(200);

    act(() => {
      result.current.handleDownloadProgress({
        status: 'done',
        bytes_done: 1000,
        bytes_total: 1000,
      });
    });

    expect(result.current.updateInstallState.status).toBe('done');
  });

  it('handles successful installUpdate via bridge', async () => {
    const mockApi: Partial<PywebviewApi> = {
      download_and_install_update: vi.fn().mockImplementation(async () => {
        return { ok: true };
      }),
    };
    window.pywebview = { api: mockApi as PywebviewApi };

    const { result } = renderHook(() =>
      useUpdateInstaller({
        latestVersion: '1.2.0',
        appendConsole,
        upsertNotification,
      }),
    );

    let installPromise: Promise<void>;
    act(() => {
      installPromise = result.current.installUpdate('1.2.0');
    });

    // Simulate completion from bridge
    act(() => {
      result.current.handleDownloadProgress({
        status: 'done',
        bytes_done: 1000,
        bytes_total: 1000,
      });
    });

    await act(async () => {
      await installPromise;
    });

    expect(mockApi.download_and_install_update).toHaveBeenCalledWith('1.2.0');
  });

  it('removes update-available notification when installUpdate begins', async () => {
    const mockApi: Partial<PywebviewApi> = {
      download_and_install_update: vi.fn().mockImplementation(async () => ({ ok: true })),
    };
    window.pywebview = { api: mockApi as PywebviewApi };
    const removeNotificationByDedupeKey = vi.fn();

    const { result } = renderHook(() =>
      useUpdateInstaller({
        latestVersion: '1.2.0',
        appendConsole,
        upsertNotification,
        removeNotificationByDedupeKey,
      }),
    );

    act(() => {
      void result.current.installUpdate('1.2.0');
    });

    expect(removeNotificationByDedupeKey).toHaveBeenCalledWith('update-available');
  });
});
