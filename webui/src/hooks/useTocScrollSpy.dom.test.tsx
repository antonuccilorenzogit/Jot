import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useTocScrollSpy } from './useTocScrollSpy';
import type { Heading } from '../editorExtensions';

describe('useTocScrollSpy Hook', () => {
  const headings: Heading[] = [
    { id: 'heading-1', text: 'Introduzione', level: 1 },
    { id: 'heading-2', text: 'Capitolo 1', level: 2 },
  ];

  it('initializes with null active heading and valid refs', () => {
    const scrollContainerRef = { current: document.createElement('div') };
    const { result } = renderHook(() =>
      useTocScrollSpy({
        tocHeadings: headings,
        scrollContainerRef,
      })
    );

    expect(result.current.activeHeadingId).toBeNull();
    expect(result.current.tocNavRef).toBeDefined();
    expect(result.current.tocStickyRef).toBeDefined();
  });
});
