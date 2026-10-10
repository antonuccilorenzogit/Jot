import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AppStatus, FileItem } from '../appState';
import { QueueSection, type QueueSectionProps } from './QueueSection';

function makeFile(overrides: Partial<FileItem> = {}): FileItem {
  return {
    id: 'f1',
    name: 'lezione.mp3',
    size: 1024,
    duration: 60,
    status: 'queued',
    progress: 0,
    phase: 0,
    ...overrides,
  };
}

interface TestOverrides {
  pendingFiles?: FileItem[];
  appState?: AppStatus;
  currentPhase?: string;
  currentModel?: string;
  preferredModel?: string;
  queuedCount?: number;
  failedCount?: number;
  canStart?: boolean;
  canResumeAll?: boolean;
  hasApiKey?: boolean;
  isApiKeyValid?: boolean;
  isOnline?: boolean;
  autoContinue?: boolean;
  setAutoContinue?: React.Dispatch<React.SetStateAction<boolean>>;
  onRemove?: (id: string) => void;
  onClearAll?: () => void;
  onRetry?: (id: string) => void;
  onResumeAll?: () => void;
  onPreview?: (htmlPath: string, filename: string, sourcePath?: string, fileId?: string, sessionDir?: string) => void;
  onOpenFile?: (path: string) => void;
  onStart?: () => void;
  onStop?: () => void;
  onOpenSettings?: () => void;
  onAddFiles?: () => void;
}

function makeProps(overrides: TestOverrides = {}): QueueSectionProps {
  const pending = overrides.pendingFiles !== undefined ? overrides.pendingFiles : [makeFile()];
  const failed = pending.filter(f => f.status === 'error' || f.status === 'paused').length;
  return {
    pendingFiles: pending,
    progress: {
      appState: overrides.appState ?? 'idle',
      currentPhase: overrides.currentPhase ?? '',
      currentModel: overrides.currentModel,
    },
    auth: {
      preferredModel: overrides.preferredModel ?? 'gemini-2.5-flash',
    },
    status: {
      queuedCount: overrides.queuedCount !== undefined ? overrides.queuedCount : pending.filter(f => f.status === 'queued').length,
      failedCount: overrides.failedCount !== undefined ? overrides.failedCount : failed,
      canStart: overrides.canStart ?? true,
      canResumeAll: overrides.canResumeAll ?? true,
      hasApiKey: overrides.hasApiKey ?? true,
      isApiKeyValid: overrides.isApiKeyValid ?? true,
      isOnline: overrides.isOnline ?? true,
      autoContinue: overrides.autoContinue ?? false,
      setAutoContinue: overrides.setAutoContinue ?? vi.fn(),
    },
    dnd: {
      sensors: [],
      onDragEnd: vi.fn(),
    },
    actions: {
      onRemove: overrides.onRemove ?? vi.fn(),
      onClearAll: overrides.onClearAll ?? vi.fn(),
      onRetry: overrides.onRetry ?? vi.fn(),
      onResumeAll: overrides.onResumeAll,
      onPreview: overrides.onPreview ?? vi.fn(),
      onOpenFile: overrides.onOpenFile ?? vi.fn(),
      onStart: overrides.onStart ?? vi.fn(),
      onStop: overrides.onStop ?? vi.fn(),
      onOpenSettings: overrides.onOpenSettings,
      onAddFiles: overrides.onAddFiles,
    },
  };
}

