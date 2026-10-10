import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { type Editor as TiptapEditor } from '@tiptap/core';
import {
  Bold, Italic, Underline as UnderlineIcon, Strikethrough,
  Highlighter, Eraser, Link2, Link2Off, Heading1, Heading2, Heading3,
  RemoveFormatting
} from 'lucide-react';
import { getLastHighlightColor } from '../editorUtils';

interface EditorBubbleMenuProps {
  editor: TiptapEditor | null;
  isContextMenuOpen?: boolean;
}

export const EditorBubbleMenu: React.FC<EditorBubbleMenuProps> = ({ editor, isContextMenuOpen = false }) => {
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);
  const [isLinkOpen, setIsLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState('');
  const isMouseDownRef = useRef(false);
  const linkBtnRef = useRef<HTMLButtonElement>(null);
  const linkInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editor) return;

    const updatePosition = () => {
      // Don't show while mouse is pressed down dragging selection
      if (isMouseDownRef.current) {
        setCoords(null);
        return;
      }

      if (
        isContextMenuOpen ||
        !editor.isFocused ||
        editor.state.selection.empty ||
        editor.isActive('image') ||
        editor.isActive('floatingImage')
      ) {
        setCoords(null);
        setIsLinkOpen(false);
        return;
      }

      const { from, to } = editor.state.selection;
      try {
        const startCoords = editor.view.coordsAtPos(from);
        const endCoords = editor.view.coordsAtPos(to);
        const rawTop = Math.min(startCoords.top, endCoords.top) - 52;
        const rawLeft = (startCoords.left + endCoords.left) / 2;

      const paperEl = editor.view.dom.closest('.editor-page') || document.body;
        const paperRect = paperEl.getBoundingClientRect();
        const containerEl = editor.view.dom.closest('.editor-page-container');
        if (containerEl) {
          const containerRect = containerEl.getBoundingClientRect();
          if (startCoords.top < containerRect.top - 20 || endCoords.bottom > containerRect.bottom + 20) {
            setCoords(null);
            return;
          }
        }

        // Clamp left coordinate so bubble menu is 100% visible without overflowing off-screen
        const menuHalfWidth = 180;
        const minLeft = Math.max(paperRect.left + menuHalfWidth + 12, menuHalfWidth + 12);
        const maxLeft = Math.min(paperRect.right - menuHalfWidth - 12, window.innerWidth - menuHalfWidth - 12);
        const clampedLeft = Math.max(minLeft, Math.min(maxLeft, rawLeft));
        const clampedTop = Math.max(12, rawTop);

        setCoords({ top: clampedTop, left: clampedLeft });
      } catch (_) {
        setCoords(null);
      }
    };

    const handleMouseDown = (e: MouseEvent) => {
      const target = e.target as Element;
      if (target?.closest?.('.editor-bubble-menu') || target?.closest?.('.link-panel')) {
        return;
      }
      isMouseDownRef.current = true;
      setCoords(null);
      setIsLinkOpen(false);
    };

    let mouseUpTimer: ReturnType<typeof setTimeout> | null = null;
    let blurTimer: ReturnType<typeof setTimeout> | null = null;

    const handleMouseUp = () => {
      isMouseDownRef.current = false;
      if (mouseUpTimer) clearTimeout(mouseUpTimer);
      // Delay slightly so ProseMirror updates selection state
      mouseUpTimer = setTimeout(updatePosition, 20);
    };

    const handleScroll = () => {
      setCoords(null);
      setIsLinkOpen(false);
    };

    const handleBlur = () => {
      if (blurTimer) clearTimeout(blurTimer);
      blurTimer = setTimeout(() => {
        if (
          !document.activeElement?.closest('.editor-bubble-menu') &&
          !document.activeElement?.closest('.link-panel')
        ) {
          setCoords(null);
          setIsLinkOpen(false);
        }
      }, 150);
    };

    window.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mouseup', handleMouseUp);
    window.addEventListener('scroll', handleScroll, true);
    editor.on('selectionUpdate', updatePosition);
    editor.on('blur', handleBlur);

    updatePosition();

    return () => {
      if (mouseUpTimer) clearTimeout(mouseUpTimer);
      if (blurTimer) clearTimeout(blurTimer);
      window.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mouseup', handleMouseUp);
      window.removeEventListener('scroll', handleScroll, true);
      editor.off('selectionUpdate', updatePosition);
      editor.off('blur', handleBlur);
    };
  }, [editor, isContextMenuOpen]);

  if (!editor || !coords) return null;

  const btn = (active: boolean) => `editor-bubble-btn${active ? ' is-active' : ''}`;

  const { from, to } = editor.state.selection;
  const hasHighlight =
    editor.isActive('highlight') ||
    Boolean(editor.schema?.marks?.highlight && editor.state?.doc?.rangeHasMark?.(from, to, editor.schema.marks.highlight));

  const activeHighlightColor = editor.getAttributes('highlight').color || getLastHighlightColor();

  const toggleLink = () => {
    if (editor.isActive('link')) {
      editor.chain().focus().unsetLink().run();
      return;
    }
    setLinkUrl(editor.getAttributes('link').href ?? '');
    setIsLinkOpen(prev => !prev);
    setTimeout(() => linkInputRef.current?.focus(), 50);
  };

  const applyLink = () => {
    if (linkUrl.trim()) {
      const href = linkUrl.startsWith('http') ? linkUrl : `https://${linkUrl}`;
      editor.chain().focus().setLink({ href }).run();
    }
    setIsLinkOpen(false);
  };

  return createPortal(
    <div
      className="editor-bubble-menu-wrapper"
      style={{
        position: 'fixed',
        top: coords.top,
        left: coords.left,
        transform: 'translateX(-50%)',
        zIndex: 9999,
        pointerEvents: 'auto',
      }}
    >
      <div className="editor-bubble-menu">
        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); editor.chain().focus().toggleBold().run(); }}
          className={btn(editor.isActive('bold'))}
          title="Grassetto (Ctrl+B)"
        >
          <Bold className="h-3.5 w-3.5 shrink-0" />
        </button>

        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); editor.chain().focus().toggleItalic().run(); }}
          className={btn(editor.isActive('italic'))}
          title="Corsivo (Ctrl+I)"
        >
          <Italic className="h-3.5 w-3.5 shrink-0" />
        </button>

        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); editor.chain().focus().toggleUnderline().run(); }}
          className={btn(editor.isActive('underline'))}
          title="Sottolineato (Ctrl+U)"
        >
          <UnderlineIcon className="h-3.5 w-3.5 shrink-0" />
        </button>

        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); editor.chain().focus().toggleStrike().run(); }}
          className={btn(editor.isActive('strike'))}
          title="Barrato"
        >
          <Strikethrough className="h-3.5 w-3.5 shrink-0" />
        </button>

        <button
          type="button"
          onMouseDown={e => {
            e.preventDefault();
            if (editor.isActive('highlight')) {
              editor.chain().focus().unsetHighlight().run();
            } else {
              const colorToUse = getLastHighlightColor();
              editor.chain().focus().toggleHighlight({ color: colorToUse }).run();
            }
          }}
          className={btn(editor.isActive('highlight'))}
          title="Evidenzia testo"
        >
          <span className="relative inline-flex items-center justify-center">
            <Highlighter className="h-3.5 w-3.5 shrink-0" />
            <span
              className="absolute -bottom-1 left-0 right-0 h-[2.5px] rounded-full"
              style={{ background: activeHighlightColor }}
            />
          </span>
        </button>

        {hasHighlight && (
          <button
            type="button"
            onMouseDown={e => {
              e.preventDefault();
              editor.chain().focus().unsetHighlight().run();
            }}
            className="editor-bubble-btn"
            title="Rimuovi evidenziatura"
          >
            <Eraser className="h-3.5 w-3.5 shrink-0" />
          </button>
        )}

        <div className="editor-bubble-divider" />

        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); editor.chain().focus().clearBlockFontSize().toggleHeading({ level: 1 }).run(); }}
          className={btn(editor.isActive('heading', { level: 1 }))}
          title="Titolo 1"
        >
          <Heading1 className="h-3.5 w-3.5 shrink-0" />
        </button>

        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); editor.chain().focus().clearBlockFontSize().toggleHeading({ level: 2 }).run(); }}
          className={btn(editor.isActive('heading', { level: 2 }))}
          title="Titolo 2"
        >
          <Heading2 className="h-3.5 w-3.5 shrink-0" />
        </button>

        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); editor.chain().focus().clearBlockFontSize().toggleHeading({ level: 3 }).run(); }}
          className={btn(editor.isActive('heading', { level: 3 }))}
          title="Titolo 3"
        >
          <Heading3 className="h-3.5 w-3.5 shrink-0" />
        </button>

        <div className="editor-bubble-divider" />

        <button
          ref={linkBtnRef}
          type="button"
          onMouseDown={e => { e.preventDefault(); toggleLink(); }}
          className={btn(editor.isActive('link'))}
          title="Inserisci link (Ctrl+K)"
        >
          {editor.isActive('link') ? (
            <Link2Off className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <Link2 className="h-3.5 w-3.5 shrink-0" />
          )}
        </button>

        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); editor.chain().focus().unsetAllMarks().run(); }}
          className="editor-bubble-btn"
          title="Rimuovi formattazione"
        >
          <RemoveFormatting className="h-3.5 w-3.5 shrink-0" />
        </button>
      </div>

      {isLinkOpen && (
        <div
          className="link-panel"
          style={{
            position: 'absolute',
            top: 44,
            left: 0,
            zIndex: 9999,
          }}
        >
          <input
            ref={linkInputRef}
            type="url"
            placeholder="https://..."
            value={linkUrl}
            onChange={e => setLinkUrl(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') applyLink();
              if (e.key === 'Escape') setIsLinkOpen(false);
            }}
            className="link-input"
          />
          <button type="button" onClick={applyLink} className="link-apply-btn">
            Applica
          </button>
        </div>
      )}
    </div>,
    document.body
  );
};
