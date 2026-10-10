import { useCallback, useEffect, useRef, useState } from 'react';
import { APP_VERSION, GITHUB_API_RELEASES_URL } from '../branding';
import { compareVersions } from '../utils';

const UPDATE_DISMISSED_KEY = 'jot.dismissed-update.v1';
const UPDATE_LAST_CHECK_KEY = 'jot.last-update-check.v1';
const UPDATE_LATEST_CACHE_KEY = 'jot.latest-release-cache.v1';
const UPDATE_CHECK_INTERVAL_MS = 15 * 60 * 1000;
const UPDATE_CACHE_VALID_MS = 24 * 60 * 60 * 1000;

type LatestReleaseCache = {
  version: string;
  checkedAt: number;
};


const readCachedLatest = (): LatestReleaseCache | null => {
  try {
    const raw = window.localStorage.getItem(UPDATE_LATEST_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LatestReleaseCache>;
    const version = typeof parsed.version === 'string' ? parsed.version : '';
    const checkedAt = typeof parsed.checkedAt === 'number' ? parsed.checkedAt : 0;
    if (!version || !checkedAt) return null;
    if (Date.now() - checkedAt > UPDATE_CACHE_VALID_MS) return null;
    return { version, checkedAt };
  } catch (_) {
    return null;
  }
};

const writeCachedLatest = (version: string) => {
  try {
    window.localStorage.setItem(
      UPDATE_LATEST_CACHE_KEY,
      JSON.stringify({ version, checkedAt: Date.now() }),
    );
  } catch (_) {}
};

export function useUpdateChecker(enabled: boolean = true) {
  const [updateAvailable, setUpdateAvailable] = useState<string | null>(null);
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  const [isDismissed, setIsDismissed] = useState(false);
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false);
  const [hasChecked, setHasChecked] = useState(false);
  const [checkFailed, setCheckFailed] = useState(false);
  const isCheckingRef = useRef(false);

  const applyLatestVersion = useCallback((latest: string | null): boolean => {
    if (!latest) {
      setLatestVersion(null);
      setUpdateAvailable(null);
      setIsDismissed(false);
      return false;
    }
    setUpdateAvailable(null);
    if (compareVersions(latest, APP_VERSION) > 0) {
      setLatestVersion(latest);
      try {
        const dismissed = window.localStorage.getItem(UPDATE_DISMISSED_KEY);
        if (dismissed !== latest) {
          setUpdateAvailable(latest);
          setIsDismissed(false);
        } else {
          setIsDismissed(true);
        }
      } catch (_) {
        setUpdateAvailable(latest);
        setIsDismissed(false);
      }
    } else {
      setLatestVersion(null);
      setIsDismissed(false);
    }
    return true;
  }, []);

  const checkForUpdates = useCallback((force: boolean = false) => {
    if (!enabled) return;
    if (isCheckingRef.current) return;
    if (!force) {
      try {
        const lastCheck = Number(window.localStorage.getItem(UPDATE_LAST_CHECK_KEY) || 0);
        if (Date.now() - lastCheck < UPDATE_CHECK_INTERVAL_MS) return;
      } catch (_) {}
    }
    isCheckingRef.current = true;
    if (force) setIsCheckingUpdate(true);
    fetch(GITHUB_API_RELEASES_URL)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(data => {
        try { window.localStorage.setItem(UPDATE_LAST_CHECK_KEY, String(Date.now())); } catch (_) {}
        const latest: string = data?.tag_name;
        if (!latest) {
          setLatestVersion(null);
          setUpdateAvailable(null);
          setIsDismissed(false);
          setCheckFailed(false);
          return;
        }
        writeCachedLatest(latest);
        applyLatestVersion(latest);
        setCheckFailed(false);
      })
      .catch(() => {
        const cached = readCachedLatest();
        if (cached && applyLatestVersion(cached.version)) {
          setCheckFailed(false);
          return;
        }
        setCheckFailed(true);
      })
      .finally(() => {
        isCheckingRef.current = false;
        if (force) setIsCheckingUpdate(false);
        setHasChecked(true);
      });
  }, [applyLatestVersion, enabled]);

  useEffect(() => {
    if (enabled) checkForUpdates(false);
  }, [checkForUpdates, enabled]);

  const dismissUpdate = useCallback((version: string) => {
    try { window.localStorage.setItem(UPDATE_DISMISSED_KEY, version); } catch (_) {}
    setUpdateAvailable(null);
    setIsDismissed(true);
  }, []);

  return { updateAvailable, latestVersion, isDismissed, isCheckingUpdate, hasChecked, checkFailed, checkForUpdates, dismissUpdate };
}
