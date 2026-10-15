import { credentialStorageWarning } from '../credentialStorage';
import React, { useCallback, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { type DragEndEvent, type SensorDescriptor, type SensorOptions } from '@dnd-kit/core';
import { AlertTriangle, Loader2, Settings } from 'lucide-react';
import { GithubIcon } from './icons/GithubIcon';
import { GITHUB_URL } from '../branding';
import type { ArchiveFolder, ArchiveSession, QuotaSnapshot } from '../bridge';
import { type AppStatus, type FileItem, getDoneFiles, getPendingFiles } from '../appState';
import { GEMINI_KEY_PATTERN } from '../utils';
import { STORAGE_KEYS } from '../storageKeys';
import { ProcessingStatusBanner } from './ProcessingStatusBanner';
import { LessonComposer, type ScheduledLesson } from './lesson/LessonComposer';
import { QueueSection } from './QueueSection';
import { CompletedSection } from './CompletedSection';
import { ConsolePanel } from './ConsolePanel';
import type { ConfirmAction } from '../hooks/useConfirmModal';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

const SetupPage = React.lazy(() => import('./SetupPage').then(m => ({ default: m.SetupPage })));

export type UiMode = 'loading' | 'setup' | 'ready-empty' | 'ready-with-files' | 'processing' | 'canceling';

export interface QueueProgressProps {
  appState: AppStatus;
  currentPhase: string;
  currentModel: string;
  activeProgress: number;
  workDone: { chunks: number; macro: number };
  workTotals: { chunks: number; macro: number };
  batchCompleted: number;
  batchTotal: number;
  completionFlash: boolean;
}

export interface QueueAuthProps {
  apiReady: boolean;
  bridgeDelayed: boolean;
  apiKey: string;
  setApiKey: (key: string) => void;
  hasProtectedKey: boolean;
  apiKeyInsecure: boolean;
  setApiKeyInsecure: (val: boolean) => void;
  apiKeyInsecureReason: string;
  setApiKeyInsecureReason: (val: string) => void;
  fallbackKeys: string[];
  preferredModel: string;
  setPreferredModel?: (model: string) => void;
  fallbackModels: string[];
  setFallbackModels?: (models: string[]) => void;
}

export interface QueueIngestProps {
  isDragging: boolean;
  handleDragOver: (e: React.DragEvent) => void;
  handleDragLeave: (e: React.DragEvent) => void;
  handleDrop: (e: React.DragEvent) => void;
  handleBrowseClick: () => void;
}

export interface QueueConsoleProps {
  showConsole: boolean;
  setShowConsole: (val: boolean) => void;
  consoleLogs: string[];
  isConsoleExpanded: boolean;
  setIsConsoleExpanded: React.Dispatch<React.SetStateAction<boolean>>;
  appendConsole: (msg: string) => void;
}

export interface QueueActionProps {
  requestRemoveFile: (id: string) => void;
  handleClearAll: () => void;
  handleQueueRetry: (id: string) => void;
  handleQueueResumeAll?: () => void;
  openPreview: (htmlPath: string, title?: string, inputPath?: string, placeholder?: string, sessionDir?: string) => void;
  openFile: (path: string) => void;
  handleQueueStart: () => void;
  handleQueueStop: () => void;
  handleOpenSettings: () => void;
  handleRemoveDoneFile: (id: string) => void;
  setConfirmAction: (action: ConfirmAction | null) => void;
  handleRetryFailedRevisionBlocks: (sessionDir: string, fileId?: string) => Promise<void>;
}

export interface QueueLessonProps {
  courses: string[];
  quota: QuotaSnapshot | null;
  scheduled: ScheduledLesson | null;
  queuedIds: ReadonlySet<string>;
  onStart: (job: FileItem) => void;
  onSchedule: (job: FileItem, at: number) => void;
  onCancelSchedule: () => void;
}

export interface QueuePageProps {
  files: FileItem[];
  progress: QueueProgressProps;
  auth: QueueAuthProps;
  ingest: QueueIngestProps;
  console: QueueConsoleProps;
  actions: QueueActionProps;
  autoContinue: boolean;
  setAutoContinue: React.Dispatch<React.SetStateAction<boolean>>;
  archiveSessions: ArchiveSession[];
  isArchiveLoaded: boolean;
  completedSessionFolderMap: Map<string, ArchiveFolder>;
  dndSensors: SensorDescriptor<SensorOptions>[];
  handleDragEnd: (event: DragEndEvent) => void;
  lesson?: QueueLessonProps;
}

const EMPTY_IDS: ReadonlySet<string> = new Set();

export function QueuePage({
  files,
  progress,
  auth,
  ingest,
  console: consoleState,
  actions,
  autoContinue,
  setAutoContinue,
  archiveSessions: _archiveSessions,
  isArchiveLoaded: _isArchiveLoaded,
  completedSessionFolderMap,
  dndSensors,
  handleDragEnd,
  lesson,
}: QueuePageProps) {
  const [showNextComposer, setShowNextComposer] = React.useState(false);
  const {
    appState,
    currentPhase,
    currentModel,
    activeProgress,
    workDone,
    workTotals,
    batchCompleted,
    batchTotal,
    completionFlash,
  } = progress;

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
    fallbackKeys,
    preferredModel,
    setPreferredModel,
    fallbackModels,
    setFallbackModels,
  } = auth;

  const {
    isDragging,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleBrowseClick,
  } = ingest;

  const {
    showConsole,
    setShowConsole,
    consoleLogs,
    isConsoleExpanded,
    setIsConsoleExpanded,
    appendConsole,
  } = consoleState;

  const {
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
  } = actions;

  const pendingFiles = useMemo(() => getPendingFiles(files), [files]);
  const doneFiles = useMemo(() => getDoneFiles(files), [files]);
  const { queuedCount, failedCount } = useMemo(() => {
    let queued = 0;
    let failed = 0;
    for (const f of files) {
      if (f.status === 'queued') queued++;
      else if (f.status === 'error' || f.status === 'paused') failed++;
    }
    return { queuedCount: queued, failedCount: failed };
  }, [files]);

  const hasApiKey = Boolean(apiKey.trim() || hasProtectedKey);
  const isApiKeyValid = hasProtectedKey || GEMINI_KEY_PATTERN.test(apiKey.trim());
  const handleNetworkChange = useCallback((online: boolean) => {
    if (online) {
      appendConsole('Connessione a Internet ripristinata.');
    } else {
      appendConsole('⚠️ Connessione a Internet interrotta.');
    }
  }, [appendConsole]);
  const isOnline = useOnlineStatus(handleNetworkChange);
  const canStart = (queuedCount > 0 || failedCount > 0) && hasApiKey && isApiKeyValid && isOnline;
  const canResumeAll = failedCount > 0 && hasApiKey && isApiKeyValid && isOnline;

  const uiMode: UiMode =
    !apiReady ? 'loading' :
    appState === 'canceling' ? 'canceling' :
    appState === 'processing' ? 'processing' :
    (!hasApiKey || !isApiKeyValid) ? 'setup' :
    (queuedCount > 0 || failedCount > 0) ? 'ready-with-files' : 'ready-empty';

  const lastConsoleMessage = consoleLogs.length > 0 ? consoleLogs[consoleLogs.length - 1] : 'Pronto per iniziare.';
  const showProcessingBanner = appState === 'processing' || appState === 'canceling' || completionFlash;
  const apiKeyInsecureReasonLabel = apiKeyInsecureReason.trim() || 'Credenziali presenti in chiaro nel file di configurazione.';
  const bannerFile = useMemo(
    () => files.find(f => f.status === 'processing' || f.isRetryingBlocks) ?? (completionFlash ? doneFiles[0] : undefined),
    [files, completionFlash, doneFiles],
  );
  const isConsoleDisabled = !hasApiKey || !isApiKeyValid || !(pendingFiles.length > 0 || doneFiles.length > 0 || showProcessingBanner);

  useEffect(() => {
    if (isConsoleDisabled && showConsole) {
      setShowConsole(false);
      localStorage.setItem(STORAGE_KEYS.SHOW_CONSOLE, 'false');
    }
  }, [isConsoleDisabled, showConsole, setShowConsole]);

  return (
    <motion.main
      key="queue"
      className="flex-1 w-full flex flex-col overflow-y-auto app-scroll"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15, ease: 'easeOut' }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDragging && (
        <div className="drop-overlay" aria-hidden="true">
          <span>Rilascia gli audio per metterli in coda</span>
        </div>
      )}
      <div className="my-auto px-5 sm:px-6 py-8 flex flex-col gap-6 max-w-4xl w-full mx-auto">
        {apiKeyInsecure && (
          <motion.div
            key="api-key-insecure-banner"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="w-full alert-card is-warning px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
          >
            <div className="flex items-start gap-3 text-sm leading-relaxed text-[var(--warning-text)]">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>
                {apiKeyInsecureReasonLabel}
              </span>
            </div>
            <button
              type="button"
              onClick={handleOpenSettings}
              className="shrink-0 premium-button-secondary compact-button is-warning flex items-center justify-center gap-2"
            >
              <Settings className="w-4 h-4" />
              Gestisci credenziali
            </button>
          </motion.div>
        )}
        {uiMode === 'loading' ? (
          <motion.div
            key="connecting-loader"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
            className="premium-panel py-12 px-6 flex flex-col items-center justify-center gap-4 text-center max-w-md mx-auto w-full"
          >
            <Loader2 className="w-8 h-8 animate-spin" style={{ color: 'var(--accent-text)' }} />
            <h3 className="text-lg font-bold" style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-display)' }}>
              Connessione in corso...
            </h3>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Inizializzazione dell'applicazione e caricamento delle impostazioni.
            </p>
            {bridgeDelayed && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="alert-card is-error p-3 rounded-lg text-xs leading-relaxed max-w-sm mt-2 text-[var(--error-text)]"
              >
                Il motore dell'applicazione sta impiegando più tempo del previsto.
                Verifica se l'app è bloccata o prova a riavviare.
              </motion.div>
            )}
          </motion.div>
        ) : uiMode === 'setup' ? (
          <React.Suspense fallback={null}>
            <SetupPage
              hasProtectedKey={hasProtectedKey}
              onSaved={(key, model, storage, legacyPlaintext, chosenFallbacks) => {
                const warning = credentialStorageWarning(storage, legacyPlaintext);
                setApiKeyInsecure(Boolean(warning));
                setApiKeyInsecureReason(warning);
                setApiKey(key);
                if (model && setPreferredModel) {
                  setPreferredModel(model);
                }
                if (chosenFallbacks && setFallbackModels) {
                  setFallbackModels(chosenFallbacks);
                }
              }}
              preferredModel={preferredModel}
              fallbackKeys={fallbackKeys}
              fallbackModels={fallbackModels}
            />
          </React.Suspense>
        ) : (
          <>
            <AnimatePresence mode="wait">
              {showProcessingBanner ? (
                <motion.div
                  key="processing-banner"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.15, ease: 'easeOut' }}
                >
                  <ProcessingStatusBanner
                    appState={appState}
                    currentPhase={completionFlash ? '__completed__' : currentPhase}
                    currentModel={currentModel}
                    activeProgress={completionFlash ? 100 : activeProgress}
                    workTotals={workTotals}
                    workDone={workDone}
                    currentFileIndex={batchCompleted}
                    currentBatchTotal={batchTotal}
                    currentFileName={bannerFile?.title || bannerFile?.name}
                    startedAt={bannerFile?.startedAt}
                    mode={bannerFile?.kind === 'notes' ? 'notes' : 'audio'}
                    sources={{
                      slides: Boolean(bannerFile?.lesson?.slidesPath),
                      book: Boolean(bannerFile?.lesson?.bookPath || bannerFile?.notes?.bookPath),
                    }}
                    quota={lesson?.quota ? { used: lesson.quota.used, limit: lesson.quota.limit } : null}
                  />
                </motion.div>
              ) : (
                <motion.div
                  key="lesson-composer"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.15, ease: 'easeOut' }}
                >
                  <LessonComposer
                    apiReady={apiReady}
                    appState={appState}
                    queuedIds={lesson?.queuedIds ?? EMPTY_IDS}
                    courses={lesson?.courses ?? []}
                    quota={lesson?.quota ?? null}
                    scheduled={lesson?.scheduled ?? null}
                    onStart={job => lesson?.onStart(job)}
                    onSchedule={(job, at) => lesson?.onSchedule(job, at)}
                    onCancelSchedule={() => lesson?.onCancelSchedule()}
                    appendConsole={appendConsole}
                  />
                </motion.div>
              )}
            </AnimatePresence>
            {showProcessingBanner && appState === 'processing' && (
              showNextComposer ? (
                <LessonComposer
                  apiReady={apiReady}
                  appState={appState}
                  queuedIds={lesson?.queuedIds ?? EMPTY_IDS}
                  courses={lesson?.courses ?? []}
                  quota={lesson?.quota ?? null}
                  scheduled={null}
                  onStart={job => { lesson?.onStart(job); setShowNextComposer(false); }}
                  onSchedule={(job, at) => lesson?.onSchedule(job, at)}
                  onCancelSchedule={() => lesson?.onCancelSchedule()}
                  appendConsole={appendConsole}
                />
              ) : (
                <button type="button" className="lesson-link is-centered" onClick={() => setShowNextComposer(true)}>
                  + Prepara la prossima lezione
                </button>
              )
            )}
          </>
        )}

        {uiMode !== 'setup' && uiMode !== 'loading' && (
          <>
            <QueueSection
              pendingFiles={pendingFiles}
              progress={progress}
              auth={auth}
              status={{
                queuedCount,
                failedCount,
                canStart,
                canResumeAll,
                hasApiKey,
                isApiKeyValid,
                isOnline,
                autoContinue,
                setAutoContinue,
              }}
              dnd={{
                sensors: dndSensors,
                onDragEnd: handleDragEnd,
              }}
              actions={{
                onRemove: requestRemoveFile,
                onClearAll: handleClearAll,
                onRetry: handleQueueRetry,
                onResumeAll: handleQueueResumeAll,
                onPreview: openPreview,
                onOpenFile: openFile,
                onStart: handleQueueStart,
                onStop: handleQueueStop,
                onOpenSettings: handleOpenSettings,
                onAddFiles: handleBrowseClick,
              }}
            />

            <CompletedSection
              doneFiles={doneFiles}
              appState={appState}
              onRemove={handleRemoveDoneFile}
              onPreview={openPreview}
              onOpenFile={openFile}
              onClearAll={() => setConfirmAction({ type: 'clear-completed', count: doneFiles.length })}
              onRetryFailedRevisionBlocks={handleRetryFailedRevisionBlocks}
              sessionFolderMap={completedSessionFolderMap}
            />
          </>
        )}

        {showConsole && uiMode !== 'setup' && uiMode !== 'loading' && (
          <ConsolePanel
            consoleLogs={consoleLogs}
            lastConsoleMessage={lastConsoleMessage}
            appState={appState}
            isConsoleExpanded={isConsoleExpanded}
            setIsConsoleExpanded={setIsConsoleExpanded}
          />
        )}
      </div>
      <footer className="app-footer">
        <a href="#" onClick={e => { e.preventDefault(); window.pywebview?.api?.open_url?.(GITHUB_URL); }} className="footer-link">
          <GithubIcon className="w-3.5 h-3.5" /> Progetto Open-Source — GitHub
        </a>
      </footer>
    </motion.main>
  );
}
