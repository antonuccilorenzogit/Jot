import { useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { AlertCircle, Info, X } from 'lucide-react';
import type { ArchiveSession } from '../../bridge';
import type { FileItem } from '../../appState';

export type AlreadyProcessedMatch =
  | { source: 'done'; existingFile: FileItem; incoming: FileItem }
  | { source: 'archive'; sessions: ArchiveSession[]; incoming: FileItem };

export type DuplicatePrompt =
  | { kind: 'in-queue'; filenames: string[] }
  | { kind: 'already-processed'; matches: AlreadyProcessedMatch[]; alsoInQueue?: string[] }
  | null;

interface DuplicateFileModalProps {
  prompt: DuplicatePrompt;
  onDismiss: () => void;
  onAddAgain: (matches: AlreadyProcessedMatch[]) => void;
}

export function DuplicateFileModal({ prompt, onDismiss, onAddAgain }: DuplicateFileModalProps) {
  useEffect(() => {
    if (!prompt) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onDismiss();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [prompt, onDismiss]);

  return (
    <AnimatePresence>
      {prompt && (
        <motion.div
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
        >
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="modal-overlay absolute inset-0"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1, transition: { duration: 0.18, ease: [0.22, 1, 0.36, 1] } }}
            exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.14, ease: 'easeIn' } }}
            className="modal-card relative w-full max-w-md max-h-[86vh] overflow-hidden flex flex-col"
          >
            {prompt.kind === 'in-queue' ? (
              <InQueueVariant filenames={prompt.filenames} onDismiss={onDismiss} />
            ) : (
              <AlreadyProcessedVariant
                matches={prompt.matches}
                alsoInQueue={prompt.alsoInQueue}
                onDismiss={onDismiss}
                onAddAgain={() => onAddAgain(prompt.matches)}
              />
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function InQueueVariant({ filenames, onDismiss }: { filenames: string[]; onDismiss: () => void }) {
  const count = filenames.length;
  return (
    <>
      <div className="modal-header">
        <div className="flex items-center gap-3 min-w-0">
          <Info className="w-5 h-5 shrink-0 text-[var(--text-muted)]" />
          <h2 className="text-lg font-semibold truncate text-[var(--text-primary)]">
            {count === 1 ? '1 file già in coda' : `${count} file già in coda`}
          </h2>
        </div>
        <button
          onClick={onDismiss}
          className="icon-button modal-icon-button"
          aria-label="Chiudi finestra"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="modal-body space-y-3">
        {count === 1 ? (
          <p>
            <strong className="text-[var(--text-primary)]">{filenames[0]}</strong> è già presente in coda e non è stato aggiunto di nuovo.
          </p>
        ) : (
          <>
            <p>{count} file sono già presenti in coda e non sono stati aggiunti di nuovo:</p>
            <ul className="space-y-1 pl-1">
              {filenames.map(name => (
                <li key={name} className="truncate text-[var(--text-primary)]">- {name}</li>
              ))}
            </ul>
          </>
        )}
      </div>
      <div className="modal-footer">
        <button onClick={onDismiss} className="modal-action-button flex-1">
          Chiudi
        </button>
      </div>
    </>
  );
}

function AlreadyProcessedVariant({
  matches,
  alsoInQueue,
  onDismiss,
  onAddAgain,
}: {
  matches: AlreadyProcessedMatch[];
  alsoInQueue?: string[];
  onDismiss: () => void;
  onAddAgain: () => void;
}) {
  const count = matches.length;
  const hasDone = matches.some(match => match.source === 'done');
  const hasArchive = matches.some(match => match.source === 'archive');
  const archiveSessionCount = matches.reduce(
    (total, match) => total + (match.source === 'archive' ? match.sessions.length : 0),
    0,
  );
  const archiveMatchCount = matches.filter(match => match.source === 'archive').length;
  const isMixed = hasDone && hasArchive;
  const subtitle = hasArchive && !hasDone ? 'Sbobina già completata in precedenza' : 'Sbobina già completata';
  const locationPhrase = isMixed
    ? ' in questa sessione o in sessioni precedenti'
    : hasDone
      ? ' in questa sessione'
      : ' in sessioni precedenti';
  const singleArchiveMatch = count === 1 && matches[0].source === 'archive' ? matches[0] : null;

  return (
    <>
      <div className="modal-header">
        <div className="flex items-center gap-3 min-w-0">
          <AlertCircle className="w-5 h-5 shrink-0 text-[var(--warning-text)]" />
          <h2 className="text-lg font-semibold truncate text-[var(--text-primary)]">
            {subtitle}
          </h2>
        </div>
        <button
          onClick={onDismiss}
          className="icon-button modal-icon-button"
          aria-label="Chiudi finestra"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="modal-body space-y-3">
        {count === 1 ? (
          <>
            <p>
              <strong className="text-[var(--text-primary)]">{matches[0].incoming.name}</strong> risulta già{' '}
              {singleArchiveMatch
                ? singleArchiveMatch.sessions.length === 1
                  ? 'elaborato in una sessione precedente'
                  : `elaborato in ${singleArchiveMatch.sessions.length} sessioni precedenti`
                : 'elaborato in questa sessione'}.
            </p>
            <p>Puoi tenere la versione già pronta oppure aggiungere il file di nuovo per rielaborarlo da zero.</p>
          </>
        ) : (
          <>
            <p>
              {count} file risultano già elaborati{locationPhrase}.
              Puoi tenerli oppure rielaborarli da zero.
            </p>
            {archiveSessionCount > archiveMatchCount && (
              <p>Ho trovato {archiveSessionCount} sessioni archiviate collegate a questi file.</p>
            )}
            <ul className="space-y-1 pl-1">
              {matches.map(match => (
                <li key={match.incoming.id} className="truncate text-[var(--text-primary)]">- {match.incoming.name}</li>
              ))}
            </ul>
          </>
        )}
        {alsoInQueue && alsoInQueue.length > 0 && (
          <div className="pt-2 border-t-subtle">
            <p className="text-[var(--text-muted)]">
              {alsoInQueue.length === 1
                ? <><strong className="text-[var(--text-secondary)]">{alsoInQueue[0]}</strong> era già in coda e non è stato aggiunto di nuovo.</>
                : <>{alsoInQueue.length} file erano già in coda e non sono stati aggiunti di nuovo:</>}
            </p>
            {alsoInQueue.length > 1 && (
              <ul className="space-y-1 pl-1 mt-1">
                {alsoInQueue.map(name => (
                  <li key={name} className="truncate text-[var(--text-muted)]">- {name}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <div className="modal-footer">
        <button onClick={onDismiss} className="modal-action-button flex-1">
          Tieni la versione pronta
        </button>
        <button onClick={onAddAgain} className="modal-action-button is-danger flex-1">
          Rigenera da zero
        </button>
      </div>
    </>
  );
}
