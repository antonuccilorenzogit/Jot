import { reportClientError } from '../../diagnostics';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Settings, HardDrive, SlidersHorizontal, Loader2, X, FlaskConical } from 'lucide-react';
import type { ApiUsageResult, CredentialStorage, ModelOption, ValidationResult } from '../../bridge';
import { ConfirmActionModal } from './ConfirmActionModal';
import { ApiKeySection, type DeleteKeyTarget } from './settings/ApiKeySection';
import { ModelSection } from './settings/ModelSection';
import { NotificationSection } from './settings/NotificationSection';
import { StorageSection } from './settings/StorageSection';
import { DiagnosticsSection, type DisplayCheck } from './settings/DiagnosticsSection';
import { ActivitySection } from './settings/ActivitySection';
import { ApiStatusSection } from './settings/ApiStatusSection';
import { UpdaterSection, type SettingsUpdateInstallState } from './settings/UpdaterSection';

import { useSettingsStorage, SESSION_CLEANUP_DAYS } from '../../hooks/useSettingsStorage';
import { formatSize } from '../../utils';
import { credentialStorageWarning } from '../../credentialStorage';
import { getHostCapabilities } from '../../browserHost';
import { APP_VERSION } from '../../branding';
import { STORAGE_KEYS } from '../../storageKeys';

export type { SettingsUpdateInstallState };

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}


export interface SettingsAuthProps {
  apiKey: string;
  setApiKey: (key: string) => void;
  hasProtectedKey: boolean;
  fallbackKeys: string[];
  setFallbackKeys: React.Dispatch<React.SetStateAction<string[]>>;
  configuredFallbackKeyCount?: number;
}

export interface SettingsModelsProps {
  preferredModel: string;
  setPreferredModel: (model: string) => void;
  fallbackModels: string[];
  setFallbackModels: React.Dispatch<React.SetStateAction<string[]>>;
  availableModels: ModelOption[];
}

export interface SettingsUpdaterProps {
  latestVersion: string | null;
  checkForUpdates: (force?: boolean) => void;
  isCheckingUpdate: boolean;
  hasChecked: boolean;
  checkFailed: boolean;
  updateInstallState?: SettingsUpdateInstallState;
  onInstallUpdate?: (version: string) => Promise<void>;
}

export interface SettingsStorageProps {
  onSessionRootMoved?: (payload?: { oldRoot?: string; newRoot?: string }) => void;
}

export interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  appendConsole: (msg: string) => void;
  onSettingsSaved?: () => Promise<unknown> | unknown;
  auth: SettingsAuthProps;
  models: SettingsModelsProps;
  updater: SettingsUpdaterProps;
  storage?: SettingsStorageProps;
}

type TabType = 'general' | 'storage' | 'diagnostics';

