import { memo, useEffect, useRef, useState } from 'react';
import type React from 'react';
import { motion } from 'motion/react';
import {
  AudioLines,
  CheckCircle,
  FileDown,
  Loader,
  Mic,
  Pause,
  Sparkles,
  WifiOff,
  XCircle,
} from 'lucide-react';
import { shortModelName } from '../utils';
import type { AppStatus } from '../appState';
import { ProgressDial, QuotaDial } from './lesson/Dial';

interface ProcessingStatusBannerProps {
  appState: AppStatus;
  currentPhase: string;
  currentModel: string;
  activeProgress: number;
  workDone: { chunks: number; macro: number };
  workTotals: { chunks: number; macro: number };
  currentFileIndex: number;
  currentBatchTotal: number;
  currentFileName?: string;
  startedAt?: number;
  /** "notes" = Slide e appunti job: different step names/descriptions. */
  mode?: 'audio' | 'notes';
  /** Documents attached to the job, used by the live explanation. */
  sources?: { slides?: boolean; book?: boolean };
  /** Requests used today (small dial). */
  quota?: { used: number; limit: number } | null;
}

type PhaseInfo = {
  icon: React.ReactElement;
  iconAnimation: 'spin' | 'pulse' | 'none';
  title: string;
  description: string;
  kind: 'normal' | 'wait' | 'cancel' | 'success';
};

type StepState = 'done' | 'active' | 'pending';
type StepKey = 'preconversione' | 'trascrizione' | 'revisione';
type StepperState = Record<StepKey, StepState> | null;
type WorkKind = 'chunks' | 'macro';

const STEP_TOOLTIPS: Record<StepKey, string> = {
  preconversione: "Normalizza l'audio per renderlo più stabile e leggibile nelle fasi successive.",
  trascrizione: 'Il modello analizza i blocchi audio e genera la prima sbobinatura dettagliata.',
  revisione: "Il testo viene ripulito, organizzato e reso più chiaro sezione per sezione.",
};

const NOTES_STEP_TOOLTIPS: Record<StepKey, string> = {
  preconversione: 'Controlla slide e libro ed estrae le pagine del libro selezionate.',
  trascrizione: 'Il modello legge le slide a blocchi, le approfondisce con il libro e scrive gli appunti.',
  revisione: 'Gli appunti vengono ripuliti da ripetizioni e uniformati sezione per sezione.',
};

const STEP_LABELS: Record<'audio' | 'notes', Record<StepKey, string>> = {
  audio: { preconversione: 'Pre-conversione', trascrizione: 'Trascrizione', revisione: 'Revisione' },
  notes: { preconversione: 'Documenti', trascrizione: 'Appunti', revisione: 'Revisione' },
};

function getPhaseInfo(appState: AppStatus, currentPhase: string, mode: 'audio' | 'notes' = 'audio'): PhaseInfo {
  if (appState === 'canceling') {
    return {
      icon: <XCircle className="w-8 h-8" />,
      iconAnimation: 'none',
      title: 'Interruzione in corso...',
      description: "Attendere il completamento dell'operazione corrente prima di fermarsi.",
      kind: 'cancel',
    };
  }

  const phase = currentPhase.trim();

  if (!phase) {
    return {
      icon: <Loader className="w-8 h-8" />,
      iconAnimation: 'spin',
      title: 'Preparazione...',
      description: "Avvio dell'elaborazione in corso.",
      kind: 'normal',
    };
  }

  if (phase === '__completed__') {
    return {
      icon: <CheckCircle className="w-8 h-8" />,
      iconAnimation: 'none',
      title: mode === 'notes' ? 'Appunti completati!' : 'Sbobinatura completata!',
      description: 'Tutti i passaggi sono stati completati con successo.',
      kind: 'success',
    };
  }

  if (phase.startsWith('Fase 0/3: preparazione documenti')) {
    return {
      icon: <FileDown className="w-8 h-8" />,
      iconAnimation: 'pulse',
      title: 'Preparazione documenti',
      description: 'Controllo delle slide ed estrazione delle pagine del libro selezionate.',
      kind: 'normal',
    };
  }

  if (phase.startsWith('Fase 1/3: appunti')) {
    return {
      icon: <Sparkles className="w-8 h-8" />,
      iconAnimation: 'pulse',
      title: 'Generazione appunti',
      description: 'Gemini legge le slide a blocchi e scrive appunti completi, approfonditi con il libro.',
      kind: 'normal',
    };
  }

  if (phase.startsWith('Fase 0/3')) {
    return {
      icon: <AudioLines className="w-8 h-8" />,
      iconAnimation: 'pulse',
      title: 'Pre-conversione audio',
      description: "Conversione del file audio in un formato ottimizzato per l'elaborazione.",
      kind: 'normal',
    };
  }

  if (phase.startsWith('Fase 1/3')) {
    return {
      icon: <Mic className="w-8 h-8" />,
      iconAnimation: 'pulse',
      title: 'Trascrizione e sbobinatura',
      description: 'Gemini trascrive e sbobina ogni blocco audio in appunti dettagliati.',
      kind: 'normal',
    };
  }

  if (phase.startsWith('Fase 2/3')) {
    const isRetry = phase.includes('retry');
    return {
      icon: <Sparkles className="w-8 h-8" />,
      iconAnimation: 'pulse',
      title: isRetry ? 'Revisione blocchi mancanti' : 'Revisione e pulizia',
      description: isRetry ? phase : 'Il testo viene rivisto e ripulito da ripetizioni e imprecisioni.',
      kind: 'normal',
    };
  }

  if (phase.startsWith('Fase: esportazione') || phase.startsWith('Fase:esportazione')) {
    return {
      icon: <FileDown className="w-8 h-8" />,
      iconAnimation: 'pulse',
      title: 'Generazione output',
      description: 'Salvataggio del file HTML finale sul Desktop.',
      kind: 'normal',
    };
  }

  if (phase.startsWith('Server Gemini occupato')) {
    return {
      icon: <WifiOff className="w-8 h-8" />,
      iconAnimation: 'pulse',
      title: 'In attesa...',
      description: phase,
      kind: 'wait',
    };
  }

  if (phase.startsWith('Rate limit') || phase.includes('Rate limit')) {
    return {
      icon: <Pause className="w-8 h-8" />,
      iconAnimation: 'none',
      title: 'Pausa automatica',
      description: 'Limite richieste API raggiunto. Ripresa automatica tra qualche secondo.',
      kind: 'wait',
    };
  }

  return {
    icon: <Loader className="w-8 h-8" />,
    iconAnimation: 'spin',
    title: 'Elaborazione in corso',
    description: currentPhase,
    kind: 'normal',
  };
}

