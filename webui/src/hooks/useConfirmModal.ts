import { useCallback, useMemo, useState } from 'react';
import type { ArchiveFolder, ArchiveSession, LowDiskWarning } from '../bridge';
import type { FileItem, ProcessingAction } from '../appState';

export type ConfirmActionState =
  | { type: 'stop-processing' }
  | { type: 'remove-file'; fileId: string; fileName: string; isDone: boolean }
  | { type: 'clear-completed'; count: number }
  | { type: 'clear-all' }
  | { type: 'low-disk-warning'; warning: LowDiskWarning }
  | { type: 'delete-archive-session'; sessionDir: string; name: string }
  | { type: 'delete-multiple-archive-sessions'; sessions: { sessionDir: string; name: string }[] }
  | { type: 'retry-archive-session'; session: ArchiveSession }
  | { type: 'quit-app' };

export type ConfirmAction = ConfirmActionState;

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
  return `${Math.round(bytes / 1_048_576)} MB`;
}

interface UseConfirmModalOptions {
  dispatch: React.Dispatch<ProcessingAction>;
  filesRef: React.MutableRefObject<FileItem[]>;
  foldersRef: React.MutableRefObject<ArchiveFolder[]>;
  setFolders: React.Dispatch<React.SetStateAction<ArchiveFolder[]>>;
  setArchiveSessions: React.Dispatch<React.SetStateAction<ArchiveSession[]>>;
  setArchiveTotal: React.Dispatch<React.SetStateAction<number>>;
  refreshArchiveSessions: () => Promise<void>;
  startProcessingRef: React.MutableRefObject<(isContinuation?: boolean, overrideLowDisk?: boolean) => Promise<boolean>>;
  executeRetryFromArchive: (session: ArchiveSession) => Promise<void>;
  normalizeSessionDir: (value?: string) => string;
  appendConsole: (msg: string) => void;
  isQuittingRef?: React.RefObject<boolean>;
  onFileRemovedFromBatch?: () => void;
}

