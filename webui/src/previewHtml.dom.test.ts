import { describe, expect, it } from 'vitest';
import { normalizePreviewHtmlContent, ALLOWED_STYLE_PROPS, EDITOR_IMAGE_ALLOWED_DATA_ATTRS } from './previewHtml';

describe('normalizePreviewHtmlContent', () => {
  it('returns empty string for empty input', () => {
    const result = normalizePreviewHtmlContent('');
    expect(result).toBe('');
  });

  it('strips disallowed data-* attributes', () => {
    const html = '<p data-bad-attr="x">hello</p>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).not.toContain('data-bad-attr');
    expect(result).toContain('hello');
  });

  it('strips align attribute', () => {
    const html = '<p align="center">text</p>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).not.toContain('align="center"');
  });

  it('preserves allowed style properties', () => {
    const html = '<p style="color: red; font-size: 14px;">styled</p>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).toContain('color');
    expect(result).toContain('font-size');
  });

  it('strips disallowed style properties', () => {
    const html = '<p style="font-size: 14px; padding: 5px;">text</p>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).toContain('font-size');
    expect(result).not.toContain('padding');
  });

  it('removes style attribute entirely when no allowed props remain', () => {
    const html = '<p style="padding: 10px;">text</p>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).not.toContain('style=');
  });

  it('preserves editor image container data-* attributes', () => {
    const html = '<div data-editor-image data-width="60" data-bad="x"><img src="img.png" /></div>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).toContain('data-editor-image');
    expect(result).toContain('data-width');
    expect(result).not.toContain('data-bad');
  });

  it('strips class from editor image containers', () => {
    const html = '<div data-editor-image class="foo"><img src="img.png" /></div>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).not.toContain('class="foo"');
  });

  it('strips class from img inside editor image container', () => {
    const html = '<div data-editor-image><img src="img.png" class="bar" data-extra="x" /></div>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).not.toContain('class="bar"');
    expect(result).not.toContain('data-extra');
    expect(result).toContain('src="img.png"');
  });

  it('handles nested elements', () => {
    const html = '<div data-foo="x"><span data-bar="y">text</span></div>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).not.toContain('data-foo');
    expect(result).not.toContain('data-bar');
    expect(result).toContain('text');
  });

  it('preserves align="center" attribute on editor image containers and images', () => {
    const html = '<div data-editor-image align="center"><img src="img.png" align="center" /></div>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).toContain('align="center"');
  });

  it('preserves and computes width attribute for images inside editor image containers', () => {
    const html = '<div data-editor-image data-width="35"><img src="img.png" /></div>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).toContain('width="222"');
    expect(result).toContain('src="img.png"');
  });

  it('keeps existing width attribute if present on img inside editor image container', () => {
    const html = '<div data-editor-image data-width="50"><img src="img.png" width="317" /></div>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).toContain('width="317"');
  });

  it('exports ALLOWED_STYLE_PROPS with expected members', () => {
    expect(ALLOWED_STYLE_PROPS.has('color')).toBe(true);
    expect(ALLOWED_STYLE_PROPS.has('font-size')).toBe(true);
    expect(ALLOWED_STYLE_PROPS.has('margin')).toBe(true);
    expect(ALLOWED_STYLE_PROPS.has('width')).toBe(true);
    expect(ALLOWED_STYLE_PROPS.has('padding')).toBe(false);
  });

  it('preserves width style property on elements such as table cells or columns', () => {
    const html = '<table><colgroup><col style="width: 150px" /></colgroup></table>';
    const result = normalizePreviewHtmlContent(html);
    expect(result).toContain('style="width: 150px"');
  });

  it('exports EDITOR_IMAGE_ALLOWED_DATA_ATTRS with expected members', () => {
    expect(EDITOR_IMAGE_ALLOWED_DATA_ATTRS.has('data-editor-image')).toBe(true);
    expect(EDITOR_IMAGE_ALLOWED_DATA_ATTRS.has('data-width')).toBe(true);
    expect(EDITOR_IMAGE_ALLOWED_DATA_ATTRS.has('data-foo')).toBe(false);
  });
});