describe('QueueSection', () => {
  it('renders nothing when no pending files and appState is idle', () => {
    render(<QueueSection {...makeProps({ pendingFiles: [], queuedCount: 0 })} />);
    expect(screen.queryByText('Coda di elaborazione')).toBeNull();
  });

  it('shows queue heading when files are present', () => {
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()] })} />);
    expect(screen.getByText('Coda di elaborazione')).toBeTruthy();
  });

  it('shows file count pill', () => {
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()] })} />);
    expect(screen.getByText('1')).toBeTruthy();
  });

  it('shows count for multiple files', () => {
    const files = [makeFile({ id: 'f1' }), makeFile({ id: 'f2' })];
    render(<QueueSection {...makeProps({ pendingFiles: files, queuedCount: 2 })} />);
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('shows model pill without "Modello:" prefix', () => {
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()] })} />);
    expect(screen.getByText('2.5-flash')).toBeTruthy();
    expect(screen.queryByText(/Modello:/)).toBeNull();
  });

  it('shows currentModel instead of preferredModel when processing', () => {
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [makeFile({ status: 'processing' })],
          appState: 'processing',
          preferredModel: 'gemini-3.5-flash',
          currentModel: 'gemini-2.5-flash',
        })}
      />,
    );
    expect(screen.getByText('2.5-flash')).toBeTruthy();
    expect(screen.queryByText('3.5-flash')).toBeNull();
  });

  it('shows start button when idle with canStart', () => {
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()] })} />);
    expect(screen.getByText(/Avvia sbobinatura/)).toBeTruthy();
  });

  it('calls onStart when start button is clicked', () => {
    const onStart = vi.fn();
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()], onStart })} />);
    fireEvent.click(screen.getByText(/Avvia sbobinatura/));
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it('shows API key warning when hasApiKey is false', () => {
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()], hasApiKey: false, canStart: false })} />);
    expect(screen.getByText(/Inserisci API Key/)).toBeTruthy();
  });

  it('shows invalid key warning when key is present but invalid', () => {
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [makeFile()],
          hasApiKey: true,
          isApiKeyValid: false,
          canStart: false,
        })}
      />,
    );
    expect(screen.getByText(/API Key non valida/)).toBeTruthy();
  });

  it('shows offline warning when isOnline is false', () => {
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [makeFile()],
          isOnline: false,
          canStart: false,
        })}
      />,
    );
    expect(screen.getByText(/Connessione Internet assente/)).toBeTruthy();
  });

  it('shows Stop button when processing', () => {
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [makeFile({ status: 'processing' })],
          appState: 'processing',
        })}
      />,
    );
    expect(screen.getByText('Interrompi elaborazione')).toBeTruthy();
  });

  it('calls onStop when Stop button is clicked', () => {
    const onStop = vi.fn();
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [makeFile({ status: 'processing' })],
          appState: 'processing',
          onStop,
        })}
      />,
    );
    fireEvent.click(screen.getByText('Interrompi elaborazione'));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('shows "Annullamento in corso" when canceling', () => {
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [makeFile({ status: 'processing' })],
          appState: 'canceling',
        })}
      />,
    );
    expect(screen.getAllByText('Annullamento in corso...').length).toBeGreaterThan(0);
  });

  it('auto-continue toggle changes state and menu stays open', () => {
    const setAutoContinue = vi.fn();
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()], setAutoContinue })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni coda' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Coda automatica' }));
    expect(setAutoContinue).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('menuitem', { name: 'Coda automatica' })).toBeTruthy();
  });

  it('renders all files when more than 5 exist (no pagination button)', () => {
    const files = Array.from({ length: 7 }, (_, i) => makeFile({ id: `f${i}`, name: `file${i}.mp3` }));
    render(<QueueSection {...makeProps({ pendingFiles: files, queuedCount: 7 })} />);
    expect(screen.getByText('file6.mp3')).toBeTruthy();
    expect(screen.queryByText(/Mostra altri/)).toBeNull();
  });

  it('shows Svuota coda button when idle and files present', () => {
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()] })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni coda' }));
    expect(screen.getByRole('menuitem', { name: 'Svuota coda' })).toBeTruthy();
  });

  it('calls onClearAll when Svuota coda is clicked', () => {
    const onClearAll = vi.fn();
    render(<QueueSection {...makeProps({ pendingFiles: [makeFile()], onClearAll })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni coda' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Svuota coda' }));
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  it('hides Svuota coda button when processing', () => {
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [makeFile({ status: 'processing' })],
          appState: 'processing',
        })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni coda' }));
    expect(screen.queryByRole('menuitem', { name: 'Svuota coda' })).toBeNull();
  });

  it('hides Aggiungi audio button when idle because dropzone is already visible', () => {
    const onAddFiles = vi.fn();
    render(<QueueSection {...makeProps({ onAddFiles, appState: 'idle' })} />);
    expect(screen.queryByRole('button', { name: 'Aggiungi audio' })).toBeNull();
  });

  it('hides Aggiungi audio button when canceling', () => {
    const onAddFiles = vi.fn();
    render(<QueueSection {...makeProps({ onAddFiles, appState: 'canceling' })} />);
    expect(screen.queryByRole('button', { name: 'Aggiungi audio' })).toBeNull();
  });

  it('renders Aggiungi audio button when processing and handles click', () => {
    const onAddFiles = vi.fn();
    render(
      <QueueSection
        {...makeProps({
          onAddFiles,
          appState: 'processing',
          pendingFiles: [makeFile({ status: 'processing' })],
        })}
      />,
    );
    const addBtn = screen.getByRole('button', { name: 'Aggiungi audio' });
    expect(addBtn).toBeTruthy();
    fireEvent.click(addBtn);
    expect(onAddFiles).toHaveBeenCalledTimes(1);
  });

  it('shows drag handles during processing when at least 2 queued files exist', () => {
    const files = [
      makeFile({ id: 'f0', name: 'current.mp3', status: 'processing' }),
      makeFile({ id: 'f1', name: 'queued1.mp3', status: 'queued' }),
      makeFile({ id: 'f2', name: 'queued2.mp3', status: 'queued' }),
    ];
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: files,
          queuedCount: 2,
          appState: 'processing',
        })}
      />,
    );
    const handles = screen.getAllByLabelText('Trascina per riordinare');
    // The two queued files have drag handles, processing does not
    expect(handles.length).toBe(2);
  });

  it('renders a bounded scrollable container for queue items with natural scroll chaining', () => {
    const { container } = render(<QueueSection {...makeProps({ pendingFiles: [makeFile()] })} />);
    const scrollContainer = container.querySelector('.overflow-y-auto.app-scroll.is-chainable');
    expect(scrollContainer).toBeTruthy();
    expect(scrollContainer?.className).toContain('max-h-[390px]');
  });

  it('renders Riprendi elaborazione button when queuedCount is 0 and failedCount > 0', () => {
    const onResumeAll = vi.fn();
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [makeFile({ status: 'error' })],
          queuedCount: 0,
          failedCount: 1,
          canResumeAll: true,
          onResumeAll,
          appState: 'idle',
        })}
      />,
    );
    const resumeBtn = screen.getByText(/Riprendi elaborazione/);
    expect(resumeBtn).toBeTruthy();
    fireEvent.click(resumeBtn);
    expect(onResumeAll).toHaveBeenCalledTimes(1);
  });

  it('renders Avvia sbobinatura with sum of queued and failed files when both are > 0', () => {
    const onStart = vi.fn();
    render(
      <QueueSection
        {...makeProps({
          pendingFiles: [
            makeFile({ id: 'f1', status: 'error' }),
            makeFile({ id: 'f2', status: 'queued' }),
            makeFile({ id: 'f3', status: 'queued' }),
          ],
          queuedCount: 2,
          failedCount: 1,
          canStart: true,
          onStart,
          appState: 'idle',
        })}
      />,
    );
    const startBtn = screen.getByText('Avvia sbobinatura (3 file)');
    expect(startBtn).toBeTruthy();
    fireEvent.click(startBtn);
    expect(onStart).toHaveBeenCalledTimes(1);
  });
});
