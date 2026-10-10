import { reportClientError } from '../diagnostics';
import { useCallback, useRef } from 'react';
import type { EditorView } from '@tiptap/pm/view';
import type { Node as ProsemirrorNode } from '@tiptap/pm/model';
import { NodeSelection } from '@tiptap/pm/state';
import type { Editor as TiptapEditor } from '@tiptap/core';
import { readAndOptimizeImageAsDataUrl } from '../utils';

interface UseEditorImageDropOptions {
  editorRef: React.MutableRefObject<TiptapEditor | null>;
}

export function useEditorImageDrop({ editorRef }: UseEditorImageDropOptions) {
  const draggedImageRef = useRef<{ pos: number; size: number; node: ProsemirrorNode } | null>(null);

  const insertImageFiles = useCallback(async (inputFiles: FileList | File[]) => {
    const activeEditor = editorRef.current;
    if (!activeEditor) return;
    const files = Array.from(inputFiles).filter(f => f.type.startsWith('image/'));
    if (!files.length) return;
    for (const file of files) {
      try {
        const src = await readAndOptimizeImageAsDataUrl(file);
        activeEditor.chain().focus().insertContent([
          { type: 'floatingImage', attrs: { src, alt: file.name, title: file.name, width: 56 } },
        ]).run();
      } catch (err) {
        reportClientError(`Errore durante la lettura dell'immagine ${file.name}:`, err);
      }
    }
  }, [editorRef]);

  const handleDragStart = useCallback((view: EditorView, event: DragEvent): boolean => {
    const target = event.target as HTMLElement | null;
    const imageNodeView = target?.closest('.editor-image-node') as HTMLElement | null;
    if (imageNodeView) {
      try {
        const pos = view.posAtDOM(imageNodeView, 0);
        if (pos !== null && pos !== undefined) {
          const node = view.state.doc.nodeAt(pos);
          if (node && node.type.name === 'floatingImage') {
            draggedImageRef.current = { pos, size: node.nodeSize, node };
          }
        }
      } catch (_) {
        draggedImageRef.current = null;
      }
    }
    return false;
  }, []);

  const handlePaste = useCallback((_view: EditorView, event: ClipboardEvent): boolean => {
    const files = Array.from(event.clipboardData?.files || []).filter(f => f.type.startsWith('image/'));
    if (!files.length) return false;
    event.preventDefault();
    void insertImageFiles(files);
    return true;
  }, [insertImageFiles]);

  const handleDrop = useCallback((view: EditorView, event: DragEvent): boolean => {
    const files = Array.from(event.dataTransfer?.files || []).filter(f => f.type.startsWith('image/'));
    if (files.length) {
      event.preventDefault();
      void insertImageFiles(files);
      return true;
    }

    let dragged = draggedImageRef.current;
    draggedImageRef.current = null;

    if (!dragged) {
      const sel = view.state.selection;
      if (sel instanceof NodeSelection && sel.node.type.name === 'floatingImage') {
        dragged = { pos: sel.from, size: sel.node.nodeSize, node: sel.node };
      } else if (sel) {
        const nodeAtFrom = view.state.doc.nodeAt(sel.from);
        if (nodeAtFrom?.type.name === 'floatingImage') {
          dragged = { pos: sel.from, size: nodeAtFrom.nodeSize, node: nodeAtFrom };
        }
      }
    }

    if (dragged && dragged.node) {
      event.preventDefault();
      const dropCoords = view.posAtCoords({ left: event.clientX, top: event.clientY });
      if (!dropCoords) return true;

      const dragFrom = dragged.pos;
      const dragSize = dragged.size;
      const dragTo = dragFrom + dragSize;

      let insertPos = dropCoords.pos;
      let isTargetEmptyParagraph = false;
      let targetPStart = 0;
      let targetPEnd = 0;

      try {
        const $target = view.state.doc.resolve(dropCoords.pos);
        if ($target.depth >= 1) {
          targetPStart = $target.before(1);
          targetPEnd = $target.after(1);

          const targetParent = $target.parent;
          if (targetParent && targetParent.type.name === 'paragraph' && targetParent.content.size === 0) {
            isTargetEmptyParagraph = true;
          }

          const targetDOM = view.nodeDOM(targetPStart) as HTMLElement | null;
          if (targetDOM && typeof targetDOM.getBoundingClientRect === 'function') {
            const rect = targetDOM.getBoundingClientRect();
            if (event.clientY > rect.top + rect.height / 2) {
              insertPos = targetPEnd;
            } else {
              insertPos = targetPStart;
            }
          } else {
            insertPos = targetPStart;
          }
        }
      } catch (_) {
        insertPos = dropCoords.pos;
      }

      if (insertPos >= dragFrom && insertPos <= dragTo) {
        return true;
      }

      const tr = view.state.tr;
      let selPos = 0;
      if (isTargetEmptyParagraph && targetPStart !== undefined && targetPEnd !== undefined) {
        if (dragFrom < targetPStart) {
          tr.replaceWith(targetPStart, targetPEnd, dragged.node);
          tr.delete(dragFrom, dragFrom + dragSize);
          selPos = Math.max(0, targetPStart - dragSize);
        } else {
          tr.delete(dragFrom, dragTo);
          tr.replaceWith(targetPStart, targetPEnd, dragged.node);
          selPos = targetPStart;
        }
      } else {
        tr.delete(dragFrom, dragTo);
        let finalInsertPos = insertPos;
        if (insertPos > dragFrom) {
          finalInsertPos = Math.max(0, insertPos - dragSize);
        }
        tr.insert(finalInsertPos, dragged.node);
        selPos = finalInsertPos;
      }

      if (typeof selPos === 'number' && selPos >= 0 && selPos < tr.doc.content.size) {
        try {
          tr.setSelection(NodeSelection.create(tr.doc, selPos));
        } catch (_) {}
      }

      view.dispatch(tr);
      view.focus();
      return true;
    }

    return false;
  }, [insertImageFiles]);

  const transformPastedHTML = useCallback((html: string): string => {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.body.querySelectorAll('[style]').forEach(el => {
      const s = (el as HTMLElement).style;
      s.removeProperty('color');
      s.removeProperty('background-color');
    });
    doc.body.querySelectorAll('h1, h2, h3, h4, h5, h6, h1 *, h2 *, h3 *, h4 *, h5 *, h6 *').forEach(el => {
      (el as HTMLElement).style?.removeProperty('font-size');
    });
    return doc.body.innerHTML;
  }, []);

  return {
    insertImageFiles,
    handleDragStart,
    handlePaste,
    handleDrop,
    transformPastedHTML,
  };
}
