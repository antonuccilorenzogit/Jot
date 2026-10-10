import { describe, expect, it } from 'vitest';

import type { FileItem } from '../appState';
import { deserializeQueueFile, loadPersistedQueue, serializeQueueFile } from './useQueuePersistence';

function roundTrip(file: FileItem): FileItem {
  return deserializeQueueFile(JSON.parse(JSON.stringify(serializeQueueFile(file))), 0);
}

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

describe('useQueuePersistence — serialization contract', () => {
  it('completedAt is preserved through a JSON round-trip', () => {
    const ts = 1712491234567;
    const restored = roundTrip(makeFile({ status: 'done', progress: 100, phase: 3, completedAt: ts }));
    expect(restored.completedAt).toBe(ts);
  });

  it('completedAt missing on legacy entries is restored as undefined', () => {
    const restored = roundTrip(makeFile({ status: 'done', progress: 100, phase: 3 }));
    expect(restored.completedAt).toBeUndefined();
  });

  it('done file retains status, outputHtml and outputDir after round-trip', () => {
    const file = makeFile({
      id: 'abc',
      status: 'done',
      progress: 100,
      phase: 3,
      outputHtml: '/out/lesson.html',
      outputDir: '/out',
      completedAt: 1712491234567,
    });
    const restored = roundTrip(file);
    expect(restored.status).toBe('done');
    expect(restored.outputHtml).toBe('/out/lesson.html');
    expect(restored.outputDir).toBe('/out');
    expect(restored.completedAt).toBe(1712491234567);
  });

  it('processing status is downgraded to queued on restore', () => {
    const file = makeFile({ status: 'processing', progress: 50, phase: 1 });
    const restored = roundTrip(file);
    expect(restored.status).toBe('queued');
    expect(restored.progress).toBe(0);
  });

  it('error status, errorText and errorDetail are preserved on restore', () => {
    const file = makeFile({ status: 'error', progress: 0, phase: 0, errorText: 'timeout', errorDetail: 'api_key_prompt_timeout' });
    const restored = roundTrip(file);
    expect(restored.status).toBe('error');
    expect(restored.errorText).toBe('timeout');
    expect(restored.errorDetail).toBe('api_key_prompt_timeout');
  });

  it('effectiveModel is preserved through a JSON round-trip', () => {
    const file = makeFile({ status: 'done', progress: 100, phase: 3, effectiveModel: 'gemini-2.0-flash' });
    const restored = roundTrip(file);
    expect(restored.effectiveModel).toBe('gemini-2.0-flash');
  });

  it('effectiveModel missing on legacy entries is restored as undefined', () => {
    const restored = roundTrip(makeFile({ status: 'done', progress: 100, phase: 3 }));
    expect(restored.effectiveModel).toBeUndefined();
  });

  it('primaryModel is preserved through a JSON round-trip', () => {
    const file = makeFile({ status: 'done', progress: 100, phase: 3, primaryModel: 'gemini-2.5-flash', effectiveModel: 'gemini-3.6-flash' });
    const restored = roundTrip(file);
    expect(restored.primaryModel).toBe('gemini-2.5-flash');
    expect(restored.effectiveModel).toBe('gemini-3.6-flash');
  });

  it('primaryModel missing on legacy entries is restored as undefined', () => {
    const restored = roundTrip(makeFile({ status: 'done', progress: 100, phase: 3, effectiveModel: 'gemini-2.5-flash' }));
    expect(restored.primaryModel).toBeUndefined();
    expect(restored.effectiveModel).toBe('gemini-2.5-flash');
  });

  it('completionStatus is preserved through a JSON round-trip', () => {
    const file = makeFile({ status: 'done', progress: 100, phase: 3, completionStatus: 'completed_with_warnings', revisionFailedBlocks: [1] });
    const restored = roundTrip(file);
    expect(restored.completionStatus).toBe('completed_with_warnings');
    expect(restored.revisionFailedBlocks).toEqual([1]);
  });

  it('resumeSession and allowCompletedDestroy are preserved through a JSON round-trip', () => {
    const file = makeFile({
      resumeSession: false,
      allowCompletedDestroy: true,
    });
    const restored = roundTrip(file);
    expect(restored.resumeSession).toBe(false);
    expect(restored.allowCompletedDestroy).toBe(true);
  });

  it('resumeSession and allowCompletedDestroy missing or different values are deserialized correctly', () => {
    const file1 = makeFile({
      resumeSession: true,
      allowCompletedDestroy: false,
    });
    const restored1 = roundTrip(file1);
    expect(restored1.resumeSession).toBeUndefined();
    expect(restored1.allowCompletedDestroy).toBeUndefined();

    const file2 = makeFile({});
    const restored2 = roundTrip(file2);
    expect(restored2.resumeSession).toBeUndefined();
    expect(restored2.allowCompletedDestroy).toBeUndefined();
  });

  describe('loadPersistedQueue', () => {
    it('returns empty array if localStorage is empty or corrupt', () => {
      expect(loadPersistedQueue()).toEqual([]);
    });
  });
});
