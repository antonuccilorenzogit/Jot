import React from 'react';
import katex from 'katex';
import { Extension, Node, mergeAttributes, textInputRule, type Editor as TiptapEditor, type JSONContent } from '@tiptap/core';
import { ReactNodeViewRenderer, NodeViewWrapper, type NodeViewProps } from '@tiptap/react';
import type { Node as ProseMirrorNode } from '@tiptap/pm/model';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet, type EditorView } from '@tiptap/pm/view';

import HeadingExtension from '@tiptap/extension-heading';
import ParagraphExtension from '@tiptap/extension-paragraph';

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    searchHighlight: {
      setSearchTerm: (term: string, currentIndex?: number, matchCase?: boolean) => ReturnType;
    };
    blockTypography: {
      clearBlockFontSize: () => ReturnType;
    };
  }
}

export interface Heading {
  id: string;
  level: number;
  text: string;
}

export const extractHeadings = (editor: TiptapEditor): Heading[] => {
  const json = editor.getJSON() as JSONContent;
  const result: Heading[] = [];
  json.content?.forEach((node: JSONContent, idx: number) => {
    if (node.type === 'heading') {
      const text = node.content?.map((n: JSONContent) => n.text ?? '').join('') ?? '';
      if (text.trim()) result.push({ id: `h-${idx}`, level: node.attrs?.level ?? 2, text });
    }
  });
  return result;
};

export interface SearchMatch {
  from: number;
  to: number;
}

interface SearchHighlightPluginState {
  searchTerm: string;
  currentIndex: number;
  matchCase: boolean;
  matches: SearchMatch[];
  decorations: DecorationSet;
}

const searchHighlightKey = new PluginKey<SearchHighlightPluginState>('searchHighlight');

export const getSearchMatches = (editor: TiptapEditor): SearchMatch[] => {
  return searchHighlightKey.getState(editor.state)?.matches ?? [];
};

export const SearchHighlight = Extension.create({
  name: 'searchHighlight',

  addCommands() {
    return {
      setSearchTerm:
        (term: string, currentIndex = -1, matchCase = false) =>
        ({ view }: { view: EditorView }) => {
          view.dispatch(
            view.state.tr.setMeta(searchHighlightKey, { term, currentIndex, matchCase }),
          );
          return true;
        },
    };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin<SearchHighlightPluginState>({
        key: searchHighlightKey,
        state: {
          init(): SearchHighlightPluginState {
            return { searchTerm: '', currentIndex: -1, matchCase: false, matches: [], decorations: DecorationSet.empty };
          },
          apply(tr, value, _old, newState): SearchHighlightPluginState {
            const meta = tr.getMeta(searchHighlightKey) as
              | { term: string; currentIndex: number; matchCase?: boolean }
              | undefined;
            const searchTerm = meta !== undefined ? meta.term : value.searchTerm;
            const currentIndex = meta !== undefined ? meta.currentIndex : value.currentIndex;
            const matchCase = meta !== undefined ? (meta.matchCase ?? false) : value.matchCase;

            if (!searchTerm) {
              return { searchTerm: '', currentIndex: -1, matchCase: false, matches: [], decorations: DecorationSet.empty };
            }

            if (meta === undefined && !tr.docChanged) {
              return { searchTerm, currentIndex, matchCase, matches: value.matches, decorations: value.decorations.map(tr.mapping, tr.doc) };
            }

            const decorations: Decoration[] = [];
            const matches: SearchMatch[] = [];
            const searchStr = matchCase ? searchTerm : searchTerm.toLowerCase();
            let matchIdx = 0;

            newState.doc.descendants((node: ProseMirrorNode, pos: number) => {
              if (!node.isText || !node.text) return;
              const nodeText = matchCase ? node.text : node.text.toLowerCase();
              let idx = 0;
              while ((idx = nodeText.indexOf(searchStr, idx)) !== -1) {
                const from = pos + idx;
                const to = from + searchTerm.length;
                matches.push({ from, to });
                decorations.push(
                  Decoration.inline(from, to, {
                    class:
                      matchIdx === currentIndex
                        ? 'search-highlight-active'
                        : 'search-highlight',
                  }),
                );
                idx += searchStr.length;
                matchIdx++;
              }
            });

            return {
              searchTerm,
              currentIndex,
              matchCase,
              matches,
              decorations: DecorationSet.create(newState.doc, decorations),
            };
          },
        },
        props: {
          decorations(state) {
            return searchHighlightKey.getState(state)?.decorations ?? DecorationSet.empty;
          },
        },
      }),
    ];
  },
});

