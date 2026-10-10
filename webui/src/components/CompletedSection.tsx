import { memo, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { CheckCircle, Search, Trash2, X } from 'lucide-react';
import type { AppStatus, FileItem } from '../appState';
import type { ArchiveFolder } from '../bridge';
import { CompletedFileCard } from './QueueFileCard';
import { normalizeSessionPath } from '../utils';

interface CompletedSectionProps {
  doneFiles: FileItem[];
  appState: AppStatus;
  onRemove: (id: string) => void;
  onPreview: (htmlPath: string, filename: string, sourcePath?: string, fileId?: string, sessionDir?: string) => void;
  onOpenFile: (path: string) => void;
  onClearAll: () => void;
  onRetryFailedRevisionBlocks?: (sessionDir: string, fileId?: string) => Promise<void>;
  sessionFolderMap?: Map<string, ArchiveFolder>;
}

export const CompletedSection = memo(function CompletedSection({ doneFiles, appState, onRemove, onPreview, onOpenFile, onClearAll, onRetryFailedRevisionBlocks, sessionFolderMap }: CompletedSectionProps) {
  const [completedSearch, setCompletedSearch] = useState('');

  const filteredDoneFiles = completedSearch.trim()
    ? doneFiles.filter(f => f.name.toLowerCase().includes(completedSearch.toLowerCase()))
    : doneFiles;

  const warningCount = doneFiles.filter(f => f.completionStatus === 'completed_with_warnings' || (f.revisionFailedBlocks?.length ?? 0) > 0).length;
  const fullyCompletedCount = doneFiles.length - warningCount;

  return (
    <>
      {doneFiles.length > 0 && (
        <motion.div
          key="completed-section"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          className="premium-panel p-5 sm:p-6 space-y-4"
        >
          <div className="flex flex-col gap-4 border-b pb-5 sm:flex-row sm:items-center sm:justify-between" style={{ borderColor: 'var(--border-subtle)' }}>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
              <h2 className="text-2xl font-semibold tracking-tight flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                <CheckCircle className="w-5 h-5" style={{ color: 'var(--success-text)' }} />
                Sbobine completate
              </h2>
              <span className="status-pill self-start sm:self-auto shrink-0 whitespace-nowrap">
                {fullyCompletedCount}{warningCount > 0 ? ` · ${warningCount} con avvisi` : ''}
              </span>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {doneFiles.length >= 5 && (
                <div className="search-pill-wrap w-48 sm:w-64">
                  <Search className="search-pill-icon w-3.5 h-3.5" />
                  <input
                    type="text"
                    value={completedSearch}
                    onChange={e => setCompletedSearch(e.target.value)}
                    placeholder="Cerca..."
                    className="search-pill-input"
                  />
                  {completedSearch.trim() && (
                    <button
                      type="button"
                      onClick={() => setCompletedSearch('')}
                      className="search-pill-clear"
                      aria-label="Cancella ricerca"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </div>
              )}
              {(appState === 'idle' || appState === 'processing') && (
                <button
                  type="button"
                  onClick={onClearAll}
                  className="icon-button compact-icon-button hover-danger transition-colors text-[var(--text-muted)] hover:!text-[var(--error-text)]"
                  title="Pulisci tutto"
                  aria-label="Pulisci tutto"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>

          <div
            className="overflow-x-hidden overflow-y-auto app-scroll is-chainable max-h-[390px] px-1.5 py-1"
          >
            <div className="space-y-3">
              <AnimatePresence>
                {filteredDoneFiles.map(file => (
                  <CompletedFileCard
                    key={file.id}
                    file={file}
                    onRemove={onRemove}
                    onPreview={onPreview}
                    onOpenFile={onOpenFile}
                    onRetryFailedRevisionBlocks={onRetryFailedRevisionBlocks}
                    currentFolder={file.outputDir ? sessionFolderMap?.get(normalizeSessionPath(file.outputDir)) : undefined}
                  />
                ))}
                {completedSearch.trim() && filteredDoneFiles.length === 0 && (
                  <motion.p
                    key="no-results"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="text-sm text-center py-6"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    Nessun risultato per "{completedSearch}"
                  </motion.p>
                )}
              </AnimatePresence>
            </div>
          </div>
        </motion.div>
      )}
    </>
  );
});
