import { useEffect, useRef, useSyncExternalStore } from 'react';

function getNavigatorOnLine(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.onLine === 'boolean'
    ? navigator.onLine
    : true;
}

let currentOnlineStatus: boolean = getNavigatorOnLine();
const listeners = new Set<() => void>();

function handleOnline() {
  currentOnlineStatus = true;
  listeners.forEach((listener) => listener());
}

function handleOffline() {
  currentOnlineStatus = false;
  listeners.forEach((listener) => listener());
}

function subscribe(callback: () => void) {
  if (listeners.size === 0 && typeof window !== 'undefined') {
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
  }
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
    if (listeners.size === 0 && typeof window !== 'undefined') {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    }
  };
}

function getSnapshot(): boolean {
  if (typeof navigator !== 'undefined' && typeof navigator.onLine === 'boolean' && !navigator.onLine) {
    return false;
  }
  return currentOnlineStatus;
}

function getServerSnapshot(): boolean {
  return true;
}

export function useOnlineStatus(onStatusChange?: (isOnline: boolean) => void): boolean {
  const isOnline = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const callbackRef = useRef(onStatusChange);

  useEffect(() => {
    callbackRef.current = onStatusChange;
  }, [onStatusChange]);

  const prevOnlineRef = useRef(isOnline);
  useEffect(() => {
    if (prevOnlineRef.current !== isOnline) {
      prevOnlineRef.current = isOnline;
      callbackRef.current?.(isOnline);
    }
  }, [isOnline]);

  return isOnline;
}
