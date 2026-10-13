import React, { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { GithubIcon } from './components/icons/GithubIcon';
import { APP_NAME, GITHUB_URL, UPDATE_CHECKS_ENABLED } from './branding';
import { type JotBridge, type PywebviewApi } from './bridge';
import { createInitialProcessingState, processingReducer, type FileItem } from './appState';
import { GEMINI_KEY_PATTERN, isQuotaError } from './utils';
import type { QuotaSnapshot } from './bridge';
import type { ScheduledLesson } from './components/lesson/LessonComposer';
import { STORAGE_KEYS } from './storageKeys';
import { useConsole } from './hooks/useConsole';
import { useTheme } from './hooks/useTheme';
import { useUpdateChecker } from './hooks/useUpdateChecker';
import { loadPersistedQueue, useQueuePersistence } from './hooks/useQueuePersistence';
import { useApiReady } from './hooks/useApiReady';
import { useBridgeCallbacks } from './hooks/useBridgeCallbacks';
import { getHostCapabilities } from './browserHost';
import { useBodyScrollLock } from './hooks/useBodyScrollLock';
import { usePreview } from './hooks/usePreview';
import { useNotifications } from './hooks/useNotifications';
import { useUpdateInstaller } from './hooks/useUpdateInstaller';
import { useArchiveSync } from './hooks/useArchiveSync';
import { useQueueIngest } from './hooks/useQueueIngest';
import { useConfirmModal } from './hooks/useConfirmModal';
import { useQueueProcessing } from './hooks/useQueueProcessing';
import { useRevisionRetry } from './hooks/useRevisionRetry';
import { useRegenerateDialog } from './hooks/useRegenerateDialog';
import type { EditorSaveController } from './hooks/useEditorAutosave';
import { useSystemNotificationTriggers } from './hooks/useSystemNotificationTriggers';
import { QueuePage } from './components/QueuePage';
import { RegenerateModal } from './components/modals/RegenerateModal';
import { NewKeyModal } from './components/modals/NewKeyModal';
import { ConfirmActionModal } from './components/modals/ConfirmActionModal';
import { DuplicateFileModal } from './components/modals/DuplicateFileModal';
import { NavSidebar, type ActivePage } from './components/NavSidebar';
import { NotificationDropdown } from './components/NotificationDropdown';
import { SplashScreen } from './components/brand/SplashScreen';

const EditorFullPage = React.lazy(() => import('./components/EditorFullPage').then(m => ({ default: m.EditorFullPage })));
const SettingsModal = React.lazy(() => import('./components/modals/SettingsModal').then(m => ({ default: m.SettingsModal })));
const archivePagePromise = import('./components/ArchivePage');
const ArchivePage = React.lazy(() => archivePagePromise.then(m => ({ default: m.ArchivePage })));

declare global {
  interface Window {
    pywebview?: { api?: PywebviewApi };
    jotBridge?: JotBridge;
  }
}

export default function App() {
  const [{ files, structuralVersion, appState, currentPhase, currentModel, activeProgress, workTotals, workDone }, dispatch] = useReducer(
    processingReducer,
    undefined,
    () => createInitialProcessingState(loadPersistedQueue()),
  );

  const { consoleLogs, appendConsole } = useConsole();
  const { themeMode, setThemeMode } = useTheme();
  const { updateAvailable, latestVersion, isCheckingUpdate, hasChecked, checkFailed, checkForUpdates, dismissUpdate } = useUpdateChecker(
    UPDATE_CHECKS_ENABLED && getHostCapabilities().updateInstallation,
  );
  const {
    apiReady,
    bridgeDelayed,
    apiKey,
    setApiKey,
    hasProtectedKey,
    apiKeyInsecure,
    setApiKeyInsecure,
    apiKeyInsecureReason,
    setApiKeyInsecureReason,
    configRecoveredFrom,
    fallbackKeys,
    setFallbackKeys,
    configuredFallbackKeyCount,
    preferredModel,
    setPreferredModel,
    fallbackModels,
    setFallbackModels,
    availableModels,
    refreshSettings,
  } = useApiReady(appendConsole);

  const [activePage, setActivePage] = useState<ActivePage>('queue');
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isConsoleExpanded, setIsConsoleExpanded] = useState(false);
  const [hasOpenedSettings, setHasOpenedSettings] = useState(false);
  const shouldRenderSettings = isSettingsOpen || hasOpenedSettings;

  useEffect(() => {
    if (isSettingsOpen) {
      setHasOpenedSettings(true);
    }
  }, [isSettingsOpen]);

  const handleRetryFailedRevisionBlocksRef = useRef<(sessionDir: string, fileId?: string) => Promise<void>>(() => Promise.resolve());
  const installUpdateRef = useRef<(version: string) => Promise<void>>(() => Promise.resolve());
  const startProcessingRef = useRef<(isContinuation?: boolean, overrideLowDisk?: boolean, forceRetry?: boolean) => Promise<boolean>>(() => Promise.resolve(false));

  const {
    notifications,
    unreadNotificationsCount,
    shakeBell,
    addNotification,
    upsertNotification,
    deleteNotification,
    markNotificationAsRead,
    markAllNotificationsAsRead,
    clearAllNotifications,
    removeNotificationByDedupeKey,
  } = useNotifications({
    onRetryFailedRevisionBlocks: useCallback((sessionDir: string, fileId?: string) => handleRetryFailedRevisionBlocksRef.current(sessionDir, fileId), []),
    onInstallUpdate: useCallback((version: string) => installUpdateRef.current(version), []),
    onDismissUpdate: dismissUpdate,
    updateAvailable,
    onOpenSettings: useCallback(() => setIsSettingsOpen(true), [setIsSettingsOpen]),
  });

  const [askNewKeyPrompt, setAskNewKeyPrompt] = useState(false);
  const [showConsole, setShowConsole] = useState(() => localStorage.getItem(STORAGE_KEYS.SHOW_CONSOLE) === 'true');
  const [autoContinue, setAutoContinue] = useState(() => localStorage.getItem(STORAGE_KEYS.AUTO_CONTINUE) !== 'false');

  const filesRef = useRef(files);
  const appStateRef = useRef(appState);
  const autoContinueRef = useRef(autoContinue);
  const editorControllerRef = useRef<EditorSaveController | null>(null);
  const isQuittingRef = useRef(false);

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      const isBusy = appStateRef.current === 'processing' || filesRef.current.some(f => f.isRetryingBlocks);
      if (isBusy && !isQuittingRef.current && !(window as unknown as { __jotQuitting?: boolean }).__jotQuitting) {
        e.preventDefault();
        e.returnValue = '';
        return '';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, []);

  const {
    updateInstallState,
    installUpdate,
    handleDownloadProgress,
  } = useUpdateInstaller({
    latestVersion,
    appendConsole,
    upsertNotification,
    removeNotificationByDedupeKey,
  });

  const {
    archiveSessions,
    setArchiveSessions,
    archiveTotal,
    setArchiveTotal,
    isArchiveLoaded,
    folders,
    setFolders,
    archiveSessionsRef,
    foldersRef,
    pendingArchiveReplacementsRef,
    normalizeSessionDir,
    refreshArchiveSessions,
    handleLoadAll,
    handleOpenFailed,
    handleFoldersChange,
    handleSessionRootMoved,
    executeRetryFromArchive,
    archiveFiltered,
    completedSessionFolderMap,
  } = useArchiveSync({
    files,
    dispatch,
    activePage,
    setActivePage,
    appState,
    apiReady,
    appendConsole,
    addNotification,
    handleRetryFailedRevisionBlocks: useCallback((sessionDir: string, fileId?: string) => handleRetryFailedRevisionBlocksRef.current(sessionDir, fileId), []),
  });

  const completedFileCount = files.filter(file => file.status === 'done').length;
  useEffect(() => {
    if (apiReady && completedFileCount > 0) {
      void refreshArchiveSessions();
    }
  }, [apiReady, completedFileCount, refreshArchiveSessions]);

  const onFilesAddedToBatchRef = useRef<(count: number) => void>(() => {});
  const onFileRemovedFromBatchRef = useRef<() => void>(() => {});

  const {
    duplicatePrompt,
    setDuplicatePrompt,
    isDragging,
    enqueueUniqueFiles,
    handleDuplicateAddAgain,
    handleBrowseClick,
    handleDragOver,
    handleDragLeave,
    handleDrop,
  } = useQueueIngest({
    filesRef,
    archiveSessionsRef,
    pendingArchiveReplacementsRef,
    setArchiveSessions,
    setArchiveTotal,
    dispatch,
    appState,
    appStateRef,
    apiReady,
    appendConsole,
    onFilesAddedToBatch: useCallback((count: number) => onFilesAddedToBatchRef.current(count), []),
  });

  const {
    confirmAction,
    setConfirmAction,
    confirmModalCopy,
    handleConfirmAction,
    requestQuitConfirmation,
  } = useConfirmModal({
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
    onFileRemovedFromBatch: useCallback(() => onFileRemovedFromBatchRef.current(), []),
  });

  const {
    handleRetryFailedRevisionBlocks,
    handleRevisionWarning,
  } = useRevisionRetry({
    filesRef,
    archiveSessionsRef,
    normalizeSessionDir,
    dispatch,
    setArchiveSessions,
    refreshArchiveSessions,
    addNotification,
    setConfirmAction,
  });

  const {
    batchTotal,
    batchCompleted,
    completionFlash,
    setCompletionFlash,
    startProcessing,
    onFileContinued,
    onBatchReset,
    onBatchFullyDone,
    onFilesAddedToBatch,
    onFileRemovedFromBatch,
  } = useQueueProcessing({
    filesRef,
    appStateRef,
    apiKey,
    hasProtectedKey,
    preferredModel,
    fallbackModels,
    dispatch,
    appendConsole,
    setConfirmAction,
    refreshArchiveSessions,
  });

  const { preview, openPreview, closePreview, relinkPreviewAudio, removePreviewAudio, handleAudioStateChange, handleScrollTopChange } = usePreview({ appendConsole, dispatch, setArchiveSessions, onOpenFailed: handleOpenFailed, onArchiveRefresh: refreshArchiveSessions });

  const {
    regeneratePrompt,
    setRegeneratePrompt,
    regenDirtyConfirm,
    handleRegenerateAnswer,
    handleRegenDirtyConfirm,
    handleRegenDirtyCancel,
  } = useRegenerateDialog({
    previewContent: preview.content,
    previewSessionDir: preview.sessionDir,
    closePreview,
    editorControllerRef,
  });

  useSystemNotificationTriggers({
    configRecoveredFrom,
    updateAvailable,
    addNotification,
    removeNotificationByDedupeKey,
  });

  const [hasOpenedPreview, setHasOpenedPreview] = useState(false);
  const shouldRenderPreview = preview.content !== null || hasOpenedPreview;

  useEffect(() => {
    if (preview.content !== null) {
      setHasOpenedPreview(true);
    }
  }, [preview.content]);

  useLayoutEffect(() => {
    installUpdateRef.current = installUpdate;
    handleRetryFailedRevisionBlocksRef.current = handleRetryFailedRevisionBlocks;
    startProcessingRef.current = startProcessing;
    onFilesAddedToBatchRef.current = onFilesAddedToBatch;
    onFileRemovedFromBatchRef.current = onFileRemovedFromBatch;
    filesRef.current = files;
    appStateRef.current = appState;
    autoContinueRef.current = autoContinue;
  }, [installUpdate, handleRetryFailedRevisionBlocks, startProcessing, onFilesAddedToBatch, onFileRemovedFromBatch, files, appState, autoContinue]);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEYS.AUTO_CONTINUE, String(autoContinue)); } catch (_) {}
  }, [autoContinue]);

  const hasApiKey = Boolean(apiKey.trim() || hasProtectedKey);
  const isApiKeyValid = hasProtectedKey || GEMINI_KEY_PATTERN.test(apiKey.trim());
  const isConsoleDisabled = !hasApiKey || !isApiKeyValid || !(files.length > 0 || appState === 'processing' || appState === 'canceling' || completionFlash);

  useEffect(() => {
    document.title = appState === 'processing' ? `⏳ ${APP_NAME}` : APP_NAME;
  }, [appState]);

  useEffect(() => {
    if (appState !== 'processing' && confirmAction?.type === 'stop-processing') {
      setConfirmAction(null);
    }
  }, [appState, confirmAction, setConfirmAction]);

  const requestRemoveFile = useCallback((id: string) => {
    const targetFile = filesRef.current.find(file => file.id === id);
    if (!targetFile) return;
    if (appStateRef.current !== 'idle' && targetFile.status !== 'done' && targetFile.status !== 'queued' && targetFile.status !== 'error') return;
    setConfirmAction({ type: 'remove-file', fileId: id, fileName: targetFile.name, isDone: targetFile.status === 'done' });
  }, [setConfirmAction]);

  const dndSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    if (appState !== 'idle' && appState !== 'processing' && appState !== 'canceling') return;

    const activeFile = files.find(f => f.id === active.id);
    if (!activeFile || activeFile.status === 'processing' || activeFile.status === 'done') return;

    const fromIndex = files.findIndex(f => f.id === active.id);
    let toIndex = files.findIndex(f => f.id === over.id);
    if (fromIndex < 0 || toIndex < 0) return;

    if (appState === 'processing' || appState === 'canceling') {
      const processingIndex = files.findIndex(f => f.status === 'processing');
      if (processingIndex >= 0 && toIndex <= processingIndex) {
        toIndex = processingIndex + 1;
      }
    }

    if (fromIndex === toIndex) return;
    dispatch({ type: 'queue/reorder', fromIndex, toIndex });
  }, [appState, files, dispatch]);

  const handleClearAll = useCallback(() => {
    setConfirmAction({ type: 'clear-all' });
  }, [setConfirmAction]);

  const openFile = useCallback(async (path: string) => {
    if (!window.pywebview?.api) return;
    const res = await window.pywebview.api.open_file(path);
    if (res && !res.ok) appendConsole(`❌ Impossibile aprire il file: ${res.error ?? path}`);
  }, [appendConsole]);

  useQueuePersistence(files, structuralVersion, dispatch, appendConsole);
  useBridgeCallbacks({
    dispatch,
    appendConsole,
    filesRef,
    appStateRef,
    enqueueUniqueFiles,
    setRegeneratePrompt,
    setAskNewKeyPrompt,
    autoContinueRef,
    startProcessingRef,
    onFileContinued,
    onBatchReset,
    onBatchFullyDone,
    clearCompletionFlash: () => setCompletionFlash(false),
    onRevisionWarning: handleRevisionWarning,
    addNotification,
    batchTotal,
    onDownloadProgress: handleDownloadProgress,
    onRequestQuitConfirmation: requestQuitConfirmation,
  });
  useBodyScrollLock(isSettingsOpen || regeneratePrompt !== null || preview.content !== null || askNewKeyPrompt || confirmAction !== null || duplicatePrompt !== null || regenDirtyConfirm !== null);

  const handleQueueRetry = useCallback((id: string) => {
    dispatch({ type: 'queue/retry_one', id });
    filesRef.current = filesRef.current.map(f =>
      f.id === id && (f.status === 'error' || f.status === 'paused')
        ? {
            ...f,
            status: 'queued',
            progress: 0,
            phase: 0,
            phaseText: undefined,
            errorText: undefined,
            errorDetail: undefined,
            forceRetry: f.status === 'paused',
            retryable: undefined,
            retryReason: undefined,
            recommendedRetryAt: undefined,
            resumeSession: undefined,
          }
        : f
    );
    void startProcessingRef.current();
  }, [dispatch]);

  const handleQueueResumeAll = useCallback(() => {
    dispatch({ type: 'queue/retry_failed' });
    filesRef.current = filesRef.current.map(f =>
      f.status === 'error' || f.status === 'paused'
        ? {
            ...f,
            status: 'queued',
            progress: 0,
            phase: 0,
            phaseText: undefined,
            errorText: undefined,
            errorDetail: undefined,
            forceRetry: f.status === 'paused',
            retryable: undefined,
            retryReason: undefined,
            recommendedRetryAt: undefined,
            resumeSession: undefined,
          }
        : f
    );
    void startProcessingRef.current();
  }, [dispatch]);

  const handleQueueStart = useCallback(() => {
    const hasFailed = filesRef.current.some(f => f.status === 'error' || f.status === 'paused');
    if (hasFailed) {
      dispatch({ type: 'queue/retry_failed' });
      filesRef.current = filesRef.current.map(f =>
        f.status === 'error' || f.status === 'paused'
          ? {
              ...f,
              status: 'queued',
              progress: 0,
              phase: 0,
              phaseText: undefined,
              errorText: undefined,
              errorDetail: undefined,
              forceRetry: f.status === 'paused',
              retryable: undefined,
              retryReason: undefined,
              recommendedRetryAt: undefined,
              resumeSession: undefined,
            }
          : f
      );
    }
    void startProcessingRef.current();
  }, [dispatch]);

  const handleQueueStop = useCallback(() => {
    setConfirmAction({ type: 'stop-processing' });
  }, [setConfirmAction]);

  const handleOpenSettings = useCallback(() => {
    setIsSettingsOpen(true);
  }, [setIsSettingsOpen]);

  const queuedIds = React.useMemo(() => new Set(files.filter(f => f.status !== 'done').map(f => f.id)), [files]);

  // ── Nuova lezione: start now, add to the running batch, or start later ──
  const handleStartLesson = useCallback((job: FileItem) => {
    if (filesRef.current.some(f => f.id === job.id && f.status !== 'done')) return;
    const queued: FileItem = { ...job, status: 'queued', progress: 0, phase: 0 };
    dispatch({ type: 'queue/add', files: [queued] });
    filesRef.current = [...filesRef.current, queued];
    setActivePage('queue');
    if (appStateRef.current === 'processing') {
      onFilesAddedToBatchRef.current(1);
      return;
    }
    if (appStateRef.current === 'idle') void startProcessingRef.current();
  }, [dispatch]);

  const [scheduledLesson, setScheduledLesson] = useState<(ScheduledLesson & { job: FileItem }) | null>(null);
  const handleScheduleLesson = useCallback((job: FileItem, at: number) => {
    setScheduledLesson({ at, name: job.title || job.name, job });
  }, []);
  const handleCancelSchedule = useCallback(() => setScheduledLesson(null), []);
  useEffect(() => {
    if (!scheduledLesson) return;
    const delay = Math.max(0, scheduledLesson.at - Date.now());
    const timer = window.setTimeout(() => {
      const { job } = scheduledLesson;
      setScheduledLesson(null);
      handleStartLesson(job);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [scheduledLesson, handleStartLesson]);

  // ── Daily quota: shown before starting and while processing ──
  const [quota, setQuota] = useState<QuotaSnapshot | null>(null);
  const refreshQuota = useCallback(async () => {
    const api = window.pywebview?.api;
    if (!api?.get_quota_snapshot) return;
    try {
      const res = await api.get_quota_snapshot(preferredModel, fallbackModels);
      if (res?.ok && res.result) setQuota(res.result);
    } catch (_) { /* quota is a hint, never blocking */ }
  }, [preferredModel, fallbackModels]);
  useEffect(() => {
    if (!apiReady) return;
    void refreshQuota();
    const timer = window.setInterval(() => void refreshQuota(), appState === 'processing' ? 20_000 : 120_000);
    return () => window.clearInterval(timer);
  }, [apiReady, appState, refreshQuota]);

  // ── Lessons stopped by the daily quota restart by themselves after the reset ──
  const hasQuotaStopped = files.some(f => (f.status === 'error' || f.status === 'paused') && isQuotaError(f.errorText));
  useEffect(() => {
    if (!hasQuotaStopped || !quota?.reset_at || appState !== 'idle') return;
    const resetAt = new Date(quota.reset_at).getTime();
    if (!Number.isFinite(resetAt)) return;
    // a few minutes after the reset, so Google has really refilled the quota
    const delay = Math.max(60_000, resetAt + 5 * 60_000 - Date.now());
    const timer = window.setTimeout(() => {
      appendConsole('Quota giornaliera ripristinata: riprendo le lezioni in sospeso.');
      handleQueueResumeAll();
    }, Math.min(delay, 2_147_000_000));
    return () => window.clearTimeout(timer);
  }, [hasQuotaStopped, quota?.reset_at, appState, appendConsole, handleQueueResumeAll]);

  const courses = React.useMemo(() => {
    const seen = new Map<string, string>();
    for (const session of archiveSessions) {
      const course = String(session.course || '').trim();
      if (course && !seen.has(course.toLowerCase())) seen.set(course.toLowerCase(), course);
    }
    for (const file of files) {
      const course = String(file.course || '').trim();
      if (course && !seen.has(course.toLowerCase())) seen.set(course.toLowerCase(), course);
    }
    return Array.from(seen.values()).sort((a, b) => a.localeCompare(b, 'it'));
  }, [archiveSessions, files]);
  const pendingCount = files.filter(f => f.status !== 'done').length;

  const handleRemoveDoneFile = useCallback((id: string) => {
    const f = filesRef.current.find(item => item.id === id);
    if (!f) return;
    if (appStateRef.current !== 'idle' && f.status !== 'done') return;
    setConfirmAction({ type: 'remove-file', fileId: id, fileName: f.name, isDone: true });
  }, [setConfirmAction]);

  return (
    <div className="app-shell h-screen overflow-hidden font-sans flex flex-col bg-[var(--bg-base)] text-[var(--text-secondary)]">
      <SplashScreen />
      <NavSidebar
        activePage={activePage}
        setActivePage={setActivePage}
        apiReady={apiReady}
        bridgeDelayed={bridgeDelayed}
        hasApiKey={hasApiKey}
        isApiKeyValid={isApiKeyValid}
        appState={appState}
        themeMode={themeMode}
        setThemeMode={setThemeMode}
        showConsole={showConsole}
        setShowConsole={setShowConsole}
        setIsSettingsOpen={setIsSettingsOpen}
        hasPendingUpdate={updateAvailable !== null}
        consoleDisabled={isConsoleDisabled}
        unreadNotificationsCount={unreadNotificationsCount}
        isNotificationsOpen={isNotificationsOpen}
        setIsNotificationsOpen={setIsNotificationsOpen}
        shakeBell={shakeBell}
        queueCount={pendingCount}
        quota={quota}
      />

      <div className="flex flex-col flex-1 min-w-0 min-h-0 overflow-hidden">
        <AnimatePresence mode="wait">
          {activePage === 'queue' ? (
            <QueuePage
              files={files}
              progress={{
                appState,
                currentPhase,
                currentModel,
                activeProgress,
                workDone,
                workTotals,
                batchCompleted,
                batchTotal,
                completionFlash,
              }}
              auth={{
                apiReady,
                bridgeDelayed,
                apiKey,
                setApiKey,
                hasProtectedKey,
                apiKeyInsecure,
                setApiKeyInsecure,
                apiKeyInsecureReason,
                setApiKeyInsecureReason,
                fallbackKeys,
                preferredModel,
                setPreferredModel,
                fallbackModels,
                setFallbackModels,
              }}
              ingest={{
                isDragging,
                handleDragOver,
                handleDragLeave,
                handleDrop,
                handleBrowseClick,
              }}
              console={{
                showConsole,
                setShowConsole,
                consoleLogs,
                isConsoleExpanded,
                setIsConsoleExpanded,
                appendConsole,
              }}
              actions={{
                requestRemoveFile,
                handleClearAll,
                handleQueueRetry,
                handleQueueResumeAll,
                openPreview,
                openFile,
                handleQueueStart,
                handleQueueStop,
                handleOpenSettings,
                handleRemoveDoneFile,
                setConfirmAction,
                handleRetryFailedRevisionBlocks,
              }}
              autoContinue={autoContinue}
              setAutoContinue={setAutoContinue}
              archiveSessions={archiveSessions}
              isArchiveLoaded={isArchiveLoaded}
              completedSessionFolderMap={completedSessionFolderMap}
              dndSensors={dndSensors}
              handleDragEnd={handleDragEnd}
              lesson={{
                courses,
                quota,
                scheduled: scheduledLesson ? { at: scheduledLesson.at, name: scheduledLesson.name } : null,
                queuedIds,
                onStart: handleStartLesson,
                onSchedule: handleScheduleLesson,
                onCancelSchedule: handleCancelSchedule,
              }}
            />
          ) : (
            <motion.main
              key="archive"
              className="flex-1 w-full flex flex-col overflow-y-auto app-scroll"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.15, ease: 'easeOut' }}
            >
              <div className="flex-1 px-5 sm:px-6 py-8 flex flex-col max-w-4xl w-full mx-auto">
                <React.Suspense fallback={null}>
                  <ArchivePage
                    sessions={archiveFiltered}
                    total={archiveTotal - (archiveSessions.length - archiveFiltered.length)}
                    folders={folders}
                    onFoldersChange={handleFoldersChange}
                    onPreview={openPreview}
                    onOpenFile={openFile}
                    onDeleteSession={(sessionDir, name) => setConfirmAction({ type: 'delete-archive-session', sessionDir, name })}
                    onDeleteMultipleSessions={(sessionsList) => setConfirmAction({ type: 'delete-multiple-archive-sessions', sessions: sessionsList })}
                    onRefresh={refreshArchiveSessions}
                    onLoadAll={handleLoadAll}
                    onRetryFailedRevisionBlocks={handleRetryFailedRevisionBlocks}
                    onNotification={addNotification}
                  />
                </React.Suspense>
              </div>
              <footer className="app-footer">
                <a href="#" onClick={e => { e.preventDefault(); window.pywebview?.api?.open_url?.(GITHUB_URL); }} className="footer-link">
                  <GithubIcon className="w-3.5 h-3.5" /> Progetto Open-Source — GitHub
                </a>
              </footer>
            </motion.main>
          )}
        </AnimatePresence>
      </div>

      <RegenerateModal
        prompt={regeneratePrompt}
        onAnswer={handleRegenerateAnswer}
        onDismiss={() => void handleRegenerateAnswer(null)}
      />
      <NewKeyModal
        isOpen={askNewKeyPrompt}
        onClose={() => setAskNewKeyPrompt(false)}
      />
      <DuplicateFileModal
        prompt={duplicatePrompt}
        onDismiss={() => setDuplicatePrompt(null)}
        onAddAgain={handleDuplicateAddAgain}
      />
      <ConfirmActionModal
        isOpen={confirmAction !== null && confirmModalCopy !== null}
        title={confirmModalCopy?.title ?? ''}
        description={confirmModalCopy?.description ?? ''}
        confirmLabel={confirmModalCopy?.confirmLabel ?? ''}
        cancelLabel={confirmModalCopy?.cancelLabel}
        onClose={() => setConfirmAction(null)}
        onConfirm={handleConfirmAction}
      />
      <ConfirmActionModal
        isOpen={regenDirtyConfirm !== null}
        title="Conferma rigenerazione"
        description={`La rigenerazione sovrascriverà il testo revisionato di "${regenDirtyConfirm?.filename ?? ''}". Vuoi procedere comunque?`}
        confirmLabel="Rigenera comunque"
        cancelLabel="Annulla"
        onClose={() => void handleRegenDirtyCancel()}
        onConfirm={() => void handleRegenDirtyConfirm()}
      />
      {shouldRenderSettings && (
        <React.Suspense fallback={null}>
          <SettingsModal
            isOpen={isSettingsOpen}
            onClose={() => {
              setIsSettingsOpen(false);
            }}
            appendConsole={appendConsole}
            onSettingsSaved={refreshSettings}
            auth={{
              apiKey,
              setApiKey,
              hasProtectedKey,
              fallbackKeys,
              setFallbackKeys,
              configuredFallbackKeyCount,
            }}
            models={{
              preferredModel,
              setPreferredModel,
              fallbackModels,
              setFallbackModels,
              availableModels,
            }}
            updater={{
              latestVersion,
              checkForUpdates,
              isCheckingUpdate,
              hasChecked,
              checkFailed,
              updateInstallState,
              onInstallUpdate: installUpdate,
            }}
            storage={{
              onSessionRootMoved: handleSessionRootMoved,
            }}
          />
        </React.Suspense>
      )}
      {shouldRenderPreview && (
        <React.Suspense fallback={null}>
          <EditorFullPage
            document={{
              content: preview.content,
              title: preview.title,
              htmlPath: preview.path,
              initScrollTop: preview.initScrollTop,
              initialSearchTerm: preview.initialSearchTerm,
            }}
            audio={{
              src: preview.audioSrc,
              relinkNeeded: preview.audioRelinkNeeded,
              onRelink: relinkPreviewAudio,
              onRemoveAudio: removePreviewAudio,
              init: preview.initAudio,
              onStateChange: handleAudioStateChange,
            }}
            theme={{
              mode: themeMode,
              setMode: setThemeMode,
            }}
            onClose={closePreview}
            onScrollTopChange={handleScrollTopChange}
            saveControllerRef={editorControllerRef}
          />
        </React.Suspense>
      )}
      <NotificationDropdown
        isOpen={isNotificationsOpen}
        onClose={() => setIsNotificationsOpen(false)}
        notifications={notifications}
        onMarkAsRead={markNotificationAsRead}
        onMarkAllAsRead={markAllNotificationsAsRead}
        onDelete={deleteNotification}
        onClearAll={clearAllNotifications}
        onNotificationClick={(notification) => {
          if (notification.category === 'update' || notification.action?.type === 'open_settings') {
            setIsNotificationsOpen(false);
            setIsSettingsOpen(true);
          }
        }}
        align="right"
        valign="top"
      />
    </div>
  );
}