interface SettingsSnapshot {
  apiKey: string;
  fallbackKeys: string[];
  preferredModel: string;
  fallbackModels: string[];
  notificationsEnabled: boolean;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  appendConsole,
  onSettingsSaved,
  auth,
  models,
  updater,
  storage,
}) => {
  const {
    apiKey,
    setApiKey,
    hasProtectedKey,
    fallbackKeys,
    setFallbackKeys,
    configuredFallbackKeyCount,
  } = auth;
  const {
    preferredModel,
    setPreferredModel,
    fallbackModels,
    setFallbackModels,
    availableModels,
  } = models;
  const { latestVersion, checkForUpdates, isCheckingUpdate, hasChecked, checkFailed, updateInstallState, onInstallUpdate } = updater;
  const onSessionRootMoved = storage?.onSessionRootMoved;
  const hostCapabilities = getHostCapabilities();
  const [activeTab, setActiveTab] = useState<TabType>('general');
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [notificationsEnabled, setNotificationsEnabled] = useState(
    () => localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED) !== 'false',
  );
  const [credentialStorage, setCredentialStorage] = useState<CredentialStorage | undefined>();
  const [apiKeyInsecure, setApiKeyInsecure] = useState(false);
  const [apiKeyInsecureReason, setApiKeyInsecureReason] = useState<string | null>(null);

  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [isValidatingEnvironment, setIsValidatingEnvironment] = useState(false);
  const [apiUsage, setApiUsage] = useState<ApiUsageResult | null>(null);
  const [isLoadingUsage, setIsLoadingUsage] = useState(false);
  const [clearProtectedPrimary, setClearProtectedPrimary] = useState(false);
  const [keyDeleteTarget, setKeyDeleteTarget] = useState<DeleteKeyTarget | null>(null);

  const isSavingRef = useRef(false);
  const isMountedRef = useRef(true);
  const settingsSnapshotRef = useRef<SettingsSnapshot | null>(null);
  const wasOpenRef = useRef(false);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0;
  }, [activeTab, isOpen]);

  const {
    sessionInfo,
    isLoadingSessionInfo,
    fetchSessionStorageInfo,
    isMoveInProgress,
    moveProgress,
    moveError,
    pendingMovePath,
    showMoveConfirm,
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
  } = useSettingsStorage({
    isOpen,
    activeTab,
    appendConsole,
    onSessionRootMoved,
  });


  const prevSettingsKeyRef = useRef<string>('');
  useEffect(() => {
    const key = `${apiKey}|${preferredModel}|${fallbackModels.join(',')}`;
    if (prevSettingsKeyRef.current && prevSettingsKeyRef.current !== key) {
      setValidationResult(null);
    }
    prevSettingsKeyRef.current = key;
  }, [apiKey, preferredModel, fallbackModels]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      settingsSnapshotRef.current = {
        apiKey,
        fallbackKeys: [...fallbackKeys],
        preferredModel,
        fallbackModels: [...fallbackModels],
        notificationsEnabled: localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED) !== 'false',
      };
    } else if (!isOpen) {
      settingsSnapshotRef.current = null;
    }
    wasOpenRef.current = isOpen;
  }, [apiKey, fallbackKeys, fallbackModels, isOpen, preferredModel]);

  const snapshot = settingsSnapshotRef.current;
  const hasPendingChanges = Boolean(snapshot && (
    apiKey !== snapshot.apiKey ||
    preferredModel !== snapshot.preferredModel ||
    JSON.stringify(fallbackKeys) !== JSON.stringify(snapshot.fallbackKeys) ||
    JSON.stringify(fallbackModels) !== JSON.stringify(snapshot.fallbackModels) ||
    notificationsEnabled !== snapshot.notificationsEnabled ||
    clearProtectedPrimary
  ));
  const showCloseOnly = activeTab === 'diagnostics' && !hasPendingChanges;


  const usageRequestInFlightRef = useRef(false);
  const usageRequestIdRef = useRef(0);
  const fetchApiUsage = useCallback(async (forceRefresh = false, background = false) => {
    if (!window.pywebview?.api?.get_api_usage) return;
    if (background && usageRequestInFlightRef.current) return;
    const requestId = ++usageRequestIdRef.current;
    usageRequestInFlightRef.current = true;
    if (!background) setIsLoadingUsage(true);
    try {
      const res = await window.pywebview.api.get_api_usage(
        clearProtectedPrimary
          ? ''
          : hasProtectedKey && !apiKey.trim()
            ? undefined
            : apiKey.trim(),
        fallbackKeys,
        preferredModel,
        fallbackModels,
        forceRefresh,
      );
      if (isMountedRef.current && requestId === usageRequestIdRef.current) {
        setApiUsage(res?.ok && res.result ? res.result : null);
      }
    } catch (e) {
      if (isMountedRef.current && requestId === usageRequestIdRef.current) setApiUsage(null);
      reportClientError('Failed to fetch api usage:', e);
    } finally {
      // A superseded request must not release the current request's busy state.
      if (requestId === usageRequestIdRef.current) {
        usageRequestInFlightRef.current = false;
        if (!background && isMountedRef.current) setIsLoadingUsage(false);
      }
    }
  }, [apiKey, clearProtectedPrimary, fallbackKeys, fallbackModels, hasProtectedKey, preferredModel]);

  const handleRefreshUsage = useCallback(() => {
    void fetchApiUsage(true);
  }, [fetchApiUsage]);

  const handleRetryActivity = useCallback(() => {
    void fetchApiUsage();
  }, [fetchApiUsage]);

  useEffect(() => {
    if (!isOpen || activeTab !== 'diagnostics') return;
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'visible') void fetchApiUsage(false, true);
    }, 10_000);
    return () => window.clearInterval(intervalId);
  }, [isOpen, activeTab, fetchApiUsage]);

  useEffect(() => {
    if (isOpen) {
      if (activeTab === 'diagnostics' || activeTab === 'general') {
        void fetchApiUsage();
      }
      if (activeTab === 'storage') {
        void fetchSessionStorageInfo();
      }
    }
  }, [isOpen, activeTab, fetchApiUsage, fetchSessionStorageInfo]);

  useEffect(() => {
    if (isOpen) {
      setNotificationsEnabled(localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED) !== 'false');
      setClearProtectedPrimary(false);
      setSaveError(null);
      setIsSaving(false);
      isSavingRef.current = false;
      if (window.pywebview?.api?.load_settings) {
        window.pywebview.api.load_settings().then(res => {
          if (isMountedRef.current && res) {
            setCredentialStorage(res.credential_storage);
            setApiKeyInsecure(!!res.api_key_insecure);
            setApiKeyInsecureReason(res.api_key_insecure_reason || null);
          }
        }).catch(() => {});
      }
    } else {
      setValidationResult(null);
      setActiveTab('general');
    }
  }, [isOpen]);

  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
    setSaveError(null);
  };

  const runEnvironmentValidation = async () => {
    if (isValidatingEnvironment || !window.pywebview?.api?.validate_environment) return;
    setIsValidatingEnvironment(true);
    try {
      const response = await window.pywebview.api.validate_environment(
        apiKey.trim(),
        true,
        preferredModel,
        fallbackModels,
      );
      if (!isMountedRef.current) return;
      if (!response?.ok || !response.result) {
        appendConsole(`❌ Validazione ambiente fallita: ${response?.error || 'errore sconosciuto'}`);
        setValidationResult(null);
        return;
      }
      setValidationResult(response.result);
      appendConsole(response.result.summary);
      void fetchApiUsage();
    } catch (error: unknown) {
      if (isMountedRef.current) {
        appendConsole(`❌ Validazione ambiente fallita: ${getErrorMessage(error)}`);
        setValidationResult(null);
      }
    } finally {
      if (isMountedRef.current) setIsValidatingEnvironment(false);
    }
  };

  const handleCopyReport = async (sessionDir?: string) => {
    if (!window.pywebview?.api?.get_diagnostic_report) return;
    const res = await window.pywebview.api.get_diagnostic_report(
      undefined, undefined, undefined, undefined, sessionDir, APP_VERSION,
    );
    if (res?.ok && res.report) {
      await navigator.clipboard.writeText(res.report);
      appendConsole('📋 Report diagnostico copiato negli appunti.');
    } else {
      appendConsole(`❌ Generazione report diagnostico fallita: ${res?.error || 'errore sconosciuto'}`);
      throw new Error(res?.error || 'Errore generazione report diagnostico');
    }
  };

  const handleOpenLogs = useCallback(() => {
    if (window.pywebview?.api?.open_logs_folder) {
      void window.pywebview.api.open_logs_folder();
    }
  }, []);

  const getPendingChecks = useCallback((): DisplayCheck[] => {
    const isWindows = typeof window !== 'undefined' && /windows|win32/i.test(navigator.userAgent || '');
    const checks: DisplayCheck[] = [
      {
        id: 'api_key',
        label: 'API Key Gemini',
        status: 'pending',
        message: '',
        details: '',
      },
      {
        id: 'ffmpeg',
        label: 'FFmpeg',
        status: 'pending',
        message: '',
        details: '',
      },
      {
        id: 'config',
        label: 'Config locale',
        status: 'pending',
        message: '',
        details: '',
      },
      {
        id: 'output',
        label: 'Cartella sessioni/output',
        status: 'pending',
        message: '',
        details: sessionInfo?.session_root || '',
      },
    ];

    if (!isWindows) {
      checks.push({
        id: 'keyring',
        label: 'Keyring',
        status: 'pending',
        message: '',
        details: '',
      });
    }

    return checks;
  }, [sessionInfo?.session_root]);

  const getDisplayChecks = useCallback((): DisplayCheck[] => {
    const pending = getPendingChecks();
    if (!validationResult) return pending;

    const resultChecks = validationResult.checks;
    const list: DisplayCheck[] = [];
    for (const p of pending) {
      const match = resultChecks.find(r => r.id === p.id);
      if (match) {
        list.push({
          id: p.id,
          label: p.label,
          status: match.status,
          message: match.message,
          details: match.details,
        });
      } else {
        list.push(p);
      }
    }
    return list;
  }, [getPendingChecks, validationResult]);

  const handleSave = async () => {
    if (isSavingRef.current) return;
    isSavingRef.current = true;
    setIsSaving(true);
    setSaveError(null);

    try {
      if (!window.pywebview?.api?.save_settings) {
        const err = 'Bridge Python non disponibile — impostazioni non salvate.';
        if (isMountedRef.current) setSaveError(err);
        appendConsole(`❌ ${err}`);
        return;
      }
      const keys = fallbackKeys.map(k => k.trim()).filter(Boolean);
      let result;
      try {
        const apiKeyPayload = clearProtectedPrimary
          ? ''
          : hasProtectedKey && !apiKey.trim()
            ? null
            : apiKey.trim();
        const fallbackKeysPayload =
          fallbackKeys.length === 0 && (configuredFallbackKeyCount ?? 0) > 0
            ? null
            : keys;
        result = await window.pywebview.api.save_settings(
          apiKeyPayload,
          fallbackKeysPayload,
          preferredModel,
          fallbackModels,
        );
      } catch (e: unknown) {
        const err = `Errore salvataggio impostazioni: ${getErrorMessage(e)}`;
        if (isMountedRef.current) setSaveError(err);
        appendConsole(`❌ ${err}`);
        return;
      }
      if (!isMountedRef.current) return;
      if (!result?.ok) {
        const err = `Errore salvataggio impostazioni: ${result?.error || 'errore sconosciuto'}`;
        setSaveError(err);
        appendConsole(`❌ ${err}`);
        return;
      }
      settingsSnapshotRef.current = { apiKey, fallbackKeys: [...fallbackKeys], preferredModel, fallbackModels: [...fallbackModels], notificationsEnabled };
      setCredentialStorage(result.credential_storage);
      setApiKeyInsecure(Boolean(result.api_key_insecure));
      setApiKeyInsecureReason(result.api_key_insecure_reason || null);
      localStorage.setItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED, String(notificationsEnabled));
      try {
        await onSettingsSaved?.();
      } catch (e: unknown) {
        appendConsole(`Avviso: impostazioni salvate, ma il refresh dello stato non e riuscito: ${getErrorMessage(e)}`);
      }
      if (credentialStorageWarning(result.credential_storage, result.api_key_insecure)) {
        setActiveTab('general');
      } else {
        onClose();
      }
    } finally {
      isSavingRef.current = false;
      if (isMountedRef.current) setIsSaving(false);
    }
  };

  const handleClose = useCallback(() => {
    if (isSavingRef.current) return;
    setNotificationsEnabled(localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED) !== 'false');
    const snapshot = settingsSnapshotRef.current;
    if (snapshot) {
      setApiKey(snapshot.apiKey);
      setFallbackKeys([...snapshot.fallbackKeys]);
      setPreferredModel(snapshot.preferredModel);
      setFallbackModels([...snapshot.fallbackModels]);
      setClearProtectedPrimary(false);
    }
    onClose();
  }, [onClose, setApiKey, setFallbackKeys, setFallbackModels, setPreferredModel]);

  const handleConfirmDeleteKey = useCallback(() => {
    if (!keyDeleteTarget) return;

    if (keyDeleteTarget.type === 'primary') {
      const cleaned = fallbackKeys.map(k => k.trim()).filter(Boolean);
      if (cleaned.length > 0) {
        const [firstReserve, ...rest] = cleaned;
        setApiKey(firstReserve);
        setFallbackKeys(rest);
        setClearProtectedPrimary(false);
      } else {
        setApiKey('');
        if (hasProtectedKey) {
          setClearProtectedPrimary(true);
        }
      }
    } else if (keyDeleteTarget.type === 'fallback' && typeof keyDeleteTarget.index === 'number') {
      const cleaned = fallbackKeys.map(k => k.trim()).filter(Boolean);
      const updated = cleaned.filter((_, idx) => idx !== keyDeleteTarget.index);
      setFallbackKeys(updated);
    }

    setKeyDeleteTarget(null);
  }, [fallbackKeys, hasProtectedKey, keyDeleteTarget, setApiKey, setFallbackKeys]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isSavingRef.current) {
        e.preventDefault();
        handleClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, handleClose]);

  return (
    <>
      <AnimatePresence>
        {isOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="modal-overlay absolute inset-0"
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1, transition: { duration: 0.15, ease: [0.16, 1, 0.3, 1] } }}
              exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.12, ease: 'easeIn' } }}
              className="modal-card relative w-full max-w-md md:max-w-4xl h-[85vh] md:h-[80vh] overflow-hidden flex flex-col md:flex-row"
            >
              <nav aria-label="Sezioni delle impostazioni" className="settings-nav app-scroll">
                <div className="hidden md:flex items-center gap-2 px-3 py-2.5 mb-3 border-b border-[var(--border-subtle)]">
                  <Settings className="w-5 h-5 text-[var(--accent-text)] shrink-0" />
                  <span role="heading" aria-level={2} className="font-bold text-base tracking-wide uppercase text-[var(--text-primary)]">
                    Impostazioni
                  </span>
                </div>

                <button
                  type="button"
                  onClick={() => handleTabChange('general')}
                  aria-current={activeTab === 'general' ? 'page' : undefined}
                  className={`settings-nav-item ${activeTab === 'general' ? 'is-active' : ''}`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <SlidersHorizontal className={`w-4 h-4 shrink-0 transition-colors ${activeTab === 'general' ? 'text-[var(--accent-text)]' : 'text-[var(--text-secondary)]'}`} />
                    <span className="truncate">Generale</span>
                  </div>
                  <span
                    className={`w-1.5 h-1.5 rounded-full bg-[var(--accent-text)] shrink-0 hidden md:block transition-opacity duration-150 ${
                      activeTab === 'general' ? 'opacity-100' : 'opacity-0'
                    }`}
                  />
                </button>

                <button
                  type="button"
                  onClick={() => handleTabChange('storage')}
                  aria-current={activeTab === 'storage' ? 'page' : undefined}
                  className={`settings-nav-item ${activeTab === 'storage' ? 'is-active' : ''}`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <HardDrive className={`w-4 h-4 shrink-0 transition-colors ${activeTab === 'storage' ? 'text-[var(--accent-text)]' : 'text-[var(--text-secondary)]'}`} />
                    <span className="truncate">Archiviazione</span>
                  </div>
                  <span
                    className={`w-1.5 h-1.5 rounded-full bg-[var(--accent-text)] shrink-0 hidden md:block transition-opacity duration-150 ${
                      activeTab === 'storage' ? 'opacity-100' : 'opacity-0'
                    }`}
                  />
                </button>

                <button
                  type="button"
                  onClick={() => handleTabChange('diagnostics')}
                  aria-current={activeTab === 'diagnostics' ? 'page' : undefined}
                  className={`settings-nav-item ${activeTab === 'diagnostics' ? 'is-active' : ''}`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <FlaskConical className={`w-4 h-4 shrink-0 transition-colors ${activeTab === 'diagnostics' ? 'text-[var(--accent-text)]' : 'text-[var(--text-secondary)]'}`} />
                    <span className="truncate">Diagnostica</span>
                  </div>
                  <span
                    className={`w-1.5 h-1.5 rounded-full bg-[var(--accent-text)] shrink-0 hidden md:block transition-opacity duration-150 ${
                      activeTab === 'diagnostics' ? 'opacity-100' : 'opacity-0'
                    }`}
                  />
                </button>
              </nav>

              <div className="flex-1 min-h-0 flex flex-col min-w-0 bg-[var(--bg-surface)] relative">
                <button
                  type="button"
                  onClick={handleClose}
                  disabled={isSaving}
                  className="icon-button modal-icon-button absolute top-4 right-4 z-20"
                  aria-label="Chiudi finestra"
                >
                  <X className="w-4 h-4" />
                </button>
                <div ref={contentRef} className="app-scroll flex-1 overflow-y-auto overflow-x-hidden p-6 md:p-8 space-y-6 [scrollbar-gutter:stable]">
                  {activeTab === 'general' && (
                    <div className="space-y-6 animate-fade-in">
                      <div>
                        <h2 className="text-lg font-bold text-[var(--text-primary)] tracking-tight">Generale</h2>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                          Chiave API Google Gemini, modello di trascrizione e preferenze di sistema.
                        </p>
                      </div>

                      <ModelSection
                        preferredModel={preferredModel}
                        setPreferredModel={setPreferredModel}
                        availableModels={availableModels}
                      />

                      <div className="border-t border-[var(--border-default)]" />

                      <ApiKeySection
                        apiKey={apiKey}
                        setApiKey={key => {
                          if (key.trim()) setClearProtectedPrimary(false);
                          setApiKey(key);
                        }}
                        hasProtectedKey={hasProtectedKey && !clearProtectedPrimary}
                        credentialStorage={credentialStorage}
                        apiKeyInsecure={apiKeyInsecure}
                        apiKeyInsecureReason={apiKeyInsecureReason || ''}
                        fallbackKeys={fallbackKeys}
                        setFallbackKeys={setFallbackKeys}
                        onClearProtectedPrimary={() => setClearProtectedPrimary(true)}
                        apiUsage={apiUsage}
                        isLoadingUsage={isLoadingUsage}
                        preferredModel={preferredModel}
                        onAskDeleteKey={setKeyDeleteTarget}
                        onRefreshUsage={handleRefreshUsage}
                        statusSummary={<ApiStatusSection apiUsage={apiUsage} isLoadingUsage={isLoadingUsage} />}
                      />

                      <div className="border-t border-[var(--border-default)]" />

                      <NotificationSection
                        notificationsEnabled={notificationsEnabled}
                        onChange={setNotificationsEnabled}
                        disabled={isSaving}
                      />

                      <div className="border-t border-[var(--border-default)]" />

                      <UpdaterSection
                        latestVersion={latestVersion}
                        checkForUpdates={checkForUpdates}
                        isCheckingUpdate={isCheckingUpdate}
                        hasChecked={hasChecked}
                        checkFailed={checkFailed}
                        updateInstallState={updateInstallState}
                        onInstallUpdate={onInstallUpdate}
                      />
                    </div>
                  )}

                  {activeTab === 'storage' && (
                    <div className="space-y-6 animate-fade-in">
                      <div>
                        <h2 className="text-lg font-bold text-[var(--text-primary)] tracking-tight">Archiviazione</h2>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                          Spazio su disco occupato dalle sbobine e gestione della cartella di lavoro.
                        </p>
                      </div>

                      <StorageSection
                        sessionInfo={sessionInfo}
                        isLoadingSessionInfo={isLoadingSessionInfo}
                        onOpenSessionFolder={handleOpenSessionFolder}
                        onAskMoveFolder={handleAskMoveFolder}
                        isMoveInProgress={isMoveInProgress}
                        moveProgress={moveProgress}
                        moveError={moveError}
                        isCleaningSession={isCleaningSession}
                        isCleaningCompletedSessions={isCleaningCompletedSessions}
                        cleanupPreview={cleanupPreview}
                        completedCleanupPreview={completedCleanupPreview}
                        onAskCleanup={handleAskCleanup}
                        onAskCompletedCleanup={handleAskCompletedCleanup}
                        cleanupResult={cleanupResult}
                        completedCleanupResult={completedCleanupResult}
                        onDismissCleanupResult={handleDismissCleanupResult}
                        canManageSessionFolder={hostCapabilities.nativeFolderPicker && hostCapabilities.openLocalPath}
                      />
                    </div>
                  )}

                  {activeTab === 'diagnostics' && (
                    <div className="space-y-6 animate-fade-in">
                      <div>
                        <h2 className="text-lg font-bold text-[var(--text-primary)] tracking-tight">Diagnostica</h2>
                        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                          Verifica requisiti di sistema (FFmpeg, API, disco) e report di assistenza.
                        </p>
                      </div>

                      <ActivitySection
                        apiUsage={apiUsage}
                        isLoadingUsage={isLoadingUsage}
                        onRetry={handleRetryActivity}
                      />
                      <div className="border-t border-[var(--border-default)]" />

                      <DiagnosticsSection
                        isValidatingEnvironment={isValidatingEnvironment}
                        onRunValidation={runEnvironmentValidation}
                        validationResult={validationResult}
                        displayChecks={getDisplayChecks()}
                        onCopyReport={handleCopyReport}
                        onOpenLogs={handleOpenLogs}
                        showOpenLogs={hostCapabilities.openLocalPath}
                      />

                    </div>
                  )}
                </div>

                <div className="modal-footer flex items-center justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    {saveError && (
                      <p role="alert" className="text-xs text-[var(--error-text)] font-semibold break-words">
                        {saveError}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {!showCloseOnly && <button
                      type="button"
                      onClick={handleClose}
                      disabled={isSaving}
                      className="modal-action-button"
                    >
                      Annulla
                    </button>}

                    <button
                      type="button"
                      onClick={showCloseOnly ? handleClose : handleSave}
                      disabled={isSaving}
                      className="modal-action-button is-primary"
                    >
                      {isSaving && <Loader2 className="w-4 h-4 animate-spin" />}
                      {showCloseOnly ? 'Chiudi' : 'Salva e Chiudi'}
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Confirmation Dialog Modals */}
      <ConfirmActionModal
        isOpen={showCleanupConfirm}
        title="Eliminare tutte le elaborazioni incomplete?"
        description={`Questa operazione elimina subito tutte le elaborazioni incomplete per liberare spazio. Sbobine interessate: ${cleanupPreview?.candidates ?? 0}. Spazio stimato: ${formatSize(cleanupPreview?.freed_bytes ?? 0)}. L'operazione è irreversibile.`}
        confirmLabel="Elimina incomplete"
        cancelLabel="Annulla"
        onClose={() => setShowCleanupConfirm(false)}
        onConfirm={() => {
          setShowCleanupConfirm(false);
          void handleCleanupSessions();
        }}
      />
      <ConfirmActionModal
        isOpen={showCompletedCleanupConfirm}
        title="Eliminare le sbobine completate vecchie?"
        description={`Questa operazione elimina subito le sbobine completate più vecchie di ${SESSION_CLEANUP_DAYS} giorni. Sbobine interessate: ${completedCleanupPreview?.candidates ?? 0}. Spazio stimato: ${formatSize(completedCleanupPreview?.freed_bytes ?? 0)}. L'operazione è irreversibile.`}
        confirmLabel="Elimina sbobine completate"
        cancelLabel="Annulla"
        onClose={() => setShowCompletedCleanupConfirm(false)}
        onConfirm={() => {
          setShowCompletedCleanupConfirm(false);
          void handleCleanupCompletedSessions();
        }}
      />
      <ConfirmActionModal
        isOpen={showMoveConfirm}
        title="Spostare la cartella sessioni?"
        description={`Le sessioni verranno spostate subito in:\n${pendingMovePath ?? ''}\n\nL'operazione è rapida se la destinazione è sullo stesso disco.`}
        confirmLabel="Sposta"
        cancelLabel="Annulla"
        onClose={handleCancelMove}
        onConfirm={() => {
          void handleConfirmMove();
        }}
      />
      <ConfirmActionModal
        isOpen={Boolean(keyDeleteTarget)}
        title="Rimuovi chiave API"
        description={
          keyDeleteTarget?.type === 'primary'
            ? fallbackKeys.map(k => k.trim()).filter(Boolean).length > 0
              ? `Sei sicuro di voler rimuovere la Chiave Principale (${keyDeleteTarget.maskedKey})? La Chiave Riserva 1 verrà promossa automaticamente a nuova chiave principale.`
              : `Sei sicuro di voler rimuovere la Chiave Principale (${keyDeleteTarget?.maskedKey})? Non sarà più possibile eseguire trascrizioni fino all'inserimento di una nuova chiave.`
            : `Sei sicuro di voler rimuovere ${keyDeleteTarget?.label || 'questa chiave di riserva'} (${keyDeleteTarget?.maskedKey})?`
        }
        confirmLabel="Rimuovi"
        cancelLabel="Annulla"
        onClose={() => setKeyDeleteTarget(null)}
        onConfirm={handleConfirmDeleteKey}
      />
    </>
  );
};
