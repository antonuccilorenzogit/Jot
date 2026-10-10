import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { APP_VERSION, GITHUB_RELEASES_URL } from '../branding';
import type { NotificationMessage } from '../components/NotificationDropdown';
import { STORAGE_KEYS } from '../storageKeys';
import { compareVersions } from '../utils';

export const NOTIFICATIONS_STORAGE_KEY = STORAGE_KEYS.NOTIFICATIONS_V1;

export type NotificationType = 'info' | 'warning' | 'error' | 'success';
export type NotificationCategory = 'processing' | 'update' | 'system';
export type NotificationActionType = 'retry_failed_revision_blocks' | 'install_update' | 'open_github' | 'open_settings';

export interface PersistedNotification {
  id: string;
  title: string;
  message: string;
  type: NotificationType;
  category: NotificationCategory;
  timestamp: number;
  read: boolean;
  persistent?: boolean;
  dedupeKey?: string;
  actionType?: NotificationActionType;
  actionData?: unknown;
}

export interface AddNotificationOptions {
  persistent?: boolean;
  dedupeKey?: string;
  actionType?: NotificationActionType;
  actionData?: unknown;
}

export interface UseNotificationsOptions {
  onRetryFailedRevisionBlocks?: (sessionDir: string, fileId?: string) => Promise<void>;
  onInstallUpdate?: (version: string) => Promise<void>;
  onDismissUpdate?: (version: string) => void;
  onOpenUrl?: (url: string) => Promise<void>;
  updateAvailable?: string | null;
  onOpenSettings?: () => void;
  currentAppVersion?: string;
}

interface NotificationsBootstrap {
  appVersion: string;
  didUpgrade: boolean;
  notifications: PersistedNotification[];
}

export function sanitizePersistedNotifications(list: unknown, currentAppVersion: string = APP_VERSION): PersistedNotification[] {
  if (!Array.isArray(list)) return [];
  const result: PersistedNotification[] = [];

  for (const item of list) {
    if (!item || typeof item !== 'object') continue;
    const n = item as PersistedNotification;

    // Remove stale in-progress update notifications from prior sessions
    if (n.dedupeKey === 'update-install') {
      continue;
    }

    // Remove stale update-available notifications if currentAppVersion >= targetVersion
    if (n.dedupeKey === 'update-available') {
      const actionData = n.actionData as Record<string, unknown> | undefined;
      const targetVersion = (typeof actionData?.version === 'string' ? actionData.version : '') || '';
      if (!targetVersion || compareVersions(currentAppVersion, targetVersion) >= 0) {
        continue;
      }
    }

    if (typeof n.message === 'string' && n.message.includes('regenerate_prompt_timeout')) {
      const cleanMessage = n.message
        .replace(
          'regenerate_prompt_timeout',
          'Nessuna scelta ricevuta sulla ripresa entro 120 secondi. Sessione salvata: clicca Riprendi per continuare.'
        )
        .replace(/^Errore per /, 'Per ');
      result.push({
        ...n,
        title: n.title === 'Errore elaborazione' ? 'Elaborazione in pausa' : n.title,
        type: n.type === 'error' ? 'warning' : n.type,
        message: cleanMessage,
      });
      continue;
    }

    result.push(n);
  }

  return result;
}

function loadNotificationsBootstrap(currentAppVersion?: string): NotificationsBootstrap {
  let storedList: unknown = [];
  try {
    const stored = localStorage.getItem(NOTIFICATIONS_STORAGE_KEY);
    storedList = stored ? JSON.parse(stored) : [];
  } catch (_) {
    storedList = [];
  }

  const appVersion = currentAppVersion || APP_VERSION;
  const notifications = sanitizePersistedNotifications(storedList, appVersion);
  let didUpgrade = false;

  try {
    const lastSeenVersion = localStorage.getItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1);
    if (lastSeenVersion) {
      didUpgrade = compareVersions(appVersion, lastSeenVersion) > 0;
    } else if (Array.isArray(storedList) && storedList.length > 0) {
      didUpgrade = storedList.some(item => {
        const n = item as PersistedNotification;
        if (!n) return false;
        if (n.dedupeKey === 'update-install') return true;
        if (n.dedupeKey === 'update-available') {
          const actionData = n.actionData as Record<string, unknown> | undefined;
          const targetVersion = (typeof actionData?.version === 'string' ? actionData.version : '') || '';
          return Boolean(targetVersion && compareVersions(appVersion, targetVersion) >= 0);
        }
        return false;
      });
    }
  } catch (_) {}

  return { appVersion, didUpgrade, notifications };
}

