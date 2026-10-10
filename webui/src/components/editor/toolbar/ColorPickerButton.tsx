import React from 'react';
import { createPortal } from 'react-dom';
import { type Editor as TiptapEditor } from '@tiptap/core';
import { ChevronDown } from 'lucide-react';

const COLOR_PALETTE: string[][] = [
  ['#000000', '#434343', '#666666', '#999999', '#b7b7b7', '#cccccc', '#d9d9d9', '#ffffff'],
  ['#ff0000', '#ff4500', '#ff9900', '#ffff00', '#00ff00', '#00ffff', '#4a86e8', '#9900ff'],
  ['#f4cccc', '#fce5cd', '#fff2cc', '#d9ead3', '#c9daf8', '#cfe2f3', '#d9d2e9', '#ead1dc'],
  ['#ea9999', '#f9cb9c', '#ffe599', '#b6d7a8', '#a4c2f4', '#9fc5e8', '#b4a7d6', '#d5a6bd'],
  ['#e06666', '#f6b26b', '#ffd966', '#93c47d', '#6d9eeb', '#6fa8dc', '#8e7cc3', '#c27ba0'],
  ['#cc0000', '#e69138', '#f1c232', '#6aa84f', '#3c78d8', '#3d85c8', '#674ea7', '#a64d79'],
  ['#990000', '#b45f06', '#bf9000', '#38761d', '#1155cc', '#0b5394', '#20124d', '#4c1130'],
];

export const ColorPickerButton = ({ editor }: { editor: TiptapEditor }) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [panelPos, setPanelPos] = React.useState({ top: 0, left: 0 });
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const currentColor: string | undefined = editor.getAttributes('textStyle').color;

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

  const applyColor = (color: string, close = true) => {
    editor.chain().focus().setColor(color).run();
    if (close) setIsOpen(false);
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        className={`editor-button color-picker-btn${isOpen ? ' is-active' : ''}`}
        title="Colore testo"
      >
        <span className="color-picker-label">
          <span style={{ fontWeight: 700, fontSize: '0.8rem', lineHeight: 1, fontFamily: 'serif' }}>A</span>
          <span
            className="color-indicator"
            style={{ background: currentColor ?? 'var(--text-primary)', opacity: currentColor ? 1 : 0.55 }}
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
          {COLOR_PALETTE.map((row, ri) => (
            <div key={ri} className="color-row">
              {row.map(color => (
                <button
                  key={color}
                  type="button"
                  onPointerDown={e => { e.preventDefault(); applyColor(color); }}
                  className={`color-swatch${currentColor === color ? ' is-selected' : ''}`}
                  style={{ background: color }}
                  title={color}
                />
              ))}
            </div>
          ))}
          <div className="color-footer">
            <button
              type="button"
              onPointerDown={e => { e.preventDefault(); editor.chain().focus().unsetColor().run(); setIsOpen(false); }}
              className="color-reset"
            >
              ✕ Rimuovi colore
            </button>
            <label className="color-custom" title="Colore personalizzato">
              <span className="color-custom-preview" style={{ background: currentColor || '#888' }} />
              Personalizzato
              <input
                type="color"
                value={currentColor || '#888888'}
                onChange={e => applyColor(e.target.value, false)}
                style={{ position: 'absolute', opacity: 0, width: 0, height: 0, pointerEvents: 'none' }}
              />
            </label>
          </div>
        </div>,
        document.body
      )}
    </>
  );
};
