import { useState } from 'react';
import { motion } from 'motion/react';
import { AlertCircle, ArrowRight, CheckCircle2, ExternalLink, Eye, EyeOff, Key, Lightbulb, Loader2 } from 'lucide-react';
import type { CredentialStorage } from '../bridge';
import { GEMINI_KEY_PATTERN } from '../utils';
import { Wordmark } from './brand/Wordmark';
import { MASCOT } from './brand/mascot';

interface SetupPageProps {
  hasProtectedKey: boolean;
  onSaved: (key: string, model?: string, storage?: CredentialStorage, legacyPlaintext?: boolean, fallbackModels?: string[]) => void;
  preferredModel: string;
  fallbackKeys: string[];
  fallbackModels: string[];
}

export function SetupPage({
  hasProtectedKey,
  onSaved,
  preferredModel,
  fallbackKeys,
  fallbackModels,
}: SetupPageProps) {
  const [setupKeyInput, setSetupKeyInput] = useState('');
  const [setupKeyShowRaw, setSetupKeyShowRaw] = useState(false);
  const [setupKeySaving, setSetupKeySaving] = useState(false);
  const [setupKeyError, setSetupKeyError] = useState<string | null>(null);
  const [setupStep, setSetupStep] = useState<string | null>(null);

  const trimmedKey = setupKeyInput.trim();
  const isValidFormat = GEMINI_KEY_PATTERN.test(trimmedKey);
  const canSave = trimmedKey.length > 0 && isValidFormat && !setupKeySaving;

  const handleSetupSave = async () => {
    if (setupKeySaving) return;
    setSetupKeySaving(true);
    setSetupKeyError(null);
    try {
      if (!window.pywebview?.api?.save_settings) {
        setSetupKeyError('Bridge Python non disponibile — impostazioni non salvate.');
        return;
      }

      let activeModel = preferredModel;
      let activeFallbacks = fallbackModels;
      let autoPicked = false;

      // 1. Pick the newest model this key can use, plus fallbacks (no quota used)
      if (window.pywebview?.api?.recommend_models) {
        setSetupStep('Scelgo il modello migliore per la tua chiave…');
        try {
          const rec = await window.pywebview.api.recommend_models(trimmedKey);
          if (rec?.ok && rec.preferred_model) {
            activeModel = rec.preferred_model;
            activeFallbacks = rec.fallback_models ?? [];
            autoPicked = true;
          } else if (rec && !rec.ok && rec.error) {
            setSetupKeyError(rec.error);
            return;
          }
        } catch (recErr: unknown) {
          console.warn('Automatic model choice skipped:', recErr);
        }
      }

      // 2. Live key and model validation if validate_environment is available
      if (!autoPicked && window.pywebview?.api?.validate_environment) {
        try {
          const valRes = await window.pywebview.api.validate_environment(
            trimmedKey,
            true,
            activeModel,
            fallbackModels,
          );
          if (valRes?.result?.checks) {
            const apiCheck = valRes.result.checks.find(c => c.id === 'api_key');
            if (apiCheck && apiCheck.status === 'error') {
              const details = (apiCheck.details || '').toLowerCase();
              const isNotFound =
                details.includes('404') ||
                details.includes('not_found') ||
                details.includes('not found');

              // If the chosen model is not available for this project, try auto-fallback to gemini-3.5-flash
              if (isNotFound && activeModel !== 'gemini-3.5-flash') {
                try {
                  const retryVal = await window.pywebview.api.validate_environment(
                    trimmedKey,
                    true,
                    'gemini-3.5-flash',
                    fallbackModels,
                  );
                  const retryCheck = retryVal?.result?.checks?.find(c => c.id === 'api_key');
                  if (retryCheck && retryCheck.status === 'ok') {
                    activeModel = 'gemini-3.5-flash';
                  } else {
                    setSetupKeyError(
                      `I modelli Gemini predefiniti non sono disponibili per questo progetto Google Cloud con la chiave inserita.`
                    );
                    return;
                  }
                } catch {
                  setSetupKeyError(
                    `Il modello ${activeModel} non è disponibile per questo progetto Google Cloud.`
                  );
                  return;
                }
              } else {
                setSetupKeyError(apiCheck.message || 'Chiave API non valida o non attiva.');
                return;
              }
            }
          }
        } catch (valErr: unknown) {
          console.warn('Live API validation skipped or failed:', valErr);
        }
      }

      setSetupStep('Salvo le impostazioni…');
      let result;
      try {
        result = await window.pywebview.api.save_settings(
          trimmedKey,
          fallbackKeys,
          activeModel,
          activeFallbacks,
        );
      } catch (e: unknown) {
        setSetupKeyError(`Errore salvataggio: ${e instanceof Error ? e.message : String(e)}`);
        return;
      }
      if (!result?.ok) {
        setSetupKeyError(`Errore salvataggio: ${result?.error || 'errore sconosciuto'}`);
        return;
      }
      if (autoPicked) {
        onSaved(trimmedKey, activeModel, result.credential_storage, result.api_key_insecure, activeFallbacks);
      } else if (result.api_key_insecure !== undefined) {
        onSaved(trimmedKey, activeModel, result.credential_storage, result.api_key_insecure);
      } else if (result.credential_storage) {
        onSaved(trimmedKey, activeModel, result.credential_storage);
      } else {
        onSaved(trimmedKey, activeModel);
      }
    } finally {
      setSetupKeySaving(false);
      setSetupStep(null);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="w-full max-w-2xl mx-auto"
    >
      {/* Document Header */}
      <div className="space-y-3 text-left">
        <div className="flex items-end gap-4">
          <img
            src={MASCOT.pencil}
            alt=""
            className="w-28 h-auto object-contain select-none pointer-events-none"
            draggable={false}
          />
          <Wordmark className="setup-wordmark" />
        </div>
        <div className="space-y-1.5">
          <h1 className="text-[1.75rem] font-semibold tracking-tight leading-tight text-[var(--text-primary)] font-display">
            {hasProtectedKey ? 'Chiave API non accessibile' : 'Configura la tua API Key'}
          </h1>
          <p className="text-base leading-relaxed text-[var(--text-muted)]">
            {hasProtectedKey
              ? 'La tua chiave era salvata ma non è accessibile (errore di sistema). Reinseriscila per continuare.'
              : 'jot usa Google Gemini per trasformare le lezioni in appunti. Incolla una chiave gratuita: al resto (modello, riserve) pensa da solo.'}
          </p>
        </div>
      </div>

      {/* Main Setup Section */}
      <div className="mt-5 space-y-1.5">
        <div className="space-y-1.5">
          <label
            htmlFor="gemini-setup-api-key"
            className="text-xs font-semibold text-[var(--text-secondary)] flex items-center gap-1.5 select-none"
          >
            <Key className="w-3.5 h-3.5 text-[var(--accent-text)]" />
            <span>Chiave API Gemini</span>
          </label>

          <div className="flex items-center gap-2.5">
            <div className="relative flex-1">
              <input
                id="gemini-setup-api-key"
                type="text"
                data-masked={!setupKeyShowRaw ? 'true' : 'false'}
                value={setupKeyInput}
                onChange={e => setSetupKeyInput(e.target.value)}
                onKeyDown={async e => {
                  if (e.key !== 'Enter') return;
                  if (!GEMINI_KEY_PATTERN.test(setupKeyInput.trim())) return;
                  if (setupKeySaving) return;
                  await handleSetupSave();
                }}
                placeholder="Incolla qui la tua API Key (AIzaSy... o AQ...)"
                autoComplete="off"
                data-lpignore="true"
                data-1p-ignore="true"
                data-form-type="other"
                spellCheck={false}
                autoCorrect="off"
                autoCapitalize="off"
                className={`app-input w-full h-[42px] font-mono text-sm !pl-3.5 !pr-12 !py-2.5 rounded-lg border outline-none bg-[var(--bg-input)] text-[var(--text-primary)] transition-all duration-150 ${
                  !setupKeyShowRaw ? 'obscured-text' : ''
                } ${
                  trimmedKey && isValidFormat
                    ? 'border-[var(--success-ring)] focus:border-[var(--success-text)] focus:ring-2 focus:ring-[var(--success-ring)]'
                    : trimmedKey
                      ? 'border-[var(--warning-ring)] focus:border-[var(--warning-text)] focus:ring-2 focus:ring-[var(--warning-ring)]'
                      : 'border-[var(--border-default)] hover:border-[var(--border-strong)] focus:border-[var(--accent-bg)] focus:ring-2 focus:ring-[var(--accent-ring)]'
                }`}
              />
              <button
                type="button"
                onClick={() => setSetupKeyShowRaw(v => !v)}
                tabIndex={-1}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 z-10 p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors cursor-pointer"
                aria-label={setupKeyShowRaw ? 'Nascondi chiave' : 'Mostra chiave'}
              >
                {setupKeyShowRaw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>

            <button
              type="button"
              disabled={!canSave}
              onClick={handleSetupSave}
              className={`shrink-0 h-[42px] min-w-[175px] px-4 rounded-lg font-semibold text-sm inline-flex items-center justify-center gap-2 transition-all duration-150 select-none whitespace-nowrap border ${
                canSave
                  ? 'border-transparent bg-[var(--btn-primary-bg)] text-[var(--btn-primary-text)] hover:bg-[var(--btn-primary-hover)] active:scale-[0.98] cursor-pointer'
                  : 'border-[var(--border-default)] bg-[var(--bg-panel)] text-[var(--text-muted)] cursor-not-allowed opacity-80'
              }`}
            >
              {setupKeySaving ? (
                <Loader2 className="w-4 h-4 animate-spin shrink-0" />
              ) : (
                <ArrowRight className={`w-4 h-4 shrink-0 transition-transform ${canSave ? 'translate-x-0.5' : ''}`} />
              )}
              <span>{setupKeySaving ? 'Verifica e salvataggio…' : 'Salva e inizia'}</span>
            </button>
          </div>
        </div>

        {trimmedKey ? (
          <div
            className={`flex items-center gap-1.5 text-xs font-medium transition-opacity ${
              isValidFormat ? 'text-[var(--success-text)]' : 'text-[var(--warning-text)]'
            }`}
          >
            {isValidFormat ? (
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
            ) : (
              <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            )}
            <span className="truncate">
              {isValidFormat
                ? 'Formato valido — premi Salva per continuare'
                : 'Formato non valido — le chiavi iniziano con AIzaSy... o AQ.'}
            </span>
          </div>
        ) : null}

        {setupKeySaving && setupStep && (
          <p className="text-xs font-semibold text-[var(--text-muted)]" aria-live="polite">{setupStep}</p>
        )}

        {setupKeyError && (
          <div className="alert-card is-error text-xs flex items-center gap-2 py-2 px-3 mt-1.5">
            <AlertCircle className="w-4 h-4 shrink-0 text-[var(--error-text)]" />
            <span className="text-[var(--error-text)] leading-snug">{setupKeyError}</span>
          </div>
        )}
      </div>

      {/* Callout Guide */}
      <div className="mt-2.5 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-default)] p-4 sm:p-5 text-left space-y-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-[var(--text-primary)]">
          <Lightbulb className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
          <span>Come ottenere la chiave in 1 minuto</span>
        </div>
        <ol className="flex flex-col gap-2.5 text-xs text-[var(--text-secondary)]">
          <li className="flex items-start gap-3">
            <span className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full bg-[var(--bg-panel)] border border-[var(--border-subtle)] text-[11px] font-semibold text-[var(--text-muted)] mt-0.5">
              1
            </span>
            <span className="leading-snug pt-0.5">
              Vai su{' '}
              <a
                href="https://aistudio.google.com/apikey"
                onClick={e => {
                  e.preventDefault();
                  window.pywebview?.api?.open_url?.('https://aistudio.google.com/apikey');
                }}
                className="font-medium text-[var(--accent-text)] hover:underline inline-flex items-center gap-0.5"
              >
                <span>aistudio.google.com/apikey</span>
                <ExternalLink className="w-3 h-3 shrink-0" />
              </a>
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full bg-[var(--bg-panel)] border border-[var(--border-subtle)] text-[11px] font-semibold text-[var(--text-muted)] mt-0.5">
              2
            </span>
            <span className="leading-snug pt-0.5">
              Clicca <strong className="font-semibold text-[var(--text-primary)]">&quot;Create API key&quot;</strong> e copia la chiave
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full bg-[var(--bg-panel)] border border-[var(--border-subtle)] text-[11px] font-semibold text-[var(--text-muted)] mt-0.5">
              3
            </span>
            <span className="leading-snug pt-0.5">
              Incollala nel campo qui sopra e premi <strong className="font-semibold text-[var(--text-primary)]">Salva e inizia</strong>
            </span>
          </li>
        </ol>
      </div>
    </motion.div>
  );
}
