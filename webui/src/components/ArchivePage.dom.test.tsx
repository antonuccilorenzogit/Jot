import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ArchiveFolder, ArchiveSession } from '../bridge';
import { ArchivePage } from './ArchivePage';

const motionCache = new Map<string, React.ComponentType<Record<string, unknown>>>();
vi.mock('motion/react', () => ({
  motion: new Proxy({}, {
    get: (_target, prop: string) => {
      const tag = prop;
      if (!motionCache.has(tag)) {
        motionCache.set(
          tag,
          React.forwardRef((props: Record<string, unknown>, ref: unknown) => {
            const { initial: _i, animate: _a, exit: _e, transition: _t, layout: _l, variants: _v, layoutId: _li, whileTap: _wt, whileHover: _wh, ...rest } = props;
            return React.createElement(tag, { ...rest, ref: ref as React.Ref<unknown> });
          })
        );
      }
      return motionCache.get(tag);
    },
  }),
  AnimatePresence: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
}));

function makeSession(id: string, name = `Lezione ${id}`): ArchiveSession {
  return {
    session_dir: `/sessions/${id}`,
    name,
    html_path: `/sessions/${id}/out.html`,
    input_path: `/audio/${id}.mp3`,
    completed_at_iso: `2024-01-0${Math.min(Number(id.replace(/\D/g, '')) || 1, 9)}T00:00:00`,
    effective_model: 'gemini-flash',
  };
}

function renderArchive(overrides: Partial<{
  sessions: ArchiveSession[];
  folders: ArchiveFolder[];
  onFoldersChange: (folders: ArchiveFolder[]) => void;
}> = {}) {
  return render(
    <ArchivePage
      sessions={overrides.sessions ?? [makeSession('s1')]}
      folders={overrides.folders ?? []}
      onFoldersChange={overrides.onFoldersChange ?? vi.fn()}
      onPreview={vi.fn()}
      onOpenFile={vi.fn()}
      onDeleteSession={vi.fn()}
    />,
  );
}

