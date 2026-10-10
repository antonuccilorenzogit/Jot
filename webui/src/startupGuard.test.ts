import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

function boot() {
  vi.useFakeTimers();
  const handlers: Record<string, (event: unknown) => void> = {};
  const send = vi.fn().mockResolvedValue({ ok: true });
  const page = {
    pywebview: undefined as unknown,
    elDesktopStartup: undefined as unknown as { validate: (v: string) => boolean; settingsStarted: () => Promise<boolean>; ready: () => Promise<boolean> },
    addEventListener: (name: string, handler: (event: unknown) => void) => { handlers[name] = handler; },
  };
  const location = { pathname: '/ui/build123/index.html' };
  const config = { build_id: 'build123', version: '2.7.3', attempt: 0, event_url: '/control/event' };
  runInNewContext(readFileSync(new URL('../public/startup-guard.js', import.meta.url), 'utf8'), {
    window: page, location,
    document: { querySelector: () => ({ content: JSON.stringify(config) }) },
    fetch: send, AbortController, Promise, setTimeout, clearTimeout,
  });
  return { page, handlers, send, location };
}

describe('desktop startup without Python bridge', () => {
  it('detects a mismatched bundle or document before enabling the app', () => {
    const { page, send, location } = boot();
    expect(page.elDesktopStartup.validate('v2.7.0')).toBe(false);
    expect(JSON.parse(send.mock.calls.at(-1)![1].body).kind).toBe('mismatch');
    location.pathname = '/ui/old/index.html';
    expect(page.elDesktopStartup.validate('v2.7.3')).toBe(false);
  });

  it('requires both bridge methods and an acknowledged settings handshake', async () => {
    const { page, send } = boot();
    expect(await page.elDesktopStartup.ready()).toBe(false);
    expect(page.elDesktopStartup.validate('v2.7.3')).toBe(true);
    page.pywebview = { api: { load_settings: () => undefined } };
    expect(await page.elDesktopStartup.ready()).toBe(false);
    page.pywebview = { api: { load_settings: () => undefined, save_settings: () => undefined } };
    expect(await page.elDesktopStartup.ready()).toBe(true);
    expect(JSON.parse(send.mock.calls.at(-1)![1].body)).toMatchObject({ kind: 'ready', version: '2.7.3', build_id: 'build123' });
  });

  it('captures missing modules and rejections without React or bridge', async () => {
    const { handlers, send } = boot();
    handlers.error({ target: { tagName: 'IMG', src: '/missing-image.png' } });
    handlers.error({ target: { tagName: 'SCRIPT', src: '/assets/missing.js' } });
    handlers.unhandledrejection({ reason: 'module import failed' });
    await vi.advanceTimersByTimeAsync(0);
    expect(send.mock.calls.map(call => JSON.parse(call[1].body).kind)).toEqual(['page', 'error', 'error']);
  });

  it('acknowledges the settings phase only for a validated bundle and available method', async () => {
    const { page, send } = boot();
    expect(await page.elDesktopStartup.settingsStarted()).toBe(false);
    page.elDesktopStartup.validate('v2.7.3');
    expect(await page.elDesktopStartup.settingsStarted()).toBe(false);
    page.pywebview = { api: { load_settings: () => undefined } };
    expect(await page.elDesktopStartup.settingsStarted()).toBe(true);
    expect(JSON.parse(send.mock.calls.at(-1)![1].body)).toMatchObject({ kind: 'settings-started', version: '2.7.3', attempt: 0 });
    send.mockResolvedValue({ ok: false });
    expect(await page.elDesktopStartup.settingsStarted()).toBe(false);
  });

  it('does not turn errors after a successful startup into recovery requests', async () => {
    const { page, handlers, send } = boot();
    page.elDesktopStartup.validate('v2.7.3');
    page.pywebview = { api: { load_settings: () => undefined, save_settings: () => undefined } };
    await page.elDesktopStartup.ready();
    handlers.error({ message: 'later pipeline error' });
    handlers.unhandledrejection({ reason: 'later rejection' });
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('fails a settings handshake when local reporting cannot be acknowledged', async () => {
    const { page, send } = boot();
    page.elDesktopStartup.validate('v2.7.3');
    page.pywebview = { api: { load_settings: () => undefined, save_settings: () => undefined } };
    send.mockRejectedValue(new Error('server unavailable'));
    expect(await page.elDesktopStartup.ready()).toBe(false);
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(0);
  });
});
