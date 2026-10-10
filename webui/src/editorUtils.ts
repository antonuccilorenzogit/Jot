import type { Node as ProseMirrorNode } from '@tiptap/pm/model';
import type { EditorView } from '@tiptap/pm/view';

const DEFAULT_HIGHLIGHT_COLOR = '#fef08a';
const HIGHLIGHT_COLOR_KEY = 'jot_last_highlight_color';

export const getLastHighlightColor = (): string => {
  try {
    return localStorage.getItem(HIGHLIGHT_COLOR_KEY) || DEFAULT_HIGHLIGHT_COLOR;
  } catch {
    return DEFAULT_HIGHLIGHT_COLOR;
  }
};

export const setLastHighlightColor = (color: string): void => {
  if (!color || color === '#ffffff') return;
  try {
    localStorage.setItem(HIGHLIGHT_COLOR_KEY, color);
  } catch {
    // Ignore storage quota / restriction errors
  }
};

/**
 * Calculates the exact word range (excluding trailing/leading spaces) at a given document position on double click.
 */
export const getWordRangeAtPos = (
  view: Pick<EditorView, 'state'> | { state: { doc: ProseMirrorNode } },
  pos: number,
): { from: number; to: number } | null => {
  const $pos = view.state.doc.resolve(pos);
  if (!$pos.parent.isTextblock) return null;

  const parent = $pos.parent;
  const parentStart = $pos.start();

  let fullText = '';
  const posMap: number[] = [];

  parent.forEach((child: ProseMirrorNode, offset: number) => {
    const childDocPos = parentStart + offset;
    if (child.isText && child.text) {
      for (let i = 0; i < child.text.length; i++) {
        posMap.push(childDocPos + i);
        fullText += child.text[i];
      }
    } else {
      for (let i = 0; i < child.nodeSize; i++) {
        posMap.push(childDocPos + i);
        fullText += ' ';
      }
    }
  });

  if (!fullText.length || posMap.length === 0) return null;

  let charIdx = pos - parentStart;
  if (charIdx < 0) charIdx = 0;
  if (charIdx >= fullText.length) charIdx = fullText.length - 1;

  const isWordChar = (ch: string) => /[\p{L}\p{N}_]/u.test(ch);

  if (!isWordChar(fullText[charIdx])) {
    if (charIdx > 0 && isWordChar(fullText[charIdx - 1])) {
      charIdx = charIdx - 1;
    } else {
      return null;
    }
  }

  let startIdx = charIdx;
  while (startIdx > 0 && isWordChar(fullText[startIdx - 1])) {
    startIdx--;
  }

  let endIdx = charIdx;
  while (endIdx < fullText.length - 1 && isWordChar(fullText[endIdx + 1])) {
    endIdx++;
  }

  const fromDocPos = posMap[startIdx];
  const toDocPos = posMap[endIdx] + 1;

  return { from: fromDocPos, to: toDocPos };
};
