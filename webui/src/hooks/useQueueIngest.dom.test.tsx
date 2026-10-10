import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useQueueIngest } from './useQueueIngest';
import type { FileItem } from '../appState';
import type { ArchiveSession } from '../bridge';

describe('useQueueIngest', () => {
  const dispatch = vi.fn();
  const setArchiveSessions = vi.fn();
  const setArchiveTotal = vi.fn();
  const appendConsole = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it('generates consistent fingerprints based on path or metadata', () => {
    const filesRef = { current: [] as FileItem[] };
    const archiveSessionsRef = { current: [] };
    const pendingArchiveReplacementsRef = { current: new Map() };
    const appStateRef = { current: 'idle' };

    const { result } = renderHook(() =>
      useQueueIngest({
        filesRef,
        archiveSessionsRef,
        pendingArchiveReplacementsRef,
        setArchiveSessions,
        setArchiveTotal,
        dispatch,
        appState: 'idle',
        appStateRef,
        apiReady: true,
        appendConsole,
      }),
    );

    const fpPath = result.current.getFileFingerprint({
      path: '/audio/test.mp3',
      name: 'test.mp3',
      size: 1024,
      duration: 60,
    });
    expect(fpPath).toBe('path:/audio/test.mp3');

    const fpMeta = result.current.getFileFingerprint({
      path: '',
      name: 'test.mp3',
      size: 1024,
      duration: 60,
    });
    expect(fpMeta).toBe('meta:test.mp3::1024::60');
  });

  it('enqueues unique files and dispatches queue/add', () => {
    const filesRef = { current: [] as FileItem[] };
    const archiveSessionsRef = { current: [] };
    const pendingArchiveReplacementsRef = { current: new Map() };
    const appStateRef = { current: 'idle' };

    const { result } = renderHook(() =>
      useQueueIngest({
        filesRef,
        archiveSessionsRef,
        pendingArchiveReplacementsRef,
        setArchiveSessions,
        setArchiveTotal,
        dispatch,
        appState: 'idle',
        appStateRef,
        apiReady: true,
        appendConsole,
      }),
    );

    const newFile: FileItem = {
      id: 'f1',
      name: 'lesson1.mp3',
      path: '/path/lesson1.mp3',
      size: 5000,
      duration: 100,
      status: 'queued',
      progress: 0,
      phase: 0,
    };

    act(() => {
      result.current.enqueueUniqueFiles([newFile]);
    });

    expect(dispatch).toHaveBeenCalledWith({
      type: 'queue/add',
      files: [newFile],
    });
    expect(result.current.duplicatePrompt).toBeNull();
  });

  it('triggers in-queue duplicate prompt when item is already in active queue', () => {
    const existingFile: FileItem = {
      id: 'f1',
      name: 'lesson1.mp3',
      path: '/path/lesson1.mp3',
      size: 5000,
      duration: 100,
      status: 'queued',
      progress: 0,
      phase: 0,
    };
    const filesRef = { current: [existingFile] };
    const archiveSessionsRef = { current: [] };
    const pendingArchiveReplacementsRef = { current: new Map() };
    const appStateRef = { current: 'idle' };

    const { result } = renderHook(() =>
      useQueueIngest({
        filesRef,
        archiveSessionsRef,
        pendingArchiveReplacementsRef,
        setArchiveSessions,
        setArchiveTotal,
        dispatch,
        appState: 'idle',
        appStateRef,
        apiReady: true,
        appendConsole,
      }),
    );

    act(() => {
      result.current.enqueueUniqueFiles([existingFile]);
    });

    expect(dispatch).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'queue/add' }));
    expect(result.current.duplicatePrompt).toEqual({
      kind: 'in-queue',
      filenames: ['lesson1.mp3'],
    });
  });

  it('notifies onFilesAddedToBatch when new files are enqueued during processing', () => {
    const filesRef = { current: [] as FileItem[] };
    const archiveSessionsRef = { current: [] };
    const pendingArchiveReplacementsRef = { current: new Map() };
    const appStateRef = { current: 'processing' };
    const onFilesAddedToBatch = vi.fn();

    const { result } = renderHook(() =>
      useQueueIngest({
        filesRef,
        archiveSessionsRef,
        pendingArchiveReplacementsRef,
        setArchiveSessions,
        setArchiveTotal,
        dispatch,
        appState: 'processing',
        appStateRef,
        apiReady: true,
        appendConsole,
        onFilesAddedToBatch,
      }),
    );

    const newFile: FileItem = {
      id: 'f2',
      name: 'lesson2.mp3',
      path: '/path/lesson2.mp3',
      size: 5000,
      duration: 100,
      status: 'queued',
      progress: 0,
      phase: 0,
    };

    act(() => {
      result.current.enqueueUniqueFiles([newFile]);
    });

    expect(dispatch).toHaveBeenCalledWith({
      type: 'queue/add',
      files: [newFile],
    });
    expect(onFilesAddedToBatch).toHaveBeenCalledWith(1);
  });

  it('sets isDragging to true on handleDragOver when processing', () => {
    const filesRef = { current: [] as FileItem[] };
    const archiveSessionsRef = { current: [] };
    const pendingArchiveReplacementsRef = { current: new Map() };
    const appStateRef = { current: 'processing' };

    const { result } = renderHook(() =>
      useQueueIngest({
        filesRef,
        archiveSessionsRef,
        pendingArchiveReplacementsRef,
        setArchiveSessions,
        setArchiveTotal,
        dispatch,
        appState: 'processing',
        appStateRef,
        apiReady: true,
        appendConsole,
      }),
    );

    const mockEvent = {
      preventDefault: vi.fn(),
    } as unknown as React.DragEvent;

    act(() => {
      result.current.handleDragOver(mockEvent);
    });

    expect(mockEvent.preventDefault).toHaveBeenCalled();
    expect(result.current.isDragging).toBe(true);
  });

  it('uploads browser drops through the shared upload flow', async () => {
    const uploadBrowserFiles = vi.fn().mockResolvedValue([
      { id: 'uploaded', name: 'drop.mp3', path: '/isolated/drop.mp3', size: 3 },
    ]);
    (window as unknown as { pywebview: { api: Record<string, unknown> } }).pywebview = {
      api: { upload_browser_files: uploadBrowserFiles },
    };
    const filesRef = { current: [] as FileItem[] };
    const archiveSessionsRef = { current: [] };
    const pendingArchiveReplacementsRef = { current: new Map() };
    const appStateRef = { current: 'idle' };
    const { result } = renderHook(() => useQueueIngest({
      filesRef,
      archiveSessionsRef,
      pendingArchiveReplacementsRef,
      setArchiveSessions,
      setArchiveTotal,
      dispatch,
      appState: 'idle',
      appStateRef,
      apiReady: true,
      appendConsole,
    }));
    const droppedFile = new File(['abc'], 'drop.mp3', { type: 'audio/mpeg' });
    const event = {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      dataTransfer: { files: [droppedFile] },
    } as unknown as React.DragEvent;

    await act(async () => {
      await result.current.handleDrop(event);
    });

    expect(uploadBrowserFiles).toHaveBeenCalledWith([droppedFile]);
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({
      type: 'queue/add',
      files: [expect.objectContaining({ name: 'drop.mp3', path: '/isolated/drop.mp3' })],
    }));
  });

  it('handleDuplicateAddAgain registers pending replacement and enqueues file without direct archive mutation', async () => {
    const filesRef = { current: [] as FileItem[] };
    const archiveSessionsRef = { current: [] };
    const pendingArchiveReplacementsRef = { current: new Map() };
    const appStateRef = { current: 'idle' };

    const { result } = renderHook(() =>
      useQueueIngest({
        filesRef,
        archiveSessionsRef,
        pendingArchiveReplacementsRef,
        setArchiveSessions,
        setArchiveTotal,
        dispatch,
        appState: 'idle',
        appStateRef,
        apiReady: true,
        appendConsole,
      }),
    );

    const incoming: FileItem = {
      id: 'incoming-1',
      name: 'Lesson 1.mp3',
      path: '/audio/lesson1.mp3',
      size: 1000,
      duration: 60,
      status: 'queued',
      progress: 0,
      phase: 0,
    };

    const archiveMatch: ArchiveSession = {
      session_dir: '/sessions/s1',
      name: 'Lesson 1',
      html_path: '/sessions/s1/Lesson 1.html',
      completed_at_iso: '2026-09-17T12:00:00Z',
      effective_model: 'gemini-2.5-flash',
      input_path: '/audio/lesson1.mp3',
    };

    await act(async () => {
      await result.current.handleDuplicateAddAgain([
        {
          source: 'archive',
          sessions: [archiveMatch],
          incoming,
        },
      ]);
    });

    expect(dispatch).toHaveBeenCalledWith({
      type: 'queue/add',
      files: [
        expect.objectContaining({
          name: 'Lesson 1.mp3',
          path: '/audio/lesson1.mp3',
          resumeSession: false,
          allowCompletedDestroy: true,
        }),
      ],
    });

    expect(pendingArchiveReplacementsRef.current.size).toBe(1);
    const replacement = Array.from(pendingArchiveReplacementsRef.current.values())[0] as {
      fileName: string;
      sessions: typeof archiveMatch[];
    };
    expect(replacement.fileName).toBe('Lesson 1.mp3');
    expect(replacement.sessions).toEqual([archiveMatch]);
    expect(setArchiveSessions).not.toHaveBeenCalled();
    expect(setArchiveTotal).not.toHaveBeenCalled();
  });
});
