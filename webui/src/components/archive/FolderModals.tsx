import { type FormEvent, useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { Trash2, X } from 'lucide-react';
import type { ArchiveFolder } from '../../bridge';
import { DEFAULT_FOLDER_COLOR, FOLDER_COLORS, type FolderModalState } from './types';

interface FolderModalProps {
  state: FolderModalState;
  onClose: () => void;
  onSave: (name: string, color: string) => void;
}

export function FolderModal({ state, onClose, onSave }: FolderModalProps) {
  const [name, setName] = useState(state.type === 'edit' ? state.folder.name : '');
  const [color, setColor] = useState(state.type === 'edit' ? (state.folder.color || DEFAULT_FOLDER_COLOR) : DEFAULT_FOLDER_COLOR);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setName(state.type === 'edit' ? state.folder.name : '');
    setColor(state.type === 'edit' ? (state.folder.color || DEFAULT_FOLDER_COLOR) : DEFAULT_FOLDER_COLOR);
  }, [state]);

  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 80);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    onSave(name.trim(), color || DEFAULT_FOLDER_COLOR);
  };

  return (
    <motion.div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      exit={{ opacity: 0 }}
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
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="modal-header">
          <div className="flex items-center gap-3 min-w-0">
            <span className="folder-color-dot" style={{ '--folder-color': color } as React.CSSProperties} />
            <h2 className="text-lg font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
              {state.type === 'create' ? 'Nuova cartella' : 'Modifica cartella'}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="icon-button modal-icon-button"
            aria-label="Chiudi finestra"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {/* Form Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto flex flex-col">
          <div className="modal-body space-y-4">
            <div>
              <label className="text-xs font-semibold block mb-1.5" style={{ color: 'var(--text-muted)' }}>
                NOME RACCOLTA
              </label>
              <input
                ref={inputRef}
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="es. Anatomia"
                maxLength={48}
                className="app-input w-full text-sm"
              />
            </div>
            <div>
              <label className="text-xs font-semibold block mb-2" style={{ color: 'var(--text-muted)' }}>
                COLORE IDENTIFICATIVO
              </label>
              <div className="flex flex-wrap gap-2">
                {FOLDER_COLORS.map(c => {
                  const isSelected = color.trim().toLowerCase() === c.trim().toLowerCase();
                  return (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setColor(c)}
                      className="w-7 h-7 rounded-full transition-transform hover:scale-105 focus:outline-none"
                      style={{
                        background: c,
                        border: isSelected ? '3px solid var(--text-primary)' : '3px solid transparent',
                        outline: isSelected ? `2px solid ${c}` : 'none',
                        outlineOffset: 2,
                      }}
                      aria-label={`Colore ${c}`}
                      aria-pressed={isSelected}
                    />
                  );
                })}
              </div>
            </div>
          </div>
          {/* Footer Actions */}
          <div className="modal-footer">
            <button type="button" onClick={onClose} className="modal-action-button flex-1">
              Annulla
            </button>
            <button
              type="submit"
              disabled={!name.trim()}
              className="modal-action-button is-primary flex-1"
            >
              {state.type === 'create' ? 'Crea raccolta' : 'Salva modifiche'}
            </button>
          </div>
        </form>
      </motion.div>
    </motion.div>
  );
}

interface DeleteFolderConfirmModalProps {
  folder: ArchiveFolder;
  onClose: () => void;
  onConfirm: () => void;
}

export function DeleteFolderConfirmModal({
  folder,
  onClose,
  onConfirm,
}: DeleteFolderConfirmModalProps) {
  const sessionCount = folder.session_dirs.length;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
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
        onClick={e => e.stopPropagation()}
      >
        <div className="modal-header">
          <div className="flex items-center gap-3 min-w-0">
            <Trash2 className="w-5 h-5 shrink-0" style={{ color: 'var(--error-text)' }} />
            <h2 className="text-lg font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
              Eliminare questa raccolta?
            </h2>
          </div>
          <button
            onClick={onClose}
            className="icon-button modal-icon-button"
            aria-label="Chiudi finestra"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="modal-body space-y-4">
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-xl"
            style={{
              '--folder-color': folder.color || DEFAULT_FOLDER_COLOR,
              background: 'color-mix(in srgb, var(--folder-color) 12%, transparent)',
              border: '1px solid color-mix(in srgb, var(--folder-color) 28%, transparent)',
            } as React.CSSProperties}
          >
            <span className="folder-color-dot is-small" />
            <span className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>{folder.name}</span>
            {sessionCount > 0 && (
              <span className="ml-auto text-xs shrink-0" style={{ color: 'var(--text-muted)' }}>
                {sessionCount === 1 ? '1 lezione' : `${sessionCount} lezioni`}
              </span>
            )}
          </div>

          <p style={{ color: 'var(--text-muted)' }}>
            La raccolta verrà eliminata. Le sbobine al suo interno{' '}
            <strong style={{ color: 'var(--text-primary)' }}>non verranno cancellate</strong>{' '}
            e resteranno disponibili nell&apos;archivio.
          </p>
        </div>

        <div className="modal-footer">
          <button onClick={onClose} className="modal-action-button flex-1">
            Annulla
          </button>
          <button
            onClick={onConfirm}
            className="modal-action-button is-danger flex-1"
          >
            Elimina raccolta
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

interface DeleteMultipleSessionsConfirmModalProps {
  sessions: { sessionDir: string; name: string }[];
  onClose: () => void;
  onConfirm: () => void;
}

export function DeleteMultipleSessionsConfirmModal({
  sessions,
  onClose,
  onConfirm,
}: DeleteMultipleSessionsConfirmModalProps) {
  const count = sessions.length;
  const previewList = sessions.slice(0, 5);
  const remainingCount = count - previewList.length;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
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
        onClick={e => e.stopPropagation()}
      >
        <div className="modal-header">
          <div className="flex items-center gap-3 min-w-0">
            <Trash2 className="w-5 h-5 shrink-0" style={{ color: 'var(--error-text)' }} />
            <h2 className="text-lg font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
              {count === 1 ? 'Eliminare questa sbobina?' : `Eliminare ${count} sbobine?`}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="icon-button modal-icon-button"
            aria-label="Chiudi finestra"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="modal-body space-y-3">
          <div className="p-3 rounded-xl border space-y-1.5" style={{ background: 'var(--bg-input)', borderColor: 'var(--border-subtle)' }}>
            {previewList.map(s => (
              <div key={s.sessionDir} className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
                • {s.name}
              </div>
            ))}
            {remainingCount > 0 && (
              <div className="text-xs italic pt-1" style={{ color: 'var(--text-muted)' }}>
                …e altre {remainingCount} {remainingCount === 1 ? 'sbobina' : 'sbobine'}
              </div>
            )}
          </div>

          <p style={{ color: 'var(--text-muted)' }}>
            Tutti i file e i dati di sessione relativi verranno eliminati definitivamente dal disco.{' '}
            <strong style={{ color: 'var(--error-text)' }}>L&apos;operazione è irreversibile.</strong>
          </p>
        </div>

        <div className="modal-footer">
          <button onClick={onClose} className="modal-action-button flex-1">
            Annulla
          </button>
          <button
            onClick={onConfirm}
            className="modal-action-button is-danger flex-1"
          >
            {count === 1 ? 'Elimina definitivamente' : `Elimina ${count} sbobine`}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

export { DEFAULT_FOLDER_COLOR, FOLDER_COLORS } from './types';
export { AddSessionsToFolderModal, type AddSessionsToFolderModalProps } from './AddSessionsToFolderModal';
