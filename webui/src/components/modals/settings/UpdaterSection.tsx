import React from 'react';
import { ArrowDownToLine, CheckCircle2, RefreshCw, Tag, ExternalLink, Loader2, AlertCircle } from 'lucide-react';
import { APP_VERSION, GITHUB_RELEASES_URL } from '../../../branding';

export interface SettingsUpdateInstallState {
  status?: 'idle' | 'downloading' | 'verifying' | 'installing' | 'done' | 'error';
  version?: string | null;
  bytesDone?: number;
  bytesDownloaded?: number;
  bytesTotal?: number;
  totalBytes?: number;
  percent?: number;
  error?: string | null;
}

const formatVersion = (ver?: string | null): string => {
  if (!ver) return '';
  const clean = ver.trim().replace(/^v+/, '');
  return clean ? `v${clean}` : '';
};

const formatBytes = (bytes?: number): string => {
  if (!bytes || bytes <= 0) return '0 MB';
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(1)} MB`;
};

interface UpdaterSectionProps {
  latestVersion: string | null;
  checkForUpdates: (force?: boolean) => void;
  isCheckingUpdate: boolean;
  hasChecked: boolean;
  checkFailed: boolean;
  updateInstallState?: SettingsUpdateInstallState;
  onInstallUpdate?: (version: string) => Promise<void>;
}

export const UpdaterSection: React.FC<UpdaterSectionProps> = React.memo(({
  latestVersion,
  checkForUpdates,
  isCheckingUpdate,
  hasChecked,
  checkFailed,
  updateInstallState,
  onInstallUpdate,
}) => {
  const cleanAppVersion = formatVersion(APP_VERSION);
  const cleanLatestVersion = formatVersion(latestVersion);
  const isUpdateAvailable = Boolean(cleanLatestVersion && cleanLatestVersion !== cleanAppVersion);

  const isDownloading = updateInstallState?.status === 'downloading';
  const isVerifying = updateInstallState?.status === 'verifying';
  const isInstalling = updateInstallState?.status === 'installing';
  const isDone = updateInstallState?.status === 'done';
  const isError = updateInstallState?.status === 'error';
  const isInProgress = isDownloading || isVerifying || isInstalling;

  return (
    <div className="space-y-3">
      {/* Header row: Version Info & Check Button */}
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2">
            <Tag className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">
              Versione applicazione
            </h3>
          </div>
          <p className="text-xs text-[var(--text-secondary)]">
            Installata:{' '}
            <span className="font-mono font-bold text-[var(--text-primary)]">{cleanAppVersion}</span>
            {!isUpdateAvailable && (
              <a
                href={GITHUB_RELEASES_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-2 hover:underline text-[var(--accent-text)] font-semibold inline-flex items-center gap-0.5"
              >
                Note di rilascio ↗
              </a>
            )}
          </p>
        </div>

        <button
          type="button"
          onClick={() => checkForUpdates(true)}
          disabled={isCheckingUpdate || isInProgress}
          aria-label="Cerca aggiornamenti"
          title={isCheckingUpdate ? 'Controllo in corso…' : 'Cerca aggiornamenti'}
          className="app-button-secondary is-settings-action"
        >
          <RefreshCw
            className={`w-4 h-4 transition-transform duration-500 ease-out ${
              isCheckingUpdate
                ? 'animate-spin text-[var(--accent-text)]'
                : 'settings-refresh-icon'
            }`}
          />
          <span>{isCheckingUpdate ? 'Controllo in corso…' : 'Cerca aggiornamenti'}</span>
        </button>
      </div>

      {/* Update Available Banner Card */}
      {isUpdateAvailable && !isDone && (
        <div className="p-4 rounded-lg bg-[var(--accent-subtle)] border border-[var(--border-subtle)] space-y-3 relative overflow-hidden">
          {/* Top/Inline Content */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-3 min-w-0 flex-1 basis-64">
              <div aria-hidden="true" className="flex items-center justify-center w-9 h-9 rounded-full bg-[var(--bg-surface)] border border-[var(--accent-ring)] text-[var(--accent-text)] shrink-0">
                <ArrowDownToLine className="w-4 h-4" />
              </div>
              <div className="space-y-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h4 className="text-base font-bold text-[var(--text-primary)] leading-tight">
                    Nuova versione disponibile
                  </h4>
                  <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold font-mono bg-[var(--bg-surface)] text-[var(--accent-text)] border border-[var(--accent-ring)] tracking-wide shrink-0">
                    {cleanLatestVersion}
                  </span>
                </div>

                <div>
                  <a
                    href={GITHUB_RELEASES_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-semibold text-[var(--accent-text)] hover:underline inline-flex items-center gap-1 transition-colors"
                  >
                    Note di rilascio su GitHub
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>
              </div>
            </div>

            {/* Action button if not downloading/installing */}
            {!isInProgress && onInstallUpdate && (
              <button
                type="button"
                onClick={() => { void Promise.resolve(onInstallUpdate(latestVersion!)).catch(() => {}); }}
                aria-label="Installa aggiornamento"
                className="premium-button compact-button cursor-pointer shrink-0 font-bold text-xs flex items-center gap-1.5"
              >
                <ArrowDownToLine className="w-3.5 h-3.5" />
                Aggiorna ora
              </button>
            )}
          </div>

          {/* Download progress / verifying in progress */}
          {isDownloading && (
            <div className="space-y-2 pt-1">
              {(() => {
                const total = updateInstallState?.bytesTotal ?? updateInstallState?.totalBytes ?? 0;
                const done = updateInstallState?.bytesDone ?? updateInstallState?.bytesDownloaded ?? 0;
                const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : (updateInstallState?.percent ?? 0);
                return (
                  <>
                    <div className="w-full h-1.5 rounded-full bg-[var(--bg-panel)] border border-[var(--border-subtle)] overflow-hidden">
                      <div
                        className="h-full bg-[var(--accent-bg)] rounded-full transition-all duration-200"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
                      <span className="flex items-center gap-1.5 font-bold text-[var(--text-primary)]">
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--accent-text)]" />
                        Download aggiornamento…
                      </span>
                      <span className="font-mono font-medium">{total > 0 ? `${formatBytes(done)} / ${formatBytes(total)} (${pct}%)` : `${pct}%`}</span>
                    </div>
                  </>
                );
              })()}
            </div>
          )}

          {(isVerifying || isInstalling) && (
            <div className="flex items-center gap-2 text-xs font-bold text-[var(--text-primary)] pt-1">
              <Loader2 className="w-4 h-4 animate-spin text-[var(--accent-text)]" />
              <span>{isVerifying ? 'Verifica integrità aggiornamento…' : 'Installazione aggiornamento…'}</span>
            </div>
          )}
        </div>
      )}

      {/* Done / Installer Launched Banner */}
      {isDone && (
        <div className="alert-card is-success text-xs flex-row items-center gap-2 p-3 font-bold animate-fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>Installer avviato. Segui le istruzioni a schermo.</span>
        </div>
      )}

      {/* Error Banner */}
      {(isError || (hasChecked && checkFailed && !isCheckingUpdate)) && (
        <div className="alert-card is-error text-xs flex-row items-center gap-2 p-3 font-bold animate-fade-in">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{updateInstallState?.error || (checkFailed ? 'Verifica aggiornamenti non riuscita.' : 'Aggiornamento non riuscito.')}</span>
        </div>
      )}

      {/* Up to date Banner */}
      {hasChecked && !isCheckingUpdate && !isUpdateAvailable && !checkFailed && !isError && !isDone && (
        <div className="flex items-center gap-2 text-xs text-[var(--success-text)] font-bold">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>Sei aggiornato alla versione più recente.</span>
        </div>
      )}
    </div>
  );
});

UpdaterSection.displayName = 'UpdaterSection';
