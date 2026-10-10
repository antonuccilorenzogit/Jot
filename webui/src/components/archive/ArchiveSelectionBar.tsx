import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  FolderMinus, FolderPlus,
  Plus, Trash2, X,
} from 'lucide-react';
import type { ArchiveFolder } from '../../bridge';
import { DEFAULT_FOLDER_COLOR } from './types';

export interface ArchiveSelectionBarProps {
  selectedCount: number;
  totalCount: number;
  folders: ArchiveFolder[];
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onAssignToFolder: (folderId: string) => void;
  onNewFolder: () => void;
  hasAssignedFolder?: boolean;
  onRemoveFromFolder?: () => void;
  onDeleteSelected?: () => void;
  onClose?: () => void;
}

export function ArchiveSelectionBar({
  selectedCount,
  totalCount,
  folders,
  onSelectAll,
  onDeselectAll,
  onAssignToFolder,
  onNewFolder,
  hasAssignedFolder,
  onRemoveFromFolder,
  onDeleteSelected,
  onClose,
}: ArchiveSelectionBarProps) {
  const [isFolderMenuOpen, setIsFolderMenuOpen] = useState(false);
  const folderMenuRef = useRef<HTMLDivElement>(null);
  const folderButtonRef = useRef<HTMLButtonElement>(null);

  const allSelected = selectedCount > 0 && selectedCount >= totalCount;

  useEffect(() => {
    if (!isFolderMenuOpen) return;
    const handleClickOutside = (e: MouseEvent | PointerEvent) => {
      const target = e.target as Node;
      if (folderMenuRef.current?.contains(target) || folderButtonRef.current?.contains(target)) {
        return;
      }
      setIsFolderMenuOpen(false);
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsFolderMenuOpen(false);
      }
    };
    document.addEventListener('pointerdown', handleClickOutside, true);
    document.addEventListener('mousedown', handleClickOutside, true);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handleClickOutside, true);
      document.removeEventListener('mousedown', handleClickOutside, true);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isFolderMenuOpen]);

  if (selectedCount <= 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 28, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 28, scale: 0.96 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="archive-selection-bar fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex flex-wrap justify-center items-center gap-1 sm:gap-2 p-2 w-max max-w-[95vw] overflow-visible"
    >
      {/* 1. Count & Toggle All (unified minimal button with micro-animation) */}
      <button
        type="button"
        onClick={allSelected ? onDeselectAll : onSelectAll}
        className="group/toggle flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold tracking-tight transition-colors cursor-pointer hover:bg-[var(--bg-hover)]"
        style={{ color: 'var(--text-primary)' }}
        title={allSelected ? 'Deseleziona tutte le sbobine' : `Seleziona tutte le ${totalCount} sbobine`}
      >
        <span
          className="px-1.5 py-0.5 rounded text-xs font-bold shrink-0 transition-transform duration-200 group-hover/toggle:scale-110"
          style={{
            background: 'var(--accent-subtle)',
            color: 'var(--accent-text)',
            minWidth: '20px',
            textAlign: 'center',
          }}
        >
          {selectedCount}
        </span>
        <span>{allSelected ? 'Deseleziona' : 'Seleziona tutte'}</span>
      </button>

      <div className="w-px h-6 shrink-0" style={{ background: 'var(--border-subtle)' }} />

      {/* 2. Assign to Folder Popover ("Aggiungi" with micro-animation) */}
      <div className="sm:relative">
        <button
          ref={folderButtonRef}
          type="button"
          onClick={() => setIsFolderMenuOpen(v => !v)}
          className="group/add flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold tracking-tight transition-colors cursor-pointer hover:bg-[var(--bg-hover)]"
          style={{
            background: isFolderMenuOpen ? 'var(--accent-subtle)' : undefined,
            color: 'var(--text-primary)',
            border: isFolderMenuOpen ? '1px solid var(--accent-text)' : '1px solid transparent',
          }}
          title="Aggiungi le sbobine selezionate a una cartella"
        >
          <FolderPlus
            className="w-4 h-4 shrink-0 transition-transform duration-200 group-hover/add:scale-110 group-hover/add:-translate-y-0.5"
            style={{ color: 'var(--accent-text)' }}
          />
          <span>Aggiungi</span>
        </button>

        <AnimatePresence>
          {isFolderMenuOpen && (
            <motion.div
              ref={folderMenuRef}
              initial={{ opacity: 0, y: 8, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.95 }}
              transition={{ duration: 0.14, ease: 'easeOut' }}
              className="absolute bottom-full left-1/2 -translate-x-1/2 sm:left-0 sm:translate-x-0 mb-3 w-[280px] max-w-[90vw] rounded-[10px] border overflow-hidden z-50 p-2 flex flex-col gap-0.5"
              style={{
                background: 'var(--bg-elevated)',
                borderColor: 'var(--border-strong)',
                boxShadow: 'var(--shadow-strong)',
              }}
            >
              <div className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                Seleziona raccolta
              </div>

              {folders.length === 0 && (
                <div className="px-3 py-2 text-sm text-center" style={{ color: 'var(--text-muted)' }}>
                  Nessuna cartella creata
                </div>
              )}

              <div className="max-h-48 overflow-y-auto app-scroll flex flex-col gap-0.5">
                {folders.map(folder => (
                  <button
                    key={folder.id}
                    type="button"
                    onClick={() => {
                      onAssignToFolder(folder.id);
                      setIsFolderMenuOpen(false);
                    }}
                    className="w-full flex items-center gap-3 min-h-10 px-3 py-2 rounded-lg text-sm font-semibold tracking-tight text-left transition-colors cursor-pointer hover:bg-[var(--bg-hover)]"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    <span className="folder-color-dot is-small" style={{ '--folder-color': folder.color || DEFAULT_FOLDER_COLOR } as React.CSSProperties} />
                    <span className="truncate flex-1">{folder.name}</span>
                    <span className="text-xs shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>
                      {folder.session_dirs.length}
                    </span>
                  </button>
                ))}
              </div>

              <div className="my-1 border-t" style={{ borderColor: 'var(--border-subtle)' }} />

              <button
                type="button"
                onClick={() => {
                  setIsFolderMenuOpen(false);
                  onNewFolder();
                }}
                className="group/newfolder w-full flex items-center gap-2 min-h-10 px-3 py-2 rounded-lg text-sm font-semibold tracking-tight text-left transition-colors cursor-pointer hover:bg-[var(--bg-hover)]"
                style={{ color: 'var(--accent-text)' }}
              >
                <Plus className="w-4 h-4 shrink-0 transition-transform duration-200 group-hover/newfolder:rotate-90 group-hover/newfolder:scale-110" />
                <span>Nuova raccolta...</span>
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* 3. Remove from folder action ("Rimuovi" with micro-animation) */}
      {hasAssignedFolder && onRemoveFromFolder && (
        <button
          type="button"
          onClick={onRemoveFromFolder}
          className="group/remove flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold tracking-tight transition-colors cursor-pointer hover:bg-[var(--bg-hover)]"
          style={{ color: 'var(--text-primary)' }}
          title="Rimuovi le sbobine selezionate dalla cartella"
        >
          <FolderMinus
            className="w-4 h-4 shrink-0 transition-transform duration-200 group-hover/remove:scale-110 group-hover/remove:-translate-y-0.5"
            style={{ color: 'var(--text-primary)', opacity: 0.85 }}
          />
          <span>Rimuovi</span>
        </button>
      )}

      {/* 4. Delete selected action ("Elimina" with micro-animation) */}
      {onDeleteSelected && (
        <button
          type="button"
          onClick={onDeleteSelected}
          className="group/del flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold tracking-tight transition-colors cursor-pointer hover:bg-[var(--error-subtle)]"
          style={{ color: 'var(--error-text)' }}
          title="Elimina le sbobine selezionate dal disco"
        >
          <Trash2
            className="w-4 h-4 shrink-0 transition-transform duration-200 group-hover/del:scale-110 group-hover/del:-translate-y-0.5"
            style={{ color: 'var(--error-text)' }}
          />
          <span>Elimina</span>
        </button>
      )}

      {onClose && (
        <>
          <div className="w-px h-6 shrink-0" style={{ background: 'var(--border-subtle)' }} />

          {/* 5. Close / Cancel Selection ("X" with micro-animation) */}
          <button
            type="button"
            onClick={onClose}
            className="group/close p-2.5 rounded-lg text-sm transition-colors cursor-pointer hover:bg-[var(--bg-hover)]"
            style={{ color: 'var(--text-primary)' }}
            aria-label="Annulla selezione"
            title="Annulla selezione"
          >
            <X
              className="w-4 h-4 shrink-0 transition-transform duration-200 group-hover/close:scale-110 group-hover/close:rotate-90"
              style={{ color: 'var(--text-primary)', opacity: 0.8 }}
            />
          </button>
        </>
      )}
    </motion.div>
  );
}
