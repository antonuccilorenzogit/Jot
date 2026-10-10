import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { FileItem } from '../appState';
import { CompletedSection } from './CompletedSection';

function makeFile(overrides: Partial<FileItem> = {}): FileItem {
  return {
    id: 'f1',
    name: 'lezione.mp3',
    size: 1024,
    duration: 60,
    status: 'done',
    progress: 100,
    phase: 3,
    ...overrides,
  };
}

const baseProps = {
  appState: 'idle' as const,
  onRemove: vi.fn(),
  onPreview: vi.fn(),
  onOpenFile: vi.fn(),
  onClearAll: vi.fn(),
};

describe('CompletedSection', () => {
  it('renders nothing when doneFiles is empty', () => {
    render(<CompletedSection {...baseProps} doneFiles={[]} />);
    expect(screen.queryByText('Sbobine completate')).toBeNull();
  });

  it('renders heading and file count when files are present', () => {
    render(<CompletedSection {...baseProps} doneFiles={[makeFile()]} />);
    expect(screen.getByText('Sbobine completate')).toBeTruthy();
    expect(screen.getByText('1')).toBeTruthy();
  });

  it('shows correct count for multiple files', () => {
    const files = [makeFile({ id: 'f1' }), makeFile({ id: 'f2' })];
    render(<CompletedSection {...baseProps} doneFiles={files} />);
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('renders "Pulisci tutto" button when appState is idle', () => {
    render(<CompletedSection {...baseProps} doneFiles={[makeFile()]} appState="idle" />);
    expect(screen.getByLabelText('Pulisci tutto')).toBeTruthy();
  });

  it('renders "Pulisci tutto" during processing too', () => {
    render(<CompletedSection {...baseProps} doneFiles={[makeFile()]} appState="processing" />);
    expect(screen.getByLabelText('Pulisci tutto')).toBeTruthy();
  });

  it('calls onClearAll when Pulisci tutto is clicked', () => {
    const onClearAll = vi.fn();
    render(<CompletedSection {...baseProps} doneFiles={[makeFile()]} onClearAll={onClearAll} />);
    fireEvent.click(screen.getByLabelText('Pulisci tutto'));
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  it('shows search box when there are 5 or more files', () => {
    const files = Array.from({ length: 5 }, (_, i) => makeFile({ id: `f${i}`, name: `file-${i}.mp3` }));
    render(<CompletedSection {...baseProps} doneFiles={files} />);
    expect(screen.getByPlaceholderText('Cerca...')).toBeTruthy();
  });

  it('does not show search box for fewer than 5 files', () => {
    const files = [makeFile({ id: 'f1' }), makeFile({ id: 'f2' })];
    render(<CompletedSection {...baseProps} doneFiles={files} />);
    expect(screen.queryByPlaceholderText('Cerca...')).toBeNull();
  });

  it('filters files by search query — only matching file is active', () => {
    const files = [
      makeFile({ id: 'f1', name: 'fisica.mp3' }),
      makeFile({ id: 'f2', name: 'chimica.mp3' }),
      makeFile({ id: 'f3', name: 'biologia.mp3' }),
      makeFile({ id: 'f4', name: 'storia.mp3' }),
      makeFile({ id: 'f5', name: 'matematica.mp3' }),
    ];
    render(<CompletedSection {...baseProps} doneFiles={files} />);
    fireEvent.change(screen.getByPlaceholderText('Cerca...'), { target: { value: 'fisica' } });
    expect(screen.getByText('fisica.mp3')).toBeTruthy();
  });

  it('shows no-results message when search finds nothing', () => {
    const files = Array.from({ length: 5 }, (_, i) => makeFile({ id: `f${i}`, name: `file-${i}.mp3` }));
    render(<CompletedSection {...baseProps} doneFiles={files} />);
    fireEvent.change(screen.getByPlaceholderText('Cerca...'), { target: { value: 'xyz-nonexistent' } });
    expect(screen.getByText(/Nessun risultato per/)).toBeTruthy();
  });

  it('clears search input when clear button is clicked', () => {
    const files = Array.from({ length: 5 }, (_, i) => makeFile({ id: `f${i}`, name: `file-${i}.mp3` }));
    render(<CompletedSection {...baseProps} doneFiles={files} />);
    const input = screen.getByPlaceholderText('Cerca...') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'file-1' } });
    expect(input.value).toBe('file-1');
    const clearButton = screen.getByLabelText('Cancella ricerca');
    fireEvent.click(clearButton);
    expect(input.value).toBe('');
  });

  it('passes folder indicators to completed cards by outputDir', () => {
    const sessionFolderMap = new Map([
      ['/sessions/s1', { id: 'folder-1', name: 'Corso A', color: '#4D96FF', session_dirs: ['/sessions/s1'] }],
    ]);
    render(
      <CompletedSection
        {...baseProps}
        doneFiles={[makeFile({ outputDir: '/sessions/s1', outputHtml: '/sessions/s1/out.html' })]}
        sessionFolderMap={sessionFolderMap}
      />,
    );
    expect(screen.getByTitle('Raccolta: Corso A')).toBeTruthy();
  });

  it('renders a bounded scrollable container for completed items with natural scroll chaining', () => {
    const { container } = render(
      <CompletedSection
        {...baseProps}
        doneFiles={[makeFile()]}
      />,
    );
    const scrollContainer = container.querySelector('.overflow-y-auto.app-scroll.is-chainable');
    expect(scrollContainer).toBeTruthy();
    expect(scrollContainer?.className).toContain('max-h-[390px]');
  });
});
