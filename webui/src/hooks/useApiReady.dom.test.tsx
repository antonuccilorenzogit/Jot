import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useApiReady } from './useApiReady';

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setPywebview(undefined);
});

afterEach(() => {
  vi.useRealTimers();
  setPywebview(undefined);
  delete window.elDesktopStartup;
});

describe('useApiReady — bootstrap guard', () => {
  it('announces settings before the Python request and waits for a slow result', async () => {
    const order: string[] = [];
    let finish!: (cfg: Record<string, unknown>) => void;
    const load = vi.fn(() => {
      order.push('load_settings');
      return new Promise<Record<string, unknown>>(resolve => { finish = resolve; });
    });
    window.elDesktopStartup = {
      validate: vi.fn().mockReturnValue(true),
      settingsStarted: vi.fn(async () => { order.push('settings-started'); return true; }),
      ready: vi.fn(async () => { order.push('ready'); return true; }),
    };
    setPywebview({ load_settings: load });
    const { result } = renderHook(() => useApiReady(vi.fn()));
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(order).toEqual(['settings-started', 'load_settings']);
    expect(load).toHaveBeenCalledTimes(1);
    expect(result.current.apiReady).toBe(false);
    await act(async () => { finish({ preferred_model: 'slow-model' }); });
    expect(order).toEqual(['settings-started', 'load_settings', 'ready']);
    expect(result.current.apiReady).toBe(true);
    expect(result.current.preferredModel).toBe('slow-model');
  });

  it('retries the full bootstrap when Python accepts ready but its response is lost', async () => {
    const order: string[] = [];
    let backendReady = false;
    const appendConsole = vi.fn();
    const load = vi.fn(async () => {
      order.push('load_settings');
      return { api_key: 'recovered-key', preferred_model: 'recovered-model' };
    });
    window.elDesktopStartup = {
      validate: vi.fn().mockReturnValue(true),
      settingsStarted: vi.fn(async () => {
        order.push(backendReady ? 'settings-started:already-ready' : 'settings-started');
        return true;
      }),
      ready: vi.fn(async () => {
        order.push('ready');
        const responseDelivered = backendReady;
        backendReady = true;
        return responseDelivered;
      }),
    };
    setPywebview({ load_settings: load });
    const { result } = renderHook(() => useApiReady(appendConsole));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(backendReady).toBe(true);
    expect(result.current.apiReady).toBe(false);
    expect(result.current.apiKey).toBe('');
    expect(appendConsole).not.toHaveBeenCalled();

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(order).toEqual([
      'settings-started', 'load_settings', 'ready',
      'settings-started:already-ready', 'load_settings', 'ready',
    ]);
    expect(result.current.apiReady).toBe(true);
    expect(result.current.bridgeDelayed).toBe(false);
    expect(result.current.apiKey).toBe('recovered-key');
    expect(result.current.preferredModel).toBe('recovered-model');
    expect(appendConsole).toHaveBeenCalledExactlyOnceWith('Connesso a Python.');
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(load).toHaveBeenCalledTimes(2);
    expect(window.elDesktopStartup.ready).toHaveBeenCalledTimes(2);
  });

  it('does not invoke Python if the settings phase acknowledgement fails', async () => {
    const load = vi.fn();
    window.elDesktopStartup = {
      validate: vi.fn().mockReturnValue(true),
      settingsStarted: vi.fn().mockResolvedValue(false),
      ready: vi.fn(),
    };
    setPywebview({ load_settings: load });
    const { result } = renderHook(() => useApiReady(vi.fn()));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(load).not.toHaveBeenCalled();
    expect(window.elDesktopStartup.ready).not.toHaveBeenCalled();
    expect(result.current.apiReady).toBe(false);
  });

  it('ignores a settings phase acknowledgement after the hook unmounts', async () => {
    let acknowledge!: (ok: boolean) => void;
    window.elDesktopStartup = {
      validate: vi.fn().mockReturnValue(true),
      settingsStarted: vi.fn(() => new Promise<boolean>(resolve => { acknowledge = resolve; })),
      ready: vi.fn(),
    };
    const load = vi.fn();
    setPywebview({ load_settings: load });
    const { unmount } = renderHook(() => useApiReady(vi.fn()));
    unmount();
    await act(async () => { acknowledge(true); });
    expect(load).not.toHaveBeenCalled();
  });

  it('hydrates temporary credentials and retains the old plaintext warning through refresh', async () => {
    const load = vi.fn().mockResolvedValue({ api_key: 'temporary', credential_storage: { primary: 'session_only', fallback: 'absent' }, api_key_insecure: true });
    setPywebview({ load_settings: load });
    const { result } = renderHook(() => useApiReady(vi.fn()));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.apiKey).toBe('temporary');
    expect(result.current.apiKeyInsecureReason).toContain('solo per questa sessione');
    expect(result.current.apiKeyInsecureReason).toContain('in chiaro');
    load.mockResolvedValue({ api_key: 'protected', credential_storage: { primary: 'protected', fallback: 'absent' }, api_key_insecure: false });
    await act(async () => { await result.current.refreshSettings(); });
    expect(result.current.apiKeyInsecure).toBe(false);
    expect(result.current.apiKeyInsecureReason).toBe('');
  });

  it('5-second timeout does not set apiReady when bridge is absent', async () => {
    const { result } = renderHook(() => useApiReady(vi.fn()));

    expect(result.current.apiReady).toBe(false);
    expect(result.current.bridgeDelayed).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5001);
    });

    expect(result.current.apiReady).toBe(false);
    expect(result.current.bridgeDelayed).toBe(true);
  });

  it('pywebviewready after timeout still hydrates when bridge arrives late', async () => {
    const appendConsole = vi.fn();
    const mockLoad = vi.fn().mockResolvedValue({
      api_key: 'late-key',
      preferred_model: 'gemini-2.5-flash',
    });

    const { result } = renderHook(() => useApiReady(appendConsole));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5001);
    });
    expect(result.current.apiReady).toBe(false);
    expect(result.current.bridgeDelayed).toBe(true);

    setPywebview({ load_settings: mockLoad });

    await act(async () => {
      window.dispatchEvent(new Event('pywebviewready'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.apiReady).toBe(true);
    expect(result.current.bridgeDelayed).toBe(false);
    expect(result.current.apiKey).toBe('late-key');
    expect(result.current.preferredModel).toBe('gemini-2.5-flash');
    expect(appendConsole).toHaveBeenCalledWith('Connesso a Python.');
  });

  it('load_settings failure does not latch and allows retry on next pywebviewready', async () => {
    let call = 0;
    const mockLoad = vi.fn().mockImplementation(() => {
      call++;
      if (call === 1) return Promise.reject(new Error('transient'));
      return Promise.resolve({ api_key: 'retry-key' });
    });
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(vi.fn()));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.apiReady).toBe(false);

    await act(async () => {
      window.dispatchEvent(new Event('pywebviewready'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.apiReady).toBe(true);
    expect(result.current.apiKey).toBe('retry-key');
  });

  it('catch-triggered 2s retry recovers without pywebviewready', async () => {
    let call = 0;
    const mockLoad = vi.fn().mockImplementation(() => {
      call++;
      if (call === 1) return Promise.reject(new Error('transient'));
      return Promise.resolve({ api_key: 'recovered-key' });
    });
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(vi.fn()));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.apiReady).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2001);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.apiReady).toBe(true);
    expect(result.current.apiKey).toBe('recovered-key');
  });

  it('catch-retries are bounded: no new timer scheduled after retriesRef reaches 3', async () => {
    const mockLoad = vi.fn().mockRejectedValue(new Error('always fails'));
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(vi.fn()));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(7000);
    });

    expect(result.current.apiReady).toBe(false);
    expect(result.current.bridgeDelayed).toBe(true);
    const callsAt7s = mockLoad.mock.calls.length;
    // initial (t=0) + retry_B (t=2s) + retry_C (t=4s) + delayedWarning (t=5s) = 4;
    // delayedWarning cancels retry_D (scheduled by retry_C's catch, would fire at t=6s)
    expect(callsAt7s).toBeLessThanOrEqual(4);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(mockLoad.mock.calls.length).toBe(callsAt7s);
  });

  it('bridgeDelayed is set at 5s even when a call is in-flight at that moment', async () => {
    let resolve!: (value: unknown) => void;
    const mockLoad = vi.fn().mockImplementation(
      () => new Promise(res => { resolve = res; }),
    );
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(vi.fn()));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5001);
    });

    expect(result.current.apiReady).toBe(false);
    expect(result.current.bridgeDelayed).toBe(true);

    await act(async () => {
      resolve({ api_key: 'slow-key' });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.apiReady).toBe(true);
    expect(result.current.bridgeDelayed).toBe(false);
    expect(result.current.apiKey).toBe('slow-key');
  });

  it('success log is emitted exactly once, only after successful hydration', async () => {
    const appendConsole = vi.fn();
    const mockLoad = vi.fn().mockResolvedValue({ api_key: 'key' });
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(appendConsole));

    expect(appendConsole).not.toHaveBeenCalled();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.apiReady).toBe(true);
    expect(appendConsole).toHaveBeenCalledTimes(1);
    expect(appendConsole).toHaveBeenCalledWith('Connesso a Python.');
  });

  it('hydrates plaintext API key warning fields', async () => {
    const mockLoad = vi.fn().mockResolvedValue({
      api_key: 'plain-key',
      api_key_insecure: true,
      api_key_insecure_reason: 'DPAPI non disponibile',
    });
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(vi.fn()));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.apiKey).toBe('plain-key');
    expect(result.current.apiKeyInsecure).toBe(true);
    expect(result.current.apiKeyInsecureReason).toBe('DPAPI non disponibile');
  });

  it('hydrates config recovery path', async () => {
    const mockLoad = vi.fn().mockResolvedValue({
      api_key: '',
      config_recovered_from: 'C:\\Users\\me\\AppData\\Roaming\\jot\\config.json',
    });
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(vi.fn()));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.configRecoveredFrom).toBe('C:\\Users\\me\\AppData\\Roaming\\jot\\config.json');
  });

  it('refreshSettings reloads security flags after bootstrap', async () => {
    const mockLoad = vi.fn()
      .mockResolvedValueOnce({
        api_key: 'plain-key',
        api_key_insecure: true,
        api_key_insecure_reason: 'DPAPI non disponibile',
      })
      .mockResolvedValueOnce({
        api_key: 'protected-key',
        api_key_insecure: false,
        api_key_insecure_reason: '',
      });
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(vi.fn()));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.apiKeyInsecure).toBe(true);

    await act(async () => {
      await result.current.refreshSettings();
    });

    expect(mockLoad).toHaveBeenCalledTimes(2);
    expect(result.current.apiKey).toBe('protected-key');
    expect(result.current.apiKeyInsecure).toBe(false);
    expect(result.current.apiKeyInsecureReason).toBe('');
  });

  it('refreshSettings reloads config recovery path', async () => {
    const mockLoad = vi.fn()
      .mockResolvedValueOnce({ api_key: '' })
      .mockResolvedValueOnce({
        api_key: '',
        config_recovered_from: 'C:\\broken\\config.json',
      });
    setPywebview({ load_settings: mockLoad });

    const { result } = renderHook(() => useApiReady(vi.fn()));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.configRecoveredFrom).toBe('');

    await act(async () => {
      await result.current.refreshSettings();
    });

    expect(result.current.configRecoveredFrom).toBe('C:\\broken\\config.json');
  });
});
