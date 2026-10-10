import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MenuBar } from './EditorToolbar';
import type { Editor as TiptapEditor } from '@tiptap/core';

const createMockEditor = (canUndo = true, canRedo = true) => {
  const undoRun = vi.fn().mockReturnValue(true);
  const redoRun = vi.fn().mockReturnValue(true);

  const editor = {
    isActive: vi.fn().mockReturnValue(false),
    can: vi.fn(() => ({
      undo: () => canUndo,
      redo: () => canRedo,
    })),
    getAttributes: vi.fn().mockReturnValue({}),
    chain: vi.fn(() => ({
      focus: vi.fn().mockReturnThis(),
      undo: vi.fn(() => ({ run: undoRun })),
      redo: vi.fn(() => ({ run: redoRun })),
      toggleBold: vi.fn().mockReturnThis(),
      toggleItalic: vi.fn().mockReturnThis(),
      toggleUnderline: vi.fn().mockReturnThis(),
      toggleStrike: vi.fn().mockReturnThis(),
      unsetAllMarks: vi.fn().mockReturnThis(),
      clearNodes: vi.fn().mockReturnThis(),
      toggleBulletList: vi.fn().mockReturnThis(),
      toggleOrderedList: vi.fn().mockReturnThis(),
      toggleBlockquote: vi.fn().mockReturnThis(),
      run: vi.fn().mockReturnValue(true),
    })),
    on: vi.fn(),
    off: vi.fn(),
  };

  return { editor, undoRun, redoRun };
};

describe('EditorToolbar MenuBar', () => {
  it('renders zoom dropdown after undo/redo and before heading select', () => {
    const { editor } = createMockEditor();
    const onZoomChange = vi.fn();

    const { container } = render(
      <MenuBar
        editor={editor as unknown as TiptapEditor}
        onOpenImagePicker={vi.fn()}
        showFindReplace={false}
        onToggleFindReplace={vi.fn()}
        zoomLevel={100}
        onZoomChange={onZoomChange}
      />
    );

    const toolbar = container.querySelector('.editor-toolbar');
    expect(toolbar).not.toBeNull();

    // Check elements order
    const undoBtn = screen.getByTitle('Annulla (Ctrl+Z)');
    const redoBtn = screen.getByTitle('Ripeti (Ctrl+Y)');
    const zoomSelect = screen.getByTitle('Livello di zoom');
    const headingSelect = screen.getByTitle('Stile paragrafo');
    const findBtn = screen.getByTitle('Trova e sostituisci (Ctrl+H)');

    // Verify DOM hierarchy / ordering
    expect(undoBtn.compareDocumentPosition(redoBtn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(redoBtn.compareDocumentPosition(zoomSelect) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(zoomSelect.compareDocumentPosition(headingSelect) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(headingSelect.compareDocumentPosition(findBtn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('opens zoom dropdown and triggers onZoomChange with selected value', () => {
    const { editor } = createMockEditor();
    const onZoomChange = vi.fn();

    render(
      <MenuBar
        editor={editor as unknown as TiptapEditor}
        onOpenImagePicker={vi.fn()}
        showFindReplace={false}
        onToggleFindReplace={vi.fn()}
        zoomLevel={100}
        onZoomChange={onZoomChange}
      />
    );

    const zoomBtn = screen.getByTitle('Livello di zoom');
    expect(zoomBtn.textContent).toContain('100%');

    fireEvent.click(zoomBtn);

    const opt150 = screen.getByRole('button', { name: '150%' });
    fireEvent.click(opt150);

    expect(onZoomChange).toHaveBeenCalledWith(150);
  });

  it('renders safely and disables buttons when editor.can() lacks undo and redo functions', () => {
    const editorWithoutUndo = {
      isActive: vi.fn().mockReturnValue(false),
      can: vi.fn(() => ({})), // no undo or redo defined
      getAttributes: vi.fn().mockReturnValue({}),
      chain: vi.fn(() => ({
        focus: vi.fn().mockReturnThis(),
        run: vi.fn().mockReturnValue(true),
      })),
      on: vi.fn(),
      off: vi.fn(),
    };

    expect(() => {
      render(
        <MenuBar
          editor={editorWithoutUndo as unknown as TiptapEditor}
          onOpenImagePicker={vi.fn()}
          showFindReplace={false}
          onToggleFindReplace={vi.fn()}
        />
      );
    }).not.toThrow();

    const undoBtn = screen.getByTitle('Annulla (Ctrl+Z)') as HTMLButtonElement;
    const redoBtn = screen.getByTitle('Ripeti (Ctrl+Y)') as HTMLButtonElement;

    expect(undoBtn.disabled).toBe(true);
    expect(redoBtn.disabled).toBe(true);

    // Clicking does not crash
    expect(() => {
      fireEvent.click(undoBtn);
      fireEvent.click(redoBtn);
    }).not.toThrow();
  });
});
