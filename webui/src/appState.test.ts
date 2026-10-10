import { describe, expect, it } from 'vitest';

import { createInitialProcessingState, getDoneFiles, getPendingFiles, initialProcessingState, isSuccessfulProcessDone, processingReducer, type FileItem } from './appState';


function makeFile(overrides: Partial<FileItem> = {}): FileItem {
  return {
    id: 'file-1',
    name: 'lesson.mp3',
    size: 1024,
    duration: 60,
    status: 'queued',
    progress: 0,
    phase: 0,
    ...overrides,
  };
}


describe('getPendingFiles / getDoneFiles selectors', () => {
  const queued = makeFile({ id: 'q', status: 'queued' });
  const processing = makeFile({ id: 'p', status: 'processing' });
  const error = makeFile({ id: 'e', status: 'error' });
  const done1 = makeFile({ id: 'd1', status: 'done', progress: 100, phase: 3, completedAt: 1000 });
  const done2 = makeFile({ id: 'd2', status: 'done', progress: 100, phase: 3, completedAt: 3000 });
  const done3 = makeFile({ id: 'd3', status: 'done', progress: 100, phase: 3, completedAt: 2000 });
  const mixed = [queued, processing, error, done1, done2, done3];

  it('getPendingFiles excludes all done files', () => {
    const result = getPendingFiles(mixed);
    expect(result.every(f => f.status !== 'done')).toBe(true);
    expect(result.map(f => f.id)).toEqual(['q', 'p', 'e']);
  });

  it('getPendingFiles returns an empty array when all files are done', () => {
    expect(getPendingFiles([done1, done2])).toEqual([]);
  });

  it('getDoneFiles includes only done files sorted by completedAt descending', () => {
    const result = getDoneFiles(mixed);
    expect(result.map(f => f.id)).toEqual(['d2', 'd3', 'd1']); // 3000, 2000, 1000
  });

  it('getDoneFiles treats missing completedAt as 0 (sorts last)', () => {
    const legacy = makeFile({ id: 'leg', status: 'done', progress: 100, phase: 3 }); // no completedAt
    const result = getDoneFiles([legacy, done1]);
    expect(result.map(f => f.id)).toEqual(['d1', 'leg']); // 1000 > 0
  });

  it('isSuccessfulProcessDone only returns true for all-success completions', () => {
    expect(isSuccessfulProcessDone({ completed: 1, failed: 0, total: 1 })).toBe(true);
    expect(isSuccessfulProcessDone({ completed: 0, completed_with_warnings: 1, failed: 0, total: 1 })).toBe(false);
    expect(isSuccessfulProcessDone({ completed: 1, completed_with_warnings: 1, failed: 0, total: 2 })).toBe(false);
    expect(isSuccessfulProcessDone({ completed: 0, failed: 1, total: 1 })).toBe(false);
    expect(isSuccessfulProcessDone({ completed: 1, failed: 1, total: 2 })).toBe(false);
    expect(isSuccessfulProcessDone({ cancelled: true, completed: 1, failed: 0, total: 1 })).toBe(false);
    expect(isSuccessfulProcessDone(undefined)).toBe(false);
  });
});

