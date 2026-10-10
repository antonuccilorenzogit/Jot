import { reportClientError } from '../diagnostics';
import { beginDesktopSettingsLoad, completeDesktopStartup } from '../desktopStartup';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ModelOption, SettingsPayload } from '../bridge';
import { credentialStorageWarning } from '../credentialStorage';
import { DEFAULT_MODEL } from '../utils';

export function useApiReady(appendConsole: (msg: string) => void) {
  const [apiReady, setApiReady] = useState(false);
  const [bridgeDelayed, setBridgeDelayed] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [hasProtectedKey, setHasProtectedKey] = useState(false);
  const [apiKeyInsecure, setApiKeyInsecure] = useState(false);
  const [apiKeyInsecureReason, setApiKeyInsecureReason] = useState('');
  const [configRecoveredFrom, setConfigRecoveredFrom] = useState('');
  const [fallbackKeys, setFallbackKeys] = useState<string[]>([]);
  const [configuredFallbackKeyCount, setConfiguredFallbackKeyCount] = useState(0);
  const [preferredModel, setPreferredModel] = useState(DEFAULT_MODEL);
  const [fallbackModels, setFallbackModels] = useState<string[]>([]);
  const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);
  const initDoneRef = useRef(false);
  const inFlightRef = useRef(false);
  const bootstrapAttemptRef = useRef(0);
  const retriesRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const appendConsoleRef = useRef(appendConsole);

  useEffect(() => {
    appendConsoleRef.current = appendConsole;
  }, [appendConsole]);

  useEffect(() => {
    if (apiKey) setHasProtectedKey(false);
  }, [apiKey]);

  const applySettings = useCallback((cfg: SettingsPayload | undefined) => {
    const nextApiKey = String(cfg?.api_key ?? '');
    setApiKey(nextApiKey);
    setHasProtectedKey(Boolean(cfg?.has_protected_key) && !nextApiKey);
    const storageWarning = credentialStorageWarning(cfg?.credential_storage, cfg?.credential_storage ? cfg.api_key_insecure : false);
    setApiKeyInsecure(Boolean(storageWarning || cfg?.api_key_insecure));
    setApiKeyInsecureReason(storageWarning || String(cfg?.api_key_insecure_reason ?? ''));
    setConfigRecoveredFrom(String(cfg?.config_recovered_from ?? ''));
    setFallbackKeys(Array.isArray(cfg?.fallback_keys) ? cfg.fallback_keys : []);
    setConfiguredFallbackKeyCount(Number(cfg?.configuredFallbackKeyCount ?? 0));
    setPreferredModel(cfg?.preferred_model || DEFAULT_MODEL);
    setFallbackModels(Array.isArray(cfg?.fallback_models) ? cfg.fallback_models : []);
    setAvailableModels(Array.isArray(cfg?.available_models) ? cfg.available_models : []);
  }, []);

  const refreshSettings = useCallback(async () => {
    if (!window.pywebview?.api?.load_settings) return false;
    const cfg = await window.pywebview.api.load_settings();
    applySettings(cfg);
    return true;
  }, [applySettings]);

  useEffect(() => {
    let alive = true;

    const tryBootstrap = async () => {
      if (initDoneRef.current) return;
      if (inFlightRef.current) return;
      if (!window.pywebview?.api?.load_settings) return;

      inFlightRef.current = true;
      const attempt = ++bootstrapAttemptRef.current;
      try {
        await beginDesktopSettingsLoad();
        if (!alive || attempt !== bootstrapAttemptRef.current) return;
        const cfg = await window.pywebview.api.load_settings();
        if (!alive || attempt !== bootstrapAttemptRef.current) return;
        await completeDesktopStartup();
        if (!alive || attempt !== bootstrapAttemptRef.current) return;
        initDoneRef.current = true;
        setBridgeDelayed(false);
        setApiReady(true);
        appendConsoleRef.current('Connesso a Python.');
        applySettings(cfg);
      } catch (e) {
        reportClientError('Load settings failed:', e);
        if (!alive || attempt !== bootstrapAttemptRef.current) return;
        if (!initDoneRef.current && retriesRef.current < 3) {
          retriesRef.current += 1;
          if (retryTimerRef.current !== null) clearTimeout(retryTimerRef.current);
          retryTimerRef.current = setTimeout(tryBootstrap, 2000);
        } else if (!initDoneRef.current) {
          setBridgeDelayed(true);
        }
      } finally {
        if (attempt === bootstrapAttemptRef.current) {
          inFlightRef.current = false;
        }
      }
    };

    const onBridgeReady = () => {
      if (!initDoneRef.current) {
        if (retryTimerRef.current !== null) { clearTimeout(retryTimerRef.current); retryTimerRef.current = null; }
        retriesRef.current = 0;
      }
      tryBootstrap();
    };
    window.addEventListener('pywebviewready', onBridgeReady);
    tryBootstrap();

    const delayedWarning = setTimeout(() => {
      if (initDoneRef.current) return;
      if (retryTimerRef.current !== null) { clearTimeout(retryTimerRef.current); retryTimerRef.current = null; }
      retriesRef.current = 3;
      setBridgeDelayed(true);
      if (inFlightRef.current) return;
      tryBootstrap();
    }, 5000);

    return () => {
      alive = false;
      bootstrapAttemptRef.current += 1;
      inFlightRef.current = false;
      window.removeEventListener('pywebviewready', onBridgeReady);
      clearTimeout(delayedWarning);
      if (retryTimerRef.current !== null) { clearTimeout(retryTimerRef.current); retryTimerRef.current = null; }
    };
  }, [applySettings]);

  return {
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
  };
}
