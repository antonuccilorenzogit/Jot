import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EditorContextMenu } from './EditorContextMenu';
import type { Editor as TiptapEditor } from '@tiptap/core';

describe('EditorContextMenu', () => {
  it('does not render when contextMenu is null', () => {
    const { container } = render(
      <EditorContextMenu
        contextMenu={null}
        onClose={vi.fn()}
        editor={null}
        onOpenImagePicker={vi.fn()}
        onOpenFind={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders menu items when position and editor are provided', () => {
    const onClose = vi.fn();
    const onOpenFind = vi.fn();
    const mockEditor = {
      state: { selection: { empty: true, from: 0, to: 0 }, doc: { textBetween: () => '' } },
      chain: () => ({
        focus: () => ({
          toggleBold: () => ({ run: vi.fn() }),
        }),
      }),
      commands: { insertContent: vi.fn() },
    } as unknown as TiptapEditor;

    render(
      <EditorContextMenu
        contextMenu={{ x: 100, y: 100 }}
        onClose={onClose}
        editor={mockEditor}
        onOpenImagePicker={vi.fn()}
        onOpenFind={onOpenFind}
      />,
    );

    expect(screen.getByText('Taglia')).toBeTruthy();
    expect(screen.getByText('Copia')).toBeTruthy();
    expect(screen.getByText('Grassetto')).toBeTruthy();
    expect(screen.getByText('Trova e sostituisci')).toBeTruthy();

    const findBtn = screen.getByText('Trova e sostituisci').closest('button');
    if (findBtn) fireEvent.click(findBtn);
    expect(onOpenFind).toHaveBeenCalled();
  });

  it('handles Copia and Taglia clicks gracefully', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock, write: vi.fn().mockResolvedValue(undefined) },
      writable: true,
      configurable: true,
    });

    const deleteSelectionMock = vi.fn().mockReturnValue({ run: vi.fn() });
    const mockEditor = {
      state: {
        selection: { empty: false, from: 0, to: 5, content: () => ({ content: [] }) },
        doc: { textBetween: () => 'Hello' },
      },
      schema: {},
      chain: () => ({
        focus: () => ({
          deleteSelection: deleteSelectionMock,
        }),
      }),
      commands: { insertContent: vi.fn() },
    } as unknown as TiptapEditor;

    render(
      <EditorContextMenu
        contextMenu={{ x: 50, y: 50 }}
        onClose={vi.fn()}
        editor={mockEditor}
        onOpenImagePicker={vi.fn()}
        onOpenFind={vi.fn()}
      />,
    );

    const copyBtn = screen.getByText('Copia').closest('button');
    if (copyBtn) fireEvent.click(copyBtn);

    const cutBtn = screen.getByText('Taglia').closest('button');
    if (cutBtn) fireEvent.click(cutBtn);
  });
});