export const FontSize = Extension.create({
  name: 'fontSize',
  addGlobalAttributes() {
    return [{
      types: ['textStyle'],
      attributes: {
        fontSize: {
          default: null,
          parseHTML: el => (el as HTMLElement).style.fontSize || null,
          renderHTML: attrs => attrs.fontSize ? { style: `font-size: ${attrs.fontSize}` } : {},
        },
      },
    }];
  },
  addCommands() {
    return {
      setFontSize: (fontSize: string) => ({ chain }) => {
        return chain()
          .setMark('textStyle', { fontSize })
          .run();
      },
      unsetFontSize: () => ({ chain }) => {
        return chain()
          .setMark('textStyle', { fontSize: null })
          .removeEmptyTextStyle()
          .run();
      },
      clearBlockFontSize: () => ({ tr, state }) => {
        const { from, to } = state.selection;
        state.doc.nodesBetween(from, to, (node, pos) => {
          if (node.isTextblock) {
            const start = pos + 1;
            const end = pos + node.nodeSize - 1;
            if (start < end) {
              node.nodesBetween(0, node.content.size, (child, childOffset) => {
                if (child.isText && child.marks) {
                  const textStyleMark = child.marks.find(m => m.type.name === 'textStyle' && m.attrs?.fontSize);
                  if (textStyleMark) {
                    const childFrom = start + childOffset;
                    const childTo = childFrom + child.nodeSize;
                    const remainingAttrs = { ...textStyleMark.attrs };
                    delete remainingAttrs.fontSize;
                    tr.removeMark(childFrom, childTo, state.schema.marks.textStyle);
                    if (Object.values(remainingAttrs).some(v => v !== null && v !== undefined && v !== '')) {
                      tr.addMark(childFrom, childTo, state.schema.marks.textStyle.create(remainingAttrs));
                    }
                  }
                }
              });
            }
          }
        });
        if (state.storedMarks) {
          const storedTextStyle = state.storedMarks.find(m => m.type.name === 'textStyle' && m.attrs?.fontSize);
          if (storedTextStyle) {
            const remainingAttrs = { ...storedTextStyle.attrs };
            delete remainingAttrs.fontSize;
            const newStoredMarks = state.storedMarks.filter(m => m.type.name !== 'textStyle');
            if (Object.values(remainingAttrs).some(v => v !== null && v !== undefined && v !== '')) {
              newStoredMarks.push(state.schema.marks.textStyle.create(remainingAttrs));
            }
            tr.setStoredMarks(newStoredMarks);
          }
        }
        return true;
      },
    };
  },
});

/** "2610" -> "43:30", "4000" -> "1:06:40". */
export const formatAudioTime = (value: string | number | null | undefined): string => {
  const total = Math.max(0, Math.floor(Number(value) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const mm = h > 0 ? String(m).padStart(2, '0') : String(m);
  return `${h > 0 ? `${h}:` : ''}${mm}:${String(sec).padStart(2, '0')}`;
};

export const CustomHeading = HeadingExtension.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      // Minute of the lesson where the section starts (seconds), set by the pipeline.
      dataT: {
        default: null,
        parseHTML: element => {
          const raw = element.getAttribute('data-t');
          return raw && /^\d+$/.test(raw) ? raw : null;
        },
        renderHTML: attributes => (attributes.dataT
          ? { 'data-t': attributes.dataT, 'data-t-label': formatAudioTime(attributes.dataT) }
          : {}),
      },
    };
  },
  addCommands() {
    return {
      ...this.parent?.(),
      setHeading: attributes => ({ chain }) => {
        return chain()
          .clearBlockFontSize()
          .setNode(this.name, attributes)
          .run();
      },
      toggleHeading: attributes => ({ chain }) => {
        return chain()
          .clearBlockFontSize()
          .toggleNode(this.name, 'paragraph', attributes)
          .run();
      },
    };
  },
});

