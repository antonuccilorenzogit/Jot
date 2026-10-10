import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { APP_VERSION } from '../branding';
import { useUpdateChecker } from './useUpdateChecker';

const LAST_CHECK_KEY = 'jot.last-update-check.v1';
const DISMISSED_KEY = 'jot.dismissed-update.v1';
const CACHE_KEY = 'jot.latest-release-cache.v1';

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('useUpdateChecker', () => {
  it('does not contact the release service when update support is disabled', async () => {
    const { result } = renderHook(() => useUpdateChecker(false));

    await act(async () => {
      await Promise.resolve();
    });

    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.hasChecked).toBe(false);
  });

  it('starts with no update available', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: null })));
    const { result } = renderHook(() => useUpdateChecker());
    expect(result.current.updateAvailable).toBeNull();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  });

  it('detects a newer version', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.updateAvailable).toBe('v99.0.0');
  });

  it('does not show update for same version', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: APP_VERSION })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.updateAvailable).toBeNull();
    expect(result.current.latestVersion).toBeNull();
  });

  it('does not expose latestVersion for older versions', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v0.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.updateAvailable).toBeNull();
    expect(result.current.latestVersion).toBeNull();
  });

  it('dismissUpdate clears updateAvailable and saves to localStorage', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => {
      result.current.dismissUpdate('v99.0.0');
    });
    expect(result.current.updateAvailable).toBeNull();
    expect(localStorage.getItem(DISMISSED_KEY)).toBe('v99.0.0');
  });

  it('isDismissed starts false', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: null })));
    const { result } = renderHook(() => useUpdateChecker());
    expect(result.current.isDismissed).toBe(false);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  });

  it('isDismissed is false when new update is available (banner active)', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.isDismissed).toBe(false);
    expect(result.current.updateAvailable).toBe('v99.0.0');
  });

  it('isDismissed becomes true after dismissUpdate', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => { result.current.dismissUpdate('v99.0.0'); });
    expect(result.current.isDismissed).toBe(true);
    expect(result.current.updateAvailable).toBeNull();
  });

  it('isDismissed is true on startup when previously dismissed version matches', async () => {
    localStorage.setItem(DISMISSED_KEY, 'v99.0.0');
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.isDismissed).toBe(true);
    expect(result.current.updateAvailable).toBeNull();
  });

  it('isDismissed resets to false when a newer undismissed version is found', async () => {
    localStorage.setItem(DISMISSED_KEY, 'v99.0.0');
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify({ tag_name: 'v99.0.0' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tag_name: 'v100.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.isDismissed).toBe(true);
    await act(async () => { result.current.checkForUpdates(true); });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.isDismissed).toBe(false);
    expect(result.current.updateAvailable).toBe('v100.0.0');
  });

  it('skips fetch if already checked recently', async () => {
    localStorage.setItem(LAST_CHECK_KEY, String(Date.now()));
    renderHook(() => useUpdateChecker());
    await act(async () => { await Promise.resolve(); });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('does not show update if version equals dismissed version', async () => {
    localStorage.setItem(DISMISSED_KEY, 'v99.0.0');
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.updateAvailable).toBeNull();
  });

  it('handles fetch error gracefully', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('network error'));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => { await Promise.resolve(); });
    expect(result.current.updateAvailable).toBeNull();
  });

  it('sets checkFailed=true on network error', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('network error'));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => { await Promise.resolve(); });
    expect(result.current.checkFailed).toBe(true);
  });

  it('sets checkFailed=false on successful fetch', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.checkFailed).toBe(false);
  });

  it('checkFailed=true cleared to false on subsequent successful fetch (force)', async () => {
    vi.mocked(fetch)
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tag_name: null })));
    const { result } = renderHook(() => useUpdateChecker());
    await act(async () => { await Promise.resolve(); });
    expect(result.current.checkFailed).toBe(true);
    await act(async () => { result.current.checkForUpdates(true); });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.checkFailed).toBe(false);
  });

  it('successful fetch writes latest release cache', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));

    renderHook(() => useUpdateChecker());

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const cached = JSON.parse(localStorage.getItem(CACHE_KEY) ?? '{}');
    expect(cached.version).toBe('v99.0.0');
    expect(typeof cached.checkedAt).toBe('number');
  });

  it('failed fetch uses cached newer version', async () => {
    localStorage.setItem(CACHE_KEY, JSON.stringify({
      version: 'v99.0.0',
      checkedAt: Date.now(),
    }));
    vi.mocked(fetch).mockRejectedValue(new Error('network error'));

    const { result } = renderHook(() => useUpdateChecker());

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.updateAvailable).toBe('v99.0.0');
    expect(result.current.latestVersion).toBe('v99.0.0');
    expect(result.current.checkFailed).toBe(false);
  });

  it('rate-limited fetch uses cached newer version', async () => {
    localStorage.setItem(CACHE_KEY, JSON.stringify({
      version: 'v99.0.0',
      checkedAt: Date.now(),
    }));
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ message: 'rate limit' }), { status: 403 }));

    const { result } = renderHook(() => useUpdateChecker());

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.updateAvailable).toBe('v99.0.0');
    expect(result.current.checkFailed).toBe(false);
  });

  it('expired cache is ignored on failed fetch', async () => {
    localStorage.setItem(CACHE_KEY, JSON.stringify({
      version: 'v99.0.0',
      checkedAt: Date.now() - (25 * 60 * 60 * 1000),
    }));
    vi.mocked(fetch).mockRejectedValue(new Error('network error'));

    const { result } = renderHook(() => useUpdateChecker());

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.updateAvailable).toBeNull();
    expect(result.current.checkFailed).toBe(true);
  });

  it('failed fetch ignores cached current version as an installable update', async () => {
    localStorage.setItem(CACHE_KEY, JSON.stringify({
      version: APP_VERSION,
      checkedAt: Date.now(),
    }));
    vi.mocked(fetch).mockRejectedValue(new Error('network error'));

    const { result } = renderHook(() => useUpdateChecker());

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.updateAvailable).toBeNull();
    expect(result.current.latestVersion).toBeNull();
    expect(result.current.checkFailed).toBe(false);
  });

  it('dismissed cached version remains hidden', async () => {
    localStorage.setItem(DISMISSED_KEY, 'v99.0.0');
    localStorage.setItem(CACHE_KEY, JSON.stringify({
      version: 'v99.0.0',
      checkedAt: Date.now(),
    }));
    vi.mocked(fetch).mockRejectedValue(new Error('network error'));

    const { result } = renderHook(() => useUpdateChecker());

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.updateAvailable).toBeNull();
    expect(result.current.isDismissed).toBe(true);
    expect(result.current.checkFailed).toBe(false);
  });

  it('manual force fetches even inside 15-minute throttle', async () => {
    localStorage.setItem(LAST_CHECK_KEY, String(Date.now()));
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tag_name: 'v99.0.0' })));

    const { result } = renderHook(() => useUpdateChecker());

    await act(async () => {
      await Promise.resolve();
    });
    expect(fetch).not.toHaveBeenCalled();

    await act(async () => {
      result.current.checkForUpdates(true);
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(result.current.updateAvailable).toBe('v99.0.0');
  });

  it('clears stale latestVersion when forced successful fetch has no tag_name', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify({ tag_name: 'v99.0.0' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tag_name: null })));

    const { result } = renderHook(() => useUpdateChecker());

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.updateAvailable).toBe('v99.0.0');
    expect(result.current.latestVersion).toBe('v99.0.0');

    await act(async () => {
      result.current.checkForUpdates(true);
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.updateAvailable).toBeNull();
    expect(result.current.latestVersion).toBeNull();
  });
});
