import { act, renderHook } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useBridgeCallbacks } from './useBridgeCallbacks';
import type { AppStatus, FileItem, ProcessDonePayload, ProcessingAction } from '../appState';

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

describe('useBridgeCallbacks auto-continue', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setPywebview({});
    window.jotBridge = null;
  });

  afterEach(() => {
    vi.useRealTimers();
    setPywebview(undefined);
    window.jotBridge = null;
  });

  it('waits for the continuation start instead of forcing processing state early', async () => {
    const dispatch = vi.fn<(action: ProcessingAction) => void>();
    const startProcessing = vi.fn<(isContinuation?: boolean) => Promise<boolean>>().mockResolvedValue(true);
    const onFileContinued = vi.fn();
    const onBatchReset = vi.fn();
    const onBatchFullyDone = vi.fn<(data: ProcessDonePayload) => void>();
    const queuedFiles: FileItem[] = [{
      id: 'queued-1',
      name: 'lesson.mp3',
      size: 1,
      duration: 1,
      path: 'C:\\audio\\lesson.mp3',
      status: 'queued',
      progress: 0,
      phase: 0,
    }];

    renderHook(() => {
      const filesRef = useRef<FileItem[]>(queuedFiles);
      const appStateRef = useRef<AppStatus>('idle');
      const autoContinueRef = useRef(true);
      const startProcessingRef = useRef<(isContinuation?: boolean) => Promise<boolean>>(startProcessing);

      useBridgeCallbacks({
        dispatch,
        appendConsole: vi.fn(),
        filesRef,
        appStateRef,
        enqueueUniqueFiles: vi.fn(),
        setRegeneratePrompt: vi.fn(),
        setAskNewKeyPrompt: vi.fn(),
        autoContinueRef,
        startProcessingRef,
        onFileContinued,
        onBatchReset,
        onBatchFullyDone,
        clearCompletionFlash: vi.fn(),
      });
    });

    const payload = { completed: 1, failed: 0, total: 2 };

    act(() => {
      window.jotBridge?.processDone(payload);
    });

    expect(dispatch).toHaveBeenCalledWith({ type: 'bridge/process_done', data: payload });
    expect(dispatch).not.toHaveBeenCalledWith({ type: 'app/set_status', status: 'processing' });
    expect(onFileContinued).not.toHaveBeenCalled();
    expect(onBatchReset).not.toHaveBeenCalled();
    expect(onBatchFullyDone).not.toHaveBeenCalled();
    expect(startProcessing).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });

    expect(startProcessing).toHaveBeenCalledTimes(1);
    expect(startProcessing).toHaveBeenCalledWith(true);
    expect(onFileContinued).toHaveBeenCalledTimes(1);
    expect(onBatchReset).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalledWith({ type: 'app/set_status', status: 'processing' });
  });

  it('resets batch progress when the continuation never starts', async () => {
    const dispatch = vi.fn<(action: ProcessingAction) => void>();
    const startProcessing = vi.fn<(isContinuation?: boolean) => Promise<boolean>>().mockResolvedValue(false);
    const onFileContinued = vi.fn();
    const onBatchReset = vi.fn();
    const onBatchFullyDone = vi.fn<(data: ProcessDonePayload) => void>();
    const queuedFiles: FileItem[] = [{
      id: 'queued-1',
      name: 'lesson.mp3',
      size: 1,
      duration: 1,
      path: 'C:\\audio\\lesson.mp3',
      status: 'queued',
      progress: 0,
      phase: 0,
    }];

    renderHook(() => {
      const filesRef = useRef<FileItem[]>(queuedFiles);
      const appStateRef = useRef<AppStatus>('idle');
      const autoContinueRef = useRef(true);
      const startProcessingRef = useRef<(isContinuation?: boolean) => Promise<boolean>>(startProcessing);

      useBridgeCallbacks({
        dispatch,
        appendConsole: vi.fn(),
        filesRef,
        appStateRef,
        enqueueUniqueFiles: vi.fn(),
        setRegeneratePrompt: vi.fn(),
        setAskNewKeyPrompt: vi.fn(),
        autoContinueRef,
        startProcessingRef,
        onFileContinued,
        onBatchReset,
        onBatchFullyDone,
        clearCompletionFlash: vi.fn(),
      });
    });

    act(() => {
      window.jotBridge?.processDone({ completed: 1, failed: 0, total: 2 });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });

    expect(startProcessing).toHaveBeenCalledWith(true);
    expect(onFileContinued).not.toHaveBeenCalled();
    expect(onBatchReset).toHaveBeenCalledTimes(1);
    expect(onBatchFullyDone).not.toHaveBeenCalled();
  });

  it('does not auto-continue when processDone marks quota exhaustion', async () => {
    const startProcessing = vi.fn<(isContinuation?: boolean) => Promise<boolean>>().mockResolvedValue(true);
    const onBatchFullyDone = vi.fn<(data: ProcessDonePayload) => void>();
    const queuedFiles: FileItem[] = [{
      id: 'queued-1',
      name: 'next.mp3',
      size: 1,
      duration: 1,
      path: 'C:\\audio\\next.mp3',
      status: 'queued',
      progress: 0,
      phase: 0,
    }];

    renderHook(() => {
      const filesRef = useRef<FileItem[]>(queuedFiles);
      const appStateRef = useRef<AppStatus>('idle');
      const autoContinueRef = useRef(true);
      const startProcessingRef = useRef<(isContinuation?: boolean) => Promise<boolean>>(startProcessing);

      useBridgeCallbacks({
        dispatch: vi.fn(),
        appendConsole: vi.fn(),
        filesRef,
        appStateRef,
        enqueueUniqueFiles: vi.fn(),
        setRegeneratePrompt: vi.fn(),
        setAskNewKeyPrompt: vi.fn(),
        autoContinueRef,
        startProcessingRef,
        onFileContinued: vi.fn(),
        onBatchReset: vi.fn(),
        onBatchFullyDone,
        clearCompletionFlash: vi.fn(),
      });
    });

    const payload = { completed: 0, failed: 1, total: 2, quota_exhausted: true };
    act(() => {
      window.jotBridge?.processDone(payload);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });

    expect(startProcessing).not.toHaveBeenCalled();
    expect(onBatchFullyDone).toHaveBeenCalledWith(payload);
  });
});

