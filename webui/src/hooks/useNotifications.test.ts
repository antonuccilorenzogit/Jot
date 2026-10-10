// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { APP_VERSION, GITHUB_RELEASES_URL } from '../branding';
import { STORAGE_KEYS } from '../storageKeys';
import {
  NOTIFICATIONS_STORAGE_KEY,
  sanitizePersistedNotifications,
  useNotifications,
  type PersistedNotification,
} from './useNotifications';

describe('useNotifications', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    localStorage.clear();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe('Persistence & Initial Load', () => {
    it('initializes with an empty array when localStorage is empty', () => {
      const { result } = renderHook(() => useNotifications());
      expect(result.current.rawNotifications).toEqual([]);
      expect(result.current.notifications).toEqual([]);
      expect(result.current.unreadNotificationsCount).toBe(0);
    });

    it('loads existing notifications from localStorage on init', () => {
      const existing: PersistedNotification[] = [
        {
          id: 'notif-1',
          title: 'Titolo 1',
          message: 'Messaggio 1',
          type: 'info',
          category: 'system',
          timestamp: 1000,
          read: false,
        },
        {
          id: 'notif-2',
          title: 'Titolo 2',
          message: 'Messaggio 2',
          type: 'warning',
          category: 'processing',
          timestamp: 2000,
          read: true,
        },
      ];
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(existing));

      const { result } = renderHook(() => useNotifications());
      expect(result.current.rawNotifications).toHaveLength(2);
      expect(result.current.rawNotifications[0].id).toBe('notif-1');
      expect(result.current.unreadNotificationsCount).toBe(1);
    });

    it('sanitizes legacy notifications containing regenerate_prompt_timeout on load', () => {
      const legacy: PersistedNotification[] = [
        {
          id: 'old-1',
          title: 'Errore elaborazione',
          message: 'Errore per "Istologia lezione 9 parte 1.m4a": regenerate_prompt_timeout',
          type: 'error',
          category: 'processing',
          timestamp: 1000,
          read: false,
        },
      ];
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(legacy));

      const { result } = renderHook(() => useNotifications());
      expect(result.current.rawNotifications).toHaveLength(1);
      expect(result.current.rawNotifications[0].title).toBe('Elaborazione in pausa');
      expect(result.current.rawNotifications[0].type).toBe('warning');
      expect(result.current.rawNotifications[0].message).toContain('Nessuna scelta ricevuta');
    });

    it('removes stale in-progress update-install notifications on bootstrap', () => {
      const stale: PersistedNotification[] = [
        {
          id: 'install-1',
          title: 'Installazione aggiornamento',
          message: 'Installazione aggiornamento…',
          type: 'info',
          category: 'update',
          timestamp: Date.now() - 10_000,
          read: false,
          persistent: true,
          dedupeKey: 'update-install',
        },
      ];
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(stale));

      const { result } = renderHook(() => useNotifications());
      const hasInstallNotif = result.current.rawNotifications.some(n => n.dedupeKey === 'update-install');
      expect(hasInstallNotif).toBe(false);
    });

    it('removes stale update-available notifications when target version <= current APP_VERSION', () => {
      const stale: PersistedNotification[] = [
        {
          id: 'avail-1',
          title: 'Aggiornamento disponibile',
          message: `Nuova versione disponibile: ${APP_VERSION}`,
          type: 'info',
          category: 'update',
          timestamp: Date.now() - 60_000,
          read: false,
          persistent: true,
          dedupeKey: 'update-available',
          actionType: 'install_update',
          actionData: { version: APP_VERSION },
        },
      ];
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(stale));

      const { result } = renderHook(() => useNotifications());
      const hasAvailNotif = result.current.rawNotifications.some(n => n.dedupeKey === 'update-available');
      expect(hasAvailNotif).toBe(false);
    });

    it('retains update-available notification when target version is strictly greater than current APP_VERSION', () => {
      const futureVersion = 'v999.0.0';
      const future: PersistedNotification[] = [
        {
          id: 'avail-future',
          title: 'Aggiornamento disponibile',
          message: `Nuova versione disponibile: ${futureVersion}`,
          type: 'info',
          category: 'update',
          timestamp: Date.now() - 10_000,
          read: false,
          persistent: true,
          dedupeKey: 'update-available',
          actionType: 'install_update',
          actionData: { version: futureVersion },
        },
      ];
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(future));
      localStorage.setItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1, APP_VERSION);

      const { result } = renderHook(() => useNotifications());
      const hasAvailNotif = result.current.rawNotifications.some(n => n.dedupeKey === 'update-available');
      expect(hasAvailNotif).toBe(true);
    });

    it('adds Aggiornamento completato notification when transitioning from a prior version', () => {
      localStorage.setItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1, 'v2.5.1');
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify([]));

      const { result } = renderHook(() => useNotifications({ currentAppVersion: 'v2.6.0' }));
      const successNotif = result.current.rawNotifications.find(n => n.dedupeKey === 'update-success:v2.6.0');
      expect(successNotif).toBeDefined();
      expect(successNotif?.title).toBe('Aggiornamento completato');
      expect(successNotif?.message).toContain('v2.6.0');
      expect(successNotif?.type).toBe('success');
      expect(localStorage.getItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1)).toBe('v2.6.0');
    });

    it('does not consume the prior version when render aborts before effects commit', () => {
      localStorage.setItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1, 'v2.5.1');
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify([]));
      vi.spyOn(console, 'error').mockImplementation(() => {});

      expect(() =>
        renderHook(() => {
          useNotifications({ currentAppVersion: 'v2.6.0' });
          throw new Error('abort before commit');
        })
      ).toThrow('abort before commit');

      expect(localStorage.getItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1)).toBe('v2.5.1');
    });

    it('adds Aggiornamento completato notification when prior storage had pending update for current APP_VERSION', () => {
      const priorState: PersistedNotification[] = [
        {
          id: 'install-1',
          title: 'Installazione aggiornamento',
          message: 'Installazione aggiornamento…',
          type: 'info',
          category: 'update',
          timestamp: Date.now() - 5000,
          read: false,
          persistent: true,
          dedupeKey: 'update-install',
        },
        {
          id: 'avail-1',
          title: 'Aggiornamento disponibile',
          message: `Nuova versione disponibile: ${APP_VERSION}`,
          type: 'info',
          category: 'update',
          timestamp: Date.now() - 10000,
          read: false,
          persistent: true,
          dedupeKey: 'update-available',
          actionType: 'install_update',
          actionData: { version: APP_VERSION },
        },
      ];
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(priorState));

      const { result } = renderHook(() => useNotifications());
      // Stale ones are gone
      expect(result.current.rawNotifications.some(n => n.dedupeKey === 'update-install')).toBe(false);
      expect(result.current.rawNotifications.some(n => n.dedupeKey === 'update-available')).toBe(false);
      // Success is present
      const successNotif = result.current.rawNotifications.find(n => n.dedupeKey === `update-success:${APP_VERSION}`);
      expect(successNotif).toBeDefined();
      expect(successNotif?.title).toBe('Aggiornamento completato');
      expect(localStorage.getItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1)).toBe(APP_VERSION);
    });

    it('does not add duplicate Aggiornamento completato notification on subsequent loads', () => {
      localStorage.setItem(STORAGE_KEYS.LAST_SEEN_APP_VERSION_V1, APP_VERSION);
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify([]));

      const { result } = renderHook(() => useNotifications());
      const successNotifs = result.current.rawNotifications.filter(n => n.dedupeKey === `update-success:${APP_VERSION}`);
      expect(successNotifs).toHaveLength(0);
    });

    it('gracefully handles corrupt JSON in localStorage', () => {
      localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, '{invalid json');
      const { result } = renderHook(() => useNotifications());
      expect(result.current.rawNotifications).toEqual([]);
      expect(result.current.notifications).toEqual([]);
    });

    it('persists notifications to localStorage when added and updated', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('Test', 'Messaggio di prova', 'info', 'system');
      });

      const stored = JSON.parse(localStorage.getItem(NOTIFICATIONS_STORAGE_KEY) || '[]');
      expect(stored).toHaveLength(1);
      expect(stored[0].title).toBe('Test');
      expect(stored[0].message).toBe('Messaggio di prova');
      expect(stored[0].read).toBe(false);
    });
  });

  describe('addNotification & Deduplication', () => {
    it('adds a notification with default type and category', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('Nuova notifica', 'Dettagli');
      });

      expect(result.current.rawNotifications).toHaveLength(1);
      const notif = result.current.rawNotifications[0];
      expect(notif.title).toBe('Nuova notifica');
      expect(notif.message).toBe('Dettagli');
      expect(notif.type).toBe('info');
      expect(notif.category).toBe('system');
      expect(notif.read).toBe(false);
      expect(typeof notif.id).toBe('string');
      expect(typeof notif.timestamp).toBe('number');
    });

    it('adds a notification with custom options and actionData', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('Errore', 'Errore grave', 'error', 'processing', {
          persistent: true,
          dedupeKey: 'custom-error',
          actionType: 'retry_failed_revision_blocks',
          actionData: { sessionDir: '/sessions/1', fileId: 'file-1' },
        });
      });

      expect(result.current.rawNotifications).toHaveLength(1);
      const notif = result.current.rawNotifications[0];
      expect(notif.type).toBe('error');
      expect(notif.category).toBe('processing');
      expect(notif.persistent).toBe(true);
      expect(notif.dedupeKey).toBe('custom-error');
      expect(notif.actionType).toBe('retry_failed_revision_blocks');
      expect(notif.actionData).toEqual({ sessionDir: '/sessions/1', fileId: 'file-1' });
    });

    it('ignores duplicate notification if dedupeKey already exists', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('Primo', 'Msg 1', 'warning', 'system', { dedupeKey: 'dup-1' });
      });
      act(() => {
        result.current.addNotification('Secondo', 'Msg 2', 'warning', 'system', { dedupeKey: 'dup-1' });
      });

      expect(result.current.rawNotifications).toHaveLength(1);
      expect(result.current.rawNotifications[0].title).toBe('Primo');
    });

    it('caps notifications at 50 entries', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        for (let i = 0; i < 60; i++) {
          result.current.addNotification(`Notifica ${i}`, `Messaggio ${i}`);
        }
      });

      expect(result.current.rawNotifications).toHaveLength(50);
      expect(result.current.rawNotifications[0].title).toBe('Notifica 59');
    });
  });

  describe('upsertNotification', () => {
    it('creates a new notification if dedupeKey does not exist and returns new ID', () => {
      const { result } = renderHook(() => useNotifications());

      let createdId = '';
      act(() => {
        createdId = result.current.upsertNotification('Download', 'Inizio download', 'info', 'update', {
          dedupeKey: 'update-dl',
        });
      });

      expect(createdId).toBeTruthy();
      expect(result.current.rawNotifications).toHaveLength(1);
      expect(result.current.rawNotifications[0].id).toBe(createdId);
      expect(result.current.rawNotifications[0].message).toBe('Inizio download');
    });

    it('updates an existing notification in-place when matching dedupeKey and returns the same ID', () => {
      const { result } = renderHook(() => useNotifications());

      let firstId = '';
      act(() => {
        firstId = result.current.upsertNotification('Download', '50%', 'info', 'update', {
          dedupeKey: 'update-dl',
        });
      });

      let secondId = '';
      act(() => {
        secondId = result.current.upsertNotification('Download', '100%', 'success', 'update', {
          dedupeKey: 'update-dl',
        });
      });

      expect(secondId).toBe(firstId);
      expect(result.current.rawNotifications).toHaveLength(1);
      expect(result.current.rawNotifications[0].id).toBe(firstId);
      expect(result.current.rawNotifications[0].message).toBe('100%');
      expect(result.current.rawNotifications[0].type).toBe('success');
    });
  });

  describe('deleteNotification & Special Dismissal Triggers', () => {
    it('removes the notification by id', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('Notifica 1', 'Msg 1');
        result.current.addNotification('Notifica 2', 'Msg 2');
      });

      const idToDelete = result.current.rawNotifications[0].id;
      act(() => {
        result.current.deleteNotification(idToDelete);
      });

      expect(result.current.rawNotifications).toHaveLength(1);
      expect(result.current.rawNotifications[0].id).not.toBe(idToDelete);
    });

    it('sets config-recovery dismissal localStorage flag on delete', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('Config', 'Ripristinata', 'warning', 'system', {
          dedupeKey: 'config-recovery:C:/test/path/config.json',
        });
      });

      const notifId = result.current.rawNotifications[0].id;
      act(() => {
        result.current.deleteNotification(notifId);
      });

      expect(localStorage.getItem('jot.config-recovery-dismissed.v1:C:/test/path/config.json')).toBe('1');
    });

    it('calls onDismissUpdate when deleting update-available notification', () => {
      const onDismissUpdate = vi.fn();
      const { result } = renderHook(() => useNotifications({ onDismissUpdate }));

      act(() => {
        result.current.addNotification('Aggiornamento', 'Nuova versione', 'info', 'update', {
          dedupeKey: 'update-available',
          actionData: { version: 'v2.5.0' },
        });
      });

      const notifId = result.current.rawNotifications[0].id;
      act(() => {
        result.current.deleteNotification(notifId);
      });

      expect(onDismissUpdate).toHaveBeenCalledWith('v2.5.0');
    });
  });

  describe('clearAllNotifications', () => {
    it('clears all notifications and runs dismissal side effects for all items', () => {
      const onDismissUpdate = vi.fn();
      const { result } = renderHook(() => useNotifications({ onDismissUpdate }));

      act(() => {
        result.current.addNotification('Normal', 'Msg');
        result.current.addNotification('Config', 'Msg', 'warning', 'system', {
          dedupeKey: 'config-recovery:C:/path/config.json',
        });
        result.current.addNotification('Update', 'Msg', 'info', 'update', {
          dedupeKey: 'update-available',
          actionData: { version: 'v3.0.0' },
        });
      });

      expect(result.current.rawNotifications).toHaveLength(3);

      act(() => {
        result.current.clearAllNotifications();
      });

      expect(result.current.rawNotifications).toHaveLength(0);
      expect(result.current.unreadNotificationsCount).toBe(0);
      expect(localStorage.getItem('jot.config-recovery-dismissed.v1:C:/path/config.json')).toBe('1');
      expect(onDismissUpdate).toHaveBeenCalledWith('v3.0.0');
    });
  });

  describe('removeNotificationByDedupeKey', () => {
    it('removes only notifications matching the specified dedupeKey', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('N1', 'M1', 'info', 'system', { dedupeKey: 'k1' });
        result.current.addNotification('N2', 'M2', 'info', 'system', { dedupeKey: 'k2' });
      });

      act(() => {
        result.current.removeNotificationByDedupeKey('k1');
      });

      expect(result.current.rawNotifications).toHaveLength(1);
      expect(result.current.rawNotifications[0].dedupeKey).toBe('k2');
    });
  });

  describe('Read Status & Unread Count & shakeBell', () => {
    it('markNotificationAsRead marks an item as read', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('N1', 'M1');
      });

      expect(result.current.unreadNotificationsCount).toBe(1);
      const id = result.current.rawNotifications[0].id;

      act(() => {
        result.current.markNotificationAsRead(id);
      });

      expect(result.current.rawNotifications[0].read).toBe(true);
      expect(result.current.unreadNotificationsCount).toBe(0);
    });

    it('markAllNotificationsAsRead marks all items as read', () => {
      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('N1', 'M1');
        result.current.addNotification('N2', 'M2');
      });

      expect(result.current.unreadNotificationsCount).toBe(2);

      act(() => {
        result.current.markAllNotificationsAsRead();
      });

      expect(result.current.rawNotifications.every(n => n.read)).toBe(true);
      expect(result.current.unreadNotificationsCount).toBe(0);
    });

    it('triggers shakeBell when unread notifications count increases', () => {
      const { result } = renderHook(() => useNotifications());

      expect(result.current.shakeBell).toBe(false);

      act(() => {
        result.current.addNotification('N1', 'M1');
      });

      expect(result.current.shakeBell).toBe(true);

      act(() => {
        vi.advanceTimersByTime(500);
      });

      expect(result.current.shakeBell).toBe(false);
    });
  });

  describe('Action Binding', () => {
    it('binds retry_failed_revision_blocks action and executes callback', async () => {
      const onRetryFailedRevisionBlocks = vi.fn().mockResolvedValue(undefined);
      const { result } = renderHook(() => useNotifications({ onRetryFailedRevisionBlocks }));

      act(() => {
        result.current.addNotification('Retry', 'Blocchi falliti', 'warning', 'processing', {
          actionType: 'retry_failed_revision_blocks',
          actionData: { sessionDir: '/path/to/session', fileId: 'file-123' },
        });
      });

      const notification = result.current.notifications[0];
      expect(notification.action).toBeDefined();
      expect(notification.action?.label).toBe('Riprova');
      expect(notification.action?.loadingLabel).toBe('Riprovo...');
      expect(notification.action?.errorSuffix).toBe('puoi usare il pulsante sulla scheda');

      await act(async () => {
        await notification.action?.onAction();
      });

      expect(onRetryFailedRevisionBlocks).toHaveBeenCalledWith('/path/to/session', 'file-123');
    });

    it('binds install_update action and executes callback', async () => {
      const onInstallUpdate = vi.fn().mockResolvedValue(undefined);
      const { result } = renderHook(() => useNotifications({ onInstallUpdate }));

      act(() => {
        result.current.addNotification('Update', 'Nuova versione', 'info', 'update', {
          actionType: 'install_update',
          actionData: { version: 'v2.1.0' },
        });
      });

      const notification = result.current.notifications[0];
      expect(notification.action).toBeDefined();
      expect(notification.action?.label).toBe('Aggiorna');
      expect(notification.action?.loadingLabel).toBe('Download in corso…');
      expect(notification.action?.errorSuffix).toBe('usa il pulsante “Apri GitHub” per scaricare manualmente.');

      await act(async () => {
        await notification.action?.onAction();
      });

      expect(onInstallUpdate).toHaveBeenCalledWith('v2.1.0');
    });

    it('binds open_github action and executes custom onOpenUrl callback', async () => {
      const onOpenUrl = vi.fn().mockResolvedValue(undefined);
      const { result } = renderHook(() => useNotifications({ onOpenUrl }));

      act(() => {
        result.current.addNotification('GitHub', 'Vedi repository', 'info', 'system', {
          actionType: 'open_github',
        });
      });

      const notification = result.current.notifications[0];
      expect(notification.action).toBeDefined();
      expect(notification.action?.label).toBe('Apri GitHub');

      await act(async () => {
        await notification.action?.onAction();
      });

      expect(onOpenUrl).toHaveBeenCalledWith(GITHUB_RELEASES_URL);
    });

    it('binds open_github action and falls back to window.pywebview.api.open_url', async () => {
      const pywebviewOpenUrl = vi.fn().mockResolvedValue({ ok: true });
      Object.defineProperty(window, 'pywebview', {
        value: { api: { open_url: pywebviewOpenUrl } },
        writable: true,
        configurable: true,
      });

      const { result } = renderHook(() => useNotifications());

      act(() => {
        result.current.addNotification('GitHub', 'Vedi repository', 'info', 'system', {
          actionType: 'open_github',
        });
      });

      const notification = result.current.notifications[0];
      await act(async () => {
        await notification.action?.onAction();
      });

      expect(pywebviewOpenUrl).toHaveBeenCalledWith(GITHUB_RELEASES_URL);
    });
  });
});