function getStepperState(currentPhase: string): StepperState {
  const phase = currentPhase.trim();
  if (phase === '__completed__' || phase.startsWith('Fase: esportazione') || phase.startsWith('Fase:esportazione')) {
    return { preconversione: 'done', trascrizione: 'done', revisione: 'done' };
  }
  if (phase.startsWith('Fase 0/3')) {
    return { preconversione: 'active', trascrizione: 'pending', revisione: 'pending' };
  }
  if (phase.startsWith('Fase 1/3')) {
    return { preconversione: 'done', trascrizione: 'active', revisione: 'pending' };
  }
  if (phase.startsWith('Fase 2/3')) {
    return { preconversione: 'done', trascrizione: 'done', revisione: 'active' };
  }
  return null;
}

function parseCurrentIndex(phase: string, stage: WorkKind): { current: number; total: number } | null {
  if (stage === 'chunks') {
    const match = phase.match(/chunk\s+(\d+)\s*\/\s*(\d+)/i);
    if (match) {
      return { current: Number(match[1]), total: Number(match[2]) };
    }
  }

  if (stage === 'macro' && phase.startsWith('Fase 2/3')) {
    const match = phase.match(/\((?:blocco\s+)?(\d+)\s*\/\s*(\d+)\)/i);
    if (match) {
      return { current: Number(match[1]), total: Number(match[2]) };
    }
  }

  return null;
}

function getActiveStepIndex(done: number, total: number): number {
  if (total <= 0) return 0;
  if (done >= total) return total;
  return Math.min(total, Math.max(1, done + 1));
}

function getProgressLabel(
  currentPhase: string,
  workDone: { chunks: number; macro: number },
  workTotals: { chunks: number; macro: number },
): string | null {
  const phase = currentPhase.trim();

  const chunkInfo = parseCurrentIndex(phase, 'chunks');
  if (chunkInfo) return `Blocco ${chunkInfo.current} di ${chunkInfo.total}`;
  if (phase.startsWith('Fase 1/3') && workTotals.chunks > 0) {
    return `Blocco ${getActiveStepIndex(workDone.chunks, workTotals.chunks)} di ${workTotals.chunks}`;
  }

  const macroInfo = parseCurrentIndex(phase, 'macro');
  const macroCurrentNum = macroInfo
    ? macroInfo.current
    : getActiveStepIndex(workDone.macro, workTotals.macro);
  const macroTotalNum = macroInfo ? macroInfo.total : workTotals.macro;

  if (phase.startsWith('Fase 2/3') && macroTotalNum > 0) {
    return `Sezione ${macroCurrentNum} di ${macroTotalNum}`;
  }

  return null;
}