function makeMinimalHook(overrides: Partial<Parameters<typeof useBridgeCallbacks>[0]> = {}) {
  const filesRef = { current: [] as FileItem[] };
  const appStateRef = { current: 'idle' as AppStatus };
  const autoContinueRef = { current: false };
  const startProcessingRef = { current: vi.fn<(isContinuation?: boolean) => Promise<boolean>>().mockResolvedValue(false) };
  const opts = {
    dispatch: vi.fn(),
    appendConsole: vi.fn(),
    filesRef: filesRef as unknown as ReturnType<typeof useRef<FileItem[]>>,
    appStateRef: appStateRef as unknown as ReturnType<typeof useRef<AppStatus>>,
    enqueueUniqueFiles: vi.fn(),
    setRegeneratePrompt: vi.fn(),
    setAskNewKeyPrompt: vi.fn(),
    autoContinueRef: autoContinueRef as unknown as ReturnType<typeof useRef<boolean>>,
    startProcessingRef: startProcessingRef as unknown as ReturnType<typeof useRef<(isContinuation?: boolean) => Promise<boolean>>>,
    onFileContinued: vi.fn(),
    onBatchReset: vi.fn(),
    onBatchFullyDone: vi.fn<(data: ProcessDonePayload) => void>(),
    clearCompletionFlash: vi.fn(),
    ...overrides,
  };
  return opts;
}

