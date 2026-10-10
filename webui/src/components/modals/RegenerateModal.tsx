import { useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { AlertCircle, X } from 'lucide-react';

interface RegenerateModalProps {
  prompt: { filename: string; mode?: 'completed' | 'resume' } | null;
  onAnswer: (yes: boolean) => void;
  onDismiss: () => void;
}

export function RegenerateModal({ prompt, onAnswer, onDismiss }: RegenerateModalProps) {
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
            <div className="modal-header">
              <div className="flex items-center gap-3 min-w-0">
                <AlertCircle className="w-5 h-5 shrink-0 text-[var(--warning-text)]" />
                <h2 className="text-lg font-semibold truncate text-[var(--text-primary)]">
                  {prompt.mode === 'completed' ? 'Versione già pronta' : 'Ripresa disponibile'}
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
            <div className="modal-body space-y-4">
              <p>
                {prompt.mode === 'completed'
                  ? <><strong className="text-[var(--text-primary)]">{prompt.filename}</strong> {' '}risulta già completato.</>
                  : <>Per il file <strong className="text-[var(--text-primary)]">{prompt.filename}</strong> ci sono progressi salvati e pronti per essere ripresi.</>}
              </p>
              <p>
                {prompt.mode === 'completed'
                  ? 'Puoi usare la versione già pronta oppure rigenerare tutto da zero.'
                  : 'Puoi riprendere da dove eri rimasto oppure ricominciare da zero perdendo i progressi salvati.'}
              </p>
            </div>
            <div className="modal-footer">
              <button onClick={() => onAnswer(false)} className="modal-action-button flex-1">
                {prompt.mode === 'completed' ? 'Usa versione pronta' : 'Riprendi da dove eri rimasto'}
              </button>
              <button onClick={() => onAnswer(true)} className="modal-action-button is-danger flex-1">
                {prompt.mode === 'completed' ? 'Rigenera da zero' : 'Ricomincia da zero'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
