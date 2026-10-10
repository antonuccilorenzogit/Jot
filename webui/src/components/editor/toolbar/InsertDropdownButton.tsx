import React from 'react';
import { type Editor as TiptapEditor } from '@tiptap/core';
import { Calculator, ImagePlus, Video } from 'lucide-react';

export const InsertImageButton = ({ onOpenImagePicker }: { onOpenImagePicker: () => void }) => {
  return (
    <button
      type="button"
      onClick={onOpenImagePicker}
      className="editor-button"
      title="Inserisci immagine"
    >
      <ImagePlus className="h-4 w-4" />
    </button>
  );
};

export const InsertMathButton = ({ editor }: { editor: TiptapEditor }) => {
  const handleInsert = () => {
    const latex = window.prompt('Inserisci formula LaTeX (es. E=mc^2, \\frac{a}{b}):', 'E=mc^2');
    if (latex && latex.trim()) {
      editor.chain().focus().insertContent({ type: 'mathInline', attrs: { latex: latex.trim() } }).run();
    }
  };

  return (
    <button
      type="button"
      onClick={handleInsert}
      className="editor-button"
      title="Inserisci formula matematica (LaTeX)"
    >
      <Calculator className="h-4 w-4" />
    </button>
  );
};

export const InsertYoutubeButton = ({ editor }: { editor: TiptapEditor }) => {
  const handleInsert = () => {
    const url = window.prompt('Inserisci URL del video YouTube:');
    if (url && url.trim()) {
      (editor.chain().focus() as unknown as { setYoutubeVideo: (options: { src: string }) => { run: () => boolean } }).setYoutubeVideo({ src: url.trim() }).run();
    }
  };

  return (
    <button
      type="button"
      onClick={handleInsert}
      className="editor-button"
      title="Inserisci video YouTube"
    >
      <Video className="h-4 w-4" />
    </button>
  );
};
