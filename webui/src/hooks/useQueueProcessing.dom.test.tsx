import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useQueueProcessing, isSupportedMediaPath } from './useQueueProcessing';
import { type FileItem } from '../appState';
import { type PywebviewApi } from '../bridge';

describe('useQueueProcessing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
    localStorage.clear();
  });

  it('correctly identifies supported and unsupported media formats', () => {
    expect(isSupportedMediaPath('audio.mp3')).toBe(true);
    expect(isSupportedMediaPath('video.mp4')).toBe(true);
    expect(isSupportedMediaPath('recording.m4a')).toBe(true);
    expect(isSupportedMediaPath('voice_memo.opus')).toBe(true);
    expect(isSupportedMediaPath('video.mov')).toBe(true);
    expect(isSupportedMediaPath('audio.3gp')).toBe(true);
    expect(isSupportedMediaPath('Fisiologia II Lezione 10 pt 1')).toBe(true);
    expect(isSupportedMediaPath('Fisiologia II Lezione 10.10.2024')).toBe(true);
    expect(isSupportedMediaPath('document.pdf')).toBe(false);
    expect(isSupportedMediaPath('image.png')).toBe(false);
    expect(isSupportedMediaPath('library.so')).toBe(false);
    expect(isSupportedMediaPath('')).toBe(false);
  });

  it('handles startProcessing when queue has files and valid apiKey', async () => {
    const startProcessingMock = vi.fn().mockResolvedValue({ ok: true });
    window.pywebview = {
      api: {
        check_path_exists: vi.fn().mockResolvedValue({ exists: true }),
        start_processing: startProcessingMock,
      } as unknown as PywebviewApi,
    };

    const files: FileItem[] = [
      { id: '1', path: '/test/audio.mp3', name: 'audio.mp3', size: 1000, duration: 10, status: 'queued', progress: 0, phase: 0 },
    ];
    const filesRef = { current: files };
    const appStateRef = { current: 'idle' as const };
    const dispatch = vi.fn();
    const appendConsole = vi.fn();
    const setConfirmAction = vi.fn();
    const refreshArchiveSessions = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useQueueProcessing({
        filesRef,
        appStateRef,
        apiKey: 'AIzaSyTestKey_123456789012345678901',
        preferredModel: 'gemini-2.5-flash',
        fallbackModels: [],
        dispatch,
        appendConsole,
        setConfirmAction,
        refreshArchiveSessions,
      }),
    );

    let started = false;
    await act(async () => {
      started = await result.current.startProcessing();
    });

    expect(started).toBe(true);
    expect(startProcessingMock).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith({ type: 'app/set_status', status: 'processing' });
  });

  it('handles startProcessing when apiKey is empty but hasProtectedKey is true', async () => {
    const startProcessingMock = vi.fn().mockResolvedValue({ ok: true });
    window.pywebview = {
      api: {
        check_path_exists: vi.fn().mockResolvedValue({ exists: true }),
        start_processing: startProcessingMock,
      } as unknown as PywebviewApi,
    };

    const files: FileItem[] = [
      { id: '1', path: '/test/audio.mp3', name: 'audio.mp3', size: 1000, duration: 10, status: 'queued', progress: 0, phase: 0 },
    ];
    const filesRef = { current: files };
    const appStateRef = { current: 'idle' as const };
    const dispatch = vi.fn();
    const appendConsole = vi.fn();
    const setConfirmAction = vi.fn();
    const refreshArchiveSessions = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useQueueProcessing({
        filesRef,
        appStateRef,
        apiKey: '',
        hasProtectedKey: true,
        preferredModel: 'gemini-2.5-flash',
        fallbackModels: [],
        dispatch,
        appendConsole,
        setConfirmAction,
        refreshArchiveSessions,
      }),
    );

    let started = false;
    await act(async () => {
      started = await result.current.startProcessing();
    });

    expect(started).toBe(true);
    expect(startProcessingMock).toHaveBeenCalledTimes(1);
  });

  it('handles low disk warning during start_processing', async () => {
    const lowDiskWarning = {
      needed_bytes: 3000000000,
      free_bytes: 1500000000,
      location: 'C:\\',
      kind: 'system',
      file_name: 'audio.mp3',
    };
    const startProcessingMock = vi.fn().mockResolvedValue({ ok: false, low_disk_warning: lowDiskWarning });
    window.pywebview = {
      api: {
        check_path_exists: vi.fn().mockResolvedValue({ exists: true }),
        start_processing: startProcessingMock,
        flash_window: vi.fn(),
      } as unknown as PywebviewApi,
    };

    const files: FileItem[] = [
      { id: '1', path: '/test/audio.mp3', name: 'audio.mp3', size: 1000, duration: 10, status: 'queued', progress: 0, phase: 0 },
    ];
    const filesRef = { current: files };
    const appStateRef = { current: 'idle' as const };
    const dispatch = vi.fn();
    const appendConsole = vi.fn();
    const setConfirmAction = vi.fn();
    const refreshArchiveSessions = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useQueueProcessing({
        filesRef,
        appStateRef,
        apiKey: 'AIzaSyTestKey_123456789012345678901',
        preferredModel: 'gemini-2.5-flash',
        fallbackModels: [],
        dispatch,
        appendConsole,
        setConfirmAction,
        refreshArchiveSessions,
      }),
    );

    let started = false;
    await act(async () => {
      started = await result.current.startProcessing();
    });

    expect(started).toBe(false);
    expect(setConfirmAction).toHaveBeenCalledWith({ type: 'low-disk-warning', warning: lowDiskWarning });
  });

  it('passes force_retry only for an explicitly resumed paused file', async () => {
    const startProcessingMock = vi.fn().mockResolvedValue({ ok: true });
    window.pywebview = {
      api: {
        check_path_exists: vi.fn().mockResolvedValue({ exists: true }),
        start_processing: startProcessingMock,
      } as unknown as PywebviewApi,
    };
    const files: FileItem[] = [
      { id: 'paused', path: '/test/audio.mp3', name: 'audio.mp3', size: 1000, duration: 10, status: 'queued', progress: 0, phase: 0, forceRetry: true },
    ];
    const { result } = renderHook(() =>
      useQueueProcessing({
        filesRef: { current: files },
        appStateRef: { current: 'idle' as const },
        apiKey: 'AIzaSyTestKey_123456789012345678901',
        preferredModel: 'gemini-2.5-flash',
        fallbackModels: [],
        dispatch: vi.fn(),
        appendConsole: vi.fn(),
        setConfirmAction: vi.fn(),
        refreshArchiveSessions: vi.fn().mockResolvedValue(undefined),
      }),
    );

    await act(async () => {
      await result.current.startProcessing();
    });

    const descriptors = startProcessingMock.mock.calls[0][0];
    expect(descriptors).toEqual([
      expect.objectContaining({ id: 'paused', force_retry: true }),
    ]);
  });

  it('increments and decrements batchTotal dynamically when processing', () => {
    const files: FileItem[] = [
      { id: '1', path: '/test/audio1.mp3', name: 'audio1.mp3', size: 1000, duration: 10, status: 'processing', progress: 0, phase: 1 },
      { id: '2', path: '/test/audio2.mp3', name: 'audio2.mp3', size: 1000, duration: 10, status: 'queued', progress: 0, phase: 0 },
    ];
    const filesRef = { current: files };
    const appStateRef = { current: 'processing' as const };
    const dispatch = vi.fn();
    const appendConsole = vi.fn();
    const setConfirmAction = vi.fn();
    const refreshArchiveSessions = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useQueueProcessing({
        filesRef,
        appStateRef,
        apiKey: 'AIzaSyTestKey_123456789012345678901',
        preferredModel: 'gemini-2.5-flash',
        fallbackModels: [],
        dispatch,
        appendConsole,
        setConfirmAction,
        refreshArchiveSessions,
      }),
    );

    act(() => {
      result.current.setBatchTotal(2);
    });
    expect(result.current.batchTotal).toBe(2);

    act(() => {
      result.current.onFilesAddedToBatch(2);
    });
    expect(result.current.batchTotal).toBe(4);

    act(() => {
      result.current.onFileRemovedFromBatch();
    });
    expect(result.current.batchTotal).toBe(3);
  });
});
