import React, { useEffect, useMemo, useRef, useState } from 'react';
import { type Editor as TiptapEditor } from '@tiptap/core';
import { TextSelection } from '@tiptap/pm/state';
import { DOMSerializer } from '@tiptap/pm/model';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Color } from '@tiptap/extension-color';
import { TextStyle } from '@tiptap/extension-text-style';
import Underline from '@tiptap/extension-underline';
import Highlight from '@tiptap/extension-highlight';
import TextAlign from '@tiptap/extension-text-align';
import FontFamily from '@tiptap/extension-font-family';
import Link from '@tiptap/extension-link';
import Subscript from '@tiptap/extension-subscript';
import Superscript from '@tiptap/extension-superscript';
import { Menu, X } from 'lucide-react';
import { FloatingImage } from './FloatingImage';
import { type Heading, SearchHighlight, FontSize, CustomHeading, CustomParagraph, MathInline, MathBlock, SmartArrows, extractHeadings } from '../editorExtensions';
import Youtube from '@tiptap/extension-youtube';
import Typography from '@tiptap/extension-typography';
import { Table, TableRow, TableCell, TableHeader } from '@tiptap/extension-table';
import { MenuBar } from './EditorToolbar';
import { getWordRangeAtPos } from '../editorUtils';
import { EditorBubbleMenu } from './EditorBubbleMenu';
import { FindReplacePanel } from './EditorFindReplace';
import { useEditorImageDrop } from '../hooks/useEditorImageDrop';
import { useTocScrollSpy } from '../hooks/useTocScrollSpy';
import { EditorContextMenu } from './EditorContextMenu';
import { prepareHtmlForClipboard } from '../utils';

export type { Heading };

interface RichTextEditorProps {
  initialContent?: string;
  onChange?: (content: string) => void;
  onEditorReady?: (getHtml: () => string) => void;
  initialScrollTop?: number;
  initialSearchTerm?: string;
  onScrollTopChange?: (scrollTop: number) => void;
  onHeadingsChange?: (headings: Heading[]) => void;
  isTocOpen?: boolean;
  onTocToggle?: () => void;
  tocHeadings?: Heading[];
  onScrollToHeading?: (heading: Heading) => void;
  zoomLevel?: number;
  onZoomChange?: (zoomLevel: number) => void;
}

