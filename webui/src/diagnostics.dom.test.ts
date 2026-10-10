import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  delete window.pywebview;
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('support error collection', () => {
  it('queues errors before the bridge, retries failed delivery and deduplicates', async () => {
    vi.useFakeTimers();
    vi.resetModules();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const listeners: EventListener[] = [];
    vi.spyOn(window, 'addEventListener').mockImplementation((name, listener) => {
      if (name === 'pywebviewready') listeners.push(listener as EventListener);
    });
    const diagnostics = await import('./diagnostics');
    diagnostics.installFrontendDiagnostics();
    diagnostics.installFrontendDiagnostics();
    diagnostics.reportClientError('autosave', new Error('disk full'));
    diagnostics.reportClientError('autosave', new Error('disk full'));
    const send = vi.fn().mockRejectedValueOnce(new Error('bridge busy')).mockResolvedValue({ ok: true });
    window.pywebview = { api: { record_frontend_event: send } } as unknown as NonNullable<typeof window.pywebview>;
    listeners[0](new Event('pywebviewready'));
    await vi.advanceTimersByTimeAsync(0);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(10000);
    expect(send).toHaveBeenCalledTimes(2);
    expect(send).toHaveBeenLastCalledWith('error', 'autosave: disk full', expect.stringContaining('disk full'));
    expect(listeners).toHaveLength(1);
  });

  it.each(['rejected', 'not-ok', 'throwing'])('bounds retries for a %s bridge and retains FIFO delivery', async failure => {
    vi.useFakeTimers();
    vi.resetModules();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const send = vi.fn().mockImplementation(() => {
      if (failure === 'throwing') throw new Error('bridge busy');
      if (failure === 'rejected') return Promise.reject(new Error('bridge busy'));
      return Promise.resolve({ ok: false });
    });
    window.pywebview = { api: { record_frontend_event: send } } as unknown as NonNullable<typeof window.pywebview>;
    const diagnostics = await import('./diagnostics');
    diagnostics.reportClientError('first', 'failure');
    diagnostics.reportClientError('second', 'failure');
    await vi.advanceTimersByTimeAsync(10000);
    expect(send).toHaveBeenCalledTimes(4);
    expect(send.mock.calls.every(call => call[1] === 'first: failure')).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    send.mockResolvedValue({ ok: true });
    diagnostics.reportClientError('third', 'failure');
    await vi.advanceTimersByTimeAsync(0);
    expect(send.mock.calls.slice(4).map(call => call[1])).toEqual(['first: failure', 'second: failure', 'third: failure']);
  });

  it('bounds the queue and payloads while the bridge is unavailable', async () => {
    vi.resetModules();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const diagnostics = await import('./diagnostics');
    for (let index = 0; index < 50; index++) diagnostics.reportClientError(String(index), 'x'.repeat(5000));
    const send = vi.fn().mockResolvedValue({ ok: true });
    window.pywebview = { api: { record_frontend_event: send } } as unknown as NonNullable<typeof window.pywebview>;
    // A distinct event triggers delivery of the bounded pending queue.
    diagnostics.reportClientError('late', 'late');
    diagnostics.installFrontendDiagnostics();
    window.dispatchEvent(new Event('pywebviewready'));
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(20));
    expect(send.mock.calls.every(call => call[1].length <= 3000)).toBe(true);
  });
});
