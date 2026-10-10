import { reportClientError } from '../diagnostics';
/* eslint-disable react-refresh/only-export-components */
import React, { useEffect, useRef } from 'react';
import { Node, mergeAttributes } from '@tiptap/core';
import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from '@tiptap/react';
import { NodeSelection, Plugin, PluginKey } from '@tiptap/pm/state';
import { optimizeDataUrlImage } from '../utils';

export type ImageAlignment = 'center';

export const EDITOR_CONTENT_WIDTH_PX = 634;

export const clampWidth = (value: unknown) => {
  const numeric = typeof value === 'number' ? value : Number.parseFloat(String(value ?? '56'));
  if (!Number.isFinite(numeric)) return 56;
  return Math.min(100, Math.max(20, Math.round(numeric)));
};

export const calculateImagePixelWidth = (widthPercent: unknown) =>
  Math.round((EDITOR_CONTENT_WIDTH_PX * clampWidth(widthPercent)) / 100);

const buildWrapperReactStyle = (width: number): React.CSSProperties => ({
  width: `${width}%`,
  maxWidth: '100%',
  position: 'relative',
  userSelect: 'none',
  margin: '14px auto',
  marginLeft: 'auto',
  marginRight: 'auto',
  display: 'block',
  clear: 'both',
  textAlign: 'center',
});

const buildWrapperStyle = (_width: number) =>
  'width:100%;max-width:100%;position:relative;float:none;margin:14px auto;margin-left:auto;margin-right:auto;display:block;clear:both;text-align:center;';

const buildImageStyle = (width: number) =>
  `display:block;width:${width}%;max-width:100%;height:auto;margin:0 auto;margin-left:auto;margin-right:auto;padding:0;text-align:center;`;

const extractImageAttrs = (element: HTMLElement) => {
  const img = element.tagName.toLowerCase() === 'img' ? (element as HTMLImageElement) : element.querySelector('img');
  if (!img) {
    return false;
  }
  const figcaption = element.querySelector('figcaption');

  let widthVal = element.getAttribute('data-width') || img.getAttribute('data-width') || '';
  if (!widthVal) {
    const elementStyleWidth = element.style.width;
    const imgStyleWidth = img.style.width;
    const imgWidthAttr = img.getAttribute('width');
    if (elementStyleWidth && elementStyleWidth.endsWith('%')) {
      widthVal = elementStyleWidth;
    } else if (imgStyleWidth && imgStyleWidth.endsWith('%')) {
      widthVal = imgStyleWidth;
    } else if (imgWidthAttr && Number.isFinite(Number(imgWidthAttr))) {
      const px = Number(imgWidthAttr);
      widthVal = String(Math.round((px / EDITOR_CONTENT_WIDTH_PX) * 100));
    } else if (elementStyleWidth || imgStyleWidth) {
      widthVal = elementStyleWidth || imgStyleWidth;
    }
  }

  return {
    src: img.getAttribute('src') || '',
    alt: img.getAttribute('alt') || '',
    title: img.getAttribute('title') || '',
    width: clampWidth(widthVal || '56'),
    align: 'center',
    caption: figcaption ? figcaption.textContent || '' : element.getAttribute('data-caption') || '',
  };
};

