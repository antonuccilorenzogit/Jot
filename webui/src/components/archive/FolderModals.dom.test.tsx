import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import {
  FolderModal,
  DeleteFolderConfirmModal,
  DeleteMultipleSessionsConfirmModal,
  AddSessionsToFolderModal,
  DEFAULT_FOLDER_COLOR,
  FOLDER_COLORS,
} from './FolderModals';
import type { ArchiveFolder, ArchiveSession } from '../../bridge';

describe('FolderModals and AddSessionsToFolderModal', () => {
  const mockFolder: ArchiveFolder = {
    id: 'folder-1',
    name: 'Anatomia',
    color: DEFAULT_FOLDER_COLOR,
    session_dirs: ['session-1'],
  };

  describe('FolderModal', () => {
    it('renders create modal with design system classes and saves new folder with default saturated color', () => {
      const handleClose = vi.fn();
      const handleSave = vi.fn();

      const { container } = render(
        <FolderModal
          state={{ type: 'create' }}
          onClose={handleClose}
          onSave={handleSave}
        />,
      );

      // Verify modal structural classes
      expect(container.querySelector('.modal-header')).toBeTruthy();
      expect(container.querySelector('.modal-body')).toBeTruthy();
      expect(container.querySelector('.modal-footer')).toBeTruthy();

      // Verify input has .app-input class
      const input = screen.getByPlaceholderText('es. Anatomia');
      expect(input.className).toContain('app-input');

      // Verify header folder color dot has default saturated color
      const headerDot = container.querySelector('.modal-header .folder-color-dot');
      expect(headerDot).toBeTruthy();

      // Verify close button
      const closeBtn = container.querySelector('.modal-header .modal-icon-button');
      expect(closeBtn).toBeTruthy();

      // Verify all 10 saturated colors are present
      expect(FOLDER_COLORS).toHaveLength(10);
      expect(FOLDER_COLORS[0]).toBe('#FF6B6B');
      expect(DEFAULT_FOLDER_COLOR).toBe('#FF6B6B');
      for (const c of FOLDER_COLORS) {
        expect(screen.getByLabelText(`Colore ${c}`)).toBeTruthy();
      }

      // Type name and save
      fireEvent.change(input, { target: { value: 'Biochimica' } });
      const submitBtn = screen.getByRole('button', { name: 'Crea raccolta' });
      fireEvent.click(submitBtn);

      expect(handleSave).toHaveBeenCalledWith('Biochimica', DEFAULT_FOLDER_COLOR);
    });

    it('allows selecting a different saturated color from the palette', () => {
      const handleSave = vi.fn();

      render(
        <FolderModal
          state={{ type: 'create' }}
          onClose={vi.fn()}
          onSave={handleSave}
        />,
      );

      const input = screen.getByPlaceholderText('es. Anatomia');
      fireEvent.change(input, { target: { value: 'Farmacologia' } });

      // Pick blue from saturated palette (#4D96FF)
      const blueSwatch = screen.getByLabelText(`Colore ${FOLDER_COLORS[4]}`);
      fireEvent.click(blueSwatch);

      const submitBtn = screen.getByRole('button', { name: 'Crea raccolta' });
      fireEvent.click(submitBtn);

      expect(handleSave).toHaveBeenCalledWith('Farmacologia', '#4D96FF');
    });

    it('renders edit modal with existing name and color', () => {
      const handleClose = vi.fn();
      const handleSave = vi.fn();

      render(
        <FolderModal
          state={{ type: 'edit', folder: mockFolder }}
          onClose={handleClose}
          onSave={handleSave}
        />,
      );

      expect(screen.getByDisplayValue('Anatomia')).toBeTruthy();
      const saveBtn = screen.getByRole('button', { name: 'Salva modifiche' });
      expect(saveBtn).toBeTruthy();
    });

    it('matches color swatch case-insensitively and falls back to default when empty', () => {
      const handleSave = vi.fn();

      // Test lowercase hex matching
      const { rerender } = render(
        <FolderModal
          state={{ type: 'edit', folder: { id: 'f-2', name: 'Cardio', color: '#ffd93d', session_dirs: [] } }}
          onClose={vi.fn()}
          onSave={handleSave}
        />,
      );

      const yellowSwatch = screen.getByLabelText('Colore #FFD93D');
      expect(yellowSwatch.getAttribute('aria-pressed')).toBe('true');
      expect(yellowSwatch.style.border).toContain('3px solid var(--text-primary)');

      // Rerender with empty color to test fallback to DEFAULT_FOLDER_COLOR
      rerender(
        <FolderModal
          state={{ type: 'edit', folder: { id: 'f-3', name: 'Neurologia', color: '', session_dirs: [] } }}
          onClose={vi.fn()}
          onSave={handleSave}
        />,
      );

      expect(screen.getByDisplayValue('Neurologia')).toBeTruthy();
      const defaultSwatch = screen.getByLabelText(`Colore ${DEFAULT_FOLDER_COLOR}`);
      expect(defaultSwatch.getAttribute('aria-pressed')).toBe('true');

      fireEvent.click(screen.getByRole('button', { name: 'Salva modifiche' }));
      expect(handleSave).toHaveBeenCalledWith('Neurologia', DEFAULT_FOLDER_COLOR);
    });

    it('closes on cancel button and close icon button click', () => {
      const handleClose = vi.fn();

      const { container } = render(
        <FolderModal
          state={{ type: 'create' }}
          onClose={handleClose}
          onSave={vi.fn()}
        />,
      );

      fireEvent.click(screen.getByRole('button', { name: 'Annulla' }));
      expect(handleClose).toHaveBeenCalledTimes(1);

      const closeIconBtn = container.querySelector('.modal-header .modal-icon-button') as HTMLElement;
      fireEvent.click(closeIconBtn);
      expect(handleClose).toHaveBeenCalledTimes(2);
    });
  });

  describe('DeleteFolderConfirmModal', () => {
    it('renders with modal classes and confirms deletion', () => {
      const handleClose = vi.fn();
      const handleConfirm = vi.fn();

      const { container } = render(
        <DeleteFolderConfirmModal
          folder={mockFolder}
          onClose={handleClose}
          onConfirm={handleConfirm}
        />,
      );

      expect(container.querySelector('.modal-header')).toBeTruthy();
      expect(container.querySelector('.modal-body')).toBeTruthy();
      expect(container.querySelector('.modal-footer')).toBeTruthy();

      const closeBtn = container.querySelector('.modal-header .modal-icon-button');
      expect(closeBtn).toBeTruthy();

      const confirmBtn = screen.getByRole('button', { name: 'Elimina raccolta' });
      expect(confirmBtn.className).toContain('modal-action-button');
      expect(confirmBtn.className).toContain('is-danger');

      fireEvent.click(confirmBtn);
      expect(handleConfirm).toHaveBeenCalledTimes(1);
    });
  });

  describe('DeleteMultipleSessionsConfirmModal', () => {
    it('renders preview of sessions and calls onConfirm', () => {
      const handleClose = vi.fn();
      const handleConfirm = vi.fn();

      const { container } = render(
        <DeleteMultipleSessionsConfirmModal
          sessions={[
            { sessionDir: 'dir-1', name: 'Lezione 1' },
            { sessionDir: 'dir-2', name: 'Lezione 2' },
          ]}
          onClose={handleClose}
          onConfirm={handleConfirm}
        />,
      );

      expect(container.querySelector('.modal-header')).toBeTruthy();
      expect(container.querySelector('.modal-body')).toBeTruthy();
      expect(container.querySelector('.modal-footer')).toBeTruthy();

      expect(screen.getByText(/Lezione 1/)).toBeTruthy();
      expect(screen.getByText(/Lezione 2/)).toBeTruthy();

      const confirmBtn = screen.getByRole('button', { name: 'Elimina 2 sbobine' });
      fireEvent.click(confirmBtn);
      expect(handleConfirm).toHaveBeenCalledTimes(1);
    });
  });

  describe('AddSessionsToFolderModal', () => {
    const mockSessions: ArchiveSession[] = [
      {
        session_dir: 'session-2',
        name: 'Lezione 2 Disponibile',
        html_path: '/path/2.html',
        input_path: '/path/2.mp3',
        completed_at_iso: '2026-01-01T10:00:00Z',
        effective_model: 'gemini-1.5-pro',
      },
      {
        session_dir: 'session-3',
        name: 'Lezione 3 Disponibile',
        html_path: '/path/3.html',
        input_path: '/path/3.mp3',
        completed_at_iso: '2026-01-02T10:00:00Z',
        effective_model: 'gemini-1.5-pro',
      },
    ];

    it('renders with modal classes, folder-color-dot, and adds selected sessions', () => {
      const handleClose = vi.fn();
      const handleAddSessions = vi.fn();

      const { container } = render(
        <AddSessionsToFolderModal
          folder={mockFolder}
          availableSessions={mockSessions}
          onClose={handleClose}
          onAdd={handleAddSessions}
        />,
      );

      expect(container.querySelector('.modal-header')).toBeTruthy();
      expect(container.querySelector('.modal-body')).toBeTruthy();
      expect(container.querySelector('.modal-footer')).toBeTruthy();

      const headerDot = container.querySelector('.modal-header .folder-color-dot');
      expect(headerDot).toBeTruthy();

      const closeBtn = container.querySelector('.modal-header .modal-icon-button');
      expect(closeBtn).toBeTruthy();

      // Select session-2
      const session2Card = screen.getByText('Lezione 2 Disponibile');
      fireEvent.click(session2Card);

      const addBtn = screen.getByRole('button', { name: 'Aggiungi (1)' });
      fireEvent.click(addBtn);

      expect(handleAddSessions).toHaveBeenCalledWith(['session-2']);
    });
  });
});
