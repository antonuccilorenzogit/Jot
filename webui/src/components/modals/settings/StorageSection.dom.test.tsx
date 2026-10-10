import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { StorageSection } from './StorageSection';

describe('StorageSection component', () => {
  const baseProps = {
    sessionInfo: { total_bytes: 1048576, total_sessions: 3, session_root: '/home/user/sessions' },
    isMoveInProgress: false,
    moveProgress: null,
    moveError: null,
    onOpenSessionFolder: vi.fn(),
    onAskMoveFolder: vi.fn(),
    isCleaningSession: false,
    isCleaningCompletedSessions: false,
    cleanupPreview: null,
    completedCleanupPreview: null,
    cleanupResult: null,
    completedCleanupResult: null,
    onAskCleanup: vi.fn(),
    onAskCompletedCleanup: vi.fn(),
  };

  it('renders session root path and triggers onOpenSessionFolder when clicked', () => {
    render(<StorageSection {...baseProps} />);

    // Verify session root is displayed
    expect(screen.getByText('/home/user/sessions')).toBeTruthy();

    // Verify clicking opens session folder
    fireEvent.click(screen.getByTitle('Apri cartella sessioni'));
    expect(baseProps.onOpenSessionFolder).toHaveBeenCalledTimes(1);
  });

  it('renders move progress with .alert-card.is-info', () => {
    const { container } = render(
      <StorageSection
        {...baseProps}
        isMoveInProgress={true}
        moveProgress={{ moved: 2, total: 5 }}
      />,
    );

    const alert = container.querySelector('.alert-card.is-info');
    expect(alert).toBeTruthy();
    expect(screen.getByText('Spostamento cartella in corso...')).toBeTruthy();
  });

  it('renders move error with .alert-card.is-error', () => {
    const { container } = render(
      <StorageSection
        {...baseProps}
        moveError="Permesso negato sul disco"
      />,
    );

    const alert = container.querySelector('.alert-card.is-error');
    expect(alert).toBeTruthy();
    expect(screen.getByText('Permesso negato sul disco')).toBeTruthy();
  });

  it('renders informational notice with .alert-card.is-info when cleanup removed 0 items', () => {
    const { container } = render(
      <StorageSection
        {...baseProps}
        cleanupResult={{ removed: 0, freed_bytes: 0 }}
      />,
    );

    const alert = container.querySelector('.alert-card.is-info');
    expect(alert).toBeTruthy();
    expect(screen.getByText('Nessuna elaborazione incompleta da eliminare.')).toBeTruthy();
  });

  it('renders success notice with .alert-card.is-success when cleanup removed items', () => {
    const { container } = render(
      <StorageSection
        {...baseProps}
        cleanupResult={{ removed: 2, freed_bytes: 2048 }}
      />,
    );

    const alert = container.querySelector('.alert-card.is-success');
    expect(alert).toBeTruthy();
    expect(screen.getByText(/Rimosse 2 elaborazioni incomplete/)).toBeTruthy();
  });

  it('renders close button in top right and triggers onDismissCleanupResult when clicked', () => {
    const onDismiss = vi.fn();
    render(
      <StorageSection
        {...baseProps}
        cleanupResult={{ removed: 0, freed_bytes: 0 }}
        onDismissCleanupResult={onDismiss}
      />,
    );

    const closeBtn = screen.getByRole('button', { name: 'Chiudi notifica' });
    expect(closeBtn).toBeTruthy();
    expect(closeBtn.className).toContain('absolute');
    expect(closeBtn.className).toContain('top-2.5');
    expect(closeBtn.className).toContain('right-2.5');
    expect(closeBtn.querySelector('svg')).toBeTruthy();
    fireEvent.click(closeBtn);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
