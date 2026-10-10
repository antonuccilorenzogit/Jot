import React from 'react';
import { createPortal } from 'react-dom';
import { type Editor as TiptapEditor } from '@tiptap/core';
import { ChevronDown } from 'lucide-react';

const FONT_FAMILIES = [
  { label: 'Arial', value: '', cssFamily: 'Arial, sans-serif' },
  { label: 'Times New Roman', value: '"Times New Roman", serif', cssFamily: '"Times New Roman", serif' },
  { label: 'Georgia', value: 'Georgia, serif', cssFamily: 'Georgia, serif' },
  { label: 'Courier New', value: '"Courier New", monospace', cssFamily: '"Courier New", monospace' },
  { label: 'Verdana', value: 'Verdana, sans-serif', cssFamily: 'Verdana, sans-serif' },
  { label: 'Trebuchet MS', value: '"Trebuchet MS", sans-serif', cssFamily: '"Trebuchet MS", sans-serif' },
];

const FONT_SIZES = ['8', '9', '10', '11', '12', '14', '16', '18', '20', '24', '28', '32', '36', '48', '72'];

const HEADING_OPTIONS = [
  { label: 'Testo normale', value: 'paragraph', level: 0 },
  { label: 'Titolo 1', value: 'h1', level: 1 },
  { label: 'Titolo 2', value: 'h2', level: 2 },
  { label: 'Titolo 3', value: 'h3', level: 3 },
  { label: 'Titolo 4', value: 'h4', level: 4 },
  { label: 'Titolo 5', value: 'h5', level: 5 },
];

// Matches CSS: h1=20pt, h2=16pt, h3=14pt, h4=11pt, h5=10pt (same as HTML export)
const HEADING_PT: Record<number, number> = { 1: 20, 2: 16, 3: 14, 4: 11, 5: 10 };

export const FontFamilySelect = ({ editor }: { editor: TiptapEditor }) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [panelPos, setPanelPos] = React.useState({ top: 0, left: 0 });
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

  const rawFamily = editor.getAttributes('textStyle').fontFamily ?? '';
  const currentFamily = (rawFamily === '' || rawFamily === 'Arial, sans-serif' || rawFamily === 'Arial') ? '' : rawFamily;
  const currentLabel = FONT_FAMILIES.find(f => f.value === currentFamily)?.label || (currentFamily ? currentFamily.replace(/['"]/g, '') : 'Arial');

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
    const handleScroll = (e: Event) => {
      if (panelRef.current?.contains(e.target as Node)) return;
      setIsOpen(false);
    };
    document.addEventListener('pointerdown', handler, true);
    document.addEventListener('mousedown', handler, true);
    window.addEventListener('scroll', handleScroll, true);
    window.addEventListener('resize', handleScroll, true);
    return () => {
      document.removeEventListener('pointerdown', handler, true);
      document.removeEventListener('mousedown', handler, true);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('resize', handleScroll, true);
    };
  }, [isOpen]);

  const selectFamily = (value: string) => {
    setIsOpen(false);
    if (value === '') {
      editor.chain().focus().unsetFontFamily().run();
    } else {
      editor.chain().focus().setFontFamily(value).run();
    }
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        className={`editor-button font-family-dropdown-btn${isOpen ? ' is-active' : ''}`}
        title="Carattere"
      >
        <span className="text-xs font-medium truncate flex-1 text-left">{currentLabel}</span>
        <ChevronDown size={10} style={{ opacity: 0.6, marginLeft: 2, flexShrink: 0 }} />
      </button>
      {isOpen && createPortal(
        <div
          ref={panelRef}
          className="editor-dropdown-panel font-family-dropdown-panel"
          style={{ position: 'fixed', top: panelPos.top, left: panelPos.left, zIndex: 9999, minWidth: '170px' }}
        >
          {FONT_FAMILIES.map(f => {
            const isActive = currentFamily === f.value;
            return (
              <button
                key={f.label}
                type="button"
                className={`editor-dropdown-item${isActive ? ' is-active' : ''}`}
                style={{ fontFamily: f.cssFamily }}
                onClick={() => selectFamily(f.value)}
              >
                <span>{f.label}</span>
              </button>
            );
          })}
        </div>,
        document.body
      )}
    </>
  );
};

