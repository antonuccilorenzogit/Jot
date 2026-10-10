import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { CheckCircle2, FolderInput, HardDrive, Info, Loader2, Trash2, X } from 'lucide-react';

function formatSize(bytes: number): string {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

const SESSION_CLEANUP_DAYS = 30;

interface StorageSectionProps {
  sessionInfo: { total_bytes: number; total_sessions: number; session_root: string } | null;
  isLoadingSessionInfo?: boolean;
  isMoveInProgress: boolean;
  moveProgress: { moved: number; total: number } | null;
  moveError: string | null;
  onOpenSessionFolder: () => void;
  onAskMoveFolder: () => void;
  isCleaningSession: boolean;
  isCleaningCompletedSessions: boolean;
  cleanupPreview: { removed: number; freed_bytes: number; candidates?: number } | null;
  completedCleanupPreview: { removed: number; freed_bytes: number; candidates?: number } | null;
  cleanupResult: { removed: number; freed_bytes: number; candidates?: number; preserved_completed?: number; missing_completed_html?: number } | null;
  completedCleanupResult?: { removed: number; freed_bytes: number; candidates?: number } | null;
  onAskCleanup: () => void;
  onAskCompletedCleanup: () => void;
  onDismissCleanupResult?: () => void;
  canManageSessionFolder?: boolean;
}

export const StorageSection: React.FC<StorageSectionProps> = React.memo(({
  sessionInfo,
  isLoadingSessionInfo,
  isMoveInProgress,
  moveProgress,
  moveError,
  onOpenSessionFolder,
  onAskMoveFolder,
  isCleaningSession,
  isCleaningCompletedSessions,
  cleanupPreview: _cleanupPreview,
  completedCleanupPreview: _completedCleanupPreview,
  cleanupResult,
  completedCleanupResult,
  onAskCleanup,
  onAskCompletedCleanup,
  onDismissCleanupResult,
  canManageSessionFolder = true,
}) => {
  return (
    <div className="space-y-6">
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
        Spostamento e pulizia hanno effetto immediato dopo la conferma e non vengono annullati con Annulla.
      </p>
      {/* 1. Spazio Disco e Posizione Cartella */}
      <div className="space-y-3">
        {/* Header */}
        <div className="flex items-center gap-2">
          <HardDrive className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">
            Spazio disco e archivio
          </h3>
        </div>

        {/* Metric Stat Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="premium-panel p-3.5 space-y-1">
            <span className="text-[11px] font-bold text-[var(--text-secondary)] uppercase tracking-wider block">
              Spazio occupato
            </span>
            <span className="text-2xl font-bold text-[var(--text-primary)] block">
              {isLoadingSessionInfo ? 'Calcolo…' : sessionInfo ? formatSize(sessionInfo.total_bytes) : '—'}
            </span>
          </div>
          <div className="premium-panel p-3.5 space-y-1">
            <span className="text-[11px] font-bold text-[var(--text-secondary)] uppercase tracking-wider block">
              Sbobine salvate
            </span>
            <span className="text-2xl font-bold text-[var(--text-primary)] block">
              {sessionInfo ? `${sessionInfo.total_sessions} ${sessionInfo.total_sessions === 1 ? 'sbobina' : 'sbobine'}` : '—'}
            </span>
          </div>
        </div>

        {/* Row: Sessions Folder */}
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-0.5 min-w-0">
              <span className="text-sm font-bold text-[var(--text-primary)] block">
                Cartella sessioni
              </span>
              <p className="text-xs text-[var(--text-secondary)]">
                Posizione su disco delle trascrizioni e dei file di lavoro.
              </p>
            </div>
            {canManageSessionFolder && (
              <button
                type="button"
                onClick={onAskMoveFolder}
                disabled={isMoveInProgress}
                aria-label="Cambia cartella"
                title="Cambia cartella"
                className="app-button-secondary is-settings-action"
              >
                {isMoveInProgress ? (
                  <Loader2 className="w-4 h-4 animate-spin text-[var(--accent-text)]" />
                ) : (
                  <FolderInput className="w-4 h-4" />
                )}
                <span>Cambia cartella</span>
              </button>
            )}
          </div>

          <div
            onClick={canManageSessionFolder ? onOpenSessionFolder : undefined}
            title={canManageSessionFolder ? 'Apri cartella sessioni' : undefined}
            role={canManageSessionFolder ? 'button' : undefined}
            tabIndex={canManageSessionFolder ? 0 : undefined}
            onKeyDown={canManageSessionFolder ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onOpenSessionFolder();
              }
            } : undefined}
            className={`p-2.5 rounded-lg bg-[var(--bg-surface)] border border-[var(--border-default)] font-mono text-xs break-all text-[var(--text-primary)] group transition-colors ${canManageSessionFolder ? 'cursor-pointer hover:border-[var(--border-strong)]' : ''}`}
          >
            <span className="font-mono text-xs break-all group-hover:underline font-medium">
              {sessionInfo?.session_root || (isLoadingSessionInfo ? '…' : '—')}
            </span>
          </div>

          {isMoveInProgress && (
            <div className="alert-card is-info text-xs space-y-2">
              <div className="flex items-center justify-between text-[var(--accent-text)] font-medium">
                <span>Spostamento cartella in corso...</span>
                {moveProgress && moveProgress.total > 0 && (
                  <span>{moveProgress.moved} / {moveProgress.total} file</span>
                )}
              </div>
              <div className="w-full h-2 bg-[var(--bg-surface)] rounded-full overflow-hidden">
                <div
                  className="h-full bg-[var(--accent-bg)] transition-all duration-300"
                  style={{
                    width: `${
                      moveProgress && moveProgress.total > 0
                        ? Math.round((moveProgress.moved / moveProgress.total) * 100)
                        : 0
                    }%`,
                  }}
                />
              </div>
            </div>
          )}

          {moveError && (
            <div className="alert-card is-error text-xs font-medium">
              {moveError}
            </div>
          )}
        </div>
      </div>

      {/* 2. Eliminazione e Pulizia Sbobine */}
      <div className="border-t border-[var(--border-default)] pt-6 space-y-3">
        {/* Header */}
        <div className="flex items-center gap-2">
          <Trash2 className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">
            Pulizia archivio
          </h3>
        </div>

        <div className="space-y-1">
          {/* Row: Incomplete Sessions */}
          <div className="flex items-center justify-between gap-3 p-2.5 rounded-lg hover:bg-[var(--bg-hover)] transition-colors -mx-2">
            <div className="space-y-0.5 min-w-0">
              <span className="text-sm font-bold text-[var(--text-primary)] block">
                Elaborazioni incomplete
              </span>
              <p className="text-xs text-[var(--text-secondary)]">
                File temporanei e bozze interrotte
              </p>
            </div>
            <button
              type="button"
              onClick={onAskCleanup}
              disabled={isCleaningSession}
              aria-label="Pulisci elaborazioni incomplete"
              title="Conta ed elimina tutte le elaborazioni incomplete"
              className="app-button-secondary is-settings-action is-icon is-danger"
            >
              {isCleaningSession ? (
                <Loader2 className="w-4 h-4 animate-spin text-[var(--error-text)]" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
            </button>
          </div>

          {/* Row: Old Completed Sessions */}
          <div className="flex items-center justify-between gap-3 p-2.5 rounded-lg hover:bg-[var(--bg-hover)] transition-colors -mx-2">
            <div className="space-y-0.5 min-w-0">
              <span className="text-sm font-bold text-[var(--text-primary)] block">
                Sbobine archiviate
              </span>
              <p className="text-xs text-[var(--text-secondary)]">
                Salvate da oltre {SESSION_CLEANUP_DAYS} giorni
              </p>
            </div>
            <button
              type="button"
              onClick={onAskCompletedCleanup}
              disabled={isCleaningCompletedSessions}
              aria-label={`Elimina sbobine completate archiviate da oltre ${SESSION_CLEANUP_DAYS} giorni`}
              title={`Conta ed elimina sbobine completate archiviate da oltre ${SESSION_CLEANUP_DAYS} giorni`}
              className="app-button-secondary is-settings-action is-icon is-danger"
            >
              {isCleaningCompletedSessions ? (
                <Loader2 className="w-4 h-4 animate-spin text-[var(--error-text)]" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>

      {/* Cleanup Results Feedback Notification Banner */}
      <AnimatePresence>
        {(cleanupResult || completedCleanupResult) && (
          <motion.div
            initial={{ opacity: 0, y: -6, height: 0 }}
            animate={{ opacity: 1, y: 0, height: 'auto' }}
            exit={{ opacity: 0, y: -6, height: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            <div
              className={`relative alert-card ${
                (cleanupResult?.removed ?? 0) > 0 || (completedCleanupResult?.removed ?? 0) > 0
                  ? 'is-success'
                  : 'is-info'
              } !flex-row items-start justify-between gap-3`}
            >
              <div className="flex items-start gap-2.5 min-w-0 pr-6">
                {(cleanupResult?.removed ?? 0) > 0 || (completedCleanupResult?.removed ?? 0) > 0 ? (
                  <CheckCircle2 className="w-4 h-4 text-[var(--success-text)] shrink-0 mt-0.5" />
                ) : (
                  <Info className="w-4 h-4 text-[var(--text-secondary)] shrink-0 mt-0.5" />
                )}
                <div className="space-y-0.5 min-w-0">
                  {cleanupResult && (
                    <>
                      <p
                        className={`text-xs ${cleanupResult.removed > 0 ? 'font-semibold text-[var(--success-text)]' : 'font-medium text-[var(--text-secondary)]'}`}
                      >
                        {cleanupResult.removed > 0
                          ? cleanupResult.removed === 1
                            ? `Rimossa 1 elaborazione incompleta, liberati ${formatSize(cleanupResult.freed_bytes)}.`
                            : `Rimosse ${cleanupResult.removed} elaborazioni incomplete, liberati ${formatSize(cleanupResult.freed_bytes)}.`
                          : 'Nessuna elaborazione incompleta da eliminare.'}
                      </p>
                      {(cleanupResult?.preserved_completed ?? 0) > 0 && (
                        <p className="text-xs text-[var(--text-secondary)]">
                          {cleanupResult.preserved_completed} sbobine completate preservate.
                        </p>
                      )}
                      {(cleanupResult?.missing_completed_html ?? 0) > 0 && (
                        <p className="text-xs text-[var(--warning-text)]">
                          {cleanupResult.missing_completed_html} sessioni completate senza HTML finale trattate come incomplete.
                        </p>
                      )}
                    </>
                  )}
                  {completedCleanupResult && (
                    <p
                      className={`text-xs ${completedCleanupResult.removed > 0 ? 'font-semibold text-[var(--success-text)]' : 'font-medium text-[var(--text-secondary)]'}`}
                    >
                      {completedCleanupResult.removed > 0
                        ? completedCleanupResult.removed === 1
                          ? `Eliminata 1 sbobina completata, liberati ${formatSize(completedCleanupResult.freed_bytes)}.`
                          : `Eliminate ${completedCleanupResult.removed} sbobine completate, liberati ${formatSize(completedCleanupResult.freed_bytes)}.`
                        : 'Nessuna sbobina completata vecchia da eliminare.'}
                    </p>
                  )}
                </div>
              </div>

              {onDismissCleanupResult && (
                <button
                  type="button"
                  onClick={onDismissCleanupResult}
                  aria-label="Chiudi notifica"
                  title="Chiudi notifica"
                  className="absolute top-2.5 right-2.5 p-1 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors cursor-pointer shrink-0"
                >
                  <X className="w-4 h-4 shrink-0" />
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      </div>
    </div>
  );
});

StorageSection.displayName = 'StorageSection';
