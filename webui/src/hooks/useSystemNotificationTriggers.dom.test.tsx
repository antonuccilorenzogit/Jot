import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSystemNotificationTriggers } from './useSystemNotificationTriggers';

describe('useSystemNotificationTriggers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('triggers notification when config was recovered from backup', () => {
    const addNotification = vi.fn();
    const removeNotificationByDedupeKey = vi.fn();

    renderHook(() =>
      useSystemNotificationTriggers({
        configRecoveredFrom: 'C:/Users/User/.jot/config.json.corrupt',
        updateAvailable: null,
        addNotification,
        removeNotificationByDedupeKey,
      }),
    );

    expect(addNotification).toHaveBeenCalledWith(
      'Configurazione ripristinata',
      expect.stringContaining('Il file di configurazione era corrotto'),
      'warning',
      'system',
      expect.objectContaining({
        persistent: true,
      }),
    );
  });

  it('triggers notification when update is available', () => {
    const addNotification = vi.fn();
    const removeNotificationByDedupeKey = vi.fn();

    renderHook(() =>
      useSystemNotificationTriggers({
        configRecoveredFrom: '',
        updateAvailable: 'v2.1.0',
        addNotification,
        removeNotificationByDedupeKey,
      }),
    );

    expect(addNotification).toHaveBeenCalledWith(
      'Aggiornamento disponibile',
      'Nuova versione disponibile: v2.1.0',
      'info',
      'update',
      expect.objectContaining({
        persistent: true,
        dedupeKey: 'update-available',
        actionType: 'install_update',
      }),
    );
  });

  it('removes update-available notification when updateAvailable transitions to null', () => {
    const addNotification = vi.fn();
    const removeNotificationByDedupeKey = vi.fn();

    const { rerender } = renderHook(
      ({ updateAvailable }: { updateAvailable: string | null }) =>
        useSystemNotificationTriggers({
          configRecoveredFrom: '',
          updateAvailable,
          addNotification,
          removeNotificationByDedupeKey,
        }),
      {
        initialProps: { updateAvailable: 'v2.1.0' as string | null },
      },
    );

    expect(addNotification).toHaveBeenCalledTimes(1);
    expect(removeNotificationByDedupeKey).not.toHaveBeenCalled();

    // Now simulate update dismissal or no longer available
    rerender({ updateAvailable: null });

    expect(removeNotificationByDedupeKey).toHaveBeenCalledWith('update-available');
  });
});
