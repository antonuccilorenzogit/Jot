import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { UpdaterSection } from './UpdaterSection';

describe('UpdaterSection component', () => {
  const defaultProps = {
    latestVersion: null,
    checkForUpdates: vi.fn(),
    isCheckingUpdate: false,
    hasChecked: false,
    checkFailed: false,
    updateInstallState: null,
    onInstallUpdate: vi.fn(),
  };

  it('renders installed application version', () => {
    render(<UpdaterSection {...defaultProps} />);
    expect(screen.getByText('Versione applicazione')).toBeTruthy();
    expect(screen.getByText(/Installata:/)).toBeTruthy();
  });

  it('triggers checkForUpdates when check button is clicked', () => {
    const checkForUpdates = vi.fn();
    render(<UpdaterSection {...defaultProps} checkForUpdates={checkForUpdates} />);

    const checkBtn = screen.getByRole('button', { name: 'Cerca aggiornamenti' });
    expect(checkBtn).toBeTruthy();
    expect(screen.getByText('Cerca aggiornamenti')).toBeTruthy();
    fireEvent.click(checkBtn);
    expect(checkForUpdates).toHaveBeenCalledWith(true);
  });

  it('renders update available banner with clean styling', () => {
    const onInstall = vi.fn();
    const { container } = render(
      <UpdaterSection
        {...defaultProps}
        latestVersion="v2.5.1"
        onInstallUpdate={onInstall}
      />,
    );

    // Verify title and version badge
    expect(screen.getByText('Nuova versione disponibile')).toBeTruthy();
    const badge = screen.getByText('v2.5.1');
    expect(badge).toBeTruthy();
    expect(badge.className).toContain('rounded-full');

    // Verify card styling
    const card = container.querySelector('.bg-\\[var\\(--accent-subtle\\)\\]');
    expect(card).toBeTruthy();
    expect(card?.className).toContain('rounded-lg');

    // Verify release notes link
    expect(screen.getByText('Note di rilascio su GitHub')).toBeTruthy();

    // Verify update button and trigger
    const updateBtn = screen.getByRole('button', { name: 'Installa aggiornamento' });
    expect(updateBtn).toBeTruthy();
    fireEvent.click(updateBtn);
    expect(onInstall).toHaveBeenCalledWith('v2.5.1');
  });

  it('renders download progress state', () => {
    render(
      <UpdaterSection
        {...defaultProps}
        latestVersion="v2.5.1"
        updateInstallState={{
          version: '2.5.1',
          status: 'downloading',
          bytesDone: 5242880,
          bytesTotal: 10485760,
          percent: 50,
          error: null,
        }}
      />,
    );

    expect(screen.getByText('Download aggiornamento…')).toBeTruthy();
    expect(screen.getByText(/50%/)).toBeTruthy();
  });

  it('renders error notice when checkFailed is true', () => {
    render(
      <UpdaterSection
        {...defaultProps}
        hasChecked={true}
        checkFailed={true}
      />,
    );

    expect(screen.getByText('Verifica aggiornamenti non riuscita.')).toBeTruthy();
  });

  it('renders up to date notice when checked with no update', () => {
    render(
      <UpdaterSection
        {...defaultProps}
        hasChecked={true}
        latestVersion={null}
      />,
    );

    expect(screen.getByText('Sei aggiornato alla versione più recente.')).toBeTruthy();
  });
});
