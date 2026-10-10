import React from 'react';
import { createPortal } from 'react-dom';
import { type Editor as TiptapEditor } from '@tiptap/core';
import { ChevronDown } from 'lucide-react';
import { getLastHighlightColor, setLastHighlightColor } from '../../../editorUtils';

const HIGHLIGHT_COLORS = [
  { label: 'Giallo', color: '#fef08a' },
  { label: 'Verde', color: '#bbf7d0' },
  { label: 'Azzurro', color: '#bae6fd' },
  { label: 'Rosa', color: '#fecdd3' },
  { label: 'Arancione', color: '#fed7aa' },
  { label: 'Viola', color: '#e9d5ff' },
  { label: 'Nessuno', color: '#ffffff' },
];

export const HighlightPickerButton = ({ editor }: { editor: TiptapEditor }) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [panelPos, setPanelPos] = React.useState({ top: 0, left: 0 });
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const currentColor: string | undefined = editor.getAttributes('highlight').color;
  const activeColor = currentColor ?? getLastHighlightColor();

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

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        className={`editor-button color-picker-btn${isOpen || editor.isActive('highlight') ? ' is-active' : ''}`}
        title="Evidenziatore"
      >
        <span className="color-picker-label">
          <span style={{ fontWeight: 700, fontSize: '0.8rem', lineHeight: 1 }}>H</span>
          <span
            className="color-indicator"
            style={{ background: activeColor, opacity: 0.9 }}
          />
        </span>
        <ChevronDown size={9} style={{ opacity: 0.55, flexShrink: 0 }} />
      </button>
      {isOpen && createPortal(
        <div
          ref={panelRef}
          className="color-picker-panel"
          style={{ position: 'fixed', top: panelPos.top, left: panelPos.left, zIndex: 9999 }}
        >
          <div className="color-row" style={{ flexWrap: 'wrap', gap: 5 }}>
            {HIGHLIGHT_COLORS.map(({ label, color }) => (
              <button
                key={color}
                type="button"
                onPointerDown={e => {
                  e.preventDefault();
                  if (color === '#ffffff') {
                    editor.chain().focus().unsetHighlight().run();
                  } else {
                    setLastHighlightColor(color);
                    editor.chain().focus().toggleHighlight({ color }).run();
                  }
                  setIsOpen(false);
                }}
                className={`color-swatch${currentColor === color ? ' is-selected' : ''}`}
                style={{ background: color, border: color === '#ffffff' ? '1px solid #ccc' : undefined }}
                title={label}
              />
            ))}
          </div>
          <div className="color-footer" style={{ justifyContent: 'flex-start' }}>
            <button
              type="button"
              onPointerDown={e => { e.preventDefault(); editor.chain().focus().unsetHighlight().run(); setIsOpen(false); }}
              className="color-reset"
            >
              ✕ Rimuovi evidenziatore
            </button>
          </div>
        </div>,
        document.body
      )}
    </>
  );
};
