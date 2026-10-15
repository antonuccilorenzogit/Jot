import { describe, expect, it } from 'vitest';
import {
  buildLessonJob,
  estimateAudioRequests,
  estimateLessonRequests,
  isBusyHour,
  lessonMode,
  nextQuietStart,
} from './lessonJob';
import { latexToReadable } from './utils';

const audio = { id: 'a', name: 'a.m4a', size: 1, duration: 9000, path: '/a.m4a' };
const slides = { path: '/s.pdf', name: 's.pdf', size: 1, pages: 60, format: 'pdf' };
const book = { path: '/b.pdf', name: 'b.pdf', size: 1, pages: 300, format: 'pdf' };

describe('lessonJob', () => {
  it('maps sources to a mode', () => {
    expect(lessonMode({ audio: null, slides: null, book: null })).toBe('empty');
    expect(lessonMode({ audio: null, slides: null, book })).toBe('invalid');
    expect(lessonMode({ audio: null, slides, book })).toBe('notes');
    expect(lessonMode({ audio, slides, book })).toBe('audio');
  });

  it('estimates requests like the pipeline', () => {
    // 2h30: 11 blocks of 14:30 + 4 revision blocks of ~22k characters
    expect(estimateAudioRequests(9000)).toEqual({ chunks: 11, revisions: 4, total: 15 });
    expect(estimateAudioRequests(0).total).toBe(0);
    // + 1 for the sintesi
    expect(estimateLessonRequests({ audio, slides, book })).toBe(16);
    // a second part adds its minutes: 2h30 + 2h30 = 5h → 21 blocks + 8 revisions + sintesi
    const part = { path: '/b.m4a', name: 'b.m4a', size: 1, duration: 9000 };
    expect(estimateLessonRequests({ audio, slides: null, book: null, parts: [part] })).toBe(
      estimateAudioRequests(18000).total + 1,
    );
    expect(estimateLessonRequests({ audio: null, slides, book })).toBeGreaterThan(0);
  });

  it('joins a second audio part and keeps the lesson date', () => {
    const part = { path: '/b.m4a', name: 'b.m4a', size: 2, duration: 1800 };
    const job = buildLessonJob(
      { audio, slides: null, book: null, parts: [part] },
      { bookPages: '', title: 'Diritto', course: 'Diritto privato', lessonDate: '2026-10-12' },
    );
    expect(job?.id).toBe('lesson::/a.m4a::::::::+/b.m4a');
    expect(job?.duration).toBe(10800);
    expect(job?.size).toBe(3);
    expect(job?.lessonDate).toBe('2026-10-12');
    expect(job?.lesson?.audioParts).toEqual([part]);
  });

  it('keeps audio-only jobs identical to the classic queue', () => {
    const job = buildLessonJob({ audio, slides: null, book: null }, { bookPages: '', title: '', course: '' });
    expect(job).toMatchObject({ id: 'a', name: 'a.m4a', kind: 'audio', path: '/a.m4a' });
    expect(job?.lesson).toBeUndefined();
  });

  it('book pages only matter with a book', () => {
    const job = buildLessonJob({ audio, slides, book: null }, { bookPages: '1-3', title: 'T', course: 'C' });
    expect(job?.id).toBe('lesson::/a.m4a::/s.pdf::::');
    expect(job?.lesson).toEqual({ slidesPath: '/s.pdf', slidesName: 's.pdf', slidesCount: 60 });
  });

  it('busy hours and the quiet start', () => {
    expect(isBusyHour(new Date(2026, 0, 1, 16, 0))).toBe(true);
    expect(isBusyHour(new Date(2026, 0, 1, 22, 0))).toBe(false);
    const late = nextQuietStart(new Date(2026, 0, 1, 22, 0));
    expect([late.getDate(), late.getHours(), late.getMinutes()]).toEqual([2, 21, 30]);
  });
});

describe('latexToReadable', () => {
  it('turns common LaTeX into readable text', () => {
    expect(latexToReadable('E = mc^2')).toBe('E = mc²');
    expect(latexToReadable('\\frac{a}{b} \\cdot \\alpha_1')).toBe('(a)/(b) · α₁');
    expect(latexToReadable('\\sqrt{x^{2}+1}')).toBe('√(x²+1)');
    expect(latexToReadable('\\text{RTT} = 2 \\times d')).toBe('RTT = 2 × d');
  });
});