describe('sanitizePersistedNotifications', () => {
  it('returns empty array when input is not an array', () => {
    expect(sanitizePersistedNotifications(null)).toEqual([]);
    expect(sanitizePersistedNotifications('string')).toEqual([]);
    expect(sanitizePersistedNotifications({})).toEqual([]);
  });

  it('filters out stale update-install notifications', () => {
    const list = [
      { id: '1', dedupeKey: 'update-install', title: 'Install', message: 'test', type: 'info', category: 'update', timestamp: 1, read: false },
      { id: '2', title: 'Regular', message: 'hello', type: 'info', category: 'system', timestamp: 2, read: false },
    ];
    const res = sanitizePersistedNotifications(list, 'v2.6.0');
    expect(res).toHaveLength(1);
    expect(res[0].id).toBe('2');
  });

  it('filters out update-available notifications when targetVersion <= currentAppVersion', () => {
    const list = [
      { id: '1', dedupeKey: 'update-available', title: 'Update', message: 'v2.6.0', type: 'info', category: 'update', timestamp: 1, read: false, actionData: { version: 'v2.6.0' } },
      { id: '2', dedupeKey: 'update-available', title: 'Update', message: 'v2.7.0', type: 'info', category: 'update', timestamp: 2, read: false, actionData: { version: 'v2.7.0' } },
    ];
    const res = sanitizePersistedNotifications(list, 'v2.6.0');
    expect(res).toHaveLength(1);
    expect(res[0].id).toBe('2');
  });
});
