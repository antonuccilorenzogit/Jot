import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EDITOR_SESSION_STORAGE_KEY, loadAllEditorSessions, loadEditorSession, normalizeEditorSessions, saveEditorSession, touchEditorSession } from './editorSessions';

describe('normalizeEditorSessions', () => {
  it('preserves legacy sessions that do not have savedAt yet', () => {
    const now = new Date('2026-03-31T11:00:00Z').getTime();

    const sessions = normalizeEditorSessions(
      {
        legacy: { audioTime: 42, playbackRate: 1.25 },
      },
      now,
    );

    expect(sessions.legacy).toEqual({
      audioTime: 42,
      playbackRate: 1.25,
      savedAt: now,
    });
  });

  it('drops tagged sessions older than the TTL', () => {
    const now = new Date('2026-03-31T11:00:00Z').getTime();
    const thirtyOneDaysMs = 31 * 24 * 60 * 60 * 1000;

    const sessions = normalizeEditorSessions(
      {
        expired: { audioTime: 5, savedAt: now - thirtyOneDaysMs },
        fresh: { audioTime: 7, savedAt: now },
      },
      now,
    );

    expect(sessions).toEqual({
      fresh: { audioTime: 7, savedAt: now },
    });
  });
});

describe('editorSessions storage integration', () => {
  const storage = new Map<string, string>();
  const localStorageMock = {
    getItem: vi.fn((key: string) => storage.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      storage.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      storage.delete(key);
    }),
    clear: vi.fn(() => {
      storage.clear();
    }),
  };

  beforeEach(() => {
    storage.clear();
    localStorageMock.getItem.mockClear();
    localStorageMock.setItem.mockClear();
    localStorageMock.removeItem.mockClear();
    localStorageMock.clear.mockClear();
    vi.stubGlobal('window', { localStorage: localStorageMock });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('does not rewrite storage when normalized data is unchanged', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_000);
    storage.set(
      EDITOR_SESSION_STORAGE_KEY,
      JSON.stringify({ file1: { audioTime: 10, savedAt: 1_000 } }),
    );

    const session = loadEditorSession('file1');

    expect(session).toEqual({ audioTime: 10, savedAt: 1_000 });
    expect(localStorageMock.setItem).not.toHaveBeenCalled();
  });

  it('rewrites legacy sessions once so they gain savedAt', () => {
    vi.spyOn(Date, 'now').mockReturnValue(999);
    storage.set(
      EDITOR_SESSION_STORAGE_KEY,
      JSON.stringify({ legacy: { audioTime: 33 } }),
    );

    const session = loadEditorSession('legacy');

    expect(session).toEqual({ audioTime: 33, savedAt: 999 });
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      EDITOR_SESSION_STORAGE_KEY,
      JSON.stringify({ legacy: { audioTime: 33, savedAt: 999 } }),
    );
  });

  it('round-trips a saved session through localStorage', () => {
    vi.spyOn(Date, 'now').mockReturnValue(777);

    saveEditorSession('file2', { scrollTop: 55, volume: 0.8 });

    expect(loadEditorSession('file2')).toEqual({
      scrollTop: 55,
      volume: 0.8,
      savedAt: 777,
    });
  });

  it('touches session to update openedAt timestamp', () => {
    const now = Date.now();
    touchEditorSession('file3', now);

    expect(loadEditorSession('file3')).toEqual({
      openedAt: now,
      savedAt: now,
    });
    expect(loadAllEditorSessions()['file3']).toEqual({
      openedAt: now,
      savedAt: now,
    });
  });
});
