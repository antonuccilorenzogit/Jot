import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { InsertImageButton, InsertMathButton, InsertYoutubeButton } from './InsertDropdownButton';
import type { Editor as TiptapEditor } from '@tiptap/core';

describe('InsertButtons', () => {
  it('InsertImageButton calls onOpenImagePicker when clicked', () => {
    const onOpen = vi.fn();
    render(<InsertImageButton onOpenImagePicker={onOpen} />);
    const btn = screen.getByTitle('Inserisci immagine');
    fireEvent.click(btn);
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it('InsertMathButton prompts and inserts LaTeX content', () => {
    const insertContentMock = vi.fn().mockReturnThis();
    const runMock = vi.fn().mockReturnValue(true);
    const editor = {
      chain: vi.fn().mockReturnValue({
        focus: vi.fn().mockReturnThis(),
        insertContent: insertContentMock,
        run: runMock,
      }),
    };

    vi.spyOn(window, 'prompt').mockReturnValue('E=mc^2');
    render(<InsertMathButton editor={editor as unknown as TiptapEditor} />);
    const btn = screen.getByTitle('Inserisci formula matematica (LaTeX)');
    fireEvent.click(btn);

    expect(insertContentMock).toHaveBeenCalledWith({
      type: 'mathInline',
      attrs: { latex: 'E=mc^2' },
    });
    expect(runMock).toHaveBeenCalled();
  });

  it('InsertYoutubeButton prompts and sets YouTube video', () => {
    const setYoutubeVideoMock = vi.fn().mockReturnValue({ run: vi.fn().mockReturnValue(true) });
    const editor = {
      chain: vi.fn().mockReturnValue({
        focus: vi.fn().mockReturnValue({
          setYoutubeVideo: setYoutubeVideoMock,
        }),
      }),
    };

    vi.spyOn(window, 'prompt').mockReturnValue('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
    render(<InsertYoutubeButton editor={editor as unknown as TiptapEditor} />);
    const btn = screen.getByTitle('Inserisci video YouTube');
    fireEvent.click(btn);

    expect(setYoutubeVideoMock).toHaveBeenCalledWith({
      src: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    });
  });
});
