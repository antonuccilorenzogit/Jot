import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createBrowserPywebviewApi, getHostCapabilities, initBrowserHost } from './browserHost';

describe('browserHost', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
    delete (window as unknown as { jotBridge?: unknown }).jotBridge;
  });

  it('skips initialization if window.pywebview.api already exists (desktop mode)', async () => {
    const dummyApi = { load_settings: vi.fn() };
    (window as unknown as { pywebview: { api: unknown } }).pywebview = { api: dummyApi };

    const initialized = await initBrowserHost();
    expect(initialized).toBe(false);
    expect(window.pywebview?.api).toBe(dummyApi);
  });

  it('initializes browser host and dispatches pywebviewready', async () => {
    const bootstrapData = {
      ok: true,
      mode: 'browser',
      session_token: 'test-token-12345',
      capabilities: { openLocalPath: false, realPipeline: false },
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(bootstrapData),
    });
    vi.stubGlobal('fetch', mockFetch);

    const onReady = vi.fn();
    window.addEventListener('pywebviewready', onReady, { once: true });

    const initialized = await initBrowserHost();
    expect(initialized).toBe(true);
    expect(window.pywebview?.api).toBeDefined();
    expect(getHostCapabilities().openLocalPath).toBe(false);
    expect(getHostCapabilities().realPipeline).toBe(false);
    expect(onReady).toHaveBeenCalledTimes(1);
  });

  it('clears only transient browser state when the isolated backend changes', async () => {
    localStorage.setItem('jot.browser-instance.v1', 'old-token');
    localStorage.setItem('jot.queue.v1', '[{"name":"stale.mp3"}]');
    localStorage.setItem('jot.notifications.v1', '[{"title":"stale"}]');
    localStorage.setItem('jot.editor-sessions.v1', '{"stale":{}}');
    localStorage.setItem('jot.has_sessions.v1', 'true');
    localStorage.setItem('jot.theme.v1', 'dark');

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ session_token: 'new-token' }),
    }));

    expect(await initBrowserHost()).toBe(true);
    expect(localStorage.getItem('jot.browser-instance.v1')).toBe('new-token');
    expect(localStorage.getItem('jot.queue.v1')).toBeNull();
    expect(localStorage.getItem('jot.notifications.v1')).toBeNull();
    expect(localStorage.getItem('jot.editor-sessions.v1')).toBeNull();
    expect(localStorage.getItem('jot.has_sessions.v1')).toBeNull();
    expect(localStorage.getItem('jot.theme.v1')).toBe('dark');
  });

  it('handles bootstrap failure gracefully', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    });
    vi.stubGlobal('fetch', mockFetch);

    const initialized = await initBrowserHost();
    expect(initialized).toBe(false);
    expect(window.pywebview).toBeUndefined();
  });

  it('forwards RPC calls through /api/rpc/{method}', async () => {
    const api = createBrowserPywebviewApi();

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true, exists: true }),
    });
    vi.stubGlobal('fetch', mockFetch);

    const res = await api.check_path_exists?.('/path/to/test.mp3');
    expect(res).toEqual({ ok: true, exists: true });
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/rpc/check_path_exists',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ args: ['/path/to/test.mp3'] }),
      }),
    );
  });

  it('handles RPC errors by throwing', async () => {
    const api = createBrowserPywebviewApi();

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: vi.fn().mockResolvedValue({ detail: 'Forbidden method' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    await expect(api.load_settings?.()).rejects.toThrow('Forbidden method');
  });

  it('uses the same upload endpoint for browser file ingestion', async () => {
    const api = createBrowserPywebviewApi();
    const descriptor = { id: '1', name: 'lesson.mp3', path: '/tmp/lesson.mp3', size: 3 };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true, files: [descriptor] }),
    });
    vi.stubGlobal('fetch', mockFetch);

    const uploaded = await api.upload_browser_files?.([
      new File(['abc'], 'lesson.mp3', { type: 'audio/mpeg' }),
    ]);

    expect(uploaded).toEqual([descriptor]);
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/upload',
      expect.objectContaining({ method: 'POST', body: expect.any(FormData) }),
    );
  });

  it('surfaces export HTTP errors instead of reporting success', async () => {
    const api = createBrowserPywebviewApi();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: vi.fn().mockResolvedValue({ detail: 'Pacchetto non esportabile' }),
    }));

    await expect(api.export_sbobina_package?.('/session', 'full')).rejects.toThrow(
      'Pacchetto non esportabile',
    );
  });

  it('resolves browser media with both path and sessionDir', async () => {
    const api = createBrowserPywebviewApi();
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ok: true, has_audio: true, url: '/api/media/stream?path=x' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    const result = await api.stream_media_file?.('/audio.mp3', '/session');

    expect(result?.ok).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('path=%2Faudio.mp3&session_dir=%2Fsession'),
      expect.any(Object),
    );
  });

  it('provides safe desktop fallbacks for desktop-only features', async () => {
    const api = createBrowserPywebviewApi();

    const openFileRes = await api.open_file?.('path.html');
    expect(openFileRes?.ok).toBe(false);
    expect(openFileRes?.error).toContain('desktop');

    const folderRes = await api.open_session_folder?.();
    expect(folderRes?.ok).toBe(false);
    expect(folderRes?.error).toContain('desktop');

    const flashRes = await api.flash_window?.();
    expect(flashRes?.ok).toBe(true);

    const closeRes = await api.close_window?.();
    expect(closeRes?.ok).toBe(true);
  });

});
