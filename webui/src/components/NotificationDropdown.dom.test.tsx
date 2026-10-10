import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { NotificationDropdown, type NotificationMessage } from './NotificationDropdown';

describe('NotificationDropdown component', () => {
  const mockNotifications: NotificationMessage[] = [
    {
      id: 'notif-1',
      title: 'Sbobina completata',
      message: 'Lezione di Istologia elaborata con successo.',
      type: 'success',
      category: 'processing',
      timestamp: Date.now() - 5 * 60_000,
      read: false,
    },
    {
      id: 'notif-2',
      title: 'Aggiornamento disponibile',
      message: 'Nuova versione v1.4 pronta per il download.',
      type: 'info',
      category: 'update',
      timestamp: Date.now() - 60 * 60_000,
      read: true,
      action: {
        label: 'Aggiorna ora',
        type: 'install_update',
        onAction: vi.fn().mockResolvedValue(undefined),
      },
    },
    {
      id: 'notif-3',
      title: 'Errore di connessione',
      message: 'Impossibile contattare le API di Gemini.',
      type: 'error',
      category: 'system',
      timestamp: Date.now() - 2 * 3600_000,
      read: false,
    },
  ];

  it('is hidden with pointer-events-none when closed', () => {
    render(
      <NotificationDropdown
        isOpen={false}
        onClose={vi.fn()}
        notifications={mockNotifications}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    const titleEl = screen.getByText('Notifiche');
    const container = titleEl.closest('.origin-bottom-left');
    expect(container?.className).toContain('pointer-events-none');
  });

  it('renders notifications, unread badge, and handles tab switching', async () => {
    const handleMarkAsRead = vi.fn();
    const handleNotificationClick = vi.fn();

    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        notifications={mockNotifications}
        onMarkAsRead={handleMarkAsRead}
        onMarkAllAsRead={vi.fn()}
        onDelete={vi.fn()}
        onNotificationClick={handleNotificationClick}
      />
    );

    // Title and unread count badge (2 unread)
    expect(screen.getByText('Notifiche')).toBeTruthy();
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1);

    // Both all and unread notifications appear initially in 'all' tab
    expect(screen.getByText('Sbobina completata')).toBeTruthy();
    expect(screen.getByText('Aggiornamento disponibile')).toBeTruthy();
    expect(screen.getByText('Errore di connessione')).toBeTruthy();

    // Click on unread notification item triggers mark as read and click callback
    fireEvent.click(screen.getByText('Sbobina completata'));
    expect(handleMarkAsRead).toHaveBeenCalledWith('notif-1');
    expect(handleNotificationClick).toHaveBeenCalledWith(mockNotifications[0]);

    // Switch to "Non lette" tab
    fireEvent.click(screen.getByRole('button', { name: /Non lette/i }));

    // Only unread notifications should be visible
    expect(screen.getByText('Sbobina completata')).toBeTruthy();
    expect(screen.getByText('Errore di connessione')).toBeTruthy();
    await waitFor(() => {
      expect(screen.queryByText('Aggiornamento disponibile')).toBeNull();
    });
  });

  it('renders update notifications with accent sparkles badge', () => {
    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        notifications={[mockNotifications[1]]}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    const updateItem = screen.getByText('Aggiornamento disponibile').closest('[data-notification-id="notif-2"]');
    expect(updateItem).toBeTruthy();
    const badge = updateItem?.querySelector('.lucide-sparkles');
    expect(badge).toBeTruthy();
  });

  it('handles "Segna come già lette" action', () => {
    const handleMarkAllAsRead = vi.fn();

    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        notifications={mockNotifications}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={handleMarkAllAsRead}
        onDelete={vi.fn()}
      />
    );

    const markAllBtn = screen.getByRole('button', { name: /Segna come già lette/i });
    fireEvent.click(markAllBtn);
    expect(handleMarkAllAsRead).toHaveBeenCalledTimes(1);
  });

  it('handles archiving / dismissing an individual notification', () => {
    const handleDelete = vi.fn();
    const onDismiss = vi.fn();
    const notifsWithDismiss: NotificationMessage[] = [
      {
        ...mockNotifications[0],
        onDismiss,
      },
    ];

    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        notifications={notifsWithDismiss}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={vi.fn()}
        onDelete={handleDelete}
      />
    );

    const archiveBtn = screen.getByLabelText('Archivia notifica');
    fireEvent.click(archiveBtn);

    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(handleDelete).toHaveBeenCalledWith('notif-1');
  });

  it('handles action button click on notification with action', async () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    const handleDelete = vi.fn();
    const onDismiss = vi.fn();
    const actionNotif: NotificationMessage[] = [
      {
        id: 'action-notif',
        title: 'Aggiornamento',
        message: 'Aggiornamento pronto.',
        type: 'info',
        category: 'update',
        timestamp: Date.now(),
        read: false,
        onDismiss,
        action: {
          label: 'Scarica ora',
          type: 'install_update',
          onAction,
        },
      },
    ];

    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        notifications={actionNotif}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={vi.fn()}
        onDelete={handleDelete}
      />
    );

    const actionBtn = screen.getByRole('button', { name: 'Scarica ora' });
    fireEvent.click(actionBtn);

    await waitFor(() => {
      expect(onAction).toHaveBeenCalledTimes(1);
      expect(onDismiss).toHaveBeenCalledTimes(1);
      expect(handleDelete).toHaveBeenCalledWith('action-notif');
    });
  });

  it('handles action button error state gracefully', async () => {
    const onAction = vi.fn().mockRejectedValue(new Error('Rete non disponibile'));
    const actionNotif: NotificationMessage[] = [
      {
        id: 'error-action-notif',
        title: 'Azione fallita',
        message: 'Tentativo di download.',
        type: 'warning',
        category: 'system',
        timestamp: Date.now(),
        read: false,
        action: {
          label: 'Esegui',
          type: 'install_update',
          errorSuffix: 'riprova più tardi',
          onAction,
        },
      },
    ];

    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        notifications={actionNotif}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    const actionBtn = screen.getByRole('button', { name: 'Esegui' });
    fireEvent.click(actionBtn);

    await waitFor(() => {
      expect(screen.getByText(/Rete non disponibile — riprova più tardi/)).toBeTruthy();
    });
  });

  it('renders clean empty state when there are no notifications', () => {
    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        notifications={[]}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getByText('Nessuna notifica')).toBeTruthy();
    expect(screen.getByText(/Qui troverai gli avvisi su elaborazioni/i)).toBeTruthy();
  });

  it('handles "Cancella tutte le notifiche" action', () => {
    const handleClearAll = vi.fn();

    render(
      <NotificationDropdown
        isOpen={true}
        onClose={vi.fn()}
        notifications={mockNotifications}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={vi.fn()}
        onDelete={vi.fn()}
        onClearAll={handleClearAll}
      />
    );

    const clearAllBtn = screen.getByRole('button', { name: /Cancella tutte le notifiche/i });
    fireEvent.click(clearAllBtn);
    expect(handleClearAll).toHaveBeenCalledTimes(1);
  });

  describe('Caret dynamic gradient and neutral color', () => {
    it('uses neutral background when no notification overlaps caret', () => {
      const { container } = render(
        <NotificationDropdown
          isOpen={true}
          onClose={vi.fn()}
          notifications={[mockNotifications[0]]}
          onMarkAsRead={vi.fn()}
          onMarkAllAsRead={vi.fn()}
          onDelete={vi.fn()}
          align="left"
          valign="bottom"
        />
      );

      const polygon = container.querySelector('svg polygon');
      expect(polygon?.getAttribute('fill')).toBe('var(--bg-elevated, #ffffff)');
    });

    it('adapts caret fill gradient when a notification overlaps the caret position', () => {
      const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
      try {
        HTMLElement.prototype.getBoundingClientRect = function () {
          const notifId = this.getAttribute('data-notification-id');
          if (notifId === 'notif-1') {
            // notif-1 (success) positioned at top [100, 200]
            return { top: 100, bottom: 200, height: 100, width: 380, left: 0, right: 380, x: 0, y: 100, toJSON: () => {} };
          }
          if (notifId === 'notif-3') {
            // notif-3 (error) positioned overlapping caret [300, 400]
            return { top: 300, bottom: 400, height: 100, width: 380, left: 0, right: 380, x: 0, y: 300, toJSON: () => {} };
          }
          if (this.classList.contains('overflow-y-auto')) {
            // scroll container
            return { top: 100, bottom: 450, height: 350, width: 380, left: 0, right: 380, x: 0, y: 100, toJSON: () => {} };
          }
          if (this.parentElement?.classList?.contains('origin-bottom-left') || this.style?.bottom === '48px') {
            // caret element
            return { top: 330, bottom: 348, height: 18, width: 9, left: 0, right: 9, x: 0, y: 330, toJSON: () => {} };
          }
          return { top: 0, bottom: 0, height: 0, width: 0, left: 0, right: 0, x: 0, y: 0, toJSON: () => {} };
        };

        const { container } = render(
          <NotificationDropdown
            isOpen={true}
            onClose={vi.fn()}
            notifications={mockNotifications}
            onMarkAsRead={vi.fn()}
            onMarkAllAsRead={vi.fn()}
            onDelete={vi.fn()}
            align="left"
            valign="bottom"
          />
        );

        const polygon = container.querySelector('svg polygon');
        expect(polygon?.getAttribute('fill')).toBe('url(#caret-grad-error)');
      } finally {
        HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect;
      }
    });
  });
});