describe('processingReducer', () => {
  it('adds and reorders queued files', () => {
    const first = makeFile({ id: 'a', name: 'a.mp3' });
    const second = makeFile({ id: 'b', name: 'b.mp3' });

    let state = processingReducer(initialProcessingState, { type: 'queue/add', files: [first, second] });
    state = processingReducer(state, { type: 'queue/reorder', fromIndex: 1, toIndex: 0 });

    expect(state.files.map(file => file.id)).toEqual(['b', 'a']);
  });

  it('marks current file as processing and completes it', () => {
    const file = makeFile({ id: 'abc' });
    let state = processingReducer(initialProcessingState, { type: 'queue/add', files: [file] });

    state = processingReducer(state, {
      type: 'bridge/set_current_file',
      data: { id: 'abc', index: 0, total: 1 },
    });
    expect(state.appState).toBe('processing');
    expect(state.files[0].status).toBe('processing');

    state = processingReducer(state, {
      type: 'bridge/file_done',
      data: { id: 'abc', index: 0, output_html: 'out.html', output_dir: 'dir' },
    });
    expect(state.files[0].status).toBe('done');
    expect(state.files[0].outputHtml).toBe('out.html');
  });

  it('bridge/file_done records completed_with_warnings status', () => {
    const file = makeFile({ id: 'abc' });
    const state = processingReducer(
      { ...initialProcessingState, files: [file] },
      {
        type: 'bridge/file_done',
        data: {
          id: 'abc',
          index: 0,
          output_html: 'out.html',
          output_dir: 'dir',
          completion_status: 'completed_with_warnings',
          revision_failed_blocks: [2],
        },
      },
    );
    expect(state.files[0].completionStatus).toBe('completed_with_warnings');
    expect(state.files[0].revisionFailedBlocks).toEqual([2]);
  });

  it('resets error files to queued on retry_failed', () => {
    const failed = makeFile({ id: 'f1', status: 'error', progress: 0, phase: 0, errorText: 'timeout' });
    const done = makeFile({ id: 'f2', status: 'done', progress: 100, phase: 3 });
    const queued = makeFile({ id: 'f3', status: 'queued' });
    const state = processingReducer(
      { ...initialProcessingState, files: [failed, done, queued] },
      { type: 'queue/retry_failed' },
    );
    expect(state.files[0].status).toBe('queued');
    expect(state.files[0].progress).toBe(0);
    expect(state.files[0].phase).toBe(0);
    expect(state.files[0].errorText).toBeUndefined();
    expect(state.files[1].status).toBe('done');
    expect(state.files[2].status).toBe('queued');
  });

  it('bridge/update_progress updates activeProgress without mutating files identity', () => {
    const file = makeFile({ id: 'x', status: 'processing' });
    const s0 = processingReducer(initialProcessingState, { type: 'queue/add', files: [file] });
    const s1 = processingReducer(s0, { type: 'bridge/update_progress', value: 0.55 });
    expect(s1.activeProgress).toBe(55);
    expect(s1.files).toBe(s0.files); // same array reference
  });

  it('bridge/file_done sets completedAt to a current timestamp', () => {
    const before = Date.now();
    const file = makeFile({ id: 'x' });
    const state = processingReducer(
      { ...initialProcessingState, files: [file] },
      { type: 'bridge/file_done', data: { id: 'x', index: 0, output_html: 'out.html', output_dir: 'dir' } },
    );
    const after = Date.now();
    const { completedAt } = state.files[0];
    expect(typeof completedAt).toBe('number');
    expect(completedAt!).toBeGreaterThanOrEqual(before);
    expect(completedAt!).toBeLessThanOrEqual(after);
  });

  it('queue/update_revision_failed_blocks matches by fileId first', () => {
    const files = [
      makeFile({ id: 'target', status: 'done', outputDir: 'C:/sessions/new', revisionFailedBlocks: [1, 2] }),
      makeFile({ id: 'other', status: 'done', outputDir: 'C:/sessions/old', revisionFailedBlocks: [3] }),
    ];
    const state = { ...initialProcessingState, structuralVersion: 2, files };
    const next = processingReducer(state, {
      type: 'queue/update_revision_failed_blocks',
      fileId: 'target',
      sessionDir: 'C:/sessions/old',
      blocks: [],
      htmlPath: 'out.html',
      effectiveModel: 'gemini-test',
    });

    expect(next.structuralVersion).toBe(3);
    expect(next.files[0].revisionFailedBlocks).toEqual([]);
    expect(next.files[0].outputHtml).toBe('out.html');
    expect(next.files[0].effectiveModel).toBe('gemini-test');
    expect(next.files[1].revisionFailedBlocks).toEqual([3]);
  });

  it('queue/update_revision_failed_blocks falls back to normalized outputDir when fileId is missing', () => {
    const file = makeFile({ id: 'target', status: 'done', outputDir: 'C:\\Sessions\\Done\\', revisionFailedBlocks: [1] });
    const state = { ...initialProcessingState, structuralVersion: 5, files: [file] };
    const next = processingReducer(state, {
      type: 'queue/update_revision_failed_blocks',
      sessionDir: 'c:/sessions/done',
      blocks: [],
    });

    expect(next.structuralVersion).toBe(6);
    expect(next.files[0].revisionFailedBlocks).toEqual([]);
  });

  it('queue/update_revision_failed_blocks leaves state unchanged when no file matches', () => {
    const file = makeFile({ id: 'target', status: 'done', outputDir: 'C:/sessions/done', revisionFailedBlocks: [1] });
    const state = { ...initialProcessingState, structuralVersion: 5, files: [file] };
    const next = processingReducer(state, {
      type: 'queue/update_revision_failed_blocks',
      fileId: 'missing',
      sessionDir: 'C:/sessions/missing',
      blocks: [],
    });

    expect(next).toBe(state);
  });

  it('queue/prepend prepends files to the front of the queue', () => {
    const existing = [makeFile({ id: 'file-1' }), makeFile({ id: 'file-2' })];
    const newFile = makeFile({ id: 'file-prepended' });
    const state = { ...initialProcessingState, files: existing, structuralVersion: 1 };
    const next = processingReducer(state, { type: 'queue/prepend', files: [newFile] });
    expect(next.structuralVersion).toBe(2);
    expect(next.files.map(f => f.id)).toEqual(['file-prepended', 'file-1', 'file-2']);
  });

  it('queue/set_retrying_blocks moves retrying file to front with processing status and resets to done on false', () => {
    const files = [
      makeFile({ id: 'q1', status: 'queued' }),
      makeFile({ id: 'done-1', status: 'done', isRetryingBlocks: false }),
    ];
    const state = { ...initialProcessingState, files, structuralVersion: 1 };
    const retrying = processingReducer(state, {
      type: 'queue/set_retrying_blocks',
      id: 'done-1',
      value: true,
    });
    expect(retrying.structuralVersion).toBe(2);
    expect(retrying.files[0].id).toBe('done-1');
    expect(retrying.files[0].status).toBe('processing');
    expect(retrying.files[0].isRetryingBlocks).toBe(true);
    expect(retrying.files[1].id).toBe('q1');

    const finished = processingReducer(retrying, {
      type: 'queue/set_retrying_blocks',
      id: 'done-1',
      value: false,
    });
    expect(finished.structuralVersion).toBe(3);
    expect(finished.files[0].id).toBe('done-1');
    expect(finished.files[0].status).toBe('done');
    expect(finished.files[0].isRetryingBlocks).toBe(false);
  });

  it('queue/clear_completed removes only done files, leaving queued and error intact', () => {
    const files = [
      makeFile({ id: 'q1', status: 'queued' }),
      makeFile({ id: 'd1', status: 'done', progress: 100, phase: 3 }),
      makeFile({ id: 'e1', status: 'error', progress: 0, phase: 0 }),
      makeFile({ id: 'd2', status: 'done', progress: 100, phase: 3 }),
    ];
    const state = processingReducer(
      { ...initialProcessingState, files },
      { type: 'queue/clear_completed' },
    );
    expect(state.files.map(f => f.id)).toEqual(['q1', 'e1']);
  });

  it('queue/reorder returns same state when fromIndex equals toIndex', () => {
    const files = [makeFile({ id: 'a' }), makeFile({ id: 'b' })];
    const state = { ...initialProcessingState, files };
    const next = processingReducer(state, { type: 'queue/reorder', fromIndex: 0, toIndex: 0 });
    expect(next).toBe(state);
  });

  it('queue/reorder returns same state when fromIndex is out of bounds', () => {
    const files = [makeFile({ id: 'a' })];
    const state = { ...initialProcessingState, files };
    const next = processingReducer(state, { type: 'queue/reorder', fromIndex: 5, toIndex: 0 });
    expect(next).toBe(state);
  });

  it('queue/update_source does not alter non-matching files', () => {
    const files = [makeFile({ id: 'x' }), makeFile({ id: 'y' })];
    const state = processingReducer(
      { ...initialProcessingState, files },
      { type: 'queue/update_source', id: 'x', path: '/new.mp3', name: 'new.mp3' },
    );
    expect(state.files[1].id).toBe('y');
  });

  it('queue/remove removes the targeted file', () => {
    const files = [makeFile({ id: 'del' }), makeFile({ id: 'keep' })];
    const state = processingReducer(
      { ...initialProcessingState, files },
      { type: 'queue/remove', id: 'del' },
    );
    expect(state.files.map(f => f.id)).toEqual(['keep']);
  });

  it('queue/update_source updates path/name/size/duration for matching file', () => {
    const file = makeFile({ id: 'src1', path: '/old.mp3', name: 'old.mp3', size: 100, duration: 10 });
    const state = processingReducer(
      { ...initialProcessingState, files: [file] },
      { type: 'queue/update_source', id: 'src1', path: '/new.mp3', name: 'new.mp3', size: 200, duration: 20 },
    );
    expect(state.files[0].path).toBe('/new.mp3');
    expect(state.files[0].name).toBe('new.mp3');
    expect(state.files[0].size).toBe(200);
  });

  it('queue/update_source can match completed files by sessionDir', () => {
    const file = makeFile({ id: 'done1', outputDir: '/sessions/s1', path: '/old.mp3', name: 'old.mp3' });
    const state = processingReducer(
      { ...initialProcessingState, files: [file] },
      { type: 'queue/update_source', sessionDir: '/sessions/s1', path: '/new.mp3', name: 'new.mp3' },
    );
    expect(state.files[0].path).toBe('/new.mp3');
    expect(state.files[0].name).toBe('new.mp3');
  });

  it('queue/retry_one resets only the targeted error file', () => {
    const files = [
      makeFile({ id: 'a', status: 'error', errorText: 'fail', progress: 0, phase: 0 }),
      makeFile({ id: 'b', status: 'error', errorText: 'fail2', progress: 0, phase: 0 }),
    ];
    const state = processingReducer(
      { ...initialProcessingState, files },
      { type: 'queue/retry_one', id: 'a' },
    );
    expect(state.files[0].status).toBe('queued');
    expect(state.files[0].errorText).toBeUndefined();
    expect(state.files[1].status).toBe('error');
  });

  it('queue/retry_one preserves an explicit force retry for paused files', () => {
    const file = makeFile({
      id: 'paused',
      status: 'paused',
      retryable: true,
      retryReason: 'circuit_breaker_paused',
    });
    const queued = processingReducer(
      { ...initialProcessingState, files: [file] },
      { type: 'queue/retry_one', id: 'paused' },
    );

    expect(queued.files[0].status).toBe('queued');
    expect(queued.files[0].forceRetry).toBe(true);

    const processing = processingReducer(queued, {
      type: 'bridge/set_current_file',
      data: { id: 'paused', index: 0, total: 1 },
    });
    expect(processing.files[0].forceRetry).toBeUndefined();
  });

  it('queue/clear_all removes non-done files', () => {
    const state = processingReducer(
      { ...initialProcessingState, files: [makeFile()] },
      { type: 'queue/clear_all' },
    );
    expect(state.files).toEqual([]);
  });

  it('queue/clear_all preserves done files', () => {
    const done = makeFile({ id: 'd1', status: 'done', progress: 100, phase: 3, completedAt: 1000 });
    const queued = makeFile({ id: 'q1', status: 'queued' });
    const error = makeFile({ id: 'e1', status: 'error', errorText: 'fail' });
    const state = processingReducer(
      { ...initialProcessingState, files: [done, queued, error] },
      { type: 'queue/clear_all' },
    );
    expect(state.files).toEqual([done]);
  });

  it('app/set_status changes appState', () => {
    const state = processingReducer(initialProcessingState, { type: 'app/set_status', status: 'canceling' });
    expect(state.appState).toBe('canceling');
  });

  it('default case returns same state for unknown action', () => {
    // @ts-expect-error testing unknown action type
    const state = processingReducer(initialProcessingState, { type: 'unknown/action' });
    expect(state).toBe(initialProcessingState);
  });

  it('queue/update_source falls back to existing duration when not provided', () => {
    const file = makeFile({ id: 'u', duration: 60 });
    const state = processingReducer(
      { ...initialProcessingState, files: [file] },
      { type: 'queue/update_source', id: 'u', path: '/new.mp3', name: 'new.mp3' },
    );
    expect(state.files[0].duration).toBe(60);
  });

  it('bridge/update_progress returns same state when progress value is unchanged', () => {
    const base = { ...initialProcessingState, activeProgress: 55 };
    const next = processingReducer(base, { type: 'bridge/update_progress', value: 0.55 });
    expect(next).toBe(base);
  });

  it('bridge/set_work_totals falls back to existing values when data fields are null', () => {
    const base = { ...initialProcessingState, workTotals: { chunks: 5, macro: 4 } };
    const state = processingReducer(
      base,
      { type: 'bridge/set_work_totals', data: { chunks: null, macro: null } },
    );
    expect(state.workTotals).toEqual({ chunks: 5, macro: 4 });
  });

  it('bridge/set_work_totals updates workTotals', () => {
    const state = processingReducer(
      initialProcessingState,
      { type: 'bridge/set_work_totals', data: { chunks: 10, macro: 8 } },
    );
    expect(state.workTotals).toEqual({ chunks: 10, macro: 8 });
  });

  it('bridge/update_work_done updates workDone for a kind', () => {
    const state = processingReducer(
      initialProcessingState,
      { type: 'bridge/update_work_done', data: { kind: 'chunks', done: 5 } },
    );
    expect(state.workDone.chunks).toBe(5);
  });

  it('bridge/update_work_done returns same state when value is unchanged', () => {
    const base = { ...initialProcessingState, workDone: { chunks: 5, macro: 0 } };
    const next = processingReducer(base, { type: 'bridge/update_work_done', data: { kind: 'chunks', done: 5 } });
    expect(next).toBe(base);
  });

  it('bridge/process_done with cancelled=true does not touch queued files', () => {
    const files = [
      makeFile({ id: 'p1', status: 'processing' }),
      makeFile({ id: 'q1', status: 'queued' }),
    ];
    const state = processingReducer(
      { ...initialProcessingState, files },
      { type: 'bridge/process_done', data: { cancelled: true, total: 1 } },
    );
    expect(state.files[1].status).toBe('queued');
  });

  it('bridge/set_current_file does not alter non-matching files', () => {
    const files = [makeFile({ id: 'active' }), makeFile({ id: 'other' })];
    const state = processingReducer(
      { ...initialProcessingState, files },
      { type: 'bridge/set_current_file', data: { id: 'active', index: 0, total: 2 } },
    );
    expect(state.files[1].status).toBe('queued');
  });

  it('bridge/file_failed uses fallback message when error is undefined', () => {
    const file = makeFile({ id: 'f', status: 'processing' });
    const state = processingReducer(
      { ...initialProcessingState, files: [file] },
      { type: 'bridge/file_failed', data: { id: 'f', index: 0, error: undefined } },
    );
    expect(state.files[0].errorText).toBe('Elaborazione non completata.');
  });


  it('bridge/file_done does not alter non-matching files', () => {
    const files = [makeFile({ id: 'target' }), makeFile({ id: 'other' })];
    const state = processingReducer(
      { ...initialProcessingState, files },
      { type: 'bridge/file_done', data: { id: 'target', index: 0, output_html: 'out.html', output_dir: 'dir' } },
    );
    expect(state.files[1].status).toBe('queued');
  });

  it('bridge/file_failed does not alter non-matching files', () => {
    const files = [makeFile({ id: 'fail1', status: 'processing' }), makeFile({ id: 'ok', status: 'queued' })];
    const state = processingReducer(
      { ...initialProcessingState, files },
      { type: 'bridge/file_failed', data: { id: 'fail1', index: 0, error: 'timeout' } },
    );
    expect(state.files[1].status).toBe('queued');
  });

  it('bridge/update_phase returns same state when phase unchanged (early return)', () => {
    const state = { ...initialProcessingState, currentPhase: 'Fase 1/3' };
    const next = processingReducer(state, { type: 'bridge/update_phase', text: 'Fase 1/3' });
    expect(next).toBe(state);
  });

  it('bridge/update_phase updates currentPhase when changed', () => {
    const state = { ...initialProcessingState, currentPhase: 'Fase 1/3' };
    const next = processingReducer(state, { type: 'bridge/update_phase', text: 'Fase 2/3' });
    expect(next.currentPhase).toBe('Fase 2/3');
  });

  it('bridge/update_model returns same state when model unchanged', () => {
    const state = { ...initialProcessingState, currentModel: 'gemini-2.5-flash' };
    const next = processingReducer(state, { type: 'bridge/update_model', model: 'gemini-2.5-flash' });
    expect(next).toBe(state);
  });

  it('bridge/update_model updates currentModel when changed', () => {
    const state = { ...initialProcessingState, currentModel: 'gemini-2.5-flash' };
    const next = processingReducer(state, { type: 'bridge/update_model', model: 'gemini-2.5-pro' });
    expect(next.currentModel).toBe('gemini-2.5-pro');
  });

  it('bridge/file_failed marks file as error with errorText', () => {
    const file = makeFile({ id: 'err1', status: 'processing' });
    const state = processingReducer(
      { ...initialProcessingState, files: [file] },
      { type: 'bridge/file_failed', data: { id: 'err1', index: 0, error: 'quota_daily_limit_phase1', error_detail: 'api_key_prompt_timeout' } },
    );
    expect(state.files[0].status).toBe('error');
    expect(state.files[0].errorText).toBe('quota_daily_limit_phase1');
    expect(state.files[0].errorDetail).toBe('api_key_prompt_timeout');
    expect(state.files[0].progress).toBe(0);
  });

  it('queue/retry_one clears errorDetail', () => {
    const file = makeFile({ id: 'err1', status: 'error', errorText: 'quota_daily_limit_phase1', errorDetail: 'api_key_prompt_timeout' });
    const state = processingReducer(
      { ...initialProcessingState, files: [file] },
      { type: 'queue/retry_one', id: 'err1' },
    );
    expect(state.files[0].status).toBe('queued');
    expect(state.files[0].errorText).toBeUndefined();
    expect(state.files[0].errorDetail).toBeUndefined();
  });

  it('resets processing files to queued on cancelled batch completion', () => {
    const file = makeFile({ status: 'processing', progress: 50, phase: 1 });
    const state = processingReducer(
      { ...initialProcessingState, appState: 'processing', currentPhase: 'Fase 1', files: [file] },
      { type: 'bridge/process_done', data: { cancelled: true, total: 1 } },
    );

    expect(state.appState).toBe('idle');
    expect(state.currentPhase).toBe('');
    expect(state.files[0].status).toBe('queued');
    expect(state.files[0].progress).toBe(0);
  });

  it('queue/remap_session_roots updates outputDir and outputHtml for matching roots', () => {
    const file1 = makeFile({
      id: 'f1',
      status: 'done',
      outputDir: 'C:\\old_sessions\\sess1',
      outputHtml: 'C:\\old_sessions\\sess1\\out.html',
    });
    const file2 = makeFile({
      id: 'f2',
      status: 'done',
      outputDir: 'D:\\other\\sess2',
      outputHtml: 'D:\\other\\sess2\\out.html',
    });
    const state = processingReducer(
      { ...initialProcessingState, files: [file1, file2] },
      { type: 'queue/remap_session_roots', oldRoot: 'C:/old_sessions', newRoot: 'E:/new_sessions' },
    );

    expect(state.files[0].outputDir).toBe('E:/new_sessions/sess1');
    expect(state.files[0].outputHtml).toBe('E:/new_sessions/sess1/out.html');
    expect(state.files[1].outputDir).toBe('D:\\other\\sess2');
    expect(state.files[1].outputHtml).toBe('D:\\other\\sess2\\out.html');
  });

  describe('createInitialProcessingState', () => {
    it('initializes with default empty files when no arguments provided', () => {
      const state = createInitialProcessingState();
      expect(state.files).toEqual([]);
      expect(state.structuralVersion).toBe(0);
      expect(state.appState).toBe('idle');
    });

    it('initializes with passed files and default state', () => {
      const customFiles = [makeFile({ id: 'f-init', name: 'init.mp3' })];
      const state = createInitialProcessingState(customFiles);
      expect(state.files).toEqual(customFiles);
      expect(state.structuralVersion).toBe(0);
      expect(state.appState).toBe('idle');
    });
  });
});
