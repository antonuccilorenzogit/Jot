import React, { useCallback, useRef } from 'react';
import { type ArchiveSession } from '../bridge';
import { type FileItem, type FileDonePayload, type ProcessingAction } from '../appState';
import { type ConfirmActionState } from './useConfirmModal';
import { type AddNotificationOptions, type NotificationCategory, type NotificationType } from './useNotifications';

export interface UseRevisionRetryOptions {
  filesRef: React.MutableRefObject<FileItem[]>;
  archiveSessionsRef: React.MutableRefObject<ArchiveSession[]>;
  normalizeSessionDir: (dir: string) => string;
  dispatch: React.Dispatch<ProcessingAction>;
  setArchiveSessions: React.Dispatch<React.SetStateAction<ArchiveSession[]>>;
  refreshArchiveSessions: () => Promise<void>;
  addNotification: (
    title: string,
    message: string,
    type?: NotificationType,
    category?: NotificationCategory,
    options?: AddNotificationOptions,
  ) => void;
  setConfirmAction: (action: ConfirmActionState | null) => void;
}

export function useRevisionRetry({
  filesRef,
  archiveSessionsRef,
  normalizeSessionDir,
  dispatch,
  setArchiveSessions,
  refreshArchiveSessions,
  addNotification,
  setConfirmAction,
}: UseRevisionRetryOptions) {
  const warnedRevisionSessionsRef = useRef<Set<string>>(new Set());

  const handleRetryFailedRevisionBlocks = useCallback(async (sessionDir: string, _fileId?: string) => {
    if (!sessionDir) throw new Error('Sessione non disponibile.');
    if (!_fileId) {
      const session = archiveSessionsRef.current.find(s => normalizeSessionDir(s.session_dir) === normalizeSessionDir(sessionDir));
      if (session) {
        setConfirmAction({ type: 'retry-archive-session', session });
      }
      return;
    }

    const existing = filesRef.current.find(f => f.id === _fileId);
    if (existing?.isRetryingBlocks) {
      addNotification('Retry in corso', 'Retry già in corso per questa sessione.', 'warning', 'processing');
      return;
    }

    const blockCount = existing?.revisionFailedBlocks?.length ?? 1;
    dispatch({ type: 'queue/set_retrying_blocks', id: _fileId, value: true });
    dispatch({ type: 'app/set_status', status: 'processing' });
    dispatch({ type: 'bridge/update_phase', text: `Fase 2/3: retry blocchi mancanti (1/${blockCount})` });
    dispatch({ type: 'bridge/update_progress', value: 0 });
    try {
      const res = await window.pywebview?.api?.retry_failed_revision_blocks?.(sessionDir);
      if (!res?.ok) {
        if (res?.conflict) {
          addNotification('Retry annullato', 'La sbobina è stata modificata: retry annullato per evitare sovrascritture.', 'warning', 'processing');
        } else if (res?.cancelled) {
          void refreshArchiveSessions();
          return;
        } else if (res?.quota_exhausted) {
          addNotification('Quota esaurita', 'Quota giornaliera esaurita: riprova domani.', 'warning', 'processing');
        } else {
          addNotification('Errore di revisione', res?.error ?? 'Impossibile completare la revisione dei blocchi.', 'error', 'processing');
        }
        throw new Error(res?.error ?? 'Retry non riuscito.');
      }
      const normalizedSessionDir = res.session_dir ?? sessionDir;
      const remaining = Array.isArray(res.remaining_failed_blocks) ? res.remaining_failed_blocks : [];
      dispatch({
        type: 'queue/update_revision_failed_blocks',
        fileId: _fileId,
        sessionDir: normalizedSessionDir,
        blocks: remaining,
        htmlPath: res.html_path,
        effectiveModel: res.effective_model,
      });
      setArchiveSessions(prev => prev.map(session =>
        normalizeSessionDir(session.session_dir) === normalizeSessionDir(normalizedSessionDir)
          ? {
              ...session,
              html_path: res.html_path ?? session.html_path,
              effective_model: res.effective_model ?? session.effective_model,
              completion_status: remaining.length > 0 ? 'completed_with_warnings' : 'completed',
              revision_failed_blocks: remaining,
            }
          : session,
      ));
      if (remaining.length > 0) {
        if (res.cancelled) {
          // Manual cancellation: user intentionally stopped the retry.
          // Card status and console already reflect the stopped state; no notification spam.
        } else if (res.quota_exhausted) {
          addNotification('Quota esaurita', `Quota giornaliera esaurita: ${remaining.length} ${remaining.length === 1 ? 'blocco resta non revisionato' : 'blocchi restano non revisionati'}. Riprova domani.`, 'warning', 'processing');
        } else {
          addNotification('Elaborazione parziale', `${remaining.length} ${remaining.length === 1 ? 'blocco resta non revisionato' : 'blocchi restano non revisionati'}. Puoi riprovare più tardi.`, 'warning', 'processing');
        }
      } else {
        addNotification('Elaborazione completata', 'Blocchi mancanti revisionati e HTML aggiornato.', 'success', 'processing');
      }
      void refreshArchiveSessions();
    } finally {
      dispatch({ type: 'queue/set_retrying_blocks', id: _fileId, value: false });
      dispatch({ type: 'app/set_status', status: 'idle' });
      dispatch({ type: 'bridge/update_phase', text: '' });
      dispatch({ type: 'bridge/update_progress', value: 0 });
    }
  }, [addNotification, archiveSessionsRef, dispatch, filesRef, normalizeSessionDir, refreshArchiveSessions, setArchiveSessions, setConfirmAction]);

  const handleRevisionWarning = useCallback((data: FileDonePayload) => {
    const count = data.revision_failed_blocks?.length ?? 0;
    if (count <= 0) return;
    const key = normalizeSessionDir(data.output_dir || data.id);
    if (key && warnedRevisionSessionsRef.current.has(key)) return;
    if (key) warnedRevisionSessionsRef.current.add(key);
    addNotification(
      'Completata con avvisi',
      `Completata con avvisi: ${count} ${count === 1 ? 'sezione è stata inclusa' : 'sezioni sono state incluse'} senza revisione AI.`,
      'warning',
      'processing',
      {
        dedupeKey: key || undefined,
        actionType: 'retry_failed_revision_blocks',
        actionData: { sessionDir: data.output_dir, fileId: data.id },
      },
    );
  }, [addNotification, normalizeSessionDir]);

  return {
    handleRetryFailedRevisionBlocks,
    handleRevisionWarning,
    warnedRevisionSessionsRef,
  };
}
