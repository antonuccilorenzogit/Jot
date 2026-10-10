import React from 'react';
import { motion } from 'motion/react';
import { AlertCircle, AlertTriangle, CheckCircle, Clock, ExternalLink, FileAudio, FolderOpen, GripVertical, PenLine, Presentation, RotateCcw, Settings, Trash2, X, XCircle } from 'lucide-react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { AppStatus, FileItem } from '../appState';
import type { ArchiveFolder } from '../bridge';
import { getHostCapabilities } from '../browserHost';
import { errorLabel, formatDuration, formatRelativeTime, formatSize, isPausedError, isQuotaError, isResumableError, shortModelName } from '../utils';
import { KebabMenu, type KebabMenuItem } from './KebabMenu';
import { FolderIndicatorChip } from './FolderChip';


interface QueueFileCardProps {
  file: FileItem;
  appState: AppStatus;
  currentPhase?: string;
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
  onPreview: (htmlPath: string, filename: string, sourcePath?: string, fileId?: string, sessionDir?: string) => void;
  onOpenFile: (path: string) => void;
  onOpenSettings?: () => void;
  showDragHandle?: boolean;
}


function QueueFileCardInner({
  file, appState, currentPhase: _currentPhase,
  onRemove,
  onRetry,
  onPreview: _onPreview,
  onOpenFile: _onOpenFile,
  onOpenSettings,
  showDragHandle = true,
}: QueueFileCardProps) {
  const isCanceling = appState === 'canceling' && file.status === 'processing';
  const isDraggable = file.status !== 'processing' && file.status !== 'done' && showDragHandle;
  const isPhase1ChunkFailure = Boolean(file.errorText?.startsWith('phase1_chunk_failed_'));
  const isPaused = file.status === 'error' && isPausedError(file.errorText, file.errorDetail);
  const { attributes, listeners, setNodeRef, transform, transition: dndTransition, isDragging } = useSortable({
    id: file.id,
    disabled: !isDraggable,
  });

  const sortableStyle: React.CSSProperties = {
    transform: CSS.Transform.toString(transform ? { ...transform, x: 0 } : null),
    transition: dndTransition ?? undefined,
    zIndex: isDragging ? 50 : undefined,
    position: 'relative',
  };

  return (
    <div ref={setNodeRef} style={sortableStyle} {...attributes}>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: isDragging ? 0.4 : 1 }}
        exit={{ opacity: 0, transition: { duration: 0.11, ease: 'easeIn' } }}
        transition={{
          opacity: { duration: 0.18, ease: 'easeOut' },
        }}
        className={`queue-card relative transition-colors px-4 py-3 group/card ${
          file.status === 'processing'
            ? isCanceling ? 'is-canceling' : 'is-processing'
            : file.status === 'error'
              ? isPaused ? 'is-warning' : 'is-error'
              : 'is-queued'
        }`}
      >
        <div className="relative z-10 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            {isDraggable && (
              <div className="group/drag flex items-center shrink-0 gap-1">
                <button
                  {...listeners}
                  className="drag-handle-btn"
                  tabIndex={-1}
                  aria-label="Trascina per riordinare"
                >
                  <GripVertical className="w-4 h-4" />
                </button>
              </div>
            )}
            <div
              className={`shrink-0 flex items-center justify-center w-8 h-8 rounded-lg transition-transform duration-200 group-hover/card:scale-105 ${
                file.status === 'processing'
                  ? isCanceling ? 'text-[var(--error-text)]' : 'text-[var(--processing-text)]'
                  : file.status === 'error'
                    ? isPaused
                      ? 'bg-[var(--warning-subtle)] text-[var(--warning-text)] border border-[var(--warning-ring)]'
                      : 'bg-[var(--error-subtle)] text-[var(--error-text)] border border-[var(--error-ring)]'
                    : 'text-[var(--text-muted)]'
              }`}
            >
              {file.status === 'processing'
                ? isCanceling
                  ? <XCircle className="w-5 h-5" />
                  : file.isRetryingBlocks
                    ? <RotateCcw className="w-5 h-5 animate-spin text-[var(--accent-text)]" />
                    : <Clock className="w-5 h-5 animate-pulse" />
                : file.status === 'error'
                  ? isPaused
                    ? <AlertTriangle className="w-4 h-4" />
                    : <AlertCircle className="w-4 h-4" />
                  : file.kind === 'notes'
                    ? <Presentation className="w-5 h-5" />
                    : <FileAudio className="w-5 h-5" />}
            </div>
            <div className="min-w-0 flex-1">
              <h4 className="text-sm font-semibold truncate tracking-tight text-[var(--text-primary)]">{file.name}</h4>
              <div className="flex items-center gap-2.5 mt-1.5 text-xs text-[var(--text-muted)] min-w-0 flex-nowrap overflow-hidden">
                <span className="shrink-0">{formatSize(file.size)}</span>
                {file.duration > 0 && (
                  <>
                    <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
                    <span className="shrink-0">{formatDuration(file.duration)}</span>
                  </>
                )}
                <NotesMeta file={file} />
                {file.status === 'processing' && (
                  <>
                    <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
                    <span className={`inline-flex items-center gap-1.5 font-medium shrink-0 ${isCanceling ? 'text-[var(--error-text)]' : 'text-[var(--processing-text)]'}`}>
                      <span className={`inline-flex h-1.5 w-1.5 rounded-full animate-pulse ${isCanceling ? 'bg-[var(--error-text)]' : 'bg-[var(--processing-dot)]'}`} />
                      {isCanceling
                        ? 'Annullamento in corso'
                        : file.isRetryingBlocks
                          ? (file.revisionFailedBlocks?.length ?? 0) > 0
                            ? `Revisione blocchi in corso (${file.revisionFailedBlocks!.length} ${file.revisionFailedBlocks!.length === 1 ? 'blocco' : 'blocchi'})`
                            : 'Revisione blocchi in corso'
                          : 'In elaborazione'}
                    </span>
                    {file.isRetryingBlocks && (
                      <span className="sr-only">Riprovo…</span>
                    )}
                  </>
                )}
                {file.status === 'error' && (
                  <>
                    <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
                    <span
                      title={file.errorDetail || file.errorText}
                      className={`truncate min-w-0 font-medium ${isPaused ? 'text-[var(--warning-text)]' : 'text-[var(--error-text)]'}`}
                    >
                      {errorLabel(file.errorText, file.errorDetail)}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {appState === 'idle' && file.status === 'error' && onOpenSettings && isQuotaError(file.errorText) && (
              <button
                onClick={onOpenSettings}
                className="premium-button-secondary compact-button"
                title="Aggiungi una chiave API di riserva per evitare interruzioni"
                aria-label="Chiavi di riserva"
              >
                <Settings className="w-3.5 h-3.5" />
                Chiavi di riserva
              </button>
            )}
            {appState === 'idle' && (file.status === 'error' || file.status === 'paused') && (
              file.status === 'paused' || isResumableError(file.errorText) || isPhase1ChunkFailure ? (
                <button
                  onClick={() => onRetry(file.id)}
                  className="icon-button compact-icon-button text-[var(--warning-text)] hover:bg-[var(--warning-subtle)] group/retry"
                  title={isPhase1ChunkFailure ? 'I blocchi precedenti sono salvati: riprendi dal blocco fallito' : 'Il progresso è salvato: riprendi da dove è rimasto'}
                  aria-label="Riprendi"
                >
                  <RotateCcw className="w-4 h-4 transition-transform duration-500 ease-out group-hover/retry:-rotate-180 group-hover/retry:scale-105" />
                </button>
              ) : (
                <button
                  onClick={() => onRetry(file.id)}
                  className="icon-button compact-icon-button is-danger text-[var(--error-text)] hover:bg-[var(--error-subtle)] group/retry"
                  title="Riprova"
                  aria-label="Riprova"
                >
                  <RotateCcw className="w-4 h-4 transition-transform duration-500 ease-out group-hover/retry:-rotate-180 group-hover/retry:scale-105" />
                </button>
              )
            )}
            {(appState === 'idle' || file.status === 'queued' || file.status === 'error') && file.status !== 'processing' && (
              <button
                onClick={() => onRemove(file.id)}
                className="icon-button compact-icon-button group/remove"
                title="Rimuovi"
                aria-label="Rimuovi"
              >
                <X className="w-4 h-4 transition-transform duration-200 group-hover/remove:scale-110 group-hover/remove:rotate-90" />
              </button>
            )}
          </div>
        </div>

      </motion.div>
    </div>
  );
}

