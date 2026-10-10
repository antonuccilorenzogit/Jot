import { describe, expect, it, vi } from 'vitest';

import { createBridge } from './bridge';
import { initialProcessingState, processingReducer, type ProcessingAction } from './appState';


describe('createBridge', () => {
  it('dispatches progress and file lifecycle events', () => {
    let state = initialProcessingState;
    const dispatch = (action: ProcessingAction) => {
      state = processingReducer(state, action);
    };

    const appendConsole = vi.fn();
    const onRegenerate = vi.fn();
    const onAskNewKey = vi.fn();
    const onDismissNewKey = vi.fn();
    const onBatchDone = vi.fn();
    const onFileDone = vi.fn();

    const bridge = createBridge({
      dispatch,
      appendConsole,
      onRegenerate,
      onAskNewKey,
      onDismissNewKey,
      onBatchDone,
      onFileDone,
      onFilesDropped: vi.fn(),
      onBatchStart: vi.fn(),
    });

    dispatch({
      type: 'queue/add',
      files: [{
        id: 'abc',
        name: 'lesson.mp3',
        size: 1,
        duration: 1,
        status: 'queued',
        progress: 0,
        phase: 0,
      }],
    });

    bridge.setCurrentFile({ id: 'abc', index: 0, total: 1 });
    bridge.setWorkTotals({ chunks: 4, macro: 2 });
    bridge.updateWorkDone({ kind: 'chunks', done: 1, total: 4 });
    bridge.registerStepTime({ kind: 'chunks', seconds: 3.5, done: 1, total: 4 });
    bridge.updateProgress(0.42);
    bridge.fileDone({ id: 'abc', index: 0, output_html: 'out.html', output_dir: 'dist' });
    bridge.processDone({ completed: 1, failed: 0, total: 1 });

    expect(state.files[0].status).toBe('done');
    expect(state.files[0].progress).toBe(100);
    expect(state.workTotals.chunks).toBe(4);
    expect(state.workDone.chunks).toBe(1);
    expect(onFileDone).toHaveBeenCalledTimes(1);
    expect(onBatchDone).toHaveBeenCalledTimes(1);
  });

  it('routes prompts to their handlers', () => {
    const onRegenerate = vi.fn();
    const onAskNewKey = vi.fn();
    const onDismissNewKey = vi.fn();
    const bridge = createBridge({
      dispatch: vi.fn(),
      appendConsole: vi.fn(),
      onRegenerate,
      onAskNewKey,
      onDismissNewKey,
      onBatchDone: vi.fn(),
      onFileDone: vi.fn(),
      onFilesDropped: vi.fn(),
      onBatchStart: vi.fn(),
    });

    bridge.askRegenerate({ filename: 'lesson.mp3' });
    bridge.askNewKey();
    bridge.dismissNewKey();

    expect(onRegenerate).toHaveBeenCalledWith({ filename: 'lesson.mp3' });
    expect(onAskNewKey).toHaveBeenCalledTimes(1);
    expect(onDismissNewKey).toHaveBeenCalledTimes(1);
  });

  it('calls onBatchStart on updatePhase and setCurrentFile (clears completionFlash)', () => {
    const onBatchStart = vi.fn();
    const bridge = createBridge({
      dispatch: vi.fn(),
      appendConsole: vi.fn(),
      onRegenerate: vi.fn(),
      onAskNewKey: vi.fn(),
      onDismissNewKey: vi.fn(),
      onBatchDone: vi.fn(),
      onFileDone: vi.fn(),
      onFilesDropped: vi.fn(),
      onBatchStart,
    });

    bridge.updatePhase('Fase 1/3');
    bridge.setCurrentFile({ id: 'abc', index: 0, total: 1 });

    expect(onBatchStart).toHaveBeenCalledTimes(2);
  });

  it('logs normalized phases once and ignores blank or consecutive duplicates', () => {
    const dispatch = vi.fn();
    const appendConsole = vi.fn();
    const bridge = createBridge({
      dispatch,
      appendConsole,
      onRegenerate: vi.fn(),
      onAskNewKey: vi.fn(),
      onDismissNewKey: vi.fn(),
      onBatchDone: vi.fn(),
      onFileDone: vi.fn(),
      onFilesDropped: vi.fn(),
      onBatchStart: vi.fn(),
    });

    bridge.updatePhase('  Trascrizione chunk 1/2...  ');
    bridge.updatePhase('Trascrizione chunk 1/2...');
    bridge.updatePhase('   ');

    expect(appendConsole).toHaveBeenCalledOnce();
    expect(appendConsole).toHaveBeenCalledWith('Trascrizione chunk 1/2...');
    expect(dispatch).toHaveBeenCalledOnce();
    expect(dispatch).toHaveBeenCalledWith({
      type: 'bridge/update_phase',
      text: 'Trascrizione chunk 1/2...',
    });
  });

  it('resets an in-flight file when processDone reports cancellation', () => {
    let state = initialProcessingState;
    const dispatch = (action: ProcessingAction) => {
      state = processingReducer(state, action);
    };

    const onBatchDone = vi.fn();
    const bridge = createBridge({
      dispatch,
      appendConsole: vi.fn(),
      onRegenerate: vi.fn(),
      onAskNewKey: vi.fn(),
      onDismissNewKey: vi.fn(),
      onBatchDone,
      onFileDone: vi.fn(),
      onFilesDropped: vi.fn(),
      onBatchStart: vi.fn(),
    });

    dispatch({
      type: 'queue/add',
      files: [{
        id: 'abc',
        name: 'lesson.mp3',
        size: 1,
        duration: 1,
        status: 'queued',
        progress: 0,
        phase: 0,
      }],
    });

    bridge.setCurrentFile({ id: 'abc', index: 0, total: 1 });
    bridge.processDone({ cancelled: true, completed: 0, failed: 0, total: 1 });

    expect(state.appState).toBe('idle');
    expect(state.files[0].status).toBe('queued');
    expect(state.files[0].progress).toBe(0);
    expect(state.files[0].phase).toBe(0);
    expect(onBatchDone).toHaveBeenCalledWith({ cancelled: true, completed: 0, failed: 0, total: 1 });
  });

  it('calls onFileFailed when a file fails', () => {
    const onFileFailed = vi.fn();
    const bridge = createBridge({
      dispatch: vi.fn(),
      appendConsole: vi.fn(),
      onRegenerate: vi.fn(),
      onAskNewKey: vi.fn(),
      onDismissNewKey: vi.fn(),
      onBatchDone: vi.fn(),
      onFileDone: vi.fn(),
      onFileFailed,
      onFilesDropped: vi.fn(),
      onBatchStart: vi.fn(),
    });

    bridge.fileFailed({ id: 'abc', index: 0, error: 'Test error' });

    expect(onFileFailed).toHaveBeenCalledWith({ id: 'abc', index: 0, error: 'Test error' });
  });

  it('forwards apiUsageUpdated to onApiUsageUpdated option', () => {
    const onApiUsageUpdated = vi.fn();
    const bridge = createBridge({
      dispatch: vi.fn(),
      appendConsole: vi.fn(),
      onRegenerate: vi.fn(),
      onAskNewKey: vi.fn(),
      onDismissNewKey: vi.fn(),
      onBatchDone: vi.fn(),
      onFileDone: vi.fn(),
      onFilesDropped: vi.fn(),
      onBatchStart: vi.fn(),
      onApiUsageUpdated,
    });

    const dummyUsage = {
      quota_date: '2026-09-02',
      next_reset_info: 'Reset quote: ore 09:00',
      keys: [],
      estimated_sbobine_remaining: 3,
      is_degraded_mode: false,
    };

    bridge.apiUsageUpdated?.(dummyUsage);
    expect(onApiUsageUpdated).toHaveBeenCalledWith(dummyUsage);
  });
});
