import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FontFamilySelect, FontSizeSelect, HeadingSelect, ZoomSelect } from './TypographySelects';
import type { Editor as TiptapEditor } from '@tiptap/core';

const createMockEditor = (attrs: Record<string, unknown> = {}, activeChecks: Record<string, boolean> = {}) => {
  const runMock = vi.fn().mockReturnValue(true);
  const chainMock = {
    focus: vi.fn().mockReturnThis(),
    setParagraph: vi.fn().mockReturnThis(),
    setNode: vi.fn().mockReturnThis(),
    setHeading: vi.fn().mockReturnThis(),
    clearBlockFontSize: vi.fn().mockReturnThis(),
    setFontFamily: vi.fn().mockReturnThis(),
    unsetFontFamily: vi.fn().mockReturnThis(),
    setMark: vi.fn().mockReturnThis(),
    run: runMock,
  };

  const editor = {
    isActive: vi.fn((name: string, opts?: Record<string, unknown>) => {
      if (name === 'heading' && opts?.level) {
        return Boolean(activeChecks[`h${opts.level}`]);
      }
      return Boolean(activeChecks[name]);
    }),
    getAttributes: vi.fn((name: string) => {
      if (name === 'textStyle') return attrs;
      return {};
    }),
    chain: vi.fn().mockReturnValue(chainMock),
  };

  return { editor, chainMock };
};

describe('TypographySelects', () => {
  describe('HeadingSelect', () => {
    it('renders default Testo normale and changes to Titolo 1 with clearBlockFontSize when clicked', () => {
      const { editor, chainMock } = createMockEditor();
      render(<HeadingSelect editor={editor as unknown as TiptapEditor} />);

      const button = screen.getByTitle('Stile paragrafo');
      expect(button.textContent).toContain('Testo normale');

      fireEvent.click(button);
      const h1Option = screen.getByRole('button', { name: 'Titolo 1' });
      fireEvent.click(h1Option);

      expect(chainMock.clearBlockFontSize).toHaveBeenCalled();
      expect(chainMock.setHeading).toHaveBeenCalledWith({ level: 1 });
      expect(chainMock.run).toHaveBeenCalled();
    });

    it('changes to paragraph with clearBlockFontSize when Testo normale is selected', () => {
      const { editor, chainMock } = createMockEditor({}, { h2: true });
      render(<HeadingSelect editor={editor as unknown as TiptapEditor} />);

      const button = screen.getByTitle('Stile paragrafo');
      expect(button.textContent).toContain('Titolo 2');

      fireEvent.click(button);
      const pOption = screen.getByRole('button', { name: 'Testo normale' });
      fireEvent.click(pOption);

      expect(chainMock.clearBlockFontSize).toHaveBeenCalled();
      expect(chainMock.setParagraph).toHaveBeenCalled();
      expect(chainMock.run).toHaveBeenCalled();
    });
  });

  describe('FontFamilySelect', () => {
    it('renders Arial by default and changes to Georgia when selected', () => {
      const { editor, chainMock } = createMockEditor();
      render(<FontFamilySelect editor={editor as unknown as TiptapEditor} />);

      const button = screen.getByTitle('Carattere');
      expect(button.textContent).toContain('Arial');

      fireEvent.click(button);
      const georgiaOption = screen.getByRole('button', { name: 'Georgia' });
      fireEvent.click(georgiaOption);

      expect(chainMock.setFontFamily).toHaveBeenCalledWith('Georgia, serif');
      expect(chainMock.run).toHaveBeenCalled();
    });
  });

  describe('FontSizeSelect', () => {
    it('displays 11 by default for body text', () => {
      const { editor } = createMockEditor();
      render(<FontSizeSelect editor={editor as unknown as TiptapEditor} />);

      const button = screen.getByTitle('Dimensione carattere');
      expect(button.textContent).toContain('11');
    });

    it('displays 20 when heading 1 is active', () => {
      const { editor } = createMockEditor({}, { h1: true });
      render(<FontSizeSelect editor={editor as unknown as TiptapEditor} />);

      const button = screen.getByTitle('Dimensione carattere');
      expect(button.textContent).toContain('20');
    });

    it('displays explicit font size when set in textStyle', () => {
      const { editor } = createMockEditor({ fontSize: '18pt' });
      render(<FontSizeSelect editor={editor as unknown as TiptapEditor} />);

      const button = screen.getByTitle('Dimensione carattere');
      expect(button.textContent).toContain('18');
    });

    it('applies selected font size', () => {
      const { editor, chainMock } = createMockEditor();
      render(<FontSizeSelect editor={editor as unknown as TiptapEditor} />);

      const button = screen.getByTitle('Dimensione carattere');
      fireEvent.click(button);

      const sizeOption = screen.getByRole('button', { name: '16' });
      fireEvent.click(sizeOption);

      expect(chainMock.setMark).toHaveBeenCalledWith('textStyle', { fontSize: '16pt' });
      expect(chainMock.run).toHaveBeenCalled();
    });
  });

  describe('ZoomSelect', () => {
    it('displays 100% by default', () => {
      render(<ZoomSelect zoomLevel={100} onZoomChange={vi.fn()} />);
      const button = screen.getByTitle('Livello di zoom');
      expect(button.textContent).toContain('100%');
    });

    it('opens dropdown and selects a zoom level', () => {
      const onZoomChange = vi.fn();
      render(<ZoomSelect zoomLevel={100} onZoomChange={onZoomChange} />);

      const button = screen.getByTitle('Livello di zoom');
      fireEvent.click(button);

      const opt75 = screen.getByRole('button', { name: '75%' });
      fireEvent.click(opt75);

      expect(onZoomChange).toHaveBeenCalledWith(75);
    });
  });
});
