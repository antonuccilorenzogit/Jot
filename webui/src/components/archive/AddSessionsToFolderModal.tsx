import { useMemo, useRef, useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Check, FileText, FolderPlus, Plus, Search, X } from 'lucide-react';
import type { ArchiveFolder, ArchiveSession } from '../../bridge';
import { DEFAULT_FOLDER_COLOR } from './types';
import { formatRelativeTime } from '../../utils';

export interface AddSessionsToFolderModalProps {
  folder: ArchiveFolder;
  availableSessions: ArchiveSession[];
  onClose: () => void;
  onAdd: (sessionDirs: string[]) => void;
}

export function AddSessionsToFolderModal({
  folder,
  availableSessions,
  onClose,
  onAdd,
}: AddSessionsToFolderModalProps) {
  const [search, setSearch] = useState('');
  const [selectedDirs, setSelectedDirs] = useState<Set<string>>(new Set());
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => searchInputRef.current?.focus(), 80);
    return () => clearTimeout(timer);
  }, []);

  const filteredSessions = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = q
      ? availableSessions.filter(s => s.name.toLowerCase().includes(q))
      : availableSessions;
    return [...list].sort((a, b) => {
      const ta = a.completed_at_iso ? new Date(a.completed_at_iso).getTime() : 0;
      const tb = b.completed_at_iso ? new Date(b.completed_at_iso).getTime() : 0;
      return tb - ta;
    });
  }, [availableSessions, search]);

  const toggleSelect = (dir: string) => {
    setSelectedDirs(prev => {
      const next = new Set(prev);
      if (next.has(dir)) next.delete(dir);
      else next.add(dir);
      return next;
    });
  };

  const selectAll = () => {
    setSelectedDirs(new Set(filteredSessions.map(s => s.session_dir)));
  };

  const clearSelect = () => {
    setSelectedDirs(new Set());
  };

  const handleConfirm = () => {
    if (selectedDirs.size === 0) return;
    onAdd(Array.from(selectedDirs));
    onClose();
  };

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

  const allFilteredSelected =
    filteredSessions.length > 0 &&
    filteredSessions.every(s => selectedDirs.has(s.session_dir));

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
        className="modal-card relative w-full max-w-lg max-h-[86vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="modal-header">
          <div className="flex items-center gap-3 min-w-0">
            <span
              className="folder-color-dot"
              style={{ '--folder-color': folder.color || DEFAULT_FOLDER_COLOR } as React.CSSProperties}
            />
            <h2 className="text-lg font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
              Aggiungi lezioni a <span style={{ color: folder.color || DEFAULT_FOLDER_COLOR }}>{folder.name}</span>
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

        {/* Body */}
        <div className="modal-body flex flex-col gap-3.5 min-h-[300px]">
          {availableSessions.length === 0 ? (
            <div
              className="flex-1 flex flex-col items-center justify-center gap-2 py-12 text-center"
              style={{ color: 'var(--text-muted)' }}
            >
              <FolderPlus className="w-9 h-9 opacity-35" />
              <p className="text-sm font-medium">Tutte le sbobine sono già presenti in questa cartella.</p>
            </div>
          ) : (
            <>
              {/* Search Bar */}
              <div className="search-pill-wrap shrink-0">
                <Search className="search-pill-icon w-3.5 h-3.5" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Cerca sbobina per nome..."
                  className="search-pill-input"
                />
                <AnimatePresence>
                  {search.trim().length > 0 && (
                    <motion.button
                      key="clear"
                      initial={{ opacity: 0, scale: 0.7 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.7 }}
                      transition={{ duration: 0.1 }}
                      onClick={() => {
                        setSearch('');
                        searchInputRef.current?.focus();
                      }}
                      className="search-pill-clear"
                      aria-label="Cancella ricerca"
                    >
                      <X className="w-3 h-3" />
                    </motion.button>
                  )}
                </AnimatePresence>
              </div>

              {/* Status & Quick Toggle */}
              {filteredSessions.length > 0 && (
                <div className="flex items-center justify-between gap-2 px-1 text-xs shrink-0">
                  <span className="font-semibold" style={{ color: 'var(--text-muted)' }}>
                    {filteredSessions.length}{' '}
                    {filteredSessions.length === 1 ? 'sbobina disponibile' : 'sbobine disponibili'}
                  </span>
                  <div className="flex items-center gap-2">
                    {selectedDirs.size > 0 && (
                      <button
                        type="button"
                        onClick={clearSelect}
                        className="text-xs hover:underline cursor-pointer"
                        style={{ color: 'var(--text-muted)' }}
                      >
                        Deseleziona
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={allFilteredSelected ? clearSelect : selectAll}
                      className="text-xs font-semibold flex items-center gap-1 cursor-pointer hover:underline"
                      style={{ color: 'var(--accent-text)' }}
                    >
                      {allFilteredSelected
                        ? 'Deseleziona tutte'
                        : `Seleziona tutte (${filteredSessions.length})`}
                    </button>
                  </div>
                </div>
              )}

              {/* Sessions List */}
              {filteredSessions.length === 0 && search.trim() ? (
                <div
                  className="flex-1 flex items-center justify-center py-8 text-center text-xs"
                  style={{ color: 'var(--text-muted)' }}
                >
                  Nessun risultato per &ldquo;{search}&rdquo;
                </div>
              ) : (
                <div className="flex-1 overflow-y-auto app-scroll pr-1 flex flex-col gap-2 min-h-[160px] max-h-[360px]">
                  {filteredSessions.map(session => {
                    const ts = session.completed_at_iso
                      ? new Date(session.completed_at_iso).getTime()
                      : 0;
                    const isSelected = selectedDirs.has(session.session_dir);
                    return (
                      <div
                        key={session.session_dir}
                        className={`archive-session-card flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-xl border cursor-pointer select-none transition-all ${isSelected ? 'is-selected' : ''}`}
                        onClick={() => toggleSelect(session.session_dir)}
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          <button
                            type="button"
                            onClick={e => {
                              e.stopPropagation();
                              toggleSelect(session.session_dir);
                            }}
                            className={`w-4 h-4 rounded flex items-center justify-center transition-all shrink-0 cursor-pointer ${
                              isSelected
                                ? 'bg-[var(--accent-text)] text-[var(--btn-primary-text)]'
                                : 'border border-[var(--border-strong)] bg-[var(--bg-elevated)] hover:border-[var(--accent-text)] opacity-70'
                            }`}
                            aria-label={
                              isSelected
                                ? `Deseleziona ${session.name}`
                                : `Seleziona ${session.name}`
                            }
                            title={isSelected ? 'Deseleziona' : 'Seleziona'}
                          >
                            {isSelected && <Check className="w-3 h-3 stroke-[3]" />}
                          </button>
                          <FileText
                            className="w-4 h-4 shrink-0"
                            style={{ color: 'var(--accent-text)', opacity: 0.8 }}
                          />
                          <div className="min-w-0 flex-1">
                            <p
                              className="text-xs font-semibold truncate"
                              style={{ color: 'var(--text-primary)' }}
                            >
                              {session.name}
                            </p>
                            {ts > 0 && (
                              <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                                {formatRelativeTime(ts)}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
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
            onClick={handleConfirm}
            disabled={selectedDirs.size === 0}
            className="modal-action-button is-primary flex-1 flex items-center justify-center gap-1.5"
          >
            <Plus className="w-4 h-4" />
            <span>
              {selectedDirs.size > 0
                ? `Aggiungi (${selectedDirs.size})`
                : 'Aggiungi alla cartella'}
            </span>
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
