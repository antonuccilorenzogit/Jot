import { describe, it, expect, vi } from 'vitest';
import katex from 'katex';
import { escapeHtml, MathInline, MathBlock } from './editorExtensions';

describe('escapeHtml', () => {
  it('escapes &, <, >, ", and single quotes', () => {
    const raw = '<img src="x" onerror=\'alert(1)\'> & test';
    const escaped = escapeHtml(raw);
    expect(escaped).toBe('&lt;img src=&quot;x&quot; onerror=&#039;alert(1)&#039;&gt; &amp; test');
    expect(escaped).not.toContain('<');
    expect(escaped).not.toContain('>');
  });

  it('safely handles null, undefined, or non-string inputs', () => {
    expect(escapeHtml(null as unknown as string)).toBe('');
    expect(escapeHtml(undefined as unknown as string)).toBe('');
    expect(escapeHtml(123 as unknown as string)).toBe('123');
  });
});

describe('Math nodes KaTeX fallback escaping', () => {
  it('escapes latex in MathInline.renderHTML fallback when katex throws', () => {
    const spy = vi.spyOn(katex, 'renderToString').mockImplementation(() => {
      throw new Error('KaTeX parser failure');
    });

    const maliciousLatex = '<img src=x onerror=alert("xss")>';
    const renderFn = MathInline.config.renderHTML as unknown as (props: { HTMLAttributes: Record<string, unknown> }) => unknown;
    const rendered = renderFn({
      HTMLAttributes: { latex: maliciousLatex },
    });

    spy.mockRestore();

    expect(rendered).toBeDefined();
    // In TipTap/ProseMirror DOM output format: ['span', attrs, ['span', { class: ... }, content]]
    const innerSpan = (rendered as [string, Record<string, unknown>, [string, Record<string, unknown>, string]])[2];
    expect(innerSpan[2]).not.toContain('<img');
    expect(innerSpan[2]).toContain('&lt;img');
  });

  it('escapes latex in MathBlock.renderHTML fallback when katex throws', () => {
    const spy = vi.spyOn(katex, 'renderToString').mockImplementation(() => {
      throw new Error('KaTeX parser failure');
    });

    const maliciousLatex = '<script>alert("xss")</script>';
    const renderBlockFn = MathBlock.config.renderHTML as unknown as (props: { HTMLAttributes: Record<string, unknown> }) => unknown;
    const rendered = renderBlockFn({
      HTMLAttributes: { latex: maliciousLatex },
    });

    spy.mockRestore();

    expect(rendered).toBeDefined();
    const innerDiv = (rendered as [string, Record<string, unknown>, [string, Record<string, unknown>, string]])[2];
    expect(innerDiv[2]).not.toContain('<script');
    expect(innerDiv[2]).toContain('&lt;script');
  });
});
