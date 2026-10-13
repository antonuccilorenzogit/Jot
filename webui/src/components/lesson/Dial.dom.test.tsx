import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QuotaDial } from './Dial';
import { NavSidebar } from '../NavSidebar';
import type { QuotaSnapshot } from '../../bridge';

describe('requests of today', () => {
  it('the dial shows used over available and what is left', () => {
    render(<QuotaDial used={36} limit={240} remaining={204} />);
    expect(screen.getByText('Richieste · restano 204')).toBeTruthy();
    expect(screen.getByRole('img', { name: '36 richieste usate su 240 oggi' })).toBeTruthy();
  });

  it('the top bar always shows the box, with the detail per model', () => {
    const quota: QuotaSnapshot = {
      used: 36, limit: 240, remaining: 204, exhausted: false, has_reserve: false, reset_at: '2026-10-14T07:00:00Z', keys: 4,
      per_model: [
        { model: 'gemini-3.8-flash', used: 30, limit: 80, remaining: 50 },
        { model: 'gemini-3.7-flash', used: 6, limit: 80, remaining: 74 },
      ],
    };
    render(
      <NavSidebar
        activePage="queue" setActivePage={vi.fn()} apiReady bridgeDelayed={false} hasApiKey isApiKeyValid appState="idle"
        themeMode="dark" setThemeMode={vi.fn()} showConsole={false} setShowConsole={vi.fn()} setIsSettingsOpen={vi.fn()}
        hasPendingUpdate={false} consoleDisabled={false} unreadNotificationsCount={0} isNotificationsOpen={false}
        setIsNotificationsOpen={vi.fn()} shakeBell={false} quota={quota}
      />,
    );
    const box = screen.getByLabelText('Richieste di oggi: 36 usate su 240, ne restano 204');
    expect(box.textContent).toContain('36/240');
    expect(box.textContent).toContain('restano 204');
    expect(box.getAttribute('title')).toContain('3.8 Flash: ne restano 50 su 80');
    expect(box.getAttribute('title')).toContain('Contano anche le richieste fallite');
  });
});
