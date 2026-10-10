import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { FileItem } from '../../appState';
import type { ArchiveSession } from '../../bridge';
import { DuplicateFileModal } from './DuplicateFileModal';

function makeFile(overrides: Partial<FileItem> = {}): FileItem {
  return {
    id: 'incoming-1',
    name: 'lesson.mp3',
    size: 1024,
    duration: 60,
    status: 'queued',
    progress: 0,
    phase: 0,
    ...overrides,
  };
}

function makeArchiveSession(overrides: Partial<ArchiveSession> = {}): ArchiveSession {
  return {
    name: 'lesson',
    completed_at_iso: '2026-04-14T12:00:00Z',
    html_path: '/archive/lesson.html',
    effective_model: 'gemini',
    input_path: '/archive/lesson.mp3',
    session_dir: '/sessions/one',
    ...overrides,
  };
}

describe('DuplicateFileModal', () => {
  it('mentions multiple previous sessions for a single archived duplicate', () => {
    render(
      <DuplicateFileModal
        prompt={{
          kind: 'already-processed',
          matches: [{
            source: 'archive',
            incoming: makeFile(),
            sessions: [
              makeArchiveSession({ session_dir: '/sessions/one' }),
              makeArchiveSession({ session_dir: '/sessions/two' }),
            ],
          }],
        }}
        onDismiss={vi.fn()}
        onAddAgain={vi.fn()}
      />,
    );

    expect(screen.getByText(/elaborato in 2 sessioni precedenti/i)).toBeDefined();
  });

  it('shows in-queue modal for single file', () => {
    render(
      <DuplicateFileModal
        prompt={{ kind: 'in-queue', filenames: ['audio.mp3'] }}
        onDismiss={vi.fn()}
        onAddAgain={vi.fn()}
      />,
    );
    expect(screen.getByText(/1 file gi/)).toBeTruthy();
    expect(screen.getByText(/audio.mp3/)).toBeTruthy();
  });

  it('shows in-queue modal for multiple files', () => {
    render(
      <DuplicateFileModal
        prompt={{ kind: 'in-queue', filenames: ['a.mp3', 'b.mp3', 'c.mp3'] }}
        onDismiss={vi.fn()}
        onAddAgain={vi.fn()}
      />,
    );
    expect(screen.getAllByText(/3 file/).length).toBeGreaterThan(0);
    expect(screen.getByText('- a.mp3')).toBeTruthy();
  });

  it('calls onDismiss when X button is clicked in in-queue modal', () => {
    const onDismiss = vi.fn();
    render(
      <DuplicateFileModal
        prompt={{ kind: 'in-queue', filenames: ['audio.mp3'] }}
        onDismiss={onDismiss}
        onAddAgain={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByLabelText('Chiudi finestra'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('renders nothing when prompt is null', () => {
    render(<DuplicateFileModal prompt={null} onDismiss={vi.fn()} onAddAgain={vi.fn()} />);
    expect(screen.queryByRole('heading')).toBeNull();
  });

  it('shows multiple matches list (count > 1)', () => {
    render(
      <DuplicateFileModal
        prompt={{
          kind: 'already-processed',
          matches: [
            { source: 'archive' as const, incoming: makeFile({ id: 'x1', name: 'a.mp3' }), sessions: [makeArchiveSession()] },
            { source: 'archive' as const, incoming: makeFile({ id: 'x2', name: 'b.mp3' }), sessions: [makeArchiveSession()] },
          ],
        }}
        onDismiss={vi.fn()}
        onAddAgain={vi.fn()}
      />,
    );
    expect(screen.getByText('- a.mp3')).toBeTruthy();
    expect(screen.getByText('- b.mp3')).toBeTruthy();
  });

  it('shows alsoInQueue list when provided', () => {
    render(
      <DuplicateFileModal
        prompt={{
          kind: 'already-processed',
          matches: [{ source: 'archive' as const, incoming: makeFile(), sessions: [makeArchiveSession()] }],
          alsoInQueue: ['extra.mp3'],
        }}
        onDismiss={vi.fn()}
        onAddAgain={vi.fn()}
      />,
    );
    expect(screen.getByText(/extra.mp3/)).toBeTruthy();
  });

  it('calls onAddAgain when re-process button is clicked', () => {
    const onAddAgain = vi.fn();
    const match = {
      source: 'archive' as const,
      incoming: makeFile(),
      sessions: [makeArchiveSession()],
    };
    render(
      <DuplicateFileModal
        prompt={{ kind: 'already-processed', matches: [match] }}
        onDismiss={vi.fn()}
        onAddAgain={onAddAgain}
      />,
    );
    fireEvent.click(screen.getByText('Rigenera da zero'));
    expect(onAddAgain).toHaveBeenCalledWith([match]);
  });

  it('does not call onDismiss when backdrop overlay is clicked', () => {
    const onDismiss = vi.fn();
    const { container } = render(
      <DuplicateFileModal
        prompt={{ kind: 'in-queue', filenames: ['audio.mp3'] }}
        onDismiss={onDismiss}
        onAddAgain={vi.fn()}
      />,
    );
    const backdrop = container.querySelector('.modal-overlay') as HTMLElement;
    fireEvent.click(backdrop);
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('calls onDismiss when Escape key is pressed', () => {
    const onDismiss = vi.fn();
    render(
      <DuplicateFileModal
        prompt={{ kind: 'in-queue', filenames: ['audio.mp3'] }}
        onDismiss={onDismiss}
        onAddAgain={vi.fn()}
      />,
    );
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