describe('ArchivePage', () => {
  it('shows the folder indicator on archive session cards', () => {
    const folder: ArchiveFolder = {
      id: 'f1',
      name: 'Corso A',
      color: '#4D96FF',
      session_dirs: ['/sessions/s1'],
    };
    renderArchive({ folders: [folder] });
    expect(screen.getAllByTitle('Raccolta: Corso A').length).toBeGreaterThan(0);
  });

  it('renders all sessions in a single list without pagination controls', () => {
    const sessions = Array.from({ length: 15 }, (_, index) => makeSession(`s${index + 1}`, `Lezione ${index + 1}`));
    renderArchive({ sessions });

    // Assert all 15 sessions are visible on the screen
    for (let i = 1; i <= 15; i++) {
      expect(screen.getAllByText(`Lezione ${i}`).length).toBeGreaterThan(0);
    }

    // Assert that the page navigation buttons do not exist
    expect(screen.queryByLabelText('Pagina successiva')).toBeNull();
    expect(screen.queryByLabelText('Pagina precedente')).toBeNull();
  });

  it('displays Aperto badge when last_opened_at_iso is present on a session', () => {
    const session = {
      ...makeSession('s1'),
      last_opened_at_iso: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    };
    renderArchive({ sessions: [session] });
    expect(screen.getAllByText(/Aperto/).length).toBeGreaterThan(0);
  });

  it('opens the add lessons modal from folder header and renders available sessions', () => {
    const s1 = makeSession('s1', 'Lezione In Cartella');
    const s2 = makeSession('s2', 'Lezione Disponibile');
    const folder: ArchiveFolder = {
      id: 'f1',
      name: 'Corso A',
      color: '#4D96FF',
      session_dirs: ['/sessions/s1'],
    };

    renderArchive({ sessions: [s1, s2], folders: [folder] });

    fireEvent.click(screen.getAllByText('Corso A')[0]);

    const openModalButton = screen.getByText('Aggiungi lezioni').closest('button');
    expect(openModalButton).toBeTruthy();
    fireEvent.click(openModalButton!);

    // Modal title contains the folder name
    expect(screen.getByText('Corso A', { selector: 'span' })).toBeTruthy();
    // Modal displays available session
    expect(screen.getByText('Lezione Disponibile')).toBeTruthy();
  });

  it('renders the last opened/modified sbobina mini section and triggers preview on click', () => {
    const onPreview = vi.fn();
    const s1 = {
      ...makeSession('s1', 'Lezione Vecchia'),
      completed_at_iso: '2024-01-01T00:00:00Z',
    };
    const s2 = {
      ...makeSession('s2', 'Lezione Recente'),
      last_opened_at_iso: new Date(Date.now() - 60000).toISOString(),
    };

    render(
      <ArchivePage
        sessions={[s1, s2]}
        folders={[]}
        onFoldersChange={vi.fn()}
        onPreview={onPreview}
        onOpenFile={vi.fn()}
        onDeleteSession={vi.fn()}
      />,
    );

    expect(screen.getByText('Ultima sbobina aperta / modificata')).toBeTruthy();
    expect(screen.getAllByText('Lezione Recente').length).toBeGreaterThan(0);
    expect(screen.getByText('Riprendi')).toBeTruthy();

    fireEvent.click(screen.getByText('Riprendi'));
    expect(onPreview).toHaveBeenCalledWith(s2.html_path, s2.name, s2.input_path, undefined, s2.session_dir);
  });

  it('supports multiselect and batch assigning sessions to a folder', () => {
    const s1 = makeSession('s1', 'Lezione 1');
    const s2 = makeSession('s2', 'Lezione 2');
    const s3 = makeSession('s3', 'Lezione 3');
    const folder: ArchiveFolder = {
      id: 'f1',
      name: 'Corso Biologia',
      color: '#4D96FF',
      session_dirs: [],
    };
    const onFoldersChange = vi.fn();

    renderArchive({ sessions: [s1, s2, s3], folders: [folder], onFoldersChange });

    // Select s1 and s2 via their checkbox buttons
    const selectButtons = screen.getAllByTitle('Seleziona');
    fireEvent.click(selectButtons[0]);
    fireEvent.click(selectButtons[1]);

    // Action bar is visible with 2 selected
    expect(screen.getByText('Aggiungi')).toBeTruthy();
    expect(screen.getByTitle('Aggiungi le sbobine selezionate a una cartella')).toBeTruthy();

    // Click Aggiungi
    fireEvent.click(screen.getByTitle('Aggiungi le sbobine selezionate a una cartella'));

    // Click the folder in the dropdown
    const folderMenuItems = screen.getAllByText('Corso Biologia');
    fireEvent.click(folderMenuItems[folderMenuItems.length - 1]);

    expect(onFoldersChange).toHaveBeenCalled();
    const updatedFolders = onFoldersChange.mock.calls[0][0] as ArchiveFolder[];
    expect(updatedFolders[0].session_dirs).toContain('/sessions/s3');
    expect(updatedFolders[0].session_dirs).toContain('/sessions/s2');
  });

  it('supports batch adding multiple sessions from the add lessons modal in FolderDetailView', () => {
    const s1 = makeSession('s1', 'Lezione In Cartella');
    const s2 = makeSession('s2', 'Lezione Disp 1');
    const s3 = makeSession('s3', 'Lezione Disp 2');
    const folder: ArchiveFolder = {
      id: 'f1',
      name: 'Corso A',
      color: '#4D96FF',
      session_dirs: ['/sessions/s1'],
    };
    const onFoldersChange = vi.fn();

    renderArchive({ sessions: [s1, s2, s3], folders: [folder], onFoldersChange });

    // Navigate to folder
    fireEvent.click(screen.getAllByText('Corso A')[0]);

    // Open add modal
    const openModalButton = screen.getByText('Aggiungi lezioni').closest('button');
    fireEvent.click(openModalButton!);

    // Click "Seleziona tutte (2)"
    const selectAllBtn = screen.getByText(/Seleziona tutte/);
    fireEvent.click(selectAllBtn);

    // Click "Aggiungi (2)"
    const addBatchBtn = screen.getByText(/Aggiungi \(2\)/).closest('button');
    expect(addBatchBtn).toBeTruthy();
    fireEvent.click(addBatchBtn!);

    expect(onFoldersChange).toHaveBeenCalled();
  });

  it('toggles select all and deselect all from the action bar', () => {
    const s1 = makeSession('s1', 'Lezione 1');
    const s2 = makeSession('s2', 'Lezione 2');
    const s3 = makeSession('s3', 'Lezione 3');

    renderArchive({ sessions: [s1, s2, s3], folders: [] });

    // Select 1 item
    const selectButtons = screen.getAllByTitle('Seleziona');
    fireEvent.click(selectButtons[0]);

    // Click "Seleziona tutte"
    const selectAllBtn = screen.getByText('Seleziona tutte');
    fireEvent.click(selectAllBtn);

    // Now all 3 are selected, button changes to "Deseleziona"
    const deselectBtn = screen.getByText('Deseleziona');
    expect(deselectBtn).toBeTruthy();

    // Click "Deseleziona" -> restores the 1 item previously chosen
    fireEvent.click(deselectBtn);

    // 1 item is now selected again
    expect(screen.getByText('1')).toBeTruthy();
    expect(screen.getByText('Seleziona tutte')).toBeTruthy();
  });

  it('keeps selections intact when delete confirmation modal opens and cancels', () => {
    const s1 = makeSession('s1', 'Lezione 1');
    const s2 = makeSession('s2', 'Lezione 2');
    const onDeleteMultipleSessions = vi.fn();

    render(
      <ArchivePage
        sessions={[s1, s2]}
        folders={[]}
        onFoldersChange={vi.fn()}
        onPreview={vi.fn()}
        onOpenFile={vi.fn()}
        onDeleteSession={vi.fn()}
        onDeleteMultipleSessions={onDeleteMultipleSessions}
      />,
    );

    // Select both
    const selectButtons = screen.getAllByTitle('Seleziona');
    fireEvent.click(selectButtons[0]);
    fireEvent.click(selectButtons[1]);

    // Click Elimina
    const deleteBtn = screen.getByTitle('Elimina le sbobine selezionate dal disco');
    fireEvent.click(deleteBtn);

    // onDeleteMultipleSessions called with selected items
    expect(onDeleteMultipleSessions).toHaveBeenCalledWith([
      expect.objectContaining({ sessionDir: s2.session_dir }),
      expect.objectContaining({ sessionDir: s1.session_dir }),
    ]);

    // Selection bar remains visible
    expect(screen.getByText('Deseleziona')).toBeTruthy();
  });

  it('matches sessions and displays correct folder count regardless of path casing or backslashes', () => {
    const s1: ArchiveSession = {
      session_dir: 'C:\\Users\\lorenzo\\AppData\\Local\\jot\\Sessions\\s1',
      name: 'Lezione Istologia 1',
      html_path: 'C:\\Users\\lorenzo\\AppData\\Local\\jot\\Sessions\\s1\\out.html',
      input_path: 'C:\\audio\\s1.mp3',
      completed_at_iso: '2024-01-01T00:00:00',
      effective_model: 'gemini-flash',
    };

    // Folder saved with lower-case "sessions"
    const folder: ArchiveFolder = {
      id: 'f1',
      name: 'ISTOLOGIA',
      color: '#FF6B6B',
      session_dirs: ['C:\\Users\\lorenzo\\AppData\\Local\\jot\\sessions\\s1'],
    };

    renderArchive({ sessions: [s1], folders: [folder] });

    // 1. Folder card on main archive page displays "1 lezione" (not 0)
    expect(screen.getByText('1 lezione')).toBeTruthy();

    // 2. Session card displays the ISTOLOGIA chip
    expect(screen.getAllByTitle('Raccolta: ISTOLOGIA').length).toBeGreaterThan(0);

    // 3. Navigate into the folder
    const folderCard = screen.getAllByText('ISTOLOGIA')[0];
    fireEvent.click(folderCard);

    // 4. Inside FolderDetailView, the session is displayed and count is 1
    expect(screen.getByText('Lezione Istologia 1')).toBeTruthy();
  });

  it('performs full-text search and formats count with plus when total exceeds results', async () => {
    const s1 = makeSession('s1', 'Istologia 1');
    const mockSearchSessions = vi.fn().mockResolvedValue({
      ok: true,
      results: [
        {
          session_dir: '/sessions/s1',
          name: 'Istologia 1',
          html_path: '/sessions/s1/out.html',
          completed_at_iso: '2024-01-01T00:00:00Z',
          snippets: [{ before: 'test', match: 'epitelio', after: 'tessuto' }],
          match_count: 5,
        },
      ],
      total: 10,
    });

    (window as unknown as { pywebview: { api: { search_sessions: unknown } } }).pywebview = {
      api: { search_sessions: mockSearchSessions },
    };

    renderArchive({ sessions: [s1] });

    // Switch to full-text search mode
    const modeBtn = screen.getByTitle('Testo completo (Ricerca nel contenuto)');
    act(() => {
      fireEvent.click(modeBtn);
    });

    const input = screen.getByPlaceholderText('Cerca nel contenuto...');
    act(() => {
      fireEvent.change(input, { target: { value: 'epitelio' } });
    });

    // Wait for debounced search and results
    await waitFor(() => {
      expect(mockSearchSessions).toHaveBeenCalledWith('epitelio', 100);
      expect(screen.getByText('1+ sbobine trovate')).toBeTruthy();
    });

    // SortMenu remains visible and includes full-text relevance option
    const sortBtn = screen.getByRole('button', { name: 'Cambia ordinamento' });
    expect(sortBtn).toBeTruthy();
    act(() => {
      fireEvent.click(sortBtn);
    });
    expect(await screen.findByText('Più occorrenze')).toBeTruthy();
  });

  it('calls onNotification when importing sbobina package fails with error', async () => {
    const onNotification = vi.fn();
    (window as unknown as { pywebview: { api: { import_sbobina_package: unknown } } }).pywebview = {
      api: {
        import_sbobina_package: vi.fn().mockResolvedValue({ ok: false, error: 'File corrotto' }),
      },
    };

    render(
      <ArchivePage
        sessions={[makeSession('s1')]}
        folders={[]}
        onFoldersChange={vi.fn()}
        onPreview={vi.fn()}
        onOpenFile={vi.fn()}
        onDeleteSession={vi.fn()}
        onNotification={onNotification}
      />,
    );

    const importBtn = screen.getByTitle('Importa Sbobina (.sbobina)');
    await act(async () => {
      fireEvent.click(importBtn);
    });

    await vi.waitFor(() => {
      expect(onNotification).toHaveBeenCalledWith('Importazione non riuscita', 'File corrotto', 'error');
    });
  });

  it('calls onNotification when importing sbobina package throws unexpected exception', async () => {
    const onNotification = vi.fn();
    (window as unknown as { pywebview: { api: { import_sbobina_package: unknown } } }).pywebview = {
      api: {
        import_sbobina_package: vi.fn().mockRejectedValue(new Error('Network IPC failure')),
      },
    };

    render(
      <ArchivePage
        sessions={[makeSession('s1')]}
        folders={[]}
        onFoldersChange={vi.fn()}
        onPreview={vi.fn()}
        onOpenFile={vi.fn()}
        onDeleteSession={vi.fn()}
        onNotification={onNotification}
      />,
    );

    const importBtn = screen.getByTitle('Importa Sbobina (.sbobina)');
    await act(async () => {
      fireEvent.click(importBtn);
    });

    await vi.waitFor(() => {
      expect(onNotification).toHaveBeenCalledWith('Importazione non riuscita', 'Error: Network IPC failure', 'error');
    });
  });
});