export const CustomParagraph = ParagraphExtension.extend({
  addCommands() {
    return {
      ...this.parent?.(),
      setParagraph: () => ({ chain }) => {
        return chain()
          .clearBlockFontSize()
          .setNode(this.name)
          .run();
      },
    };
  },
});

export const escapeHtml = (text: string): string =>
  String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');

function MathNodeView({ node, updateAttributes, selected }: NodeViewProps) {
  const [isEditing, setIsEditing] = React.useState(false);
  const [latex, setLatex] = React.useState(node.attrs.latex || '');

  React.useEffect(() => {
    setLatex(node.attrs.latex || '');
  }, [node.attrs.latex]);

  const html = React.useMemo(() => {
    const raw = node.attrs.latex || 'E=mc^2';
    try {
      return katex.renderToString(raw, { displayMode: false, throwOnError: false });
    } catch {
      return `<span class="katex-error text-red-500 font-mono text-xs">${escapeHtml(raw)}</span>`;
    }
  }, [node.attrs.latex]);

  if (isEditing) {
    return React.createElement(
      NodeViewWrapper,
      { as: 'span', className: `math-node-wrapper ${selected ? 'is-selected' : ''}` },
      React.createElement(
        'span',
        { className: 'math-inline-edit inline-flex items-center gap-1.5 bg-[var(--bg-elevated)] p-1 rounded-lg border border-[var(--accent-text)]' },
        React.createElement('span', { className: 'text-xs font-mono font-semibold text-[var(--accent-text)]' }, 'TeX:'),
        React.createElement('input', {
          type: 'text',
          value: latex,
          onChange: (e: React.ChangeEvent<HTMLInputElement>) => setLatex(e.target.value),
          onBlur: () => { updateAttributes({ latex }); setIsEditing(false); },
          onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => {
            if (e.key === 'Enter') { updateAttributes({ latex }); setIsEditing(false); }
          },
          autoFocus: true,
          className: 'app-input font-mono text-xs px-2 py-0.5 min-w-[120px]',
        })
      )
    );
  }

  return React.createElement(
    NodeViewWrapper,
    { as: 'span', className: `math-node-wrapper ${selected ? 'is-selected' : ''}` },
    React.createElement('span', {
      className: 'math-rendered cursor-pointer inline-block px-1.5 py-0.5 rounded transition-all hover:bg-[var(--accent-subtle)] hover:ring-1 hover:ring-[var(--accent-ring)]',
      onClick: () => setIsEditing(true),
      title: 'Clicca per modificare la formula LaTeX',
      dangerouslySetInnerHTML: { __html: html },
    })
  );
}