function NotesMeta({ file }: { file: FileItem }) {
  if (file.kind !== 'notes' || !file.notes) return null;
  const { slides, bookName, bookPages, bookMode } = file.notes;
  return (
    <>
      <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
      <span className="shrink-0">Appunti · {slides} slide</span>
      {bookName && (
        <>
          <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
          <span className="truncate" title={bookName}>Libro{bookPages ? ` p. ${bookPages}` : ''}{bookMode === 'auto' ? ' · solo pagine pertinenti' : ''}</span>
        </>
      )}
    </>
  );
}

export const QueueFileCard = React.memo(QueueFileCardInner);

interface CompletedFileCardProps {
  file: FileItem;
  isNewest?: boolean;
  onRemove: (id: string) => void;
  onPreview: (htmlPath: string, filename: string, sourcePath?: string, fileId?: string, sessionDir?: string) => void;
  onOpenFile: (path: string) => void;
  onRetryFailedRevisionBlocks?: (sessionDir: string, fileId?: string) => Promise<void>;
  currentFolder?: Pick<ArchiveFolder, 'name' | 'color'>;
}

function CompletedFileCardInner({ file, onRemove, onPreview, onOpenFile, onRetryFailedRevisionBlocks, currentFolder }: CompletedFileCardProps) {
  const canOpenLocalPath = getHostCapabilities().openLocalPath;
  const isClickable = Boolean(file.outputHtml);
  const [isRetryingBlocks, setIsRetryingBlocks] = React.useState(false);
  const isRetrying = file.isRetryingBlocks || isRetryingBlocks;
  const failedBlockCount = file.revisionFailedBlocks?.length ?? 0;
  const hasRevisionWarnings = file.completionStatus === 'completed_with_warnings' || failedBlockCount > 0;
  const canRetryBlocks = failedBlockCount > 0 && Boolean(file.outputDir) && Boolean(onRetryFailedRevisionBlocks);
  const handleRetryBlocks = async (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!canRetryBlocks || !file.outputDir || isRetrying) return;
    setIsRetryingBlocks(true);
    try {
      await onRetryFailedRevisionBlocks?.(file.outputDir, file.id);
    } finally {
      setIsRetryingBlocks(false);
    }
  };
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.11, ease: 'easeIn' } }}
      transition={{
        opacity: { duration: 0.2, ease: 'easeOut' },
      }}
      onClick={isClickable ? () => onPreview(file.outputHtml!, file.name, file.path, file.id, file.outputDir) : undefined}
      className={`queue-card relative px-4 py-3 transition-colors group/card ${isClickable ? 'cursor-pointer' : ''} is-completed ${
        hasRevisionWarnings ? 'is-warning' : ''
      }`}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div
            className={`shrink-0 flex items-center justify-center w-8 h-8 rounded-lg transition-transform duration-200 group-hover/card:scale-105 ${
              hasRevisionWarnings
                ? 'bg-[var(--warning-subtle)] text-[var(--warning-text)] border border-[var(--warning-ring)]'
                : 'bg-[var(--success-subtle)] text-[var(--success-text)] border border-[var(--success-ring)]'
            }`}
          >
            {hasRevisionWarnings ? <AlertTriangle className="w-4 h-4" /> : <CheckCircle className="w-4 h-4" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 min-w-0">
              <h4 className="text-sm font-semibold truncate tracking-tight text-[var(--text-primary)]">{file.name}</h4>
              {currentFolder && (
                <FolderIndicatorChip folder={currentFolder} />
              )}
            </div>
            <div className="flex items-center gap-2.5 mt-1.5 text-xs text-[var(--text-muted)] min-w-0 flex-nowrap overflow-hidden">
              <span className="shrink-0">{formatSize(file.size)}</span>
              {file.duration > 0 && (
                <>
                  <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
                  <span className="shrink-0">{formatDuration(file.duration)}</span>
                </>
              )}
              <NotesMeta file={file} />
              {(file.primaryModel || file.effectiveModel) && (
                <>
                  <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
                  <span className="shrink-0" title={file.primaryModel || file.effectiveModel}>
                    {shortModelName(file.primaryModel || file.effectiveModel!)}
                  </span>
                  {file.primaryModel && file.effectiveModel && file.primaryModel !== file.effectiveModel && (
                    <span
                      className="text-[10px] leading-none font-semibold uppercase tracking-wider px-1.5 py-[2px] h-4 box-border rounded-full badge-warning shrink-0"
                      title={`Fallback usato: ${shortModelName(file.effectiveModel)}`}
                    >
                      fallback
                    </span>
                  )}
                </>
              )}
              <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
              <span className={`shrink-0 ${hasRevisionWarnings ? 'text-[var(--warning-text)] font-medium' : 'text-[var(--success-text)]'}`}>
                {hasRevisionWarnings ? 'Completata con avvisi' : file.completedAt ? formatRelativeTime(file.completedAt) : 'Completato'}
              </span>
              {failedBlockCount > 0 && (
                <>
                  <span className="w-1 h-1 rounded-full bg-[var(--border-default)] shrink-0" />
                  <span
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--warning-text)] shrink-0"
                  >
                    <AlertTriangle className="w-3 h-3" />
                    {failedBlockCount} {failedBlockCount === 1 ? 'blocco non revisionato' : 'blocchi non revisionati'}
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0" onClick={e => e.stopPropagation()}>
          {canRetryBlocks && (
            <button
              type="button"
              onClick={handleRetryBlocks}
              disabled={isRetrying}
              className="icon-button compact-icon-button text-[var(--warning-text)] hover:bg-[var(--warning-subtle)] group/retry"
              style={{ opacity: isRetrying ? 0.65 : 1 }}
              title="Riprova solo i blocchi inclusi senza revisione"
              aria-label="Riprova revisione"
            >
              <RotateCcw className={`w-4 h-4 transition-transform duration-500 ease-out ${isRetrying ? 'animate-spin' : 'group-hover/retry:-rotate-180 group-hover/retry:scale-105'}`} />
              <span className="sr-only">{isRetrying ? 'Riprovo…' : 'Riprova revisione'}</span>
            </button>
          )}
          <KebabMenu
            items={[
              ...( file.outputHtml ? [
                {
                  label: 'Modifica',
                  icon: <PenLine className="w-3.5 h-3.5" />,
                  onClick: () => onPreview(file.outputHtml!, file.name, file.path, file.id, file.outputDir),
                } as KebabMenuItem,
                ...(canOpenLocalPath ? [{
                  label: 'Apri cartella',
                  icon: <FolderOpen className="w-3.5 h-3.5" />,
                  onClick: () => onOpenFile(file.outputDir ?? file.outputHtml!),
                } as KebabMenuItem,
                {
                  label: 'Apri nel browser',
                  icon: <ExternalLink className="w-3.5 h-3.5" />,
                  onClick: () => onOpenFile(file.outputHtml!),
                } as KebabMenuItem] : []),
              ] : []),
              {
                label: 'Rimuovi',
                icon: <Trash2 className="w-3.5 h-3.5" />,
                danger: true,
                onClick: () => onRemove(file.id),
              },
            ]}
          />
        </div>
      </div>
    </motion.div>
  );
}

export const CompletedFileCard = React.memo(CompletedFileCardInner);
