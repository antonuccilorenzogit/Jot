import { useEffect, useState } from 'react';
import { STORAGE_KEYS } from '../storageKeys';

const THEME_STORAGE_KEY = STORAGE_KEYS.THEME_V1;

export function useTheme() {
  const [themeMode, setThemeMode] = useState<'light' | 'dark'>(() => {
    try {
      const persisted = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (persisted === 'light' || persisted === 'dark') return persisted;
    } catch (_) {}
    try {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } catch (_) {}
    return 'dark';
  });

  useEffect(() => {
    try {
      document.documentElement.dataset.theme = themeMode;
      document.documentElement.style.colorScheme = themeMode;
    } catch (_) {}

    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
    } catch (_) {}

    try {
      window.pywebview?.api?.save_theme_preference?.(themeMode);
    } catch (_) {}
  }, [themeMode]);

  return { themeMode, setThemeMode };
}
