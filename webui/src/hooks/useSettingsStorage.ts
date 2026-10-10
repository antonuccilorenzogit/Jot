import { useCallback, useEffect, useRef, useState } from 'react';

export const SESSION_CLEANUP_DAYS = 30;

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export interface SessionStorageInfo {
  total_bytes: number;
  total_sessions: number;
  session_root: string;
}

export interface UseSettingsStorageOptions {
  isOpen: boolean;
  activeTab: 'general' | 'models' | 'diagnostics' | 'advanced' | string;
  appendConsole: (msg: string) => void;
  onSessionRootMoved?: (payload?: { oldRoot?: string; newRoot?: string }) => void;
}


export interface CleanupResult {
  removed: number;
  freed_bytes: number;
  candidates?: number;
  preserved_completed?: number;
  missing_completed_html?: number;
}

export interface CleanupPreview {
  removed: number;
  freed_bytes: number;
  candidates?: number;
}

export function useSettingsStorage({
  isOpen,
  activeTab,
  appendConsole,
  onSessionRootMoved,
}: UseSettingsStorageOptions) {
  const [sessionInfo, setSessionInfo] = useState<SessionStorageInfo | null>(null);
  const [isLoadingSessionInfo, setIsLoadingSessionInfo] = useState(false);
  const [isMoveInProgress, setIsMoveInProgress] = useState(false);
  const [moveProgress, setMoveProgress] = useState<{ moved: number; total: number } | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [pendingMovePath, setPendingMovePath] = useState<string | null>(null);
  const [showMoveConfirm, setShowMoveConfirm] = useState(false);

  const [isCleaningSession, setIsCleaningSession] = useState(false);
  const [isCleaningCompletedSessions, setIsCleaningCompletedSessions] = useState(false);
  const [showCleanupConfirm, setShowCleanupConfirm] = useState(false);
  const [showCompletedCleanupConfirm, setShowCompletedCleanupConfirm] = useState(false);
  const [cleanupPreview, setCleanupPreview] = useState<CleanupPreview | null>(null);
  const [completedCleanupPreview, setCompletedCleanupPreview] = useState<CleanupPreview | null>(null);
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null);
  const [completedCleanupResult, setCompletedCleanupResult] = useState<CleanupPreview | null>(null);

  const isMountedRef = useRef(true);
  const isOpenRef = useRef(isOpen);
  const sessionInfoReqIdRef = useRef(0);
  const moveTimerRef = useRef<NodeJS.Timeout | null>(null);
  const cleanupDismissTimerRef = useRef<NodeJS.Timeout | null>(null);
  const pollMoveStatusRef = useRef<() => Promise<void>>(() => Promise.resolve());

  const handleDismissCleanupResult = useCallback(() => {
    if (cleanupDismissTimerRef.current) {
      clearTimeout(cleanupDismissTimerRef.current);
      cleanupDismissTimerRef.current = null;
    }
    setCleanupResult(null);
    setCompletedCleanupResult(null);
  }, []);

  const scheduleCleanupDismiss = useCallback(() => {
    if (cleanupDismissTimerRef.current) {
      clearTimeout(cleanupDismissTimerRef.current);
    }
    cleanupDismissTimerRef.current = setTimeout(() => {
      if (isMountedRef.current) {
        setCleanupResult(null);
        setCompletedCleanupResult(null);
      }
      cleanupDismissTimerRef.current = null;
    }, 5000);
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (cleanupDismissTimerRef.current) {
        clearTimeout(cleanupDismissTimerRef.current);
        cleanupDismissTimerRef.current = null;
      }
    };
  }, []);

  const fetchSessionStorageInfo = useCallback(() => {
    if (!window.pywebview?.api?.get_session_storage_info) return;
    const reqId = ++sessionInfoReqIdRef.current;
    setIsLoadingSessionInfo(true);
    setSessionInfo(null);
    try {
      const p = window.pywebview.api.get_session_storage_info();
      if (!p || typeof p.then !== 'function') {
        return;
      }
      p.then((res) => {
        if (!isOpenRef.current || !isMountedRef.current || reqId !== sessionInfoReqIdRef.current) return;
        if (res?.ok) {
          setSessionInfo({
            total_bytes: res.total_bytes ?? 0,
            total_sessions: res.total_sessions ?? 0,
            session_root: res.session_root ?? '',
          });
        }
      })
      .catch(() => {})
      .finally(() => {
        if (isOpenRef.current && isMountedRef.current && reqId === sessionInfoReqIdRef.current) {
          setIsLoadingSessionInfo(false);
        }
      });
    } catch {
      setIsLoadingSessionInfo(false);
    }
  }, []);

  const pollMoveStatus = useCallback(async () => {
    try {
      const res = await window.pywebview?.api?.get_session_move_status?.();
      if (!res || !isOpenRef.current || !isMountedRef.current) return;
      if (res.status === 'moving') {
        setMoveProgress({ moved: res.moved ?? 0, total: res.total ?? 0 });
        moveTimerRef.current = setTimeout(() => void pollMoveStatusRef.current(), 500);
      } else if (res.status === 'done') {
        setIsMoveInProgress(false);
        setMoveProgress(null);
        if (window.pywebview?.api?.get_session_storage_info) {
          const info = await window.pywebview.api.get_session_storage_info();
          if (info?.ok && isOpenRef.current && isMountedRef.current) {
            setSessionInfo({
              total_bytes: info.total_bytes ?? 0,
              total_sessions: info.total_sessions ?? 0,
              session_root: info.session_root ?? '',
            });
          }
        }
        onSessionRootMoved?.({
          oldRoot: res.old_root,
          newRoot: res.new_root,
        });
      } else if (res.status === 'error') {
        setIsMoveInProgress(false);
        setMoveProgress(null);
        setMoveError(res.error ?? 'Errore sconosciuto');
      }
    } catch {
      if (isMountedRef.current) {
        setIsMoveInProgress(false);
        setMoveProgress(null);
        setMoveError('Errore di connessione API');
      }
    }
  }, [onSessionRootMoved]);

  useEffect(() => {
    pollMoveStatusRef.current = pollMoveStatus;
  }, [pollMoveStatus]);

  useEffect(() => {
    isOpenRef.current = isOpen;
    if (cleanupDismissTimerRef.current) {
      clearTimeout(cleanupDismissTimerRef.current);
      cleanupDismissTimerRef.current = null;
    }
    setCleanupResult(null);
    setCompletedCleanupResult(null);
    setCleanupPreview(null);
    setCompletedCleanupPreview(null);
    setMoveError(null);
    setPendingMovePath(null);
    setShowCleanupConfirm(false);
    setShowCompletedCleanupConfirm(false);
    setShowMoveConfirm(false);

    if (!isOpen) {
      ++sessionInfoReqIdRef.current;
      return;
    }

    let aborted = false;

    if (activeTab === 'storage' || activeTab === 'models' || activeTab === 'advanced') {
      fetchSessionStorageInfo();
    }



    if (window.pywebview?.api?.get_session_move_status) {
      window.pywebview.api
        .get_session_move_status()
        .then((res) => {
          if (aborted || !isMountedRef.current) return;
          if (res?.status === 'moving') {
            setIsMoveInProgress(true);
            setMoveProgress({ moved: res.moved ?? 0, total: res.total ?? 0 });
            void pollMoveStatus();
          }
        })
        .catch(() => {});
    }

    return () => {
      aborted = true;
      if (moveTimerRef.current) {
        clearTimeout(moveTimerRef.current);
        moveTimerRef.current = null;
      }
      if (cleanupDismissTimerRef.current) {
        clearTimeout(cleanupDismissTimerRef.current);
        cleanupDismissTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const handleOpenSessionFolder = () => {
    window.pywebview?.api?.open_session_folder?.();
  };

  const handleAskMoveFolder = async () => {
    if (isMoveInProgress) return;
    const res = await window.pywebview?.api?.ask_session_folder?.();
    if (!res?.ok || !res.path) return;
    setPendingMovePath(res.path);
    setMoveError(null);
    setShowMoveConfirm(true);
  };

  const handleConfirmMove = async () => {
    if (!pendingMovePath) return;
    setShowMoveConfirm(false);
    setMoveError(null);
    const res = await window.pywebview?.api?.move_session_root?.(pendingMovePath);
    setPendingMovePath(null);
    if (!res?.ok) {
      setMoveError(res?.error ?? 'Errore sconosciuto');
      return;
    }
    setIsMoveInProgress(true);
    setMoveProgress({ moved: 0, total: 0 });
    void pollMoveStatus();
  };

  const handleCancelMove = useCallback(() => {
    setShowMoveConfirm(false);
    setPendingMovePath(null);
  }, []);

  const handleAskCleanup = async () => {
    if (!window.pywebview?.api?.cleanup_old_sessions || isCleaningSession) return;
    setIsCleaningSession(true);
    setCleanupPreview(null);
    try {
      const res = await window.pywebview.api.cleanup_old_sessions(0, true);
      if (!isMountedRef.current) return;
      if (res?.ok) {
        setCleanupPreview({
          removed: res.removed ?? 0,
          freed_bytes: res.freed_bytes ?? 0,
          candidates: res.candidates ?? 0,
        });
        setShowCleanupConfirm(true);
      } else {
        appendConsole(`❌ Conteggio sbobine incomplete fallito: ${res?.error || 'errore sconosciuto'}`);
      }
    } catch (e: unknown) {
      if (isMountedRef.current) appendConsole(`❌ Conteggio sbobine incomplete fallito: ${getErrorMessage(e)}`);
    } finally {
      if (isMountedRef.current) setIsCleaningSession(false);
    }
  };

  const handleCleanupSessions = async () => {
    if (!window.pywebview?.api?.cleanup_old_sessions) return;
    setShowCleanupConfirm(false);
    setIsCleaningSession(true);
    setCleanupResult(null);
    try {
      const res = await window.pywebview.api.cleanup_old_sessions(0, false);
      if (!isMountedRef.current) return;
      if (res?.ok) {
        setCleanupResult({
          removed: res.removed ?? 0,
          freed_bytes: res.freed_bytes ?? 0,
          candidates: res.candidates ?? res.removed ?? 0,
          preserved_completed: res.preserved_completed ?? 0,
          missing_completed_html: res.missing_completed_html ?? 0,
        });
        scheduleCleanupDismiss();
        if (window.pywebview?.api?.get_session_storage_info) {
          const info = await window.pywebview.api.get_session_storage_info();
          if (info?.ok && isMountedRef.current) {
            setSessionInfo({
              total_bytes: info.total_bytes ?? 0,
              total_sessions: info.total_sessions ?? 0,
              session_root: info.session_root ?? '',
            });
          }
        }
      } else {
        appendConsole(`❌ Pulizia sessioni fallita: ${res?.error || 'errore sconosciuto'}`);
      }
    } catch (e: unknown) {
      if (isMountedRef.current) appendConsole(`❌ Pulizia sessioni fallita: ${getErrorMessage(e)}`);
    } finally {
      if (isMountedRef.current) setIsCleaningSession(false);
    }
  };

  const handleAskCompletedCleanup = async () => {
    if (!window.pywebview?.api?.cleanup_completed_sessions || isCleaningCompletedSessions) return;
    setIsCleaningCompletedSessions(true);
    setCompletedCleanupPreview(null);
    try {
      const res = await window.pywebview.api.cleanup_completed_sessions(SESSION_CLEANUP_DAYS, true);
      if (!isMountedRef.current) return;
      if (res?.ok) {
        setCompletedCleanupPreview({
          removed: res.removed ?? 0,
          freed_bytes: res.freed_bytes ?? 0,
          candidates: res.candidates ?? 0,
        });
        setShowCompletedCleanupConfirm(true);
      } else {
        appendConsole(`❌ Conteggio sbobine completate fallito: ${res?.error || 'errore sconosciuto'}`);
      }
    } catch (e: unknown) {
      if (isMountedRef.current) appendConsole(`❌ Conteggio sbobine completate fallito: ${getErrorMessage(e)}`);
    } finally {
      if (isMountedRef.current) setIsCleaningCompletedSessions(false);
    }
  };

  const handleCleanupCompletedSessions = async () => {
    if (!window.pywebview?.api?.cleanup_completed_sessions) return;
    setShowCompletedCleanupConfirm(false);
    setIsCleaningCompletedSessions(true);
    try {
      const res = await window.pywebview.api.cleanup_completed_sessions(SESSION_CLEANUP_DAYS, false);
      if (!isMountedRef.current) return;
      if (res?.ok) {
        setCompletedCleanupResult({
          removed: res.removed ?? 0,
          freed_bytes: res.freed_bytes ?? 0,
          candidates: res.candidates ?? res.removed ?? 0,
        });
        scheduleCleanupDismiss();
        if (window.pywebview?.api?.get_session_storage_info) {
          const info = await window.pywebview.api.get_session_storage_info();
          if (info?.ok && isMountedRef.current) {
            setSessionInfo({
              total_bytes: info.total_bytes ?? 0,
              total_sessions: info.total_sessions ?? 0,
              session_root: info.session_root ?? '',
            });
          }
        }
      } else {
        appendConsole(`❌ Pulizia sbobine completate fallita: ${res?.error || 'errore sconosciuto'}`);
      }
    } catch (e: unknown) {
      if (isMountedRef.current) appendConsole(`❌ Pulizia sbobine completate fallita: ${getErrorMessage(e)}`);
    } finally {
      if (isMountedRef.current) setIsCleaningCompletedSessions(false);
    }
  };

  return {
    sessionInfo,
    isLoadingSessionInfo,
    fetchSessionStorageInfo,
    isMoveInProgress,
    moveProgress,
    moveError,
    pendingMovePath,
    showMoveConfirm,
    setShowMoveConfirm,
    handleOpenSessionFolder,
    handleAskMoveFolder,
    handleConfirmMove,
    handleCancelMove,
    isCleaningSession,
    isCleaningCompletedSessions,
    showCleanupConfirm,
    setShowCleanupConfirm,
    showCompletedCleanupConfirm,
    setShowCompletedCleanupConfirm,
    cleanupPreview,
    completedCleanupPreview,
    cleanupResult,
    completedCleanupResult,
    handleAskCleanup,
    handleCleanupSessions,
    handleAskCompletedCleanup,
    handleCleanupCompletedSessions,
    handleDismissCleanupResult,
  };
}