export function RichTextEditor({
  initialContent,
  onChange,
  onEditorReady,
  initialScrollTop,
  initialSearchTerm,
  onScrollTopChange,
  onHeadingsChange,
  isTocOpen = false,
  onTocToggle,
  tocHeadings = [],
  onScrollToHeading,
  zoomLevel,
  onZoomChange,
}: RichTextEditorProps) {
  const [contextMenu, setContextMenu] = React.useState<{ x: number; y: number } | null>(null);
  const [findMode, setFindMode] = useState<null | 'find' | 'replace'>(initialSearchTerm ? 'find' : null);
  const [findFocusTrigger, setFindFocusTrigger] = useState(0);
  const findModeRef = useRef<null | 'find' | 'replace'>(null);
  useEffect(() => { findModeRef.current = findMode; }, [findMode]);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const editorRef = useRef<TiptapEditor | null>(null);
  const initialContentRef = useRef(initialContent);
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const lastKnownScrollTopRef = useRef<number>(initialScrollTop ?? 0);
  const hasRestoredScrollRef = useRef(false);
  const onScrollTopChangeRef = useRef(onScrollTopChange);
  useEffect(() => { onScrollTopChangeRef.current = onScrollTopChange; }, [onScrollTopChange]);
  const onHeadingsChangeRef = useRef(onHeadingsChange);
  useEffect(() => { onHeadingsChangeRef.current = onHeadingsChange; }, [onHeadingsChange]);
  const headingsDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const publishHeadings = (currentEditor: TiptapEditor) => {
    if (currentEditor.isDestroyed) return;
    try {
      onHeadingsChangeRef.current?.(extractHeadings(currentEditor));
    } catch (_) {
      // TipTap can briefly retain an editor object with a disposed schema while
      // React StrictMode reconnects effects. The next mounted pass republishes.
    }
  };

  const { activeHeadingId, tocNavRef, tocStickyRef } = useTocScrollSpy({
    tocHeadings,
    scrollContainerRef,
  });

  const {
    insertImageFiles,
    handleDragStart,
    handlePaste,
    handleDrop,
    transformPastedHTML,
  } = useEditorImageDrop({ editorRef });

  const extensions = useMemo(() => [
    StarterKit.configure({
      heading: false,
      paragraph: false,
      link: false,
      underline: false,
      horizontalRule: false,
    }),
    CustomHeading,
    CustomParagraph,
    FloatingImage,
    TextStyle,
    Color,
    FontFamily.configure({ types: ['textStyle'] }),
    FontSize,
    Underline,
    Highlight.configure({ multicolor: true }),
    TextAlign.configure({ types: ['heading', 'paragraph'] }),
    Link.configure({ openOnClick: false, markdownLinks: true }),
    Subscript,
    Superscript,
    SearchHighlight,
    Youtube.configure({
      controls: true,
      nocookie: true,
      width: 640,
      height: 360,
    }),
    Typography,
    MathInline,
    MathBlock,
    SmartArrows,
    Table.configure({
      resizable: true,
    }),
    TableRow,
    TableHeader,
    TableCell,
  ], []);

  const editor = useEditor({
    extensions,
    content: initialContent,
    onCreate: ({ editor }) => {
      editorRef.current = editor;
      if (editor.utils?.getUpdatedPosition) {
        const origGetUpdatedPosition = editor.utils.getUpdatedPosition;
        editor.utils.getUpdatedPosition = (
          pos: Parameters<typeof origGetUpdatedPosition>[0],
          tr: Parameters<typeof origGetUpdatedPosition>[1],
        ) => {
          try {
            return origGetUpdatedPosition(pos, tr);
          } catch (_) {
            return { position: pos, mapResult: null };
          }
        };
      }
      onEditorReady?.(() => (editorRef.current && !editorRef.current.isDestroyed) ? editorRef.current.getHTML() : '');
    },
    onUpdate: ({ editor }) => {
      onChange?.(editor.getHTML());
      if (headingsDebounceRef.current) clearTimeout(headingsDebounceRef.current);
      headingsDebounceRef.current = setTimeout(() => {
        publishHeadings(editor);
      }, 400);
    },
    editorProps: {
      attributes: {
        class: 'prose prose-sm sm:prose-base max-w-none focus:outline-none tiptap-editor',
        spellcheck: 'false',
      },
      handleDoubleClick: (view, pos) => {
        const range = getWordRangeAtPos(view, pos);
        if (range) {
          const tr = view.state.tr.setSelection(
            TextSelection.create(view.state.tr.doc, range.from, range.to),
          );
          view.dispatch(tr);
          return true;
        }
        return false;
      },
      handleDOMEvents: {
        dragstart: (view, event) => handleDragStart(view, event as DragEvent),
        copy: (view) => {
          const { from, to, empty } = view.state.selection;
          if (empty) return false;
          const slice = view.state.selection.content();
          const serializer = DOMSerializer.fromSchema(view.state.schema);
          const dom = document.createElement('div');
          dom.appendChild(serializer.serializeFragment(slice.content));
          const rawHtml = dom.innerHTML;
          if (rawHtml.includes('<img') || rawHtml.includes('data-editor-image')) {
            const plainText = view.state.doc.textBetween(from, to, '\n');
            void prepareHtmlForClipboard(rawHtml).then(clipboardHtml => {
              if (clipboardHtml && typeof ClipboardItem !== 'undefined') {
                const htmlBlob = new Blob([clipboardHtml], { type: 'text/html' });
                const textBlob = new Blob([plainText], { type: 'text/plain' });
                navigator.clipboard.write([new ClipboardItem({ 'text/html': htmlBlob, 'text/plain': textBlob })]).catch(() => {
                  navigator.clipboard.writeText(plainText);
                });
              }
            });
          }
          return false;
        },
      },
      handlePaste: (view, event) => handlePaste(view, event as ClipboardEvent),
      handleDrop: (view, event) => handleDrop(view, event as DragEvent),
      transformPastedHTML,
    },
  }, [extensions]);

  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const timer = setTimeout(() => {
      if (!editor.isDestroyed) {
        publishHeadings(editor);
      }
    }, 0);
    return () => clearTimeout(timer);
  }, [editor]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if ((event.target as HTMLElement | null)?.closest('.gdocs-context-menu')) return;
      setContextMenu(null);
    };
    const handleScroll = () => {
      setContextMenu(null);
    };
    document.addEventListener('pointerdown', handlePointerDown, true);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault();
        if (findModeRef.current) {
          setFindFocusTrigger(prev => prev + 1);
        } else {
          setFindMode('find');
        }
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'h' || e.key === 'H')) {
        e.preventDefault();
        if (findModeRef.current === 'replace') {
          setFindFocusTrigger(prev => prev + 1);
        } else {
          setFindMode('replace');
        }
      }
      if ((e.ctrlKey || e.metaKey) && e.altKey && (e.key === 'o' || e.key === 'O')) {
        e.preventDefault();
        onTocToggle?.();
      }
      if (e.key === 'Escape' && findModeRef.current) { e.stopPropagation(); setFindMode(null); }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onTocToggle]);

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const menuWidth = 280, menuHeight = 360, padding = 12;
    const x = Math.min(e.clientX, window.innerWidth - menuWidth - padding);
    const y = Math.min(e.clientY, window.innerHeight - menuHeight - padding);
    setContextMenu({ x: Math.max(padding, x), y: Math.max(padding, y) });
  };

  useEffect(() => {
    if (initialContentRef.current === initialContent) return;
    initialContentRef.current = initialContent;
    if (!editor || editor.isDestroyed) return;
    try {
      if (initialContent !== editor.getHTML() && !editor.isFocused && editor.isEmpty) {
        editor.commands.setContent(initialContent);
      }
    } catch (_) {
      // The editor schema may already be disposed during a StrictMode reconnect.
    }
  }, [initialContent, editor]);

  useEffect(() => {
    if (hasRestoredScrollRef.current || !scrollContainerRef.current || !editor || !initialScrollTop) return;
    hasRestoredScrollRef.current = true;
    requestAnimationFrame(() => {
      if (scrollContainerRef.current) {
        scrollContainerRef.current.scrollTop = initialScrollTop;
        lastKnownScrollTopRef.current = initialScrollTop;
      }
    });
  }, [editor, initialScrollTop]);

  // Adjust scroll on zoom level changes to keep the current viewport content anchored in place
  const prevZoomLevelRef = useRef<number | undefined>(zoomLevel);
  React.useLayoutEffect(() => {
    const prevZoom = prevZoomLevelRef.current;
    prevZoomLevelRef.current = zoomLevel;

    if (prevZoom === undefined || zoomLevel === undefined || prevZoom === zoomLevel) return;

    const container = scrollContainerRef.current;
    if (!container) return;

    const oldRatio = prevZoom / 100;
    const newRatio = zoomLevel / 100;
    const viewportWidth = container.clientWidth;

    // Adjust vertical scroll proportionally so the top visible position is perfectly preserved
    const prevScrollTop = lastKnownScrollTopRef.current;
    if (prevScrollTop > 0) {
      const newScrollTop = Math.round(prevScrollTop * (newRatio / oldRatio));
      container.scrollTop = newScrollTop;
      lastKnownScrollTopRef.current = newScrollTop;
    } else {
      container.scrollTop = 0;
      lastKnownScrollTopRef.current = 0;
    }

    // Adjust horizontal scroll to keep paper centered
    const outer = container.querySelector('.editor-page-outer') as HTMLElement | null;
    if (outer) {
      const contentWidth = outer.scrollWidth;
      if (contentWidth > viewportWidth) {
        container.scrollLeft = Math.max(0, (contentWidth - viewportWidth) / 2);
      } else {
        container.scrollLeft = 0;
      }
    }
  }, [zoomLevel]);

  // Center paper in viewport when TOC opens/closes or container resizes
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const adjustScroll = () => {
      const outer = container.querySelector('.editor-page-outer') as HTMLElement;
      const tocCol = container.querySelector('.editor-toc-col') as HTMLElement;
      if (!outer || !tocCol) return;

      const viewportWidth = container.clientWidth;
      const contentWidth = outer.scrollWidth;
      if (contentWidth <= viewportWidth) {
        container.scrollLeft = 0;
        return;
      }

      const targetLeft = Math.max(0, (contentWidth - viewportWidth) / 2);
      container.scrollLeft = targetLeft;
    };

    let transitionActive = true;
    const startTime = performance.now();
    const duration = 250;

    const poll = () => {
      adjustScroll();
      if (transitionActive && performance.now() - startTime < duration) {
        requestAnimationFrame(poll);
      }
    };
    requestAnimationFrame(poll);

    const resizeObserver = new ResizeObserver(() => {
      adjustScroll();
    });
    resizeObserver.observe(container);

    return () => {
      transitionActive = false;
      resizeObserver.disconnect();
    };
  }, [isTocOpen]);

  return (
    <div className={`editor-shell flex flex-1 min-h-0 w-full flex-col relative ${isTocOpen ? 'editor-toc-open' : ''}`} onContextMenu={handleContextMenu}>
      {editor && <EditorBubbleMenu editor={editor} isContextMenuOpen={Boolean(contextMenu)} />}
      <MenuBar
        editor={editor}
        onOpenImagePicker={() => imageInputRef.current?.click()}
        showFindReplace={findMode !== null}
        onToggleFindReplace={() => setFindMode(p => p ? null : 'find')}
        zoomLevel={zoomLevel}
        onZoomChange={onZoomChange}
      />
      {findMode && editor && (
        <FindReplacePanel editor={editor} onClose={() => setFindMode(null)} initialMode={findMode} focusTrigger={findFocusTrigger} initialFindText={initialSearchTerm} />
      )}
      <div
        ref={scrollContainerRef}
        className="editor-page-container flex-1 overflow-y-auto"
        style={{ overflowX: 'auto' }}
        onScroll={() => {
          setContextMenu(null);
          if (scrollContainerRef.current) {
            const st = scrollContainerRef.current.scrollTop;
            lastKnownScrollTopRef.current = st;
            onScrollTopChangeRef.current?.(st);
          }
        }}
      >
        <div className="editor-page-outer">
          <div className="editor-toc-col" style={{ width: isTocOpen ? 260 : 44 }}>
            <div className="editor-toc-sticky" ref={tocStickyRef}>
              {!isTocOpen ? (
                <button className="editor-toc-btn" onClick={onTocToggle} title="Apri indice">
                  <Menu className="w-4 h-4" />
                </button>
              ) : (
                <>
                  <div className="editor-toc-header">
                    <span>Indice</span>
                    <button className="toc-left-close" onClick={onTocToggle} title="Chiudi">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <nav className="editor-toc-nav" ref={tocNavRef}>
                    {tocHeadings.length === 0 ? (
                      <p className="toc-empty">Nessun titolo</p>
                    ) : (
                      tocHeadings.map(h => (
                        <button
                          key={h.id}
                          className={`toc-item toc-item-h${h.level}${activeHeadingId === h.id ? ' toc-item-active' : ''}`}
                          style={{ paddingLeft: `${(h.level - 1) * 12 + 14}px` }}
                          onClick={() => onScrollToHeading?.(h)}
                          title={h.text}
                        >
                          {h.text}
                        </button>
                      ))
                    )}
                  </nav>
                </>
              )}
            </div>
          </div>
          <div className="editor-page-center">
            <div className="editor-page" style={zoomLevel !== undefined ? { zoom: zoomLevel / 100 } : undefined}>
              <EditorContent editor={editor} />
            </div>
          </div>
          <div className="editor-toc-spacer" style={{ width: isTocOpen ? 260 : 44 }} />
        </div>
      </div>

      <EditorContextMenu
        contextMenu={contextMenu}
        onClose={() => setContextMenu(null)}
        editor={editor}
        onOpenImagePicker={() => imageInputRef.current?.click()}
        onOpenFind={() => setFindMode('find')}
      />

      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={event => {
          if (event.target.files?.length) void insertImageFiles(event.target.files);
          event.currentTarget.value = '';
          setContextMenu(null);
        }}
      />
    </div>
  );
}
