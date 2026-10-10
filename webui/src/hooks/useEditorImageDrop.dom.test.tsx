import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import type { Editor as TiptapEditor } from '@tiptap/core';
import type { EditorView } from '@tiptap/pm/view';
import type { Node as ProsemirrorNode } from '@tiptap/pm/model';
import { useEditorImageDrop } from './useEditorImageDrop';
import * as utils from '../utils';

describe('useEditorImageDrop Hook', () => {
  it('initializes with handler functions', () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    expect(typeof result.current.insertImageFiles).toBe('function');
    expect(typeof result.current.handleDragStart).toBe('function');
    expect(typeof result.current.handlePaste).toBe('function');
    expect(typeof result.current.handleDrop).toBe('function');
    expect(typeof result.current.transformPastedHTML).toBe('function');
  });

  it('transforms pasted HTML removing color and background-color styles', () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    const inputHtml = '<p style="color: red; background-color: yellow; font-weight: bold;">Test text</p>';
    const outputHtml = result.current.transformPastedHTML(inputHtml);

    expect(outputHtml).not.toContain('color: red');
    expect(outputHtml).not.toContain('background-color');
    expect(outputHtml).toContain('Test text');
  });

  it('transforms pasted HTML removing font-size from headings and nested spans', () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    const inputHtml = '<h1 style="font-size: 14pt; color: red;"><span style="font-size: 11pt;">Heading Text</span></h1>';
    const outputHtml = result.current.transformPastedHTML(inputHtml);

    expect(outputHtml).not.toContain('font-size: 14pt');
    expect(outputHtml).not.toContain('font-size: 11pt');
    expect(outputHtml).not.toContain('color: red');
    expect(outputHtml).toContain('Heading Text');
  });

  it('insertImageFiles does nothing if editorRef is null or no image files passed', async () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    await result.current.insertImageFiles([]);
    const nonImageFile = new File(['hello'], 'test.txt', { type: 'text/plain' });
    await result.current.insertImageFiles([nonImageFile]);
  });

  it('insertImageFiles optimizes image and inserts floatingImage content into editor', async () => {
    const insertContentMock = vi.fn().mockReturnThis();
    const focusMock = vi.fn().mockReturnValue({ insertContent: insertContentMock });
    const runMock = vi.fn();
    insertContentMock.mockReturnValue({ run: runMock });

    const mockEditor = {
      chain: vi.fn().mockReturnValue({ focus: focusMock }),
    } as unknown as TiptapEditor;

    const editorRef = { current: mockEditor };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    const optimizeSpy = vi.spyOn(utils, 'readAndOptimizeImageAsDataUrl').mockResolvedValue('data:image/jpeg;base64,mockoptimized');

    const imageFile = new File(['binarydata'], 'photo.png', { type: 'image/png' });
    await result.current.insertImageFiles([imageFile]);

    expect(optimizeSpy).toHaveBeenCalledWith(imageFile);
    expect(insertContentMock).toHaveBeenCalledWith([
      {
        type: 'floatingImage',
        attrs: {
          src: 'data:image/jpeg;base64,mockoptimized',
          alt: 'photo.png',
          title: 'photo.png',
          width: 56,
        },
      },
    ]);
    expect(runMock).toHaveBeenCalled();
  });

  it('handlePaste returns false if no image files present in clipboard', () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    const fakeView = {} as unknown as EditorView;
    const fakeEvent = {
      clipboardData: { files: [] },
      preventDefault: vi.fn(),
    } as unknown as ClipboardEvent;

    const handled = result.current.handlePaste(fakeView, fakeEvent);
    expect(handled).toBe(false);
    expect(fakeEvent.preventDefault).not.toHaveBeenCalled();
  });

  it('handlePaste intercepts image files and prevents default', () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    const imageFile = new File(['img'], 'pic.png', { type: 'image/png' });
    const fakeView = {} as unknown as EditorView;
    const fakeEvent = {
      clipboardData: { files: [imageFile] },
      preventDefault: vi.fn(),
    } as unknown as ClipboardEvent;

    const handled = result.current.handlePaste(fakeView, fakeEvent);
    expect(handled).toBe(true);
    expect(fakeEvent.preventDefault).toHaveBeenCalled();
  });

  it('handleDrop handles file drops directly', () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    const imageFile = new File(['img'], 'drop.png', { type: 'image/png' });
    const fakeView = {} as unknown as EditorView;
    const fakeEvent = {
      dataTransfer: { files: [imageFile] },
      preventDefault: vi.fn(),
    } as unknown as DragEvent;

    const handled = result.current.handleDrop(fakeView, fakeEvent);
    expect(handled).toBe(true);
    expect(fakeEvent.preventDefault).toHaveBeenCalled();
  });

  it('handles dragstart on an editor-image-node and subsequent drop repositioning', () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    const mockImageNode = {
      type: { name: 'floatingImage' },
      nodeSize: 1,
    } as unknown as ProsemirrorNode;

    const containerEl = document.createElement('div');
    containerEl.className = 'editor-image-node';
    const childEl = document.createElement('img');
    containerEl.appendChild(childEl);
    document.body.appendChild(containerEl);

    const mockTr = {
      delete: vi.fn().mockReturnThis(),
      insert: vi.fn().mockReturnThis(),
      replaceWith: vi.fn().mockReturnThis(),
      setSelection: vi.fn().mockReturnThis(),
      doc: {
        content: { size: 100 },
      },
    };

    const mockView = {
      posAtDOM: vi.fn().mockReturnValue(10),
      posAtCoords: vi.fn().mockReturnValue({ pos: 25 }),
      nodeDOM: vi.fn().mockReturnValue(null),
      state: {
        doc: {
          nodeAt: vi.fn((pos: number) => (pos === 10 ? mockImageNode : null)),
          resolve: vi.fn().mockReturnValue({
            depth: 1,
            before: () => 20,
            after: () => 30,
            parent: { type: { name: 'paragraph' }, content: { size: 5 } },
          }),
        },
        selection: null,
        tr: mockTr,
      },
      dispatch: vi.fn(),
      focus: vi.fn(),
    } as unknown as EditorView;

    const dragEvent = {
      target: childEl,
    } as unknown as DragEvent;

    const startHandled = result.current.handleDragStart(mockView, dragEvent);
    expect(startHandled).toBe(false);

    const dropEvent = {
      dataTransfer: { files: [] },
      clientX: 100,
      clientY: 150,
      preventDefault: vi.fn(),
    } as unknown as DragEvent;

    const dropHandled = result.current.handleDrop(mockView, dropEvent);
    expect(dropHandled).toBe(true);
    expect(dropEvent.preventDefault).toHaveBeenCalled();
    expect(mockTr.delete).toHaveBeenCalledWith(10, 11);
    expect(mockTr.insert).toHaveBeenCalled();
    expect(mockView.dispatch).toHaveBeenCalledWith(mockTr);
    expect(mockView.focus).toHaveBeenCalled();

    document.body.removeChild(containerEl);
  });

  it('handleDrop falls back to Selection node check if draggedImageRef is empty', () => {
    const editorRef = { current: null };
    const { result } = renderHook(() => useEditorImageDrop({ editorRef }));

    const mockImageNode = {
      type: { name: 'floatingImage' },
      nodeSize: 1,
    } as unknown as ProsemirrorNode;

    const mockTr = {
      delete: vi.fn().mockReturnThis(),
      insert: vi.fn().mockReturnThis(),
      replaceWith: vi.fn().mockReturnThis(),
      setSelection: vi.fn().mockReturnThis(),
      doc: {
        content: { size: 100 },
      },
    };

    const mockSelection = {
      from: 5,
    };

    const mockView = {
      posAtCoords: vi.fn().mockReturnValue({ pos: 2 }),
      nodeDOM: vi.fn().mockReturnValue(null),
      state: {
        doc: {
          nodeAt: vi.fn((pos: number) => (pos === 5 ? mockImageNode : null)),
          resolve: vi.fn().mockReturnValue({ depth: 0 }),
        },
        selection: mockSelection,
        tr: mockTr,
      },
      dispatch: vi.fn(),
      focus: vi.fn(),
    } as unknown as EditorView;

    const dropEvent = {
      dataTransfer: { files: [] },
      clientX: 50,
      clientY: 50,
      preventDefault: vi.fn(),
    } as unknown as DragEvent;

    const handled = result.current.handleDrop(mockView, dropEvent);
    expect(handled).toBe(true);
    expect(mockTr.delete).toHaveBeenCalledWith(5, 6);
    expect(mockTr.insert).toHaveBeenCalledWith(2, mockImageNode);
  });
});
