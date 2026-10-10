import { afterEach, describe, expect, it, vi } from 'vitest';
import { beginDesktopSettingsLoad, completeDesktopStartup, validateDesktopBuild } from './desktopStartup';

afterEach(() => {
  delete window.elDesktopStartup;
  document.querySelector('meta[name="jot-startup"]')?.remove();
});

describe('desktop settings handshake', () => {
  it('leaves browser previews unaffected', async () => {
    expect(() => validateDesktopBuild('v1.0.0')).not.toThrow();
    await expect(beginDesktopSettingsLoad()).resolves.toBeUndefined();
    await expect(completeDesktopStartup()).resolves.toBeUndefined();
  });

  it('rejects a different build before mounting', () => {
    window.elDesktopStartup = { validate: vi.fn().mockReturnValue(false), settingsStarted: vi.fn(), ready: vi.fn() };
    expect(() => validateDesktopBuild('v2.7.0')).toThrow('non corrisponde');
  });

  it('rejects a desktop page whose independent startup script failed to load', () => {
    const meta = document.createElement('meta');
    meta.name = 'jot-startup';
    document.head.appendChild(meta);
    expect(() => validateDesktopBuild('v2.7.3')).toThrow('non è stato caricato');
  });

  it('waits for the startup acknowledgement and propagates failure', async () => {
    let resolve!: (ok: boolean) => void;
    window.elDesktopStartup = {
      validate: vi.fn().mockReturnValue(true),
      settingsStarted: vi.fn().mockResolvedValue(true),
      ready: vi.fn(() => new Promise<boolean>(done => { resolve = done; })),
    };
    validateDesktopBuild('v2.7.3');
    const promise = completeDesktopStartup();
    resolve(false);
    await expect(promise).rejects.toThrow('non riuscita');
    window.elDesktopStartup.ready = vi.fn().mockResolvedValue(true);
    await expect(completeDesktopStartup()).resolves.toBeUndefined();
  });

  it('requires an acknowledged settings phase before asking Python to load', async () => {
    window.elDesktopStartup = {
      validate: vi.fn().mockReturnValue(true),
      settingsStarted: vi.fn().mockResolvedValue(false),
      ready: vi.fn(),
    };
    await expect(beginDesktopSettingsLoad()).rejects.toThrow('non confermato');
    window.elDesktopStartup.settingsStarted = vi.fn().mockResolvedValue(true);
    await expect(beginDesktopSettingsLoad()).resolves.toBeUndefined();
  });
});
