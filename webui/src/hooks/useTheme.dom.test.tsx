import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useTheme } from './useTheme';
import type { PywebviewApi } from '../bridge';

const THEME_KEY = 'jot.theme.v1';

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('useTheme', () => {
  it('defaults to dark mode', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.themeMode).toBe('dark');
  });

  it('restores persisted light theme from localStorage', async () => {
    localStorage.setItem(THEME_KEY, 'light');
    const { result } = renderHook(() => useTheme());
    await act(async () => {});
    expect(result.current.themeMode).toBe('light');
  });

  it('restores persisted dark theme from localStorage', async () => {
    localStorage.setItem(THEME_KEY, 'dark');
    const { result } = renderHook(() => useTheme());
    await act(async () => {});
    expect(result.current.themeMode).toBe('dark');
  });

  it('persists theme change to localStorage', async () => {
    const { result } = renderHook(() => useTheme());
    await act(async () => {
      result.current.setThemeMode('light');
    });
    expect(localStorage.getItem(THEME_KEY)).toBe('light');
  });

  it('sets data-theme on documentElement', async () => {
    const { result } = renderHook(() => useTheme());
    await act(async () => {
      result.current.setThemeMode('light');
    });
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('setThemeMode toggles between light and dark', async () => {
    const { result } = renderHook(() => useTheme());
    await act(async () => { result.current.setThemeMode('light'); });
    expect(result.current.themeMode).toBe('light');
    await act(async () => { result.current.setThemeMode('dark'); });
    expect(result.current.themeMode).toBe('dark');
  });

  it('defaults to dark mode when matchMedia throws', () => {
    const originalMatchMedia = window.matchMedia;
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: () => { throw new Error('matchMedia not supported'); }
    });

    try {
      const { result } = renderHook(() => useTheme());
      expect(result.current.themeMode).toBe('dark');
    } finally {
      if (originalMatchMedia) {
        window.matchMedia = originalMatchMedia;
      } else {
        delete (window as Partial<Window>).matchMedia;
      }
    }
  });

  it('defaults to light mode when prefers-color-scheme: dark matches false', () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as MediaQueryList);

    try {
      const { result } = renderHook(() => useTheme());
      expect(result.current.themeMode).toBe('light');
    } finally {
      window.matchMedia = originalMatchMedia;
    }
  });

  it('defaults to dark mode when prefers-color-scheme: dark matches true', () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as MediaQueryList);

    try {
      const { result } = renderHook(() => useTheme());
      expect(result.current.themeMode).toBe('dark');
    } finally {
      window.matchMedia = originalMatchMedia;
    }
  });

  it('falls back to matchMedia when localStorage.getItem throws', () => {
    const originalGetItem = Storage.prototype.getItem;
    Storage.prototype.getItem = vi.fn().mockImplementation(() => {
      throw new Error('Storage error');
    });

    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
    }) as unknown as MediaQueryList);

    try {
      const { result } = renderHook(() => useTheme());
      expect(result.current.themeMode).toBe('light');
    } finally {
      Storage.prototype.getItem = originalGetItem;
      window.matchMedia = originalMatchMedia;
    }
  });

  it('tolerates localStorage.setItem throwing errors when setting theme', async () => {
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = vi.fn().mockImplementation(() => {
      throw new Error('Storage quota exceeded');
    });

    try {
      const { result } = renderHook(() => useTheme());
      await act(async () => {
        result.current.setThemeMode('light');
      });
      expect(result.current.themeMode).toBe('light');
    } finally {
      Storage.prototype.setItem = originalSetItem;
    }
  });

  it('calls pywebview API if available', async () => {
    const saveThemeMock = vi.fn();
    const originalPyWebview = window.pywebview;
    window.pywebview = {
      api: {
        save_theme_preference: saveThemeMock as unknown as PywebviewApi["save_theme_preference"],
      },
    };

    try {
      const { result } = renderHook(() => useTheme());
      await act(async () => {
        result.current.setThemeMode('light');
      });
      expect(saveThemeMock).toHaveBeenCalledWith('light');
    } finally {
      window.pywebview = originalPyWebview;
    }
  });
});