function formatElapsed(secs: number): string {
  if (secs < 60) return `Da ${secs}s`;
  const minutes = Math.floor(secs / 60);
  const remainingSeconds = secs % 60;
  if (minutes < 60) return `Da ${minutes}m ${remainingSeconds < 10 ? '0' : ''}${remainingSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `Da ${hours}h ${remainingMinutes}m`;
}

/** Minutes of audio covered by a 15-minute block (30 s overlap). */
function blockMinutes(index: number): string {
  const step = 14.5;
  const from = Math.max(0, Math.floor((index - 1) * step));
  const to = Math.floor((index - 1) * step + 15);
  return `${from}–${to}`;
}

function explainPhase(
  appState: AppStatus,
  currentPhase: string,
  mode: 'audio' | 'notes',
  sources: { slides?: boolean; book?: boolean },
  workDone: { chunks: number; macro: number },
  workTotals: { chunks: number; macro: number },
): string {
  const phase = currentPhase.trim();
  if (appState === 'canceling') return 'Finisco il passaggio in corso e mi fermo. Quello che è già fatto resta salvato.';
  if (!phase) return 'Sto preparando i file.';
  if (phase === '__completed__') {
    return mode === 'notes'
      ? 'Fatto. Apri gli appunti dall’elenco qui sotto.'
      : 'Fatto. Apri gli appunti e rileggili ascoltando l’audio nel lettore integrato.';
  }
  if (phase.startsWith('Server Gemini occupato')) return 'I server di Google sono occupati. Riprovo da solo tra pochi secondi, non devi fare nulla.';
  if (phase.includes('Rate limit')) return 'Ho raggiunto il limite di richieste al minuto. Riparto da solo tra poco.';
  if (phase.startsWith('Fase 0/3: preparazione documenti')) return 'Controllo le slide e preparo le pagine del libro.';
  if (phase.startsWith('Fase 0/3')) return 'Converto l’audio in un formato leggero, così ogni blocco parte più in fretta.';
  if (phase.startsWith('Fase 1/3')) {
    const chunk = phase.match(/chunk\s+(\d+)\s*\/\s*(\d+)/i);
    const current = chunk ? Number(chunk[1]) : getActiveStepIndex(workDone.chunks, workTotals.chunks);
    if (mode === 'notes') {
      return sources.book
        ? `Leggo il blocco ${current || 1} di slide e scrivo gli appunti, aiutandomi con il libro.`
        : `Leggo il blocco ${current || 1} di slide e scrivo gli appunti.`;
    }
    const base = `Ascolto i minuti ${blockMinutes(current || 1)} e scrivo gli appunti.`;
    return sources.slides ? `${base} Le slide mi aiutano con termini e formule.` : base;
  }
  if (phase.startsWith('Fase 2/3')) {
    if (phase.includes('retry')) return 'Rileggo le parti che prima non erano state revisionate.';
    return sources.book
      ? 'Rileggo gli appunti, tolgo le ripetizioni e chiarisco i passaggi difficili con il libro.'
      : 'Rileggo gli appunti e tolgo ripetizioni e imprecisioni.';
  }
  if (phase.startsWith('Fase: esportazione') || phase.startsWith('Fase:esportazione')) return 'Impagino gli appunti e li salvo.';
  return phase;
}

function StepBadge({ state, label, tooltip }: { state: StepState; label: string; tooltip: string }) {
  return (
    <span className={`process-step is-${state}`} tabIndex={0} aria-label={`${label}. ${tooltip}`}>
      <span className="process-step-dot" aria-hidden="true" />
      <span className="process-step-label">{label}</span>
      <span role="tooltip" className="process-step-tooltip">{tooltip}</span>
    </span>
  );
}

export const ProcessingStatusBanner = memo(function ProcessingStatusBanner({
  appState,
  currentPhase,
  currentModel,
  activeProgress,
  workDone,
  workTotals,
  currentFileIndex,
  currentBatchTotal,
  currentFileName,
  startedAt,
  mode = 'audio',
  sources = {},
  quota = null,
}: ProcessingStatusBannerProps) {
  const { title, kind } = getPhaseInfo(appState, currentPhase, mode);
  const stepLabels = STEP_LABELS[mode];
  const stepTooltips = mode === 'notes' ? NOTES_STEP_TOOLTIPS : STEP_TOOLTIPS;
  const isCanceling = appState === 'canceling';
  const isWaiting = kind === 'wait';

  const lastNormalPhaseRef = useRef('');
  if (kind === 'normal') lastNormalPhaseRef.current = currentPhase;
  const phaseForMeta = isWaiting ? lastNormalPhaseRef.current : currentPhase;

  const stepperState = getStepperState(phaseForMeta);
  const progressLabel = getProgressLabel(phaseForMeta, workDone, workTotals);
  const explanation = explainPhase(appState, isWaiting ? currentPhase : phaseForMeta, mode, sources, workDone, workTotals);

  const [elapsedSecs, setElapsedSecs] = useState(0);
  useEffect(() => {
    if (!startedAt) return;
    const update = () => setElapsedSecs(Math.floor((Date.now() - startedAt) / 1000));
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  const phase = phaseForMeta.trim();
  const isDone = kind === 'success';
  const inRevision = phase.startsWith('Fase 2/3') || phase.startsWith('Fase: esportazione') || phase.startsWith('Fase:esportazione');
  const inTranscription = phase.startsWith('Fase 1/3');
  const chunkInfo = parseCurrentIndex(phase, 'chunks');
  const macroInfo = parseCurrentIndex(phase, 'macro');

  let dial: React.ComponentProps<typeof ProgressDial>;
  const tone: 'accent' | 'ink' | 'muted' = isCanceling || isWaiting ? 'muted' : inRevision || isDone ? 'ink' : 'accent';
  if (isDone) {
    const total = Math.max(1, workTotals.chunks || 1);
    dial = { total, done: total, active: 0, tone, overline: 'Pronti', big: '✓', caption: startedAt && elapsedSecs > 0 ? `In ${Math.max(1, Math.round(elapsedSecs / 60))} minuti` : undefined, ariaLabel: 'Elaborazione completata' };
  } else if (inRevision) {
    const total = macroInfo?.total || workTotals.macro || 1;
    const current = macroInfo?.current || getActiveStepIndex(workDone.macro, total) || 1;
    dial = { total, done: Math.min(workDone.macro, total), active: current, tone, overline: 'Revisione', big: String(current), suffix: ` / ${total}`, caption: 'Rilettura', ariaLabel: `Revisione: sezione ${current} di ${total}` };
  } else if (inTranscription) {
    const total = chunkInfo?.total || workTotals.chunks || 1;
    const current = chunkInfo?.current || getActiveStepIndex(workDone.chunks, total) || 1;
    dial = { total, done: Math.min(workDone.chunks, total), active: current, tone, overline: 'Blocco', big: String(current), suffix: ` / ${total}`, caption: mode === 'notes' ? 'Scrittura' : 'Trascrizione', ariaLabel: `Trascrizione: blocco ${current} di ${total}` };
  } else {
    const total = Math.max(1, workTotals.chunks || 1);
    dial = { total, done: 0, active: 0, tone, overline: 'Preparazione', big: String(Math.max(0, Math.round(activeProgress))), suffix: '%', ariaLabel: `Preparazione: ${activeProgress}%` };
  }

  const metaChips: string[] = [];
  if (currentModel && !isDone) metaChips.push(shortModelName(currentModel));
  if (currentBatchTotal > 1) metaChips.push(`File ${currentFileIndex + 1} di ${currentBatchTotal}`);
  if (startedAt && elapsedSecs > 0 && !isDone) metaChips.push(formatElapsed(elapsedSecs));
  if (progressLabel) metaChips.push(progressLabel);

  const sourceLine = [mode === 'notes' ? null : 'Audio', sources.slides || mode === 'notes' ? 'Slide' : null, sources.book ? 'Libro' : null]
    .filter(Boolean)
    .join(' · ');

  return (
    <motion.section
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
      className={`processing-view kind-${kind}${isCanceling ? ' is-canceling' : ''}`}
      aria-label="Stato elaborazione"
    >
      <div className="processing-head">
        {currentFileName && (
          <h2 className="processing-title" title={currentFileName}>{currentFileName}</h2>
        )}
        {sourceLine && <span className="processing-sources">{sourceLine}</span>}
      </div>

      <div className="processing-dials">
        <ProgressDial {...dial} />
        {quota && <QuotaDial used={quota.used} limit={quota.limit} />}
      </div>

      <div className="processing-explain" aria-live="polite" aria-label="Cosa sta succedendo">
        <span className="processing-step-name">
          <span className="processing-dot" aria-hidden="true" />
          {title}
        </span>
        <p className="processing-text">{explanation}</p>
      </div>

      {stepperState && (
        <div className="process-steps">
          <StepBadge state={stepperState.preconversione} label={stepLabels.preconversione} tooltip={stepTooltips.preconversione} />
          <StepBadge state={stepperState.trascrizione} label={stepLabels.trascrizione} tooltip={stepTooltips.trascrizione} />
          <StepBadge state={stepperState.revisione} label={stepLabels.revisione} tooltip={stepTooltips.revisione} />
        </div>
      )}

      {metaChips.length > 0 && (
        <div className="processing-meta">
          {metaChips.map((label, index) => <span key={`${label}-${index}`}>{label}</span>)}
        </div>
      )}
    </motion.section>
  );
});
