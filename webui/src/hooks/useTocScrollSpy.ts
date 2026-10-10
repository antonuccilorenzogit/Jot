import { useEffect, useRef, useState } from 'react';
import type { Heading } from '../editorExtensions';

interface UseTocScrollSpyOptions {
  tocHeadings: Heading[];
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
}

export function useTocScrollSpy({
  tocHeadings,
  scrollContainerRef,
}: UseTocScrollSpyOptions) {
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);
  const tocHeadingsRef = useRef(tocHeadings);
  useEffect(() => { tocHeadingsRef.current = tocHeadings; }, [tocHeadings]);

  const tocNavRef = useRef<HTMLElement>(null);
  const tocStickyRef = useRef<HTMLDivElement>(null);
  const headingElsCacheRef = useRef<HTMLElement[] | null>(null);
  useEffect(() => { headingElsCacheRef.current = null; }, [tocHeadings]);
  const tocScrollRafRef = useRef<number | null>(null);

  useEffect(() => {
    const container = scrollContainerRef.current;
    const sticky = tocStickyRef.current;
    if (!container || !sticky) return;
    const update = () => { sticky.style.height = `${Math.max(100, container.clientHeight - 60)}px`; };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(container);
    return () => ro.disconnect();
  }, [scrollContainerRef]);

  useEffect(() => {
    if (!activeHeadingId || !tocNavRef.current) return;
    const nav = tocNavRef.current;
    const activeBtn = nav.querySelector<HTMLElement>('.toc-item-active');
    if (!activeBtn) return;
    const navRect = nav.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();
    if (btnRect.top < navRect.top) {
      nav.scrollTop += btnRect.top - navRect.top;
    } else if (btnRect.bottom > navRect.bottom) {
      nav.scrollTop += btnRect.bottom - navRect.bottom;
    }
  }, [activeHeadingId]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const handleScroll = () => {
      if (tocScrollRafRef.current !== null) return;
      tocScrollRafRef.current = requestAnimationFrame(() => {
        tocScrollRafRef.current = null;
        if (!headingElsCacheRef.current) {
          headingElsCacheRef.current = Array.from(
            container.querySelectorAll<HTMLElement>(
              '.tiptap-editor h1,.tiptap-editor h2,.tiptap-editor h3,.tiptap-editor h4,.tiptap-editor h5'
            )
          );
        }
        const containerTop = container.getBoundingClientRect().top;
        let activeEl: HTMLElement | null = null;
        for (const el of headingElsCacheRef.current) {
          if (el.getBoundingClientRect().top - containerTop <= 64) {
            activeEl = el;
          } else {
            break;
          }
        }
        if (activeEl) {
          const text = activeEl.textContent?.trim() ?? '';
          const level = parseInt(activeEl.tagName[1]);
          const match = tocHeadingsRef.current.find(
            h => h.level === level && h.text.trim() === text
          );
          setActiveHeadingId(match?.id ?? null);
        } else {
          setActiveHeadingId(null);
        }
      });
    };
    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      container.removeEventListener('scroll', handleScroll);
      if (tocScrollRafRef.current !== null) cancelAnimationFrame(tocScrollRafRef.current);
    };
  }, [scrollContainerRef]);

  return {
    activeHeadingId,
    tocNavRef,
    tocStickyRef,
  };
}