export const MathInline = Node.create({
  name: 'mathInline',
  group: 'inline',
  inline: true,
  atom: true,

  addAttributes() {
    return {
      latex: { default: 'E=mc^2' },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'span[data-math]',
        getAttrs: element => ({ latex: (element as HTMLElement).getAttribute('data-math') || '' }),
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    let katexHtml = '';
    try {
      katexHtml = katex.renderToString(HTMLAttributes.latex || '', { displayMode: false, throwOnError: false });
    } catch {
      katexHtml = HTMLAttributes.latex ? escapeHtml(HTMLAttributes.latex) : '';
    }
    return [
      'span',
      mergeAttributes({
        'data-math': HTMLAttributes.latex || '',
        class: 'math-node-inline',
        title: HTMLAttributes.latex || '',
      }),
      ['span', { class: 'math-rendered-html' }, katexHtml],
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(MathNodeView);
  },
});

export const SmartArrows = Extension.create({
  name: 'smartArrows',
  addInputRules() {
    return [
      textInputRule({ find: /->$/, replace: '→ ' }),
      textInputRule({ find: /<-$/, replace: '← ' }),
      textInputRule({ find: /==>$/, replace: '⇒ ' }),
      textInputRule({ find: /<=>$/, replace: '↔ ' }),
    ];
  },
});

function MathBlockNodeView({ node, updateAttributes, selected }: NodeViewProps) {
  const [isEditing, setIsEditing] = React.useState(false);
  const [latex, setLatex] = React.useState(node.attrs.latex || '');

  React.useEffect(() => {
    setLatex(node.attrs.latex || '');
  }, [node.attrs.latex]);

  const html = React.useMemo(() => {
    const raw = node.attrs.latex || 'E=mc^2';
    try {
      return katex.renderToString(raw, { displayMode: true, throwOnError: false });
    } catch {
      return `<span class="katex-error text-red-500 font-mono text-xs">${escapeHtml(raw)}</span>`;
    }
  }, [node.attrs.latex]);

  if (isEditing) {
    return React.createElement(
      NodeViewWrapper,
      { as: 'div', className: `math-block-wrapper my-2 p-2 rounded border border-[var(--accent-text)] bg-[var(--bg-elevated)] ${selected ? 'is-selected' : ''}` },
      React.createElement(
        'div',
        { className: 'flex flex-col gap-2' },
        React.createElement('span', { className: 'text-xs font-mono font-semibold text-[var(--accent-text)]' }, 'Formula LaTeX (Block):'),
        React.createElement('textarea', {
          value: latex,
          onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => setLatex(e.target.value),
          onBlur: () => { updateAttributes({ latex }); setIsEditing(false); },
          onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { updateAttributes({ latex }); setIsEditing(false); }
          },
          autoFocus: true,
          className: 'app-input font-mono text-xs p-2 w-full min-h-[60px]',
          placeholder: 'Inserisci formula LaTeX...'
        }),
        React.createElement(
          'button',
          {
            type: 'button',
            onClick: () => { updateAttributes({ latex }); setIsEditing(false); },
            className: 'self-end px-3 py-1 bg-[var(--btn-primary-bg)] hover:bg-[var(--btn-primary-hover)] text-[var(--btn-primary-text)] text-xs rounded font-semibold transition-colors'
          },
          'Salva (Ctrl+Enter)'
        )
      )
    );
  }

  return React.createElement(
    NodeViewWrapper,
    { as: 'div', className: `math-block-wrapper my-2 text-center ${selected ? 'is-selected' : ''}` },
    React.createElement('div', {
      className: 'math-rendered cursor-pointer inline-block p-2 rounded transition-all hover:bg-[var(--accent-subtle)] hover:ring-1 hover:ring-[var(--accent-ring)]',
      onClick: () => setIsEditing(true),
      title: 'Clicca per modificare la formula LaTeX',
      dangerouslySetInnerHTML: { __html: html },
    })
  );
}

export const MathBlock = Node.create({
  name: 'mathBlock',
  group: 'block',
  atom: true,

  addAttributes() {
    return {
      latex: { default: 'E=mc^2' },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-math-block]',
        getAttrs: element => ({ latex: (element as HTMLElement).getAttribute('data-math-block') || '' }),
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    let katexHtml = '';
    try {
      katexHtml = katex.renderToString(HTMLAttributes.latex || '', { displayMode: true, throwOnError: false });
    } catch {
      katexHtml = HTMLAttributes.latex ? escapeHtml(HTMLAttributes.latex) : '';
    }
    return [
      'div',
      mergeAttributes({
        'data-math-block': HTMLAttributes.latex || '',
        class: 'math-node-block',
        title: HTMLAttributes.latex || '',
      }),
      ['div', { class: 'math-rendered-html' }, katexHtml],
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(MathBlockNodeView);
  },
});
