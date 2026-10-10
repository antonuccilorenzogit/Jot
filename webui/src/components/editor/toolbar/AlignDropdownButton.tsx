import React from 'react';
import { createPortal } from 'react-dom';
import { type Editor as TiptapEditor } from '@tiptap/core';
import { AlignCenter, AlignJustify, AlignLeft, AlignRight, ChevronDown } from 'lucide-react';

export const AlignDropdownButton = ({ editor }: { editor: TiptapEditor }) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [panelPos, setPanelPos] = React.useState({ top: 0, left: 0 });
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

  const isCenter = editor.isActive({ textAlign: 'center' });
  const isRight = editor.isActive({ textAlign: 'right' });
  const isJustify = editor.isActive({ textAlign: 'justify' });

  const toggleOpen = () => {
    if (!isOpen && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      setPanelPos({ top: rect.bottom + 6, left: rect.left });
    }
    setIsOpen(prev => !prev);
  };

  React.useEffect(() => {
    if (!isOpen) return;
    const handler = (e: PointerEvent | MouseEvent) => {
      const target = e.target as Node;
      if (buttonRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      setIsOpen(false);
    };
    document.addEventListener('pointerdown', handler, true);
    document.addEventListener('mousedown', handler, true);
    return () => {
      document.removeEventListener('pointerdown', handler, true);
      document.removeEventListener('mousedown', handler, true);
    };
  }, [isOpen]);

  const CurrentIcon = isCenter ? AlignCenter : isRight ? AlignRight : isJustify ? AlignJustify : AlignLeft;

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        className={`editor-button align-dropdown-btn${isOpen ? ' is-active' : ''}`}
        title="Allineamento testo"
      >
        <CurrentIcon className="h-4 w-4" />
        <ChevronDown size={9} style={{ opacity: 0.6, marginLeft: 2 }} />
      </button>
      {isOpen && createPortal(
        <div
          ref={panelRef}
          className="editor-dropdown-panel"
          style={{ position: 'fixed', top: panelPos.top, left: panelPos.left, zIndex: 9999 }}
        >
          <button
            type="button"
            className={`editor-dropdown-item${!isCenter && !isRight && !isJustify ? ' is-active' : ''}`}
            onClick={() => { setIsOpen(false); editor.chain().focus().setTextAlign('left').run(); }}
          >
            <AlignLeft className="h-4 w-4" />
            <span>A sinistra</span>
          </button>
          <button
            type="button"
            className={`editor-dropdown-item${isCenter ? ' is-active' : ''}`}
            onClick={() => { setIsOpen(false); editor.chain().focus().setTextAlign('center').run(); }}
          >
            <AlignCenter className="h-4 w-4" />
            <span>Al centro</span>
          </button>
          <button
            type="button"
            className={`editor-dropdown-item${isRight ? ' is-active' : ''}`}
            onClick={() => { setIsOpen(false); editor.chain().focus().setTextAlign('right').run(); }}
          >
            <AlignRight className="h-4 w-4" />
            <span>A destra</span>
          </button>
          <button
            type="button"
            className={`editor-dropdown-item${isJustify ? ' is-active' : ''}`}
            onClick={() => { setIsOpen(false); editor.chain().focus().setTextAlign('justify').run(); }}
          >
            <AlignJustify className="h-4 w-4" />
            <span>Giustificato</span>
          </button>
        </div>,
        document.body
      )}
    </>
  );
};