export const FontSizeSelect = ({ editor }: { editor: TiptapEditor }) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [panelPos, setPanelPos] = React.useState({ top: 0, left: 0 });
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

  const getCurrentSize = (): string => {
    if (!editor) return '11';

    // 1. Explicit inline fontSize mark
    const fontSize = editor.getAttributes('textStyle').fontSize;
    if (fontSize) return String(fontSize).replace(/px|pt/, '').trim();

    // 2. Heading level
    for (let i = 1; i <= 5; i++) {
      if (editor.isActive('heading', { level: i })) return String(HEADING_PT[i]);
    }

    // 3. Default body text is 11pt
    return '11';
  };

  const currentSize = getCurrentSize();

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
    const handleScroll = (e: Event) => {
      if (panelRef.current?.contains(e.target as Node)) return;
      setIsOpen(false);
    };
    document.addEventListener('pointerdown', handler, true);
    document.addEventListener('mousedown', handler, true);
    window.addEventListener('scroll', handleScroll, true);
    window.addEventListener('resize', handleScroll, true);
    return () => {
      document.removeEventListener('pointerdown', handler, true);
      document.removeEventListener('mousedown', handler, true);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('resize', handleScroll, true);
    };
  }, [isOpen]);

  const selectSize = (size: string) => {
    setIsOpen(false);
    if (size) {
      editor.chain().focus().setMark('textStyle', { fontSize: `${size}pt` }).run();
    }
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        className={`editor-button font-size-dropdown-btn${isOpen ? ' is-active' : ''}`}
        title="Dimensione carattere"
      >
        <span className="text-xs font-medium flex-1 text-center">{currentSize}</span>
        <ChevronDown size={10} style={{ opacity: 0.6, marginLeft: 2, flexShrink: 0 }} />
      </button>
      {isOpen && createPortal(
        <div
          ref={panelRef}
          className="editor-dropdown-panel font-size-dropdown-panel"
          style={{ position: 'fixed', top: panelPos.top, left: panelPos.left, zIndex: 9999, minWidth: '64px', maxHeight: '220px', overflowY: 'auto' }}
        >
          {FONT_SIZES.map(s => {
            const isActive = currentSize === s;
            return (
              <button
                key={s}
                type="button"
                className={`editor-dropdown-item${isActive ? ' is-active' : ''}`}
                style={{ justifyContent: 'center', padding: '5px 8px', fontSize: '13px' }}
                onClick={() => selectSize(s)}
              >
                <span>{s}</span>
              </button>
            );
          })}
        </div>,
        document.body
      )}
    </>
  );
};