describe('useBridgeCallbacks — direct bridge callbacks', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setPywebview({});
    window.jotBridge = null;
  });
  afterEach(() => {
    vi.useRealTimers();
    setPywebview(undefined);
    window.jotBridge = null;
  });

  it('appendConsole callback forwards message', () => {
    const appendConsole = vi.fn();
    const opts = makeMinimalHook({ appendConsole });
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => { window.jotBridge?.appendConsole('hello'); });
    expect(appendConsole).toHaveBeenCalledWith('hello');
  });

  it('askRegenerate callback forwards data to setRegeneratePrompt', () => {
    const setRegeneratePrompt = vi.fn();
    const opts = makeMinimalHook({ setRegeneratePrompt });
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => { window.jotBridge?.askRegenerate({ filename: 'test.mp3' }); });
    expect(setRegeneratePrompt).toHaveBeenCalledWith(expect.objectContaining({ filename: 'test.mp3' }));
  });

  it('askRegenerate callback shows native notification and flashes taskbar when window is in background', () => {
    const showNotification = vi.fn();
    const flashWindow = vi.fn();
    setPywebview({ show_notification: showNotification, flash_window: flashWindow });
    vi.spyOn(document, 'hasFocus').mockReturnValue(false);
    const setRegeneratePrompt = vi.fn();
    const opts = makeMinimalHook({ setRegeneratePrompt });
    renderHook(() => { useBridgeCallbacks(opts); });
    localStorage.removeItem('notifications_enabled');
    act(() => {
      window.jotBridge?.askRegenerate({ filename: 'test.mp3', mode: 'resume' });
    });
    expect(setRegeneratePrompt).toHaveBeenCalledWith(expect.objectContaining({ filename: 'test.mp3' }));
    expect(flashWindow).toHaveBeenCalled();
    expect(showNotification).toHaveBeenCalledWith(
      '⚠️ Conferma richiesta — test.mp3',
      expect.stringContaining('Ci sono progressi salvati'),
    );
    vi.restoreAllMocks();
  });

  it('askRegenerate flashes taskbar in background even when notifications are disabled', () => {
    const showNotification = vi.fn();
    const flashWindow = vi.fn();
    setPywebview({ show_notification: showNotification, flash_window: flashWindow });
    vi.spyOn(document, 'hasFocus').mockReturnValue(false);
    const setRegeneratePrompt = vi.fn();
    const opts = makeMinimalHook({ setRegeneratePrompt });
    renderHook(() => { useBridgeCallbacks(opts); });
    localStorage.setItem('notifications_enabled', 'false');
    act(() => {
      window.jotBridge?.askRegenerate({ filename: 'test.mp3', mode: 'resume' });
    });
    expect(setRegeneratePrompt).toHaveBeenCalledWith(expect.objectContaining({ filename: 'test.mp3' }));
    expect(flashWindow).toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
    localStorage.removeItem('notifications_enabled');
    vi.restoreAllMocks();
  });

  it('askNewKey callback sets askNewKeyPrompt', () => {
    const setAskNewKeyPrompt = vi.fn();
    const opts = makeMinimalHook({ setAskNewKeyPrompt });
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => { window.jotBridge?.askNewKey(); });
    expect(setAskNewKeyPrompt).toHaveBeenCalledWith(true);
  });

  it('dismissNewKey callback clears askNewKeyPrompt', () => {
    const setAskNewKeyPrompt = vi.fn();
    const opts = makeMinimalHook({ setAskNewKeyPrompt });
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => { window.jotBridge?.dismissNewKey(); });
    expect(setAskNewKeyPrompt).toHaveBeenCalledWith(false);
  });

  it('requestQuitConfirmation calls onRequestQuitConfirmation option', () => {
    const onRequestQuitConfirmation = vi.fn();
    const opts = makeMinimalHook({ onRequestQuitConfirmation });
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => { window.jotBridge?.requestQuitConfirmation?.(); });
    expect(onRequestQuitConfirmation).toHaveBeenCalled();
  });

  it('filesDropped calls enqueueUniqueFiles when appState is idle or processing', () => {
    const enqueueUniqueFiles = vi.fn();
    const opts = makeMinimalHook({ enqueueUniqueFiles });
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => {
      window.jotBridge?.filesDropped([{ id: 'x', name: 'f.mp3', path: '/f.mp3', size: 100, duration: 30 }]);
    });
    expect(enqueueUniqueFiles).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({ name: 'f.mp3' })]),
    );

    enqueueUniqueFiles.mockClear();
    opts.appStateRef.current = 'processing';
    act(() => {
      window.jotBridge?.filesDropped([{ id: 'y', name: 'Fisiologia II Lezione 1 pt 1', path: '/audio', size: 200, duration: 60 }]);
    });
    expect(enqueueUniqueFiles).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({ name: 'Fisiologia II Lezione 1 pt 1' })]),
    );
  });

  it('filesDropped does not call enqueueUniqueFiles when appState is canceling', () => {
    const enqueueUniqueFiles = vi.fn();
    const opts = makeMinimalHook({ enqueueUniqueFiles });
    opts.appStateRef.current = 'canceling';
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => {
      window.jotBridge?.filesDropped([{ id: 'x', name: 'f.mp3', path: '/f.mp3', size: 100, duration: 30 }]);
    });
    expect(enqueueUniqueFiles).not.toHaveBeenCalled();
  });

  it('fileDone callback: covers notification path for completed file', () => {
    const showNotification = vi.fn();
    setPywebview({ show_notification: showNotification });
    vi.spyOn(document, 'hasFocus').mockReturnValue(false);
    const doneFile: FileItem = {
      id: 'file-1', name: 'audio.mp3', size: 1, duration: 60, path: '/a.mp3', status: 'done', progress: 1, phase: 0,
    };
    const opts = makeMinimalHook();
    opts.filesRef = { current: [doneFile] } as unknown as ReturnType<typeof useRef<FileItem[]>>;
    renderHook(() => { useBridgeCallbacks(opts); });
    localStorage.removeItem('notifications_enabled');
    act(() => {
      window.jotBridge?.fileDone({
        id: 'file-1', index: 0, output_html: '/out.html', output_dir: '/sessions/x', effective_model: 'gemini-2.5-flash',
      });
    });
    expect(showNotification).toHaveBeenCalledWith(
      '✅ Sbobina pronta — audio.mp3',
      expect.stringContaining('Elaborata con successo'),
    );
    vi.restoreAllMocks();
  });

  it('fileDone callback: does not show native notification when batchTotal > 1', () => {
    const showNotification = vi.fn();
    setPywebview({ show_notification: showNotification });
    vi.spyOn(document, 'hasFocus').mockReturnValue(false);
    const doneFile: FileItem = {
      id: 'file-1', name: 'audio.mp3', size: 1, duration: 60, path: '/a.mp3', status: 'done', progress: 1, phase: 0,
    };
    const opts = makeMinimalHook();
    opts.batchTotal = 2;
    opts.filesRef = { current: [doneFile] } as unknown as ReturnType<typeof useRef<FileItem[]>>;
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => {
      window.jotBridge?.fileDone({
        id: 'file-1', index: 0, output_html: '/out.html', output_dir: '/sessions/x', effective_model: 'gemini-2.5-flash',
      });
    });
    expect(showNotification).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it('processDone with no queued files and autoContinue=false calls onBatchFullyDone', async () => {
    const onBatchFullyDone = vi.fn<(data: ProcessDonePayload) => void>();
    const opts = makeMinimalHook({ onBatchFullyDone });
    renderHook(() => { useBridgeCallbacks(opts); });
    const payload = { completed: 1, failed: 0, total: 1 };
    act(() => { window.jotBridge?.processDone(payload); });
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    expect(onBatchFullyDone).toHaveBeenCalledWith(payload);
  });

  it('processDone clears any regenerate prompt left open by a backend timeout', () => {
    const setRegeneratePrompt = vi.fn();
    const opts = makeMinimalHook({ setRegeneratePrompt });
    renderHook(() => { useBridgeCallbacks(opts); });
    act(() => { window.jotBridge?.processDone({ completed: 0, failed: 1, total: 1 }); });
    expect(setRegeneratePrompt).toHaveBeenCalledWith(null);
  });

  it('askNewKey callback: covers notification path for key exhaustion', () => {
    const showNotification = vi.fn();
    setPywebview({ show_notification: showNotification });
    vi.spyOn(document, 'hasFocus').mockReturnValue(false);
    const opts = makeMinimalHook();
    renderHook(() => { useBridgeCallbacks(opts); });
    localStorage.removeItem('notifications_enabled');
    act(() => {
      window.jotBridge?.askNewKey();
    });
    expect(showNotification).toHaveBeenCalledWith(
      '⚠️ Chiavi esaurite — jot',
      expect.stringContaining('Limite API raggiunto'),
    );
    vi.restoreAllMocks();
  });

  it('fileDone callback: covers warning notification for completed file with warnings', () => {
    const showNotification = vi.fn();
    setPywebview({ show_notification: showNotification });
    vi.spyOn(document, 'hasFocus').mockReturnValue(false);
    const doneFile: FileItem = {
      id: 'file-1', name: 'audio.mp3', size: 1, duration: 60, path: '/a.mp3', status: 'done', progress: 1, phase: 0,
    };
    const opts = makeMinimalHook();
    opts.filesRef = { current: [doneFile] } as unknown as ReturnType<typeof useRef<FileItem[]>>;
    renderHook(() => { useBridgeCallbacks(opts); });
    localStorage.removeItem('notifications_enabled');
    act(() => {
      window.jotBridge?.fileDone({
        id: 'file-1', index: 0, output_html: '/out.html', output_dir: '/sessions/x', completion_status: 'completed_with_warnings'
      });
    });
    expect(showNotification).toHaveBeenCalledWith(
      '⚠️ Sbobina pronta con avvisi — audio.mp3',
      "Completata con alcune parti non revisionate. Apri l'app per rivederle.",
    );
    vi.restoreAllMocks();
  });

  it('fileFailed callback: covers server overload and generic error notification paths', () => {
    const showNotification = vi.fn();
    setPywebview({ show_notification: showNotification });
    vi.spyOn(document, 'hasFocus').mockReturnValue(false);
    const doneFile: FileItem = {
      id: 'file-1', name: 'audio.mp3', size: 1, duration: 60, path: '/a.mp3', status: 'error', progress: 0, phase: 0,
    };
    const opts = makeMinimalHook();
    opts.filesRef = { current: [doneFile] } as unknown as ReturnType<typeof useRef<FileItem[]>>;
    renderHook(() => { useBridgeCallbacks(opts); });
    localStorage.removeItem('notifications_enabled');

    // Test server busy/unavailable error
    act(() => {
      window.jotBridge?.fileFailed({
        id: 'file-1', index: 0, error: 'Modello Gemini indisponibile'
      });
    });
    expect(showNotification).toHaveBeenCalledWith(
      '⚠️ Server occupati — audio.mp3',
      expect.stringContaining('I server di Google Gemini sono temporaneamente sovraccarichi'),
    );

    showNotification.mockClear();

    // Test phase1_all_models_unavailable error
    act(() => {
      window.jotBridge?.fileFailed({
        id: 'file-1', index: 0, error: 'phase1_all_models_unavailable'
      });
    });
    expect(showNotification).toHaveBeenCalledWith(
      '⚠️ Server occupati — audio.mp3',
      expect.stringContaining('I server di Google Gemini sono temporaneamente sovraccarichi'),
    );

    showNotification.mockClear();

    // Test paused timeout error
    act(() => {
      window.jotBridge?.fileFailed({
        id: 'file-1', index: 0, error: 'regenerate_prompt_timeout'
      });
    });
    expect(showNotification).toHaveBeenCalledWith(
      '⏸️ Elaborazione in pausa — audio.mp3',
      expect.stringContaining('Nessuna scelta ricevuta'),
    );

    showNotification.mockClear();

    // Test generic error
    act(() => {
      window.jotBridge?.fileFailed({
        id: 'file-1', index: 0, error: 'Errore generico di test'
      });
    });
    expect(showNotification).toHaveBeenCalledWith(
      '❌ Errore elaborazione — audio.mp3',
      'Errore generico di test',
    );

    vi.restoreAllMocks();
  });

  it('does not auto-continue queued files after a circuit-breaker pause', async () => {
    const startProcessing = vi.fn().mockResolvedValue(true);
    const onBatchFullyDone = vi.fn();
    const opts = makeMinimalHook();
    opts.filesRef = { current: [{
      id: 'queued-1', name: 'lesson.mp3', size: 1, duration: 1,
      path: 'C:\\audio\\lesson.mp3', status: 'queued', progress: 0, phase: 0,
    }] } as unknown as ReturnType<typeof useRef<FileItem[]>>;
    opts.autoContinueRef = { current: true } as ReturnType<typeof useRef<boolean>>;
    opts.startProcessingRef = { current: startProcessing } as unknown as ReturnType<typeof useRef<(isContinuation?: boolean) => Promise<boolean>>>;
    opts.onBatchFullyDone = onBatchFullyDone;
    renderHook(() => { useBridgeCallbacks(opts); });

    const payload = { completed: 0, failed: 0, paused: 1, total: 2 };
    act(() => {
      window.jotBridge?.processDone(payload);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });

    expect(startProcessing).not.toHaveBeenCalled();
    expect(onBatchFullyDone).toHaveBeenCalledWith(payload);
  });

  it('uses the backend retry-state names for cooldown, probe, and pause', () => {
    const appendConsole = vi.fn();
    const opts = makeMinimalHook();
    opts.appendConsole = appendConsole;
    renderHook(() => { useBridgeCallbacks(opts); });

    act(() => {
      window.jotBridge?.retryStateChanged?.({
        state: 'cooling_down', attempt: 2, max_attempts: 4, seconds_remaining: 15,
      });
      window.jotBridge?.retryStateChanged?.({
        state: 'probing', attempt: 2, max_attempts: 4, model: 'gemini-2.5-flash',
      });
      window.jotBridge?.retryStateChanged?.({
        state: 'paused', attempt: 4, max_attempts: 4,
      });
    });

    expect(appendConsole).toHaveBeenCalledWith(expect.stringContaining('Attesa cooldown'));
    expect(appendConsole).toHaveBeenCalledWith(expect.stringContaining('Esecuzione sonda'));
    expect(appendConsole).toHaveBeenCalledWith(expect.stringContaining('Batch sospeso'));
  });
});