export function useNotifications(options: UseNotificationsOptions = {}) {
  const optionsRef = useRef(options);
  useLayoutEffect(() => {
    optionsRef.current = options;
  });

  const [bootstrap] = useState(() => loadNotificationsBootstrap(options.currentAppVersion));
  const [rawNotifications, setRawNotifications] = useState<PersistedNotification[]>(bootstrap.notifications);

  useEffect(() => {
    try {
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(rawNotifications));
    } catch (_) {}
  }, [rawNotifications]);

  useEffect(() => {
    let committedNotifications = bootstrap.notifications;

    if (bootstrap.didUpgrade) {
      const successDedupeKey = `update-success:${bootstrap.appVersion}`;
      const alreadyHasSuccess = committedNotifications.some(n => n.dedupeKey === successDedupeKey);
      if (!alreadyHasSuccess) {
        const successNotif: PersistedNotification = {
          id: crypto.randomUUID(),
          title: 'Aggiornamento completato',
          message: `jot è stato aggiornato alla versione ${bootstrap.appVersion}.`,
          type: 'success',
          category: 'update',
          timestamp: Date.now(),
          read: false,
          persistent: true,
          dedupeKey: successDedupeKey,
        };
        committedNotifications = [successNotif, ...committedNotifications].slice(0, 50);
        setRawNotifications(committedNotifications);
      }
    }

    let notificationsPersisted = true;
    try {
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(committedNotifications));
    } catch (_) {
      notificationsPersisted = false;
    }

    if (!bootstrap.didUpgrade || notificationsPersisted) {
      try {
        localStorage.setItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1, bootstrap.appVersion);
      } catch (_) {}
    }
  }, [bootstrap]);

  const deleteNotification = useCallback((id: string) => {
    setRawNotifications(prev => {
      const notif = prev.find(n => n.id === id);
      if (notif?.dedupeKey?.startsWith('config-recovery:')) {
        const recoveredPath = notif.dedupeKey.split('config-recovery:')[1];
        const storageKey = `jot.config-recovery-dismissed.v1:${recoveredPath}`;
        try { localStorage.setItem(storageKey, '1'); } catch (_) {}
      }
      if (notif?.dedupeKey === 'update-available') {
        const actionData = notif.actionData as Record<string, unknown> | undefined;
        const version = (typeof actionData?.version === 'string' ? actionData.version : undefined) || optionsRef.current.updateAvailable;
        if (version && optionsRef.current.onDismissUpdate) {
          optionsRef.current.onDismissUpdate(version);
        }
      }
      return prev.filter(n => n.id !== id);
    });
  }, []);

  const markNotificationAsRead = useCallback((id: string) => {
    setRawNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
  }, []);

  const markAllNotificationsAsRead = useCallback(() => {
    setRawNotifications(prev => prev.map(n => ({ ...n, read: true })));
  }, []);

  const clearAllNotifications = useCallback(() => {
    setRawNotifications(prev => {
      prev.forEach(notif => {
        if (notif.dedupeKey?.startsWith('config-recovery:')) {
          const recoveredPath = notif.dedupeKey.split('config-recovery:')[1];
          const storageKey = `jot.config-recovery-dismissed.v1:${recoveredPath}`;
          try { localStorage.setItem(storageKey, '1'); } catch (_) {}
        }
        if (notif.dedupeKey === 'update-available') {
          const actionData = notif.actionData as Record<string, unknown> | undefined;
          const version = (typeof actionData?.version === 'string' ? actionData.version : undefined) || optionsRef.current.updateAvailable;
          if (version && optionsRef.current.onDismissUpdate) {
            optionsRef.current.onDismissUpdate(version);
          }
        }
      });
      return [];
    });
  }, []);

  const removeNotificationByDedupeKey = useCallback((dedupeKey: string) => {
    setRawNotifications(prev => prev.filter(n => n.dedupeKey !== dedupeKey));
  }, []);

  const addNotification = useCallback((
    title: string,
    message: string,
    type: NotificationType = 'info',
    category: NotificationCategory = 'system',
    opts?: AddNotificationOptions
  ) => {
    setRawNotifications(prev => {
      if (opts?.dedupeKey) {
        const exists = prev.some(n => n.dedupeKey === opts.dedupeKey);
        if (exists) return prev;
      }
      const newNotif: PersistedNotification = {
        id: crypto.randomUUID(),
        title,
        message,
        type,
        category,
        timestamp: Date.now(),
        read: false,
        persistent: opts?.persistent,
        dedupeKey: opts?.dedupeKey,
        actionType: opts?.actionType,
        actionData: opts?.actionData,
      };
      return [newNotif, ...prev].slice(0, 50);
    });
  }, []);

  const rawNotificationsRef = useRef(rawNotifications);
  useLayoutEffect(() => {
    rawNotificationsRef.current = rawNotifications;
  }, [rawNotifications]);

  const upsertNotification = useCallback((
    title: string,
    message: string,
    type: NotificationType,
    category: NotificationCategory,
    opts?: AddNotificationOptions
  ) => {
    const existing = opts?.dedupeKey
      ? rawNotificationsRef.current.find(n => n.dedupeKey === opts.dedupeKey)
      : undefined;
    const targetId = existing ? existing.id : crypto.randomUUID();

    setRawNotifications(prev => {
      if (opts?.dedupeKey) {
        const idx = prev.findIndex(n => n.dedupeKey === opts.dedupeKey);
        if (idx !== -1) {
          const updated = [...prev];
          updated[idx] = {
            ...updated[idx],
            title,
            message,
            type,
            category,
            timestamp: Date.now(),
            read: false,
            actionType: opts?.actionType,
            actionData: opts?.actionData,
          };
          return updated;
        }
      }
      const newNotif: PersistedNotification = {
        id: targetId,
        title,
        message,
        type,
        category,
        timestamp: Date.now(),
        read: false,
        persistent: opts?.persistent,
        dedupeKey: opts?.dedupeKey,
        actionType: opts?.actionType,
        actionData: opts?.actionData,
      };
      return [newNotif, ...prev].slice(0, 50);
    });
    return targetId;
  }, []);

  const bindNotificationActions = useCallback((raw: PersistedNotification[]): NotificationMessage[] => {
    return raw.map(n => {
      if (!n.actionType) return { ...n } as NotificationMessage;

      let onAction: () => Promise<void>;
      let label = '';
      let loadingLabel = '';
      let errorSuffix = '';
      const actionData = n.actionData as Record<string, unknown> | undefined;

      if (n.actionType === 'retry_failed_revision_blocks') {
        label = 'Riprova';
        loadingLabel = 'Riprovo...';
        errorSuffix = 'puoi usare il pulsante sulla scheda';
        onAction = async () => {
          const sessionDir = typeof actionData?.sessionDir === 'string' ? actionData.sessionDir : '';
          const fileId = typeof actionData?.fileId === 'string' ? actionData.fileId : undefined;
          await optionsRef.current.onRetryFailedRevisionBlocks?.(sessionDir, fileId);
        };
      } else if (n.actionType === 'install_update') {
        label = 'Aggiorna';
        loadingLabel = 'Download in corso…';
        errorSuffix = 'usa il pulsante “Apri GitHub” per scaricare manualmente.';
        onAction = async () => {
          const version = typeof actionData?.version === 'string' ? actionData.version : '';
          await optionsRef.current.onInstallUpdate?.(version);
        };
      } else if (n.actionType === 'open_github') {
        label = 'Apri GitHub';
        onAction = async () => {
          if (optionsRef.current.onOpenUrl) {
            await optionsRef.current.onOpenUrl(GITHUB_RELEASES_URL);
          } else {
            await window.pywebview?.api?.open_url?.(GITHUB_RELEASES_URL);
          }
        };
      } else if (n.actionType === 'open_settings') {
        label = 'Apri Impostazioni';
        onAction = async () => {
          optionsRef.current.onOpenSettings?.();
        };
      } else {
        return { ...n } as NotificationMessage;
      }

      return {
        ...n,
        action: {
          label,
          type: n.actionType,
          data: n.actionData,
          loadingLabel,
          errorSuffix,
          onAction,
        },
      } as NotificationMessage;
    });
  }, []);

  const notifications = useMemo(() => {
    return bindNotificationActions(rawNotifications);
  }, [rawNotifications, bindNotificationActions]);

  const unreadNotificationsCount = useMemo(() => notifications.filter(n => !n.read).length, [notifications]);
  const [shakeBell, setShakeBell] = useState(false);
  const prevUnreadCountRef = useRef(unreadNotificationsCount);

  useEffect(() => {
    if (unreadNotificationsCount > prevUnreadCountRef.current) {
      setShakeBell(true);
      const timer = setTimeout(() => setShakeBell(false), 500);
      return () => clearTimeout(timer);
    }
    prevUnreadCountRef.current = unreadNotificationsCount;
  }, [unreadNotificationsCount]);

  return {
    rawNotifications,
    setRawNotifications,
    notifications,
    unreadNotificationsCount,
    shakeBell,
    addNotification,
    upsertNotification,
    deleteNotification,
    markNotificationAsRead,
    markAllNotificationsAsRead,
    clearAllNotifications,
    removeNotificationByDedupeKey,
  };
}
