import { useEffect, useRef } from 'react';
import { type AddNotificationOptions, type NotificationCategory, type NotificationType } from './useNotifications';

export interface UseSystemNotificationTriggersOptions {
  configRecoveredFrom: string;
  updateAvailable: string | null;
  addNotification: (
    title: string,
    message: string,
    type?: NotificationType,
    category?: NotificationCategory,
    options?: AddNotificationOptions,
  ) => void;
  removeNotificationByDedupeKey: (dedupeKey: string) => void;
}

export function useSystemNotificationTriggers({
  configRecoveredFrom,
  updateAvailable,
  addNotification,
  removeNotificationByDedupeKey,
}: UseSystemNotificationTriggersOptions) {
  const configRecoveryToastPathRef = useRef<string | null>(null);
  useEffect(() => {
    const recoveredPath = configRecoveredFrom.trim();
    if (!recoveredPath) return;
    if (configRecoveryToastPathRef.current === recoveredPath) return;
    const storageKey = `jot.config-recovery-dismissed.v1:${recoveredPath}`;
    try {
      if (localStorage.getItem(storageKey) === '1') return;
    } catch (_) {}
    configRecoveryToastPathRef.current = recoveredPath;
    addNotification(
      'Configurazione ripristinata',
      'Il file di configurazione era corrotto: ho ripristinato i valori predefiniti e salvato una copia di backup del file precedente.',
      'warning',
      'system',
      {
        persistent: true,
        dedupeKey: `config-recovery:${recoveredPath}`,
      },
    );
  }, [configRecoveredFrom, addNotification]);

  const updateToastShownVersionRef = useRef<string | null>(null);
  useEffect(() => {
    if (!updateAvailable) {
      if (updateToastShownVersionRef.current !== null) {
        removeNotificationByDedupeKey('update-available');
        updateToastShownVersionRef.current = null;
      }
      return;
    }
    if (updateToastShownVersionRef.current === updateAvailable) return;
    updateToastShownVersionRef.current = updateAvailable;
    const cleanVer = updateAvailable.trim().replace(/^v+/, '');
    addNotification(
      'Aggiornamento disponibile',
      `Nuova versione disponibile: v${cleanVer}`,
      'info',
      'update',
      {
        persistent: true,
        dedupeKey: 'update-available',
        actionType: 'install_update',
        actionData: { version: updateAvailable },
      },
    );
  }, [updateAvailable, addNotification, removeNotificationByDedupeKey]);
}