export const HeadingSelect = ({ editor }: { editor: TiptapEditor }) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [panelPos, setPanelPos] = React.useState({ top: 0, left: 0 });
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

  const getCurrentHeading = () => {
    for (let i = 1; i <= 5; i++) {
      if (editor.isActive('heading', { level: i })) return HEADING_OPTIONS[i];
    }
    return HEADING_OPTIONS[0];
  };

  const current = getCurrentHeading();

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
    const handleScroll = (e: Event) => {
      if (panelRef.current?.contains(e.target as Node)) return;
      setIsOpen(false);
    };
    document.addEventListener('pointerdown', handler, true);
    document.addEventListener('mousedown', handler, true);
    window.addEventListener('scroll', handleScroll, true);
    window.addEventListener('resize', handleScroll, true);
    return () => {
      document.removeEventListener('pointerdown', handler, true);
      document.removeEventListener('mousedown', handler, true);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('resize', handleScroll, true);
    };
  }, [isOpen]);

  const selectHeading = (option: typeof HEADING_OPTIONS[number]) => {
    setIsOpen(false);
    if (option.value === 'paragraph') {
      editor.chain().focus().clearBlockFontSize().setParagraph().run();
    } else {
      editor.chain().focus().clearBlockFontSize().setHeading({ level: option.level as 1 | 2 | 3 | 4 | 5 }).run();
    }
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        className={`editor-button heading-dropdown-btn${isOpen ? ' is-active' : ''}`}
        title="Stile paragrafo"
      >
        <span className="text-xs font-medium truncate flex-1 text-left">{current.label}</span>
        <ChevronDown size={10} style={{ opacity: 0.6, marginLeft: 2, flexShrink: 0 }} />
      </button>
      {isOpen && createPortal(
        <div
          ref={panelRef}
          className="editor-dropdown-panel heading-dropdown-panel"
          style={{ position: 'fixed', top: panelPos.top, left: panelPos.left, zIndex: 9999, minWidth: '150px' }}
        >
          {HEADING_OPTIONS.map(opt => {
            const isActive = current.value === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                className={`editor-dropdown-item${isActive ? ' is-active' : ''}`}
                onClick={() => selectHeading(opt)}
              >
                <span className={
                  opt.level === 1 ? 'font-bold text-base' :
                  opt.level === 2 ? 'font-bold text-sm' :
                  opt.level === 3 ? 'font-semibold text-sm' :
                  opt.level === 4 ? 'font-semibold text-xs' :
                  opt.level === 5 ? 'font-medium text-xs' :
                  'text-sm'
                }>
                  {opt.label}
                </span>
              </button>
            );
          })}
        </div>,
        document.body
      )}
    </>
  );
};

const ZOOM_OPTIONS = [50, 75, 90, 100, 125, 150, 175, 200];

export const ZoomSelect = ({
  zoomLevel = 100,
  onZoomChange,
}: {
  zoomLevel?: number;
  onZoomChange?: (level: number) => void;
}) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const [panelPos, setPanelPos] = React.useState({ top: 0, left: 0 });
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

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
    const handleScroll = (e: Event) => {
      if (panelRef.current?.contains(e.target as Node)) return;
      setIsOpen(false);
    };
    document.addEventListener('pointerdown', handler, true);
    document.addEventListener('mousedown', handler, true);
    window.addEventListener('scroll', handleScroll, true);
    window.addEventListener('resize', handleScroll, true);
    return () => {
      document.removeEventListener('pointerdown', handler, true);
      document.removeEventListener('mousedown', handler, true);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('resize', handleScroll, true);
    };
  }, [isOpen]);

  const selectZoom = (level: number) => {
    setIsOpen(false);
    onZoomChange?.(level);
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
        className={`editor-button zoom-dropdown-btn${isOpen ? ' is-active' : ''}`}
        title="Livello di zoom"
      >
        <span className="text-xs font-medium flex-1 text-center">{zoomLevel}%</span>
        <ChevronDown size={10} style={{ opacity: 0.6, marginLeft: 2, flexShrink: 0 }} />
      </button>
      {isOpen && createPortal(
        <div
          ref={panelRef}
          className="editor-dropdown-panel zoom-dropdown-panel"
          style={{ position: 'fixed', top: panelPos.top, left: panelPos.left, zIndex: 9999, minWidth: '72px', maxHeight: '240px', overflowY: 'auto' }}
        >
          {ZOOM_OPTIONS.map(lvl => {
            const isActive = zoomLevel === lvl;
            return (
              <button
                key={lvl}
                type="button"
                className={`editor-dropdown-item${isActive ? ' is-active' : ''}`}
                style={{ justifyContent: 'center', padding: '5px 8px', fontSize: '13px' }}
                onClick={() => selectZoom(lvl)}
              >
                <span>{lvl}%</span>
              </button>
            );
          })}
        </div>,
        document.body
      )}
    </>
  );
};
