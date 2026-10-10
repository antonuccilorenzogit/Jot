import { AlertCircle, Clock } from 'lucide-react';
import type { ApiUsageResult } from '../../../bridge';

interface ApiStatusSectionProps {
  apiUsage?: ApiUsageResult | null;
  isLoadingUsage?: boolean;
}

export function ApiStatusSection({ apiUsage, isLoadingUsage }: ApiStatusSectionProps) {
  const status = apiUsage?.primary_status;
  const hasCredentials = Boolean(apiUsage?.credentials?.length || apiUsage?.keys?.length);
  const ready = hasCredentials && (status === 'operational' || status === 'degraded');
  if (ready || (isLoadingUsage && !apiUsage)) return null;

  const title = !apiUsage ? 'Stato API non disponibile'
    : !hasCredentials ? 'Configura una chiave API'
    : status === 'rate_limited' ? 'In attesa: ripresa automatica'
    : status === 'quota_exhausted' ? 'Quota giornaliera esaurita'
    : status === 'credential_error' ? 'Verifica la chiave API'
    : 'Stato API da verificare';
  const description = !apiUsage ? 'Premi “Verifica connessione” per riprovare.'
    : !hasCredentials ? 'Inserisci una chiave nella sezione qui sotto.'
    : status === 'rate_limited' ? apiUsage.status_message || 'Il limite temporaneo richiede una pausa; il sistema riprova automaticamente.'
    : status === 'quota_exhausted' ? `${apiUsage.next_reset_info || 'Attendi il ripristino della quota.'} Puoi verificare altre chiavi o scegliere un altro modello in questa scheda.`
    : status === 'credential_error' ? 'Controlla la chiave e i permessi del progetto, poi premi “Verifica connessione”.'
    : null;
  const Icon = status === 'rate_limited' ? Clock : AlertCircle;

  return (
    <div className="premium-panel p-3.5 space-y-3">
      <div role="status" className="flex items-start gap-2.5">
        <Icon className="w-4 h-4 mt-0.5 shrink-0 text-[var(--text-secondary)]" />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-bold text-[var(--text-primary)]">{title}</p>
          {description && <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{description}</p>}
        </div>
      </div>

    </div>
  );
}
