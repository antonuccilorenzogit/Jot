import React from 'react';
import type { Editor } from '@tiptap/core';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RichTextEditor } from './RichTextEditor';

describe('RichTextEditor Component', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders the editor container and initial content', async () => {
    const onEditorReady = vi.fn();
    const onChange = vi.fn();

    render(
      <RichTextEditor
        initialContent="<p>Prima pagina di appunti per anatomia</p>"
        onEditorReady={onEditorReady}
        onChange={onChange}
      />
    );

    const editorEl = document.querySelector('.tiptap-editor');
    expect(editorEl).toBeTruthy();

    // Verify initial content rendered
    expect(screen.getByText('Prima pagina di appunti per anatomia')).toBeTruthy();

    // Verify onEditorReady callback provided getHtml function
    await waitFor(() => expect(onEditorReady).toHaveBeenCalled());
    const getHtmlFn = onEditorReady.mock.calls[0][0];
    const html = getHtmlFn();
    expect(html).toContain('Prima pagina di appunti per anatomia');
  });

  it('renders table of contents sidebar toggle and responds to zoom', () => {
    const onTocToggle = vi.fn();

    const { rerender } = render(
      <RichTextEditor
        initialContent="<h2>Capitolo 1: Ossa del Cranio</h2><p>Dettagli capitolo...</p>"
        isTocOpen={false}
        onTocToggle={onTocToggle}
        zoomLevel={100}
      />
    );

    const tocBtn = screen.getByTitle('Apri indice');
    expect(tocBtn).toBeTruthy();

    const pageWrapper = document.querySelector('.editor-page') as HTMLElement;
    expect(pageWrapper).toBeTruthy();
    expect(pageWrapper.style.zoom).toBe('1');

    rerender(
      <RichTextEditor
        initialContent="<h2>Capitolo 1: Ossa del Cranio</h2><p>Dettagli capitolo...</p>"
        isTocOpen={false}
        onTocToggle={onTocToggle}
        zoomLevel={150}
      />
    );

    expect(pageWrapper.style.zoom).toBe('1.5');
  });

  it('preserves local edits through toolbar undo and redo', async () => {
    const onChange = vi.fn();
    render(<RichTextEditor initialContent="<p>Appunti originali</p>" onChange={onChange} />);
    const element = document.querySelector('.tiptap-editor') as HTMLElement & { editor: Editor };
    await waitFor(() => expect(element.editor).toBeTruthy());

    act(() => element.editor.commands.insertContentAt(element.editor.state.doc.content.size - 1, ' corretti'));
    expect(element.textContent).toBe('Appunti originali corretti');
    expect(onChange).toHaveBeenLastCalledWith('<p>Appunti originali corretti</p>');

    act(() => fireEvent.click(screen.getByTitle('Annulla (Ctrl+Z)')));
    expect(element.textContent).toBe('Appunti originali');
    expect(onChange).toHaveBeenLastCalledWith('<p>Appunti originali</p>');

    act(() => fireEvent.click(screen.getByTitle('Ripeti (Ctrl+Y)')));
    expect(element.textContent).toBe('Appunti originali corretti');
    expect(onChange).toHaveBeenLastCalledWith('<p>Appunti originali corretti</p>');
  });

  it('extracts headings and triggers onHeadingsChange', async () => {
    const onHeadingsChange = vi.fn();

    render(
      <RichTextEditor
        initialContent="<h2>Titolo Sezione 1</h2><p>Paragrafo</p><h3>Sotto Sezione</h3>"
        onHeadingsChange={onHeadingsChange}
      />
    );

    await waitFor(() => expect(onHeadingsChange).toHaveBeenCalled());
    const headings = onHeadingsChange.mock.calls[0][0];
    expect(headings.length).toBeGreaterThanOrEqual(1);
    expect(headings.some((h: { text: string }) => h.text === 'Titolo Sezione 1')).toBe(true);
  });

  it('removes inline fontSize mark when setting a heading on text with pre-existing font-size', async () => {
    let getHtmlFn: (() => string) | null = null;
    const onEditorReady = vi.fn((getHtml: () => string) => {
      getHtmlFn = getHtml;
    });

    render(
      <RichTextEditor
        initialContent='<p><span style="font-size: 11pt">Titolo con dimensione inline</span></p>'
        onEditorReady={onEditorReady}
      />
    );

    await waitFor(() => expect(onEditorReady).toHaveBeenCalled());
    expect(getHtmlFn).toBeTruthy();

    const headingDropdownBtn = screen.getByTitle('Stile paragrafo');
    expect(headingDropdownBtn).toBeTruthy();

    // The initial content has fontSize 11pt mark on span
    expect(getHtmlFn!()).toContain('font-size: 11pt');

    // Click heading dropdown and select Titolo 1
    act(() => {
      fireEvent.click(headingDropdownBtn);
    });
    const h1Option = await screen.findByRole('button', { name: 'Titolo 1' });
    act(() => {
      fireEvent.click(h1Option);
    });

    // Verify the output HTML is an h1 without inline font-size span
    await waitFor(() => {
      const html = getHtmlFn!();
      expect(html).toContain('<h1>');
      expect(html).not.toContain('font-size: 11pt');
      expect(html).toContain('Titolo con dimensione inline');
    });
  });

  it('preserves and correctly parses HTML tables without flattening cells', async () => {
    let getHtmlFn: (() => string) | null = null;
    const onEditorReady = vi.fn((getHtml: () => string) => {
      getHtmlFn = getHtml;
    });

    const tableHtml = '<table><thead><tr><th>ID Soggetto</th><th>Sesso</th><th>Età</th></tr></thead><tbody><tr><td>001</td><td>Maschio</td><td>45</td></tr></tbody></table>';

    render(
      <RichTextEditor
        initialContent={tableHtml}
        onEditorReady={onEditorReady}
      />
    );

    await waitFor(() => expect(onEditorReady).toHaveBeenCalled());
    expect(getHtmlFn).toBeTruthy();

    const outputHtml = getHtmlFn!();
    expect(outputHtml).toContain('<table');
    expect(outputHtml).toContain('ID Soggetto');
    expect(outputHtml).toContain('Maschio');
    expect(outputHtml).not.toContain('IDSoggettoSessoEtà');
  });
});
