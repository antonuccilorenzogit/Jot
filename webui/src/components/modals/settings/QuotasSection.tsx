import React, { useMemo } from 'react';
import {
  Clock,
  Loader2,
  Gauge,
  Sparkles,
  ChevronDown,
} from 'lucide-react';
import type { ApiUsageResult, CredentialProfile } from '../../../bridge';
import { getModelDisplayName, sortModelsByVersion, MODEL_ORDER } from '../../../utils';

interface QuotasSectionProps {
  apiUsage?: ApiUsageResult | null;
  isLoadingUsage?: boolean;
  preferredModel?: string;
}

export const QuotasSection: React.FC<QuotasSectionProps> = React.memo(
  ({
    apiUsage,
    isLoadingUsage,
    preferredModel = 'gemini-2.5-flash',
  }) => {
    const effectivePreferredModel = preferredModel || 'gemini-2.5-flash';

    const projectLimits = useMemo(
      () => apiUsage?.project_limits || {},
      [apiUsage?.project_limits]
    );

    // Get all supported models in version order
    const allKnownModels = useMemo(() => {
      const keys = Object.keys(projectLimits);
      const combined = Array.from(new Set([...MODEL_ORDER, ...keys]));
      return sortModelsByVersion(combined);
    }, [projectLimits]);

    const credentials: CredentialProfile[] = useMemo(() => {
      if (apiUsage?.credentials && apiUsage.credentials.length > 0) {
        return apiUsage.credentials;
      }
      return (apiUsage?.keys || []).map((k, idx) => ({
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
        exhausted_models: [],
      }));
    }, [apiUsage]);

    return (
      <div className="space-y-3 animate-fade-in">
        {/* Loading Spinner */}
        {isLoadingUsage ? (
          <div className="py-3 flex items-center justify-center gap-2 text-xs font-medium text-[var(--text-secondary)]">
            <Loader2 className="w-4 h-4 animate-spin text-[var(--accent-text)]" />
            Caricamento quote in corso…
          </div>
        ) : apiUsage && credentials.length > 0 ? (
          <>
            {/* 5. Panoramica Altri Modelli Supportati (Quote Separate) */}
            {allKnownModels.length > 0 && (
              <details className="settings-details is-api-quota">
                <summary>
                  <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider">
                    <Gauge className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
                    Quote per modello
                  </span>
                  <ChevronDown className="w-4 h-4 shrink-0" />
                </summary>

                <div className="flex items-start gap-1.5 text-xs text-[var(--text-secondary)]">
                  <Clock className="w-3.5 h-3.5 shrink-0" />
                  {apiUsage?.next_reset_info || 'Reset automatico alle 09:00 (ora italiana / 00:00 PT)'}
                </div>

                <div className="settings-details-content divide-y divide-[var(--border-default)]">
                  {allKnownModels.map(mName => {
                    const lim = projectLimits[mName];
                    const readyForM = credentials.filter(
                      c =>
                        c.operational_status !== 'invalid' &&
                        c.operational_status !== 'permission_denied' &&
                        !(c.exhausted_models || []).includes(mName)
                    ).length;

                    const allReady = readyForM === credentials.length;
                    const noneReady = readyForM === 0;

                    return (
                      <div
                        key={mName}
                        className="py-3 flex items-center justify-between gap-3 text-xs"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-bold text-[var(--text-primary)]">
                              {getModelDisplayName(mName)}
                            </span>
                            {mName === effectivePreferredModel && (
                              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--accent-subtle)] text-[var(--accent-text)] border border-[var(--accent-ring)] leading-normal shrink-0">
                                Selezionato
                              </span>
                            )}
                          </div>
                          <span className="text-[11px] text-[var(--text-secondary)] block">
                            {lim?.rpd_limit ? `${lim.rpd_limit} RPD` : '20 RPD standard'} •{' '}
                            {lim?.rpm_limit ? `${lim.rpm_limit} RPM` : '5 RPM'}
                          </span>
                        </div>

                        <div className="shrink-0">
                          {noneReady ? (
                            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--error-subtle,var(--bg-surface))] text-[var(--error-text)] border border-[var(--error-ring)] inline-flex items-center justify-center leading-normal">
                              0/{credentials.length} chiavi disponibili
                            </span>
                          ) : allReady ? (
                            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--bg-hover)] text-[var(--text-secondary)] border border-[var(--border-default)] inline-flex items-center justify-center leading-normal">
                              {credentials.length}/{credentials.length} chiavi disponibili
                            </span>
                          ) : (
                            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--warning-subtle,var(--bg-surface))] text-[var(--warning-text)] border border-[var(--warning-ring)] inline-flex items-center justify-center leading-normal">
                              {readyForM}/{credentials.length} chiavi disponibili
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                <p className="text-xs text-[var(--text-secondary)] flex items-start gap-1.5 pt-3">
                  <Sparkles className="w-3.5 h-3.5 text-[var(--accent-text)] shrink-0" />
                  <span>
                    RPD: richieste al giorno · RPM: richieste al minuto. Una chiave che ha esaurito la quota su un modello può essere ancora disponibile sugli altri.
                  </span>
                </p>
              </details>
            )}


          </>
        ) : (
          <div className="flex items-start gap-2 text-xs text-[var(--text-secondary)]">
            <Gauge className="w-4 h-4 shrink-0 mt-0.5" />
            <p className="leading-relaxed">
              Inserisci una chiave API in Generale per visualizzare lo stato delle quote e la disponibilità delle risorse.
            </p>
          </div>
        )}
      </div>
    );
  }
);

QuotasSection.displayName = 'QuotasSection';
