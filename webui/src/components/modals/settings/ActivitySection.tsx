import { Activity, Layers } from 'lucide-react';
import type { ApiUsageResult } from '../../../bridge';

interface ActivitySectionProps {
  apiUsage?: ApiUsageResult | null;
  isLoadingUsage?: boolean;
  onRetry: () => void;
}

export function ActivitySection({ apiUsage, isLoadingUsage, onRetry }: ActivitySectionProps) {
  return (
    <div className="space-y-3" aria-busy={isLoadingUsage}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">
          <Activity className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
          Attività di oggi
        </h3>
      </div>

      {isLoadingUsage && <p role="status" className="text-xs text-[var(--text-secondary)] mt-3">Aggiornamento attività…</p>}
      {!isLoadingUsage && !apiUsage && <div className="flex items-center justify-between gap-3">
        <p role="status" className="text-xs text-[var(--text-secondary)]">Attività non disponibile.</p>
        <button type="button" onClick={onRetry} className="app-button-secondary is-settings-action">Riprova</button>
      </div>}
      {apiUsage && <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Card 1: Work Done */}
        <div className="premium-panel p-3.5 space-y-2">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
            <span className="text-[11px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
              Trascrizioni
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 pt-1 border-t border-[var(--border-default)] text-center">
            <div>
              <span className="text-lg font-bold text-[var(--text-primary)] block">
                {apiUsage?.work_stats?.chunks_completed ?? 0}
              </span>
              <span className="text-xs text-[var(--text-secondary)] font-medium">
                Segmenti
              </span>
            </div>
            <div>
              <span className="text-lg font-bold text-[var(--text-primary)] block">
                {apiUsage?.work_stats?.revisions_completed ?? 0}
              </span>
              <span className="text-xs text-[var(--text-secondary)] font-medium">
                Revisioni
              </span>
            </div>
            <div>
              <span className="text-lg font-bold text-[var(--text-primary)] block">
                {apiUsage?.work_stats?.sbobine_completed ?? 0}
              </span>
              <span className="text-xs text-[var(--text-secondary)] font-medium">
                Sbobine
              </span>
            </div>
          </div>
        </div>

        {/* Card 2: Telemetry API */}
        <div className="premium-panel p-3.5 space-y-2">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
            <span className="text-[11px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
              Chiamate API
            </span>
          </div>
          <div className="grid grid-cols-2 min-[1100px]:grid-cols-4 gap-x-3 gap-y-2 pt-1 border-t border-[var(--border-default)] text-center">
            <div>
              <span className="text-lg font-bold text-[var(--text-primary)] block">
                {apiUsage?.telemetry?.requests_sent ?? 0}
              </span>
              <span className="text-xs text-[var(--text-secondary)] font-medium truncate block">
                Inviate
              </span>
            </div>
            <div>
              <span className="text-lg font-bold text-[var(--success-text)] block">
                {apiUsage?.telemetry?.responses_succeeded ?? 0}
              </span>
              <span className="text-xs text-[var(--text-secondary)] font-medium truncate block">
                Successi
              </span>
            </div>
            <div>
              <span className="text-lg font-bold text-[var(--warning-text)] block">
                {apiUsage?.telemetry?.retries_total ?? 0}
              </span>
              <span className="text-xs text-[var(--text-secondary)] font-medium block" tabIndex={0} title="Richieste ripetute automaticamente.">
                Ritentativi
              </span>
            </div>
            <div>
              <span
                className={`text-lg font-bold block ${
                  (apiUsage?.telemetry?.final_failures ?? 0) > 0
                    ? 'text-[var(--error-text)]'
                    : 'text-[var(--text-secondary)]'
                }`}
              >
                {apiUsage?.telemetry?.final_failures ?? 0}
              </span>
              <span className="text-xs text-[var(--text-secondary)] font-medium block" tabIndex={0} title="Chiamate non recuperate con i ritentativi. Non indica il numero di sbobine fallite.">
                Fallite
              </span>
            </div>
          </div>
        </div>
      </div>}
    </div>
  );
}
