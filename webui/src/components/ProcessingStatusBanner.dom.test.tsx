import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ProcessingStatusBanner } from './ProcessingStatusBanner';

describe('ProcessingStatusBanner', () => {
  it('shows the active revision section instead of 0/x', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Fase 2/3: revisione"
        currentModel="gemini-3.6-flash"
        activeProgress={86}
        workDone={{ chunks: 8, macro: 0 }}
        workTotals={{ chunks: 11, macro: 11 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="FISIOLOGIA 2, LEZIONE 5.mp3"
        startedAt={Date.now() - 90_000}
      />,
    );

    expect(screen.getByText('Sezione 1 di 11')).toBeTruthy();
    expect(screen.queryByText(/ETA/i)).toBeNull();
  });

  it('renders explanatory tooltips for each step', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Fase 1/3: trascrizione (chunk 2/6)"
        currentModel="gemini-3.6-flash"
        activeProgress={34}
        workDone={{ chunks: 1, macro: 0 }}
        workTotals={{ chunks: 6, macro: 3 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="lesson.mp3"
      />,
    );

    expect(screen.getByText(/Normalizza l'audio/i)).toBeTruthy();
    expect(screen.getByText(/genera la prima sbobinatura dettagliata/i)).toBeTruthy();
    expect(screen.getByText(/ripulito, organizzato e reso più chiaro/i)).toBeTruthy();
  });

  it('shows file counter chip when currentBatchTotal > 1', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Fase 1/3: trascrizione (chunk 1/3)"
        currentModel="gemini-2.5-flash"
        activeProgress={20}
        workDone={{ chunks: 0, macro: 0 }}
        workTotals={{ chunks: 3, macro: 3 }}
        currentFileIndex={1}
        currentBatchTotal={3}
        currentFileName="lesson.mp3"
        startedAt={Date.now() - 30_000}
      />,
    );
    expect(screen.getByText('File 2 di 3')).toBeTruthy();
  });

  it('shows wait banner for Server Gemini occupato phase', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Server Gemini occupato — ritento tra 3s"
        currentModel="gemini-2.5-flash"
        activeProgress={30}
        workDone={{ chunks: 2, macro: 0 }}
        workTotals={{ chunks: 6, macro: 6 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="lesson.mp3"
      />,
    );
    expect(screen.getByText('In attesa...')).toBeTruthy();
  });

  it('shows pause banner for Rate limit phase', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Rate limit: attendo 60s"
        currentModel="gemini-2.5-flash"
        activeProgress={40}
        workDone={{ chunks: 3, macro: 0 }}
        workTotals={{ chunks: 6, macro: 6 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="lesson.mp3"
      />,
    );
    expect(screen.getByText('Pausa automatica')).toBeTruthy();
  });

  it('shows all-done stepper for __completed__ phase', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="__completed__"
        currentModel="gemini-2.5-flash"
        activeProgress={100}
        workDone={{ chunks: 6, macro: 6 }}
        workTotals={{ chunks: 6, macro: 6 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="lesson.mp3"
      />,
    );
    expect(screen.getByText('Sbobinatura completata!')).toBeTruthy();
  });

  it('shows macro progress from (blocco X/Y) regex in Fase 2/3', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Fase 2/3: revisione (blocco 3/8)"
        currentModel="gemini-2.5-flash"
        activeProgress={40}
        workDone={{ chunks: 6, macro: 3 }}
        workTotals={{ chunks: 6, macro: 8 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="lesson.mp3"
      />,
    );
    expect(screen.getByText('Sezione 3 di 8')).toBeTruthy();
  });

  it('shows preconversione as active step during Fase 0/3', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Fase 0/3: preconversione"
        currentModel="gemini-2.5-flash"
        activeProgress={5}
        workDone={{ chunks: 0, macro: 0 }}
        workTotals={{ chunks: 0, macro: 0 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="lesson.mp3"
      />,
    );
    expect(screen.getByText('Pre-conversione audio')).toBeTruthy();
  });

  it('renders without progress label when phase does not match any known pattern', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="In attesa"
        currentModel="gemini-2.5-flash"
        activeProgress={0}
        workDone={{ chunks: 0, macro: 0 }}
        workTotals={{ chunks: 0, macro: 0 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="lesson.mp3"
      />,
    );
    expect(screen.queryByText(/Blocco|Sezione/)).toBeNull();
  });

  it('shows Fase 1/3 progress label when no chunk number in phase', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Fase 1/3: preconversione"
        currentModel="gemini-2.5-flash"
        activeProgress={10}
        workDone={{ chunks: 0, macro: 0 }}
        workTotals={{ chunks: 5, macro: 5 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="lesson.mp3"
      />,
    );
    expect(screen.getByText(/Blocco \d+ di 5/)).toBeTruthy();
  });

  it('shows hours in elapsed chip when startedAt is > 1 hour ago', () => {
    render(
      <ProcessingStatusBanner
        appState="processing"
        currentPhase="Fase 2/3: revisione"
        currentModel="gemini-2.5-flash"
        activeProgress={50}
        workDone={{ chunks: 10, macro: 5 }}
        workTotals={{ chunks: 10, macro: 10 }}
        currentFileIndex={0}
        currentBatchTotal={1}
        currentFileName="long.mp3"
        startedAt={Date.now() - 4_000_000}
      />,
    );
    expect(screen.getByText(/\d+h \d+m/)).toBeTruthy();
  });

});
