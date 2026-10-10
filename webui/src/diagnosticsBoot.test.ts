import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe('independent bootstrap diagnostics', () => {
  it('captures bundle failures before React loads and retries bridge delivery', async () => {
    vi.useFakeTimers();
    const handlers: Record<string, (event: unknown) => void> = {};
    const send = vi.fn().mockRejectedValueOnce(new Error('not ready')).mockResolvedValue({ ok: true });
    const page = {
      pywebview: undefined as unknown,
      addEventListener: (name: string, handler: (event: unknown) => void) => { handlers[name] = handler; },
    };
    const document = { documentElement: { dataset: {} as Record<string, string> } };
    runInNewContext(readFileSync(new URL('../public/diagnostics-boot.js', import.meta.url), 'utf8'), { window: page, document, Promise, setTimeout });
    handlers.error({ target: { tagName: 'SCRIPT', src: '/assets/main.js?token=private' } });
    handlers.error({ message: 'Syntax error', error: { stack: 'early stack' } });
    page.pywebview = { api: { record_frontend_event: send } };
    handlers.pywebviewready({});
    await vi.advanceTimersByTimeAsync(0);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(10000);
    expect(send).toHaveBeenCalledTimes(3);
    expect(send).toHaveBeenNthCalledWith(2, 'error', 'Bootstrap resource failed: /assets/main.js', '');
    expect(send).toHaveBeenLastCalledWith('error', 'Bootstrap error: Syntax error', 'early stack');
    document.documentElement.dataset.diagnosticsReady = 'true';
    handlers.error({ message: 'Handled by main collector' });
    expect(send).toHaveBeenCalledTimes(3);
  });

  it.each(['rejected', 'not-ok', 'throwing'])('bounds retries for a %s bridge and retains FIFO delivery', async failure => {
    vi.useFakeTimers();
    const handlers: Record<string, (event: unknown) => void> = {};
    const send = vi.fn().mockImplementation(() => {
      if (failure === 'throwing') throw new Error('bridge busy');
      if (failure === 'rejected') return Promise.reject(new Error('bridge busy'));
      return Promise.resolve({ ok: false });
    });
    const page = {
      pywebview: { api: { record_frontend_event: send } },
      addEventListener: (name: string, handler: (event: unknown) => void) => { handlers[name] = handler; },
    };
    runInNewContext(readFileSync(new URL('../public/diagnostics-boot.js', import.meta.url), 'utf8'), {
      window: page, document: { documentElement: { dataset: {} } }, Promise, setTimeout,
    });
    handlers.error({ message: 'first' });
    handlers.error({ message: 'second' });
    await vi.advanceTimersByTimeAsync(10000);
    expect(send).toHaveBeenCalledTimes(4);
    expect(send.mock.calls.every(call => call[1] === 'Bootstrap error: first')).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    send.mockResolvedValue({ ok: true });
    handlers.error({ message: 'third' });
    await vi.advanceTimersByTimeAsync(0);
    expect(send.mock.calls.slice(4).map(call => call[1])).toEqual([
      'Bootstrap error: first', 'Bootstrap error: second', 'Bootstrap error: third',
    ]);
  });
});
