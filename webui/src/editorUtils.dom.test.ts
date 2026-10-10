import { describe, it, expect, beforeEach } from 'vitest';
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { getWordRangeAtPos, getLastHighlightColor, setLastHighlightColor } from './editorUtils';

describe('editorUtils', () => {
  describe('getLastHighlightColor and setLastHighlightColor', () => {
    beforeEach(() => {
      localStorage.clear();
    });

    it('returns default highlight color when none saved', () => {
      expect(getLastHighlightColor()).toBe('#fef08a');
    });

    it('saves and retrieves highlight color', () => {
      setLastHighlightColor('#00ff00');
      expect(getLastHighlightColor()).toBe('#00ff00');
    });

    it('ignores white color when setting', () => {
      setLastHighlightColor('#ffffff');
      expect(getLastHighlightColor()).toBe('#fef08a');
    });
  });

  describe('getWordRangeAtPos', () => {
    const createTestEditor = (text: string) => {
      return new Editor({
        extensions: [StarterKit],
        content: `<p>${text}</p>`,
      });
    };

    it('selects word excluding trailing space when double clicked inside word', () => {
      const editor = createTestEditor('gli eosinofili iniziano');
      const view = editor.view;

      // Click on 's' in 'eosinofili' (pos 8)
      const range = getWordRangeAtPos(view, 8);
      expect(range).not.toBeNull();
      expect(range).toEqual({ from: 5, to: 15 });

      // Verify doc text in that range is "eosinofili"
      const selectedText = view.state.doc.textBetween(range!.from, range!.to);
      expect(selectedText).toBe('eosinofili');
      editor.destroy();
    });

    it('selects exact word when clicked on trailing space immediately following word', () => {
      const editor = createTestEditor('gli eosinofili iniziano');
      const view = editor.view;
      // Position 15 is the space right after 'eosinofili'
      const range = getWordRangeAtPos(view, 15);
      expect(range).not.toBeNull();
      expect(range).toEqual({ from: 5, to: 15 });
      expect(view.state.doc.textBetween(range!.from, range!.to)).toBe('eosinofili');
      editor.destroy();
    });

    it('handles accented characters and numbers correctly', () => {
      const text = 'reazione allergica reazione123 difficoltà';
      const editor = createTestEditor(text);
      const view = editor.view;
      const startIdx = text.indexOf('difficoltà');
      const pos = 1 + startIdx + 2; // inside 'difficoltà'
      const range = getWordRangeAtPos(view, pos);
      expect(range).not.toBeNull();
      const selectedText = view.state.doc.textBetween(range!.from, range!.to);
      expect(selectedText).toBe('difficoltà');
      editor.destroy();
    });

    it('returns null when clicked in empty or non-word space', () => {
      const editor = createTestEditor('   ');
      const view = editor.view;
      const range = getWordRangeAtPos(view, 2);
      expect(range).toBeNull();
      editor.destroy();
    });
  });
});
