import { reportClientError } from '../../../diagnostics';
import React, { useState, useEffect } from 'react';
import {
  FlaskConical,
  Loader2,
  Check,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  X,
  Copy,
  FolderOpen,
  RefreshCw,
  Download,
  FileText,
} from 'lucide-react';
import { APP_VERSION } from '../../../branding';
import { CustomSelect } from './CustomSelect';
import type { ValidationResult, ApiUsageResult } from '../../../bridge';

export interface DisplayCheck {
  id: string;
  label: string;
  status: 'pending' | 'ok' | 'warning' | 'error';
  message?: string;
  details?: string;
  errorMessage?: string;
  errorDetails?: string;
}

interface DiagnosticsSectionProps {
  isValidatingEnvironment: boolean;
  onRunValidation: () => void;
  validationResult: ValidationResult | null;
  displayChecks: DisplayCheck[];
  onOpenLogs?: () => void;
  onCopyReport?: (sessionDir?: string) => Promise<void>;
  apiUsage?: ApiUsageResult | null;
  showOpenLogs?: boolean;
}

export const DiagnosticsSection: React.FC<DiagnosticsSectionProps> = React.memo(({
  isValidatingEnvironment,
  onRunValidation,
  validationResult,
  displayChecks,
  onOpenLogs,
  onCopyReport,
  apiUsage: _apiUsage,
  showOpenLogs = true,
}) => {
  const [copiedToast, setCopiedToast] = useState(false);
  const [isCopying, setIsCopying] = useState(false);
  const hasRun = Boolean(validationResult);
  const [sessions, setSessions] = useState<Array<{ path: string; label: string }>>([]);
  const [sessionDir, setSessionDir] = useState('');
  const [exporting, setExporting] = useState(false);
  const [supportMessage, setSupportMessage] = useState('');
  const [supportError, setSupportError] = useState('');

  useEffect(() => {
    let active = true;
    if (showOpenLogs && window.pywebview?.api?.list_diagnostic_sessions) {
      void window.pywebview.api.list_diagnostic_sessions().then(result => {
        if (!active) return;
        if (result.ok) setSessions(result.sessions || []);
        else setSupportError(result.error || 'Impossibile elencare le sbobine.');
      }).catch(() => { if (active) setSupportError('Impossibile elencare le sbobine.'); });
    }
    return () => { active = false; };
  }, [showOpenLogs]);

  const handleExport = async () => {
    const api = window.pywebview?.api?.export_diagnostics;
    if (!api || exporting) return;
    setExporting(true);
    setSupportError('');
    setSupportMessage('');
    try {
      const result = await api(sessionDir || undefined, APP_VERSION);
      if (!result.ok) throw new Error(result.error || 'Esportazione non riuscita.');
      if (!result.cancelled) setSupportMessage('Pacchetto diagnostico salvato.');
    } catch (error) {
      setSupportError(error instanceof Error ? error.message : String(error));
    } finally { setExporting(false); }
  };

  const handleCopyReport = async () => {
    if (isCopying) return;
    setIsCopying(true);
    setSupportError('');
    try {
      if (onCopyReport) {
        await onCopyReport(sessionDir || undefined);
        setCopiedToast(true);
        setTimeout(() => setCopiedToast(false), 2500);
      } else if (window.pywebview?.api?.get_diagnostic_report) {
        const res = await window.pywebview.api.get_diagnostic_report(undefined, undefined, undefined, undefined, sessionDir || undefined, APP_VERSION);
        if (res?.ok && res.report) {
          await navigator.clipboard.writeText(res.report);
          setCopiedToast(true);
          setTimeout(() => setCopiedToast(false), 2500);
        } else { throw new Error(res?.error || 'Report non disponibile.'); }
      }
    } catch (e) {
      setSupportError(e instanceof Error ? e.message : String(e));
      reportClientError('Copy diagnostic report failed:', e);
    } finally {
      setIsCopying(false);
    }
  };

  const handleOpenLogsFolder = () => {
    if (onOpenLogs) {
      onOpenLogs();
    } else if (window.pywebview?.api?.open_logs_folder) {
      void window.pywebview.api.open_logs_folder();
    }
  };

  return (
    <div className="space-y-3 animate-fade-in">
      <section aria-labelledby="diagnostic-environment-heading" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <FlaskConical className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
            <h3 id="diagnostic-environment-heading" className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">
              Verifica ambiente
            </h3>
          </div>

          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onRunValidation}
              disabled={isValidatingEnvironment}
              className="app-button-secondary is-settings-action"
              title={
                isValidatingEnvironment
                  ? 'Verifica in corso…'
                  : hasRun
                    ? 'Riesegui verifica ambiente'
                    : 'Verifica ambiente'
              }
              aria-label={
                hasRun ? 'Riesegui verifica ambiente' : 'Verifica ambiente'
              }
            >
              {isValidatingEnvironment ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--accent-text)]" />
                  <span>Verifica in corso...</span>
                </>
              ) : hasRun ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 text-[var(--accent-text)] transition-transform duration-500 ease-out settings-refresh-icon" />
                  <span>Riesegui</span>
                </>
              ) : (
                <>
                  <RefreshCw className="w-3.5 h-3.5 text-[var(--accent-text)] transition-transform duration-500 ease-out settings-refresh-icon" />
                  <span>Verifica ora</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Validation Result Banner */}
        {validationResult && (() => {
          const hasErrors = !validationResult.ok || validationResult.checks?.some(c => c.status === 'error');
          const hasWarnings = !hasErrors && (Boolean(validationResult.has_warnings) || Boolean(validationResult.checks?.some(c => c.status === 'warning')));
          const bannerClass = hasErrors ? 'is-error' : hasWarnings ? 'is-warning' : 'is-success';
          const textColor = hasErrors ? 'var(--error-text)' : hasWarnings ? 'var(--warning-text)' : 'var(--success-text)';

          return (
            <div className={`alert-card ${bannerClass} flex-row items-center gap-2.5 animate-fade-in`}>
              {hasErrors ? (
                <AlertCircle className="w-4 h-4 text-[var(--error-text)] shrink-0" />
              ) : hasWarnings ? (
                <AlertTriangle className="w-4 h-4 text-[var(--warning-text)] shrink-0" />
              ) : (
                <CheckCircle2 className="w-4 h-4 text-[var(--success-text)] shrink-0" />
              )}
              <span
                className="text-sm font-bold"
                style={{ color: textColor }}
              >
                {validationResult.summary}
              </span>
            </div>
          );
        })()}

        {/* System Requirements Checks List */}
        <ul className="divide-y divide-[var(--border-default)] border-t border-[var(--border-default)]">
          {displayChecks.map(check => (
            <li
              key={check.id}
              className="flex justify-between items-start py-3 gap-3 transition-colors"
            >
              <div className="flex-1 min-w-0 space-y-0.5">
                <span className="text-sm font-bold text-[var(--text-primary)]">{check.label}</span>
                {check.status !== 'pending' && check.message && (
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{check.message}</p>
                )}
                {check.details && (
                  <p className="text-xs font-mono text-[var(--text-secondary)] break-all whitespace-pre-wrap mt-0.5 leading-relaxed">
                    {check.details}
                  </p>
                )}
                {(check.status === 'error' || check.status === 'warning') && check.errorMessage && (
                  <div className={`mt-2 alert-card ${check.status === 'error' ? 'is-error' : 'is-warning'} text-xs space-y-1 animate-fade-in`}>
                    <p className="font-bold">{check.errorMessage}</p>
                    {check.errorDetails && (
                      <p className="font-mono break-all text-[var(--text-secondary)]">{check.errorDetails}</p>
                    )}
                  </div>
                )}
              </div>
              <div className="shrink-0 pl-2 flex items-center h-full">
                {check.status === 'pending' ? (
                  <span className="text-xs font-semibold rounded-full px-2.5 py-0.5 text-[var(--text-secondary)] bg-[var(--bg-surface)] border border-[var(--border-default)]">
                    da verificare
                  </span>
                ) : check.status === 'ok' ? (
                  <div
                    className="flex items-center justify-center w-5 h-5 rounded-full bg-[var(--success-subtle)] text-[var(--success-text)] animate-fade-in"
                    title="Verificato"
                  >
                    <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                  </div>
                ) : check.status === 'warning' ? (
                  <div
                    className="flex items-center justify-center w-5 h-5 rounded-full bg-[var(--warning-subtle)] text-[var(--warning-text)] animate-fade-in"
                    title="Avviso"
                  >
                    <AlertTriangle className="w-3.5 h-3.5" />
                  </div>
                ) : (
                  <div
                    className="flex items-center justify-center w-5 h-5 rounded-full bg-[var(--error-subtle)] text-[var(--error-text)] animate-fade-in"
                    title="Errore"
                  >
                    <X className="w-3.5 h-3.5 stroke-[2.5]" />
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="diagnostic-support-heading" className="space-y-3 border-t border-[var(--border-default)] pt-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h3 id="diagnostic-support-heading" className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">
            <FileText className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
            Report per assistenza
          </h3>
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={handleCopyReport}
              disabled={isCopying}
              className="app-button-secondary is-settings-action is-icon"
              title={copiedToast ? 'Report copiato!' : 'Copia report per assistenza'}
              aria-label="Copia report diagnostico"
            >
              {copiedToast ? (
                <Check className="w-4 h-4 text-[var(--success-text)]" />
              ) : isCopying ? (
                <Loader2 className="w-4 h-4 animate-spin text-[var(--accent-text)]" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
            </button>


            {showOpenLogs && window.pywebview?.api?.export_diagnostics && (
              <button type="button" className="app-button-secondary is-settings-action is-icon" disabled={exporting || isCopying} onClick={handleExport}
                title={exporting ? 'Esportazione in corso…' : 'Esporta diagnostica'} aria-label="Esporta diagnostica">
                {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              </button>
            )}
            {showOpenLogs && (
              <button
                type="button"
                onClick={handleOpenLogsFolder}
                className="app-button-secondary is-settings-action is-icon"
                title="Apri cartella log"
                aria-label="Apri cartella log"
              >
                <FolderOpen className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
        {showOpenLogs && window.pywebview?.api?.export_diagnostics && (
          <div className="flex flex-col gap-2">
            <label htmlFor="diagnostic-session" className="text-xs text-[var(--text-secondary)]">Sbobina con il problema (facoltativa)</label>
            <CustomSelect
              id="diagnostic-session"
              value={sessionDir}
              disabled={exporting || isCopying}
              onChange={setSessionDir}
              options={[
                { value: '', label: 'Solo diagnostica generale' },
                ...sessions.map(session => ({ value: session.path, label: session.label })),
              ]}
            />
            <p className="text-xs text-[var(--text-secondary)]">Se il problema riguarda una sbobina, selezionala per includere nel report lo stato dell’elaborazione e i relativi log.</p>
            <p className="text-xs text-[var(--text-secondary)]">Crea un pacchetto locale per l’assistenza. Include errori e log, senza audio, trascrizioni o chiavi API. Controllalo prima di condividerlo.</p>
          </div>
        )}
        {supportError && <p role="alert" className="text-xs text-[var(--error-text)]">{supportError}</p>}
        {supportMessage && <p role="status" className="text-xs text-[var(--success-text)]">{supportMessage}</p>}
      </section>
    </div>
  );
});

DiagnosticsSection.displayName = 'DiagnosticsSection';
