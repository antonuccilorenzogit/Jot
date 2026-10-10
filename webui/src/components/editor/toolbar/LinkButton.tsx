import React from 'react';
import { createPortal } from 'react-dom';
import { type Editor as TiptapEditor } from '@tiptap/core';
import { Link2, Link2Off } from 'lucide-react';

export const LinkButton = ({ editor }: { editor: TiptapEditor }) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [url, setUrl] = React.useState('');
  const [panelPos, setPanelPos] = React.useState({ top: 0, left: 0 });
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const isActive = editor.isActive('link');

  const openPanel = () => {
    if (isActive) {
      editor.chain().focus().unsetLink().run();
      return;
    }
    setUrl(editor.getAttributes('link').href ?? '');
    if (buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      setPanelPos({ top: rect.bottom + 6, left: rect.left });
    }
    setIsOpen(true);
    setTimeout(() => inputRef.current?.focus(), 50);
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

  const applyLink = () => {
    if (!url.trim()) return;
    const href = url.startsWith('http') ? url : `https://${url}`;
    editor.chain().focus().setLink({ href }).run();
    setIsOpen(false);
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={openPanel}
        className={`editor-button${isActive ? ' is-active' : ''}`}
        title={isActive ? 'Rimuovi link' : 'Inserisci link'}
      >
        {isActive ? <Link2Off className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
      </button>
      {isOpen && createPortal(
        <div
          ref={panelRef}
          className="link-panel"
          style={{ position: 'fixed', top: panelPos.top, left: panelPos.left, zIndex: 9999 }}
        >
          <input
            ref={inputRef}
            type="url"
            placeholder="https://..."
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') applyLink();
              if (e.key === 'Escape') { e.stopPropagation(); setIsOpen(false); }
            }}
            className="link-input"
          />
          <button type="button" onClick={applyLink} className="link-apply-btn">Applica</button>
        </div>,
        document.body
      )}
    </>
  );
};
