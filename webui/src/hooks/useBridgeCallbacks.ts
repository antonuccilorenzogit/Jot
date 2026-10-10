import { type Dispatch, useEffect, useLayoutEffect, useRef } from 'react';
import type React from 'react';
import { createBridge, type JotBridge, type UpdateDownloadProgressPayload } from '../bridge';
import type { AppStatus, FileDescriptor, FileDonePayload, FileItem, ProcessDonePayload, ProcessingAction } from '../appState';
import { errorLabel, isPausedError, shortModelName } from '../utils';

export function useBridgeCallbacks(options: {
  dispatch: Dispatch<ProcessingAction>;
  appendConsole: (msg: string) => void;
  filesRef: React.RefObject<FileItem[]>;
  appStateRef: React.RefObject<AppStatus>;
  enqueueUniqueFiles: (files: FileItem[]) => void;
  setRegeneratePrompt: (data: { filename: string; mode?: 'completed' | 'resume'; sessionDir?: string } | null) => void;
  setAskNewKeyPrompt: (open: boolean) => void;
  autoContinueRef: React.RefObject<boolean>;
  startProcessingRef: React.RefObject<(isContinuation?: boolean, overrideLowDisk?: boolean, forceRetry?: boolean) => Promise<boolean>>;
  onFileContinued: () => void;
  onBatchReset: () => void;
  onBatchFullyDone: (data: ProcessDonePayload) => void;
  clearCompletionFlash: () => void;
  onRevisionWarning?: (data: FileDonePayload) => void;
  onDownloadProgress?: (data: UpdateDownloadProgressPayload) => void;
  batchTotal?: number;
  addNotification?: (
    title: string,
    message: string,
    type: 'info' | 'warning' | 'error' | 'success',
    category: 'processing' | 'update' | 'system',
    opts?: {
      persistent?: boolean;
      dedupeKey?: string;
      actionType?: 'retry_failed_revision_blocks' | 'install_update' | 'open_github';
      actionData?: unknown;
    }
  ) => void;
  onRequestQuitConfirmation?: () => void;
}) {
  const {
    dispatch,
    appendConsole,
    filesRef,
    appStateRef,
    enqueueUniqueFiles,
    setRegeneratePrompt,
    setAskNewKeyPrompt,
    autoContinueRef,
    startProcessingRef,
    addNotification,
    batchTotal = 0,
  } = options;

  const dispatchRef = useRef(dispatch);
  const appendConsoleRef = useRef(appendConsole);
  const enqueueUniqueFilesRef = useRef(enqueueUniqueFiles);
  const setRegeneratePromptRef = useRef(setRegeneratePrompt);
  const setAskNewKeyPromptRef = useRef(setAskNewKeyPrompt);
  const onFileContinuedRef = useRef(options.onFileContinued);
  const onBatchResetRef = useRef(options.onBatchReset);
  const onBatchFullyDoneRef = useRef(options.onBatchFullyDone);
  const clearCompletionFlashRef = useRef(options.clearCompletionFlash);
  const onRevisionWarningRef = useRef(options.onRevisionWarning);
  const onDownloadProgressRef = useRef(options.onDownloadProgress);
  const addNotificationRef = useRef(addNotification);
  const batchTotalRef = useRef(batchTotal);
  const onRequestQuitConfirmationRef = useRef(options.onRequestQuitConfirmation);

  useLayoutEffect(() => {
    dispatchRef.current = dispatch;
    appendConsoleRef.current = appendConsole;
    enqueueUniqueFilesRef.current = enqueueUniqueFiles;
    setRegeneratePromptRef.current = setRegeneratePrompt;
    setAskNewKeyPromptRef.current = setAskNewKeyPrompt;
    onFileContinuedRef.current = options.onFileContinued;
    onBatchResetRef.current = options.onBatchReset;
    onBatchFullyDoneRef.current = options.onBatchFullyDone;
    clearCompletionFlashRef.current = options.clearCompletionFlash;
    onRevisionWarningRef.current = options.onRevisionWarning;
    onDownloadProgressRef.current = options.onDownloadProgress;
    addNotificationRef.current = options.addNotification;
    batchTotalRef.current = options.batchTotal ?? 0;
    onRequestQuitConfirmationRef.current = options.onRequestQuitConfirmation;
  });

  useEffect(() => {
    window.jotBridge = createBridge({
      dispatch: (...args) => dispatchRef.current(...args),
      appendConsole: msg => appendConsoleRef.current(msg),
      onRequestQuitConfirmation: () => { onRequestQuitConfirmationRef.current?.(); },
      onRegenerate: data => {
        setRegeneratePromptRef.current(data);
        if (!document.hasFocus()) {
          void window.pywebview?.api?.flash_window?.();
          if (localStorage.getItem('notifications_enabled') !== 'false' && window.pywebview?.api?.show_notification) {
            const isCompleted = data.mode === 'completed';
            const title = `⚠️ Conferma richiesta — ${data.filename}`;
            const message = isCompleted
              ? `Il file "${data.filename}" risulta già completato. Scegli se usare la versione pronta o rigenerare da zero.`
              : `Ci sono progressi salvati per "${data.filename}". Scegli se riprendere o ricominciare da capo.`;
            void window.pywebview.api.show_notification(title, message);
          }
        }
      },
      onFilesDropped: (droppedFiles: FileDescriptor[]) => {
        if (appStateRef.current === 'canceling') return;
        const filesToAdd = droppedFiles.map(f => ({
          id: crypto.randomUUID(),
          name: f.name,
          size: f.size,
          duration: f.duration || 0,
          path: f.path,
          status: 'queued' as const,
          progress: 0,
          phase: 0,
        }));
        enqueueUniqueFilesRef.current(filesToAdd);
      },
      onBatchStart: () => { clearCompletionFlashRef.current(); },
      onDownloadProgress: data => { onDownloadProgressRef.current?.(data); },
      onAskNewKey: () => {
        setAskNewKeyPromptRef.current(true);
        if (addNotificationRef.current) {
          addNotificationRef.current(
            'Chiavi esaurite',
            'Limite API raggiunto. Le tue chiavi Gemini hanno esaurito i crediti gratuiti o la capacità temporanea. Aggiungi una chiave nelle impostazioni per continuare.',
            'warning',
            'system'
          );
        }
        if (!document.hasFocus()) {
          void window.pywebview?.api?.flash_window?.();
          if (localStorage.getItem('notifications_enabled') !== 'false' && window.pywebview?.api?.show_notification) {
            void window.pywebview.api.show_notification(
              '⚠️ Chiavi esaurite — jot',
              'Limite API raggiunto. Le tue chiavi Gemini hanno esaurito i crediti gratuiti o la capacità temporanea. Aggiungi una chiave nelle impostazioni per continuare.',
            );
          }
        }
      },
      onDismissNewKey: () => {
        setAskNewKeyPromptRef.current(false);
      },
      onBatchDone: data => {
        setRegeneratePromptRef.current(null);
        if (!data.cancelled && !data.quota_exhausted && !data.paused && autoContinueRef.current) {
          const hasQueued = filesRef.current?.some(f => f.status === 'queued');
          if (hasQueued) {
            setTimeout(() => {
              void startProcessingRef.current(true).then(started => {
                if (started) {
                  onFileContinuedRef.current();
                  return;
                }
                onBatchResetRef.current();
              });
            }, 50);
            return;
          }
        }
        onBatchFullyDoneRef.current(data);
      },
      onFileDone: data => {
        onRevisionWarningRef.current?.(data);
        const currentFile = filesRef.current?.find(file => file.id === data.id);
        const isWarning = data.completion_status === 'completed_with_warnings' || (Array.isArray(data.revision_failed_blocks) && data.revision_failed_blocks.length > 0);

        if (addNotificationRef.current && currentFile) {
          if (!isWarning) {
            const model = data.effective_model || currentFile.effectiveModel;
            const modelPart = model ? ` con ${shortModelName(model)}` : '';
            const elapsed = currentFile.startedAt ? Math.round((Date.now() - currentFile.startedAt) / 60000) : null;
            const elapsedPart = elapsed !== null && elapsed > 0 ? ` · ${elapsed} min` : '';
            addNotificationRef.current(
              'Sbobina pronta',
              `"${currentFile.name}" completata con successo${modelPart}${elapsedPart}.`,
              'success',
              'processing'
            );
          }
          // Note: revision warnings are already added via onRevisionWarning -> handleRevisionWarning inside App.tsx
        }

        if (!document.hasFocus() && (batchTotalRef.current ?? 0) <= 1) {
          void window.pywebview?.api?.flash_window?.();
          if (localStorage.getItem('notifications_enabled') !== 'false' && currentFile && window.pywebview?.api?.show_notification) {
            if (isWarning) {
              void window.pywebview.api.show_notification(
                `⚠️ Sbobina pronta con avvisi — ${currentFile.name}`,
                'Completata con alcune parti non revisionate. Apri l\'app per rivederle.',
              );
            } else {
              const model = data.effective_model || currentFile.effectiveModel;
              const modelPart = model ? ` con ${shortModelName(model)}` : '';
              const elapsed = currentFile.startedAt ? Math.round((Date.now() - currentFile.startedAt) / 60000) : null;
              const elapsedPart = elapsed !== null && elapsed > 0 ? ` · ${elapsed} min` : '';
              void window.pywebview.api.show_notification(
                `✅ Sbobina pronta — ${currentFile.name}`,
                `Elaborata con successo${modelPart}${elapsedPart}. Disponibile nell'applicazione.`,
              );
            }
          }
        }
      },
      onRetryStateChanged: data => {
        if (data.state === 'cooling_down') {
          const sec = Math.round(data.seconds_remaining ?? 0);
          appendConsoleRef.current(`⏳ Attesa cooldown (${data.attempt ?? 1}/${data.max_attempts ?? 4}): riprovo tra ${sec}s...`);
        } else if (data.state === 'probing') {
          appendConsoleRef.current(`🔍 Esecuzione sonda (${data.attempt ?? 1}/${data.max_attempts ?? 4}) con ${data.model ?? 'modello'}...`);
        } else if (data.state === 'paused') {
          appendConsoleRef.current(`⏸️ Batch sospeso: capacità Gemini non disponibile dopo ${data.max_attempts ?? 4} tentativi. Progressi salvati.`);
        }
      },
      onFileFailed: data => {
        const currentFile = filesRef.current?.find(file => file.id === data.id);
        const isPaused = data.retry_reason === 'circuit_breaker_paused' || Boolean(data.retryable) || isPausedError(data.error, data.error_detail);
        const isGoogleServerOverload = !isPaused && (data.error?.includes('indisponibile') || data.error?.includes('unavailable') || data.error === 'phase1_all_models_unavailable');
        const friendlyError = data.retry_reason === 'circuit_breaker_paused'
          ? "Capacità Google Gemini temporaneamente esaurita. L'elaborazione è stata messa in pausa per proteggere il batch. Puoi cliccare 'Riprendi' per forzare un nuovo tentativo."
          : errorLabel(data.error, data.error_detail);

        if (addNotificationRef.current && currentFile) {
          if (isGoogleServerOverload) {
            addNotificationRef.current(
              'Server occupati',
              `I server di Google sono sovraccarichi. L'elaborazione per "${currentFile.name}" è stata interrotta.`,
              'warning',
              'processing'
            );
          } else if (isPaused) {
            addNotificationRef.current(
              'Elaborazione in pausa',
              `Per "${currentFile.name}": ${friendlyError}`,
              'warning',
              'processing'
            );
          } else {
            addNotificationRef.current(
              'Errore elaborazione',
              `Errore per "${currentFile.name}": ${friendlyError}`,
              'error',
              'processing'
            );
          }
        }

        if (!document.hasFocus()) {
          void window.pywebview?.api?.flash_window?.();
          if (localStorage.getItem('notifications_enabled') !== 'false' && currentFile && window.pywebview?.api?.show_notification) {
            if (isGoogleServerOverload) {
              void window.pywebview.api.show_notification(
                `⚠️ Server occupati — ${currentFile.name}`,
                "I server di Google Gemini sono temporaneamente sovraccarichi. L'app proverà a riprendere o puoi cliccare su 'Riprova' tra qualche minuto.",
              );
            } else if (isPaused) {
              void window.pywebview.api.show_notification(
                `⏸️ Elaborazione in pausa — ${currentFile.name}`,
                friendlyError,
              );
            } else {
              void window.pywebview.api.show_notification(
                `❌ Errore elaborazione — ${currentFile.name}`,
                friendlyError,
              );
            }
          }
        }
      },
    });
    return () => {
      window.jotBridge = null as JotBridge;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
