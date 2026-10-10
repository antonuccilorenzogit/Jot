import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { EditorBubbleMenu } from './EditorBubbleMenu';
import type { Editor as TiptapEditor } from '@tiptap/core';

type ListenerFn = (...args: unknown[]) => void;

const createMockEditor = (overrideProps: Record<string, unknown> = {}) => {
  const eventListeners: Record<string, ListenerFn[]> = {};

  const runMock = vi.fn().mockReturnValue(true);
  const chainMock = {
    focus: vi.fn().mockReturnThis(),
    toggleBold: vi.fn().mockReturnThis(),
    toggleItalic: vi.fn().mockReturnThis(),
    toggleUnderline: vi.fn().mockReturnThis(),
    toggleStrike: vi.fn().mockReturnThis(),
    toggleHighlight: vi.fn().mockReturnThis(),
    unsetHighlight: vi.fn().mockReturnThis(),
    clearBlockFontSize: vi.fn().mockReturnThis(),
    toggleHeading: vi.fn().mockReturnThis(),
    setLink: vi.fn().mockReturnThis(),
    unsetLink: vi.fn().mockReturnThis(),
    unsetAllMarks: vi.fn().mockReturnThis(),
    run: runMock,
  };

  const editor = {
    isFocused: true,
    state: {
      selection: {
        empty: false,
        from: 1,
        to: 10,
      },
    },
    isActive: vi.fn().mockReturnValue(false),
    getAttributes: vi.fn().mockReturnValue({}),
    view: {
      dom: {
        closest: vi.fn().mockReturnValue({
          getBoundingClientRect: () => ({ left: 0, top: 0, right: 800, bottom: 1000, width: 800, height: 1000 }),
        }),
      },
      coordsAtPos: vi.fn().mockReturnValue({ top: 100, left: 200 }),
    },
    on: vi.fn((event: string, fn: ListenerFn) => {
      if (!eventListeners[event]) eventListeners[event] = [];
      eventListeners[event].push(fn);
    }),
    off: vi.fn((event: string, fn: ListenerFn) => {
      if (eventListeners[event]) {
        eventListeners[event] = eventListeners[event].filter(f => f !== fn);
      }
    }),
    chain: vi.fn().mockReturnValue(chainMock),
    emit: (event: string) => {
      act(() => {
        eventListeners[event]?.forEach(fn => fn());
      });
    },
    ...overrideProps,
  };

  return { editor, chainMock };
};

