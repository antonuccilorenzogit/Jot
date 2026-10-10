import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { X, Download, Package, FileText, Music, CheckCircle2, AlertCircle, Loader2, FolderOpen } from 'lucide-react';
import type { ArchiveSession } from '../../bridge';

interface ShareExportModalProps {
  session: ArchiveSession | null;
  onClose: () => void;
}

export function ShareExportModal({ session, onClose }: ShareExportModalProps) {
  const [exportType, setExportType] = useState<'full' | 'text_only' | 'audio_only'>('full');
  const [isProcessing, setIsProcessing] = useState(false);
  const [exportedPath, setExportedPath] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isProcessing) {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [session, isProcessing, onClose]);

  if (!session) return null;

  const handleExportFile = async () => {
    setIsProcessing(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    setExportedPath(null);

    try {
      if (window.pywebview?.api?.export_sbobina_package) {
        const res = await window.pywebview.api.export_sbobina_package(
          session.session_dir,
          exportType,
        );
        if (res.cancelled) {
          setIsProcessing(false);
          return;
        }
        if (res.ok) {
          setExportedPath(res.target_path || null);
          setSuccessMsg(
            `Pacchetto .sbobina salvato con successo! ${res.audio_included ? '(Audio incluso)' : ''}`
          );
        } else {
          setErrorMsg(res.error || 'Impossibile esportare il pacchetto.');
        }
      } else {
        setErrorMsg('La funzionalità di esportazione richiede l\'applicazione desktop.');
      }
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Errore imprevisto durante l\'esportazione.');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleOpenFolder = () => {
    if (exportedPath && window.pywebview?.api?.open_file) {
      const folderPath = exportedPath.replace(/[/\\][^/\\]+$/, '');
      window.pywebview.api.open_file(folderPath);
    }
  };

  return (
    <AnimatePresence>
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
          className="modal-card relative w-full max-w-lg overflow-hidden flex flex-col"
        >
          {/* Header */}
          <div className="modal-header">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 bg-[var(--accent-subtle)] text-[var(--accent-text)]">
                <Package className="w-4.5 h-4.5" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-semibold truncate text-[var(--text-primary)]">
                  Esporta Pacchetto Sbobina
                </h2>
                <p className="text-xs truncate text-[var(--text-muted)] font-normal">
                  {session.name}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="icon-button modal-icon-button"
              aria-label="Chiudi finestra"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="modal-body space-y-4">
            {/* Option Cards */}
            <div className="space-y-2.5">
              <label className="text-xs font-semibold uppercase tracking-wider block text-[var(--text-muted)]">
                Cosa desideri includere nel pacchetto?
              </label>

              {/* Option 1: Sbobina + Audio */}
              <div
                onClick={() => setExportType('full')}
                className="p-3.5 rounded-lg border cursor-pointer transition-all flex items-start gap-3.5"
                style={{
                  borderColor: exportType === 'full' ? 'var(--accent-bg)' : 'var(--border-default)',
                  background: exportType === 'full' ? 'var(--accent-subtle)' : 'var(--bg-surface)',
                }}
              >
                <div
                  className="mt-0.5 w-4 h-4 rounded-full border flex items-center justify-center shrink-0"
                  style={{
                    borderColor: exportType === 'full' ? 'var(--accent-bg)' : 'var(--border-strong)',
                    background: exportType === 'full' ? 'var(--accent-bg)' : 'transparent',
                  }}
                >
                  {exportType === 'full' && <div className="w-2 h-2 rounded-full bg-white" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-[var(--text-primary)]">
                      Sbobina + Audio (Completo)
                    </span>
                    <span
                      className="text-[10px] uppercase font-bold px-2 py-0.5 rounded-md"
                      style={{ background: 'var(--accent-bg)', color: 'var(--btn-primary-text)' }}
                    >
                      Consigliato
                    </span>
                  </div>
                  <p className="text-xs mt-0.5 text-[var(--text-muted)]">
                    Include la sbobina completa (HTML, revisioni) e la traccia audio per riascoltarla sul nuovo PC.
                  </p>
                </div>
              </div>

              {/* Option 2: Solo Sbobina */}
              <div
                onClick={() => setExportType('text_only')}
                className="p-3.5 rounded-lg border cursor-pointer transition-all flex items-start gap-3.5"
                style={{
                  borderColor: exportType === 'text_only' ? 'var(--accent-bg)' : 'var(--border-default)',
                  background: exportType === 'text_only' ? 'var(--accent-subtle)' : 'var(--bg-surface)',
                }}
              >
                <div
                  className="mt-0.5 w-4 h-4 rounded-full border flex items-center justify-center shrink-0"
                  style={{
                    borderColor: exportType === 'text_only' ? 'var(--accent-bg)' : 'var(--border-strong)',
                    background: exportType === 'text_only' ? 'var(--accent-bg)' : 'transparent',
                  }}
                >
                  {exportType === 'text_only' && <div className="w-2 h-2 rounded-full bg-white" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-[var(--accent-text)]" />
                    <span className="text-sm font-semibold text-[var(--text-primary)]">
                      Solo Sbobina (Leggero)
                    </span>
                  </div>
                  <p className="text-xs mt-0.5 text-[var(--text-muted)]">
                    Include solo il testo della sbobina e i dati di sessione. File di dimensioni ridotte.
                  </p>
                </div>
              </div>

              {/* Option 3: Solo Audio */}
              <div
                onClick={() => setExportType('audio_only')}
                className="p-3.5 rounded-lg border cursor-pointer transition-all flex items-start gap-3.5"
                style={{
                  borderColor: exportType === 'audio_only' ? 'var(--accent-bg)' : 'var(--border-default)',
                  background: exportType === 'audio_only' ? 'var(--accent-subtle)' : 'var(--bg-surface)',
                }}
              >
                <div
                  className="mt-0.5 w-4 h-4 rounded-full border flex items-center justify-center shrink-0"
                  style={{
                    borderColor: exportType === 'audio_only' ? 'var(--accent-bg)' : 'var(--border-strong)',
                    background: exportType === 'audio_only' ? 'var(--accent-bg)' : 'transparent',
                  }}
                >
                  {exportType === 'audio_only' && <div className="w-2 h-2 rounded-full bg-white" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Music className="w-4 h-4 text-[var(--accent-text)]" />
                    <span className="text-sm font-semibold text-[var(--text-primary)]">
                      Solo Audio
                    </span>
                  </div>
                  <p className="text-xs mt-0.5 text-[var(--text-muted)]">
                    Esporta solo la registrazione audio originale per la condivisione diretta.
                  </p>
                </div>
              </div>
            </div>

            {/* Error or Success notification */}
            {errorMsg && (
              <div className="alert-card is-error text-xs flex items-center gap-2.5 p-3">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}

            {successMsg && (
              <div className="alert-card is-success text-xs flex flex-col gap-2.5 p-3">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-4 h-4 shrink-0 text-[var(--accent-text)]" />
                  <span>{successMsg}</span>
                </div>
                {exportedPath && (
                  <button
                    type="button"
                    onClick={handleOpenFolder}
                    className="inline-flex items-center gap-1.5 self-start text-xs font-semibold px-3 py-1.5 rounded-lg border transition-all cursor-pointer bg-[var(--bg-surface)] border-[var(--border-default)] text-[var(--accent-text)] hover:bg-[var(--bg-hover)]"
                  >
                    <FolderOpen className="w-3.5 h-3.5" />
                    <span>Apri cartella del pacchetto</span>
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Footer Actions */}
          <div className="modal-footer">
            <button
              type="button"
              onClick={onClose}
              className="modal-action-button flex-1"
            >
              Annulla
            </button>
            <button
              type="button"
              onClick={handleExportFile}
              disabled={isProcessing}
              className="modal-action-button is-primary flex-1 flex items-center justify-center gap-2"
            >
              {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              <span>Esporta Pacchetto (.sbobina)</span>
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
