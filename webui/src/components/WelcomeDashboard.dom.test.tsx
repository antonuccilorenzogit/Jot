import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ArchiveSession } from '../bridge';
import { WelcomeDashboard } from './WelcomeDashboard';

function makeSession(overrides: Partial<ArchiveSession> = {}): ArchiveSession {
  return {
    name: 'lezione.mp3',
    completed_at_iso: new Date().toISOString(),
    html_path: '/path/to/lezione.html',
    effective_model: 'gemini-1.5-flash-latest',
    input_path: '/path/to/lezione.mp3',
    session_dir: '/sessions/abc',
    duration_sec: 3600,
    ...overrides,
  };
}

describe('WelcomeDashboard', () => {
  it('shows first-time welcome message when there are no sessions', () => {
    render(<WelcomeDashboard archiveSessions={[]} />);
    expect(screen.getByText(/Benvenuto in jot/)).toBeTruthy();
    expect(screen.getByText(/prima sbobinatura/)).toBeTruthy();
  });

  it('does not render stat cards when there are no sessions', () => {
    render(<WelcomeDashboard archiveSessions={[]} />);
    expect(screen.queryByText('Sbobine completate')).toBeNull();
    expect(screen.queryByText('Audio elaborato')).toBeNull();
    expect(screen.queryByText('Ultima sbobina')).toBeNull();
  });

  it('shows returning welcome message when sessions exist', () => {
    render(<WelcomeDashboard archiveSessions={[makeSession()]} />);
    expect(screen.getByText(/Bentornato/)).toBeTruthy();
  });

  it('renders all 3 stat card labels when sessions exist', () => {
    render(<WelcomeDashboard archiveSessions={[makeSession()]} />);
    expect(screen.getByText('Sbobine completate')).toBeTruthy();
    expect(screen.getByText('Audio elaborato')).toBeTruthy();
    expect(screen.getByText('Ultima sbobina')).toBeTruthy();
  });

  it('shows correct total session count', () => {
    const sessions = [makeSession({ session_dir: '/s/1' }), makeSession({ session_dir: '/s/2' })];
    render(<WelcomeDashboard archiveSessions={sessions} />);
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1);
  });

  it('formats duration in hours and minutes for >= 1 hour', () => {
    render(<WelcomeDashboard archiveSessions={[makeSession({ duration_sec: 5580 })]} />);
    expect(screen.getByText('1h 33m')).toBeTruthy();
  });

  it('formats duration in minutes only for < 1 hour', () => {
    render(<WelcomeDashboard archiveSessions={[makeSession({ duration_sec: 2700 })]} />);
    expect(screen.getByText('45m')).toBeTruthy();
  });

  it('shows "< 1m" for very short or zero duration', () => {
    render(<WelcomeDashboard archiveSessions={[makeSession({ duration_sec: 0 })]} />);
    expect(screen.getByText('< 1m')).toBeTruthy();
  });

  it('sums duration_sec across all sessions', () => {
    const sessions = [
      makeSession({ session_dir: '/s/1', duration_sec: 3600 }),
      makeSession({ session_dir: '/s/2', duration_sec: 1800 }),
    ];
    render(<WelcomeDashboard archiveSessions={sessions} />);
    expect(screen.getByText('1h 30m')).toBeTruthy();
  });

  it('handles missing duration_sec gracefully (treats as 0)', () => {
    const session = makeSession({ duration_sec: undefined });
    render(<WelcomeDashboard archiveSessions={[session]} />);
    expect(screen.getByText('< 1m')).toBeTruthy();
  });

  it('shows "Oggi" for ultima sbobina when most recent session is today', () => {
    const today = new Date().toISOString();
    render(<WelcomeDashboard archiveSessions={[makeSession({ completed_at_iso: today })]} />);
    expect(screen.getByText('Oggi')).toBeTruthy();
  });

  it('shows "Ieri" for ultima sbobina when most recent session was yesterday', () => {
    const yesterday = new Date(Date.now() - 86400000).toISOString();
    render(<WelcomeDashboard archiveSessions={[makeSession({ completed_at_iso: yesterday })]} />);
    expect(screen.getByText('Ieri')).toBeTruthy();
  });

  it('shows "X giorni fa" for ultima sbobina when most recent session was 3 days ago', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 86400000).toISOString();
    render(<WelcomeDashboard archiveSessions={[makeSession({ completed_at_iso: threeDaysAgo })]} />);
    expect(screen.getByText('3 giorni fa')).toBeTruthy();
  });

  it('picks the most recent session for ultima sbobina when multiple sessions exist', () => {
    const today = new Date().toISOString();
    const threeDaysAgo = new Date(Date.now() - 3 * 86400000).toISOString();
    const sessions = [
      makeSession({ session_dir: '/s/1', completed_at_iso: threeDaysAgo }),
      makeSession({ session_dir: '/s/2', completed_at_iso: today }),
    ];
    render(<WelcomeDashboard archiveSessions={sessions} />);
    expect(screen.getByText('Oggi')).toBeTruthy();
  });
});
