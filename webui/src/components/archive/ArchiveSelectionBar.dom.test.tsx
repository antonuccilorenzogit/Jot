import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ArchiveSelectionBar } from './ArchiveSelectionBar';
import type { ArchiveFolder } from '../../bridge';

describe('ArchiveSelectionBar component', () => {
  const mockFolders: ArchiveFolder[] = [
    {
      id: 'folder-1',
      name: 'Cardiologia',
      color: '#3d6b3a',
      session_dirs: ['s-1', 's-2'],
    },
    {
      id: 'folder-2',
      name: 'Neurologia',
      color: '#c4554d',
      session_dirs: [],
    },
  ];

  it('renders nothing when selectedCount is 0', () => {
    const { container } = render(
      <ArchiveSelectionBar
        selectedCount={0}
        totalCount={5}
        onSelectAll={vi.fn()}
        onDeselectAll={vi.fn()}
        folders={mockFolders}
        onAssignToFolder={vi.fn()}
        onNewFolder={vi.fn()}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it('renders .archive-selection-bar when items are selected and handles selection toggle', () => {
    const handleSelectAll = vi.fn();
    const handleDeselectAll = vi.fn();

    const { container, rerender } = render(
      <ArchiveSelectionBar
        selectedCount={2}
        totalCount={5}
        onSelectAll={handleSelectAll}
        onDeselectAll={handleDeselectAll}
        folders={mockFolders}
        onAssignToFolder={vi.fn()}
        onNewFolder={vi.fn()}
      />,
    );

    const bar = container.querySelector('.archive-selection-bar');
    expect(bar).toBeTruthy();

    const toggleBtn = screen.getByTitle('Seleziona tutte le 5 sbobine');
    fireEvent.click(toggleBtn);
    expect(handleSelectAll).toHaveBeenCalledTimes(1);

    // Rerender as all selected (selectedCount >= totalCount)
    rerender(
      <ArchiveSelectionBar
        selectedCount={5}
        totalCount={5}
        onSelectAll={handleSelectAll}
        onDeselectAll={handleDeselectAll}
        folders={mockFolders}
        onAssignToFolder={vi.fn()}
        onNewFolder={vi.fn()}
      />,
    );

    const deselectBtn = screen.getByTitle('Deseleziona tutte le sbobine');
    fireEvent.click(deselectBtn);
    expect(handleDeselectAll).toHaveBeenCalledTimes(1);
  });

  it('opens folder menu, displays folder-color-dot and selects a folder', () => {
    const handleAssign = vi.fn();
    const handleNewFolder = vi.fn();

    const { container } = render(
      <ArchiveSelectionBar
        selectedCount={2}
        totalCount={5}
        onSelectAll={vi.fn()}
        onDeselectAll={vi.fn()}
        folders={mockFolders}
        onAssignToFolder={handleAssign}
        onNewFolder={handleNewFolder}
      />,
    );

    const addBtn = screen.getByTitle('Aggiungi le sbobine selezionate a una cartella');
    fireEvent.click(addBtn);

    expect(screen.getByText('Cardiologia')).toBeTruthy();
    expect(screen.getByText('Neurologia')).toBeTruthy();

    // Verify folder dot has design system class
    const dots = container.querySelectorAll('.folder-color-dot.is-small');
    expect(dots.length).toBeGreaterThanOrEqual(2);

    fireEvent.click(screen.getByText('Cardiologia'));
    expect(handleAssign).toHaveBeenCalledWith('folder-1');
  });

  it('handles delete and close actions', () => {
    const handleDelete = vi.fn();
    const handleClose = vi.fn();

    render(
      <ArchiveSelectionBar
        selectedCount={3}
        totalCount={5}
        onSelectAll={vi.fn()}
        onDeselectAll={vi.fn()}
        folders={mockFolders}
        onAssignToFolder={vi.fn()}
        onNewFolder={vi.fn()}
        onDeleteSelected={handleDelete}
        onClose={handleClose}
      />,
    );

    const deleteBtn = screen.getByTitle('Elimina le sbobine selezionate dal disco');
    fireEvent.click(deleteBtn);
    expect(handleDelete).toHaveBeenCalledTimes(1);

    const closeBtn = screen.getByTitle('Annulla selezione');
    fireEvent.click(closeBtn);
    expect(handleClose).toHaveBeenCalledTimes(1);
  });
});
