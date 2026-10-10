import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import { DiagnosticsSection, type DisplayCheck } from './DiagnosticsSection';
import type { ApiUsageResult } from '../../../bridge';
import { APP_VERSION } from '../../../branding';

afterEach(() => { delete window.pywebview; });

describe('DiagnosticsSection', () => {
  const dummyChecks: DisplayCheck[] = [
    {
      id: 'api_key',
      label: 'API Key Gemini',
      status: 'ok',
      message: 'Chiave API valida',
    },
    {
      id: 'ffmpeg',
      label: 'FFmpeg',
      status: 'pending',
      message: 'In attesa di verifica',
    },
  ];

  it('exports the selected sbobina and handles cancellation and export failure', async () => {
    const exportBundle = vi.fn().mockResolvedValueOnce({ ok: true, cancelled: true }).mockResolvedValueOnce({ ok: false, error: 'Disk full' }).mockResolvedValue({ ok: true });
    window.pywebview = { api: {
      list_diagnostic_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [{ path: 'archive/lesson', label: 'Lezione' }] }),
      export_diagnostics: exportBundle,
    } } as unknown as NonNullable<typeof window.pywebview>;
    const copy = vi.fn().mockResolvedValue(undefined);
    const validate = vi.fn();
    render(<DiagnosticsSection isValidatingEnvironment={false} onRunValidation={validate} validationResult={null} displayChecks={dummyChecks} onCopyReport={copy} />);
    await screen.findByText('Lezione');
    const environment = within(screen.getByRole('region', { name: 'Verifica ambiente' }));
    const support = within(screen.getByRole('region', { name: 'Report per assistenza' }));
    expect(environment.getByText('FFmpeg')).toBeTruthy();
    expect(environment.queryByRole('button', { name: 'Esporta diagnostica' })).toBeNull();
    expect(environment.queryByLabelText('Sbobina con il problema (facoltativa)')).toBeNull();
    expect(support.getByLabelText('Sbobina con il problema (facoltativa)')).toBeTruthy();
    expect(support.getByRole('button', { name: 'Copia report diagnostico' })).toBeTruthy();
    expect(support.getByRole('button', { name: 'Apri cartella log' })).toBeTruthy();
    expect(support.queryByRole('button', { name: 'Verifica ambiente' })).toBeNull();
    fireEvent.click(screen.getByLabelText('Sbobina con il problema (facoltativa)'));
    fireEvent.click(screen.getByRole('option', { name: 'Lezione' }));
    fireEvent.click(environment.getByRole('button', { name: 'Verifica ambiente' }));
    expect(validate).toHaveBeenCalledOnce();
    const button = screen.getByRole('button', { name: 'Esporta diagnostica' });
    await act(async () => { fireEvent.click(button); });
    expect(exportBundle).toHaveBeenLastCalledWith('archive/lesson', APP_VERSION);
    expect(screen.queryByText('Pacchetto diagnostico salvato.')).toBeNull();
    await act(async () => { fireEvent.click(button); });
    expect(screen.getByRole('alert').textContent).toContain('Disk full');
    await act(async () => { fireEvent.click(button); });
    expect(screen.getByRole('status').textContent).toContain('Pacchetto diagnostico salvato.');
    await act(async () => { fireEvent.click(screen.getByLabelText('Copia report diagnostico')); });
    expect(copy).toHaveBeenCalledWith('archive/lesson');
  });

  it('renders diagnostics checks and handles run validation', () => {
    const onRunValidation = vi.fn();
    render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={onRunValidation}
        validationResult={null}
        displayChecks={dummyChecks}
      />
    );

    expect(screen.getByText('Verifica ambiente')).toBeTruthy();
    expect(screen.getByText('API Key Gemini')).toBeTruthy();
    expect(screen.getByText('Chiave API valida')).toBeTruthy();
    expect(screen.getByText('FFmpeg')).toBeTruthy();
    expect(screen.getByText('da verificare')).toBeTruthy();
    expect(screen.queryByText('In attesa di verifica')).toBeNull();

    expect(screen.getByText('Verifica ora')).toBeTruthy();

    const validateBtn = screen.getByRole('button', { name: 'Verifica ambiente' });
    fireEvent.click(validateBtn);
    expect(onRunValidation).toHaveBeenCalled();
  });

  it('renders "Verifica in corso..." and is disabled when isValidatingEnvironment is true', () => {
    render(
      <DiagnosticsSection
        isValidatingEnvironment={true}
        onRunValidation={vi.fn()}
        validationResult={null}
        displayChecks={dummyChecks}
      />
    );

    const btn = screen.getByTitle('Verifica in corso…');
    expect(btn).toBeTruthy();
    expect(btn.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('Verifica in corso...')).toBeTruthy();
  });

  it('renders "Riesegui" button with appropriate label when validationResult is present', () => {
    const onRunValidation = vi.fn();
    render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={onRunValidation}
        validationResult={{ ok: true, summary: 'Tutti i controlli superati', checks: [] }}
        displayChecks={dummyChecks}
      />
    );

    const rieseguiBtn = screen.getByLabelText('Riesegui verifica ambiente');
    expect(rieseguiBtn).toBeTruthy();
    expect(screen.getByText('Riesegui')).toBeTruthy();

    fireEvent.click(rieseguiBtn);
    expect(onRunValidation).toHaveBeenCalled();
  });

  it('renders validation summary banner when validationResult is present', () => {
    const { container } = render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={vi.fn()}
        validationResult={{ ok: true, summary: 'Tutti i controlli superati con successo', checks: [] }}
        displayChecks={dummyChecks}
      />
    );

    expect(screen.getByText('Tutti i controlli superati con successo')).toBeTruthy();
    expect(container.querySelector('.alert-card.is-success')).toBeTruthy();
  });

  it('renders warning summary banner when validationResult has warnings', () => {
    const { container } = render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={vi.fn()}
        validationResult={{
          ok: true,
          has_warnings: true,
          summary: 'Ambiente pronto con avvisi: verifica le segnalazioni.',
          checks: [{ id: 'api_key', label: 'API Key Gemini', status: 'warning', message: 'API key assente' }],
        }}
        displayChecks={dummyChecks}
      />
    );

    expect(screen.getByText('Ambiente pronto con avvisi: verifica le segnalazioni.')).toBeTruthy();
    expect(container.querySelector('.alert-card.is-warning')).toBeTruthy();
  });

  it('renders error summary banner when validationResult has errors', () => {
    const { container } = render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={vi.fn()}
        validationResult={{
          ok: false,
          summary: 'Ambiente incompleto: correggi gli errori segnalati.',
          checks: [{ id: 'ffmpeg', label: 'FFmpeg', status: 'error', message: 'FFmpeg mancante' }],
        }}
        displayChecks={dummyChecks}
      />
    );

    expect(screen.getByText('Ambiente incompleto: correggi gli errori segnalati.')).toBeTruthy();
    expect(container.querySelector('.alert-card.is-error')).toBeTruthy();
  });

  it('calls onCopyReport and shows success toast when copy succeeds', async () => {
    const onCopyReport = vi.fn().mockResolvedValue(undefined);
    render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={vi.fn()}
        validationResult={null}
        displayChecks={dummyChecks}
        onCopyReport={onCopyReport}
      />
    );

    const copyBtn = screen.getByLabelText('Copia report diagnostico');
    fireEvent.click(copyBtn);

    expect(onCopyReport).toHaveBeenCalledTimes(1);
    expect(await screen.findByTitle('Report copiato!')).toBeTruthy();
  });

  it('does not show success toast when onCopyReport fails', async () => {
    const onCopyReport = vi.fn().mockRejectedValue(new Error('Generation failed'));
    render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={vi.fn()}
        validationResult={null}
        displayChecks={dummyChecks}
        onCopyReport={onCopyReport}
      />
    );

    const copyBtn = screen.getByLabelText('Copia report diagnostico');
    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(onCopyReport).toHaveBeenCalledTimes(1);
    expect(screen.queryByTitle('Report copiato!')).toBeNull();
  });

  it('calls onOpenLogs when clicking open logs button', () => {
    const onOpenLogs = vi.fn();
    render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={vi.fn()}
        validationResult={null}
        displayChecks={dummyChecks}
        onOpenLogs={onOpenLogs}
      />
    );

    const openLogsBtn = screen.getByLabelText('Apri cartella log');
    fireEvent.click(openLogsBtn);

    expect(onOpenLogs).toHaveBeenCalledTimes(1);
  });

  it('does not render telemetry even if apiUsage is provided (moved to QuotasSection)', () => {
    const apiUsageWithTelemetry: ApiUsageResult = {
      schema_version: 2,
      quota_date: '2026-09-17',
      primary_status: 'operational',
      status_message: 'API Google Gemini operative.',
      next_reset_info: 'Reset quote: ore 09:00',
      is_degraded_mode: false,
      degraded_reason: null,
      project_limits: {},
      work_stats: {
        chunks_completed: 34,
        revisions_completed: 16,
        sbobine_completed: 4,
      },
      telemetry: {
        requests_sent: 99,
        responses_succeeded: 50,
        retries_total: 20,
        final_failures: 28,
      },
    };

    render(
      <DiagnosticsSection
        isValidatingEnvironment={false}
        onRunValidation={vi.fn()}
        validationResult={null}
        displayChecks={dummyChecks}
        apiUsage={apiUsageWithTelemetry}
      />
    );

    expect(screen.queryByText('Telemetria Chiamate API & Lavoro Svolto')).toBeNull();
  });
});
