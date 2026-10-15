import { reportClientError } from '../../../diagnostics';
import React, { useState, useMemo, useCallback } from 'react';
import {
  Key,
  ShieldCheck,
  AlertCircle,
  AlertTriangle,
  Plus,
  ExternalLink,
  Eye,
  EyeOff,
  Copy,
  Check,
  ArrowUp,
  ArrowDown,
  Star,
  Loader2,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import { ConfirmActionModal } from '../ConfirmActionModal';
import { QuotasSection } from './QuotasSection';
import { KebabMenu, type KebabMenuItem } from '../../KebabMenu';
import { GEMINI_KEY_PATTERN, getModelDisplayName } from '../../../utils';
import type { ApiUsageResult, CredentialProfile, CredentialStorage } from '../../../bridge';

import { credentialStorageWarning } from '../../../credentialStorage';

export interface ApiKeySectionProps {
  apiKey: string;
  setApiKey: (key: string) => void;
  hasProtectedKey: boolean;
  credentialStorage?: CredentialStorage;
  apiKeyInsecure: boolean;
  apiKeyInsecureReason: string;
  fallbackKeys: string[];
  setFallbackKeys: (keys: string[]) => void;
  onClearProtectedPrimary?: () => void;
  apiUsage?: ApiUsageResult | null;
  isLoadingUsage?: boolean;
  onRefreshUsage?: () => void;
  preferredModel?: string;
  onAskDeleteKey?: (target: DeleteKeyTarget) => void;
  statusSummary?: React.ReactNode;
}

export interface DeleteKeyTarget {
  type: 'primary' | 'fallback';
  index?: number;
  label: string;
  maskedKey: string;
}

export const ApiKeySection: React.FC<ApiKeySectionProps> = React.memo(({
  apiKey,
  setApiKey,
  hasProtectedKey,
  credentialStorage,
  apiKeyInsecure,
  apiKeyInsecureReason,
  fallbackKeys,
  setFallbackKeys,
  onClearProtectedPrimary,
  apiUsage,
  isLoadingUsage = false,
  onRefreshUsage,
  preferredModel,
  onAskDeleteKey,
  statusSummary,
}) => {
  const storageWarning = credentialStorageWarning(credentialStorage, credentialStorage ? apiKeyInsecure : false) || (apiKeyInsecure ? (apiKeyInsecureReason || 'Credenziali presenti in chiaro nel file di configurazione.') : '');
  const [newKeyInput, setNewKeyInput] = useState('');
  const [notice, setNotice] = useState<{ type: 'error' | 'warning'; message: string } | null>(null);
  const [showNewKeyInput, setShowNewKeyInput] = useState(false);
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteKeyTarget | null>(null);

  const requestDeleteKey = (target: DeleteKeyTarget) => {
    if (onAskDeleteKey) {
      onAskDeleteKey(target);
    } else {
      setDeleteTarget(target);
    }
  };

  const cleanedFallbackKeys = useMemo(
    () => fallbackKeys.map(k => k.trim()).filter(Boolean),
    [fallbackKeys]
  );

  const hasPrimaryConfigured = Boolean(apiKey.trim() || hasProtectedKey);
  const totalKeysCount = (hasPrimaryConfigured ? 1 : 0) + cleanedFallbackKeys.length;

  const credentials: CredentialProfile[] = useMemo(() => {
    if (apiUsage?.credentials && apiUsage.credentials.length > 0) {
      return apiUsage.credentials;
    }
    if (apiUsage?.keys && apiUsage.keys.length > 0) {
      return apiUsage.keys.map((k, idx) => ({
        id: k.id,
        masked_key: k.masked_key,
        label: k.label,
        is_primary: k.is_primary,
        operational_status: (k.operational_status ||
          (Object.values(k.models || {}).some(m => m.is_exhausted)
            ? 'temporarily_failing'
            : 'active')) as CredentialProfile['operational_status'],
        key_type: (idx === 0 ? 'standard_legacy' : 'unknown') as CredentialProfile['key_type'],
        project_id: null,
        last_error_message: null,
      }));
    }
    return [];
  }, [apiUsage]);

  const getCredentialFor = useCallback(
    (rawKey: string, isPrimary: boolean, fallbackIdx?: number): CredentialProfile | undefined => {
      if (credentials.length === 0) return undefined;
      if (rawKey) {
        const suffix = rawKey.slice(-4);
        const found = credentials.find(c => c.masked_key?.endsWith(suffix));
        if (found) return found;
      }
      if (isPrimary) {
        return credentials.find(c => c.is_primary);
      }
      if (fallbackIdx !== undefined) {
        const nonPrimary = credentials.filter(c => !c.is_primary);
        return nonPrimary[fallbackIdx];
      }
      return undefined;
    },
    [credentials]
  );

  const processKeys = (candidates: string[]) => {
    if (candidates.length === 0) return;

    const primaryKeyTrimmed = apiKey.trim();
    const isPrimaryEmpty = !primaryKeyTrimmed && !hasProtectedKey;

    if (candidates.length === 1) {
      const cand = candidates[0];
      if (!GEMINI_KEY_PATTERN.test(cand)) {
        setNotice({
          type: 'error',
          message: 'Formato API key non valido (deve iniziare con "AIzaSy" o "AQ.")',
        });
        return;
      }

      if (isPrimaryEmpty) {
        setApiKey(cand);
        setNewKeyInput('');
        setShowNewKeyInput(false);
        setNotice(null);
        return;
      }

      if (primaryKeyTrimmed && cand === primaryKeyTrimmed) {
        setNotice({
          type: 'error',
          message: 'Questa chiave è già impostata come chiave principale.',
        });
        return;
      }
      if (cleanedFallbackKeys.includes(cand)) {
        setNotice({
          type: 'error',
          message: 'Questa chiave è già presente tra le riserve.',
        });
        return;
      }

      setFallbackKeys([...cleanedFallbackKeys, cand]);
      setNewKeyInput('');
      setShowNewKeyInput(false);
      setNotice(null);
      return;
    }

    const newValidKeys: string[] = [];
    let skippedCount = 0;
    let nextPrimary = isPrimaryEmpty ? '' : primaryKeyTrimmed;

    for (const cand of candidates) {
      if (!GEMINI_KEY_PATTERN.test(cand)) {
        skippedCount++;
        continue;
      }
      if (isPrimaryEmpty && !nextPrimary) {
        nextPrimary = cand;
        continue;
      }
      if (nextPrimary && cand === nextPrimary) {
        skippedCount++;
        continue;
      }
      if (cleanedFallbackKeys.includes(cand) || newValidKeys.includes(cand)) {
        skippedCount++;
        continue;
      }
      newValidKeys.push(cand);
    }

    if (isPrimaryEmpty && nextPrimary) {
      setApiKey(nextPrimary);
    }

    if (newValidKeys.length > 0 || (isPrimaryEmpty && nextPrimary)) {
      if (newValidKeys.length > 0) {
        setFallbackKeys([...cleanedFallbackKeys, ...newValidKeys]);
      }
      setNewKeyInput('');
      setShowNewKeyInput(false);
      const totalAdded = (isPrimaryEmpty && nextPrimary ? 1 : 0) + newValidKeys.length;
      if (skippedCount > 0) {
        setNotice({
          type: 'warning',
          message: `${totalAdded} ${totalAdded === 1 ? 'chiave aggiunta' : 'chiavi aggiunte'}. ${skippedCount} ${skippedCount === 1 ? 'ignorata' : 'ignorate'} (non valida o già presente).`,
        });
      } else {
        setNotice(null);
      }
    } else {
      setNotice({
        type: 'error',
        message: 'Nessuna chiave valida aggiunta: le chiavi inserite sono già presenti o non valide.',
      });
    }
  };

  const handleAddKey = () => {
    const raw = newKeyInput.trim();
    if (!raw) return;

    const candidates = raw
      .split(/[\r\n,;\s]+/)
      .map(k => k.trim())
      .filter(Boolean);

    processKeys(candidates);
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData?.getData('text');
    if (!text) return;

    const candidates = text
      .split(/[\r\n,;\s]+/)
      .map(k => k.trim())
      .filter(Boolean);

    if (candidates.length > 1) {
      e.preventDefault();
      processKeys(candidates);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddKey();
    }
  };

  const handlePromoteToPrimary = (index: number) => {
    const targetKey = cleanedFallbackKeys[index];
    if (!targetKey) return;

    const currentPrimary = apiKey.trim();
    const updatedFallbacks = [...cleanedFallbackKeys];

    if (currentPrimary) {
      updatedFallbacks[index] = currentPrimary;
    } else {
      updatedFallbacks.splice(index, 1);
    }

    setApiKey(targetKey);
    setFallbackKeys(updatedFallbacks);
    setNotice(null);
  };

  const handleMoveUp = (index: number) => {
    if (index <= 0) return;
    const updated = [...cleanedFallbackKeys];
    const temp = updated[index];
    updated[index] = updated[index - 1];
    updated[index - 1] = temp;
    setFallbackKeys(updated);
  };

  const handleMoveDown = (index: number) => {
    if (index >= cleanedFallbackKeys.length - 1) return;
    const updated = [...cleanedFallbackKeys];
    const temp = updated[index];
    updated[index] = updated[index + 1];
    updated[index + 1] = temp;
    setFallbackKeys(updated);
  };

  const handleCopyKey = async (rawKey: string, id: string) => {
    if (!rawKey) return;
    try {
      await navigator.clipboard.writeText(rawKey);
      setCopiedKeyId(id);
      setTimeout(() => {
        setCopiedKeyId(prev => (prev === id ? null : prev));
      }, 2000);
    } catch (e) {
      reportClientError('Failed to copy key to clipboard:', e);
    }
  };

  const handleConfirmDelete = () => {
    if (!deleteTarget) return;

    if (deleteTarget.type === 'primary') {
      if (cleanedFallbackKeys.length > 0) {
        const [firstReserve, ...rest] = cleanedFallbackKeys;
        setApiKey(firstReserve);
        setFallbackKeys(rest);
      } else {
        setApiKey('');
        if (hasProtectedKey) {
          onClearProtectedPrimary?.();
        }
      }
    } else if (deleteTarget.type === 'fallback' && typeof deleteTarget.index === 'number') {
      const updated = cleanedFallbackKeys.filter((_, idx) => idx !== deleteTarget.index);
      setFallbackKeys(updated);
    }

    setDeleteTarget(null);
    setNotice(null);
  };

  const effectivePreferredModel = preferredModel || 'gemini-2.5-flash';

  const isCredWorkingForModel = useCallback(
    (c?: CredentialProfile) => {
      if (!c) return true;
      if (
        c.operational_status === 'invalid' ||
        c.operational_status === 'permission_denied' ||
        c.operational_status === 'request_error'
      ) {
        return false;
      }
      const exhausted = c.exhausted_models || [];
      if (exhausted.includes(effectivePreferredModel)) {
        return false;
      }
      // If temporarily_failing but it has exhausted_models that don't include effectivePreferredModel,
      // the failure was strictly on those other models, so it IS working for effectivePreferredModel.
      if (c.operational_status === 'temporarily_failing' && exhausted.length === 0) {
        return false;
      }
      return true;
    },
    [effectivePreferredModel]
  );

  const primaryCred = getCredentialFor(apiKey, true);
  const isPrimaryWorking = hasPrimaryConfigured && isCredWorkingForModel(primaryCred);

  const activeFallbackKey = !isPrimaryWorking
    ? cleanedFallbackKeys.find((k, idx) => {
        const c = getCredentialFor(k, false, idx);
        return isCredWorkingForModel(c);
      })
    : null;

  const renderCredentialStatusBadge = (
    cred?: CredentialProfile,
    isPrimary?: boolean,
    keyVal?: string,
  ) => {
    if (isLoadingUsage) {
      return (
        <span className="text-[11px] font-semibold px-2.5 py-0.5 rounded-full bg-[var(--bg-surface)] text-[var(--text-secondary)] border border-[var(--border-default)] inline-flex items-center gap-1 leading-normal shrink-0">
          <Loader2 className="w-3 h-3 animate-spin text-[var(--accent-text)]" />
          <span>Verifica...</span>
        </span>
      );
    }

    const baseBadge =
      'text-[11px] font-semibold px-2.5 py-0.5 rounded-full inline-flex items-center justify-center leading-normal shrink-0';

    if (!cred) {
      if (isPrimary) {
        return (
          <span
            className={`${baseBadge} bg-[var(--accent-subtle)] text-[var(--accent-text)] border border-[var(--accent-ring)]`}
            title={`Operativa per ${getModelDisplayName(effectivePreferredModel)}`}
          >
            Operativa
          </span>
        );
      }
      return (
        <span
          className={`${baseBadge} bg-[var(--bg-surface)] text-[var(--text-secondary)] border border-[var(--border-default)]`}
          title={`Disponibile in riserva per ${getModelDisplayName(effectivePreferredModel)}`}
        >
          In riserva
        </span>
      );
    }

    const status = cred.operational_status;
    const exhaustedModels = cred.exhausted_models || [];
    const isCurrentModelExhausted = Boolean(
      effectivePreferredModel && exhaustedModels.includes(effectivePreferredModel)
    );

    if (status === 'invalid') {
      return (
        <span className={`${baseBadge} bg-[var(--error-subtle,var(--bg-surface))] text-[var(--error-text)] border border-[var(--error-ring)]`}>
          Non valida (401)
        </span>
      );
    }
    if (status === 'permission_denied') {
      return (
        <span className={`${baseBadge} bg-[var(--error-subtle,var(--bg-surface))] text-[var(--error-text)] border border-[var(--error-ring)]`}>
          Permesso negato (403)
        </span>
      );
    }
    if (status === 'request_error') {
      return (
        <span className={`${baseBadge} bg-[var(--error-subtle,var(--bg-surface))] text-[var(--error-text)] border border-[var(--error-ring)]`}>
          Errore richiesta (400)
        </span>
      );
    }

    const isCurrentModelQuotaExhausted =
      isCurrentModelExhausted ||
      (status === 'temporarily_failing' &&
        exhaustedModels.length === 0 &&
        (!cred.last_error_message ||
          cred.last_error_message.toLowerCase().includes('quota') ||
          cred.last_error_message.toLowerCase().includes('rpd') ||
          cred.last_error_code === 429));

    if (isCurrentModelQuotaExhausted) {
      if (exhaustedModels.length === 1) {
        return (
          <span
            className={`${baseBadge} bg-[var(--warning-subtle,var(--bg-surface))] text-[var(--warning-text)] border border-[var(--warning-ring)]`}
            title={`Quota esaurita per ${getModelDisplayName(exhaustedModels[0])}. Disponibile per gli altri modelli.`}
          >
            Quota esaurita per {getModelDisplayName(exhaustedModels[0])}
          </span>
        );
      }
      if (exhaustedModels.length > 1) {
        const names = exhaustedModels.map(getModelDisplayName).join(', ');
        const otherCount = exhaustedModels.length - 1;
        const label = isCurrentModelExhausted
          ? `Quota esaurita per ${getModelDisplayName(effectivePreferredModel)} (+${otherCount})`
          : `Quota esaurita (${exhaustedModels.length} modelli)`;
        return (
          <span
            className={`${baseBadge} bg-[var(--warning-subtle,var(--bg-surface))] text-[var(--warning-text)] border border-[var(--warning-ring)]`}
            title={`Quota esaurita per: ${names}. Disponibile per gli altri modelli.`}
          >
            {label}
          </span>
        );
      }
      return (
        <span className={`${baseBadge} bg-[var(--warning-subtle,var(--bg-surface))] text-[var(--warning-text)] border border-[var(--warning-ring)]`}>
          Quota esaurita (oggi)
        </span>
      );
    }

    if (status === 'temporarily_failing' && exhaustedModels.length === 0) {
      return (
        <span className={`${baseBadge} bg-[var(--warning-subtle,var(--bg-surface))] text-[var(--warning-text)] border border-[var(--warning-ring)]`}>
          Non disponibile (temporaneo)
        </span>
      );
    }

    const renderExhaustedTag = () => {
      const otherExhaustedModels = exhaustedModels.filter(
        m => m !== effectivePreferredModel
      );
      if (otherExhaustedModels.length === 0) return null;
      const label =
        otherExhaustedModels.length === 1
          ? `Esaurita per ${getModelDisplayName(otherExhaustedModels[0])}`
          : otherExhaustedModels.length === 2
          ? `Esaurita per ${otherExhaustedModels.map(m => getModelDisplayName(m).replace('Gemini ', '')).join(' & ')}`
          : `Esaurita per ${otherExhaustedModels.length} modelli`;
      const title = `Disponibile per ${getModelDisplayName(effectivePreferredModel)}. Quota esaurita oggi per: ${otherExhaustedModels.map(getModelDisplayName).join(', ')}`;
      return (
        <span
          className="text-[10px] font-medium text-[var(--warning-text)] bg-[var(--warning-subtle,var(--bg-surface))] px-2 py-0.5 rounded-full border border-[var(--warning-ring)] leading-normal shrink-0"
          title={title}
        >
          {label}
        </span>
      );
    };

    // Operational or reserve status
    if (isPrimary || cred.is_primary) {
      return (
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          <span
            className={`${baseBadge} bg-[var(--accent-subtle)] text-[var(--accent-text)] border border-[var(--accent-ring)]`}
            title={`Operativa per ${getModelDisplayName(effectivePreferredModel)}`}
          >
            Operativa
          </span>
          {renderExhaustedTag()}
        </div>
      );
    }

    if (keyVal && keyVal === activeFallbackKey) {
      return (
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          <span
            className={`${baseBadge} bg-[var(--accent-subtle)] text-[var(--accent-text)] border border-[var(--accent-ring)]`}
            title={`In uso per ${getModelDisplayName(effectivePreferredModel)}`}
          >
            In uso (riserva)
          </span>
          {renderExhaustedTag()}
        </div>
      );
    }

    return (
      <div className="flex items-center gap-1.5 flex-wrap justify-end">
        <span
          className={`${baseBadge} bg-[var(--bg-surface)] text-[var(--text-secondary)] border border-[var(--border-default)]`}
          title={`Disponibile in riserva per ${getModelDisplayName(effectivePreferredModel)}`}
        >
          In riserva
        </span>
        {renderExhaustedTag()}
      </div>
    );
  };
  const primaryMaskedDisplay = apiKey
    ? `...${apiKey.slice(-4)}`
    : (primaryCred?.masked_key
        ? `...${primaryCred.masked_key.slice(-4)}`
        : (hasProtectedKey ? '••••••••••••' : ''));

  const primaryKebabItems: KebabMenuItem[] = [
    ...(apiKey
      ? [
          {
            label: copiedKeyId === 'primary' ? 'Chiave copiata!' : 'Copia chiave',
            icon: copiedKeyId === 'primary' ? <Check className="w-3.5 h-3.5 text-[var(--success-text)]" /> : <Copy className="w-3.5 h-3.5" />,
            onClick: () => handleCopyKey(apiKey, 'primary'),
          },
          { separator: true as const },
        ]
      : []),
    {
      label: 'Rimuovi chiave',
      icon: <Trash2 className="w-3.5 h-3.5" />,
      danger: true,
      onClick: () =>
        requestDeleteKey({
          type: 'primary',
          label: 'Chiave Principale',
          maskedKey: primaryMaskedDisplay,
        }),
    },
  ];

  return (
    <div className="space-y-3">
      {/* 1. Header with count & global actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Key className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)] truncate">
            Chiavi API
          </h3>
          {totalKeysCount > 0 && (
            <span className="text-[11px] font-semibold text-[var(--text-secondary)] bg-[var(--bg-surface)] border border-[var(--border-default)] px-2 py-0.5 rounded-full leading-normal shrink-0">
              {totalKeysCount} {totalKeysCount === 1 ? 'chiave' : 'chiavi'}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {onRefreshUsage && (
            <button type="button" onClick={onRefreshUsage} disabled={isLoadingUsage}
              className="app-button-secondary is-settings-action min-w-[166px]"
              title={isLoadingUsage ? 'Verifica in corso…' : 'Verifica connessione'} aria-label="Verifica connessione">
              <RefreshCw className={`w-4 h-4 ${isLoadingUsage ? 'animate-spin' : ''}`} />
              <span>{isLoadingUsage ? 'Verifica in corso…' : 'Verifica connessione'}</span>
            </button>
          )}
        </div>
      </div>

      {statusSummary}

      {/* 2. Compact Add Key Bar */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 min-w-0">
          <input
            type={showNewKeyInput ? 'text' : 'password'}
            value={newKeyInput}
            onChange={e => {
              setNewKeyInput(e.target.value);
              if (notice) setNotice(null);
            }}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={
              hasPrimaryConfigured
                ? 'Aggiungi chiave di riserva (AIzaSy... o AQ...)'
                : 'Inserisci chiave principale (AIzaSy... o AQ...)'
            }
            aria-label="Nuova chiave di riserva"
            autoComplete="off"
            data-lpignore="true"
            data-1p-ignore="true"
            data-form-type="other"
            spellCheck={false}
            autoCorrect="off"
            autoCapitalize="off"
            className={`app-input is-settings-input ${
              notice?.type === 'error' ? 'is-invalid' : ''
            }`}
          />
          <button
            type="button"
            onClick={() => setShowNewKeyInput(prev => !prev)}
            className="absolute inset-y-0 right-2 flex items-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
            aria-label={showNewKeyInput ? 'Nascondi nuova chiave' : 'Mostra nuova chiave'}
            title={showNewKeyInput ? 'Nascondi nuova chiave' : 'Mostra nuova chiave'}
          >
            {showNewKeyInput ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        </div>
        <button
          type="button"
          onClick={handleAddKey}
          disabled={!newKeyInput.trim()}
          className="premium-button compact-button text-xs font-bold shrink-0 cursor-pointer flex items-center gap-1.5 min-h-[38px]"
          aria-label="Aggiungi chiave di riserva"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Aggiungi</span>
        </button>
      </div>

      {/* Validation / Format Notice */}
      {notice && (
        <div
          className={`alert-card ${
            notice.type === 'warning' ? 'is-warning' : 'is-error'
          } text-xs flex-row items-center gap-2 py-2 px-3 animate-fade-in`}
        >
          {notice.type === 'warning' ? (
            <AlertTriangle className="w-4 h-4 shrink-0" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0" />
          )}
          <span className="font-medium leading-snug">{notice.message}</span>
        </div>
      )}

      {/* Storage / Security notice */}
      {storageWarning && (
        <div className="alert-card is-warning text-xs space-y-1">
          <div className="font-bold flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {credentialStorage?.primary === 'session_only' || credentialStorage?.fallback === 'session_only' ? 'Credenziali temporanee' : 'Memorizzazione in chiaro'}
          </div>
          <p className="text-[var(--text-secondary)]">
            {storageWarning}
          </p>
        </div>
      )}

      {/* 3. Structured Card Table (Quotas Layout) */}
      <div className="border border-[var(--border-default)] rounded-lg divide-y divide-[var(--border-default)] overflow-hidden bg-[var(--bg-surface)]">
        {/* Row 1: Chiave Principale (if configured) */}
        {hasPrimaryConfigured ? (
          <div className="py-2 px-3.5 flex items-center justify-between gap-2.5 text-xs">
            <div className="flex items-center gap-2 min-w-0 flex-wrap">
              <span className="font-bold text-[var(--text-primary)]">Chiave Principale</span>

              <span
                className="px-2.5 py-0.5 rounded-full bg-[var(--bg-hover)] border border-[var(--border-default)] font-mono text-[11px] text-[var(--text-primary)] font-semibold inline-flex items-center leading-normal select-all"
                title="Chiave protetta"
              >
                {primaryMaskedDisplay}
              </span>

              {hasProtectedKey && !apiKey && (
                <span
                  className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-[var(--bg-hover)] text-[var(--success-text)] border border-[var(--border-default)] inline-flex items-center gap-1 leading-normal"
                  title="Credenziale cifrata dal sistema operativo (DPAPI su Windows, Keychain su macOS)"
                >
                  <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
                  <span>Protetta</span>
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {renderCredentialStatusBadge(primaryCred, true, apiKey)}

              <div onClick={e => e.stopPropagation()}>
                <KebabMenu
                  items={primaryKebabItems}
                  ariaLabel="Opzioni chiave principale"
                  title="Opzioni chiave principale"
                />
              </div>
            </div>
          </div>
        ) : null}

        {/* Rows 2..N: Fallback Keys */}
        {cleanedFallbackKeys.map((key, idx) => {
          const rowId = `fallback-${key}`;
          const masked = `...${key.slice(-4)}`;
          const cred = getCredentialFor(key, false, idx);
          const label = `Chiave Riserva ${idx + 1}`;

          const fallbackKebabItems: KebabMenuItem[] = [
            {
              label: 'Imposta come principale',
              icon: <Star className="w-3.5 h-3.5" />,
              onClick: () => handlePromoteToPrimary(idx),
            },
            {
              label: 'Sposta su di priorità',
              icon: <ArrowUp className="w-3.5 h-3.5" />,
              disabled: idx === 0,
              onClick: () => handleMoveUp(idx),
            },
            {
              label: 'Sposta giù di priorità',
              icon: <ArrowDown className="w-3.5 h-3.5" />,
              disabled: idx === cleanedFallbackKeys.length - 1,
              onClick: () => handleMoveDown(idx),
            },
            { separator: true as const },
            {
              label: copiedKeyId === rowId ? 'Chiave copiata!' : 'Copia chiave',
              icon: copiedKeyId === rowId ? <Check className="w-3.5 h-3.5 text-[var(--success-text)]" /> : <Copy className="w-3.5 h-3.5" />,
              onClick: () => handleCopyKey(key, rowId),
            },
            { separator: true as const },
            {
              label: 'Rimuovi chiave',
              icon: <Trash2 className="w-3.5 h-3.5" />,
              danger: true,
              onClick: () =>
                requestDeleteKey({
                  type: 'fallback',
                  index: idx,
                  label,
                  maskedKey: masked,
                }),
            },
          ];

          return (
            <div
              key={`${key}-${idx}`}
              className="py-2 px-3.5 flex items-center justify-between gap-2.5 text-xs"
            >
              <div className="flex items-center gap-2 min-w-0 flex-wrap">
                <span className="font-bold text-[var(--text-primary)]">{label}</span>

                <span
                  className="px-2.5 py-0.5 rounded-full bg-[var(--bg-hover)] border border-[var(--border-default)] font-mono text-[11px] text-[var(--text-primary)] font-semibold inline-flex items-center leading-normal select-all"
                  title="Chiave protetta"
                >
                  {masked}
                </span>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {renderCredentialStatusBadge(cred, false, key)}

                <div onClick={e => e.stopPropagation()}>
                  <KebabMenu
                    items={fallbackKebabItems}
                    ariaLabel={`Opzioni ${label}`}
                    title={`Opzioni ${label}`}
                  />
                </div>
              </div>
            </div>
          );
        })}

        {/* Empty state inside the card table */}
        {totalKeysCount === 0 && (
          <div className="p-6 text-center text-xs text-[var(--text-secondary)] space-y-1">
            <p className="font-semibold text-[var(--text-primary)]">Nessuna chiave API configurata</p>
            <p>Inserisci la tua prima chiave API nel campo qui sopra per abilitare le trascrizioni.</p>
          </div>
        )}
      </div>

      {/* 4. Quiet Footer Caption with AI Studio link */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--text-secondary)] leading-relaxed">
        <span>Le chiavi di riserva subentrano in ordine quando la principale esaurisce la quota giornaliera.</span>
        <a
          href="https://aistudio.google.com/apikey"
          target="_blank"
          rel="noopener noreferrer"
          onClick={e => {
            e.preventDefault();
            window.pywebview?.api?.open_url?.('https://aistudio.google.com/apikey');
          }}
          className="font-medium underline hover:text-[var(--text-primary)] inline-flex items-center gap-1 cursor-pointer text-[var(--accent-text)] shrink-0"
        >
          <span>Ottieni gratis su aistudio.google.com</span>
          <ExternalLink className="w-3 h-3 shrink-0" />
        </a>
      </div>

      <QuotasSection
        apiUsage={apiUsage}
        isLoadingUsage={isLoadingUsage}
        preferredModel={preferredModel}
      />

      {/* 5. Delete Confirmation Dialog (fallback for standalone rendering) */}
      {!onAskDeleteKey && (
        <ConfirmActionModal
          isOpen={Boolean(deleteTarget)}
          title="Rimuovi chiave API"
          description={
            deleteTarget?.type === 'primary'
              ? cleanedFallbackKeys.length > 0
                ? `Sei sicuro di voler rimuovere la Chiave Principale (${deleteTarget.maskedKey})? La Chiave Riserva 1 verrà promossa automaticamente a nuova chiave principale.`
                : `Sei sicuro di voler rimuovere la Chiave Principale (${deleteTarget?.maskedKey})? Non sarà più possibile eseguire trascrizioni fino all'inserimento di una nuova chiave.`
              : `Sei sicuro di voler rimuovere ${deleteTarget?.label || 'questa chiave di riserva'} (${deleteTarget?.maskedKey})?`
          }
          confirmLabel="Rimuovi"
          cancelLabel="Annulla"
          onClose={() => setDeleteTarget(null)}
          onConfirm={handleConfirmDelete}
        />
      )}
    </div>
  );
});

ApiKeySection.displayName = 'ApiKeySection';
