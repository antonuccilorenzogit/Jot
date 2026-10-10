import { reportClientError } from '../diagnostics';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ArchiveFolder, ArchiveSession } from '../bridge';
import type { FileItem, ProcessingAction } from '../appState';
import { filterArchiveSessionsByInputPath } from '../duplicateDetection';
import type { ActivePage } from '../components/NavSidebar';

export type PendingArchiveReplacement = {
  fileName: string;
  inputPath?: string;
  sessions: ArchiveSession[];
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface UseArchiveSyncOptions {
  files: FileItem[];
  dispatch: React.Dispatch<ProcessingAction>;
  activePage: ActivePage;
  setActivePage: (page: ActivePage) => void;
  appState: string;
  apiReady: boolean;
  appendConsole: (msg: string) => void;
  addNotification: (
    title: string,
    message: string,
    type: 'info' | 'warning' | 'error' | 'success',
    category: 'update' | 'system' | 'processing',
    options?: {
      persistent?: boolean;
      dedupeKey?: string;
      actionType?: 'retry_failed_revision_blocks' | 'install_update' | 'open_github' | 'open_settings';
      actionData?: unknown;
    },
  ) => void;
  handleRetryFailedRevisionBlocks: (sessionDir: string, fileId?: string) => Promise<void>;
}

export function useArchiveSync({
  files,
  dispatch,
  activePage,
  setActivePage,
  appState,
  apiReady,
  appendConsole,
  addNotification,
  handleRetryFailedRevisionBlocks,
}: UseArchiveSyncOptions) {
  const [archiveSessions, setArchiveSessions] = useState<ArchiveSession[]>([]);
  const [archiveTotal, setArchiveTotal] = useState(0);
  const [isArchiveLoaded, setIsArchiveLoaded] = useState(false);
  const [folders, setFolders] = useState<ArchiveFolder[]>([]);

  const archiveLimitRef = useRef(0);
  const prevSessionDirsRef = useRef<Map<string, string>>(new Map());
  const archiveSessionsRef = useRef<ArchiveSession[]>(archiveSessions);
  const foldersRef = useRef<ArchiveFolder[]>(folders);
  const filesRef = useRef<FileItem[]>(files);
  const appStateRef = useRef(appState);
  const pendingArchiveReplacementsRef = useRef<Map<string, PendingArchiveReplacement>>(new Map());
  const archiveReplacementCleanupInFlightRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    archiveSessionsRef.current = archiveSessions;
    foldersRef.current = folders;
    filesRef.current = files;
    appStateRef.current = appState;
  });

  const normalizeSessionDir = useCallback((value?: string) =>
    String(value || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase(), []);

  const refreshArchiveSessions = useCallback(async (limitOverride?: number) => {
    const lim = limitOverride !== undefined ? limitOverride : archiveLimitRef.current;
    try {
      const result = await window.pywebview?.api?.get_completed_sessions?.(lim <= 0 ? 0 : lim);
      if (result?.ok && result.sessions) {
        setArchiveSessions(result.sessions);
        setArchiveTotal(result.total ?? result.sessions.length);
        prevSessionDirsRef.current = new Map(result.sessions.map((s: ArchiveSession) => [normalizeSessionDir(s.session_dir), s.name]));
        try {
          localStorage.setItem('jot.has_sessions.v1', String(result.sessions.length > 0));
        } catch (_) {}
      }
    } catch (_) {} finally {
      setIsArchiveLoaded(true);
    }
  }, [normalizeSessionDir]);

  useEffect(() => {
    if (isArchiveLoaded) {
      try {
        localStorage.setItem('jot.has_sessions.v1', String(archiveSessions.length > 0));
      } catch (_) {}
    }
  }, [archiveSessions, isArchiveLoaded]);

  const handleLoadAll = useCallback(() => {
    archiveLimitRef.current = 0;
    void refreshArchiveSessions(0);
  }, [refreshArchiveSessions]);

  const handleOpenFailed = useCallback((_htmlPath: string, sessionDir: string) => {
    addNotification(
      'File non disponibile',
      'La sbobina non è più disponibile: il file è stato eliminato dal disco.',
      'warning',
      'system',
    );
    if (sessionDir) {
      setArchiveSessions(prev => prev.filter(s => s.session_dir !== sessionDir));
      setArchiveTotal(prev => Math.max(0, prev - 1));
      prevSessionDirsRef.current.delete(normalizeSessionDir(sessionDir));
    }
  }, [addNotification, normalizeSessionDir]);

  const handleFoldersChange = useCallback(async (next: ArchiveFolder[]) => {
    setFolders(next);
    try {
      await window.pywebview?.api?.save_archive_folders?.(next);
    } catch (_) {}
  }, []);

  const handleSessionRootMoved = useCallback(async (payload?: { oldRoot?: string; newRoot?: string }) => {
    if (payload?.oldRoot && payload?.newRoot) {
      dispatch({
        type: 'queue/remap_session_roots',
        oldRoot: payload.oldRoot,
        newRoot: payload.newRoot,
      });
    }
    await refreshArchiveSessions();
    try {
      const res = await window.pywebview?.api?.get_archive_folders?.();
      if (res?.ok && res.folders) {
        setFolders(res.folders);
      }
    } catch (_) {}
  }, [dispatch, refreshArchiveSessions]);

  const finalizeArchiveReplacement = useCallback(async (fileId: string) => {
    const pendingReplacement = pendingArchiveReplacementsRef.current.get(fileId);
    if (!pendingReplacement || archiveReplacementCleanupInFlightRef.current.has(fileId)) return;
    archiveReplacementCleanupInFlightRef.current.add(fileId);
    const deletedSessionDirs: string[] = [];
    const currentFile = filesRef.current.find(file => file.id === fileId);
    const deletableSessions = filterArchiveSessionsByInputPath(
      pendingReplacement.inputPath || currentFile?.path,
      pendingReplacement.sessions,
    );
    const rawNewDir = currentFile?.outputDir
      || (currentFile?.outputHtml ? String(currentFile.outputHtml).replace(/[^/\\]+$/, '').replace(/[/\\]+$/, '') : undefined);
    const newOutputDirNorm = rawNewDir ? String(rawNewDir).replace(/[/\\]+$/, '').toLowerCase() : null;
    try {
      for (const session of deletableSessions) {
        const sessionDirNorm = String(session.session_dir).replace(/[/\\]+$/, '').toLowerCase();
        if (newOutputDirNorm && sessionDirNorm === newOutputDirNorm) continue;
        try {
          const res = await window.pywebview?.api?.delete_session?.(session.session_dir);
          if (res?.ok) {
            deletedSessionDirs.push(session.session_dir);
          } else {
            appendConsole(`❌ Errore eliminazione sessione archiviata per ${pendingReplacement.fileName}: ${res?.error ?? 'errore sconosciuto'}`);
          }
        } catch (error) {
          appendConsole(`❌ Errore eliminazione sessione archiviata per ${pendingReplacement.fileName}: ${getErrorMessage(error)}`);
        }
      }
      if (deletedSessionDirs.length > 0) {
        const deletedNorm = new Set(deletedSessionDirs.map(d => normalizeSessionDir(d)));
        for (const dir of deletedSessionDirs) {
          prevSessionDirsRef.current.delete(normalizeSessionDir(dir));
        }
        setArchiveSessions(prev => prev.filter(s => !deletedNorm.has(normalizeSessionDir(s.session_dir))));
        setArchiveTotal(prev => Math.max(0, prev - deletedSessionDirs.length));
        const updated = foldersRef.current.map(folder => ({
          ...folder,
          session_dirs: folder.session_dirs.filter(d => !deletedNorm.has(normalizeSessionDir(d))),
        }));
        setFolders(updated);
        void window.pywebview?.api?.save_archive_folders?.(updated).catch(() => {});
      }
      if (deletedSessionDirs.length !== deletableSessions.length) {
        await refreshArchiveSessions();
      }
    } finally {
      pendingArchiveReplacementsRef.current.delete(fileId);
      archiveReplacementCleanupInFlightRef.current.delete(fileId);
    }
  }, [appendConsole, refreshArchiveSessions, normalizeSessionDir]);

  useEffect(() => {
    const currentFileIds = new Set(files.map(f => f.id));
    for (const fileId of pendingArchiveReplacementsRef.current.keys()) {
      if (!currentFileIds.has(fileId)) {
        pendingArchiveReplacementsRef.current.delete(fileId);
        archiveReplacementCleanupInFlightRef.current.delete(fileId);
      }
    }
    for (const file of files) {
      if (file.status === 'done' && pendingArchiveReplacementsRef.current.has(file.id)) {
        void finalizeArchiveReplacement(file.id);
      }
    }
  }, [files, finalizeArchiveReplacement]);

  // Initial load when api is ready
  useEffect(() => {
    if (!apiReady) return;
    void refreshArchiveSessions();
    window.pywebview?.api?.get_archive_folders?.().then(res => {
      if (res?.ok && res.folders) setFolders(res.folders);
    }).catch(() => {});
  }, [apiReady, refreshArchiveSessions]);

  // Polling interval when activePage === 'archive'
  useEffect(() => {
    if (activePage !== 'archive') return;
    prevSessionDirsRef.current = new Map(archiveSessionsRef.current.map(s => [normalizeSessionDir(s.session_dir), s.name]));
    const intervalId = setInterval(async () => {
      try {
        const lim = archiveLimitRef.current;
        const result = await window.pywebview?.api?.get_completed_sessions?.(lim <= 0 ? 0 : lim);
        if (!result?.ok || !result.sessions) return;
        const newSessions: ArchiveSession[] = result.sessions;
        const newDirs = new Set<string>(newSessions.map(s => normalizeSessionDir(s.session_dir)));
        if (newSessions.length > 0 || prevSessionDirsRef.current.size <= 2) {
          for (const [dir, name] of prevSessionDirsRef.current.entries()) {
            if (!newDirs.has(dir)) {
              addNotification(
                'Sessione cancellata',
                `La sessione "${name}" è stata cancellata e la sbobina non è più disponibile.`,
                'warning',
                'system',
                { dedupeKey: `session-deleted:${dir}` },
              );
            }
          }
        }
        setArchiveSessions(newSessions);
        setArchiveTotal(result.total ?? newSessions.length);
        prevSessionDirsRef.current = new Map(newSessions.map(s => [normalizeSessionDir(s.session_dir), s.name]));
      } catch (_) {}
    }, 30_000);
    return () => {
      clearInterval(intervalId);
      archiveLimitRef.current = 0;
    };
  }, [activePage, addNotification, normalizeSessionDir]);

  const executeRetryFromArchive = useCallback(async (session: ArchiveSession) => {
    const normDir = normalizeSessionDir(session.session_dir);
    const existing = filesRef.current.find(f => normalizeSessionDir(f.outputDir) === normDir);

    if (existing?.isRetryingBlocks) {
      addNotification('Retry in corso', 'Retry già in corso per questa sessione.', 'warning', 'processing');
      return;
    }
    if (appStateRef.current !== 'idle') {
      addNotification('Elaborazione in corso', 'Elaborazione in corso: riprova al termine.', 'warning', 'processing');
      return;
    }

    setActivePage('queue');
    const fileId = existing ? existing.id : `archive-${Date.now()}`;
    if (!existing) {
      const newFile: FileItem = {
        id: fileId,
        name: session.name,
        size: session.input_size ?? 0,
        duration: session.duration_sec ?? 0,
        status: 'processing',
        progress: 0,
        phase: 2,
        path: session.input_path,
        outputHtml: session.html_path,
        outputDir: session.session_dir,
        completedAt: session.completed_at_iso ? new Date(session.completed_at_iso).getTime() : Date.now(),
        effectiveModel: session.effective_model,
        completionStatus: 'completed_with_warnings',
        revisionFailedBlocks: session.revision_failed_blocks,
        isRetryingBlocks: true,
      };
      dispatch({ type: 'queue/prepend', files: [newFile] });
    } else {
      dispatch({ type: 'queue/set_retrying_blocks', id: fileId, value: true });
    }
    try {
      await handleRetryFailedRevisionBlocks(session.session_dir, fileId);
    } catch (err) {
      reportClientError('Archive retry error:', err);
    } finally {
      dispatch({ type: 'queue/set_retrying_blocks', id: fileId, value: false });
    }
  }, [handleRetryFailedRevisionBlocks, normalizeSessionDir, addNotification, setActivePage, dispatch]);

  const archiveFiltered = useMemo(() => {
    const activeHtmlPaths = new Set(files.map(f => normalizeSessionDir(f.outputHtml)).filter(Boolean));
    const currentFileIds = new Set(files.map(f => f.id));
    const pendingSessionDirs = new Set<string>();
    const pendingHtmlPaths = new Set<string>();

    for (const [fileId, replacement] of pendingArchiveReplacementsRef.current.entries()) {
      if (currentFileIds.has(fileId)) {
        for (const s of replacement.sessions) {
          if (s.session_dir) {
            pendingSessionDirs.add(normalizeSessionDir(s.session_dir));
          }
          if (s.html_path) {
            pendingHtmlPaths.add(normalizeSessionDir(s.html_path));
          }
        }
      }
    }

    return archiveSessions.filter(
      s => !activeHtmlPaths.has(normalizeSessionDir(s.html_path))
        && !pendingHtmlPaths.has(normalizeSessionDir(s.html_path))
        && !pendingSessionDirs.has(normalizeSessionDir(s.session_dir)),
    );
  }, [archiveSessions, files, normalizeSessionDir]);

  const completedSessionFolderMap = useMemo(() => {
    const map = new Map<string, ArchiveFolder>();
    for (const folder of folders) for (const dir of folder.session_dirs) map.set(normalizeSessionDir(dir), folder);
    return map;
  }, [folders, normalizeSessionDir]);

  return {
    archiveSessions,
    setArchiveSessions,
    archiveTotal,
    setArchiveTotal,
    isArchiveLoaded,
    folders,
    setFolders,
    archiveLimitRef,
    archiveSessionsRef,
    foldersRef,
    pendingArchiveReplacementsRef,
    normalizeSessionDir,
    refreshArchiveSessions,
    handleLoadAll,
    handleOpenFailed,
    handleFoldersChange,
    handleSessionRootMoved,
    finalizeArchiveReplacement,
    executeRetryFromArchive,
    archiveFiltered,
    completedSessionFolderMap,
  };
}