function FloatingImageView({ node, updateAttributes, selected, getPos, editor }: NodeViewProps) {
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const width = clampWidth(node.attrs.width);
  const caption: string = String(node.attrs.caption || '');
  const src = String(node.attrs.src || '');

  useEffect(() => {
    if (
      src.startsWith('data:image/') &&
      !src.startsWith('data:image/svg+xml') &&
      !src.startsWith('data:image/gif') &&
      (src.startsWith('data:image/webp') || !src.startsWith('data:image/jpeg') || src.length > 500_000)
    ) {
      let isMounted = true;
      void optimizeDataUrlImage(src, { format: 'image/jpeg' }).then(optimizedSrc => {
        if (isMounted && optimizedSrc && optimizedSrc !== src) {
          updateAttributes({ src: optimizedSrc });
        }
      });
      return () => {
        isMounted = false;
      };
    }
  }, [src, updateAttributes]);

  const selectImageNode = (e: React.SyntheticEvent) => {
    if ((e.target as HTMLElement)?.closest('.gdocs-handle')) return;
    if (typeof getPos === 'function') {
      const pos = getPos();
      if (typeof pos === 'number' && pos >= 0) {
        const { selection } = editor?.state || {};
        if (!(selection instanceof NodeSelection && selection.from === pos)) {
          editor?.chain().focus().setNodeSelection(pos).run();
        }
      }
    }
  };

  // Resize handler for 8 handles
  const startResizeHandle = (
    event: React.PointerEvent<HTMLDivElement>,
    handle: 'tl' | 'tc' | 'tr' | 'ml' | 'mr' | 'bl' | 'bc' | 'br'
  ) => {
    event.preventDefault();
    event.stopPropagation();

    const handleEl = event.currentTarget;
    const pointerId = event.pointerId;
    handleEl.setPointerCapture?.(pointerId);

    const startX = event.clientX;
    const startY = event.clientY;
    const startWidth = width;
    const editorRoot = anchorRef.current?.closest('.tiptap-editor') as HTMLElement | null;

    let contentWidth = 320;
    if (editorRoot) {
      const style = window.getComputedStyle(editorRoot);
      const paddingLeft = Number.parseFloat(style.paddingLeft) || 0;
      const paddingRight = Number.parseFloat(style.paddingRight) || 0;
      contentWidth = Math.max(editorRoot.clientWidth - paddingLeft - paddingRight, 320);
    }

    const imgEl = anchorRef.current?.querySelector('img');
    const aspectRatio = imgEl && imgEl.clientHeight > 0 ? imgEl.clientWidth / imgEl.clientHeight : 16 / 9;

    const move = (moveEvent: PointerEvent) => {
      let deltaPx = 0;
      const dx = moveEvent.clientX - startX;
      const dy = moveEvent.clientY - startY;

      if (handle === 'mr' || handle === 'tr' || handle === 'br') {
        deltaPx = 2 * dx;
      } else if (handle === 'ml' || handle === 'tl' || handle === 'bl') {
        deltaPx = -2 * dx;
      } else if (handle === 'bc') {
        deltaPx = 2 * dy * aspectRatio;
      } else if (handle === 'tc') {
        deltaPx = -2 * dy * aspectRatio;
      }

      const deltaPercent = (deltaPx / contentWidth) * 100;
      updateAttributes({ width: clampWidth(startWidth + deltaPercent) });
    };

    const stop = () => {
      handleEl.releasePointerCapture?.(pointerId);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
  };

  return (
    <NodeViewWrapper
      as="div"
      ref={anchorRef}
      className={`editor-image-node group ${selected ? 'is-selected' : ''}`}
      data-editor-image="true"
      data-width={width}
      data-align="center"
      align="center"
      data-caption={caption}
      style={buildWrapperReactStyle(width)}
      onClick={selectImageNode}
      onPointerDown={selectImageNode}
    >
      {/* Asset Wrapper with Google Docs Blue Border */}
      <span className="editor-image-asset-wrapper relative block transition-all overflow-hidden" data-drag-handle>
        <img
          src={String(node.attrs.src || '')}
          alt={String(node.attrs.alt || '')}
          title={String(node.attrs.title || '')}
          draggable={false}
          className="editor-image-asset cursor-grab active:cursor-grabbing block w-full h-auto"
        />
      </span>

      {/* 8 Google Docs Blue Resize Handles */}
      {selected && (
        <span className="gdocs-handles-container" contentEditable={false}>
          <div className="gdocs-handle gdocs-handle-tl" onPointerDown={e => startResizeHandle(e, 'tl')} />
          <div className="gdocs-handle gdocs-handle-tc" onPointerDown={e => startResizeHandle(e, 'tc')} />
          <div className="gdocs-handle gdocs-handle-tr" onPointerDown={e => startResizeHandle(e, 'tr')} />
          <div className="gdocs-handle gdocs-handle-ml" onPointerDown={e => startResizeHandle(e, 'ml')} />
          <div className="gdocs-handle gdocs-handle-mr" onPointerDown={e => startResizeHandle(e, 'mr')} />
          <div className="gdocs-handle gdocs-handle-bl" onPointerDown={e => startResizeHandle(e, 'bl')} />
          <div className="gdocs-handle gdocs-handle-bc" onPointerDown={e => startResizeHandle(e, 'bc')} />
          <div className="gdocs-handle gdocs-handle-br" onPointerDown={e => startResizeHandle(e, 'br')} />
        </span>
      )}
    </NodeViewWrapper>
  );
}

export const FloatingImage = Node.create({
  name: 'floatingImage',
  group: 'block',
  inline: false,
  atom: true,
  draggable: true,
  selectable: true,

  addAttributes() {
    return {
      src: {
        default: '',
        parseHTML: element => {
          const attrs = extractImageAttrs(element as HTMLElement);
          return attrs ? attrs.src : (element as HTMLElement).getAttribute('src') || '';
        },
      },
      alt: {
        default: '',
        parseHTML: element => {
          const attrs = extractImageAttrs(element as HTMLElement);
          return attrs ? attrs.alt : (element as HTMLElement).getAttribute('alt') || '';
        },
      },
      title: {
        default: '',
        parseHTML: element => {
          const attrs = extractImageAttrs(element as HTMLElement);
          return attrs ? attrs.title : (element as HTMLElement).getAttribute('title') || '';
        },
      },
      width: {
        default: 56,
        parseHTML: element => {
          const attrs = extractImageAttrs(element as HTMLElement);
          return attrs ? attrs.width : 56;
        },
      },
      align: {
        default: 'center',
        parseHTML: () => 'center',
      },
      caption: {
        default: '',
        parseHTML: element => {
          const attrs = extractImageAttrs(element as HTMLElement);
          return attrs ? attrs.caption : '';
        },
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'span[data-editor-image]',
        getAttrs: element => extractImageAttrs(element as HTMLElement),
      },
      {
        tag: 'div[data-editor-image]',
        getAttrs: element => extractImageAttrs(element as HTMLElement),
      },
      {
        tag: 'img[src]',
        getAttrs: element => extractImageAttrs(element as HTMLElement),
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    const width = clampWidth(HTMLAttributes.width);
    const caption: string = HTMLAttributes.caption || '';
    const pixelWidth = calculateImagePixelWidth(width);

    const children: Array<[string, Record<string, string>] | [string, Record<string, string>, string]> = [
      [
        'img',
        {
          src: HTMLAttributes.src,
          alt: HTMLAttributes.alt || '',
          title: HTMLAttributes.title || '',
          width: String(pixelWidth),
          align: 'center',
          style: buildImageStyle(width),
        },
      ],
    ];

    if (caption) {
      children.push(['figcaption', { class: 'editor-image-caption' }, caption]);
    }

    return [
      'div',
      mergeAttributes({
        'data-editor-image': 'true',
        'data-width': String(width),
        'data-align': 'center',
        'data-caption': caption,
        align: 'center',
        style: buildWrapperStyle(width),
      }),
      ...children,
    ];
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey('floatingImageClick'),
        props: {
          handleDOMEvents: {
            mousedown(view, event) {
              const target = event.target as HTMLElement | null;
              if (!target) return false;

              if (target.closest('.gdocs-handle') || target.closest('.gdocs-image-pill-toolbar')) {
                return false;
              }

              const imageNodeEl = target.closest('.editor-image-node') as HTMLElement | null;
              if (!imageNodeEl) return false;

              try {
                let pos: number | null = null;
                try {
                  pos = view.posAtDOM(imageNodeEl, 0);
                } catch (_) {}

                if (pos === null || pos === undefined || pos < 0) {
                  const coordsPos = view.posAtCoords({ left: event.clientX, top: event.clientY });
                  if (coordsPos) pos = coordsPos.pos;
                }

                if (typeof pos === 'number' && pos >= 0 && pos < view.state.doc.content.size) {
                  let targetPos = pos;
                  let node = view.state.doc.nodeAt(targetPos);
                  if (node?.type.name !== 'floatingImage' && targetPos > 0) {
                    const prevNode = view.state.doc.nodeAt(targetPos - 1);
                    if (prevNode?.type.name === 'floatingImage') {
                      targetPos = targetPos - 1;
                      node = prevNode;
                    }
                  }

                  if (node && node.type.name === 'floatingImage') {
                    const { selection } = view.state;
                    if (!(selection instanceof NodeSelection && selection.from === targetPos)) {
                      const tr = view.state.tr.setSelection(NodeSelection.create(view.state.doc, targetPos));
                      view.dispatch(tr);
                    }
                    view.focus();
                    return true;
                  }
                }
              } catch (e) {
                reportClientError('Error selecting image node on mousedown:', e);
              }
              return false;
            },
          },
          handleClickOn(view, _pos, node, nodePos, _event, _direct) {
            if (node.type.name === 'floatingImage') {
              const { selection } = view.state;
              if (!(selection instanceof NodeSelection && selection.from === nodePos)) {
                view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc, nodePos)));
              }
              view.focus();
              return true;
            }
            return false;
          },
        },
      }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(FloatingImageView);
  },
});
