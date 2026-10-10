import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AUDIO_SEEK_EVENT, requestAudioSeek, sectionTimeFor } from './audioSeek';
import { formatAudioTime } from './editorExtensions';
import { ProcessingStatusBanner } from './components/ProcessingStatusBanner';

describe('audio seek from the notes', () => {
  it('finds the time of the section around a paragraph', () => {
    const root = document.createElement('div');
    root.innerHTML = '<h2 data-t="0">A</h2><p id="p1">uno</p><h2 data-t="2610">B</h2><p><strong id="s2">due</strong></p>';
    document.body.appendChild(root);
    expect(sectionTimeFor(root.querySelector('#p1')!, root)).toBe(0);
    expect(sectionTimeFor(root.querySelector('#s2')!, root)).toBe(2610);
    expect(sectionTimeFor(root.querySelector('h2[data-t="2610"]')!, root)).toBe(2610);
    root.remove();
  });

  it('dispatches a seek event', () => {
    const listener = vi.fn();
    window.addEventListener(AUDIO_SEEK_EVENT, listener);
    requestAudioSeek(90);
    requestAudioSeek(-1);
    window.removeEventListener(AUDIO_SEEK_EVENT, listener);
    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ time: 90, play: true });
  });

  it('formats chip labels', () => {
    expect(formatAudioTime('2610')).toBe('43:30');
    expect(formatAudioTime(4000)).toBe('1:06:40');
    expect(formatAudioTime(null)).toBe('0:00');
  });
});

describe('processing view explanation', () => {
  const base = {
    appState: 'processing' as const,
    currentModel: 'gemini-3.8-flash',
    activeProgress: 30,
    currentFileIndex: 0,
    currentBatchTotal: 1,
  };

  it('tells which minutes are being listened to and what slides do', () => {
    render(
      <ProcessingStatusBanner
        {...base}
        currentPhase="Fase 1/3: trascrizione (chunk 4/11)"
        workDone={{ chunks: 3, macro: 0 }}
        workTotals={{ chunks: 11, macro: 0 }}
        sources={{ slides: true }}
        quota={{ used: 6, limit: 20 }}
        currentFileName="Reti — Lezione 5"
      />,
    );
    expect(screen.getByText('Ascolto i minuti 43–58 e scrivo gli appunti. Le slide mi aiutano con termini e formule.')).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Trascrizione: blocco 4 di 11' })).toBeTruthy();
    expect(screen.getByRole('img', { name: '6 richieste usate su 20 oggi' })).toBeTruthy();
    expect(screen.getByText('Audio · Slide')).toBeTruthy();
  });

  it('mentions the book during revision', () => {
    render(
      <ProcessingStatusBanner
        {...base}
        currentPhase="Fase 2/3: revisione (blocco 2/4)"
        workDone={{ chunks: 11, macro: 1 }}
        workTotals={{ chunks: 11, macro: 4 }}
        sources={{ book: true }}
      />,
    );
    expect(screen.getByText(/chiarisco i passaggi difficili con il libro/)).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Revisione: sezione 2 di 4' })).toBeTruthy();
  });
});