export function useConfirmModal({
  dispatch,
  filesRef,
  foldersRef,
  setFolders,
  setArchiveSessions,
  setArchiveTotal,
  refreshArchiveSessions,
  startProcessingRef,
  executeRetryFromArchive,
  normalizeSessionDir,
  appendConsole,
  isQuittingRef,
  onFileRemovedFromBatch,
}: UseConfirmModalOptions) {
  const [confirmAction, setConfirmAction] = useState<ConfirmActionState | null>(null);

  const confirmStopProcessing = useCallback(async () => {
    setConfirmAction(null);
    dispatch({ type: 'app/set_status', status: 'canceling' });
    appendConsole('[!] Annullamento in corso, attendere prego...');
    if (window.pywebview?.api) await window.pywebview.api.stop_processing?.();
  }, [appendConsole, dispatch]);

  const confirmClearCompleted = useCallback(() => {
    setConfirmAction(null);
    dispatch({ type: 'queue/clear_completed' });
    void refreshArchiveSessions();
  }, [dispatch, refreshArchiveSessions]);

  const confirmModalCopy = useMemo(() => {
    if (!confirmAction) return null;
    if (confirmAction.type === 'stop-processing') {
      return {
        title: 'Interrompere la sbobinatura?',
        description: "Stai per fermare l'elaborazione in corso. Il processo verrà interrotto e il file attuale tornerà in coda. Vuoi continuare?",
        confirmLabel: 'Conferma stop',
        cancelLabel: 'Continua elaborazione',
      };
    }
    if (confirmAction.type === 'remove-file') {
      return {
        title: 'Rimuovere questo elemento?',
        description: confirmAction.isDone
          ? `"${confirmAction.fileName}" verrà spostata nell'archivio e rimossa dalla lista. Vuoi continuare?`
          : `"${confirmAction.fileName}" verrà rimossa dalla lista. Vuoi continuare?`,
        confirmLabel: 'Conferma rimozione',
        cancelLabel: 'Tieni elemento',
      };
    }
    if (confirmAction.type === 'clear-all') {
      return {
        title: 'Svuotare tutta la coda?',
        description: "Tutti i file in coda verranno rimossi. L'operazione non può essere annullata.",
        confirmLabel: 'Svuota coda',
        cancelLabel: 'Annulla',
      };
    }
    if (confirmAction.type === 'low-disk-warning') {
      const { warning } = confirmAction;
      const fileLabel = warning.file_name ? ` per "${warning.file_name}"` : '';
      return {
        title: 'Spazio libero insufficiente',
        description: `Lo spazio libero sembra insufficiente${fileLabel}. Stimato richiesto: ${formatBytes(warning.needed_bytes)} · disponibile: ${formatBytes(warning.free_bytes)} in ${warning.location}. Libera spazio prima di continuare, oppure procedi assumendoti il rischio di errore durante l'elaborazione.`,
        confirmLabel: 'Continua comunque',
        cancelLabel: 'Torna alla coda',
      };
    }
    if (confirmAction.type === 'delete-archive-session') {
      return {
        title: 'Eliminare questa sbobina?',
        description: `"${confirmAction.name}" e tutti i suoi dati di sessione verranno eliminati definitivamente dal disco. L'operazione è irreversibile.`,
        confirmLabel: 'Elimina definitivamente',
        cancelLabel: 'Annulla',
      };
    }
    if (confirmAction.type === 'delete-multiple-archive-sessions') {
      const count = confirmAction.sessions.length;
      return {
        title: count === 1 ? 'Eliminare questa sbobina?' : `Eliminare ${count} sbobine?`,
        description: `Tutti i file e i dati di sessione relativi alle ${count} sbobine selezionate verranno eliminati definitivamente dal disco. L'operazione è irreversibile.`,
        confirmLabel: count === 1 ? 'Elimina definitivamente' : `Elimina ${count} sbobine`,
        cancelLabel: 'Annulla',
      };
    }
    if (confirmAction.type === 'retry-archive-session') {
      return {
        title: 'Ripristinare e riprovare la revisione?',
        description: `La sbobina "${confirmAction.session.name}" verrà spostata nella coda di elaborazione per revisionare i blocchi mancanti. Vuoi procedere?`,
        confirmLabel: 'Riprova revisione',
        cancelLabel: 'Annulla',
      };
    }
    if (confirmAction.type === 'quit-app') {
      return {
        title: 'Elaborazione in corso',
        description: "Un'elaborazione è attualmente in corso. Se chiudi l'applicazione, il processo verrà interrotto e i progressi non salvati andranno persi. Vuoi davvero uscire?",
        confirmLabel: 'Interrompi ed esci',
        cancelLabel: 'Continua elaborazione',
      };
    }
    return {
      title: 'Pulire le sbobine completate?',
      description:
        confirmAction.count === 1
          ? "La sbobina completata verrà spostata nell'archivio e rimossa dalla lista. Vuoi continuare?"
          : `Le ${confirmAction.count} sbobine completate verranno spostate nell'archivio e rimosse dalla lista. Vuoi continuare?`,
      confirmLabel: 'Conferma pulizia',
      cancelLabel: 'Mantieni nella lista',
    };
  }, [confirmAction]);

  const handleConfirmAction = useCallback(() => {
    if (!confirmAction) return;
    if (confirmAction.type === 'quit-app') {
      setConfirmAction(null);
      if (isQuittingRef) {
        isQuittingRef.current = true;
      }
      (window as unknown as { __jotQuitting?: boolean }).__jotQuitting = true;
      if (window.pywebview?.api?.close_window) {
        void window.pywebview.api.close_window();
      }
      return;
    }
    if (confirmAction.type === 'stop-processing') {
      void confirmStopProcessing();
      return;
    }
    if (confirmAction.type === 'remove-file') {
      const removedFile = filesRef.current.find(f => f.id === confirmAction.fileId);
      dispatch({ type: 'queue/remove', id: confirmAction.fileId });
      setConfirmAction(null);
      if (removedFile?.status === 'queued') onFileRemovedFromBatch?.();
      if (removedFile?.status === 'done') void refreshArchiveSessions();
      return;
    }
    if (confirmAction.type === 'clear-all') {
      setConfirmAction(null);
      dispatch({ type: 'queue/clear_all' });
      return;
    }
    if (confirmAction.type === 'low-disk-warning') {
      setConfirmAction(null);
      void startProcessingRef.current(false, true);
      return;
    }
    if (confirmAction.type === 'delete-archive-session') {
      const { sessionDir } = confirmAction;
      setConfirmAction(null);
      window.pywebview?.api?.delete_session?.(sessionDir).then(res => {
        if (res?.ok) {
          const normTarget = normalizeSessionDir(sessionDir);
          setArchiveSessions(prev => prev.filter(s => normalizeSessionDir(s.session_dir) !== normTarget));
          setArchiveTotal(prev => Math.max(0, prev - 1));
          const updated = foldersRef.current.map(folder => ({
            ...folder,
            session_dirs: folder.session_dirs.filter(d => normalizeSessionDir(d) !== normTarget),
          }));
          setFolders(updated);
          void window.pywebview?.api?.save_archive_folders?.(updated).catch(() => {});
        } else {
          appendConsole(`❌ Errore eliminazione sessione: ${res?.error ?? 'errore sconosciuto'}`);
        }
      }).catch((e: unknown) => {
        appendConsole(`❌ Errore eliminazione sessione: ${getErrorMessage(e)}`);
      });
      return;
    }
    if (confirmAction.type === 'delete-multiple-archive-sessions') {
      const { sessions: targetSessions } = confirmAction;
      setConfirmAction(null);
      const dirs = targetSessions.map(s => s.sessionDir);
      const normDirSet = new Set(dirs.map(d => normalizeSessionDir(d)));
      Promise.all(dirs.map(d => window.pywebview?.api?.delete_session?.(d))).then(() => {
        setArchiveSessions(prev => prev.filter(s => !normDirSet.has(normalizeSessionDir(s.session_dir))));
        setArchiveTotal(prev => Math.max(0, prev - dirs.length));
        const updated = foldersRef.current.map(folder => ({
          ...folder,
          session_dirs: folder.session_dirs.filter(d => !normDirSet.has(normalizeSessionDir(d))),
        }));
        setFolders(updated);
        void window.pywebview?.api?.save_archive_folders?.(updated).catch(() => {});
      }).catch((e: unknown) => {
        appendConsole(`❌ Errore eliminazione sessioni: ${getErrorMessage(e)}`);
      });
      return;
    }
    if (confirmAction.type === 'retry-archive-session') {
      const { session } = confirmAction;
      setConfirmAction(null);
      void executeRetryFromArchive(session);
      return;
    }
    confirmClearCompleted();
  }, [
    confirmAction,
    confirmClearCompleted,
    confirmStopProcessing,
    appendConsole,
    refreshArchiveSessions,
    executeRetryFromArchive,
    normalizeSessionDir,
    filesRef,
    dispatch,
    startProcessingRef,
    isQuittingRef,
    setArchiveSessions,
    setArchiveTotal,
    foldersRef,
    setFolders,
    onFileRemovedFromBatch,
  ]);

  const requestQuitConfirmation = useCallback(() => {
    setConfirmAction({ type: 'quit-app' });
  }, []);

  return {
    confirmAction,
    setConfirmAction,
    confirmModalCopy,
    handleConfirmAction,
    confirmStopProcessing,
    confirmClearCompleted,
    requestQuitConfirmation,
  };
}