describe('EditorBubbleMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.getBoundingClientRect = vi.fn().mockReturnValue({
      left: 0,
      top: 0,
      right: 1024,
      bottom: 768,
      width: 1024,
      height: 768,
    });
  });

  it('renders null when editor is null', () => {
    const { container } = render(<EditorBubbleMenu editor={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders bubble menu when selection is active', () => {
    const { editor } = createMockEditor();
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);

    editor.emit('selectionUpdate');

    expect(screen.getByTitle('Grassetto (Ctrl+B)')).toBeTruthy();
    expect(screen.getByTitle('Corsivo (Ctrl+I)')).toBeTruthy();
    expect(screen.getByTitle('Sottolineato (Ctrl+U)')).toBeTruthy();
    expect(screen.getByTitle('Barrato')).toBeTruthy();
    expect(screen.getByTitle('Evidenzia testo')).toBeTruthy();
    expect(screen.getByTitle('Titolo 1')).toBeTruthy();
    expect(screen.getByTitle('Titolo 2')).toBeTruthy();
    expect(screen.getByTitle('Titolo 3')).toBeTruthy();
    expect(screen.getByTitle('Inserisci link (Ctrl+K)')).toBeTruthy();
    expect(screen.getByTitle('Rimuovi formattazione')).toBeTruthy();
  });

  it('toggles bold mark on click', () => {
    const { editor, chainMock } = createMockEditor();
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    const boldBtn = screen.getByTitle('Grassetto (Ctrl+B)');
    act(() => {
      fireEvent.mouseDown(boldBtn);
    });

    expect(chainMock.toggleBold).toHaveBeenCalled();
    expect(chainMock.run).toHaveBeenCalled();
  });

  it('toggles highlight color on click', () => {
    const { editor, chainMock } = createMockEditor();
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    const highlightBtn = screen.getByTitle('Evidenzia testo');
    act(() => {
      fireEvent.mouseDown(highlightBtn);
    });

    expect(chainMock.toggleHighlight).toHaveBeenCalled();
  });

  it('unsets highlight if highlight is active', () => {
    const { editor, chainMock } = createMockEditor({
      isActive: vi.fn((name: string) => name === 'highlight'),
    });
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    const highlightBtn = screen.getByTitle('Evidenzia testo');
    act(() => {
      fireEvent.mouseDown(highlightBtn);
    });

    expect(chainMock.unsetHighlight).toHaveBeenCalled();
  });

  it('renders remove highlight button when highlight mark is in selection range and unsets on click', () => {
    const rangeHasMarkMock = vi.fn().mockReturnValue(true);
    const { editor, chainMock } = createMockEditor({
      isActive: vi.fn().mockReturnValue(false),
      state: {
        selection: { empty: false, from: 2, to: 8 },
        doc: { rangeHasMark: rangeHasMarkMock },
      },
      schema: {
        marks: { highlight: {} },
      },
    });

    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    const removeBtn = screen.getByTitle('Rimuovi evidenziatura');
    expect(removeBtn).toBeTruthy();

    act(() => {
      fireEvent.mouseDown(removeBtn);
    });

    expect(chainMock.unsetHighlight).toHaveBeenCalled();
  });

  it('does not render remove highlight button when selection has no highlight', () => {
    const rangeHasMarkMock = vi.fn().mockReturnValue(false);
    const { editor } = createMockEditor({
      isActive: vi.fn().mockReturnValue(false),
      state: {
        selection: { empty: false, from: 2, to: 8 },
        doc: { rangeHasMark: rangeHasMarkMock },
      },
      schema: {
        marks: { highlight: {} },
      },
    });

    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    expect(screen.queryByTitle('Rimuovi evidenziatura')).toBeNull();
  });

  it('toggles heading level 1', () => {
    const { editor, chainMock } = createMockEditor();
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    act(() => {
      fireEvent.mouseDown(screen.getByTitle('Titolo 1'));
    });
    expect(chainMock.clearBlockFontSize).toHaveBeenCalled();
    expect(chainMock.toggleHeading).toHaveBeenCalledWith({ level: 1 });
  });

  it('toggles heading level 2', () => {
    const { editor, chainMock } = createMockEditor();
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    act(() => {
      fireEvent.mouseDown(screen.getByTitle('Titolo 2'));
    });
    expect(chainMock.clearBlockFontSize).toHaveBeenCalled();
    expect(chainMock.toggleHeading).toHaveBeenCalledWith({ level: 2 });
  });

  it('toggles heading level 3', () => {
    const { editor, chainMock } = createMockEditor();
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    act(() => {
      fireEvent.mouseDown(screen.getByTitle('Titolo 3'));
    });
    expect(chainMock.clearBlockFontSize).toHaveBeenCalled();
    expect(chainMock.toggleHeading).toHaveBeenCalledWith({ level: 3 });
  });

  it('handles link panel toggle and apply', () => {
    const { editor, chainMock } = createMockEditor();
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    const linkBtn = screen.getByTitle('Inserisci link (Ctrl+K)');
    act(() => {
      fireEvent.mouseDown(linkBtn);
    });

    const input = screen.getByPlaceholderText('https://...');
    expect(input).toBeTruthy();

    act(() => {
      fireEvent.change(input, { target: { value: 'example.com' } });
      fireEvent.click(screen.getByText('Applica'));
    });

    expect(chainMock.setLink).toHaveBeenCalledWith({ href: 'https://example.com' });
  });

  it('unsets link if link is active', () => {
    const { editor, chainMock } = createMockEditor({
      isActive: vi.fn((name: string) => name === 'link'),
      getAttributes: vi.fn().mockReturnValue({ href: 'https://example.com' }),
    });
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    const linkBtn = screen.getByTitle('Inserisci link (Ctrl+K)');
    act(() => {
      fireEvent.mouseDown(linkBtn);
    });

    expect(chainMock.unsetLink).toHaveBeenCalled();
  });

  it('removes all formatting on click', () => {
    const { editor, chainMock } = createMockEditor();
    render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);
    editor.emit('selectionUpdate');

    act(() => {
      fireEvent.mouseDown(screen.getByTitle('Rimuovi formattazione'));
    });
    expect(chainMock.unsetAllMarks).toHaveBeenCalled();
  });

  it('unsubscribes listeners on unmount', () => {
    const { editor } = createMockEditor();
    const { unmount } = render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} />);

    expect(editor.on).toHaveBeenCalledWith('selectionUpdate', expect.any(Function));
    expect(editor.on).toHaveBeenCalledWith('blur', expect.any(Function));

    unmount();

    expect(editor.off).toHaveBeenCalledWith('selectionUpdate', expect.any(Function));
    expect(editor.off).toHaveBeenCalledWith('blur', expect.any(Function));
  });

  it('hides bubble menu when isContextMenuOpen is true', () => {
    const { editor } = createMockEditor();
    const { rerender } = render(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} isContextMenuOpen={false} />);
    editor.emit('selectionUpdate');

    expect(screen.getByTitle('Grassetto (Ctrl+B)')).toBeTruthy();

    rerender(<EditorBubbleMenu editor={editor as unknown as TiptapEditor} isContextMenuOpen={true} />);

    expect(screen.queryByTitle('Grassetto (Ctrl+B)')).toBeNull();
  });
});
