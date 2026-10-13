import { reportClientError } from '../diagnostics';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { MASCOT } from './brand/mascot';
import { motion, AnimatePresence } from 'motion/react';
import {
  ArrowRight, Clock, Eye, FileSearch, FileText,
  Loader2, Pencil, RefreshCw, Search, Upload, X,
} from 'lucide-react';
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, useSensor, useSensors,
  type DragEndEvent, type DragStartEvent,
} from '@dnd-kit/core';
import {
  SortableContext, arrayMove, rectSortingStrategy, sortableKeyboardCoordinates,
} from '@dnd-kit/sortable';
import type { ArchiveFolder, ArchiveSession } from '../bridge';
import { loadAllEditorSessions } from '../editorSessions';
import { formatRelativeTime, normalizeSessionPath, shortModelName } from '../utils';
import { FolderIndicatorChip } from './FolderChip';
import { ShareExportModal } from './modals/ShareExportModal';

import {
  type ArchivePageProps,
  DEFAULT_FOLDER_COLOR,
  type DeleteFolderConfirmState,
  type DeleteMultipleSessionsConfirmState,
  type FolderModalState,
  FULL_TEXT_SORT_OPTIONS,
  getOpenedAtMs,
  SORT_OPTIONS,
  type SortOption,
} from './archive/types';
import { SortMenu } from './archive/SortMenu';
import { FolderCardOverlay, NewFolderCard, SortableFolderCard } from './archive/FolderCard';
import { DraggableSessionCard } from './archive/SessionCard';
import { FolderDetailView } from './archive/FolderDetailView';
import { DeleteFolderConfirmModal, DeleteMultipleSessionsConfirmModal, FolderModal } from './archive/FolderModals';
import { ArchiveSelectionBar } from './archive/ArchiveSelectionBar';
import { FullTextResultList } from './archive/FullTextResults';

import { useArchiveSearch } from '../hooks/useArchiveSearch';
import { useArchiveSelection } from '../hooks/useArchiveSelection';

export type { ArchivePageProps, SortOption, FolderModalState, DeleteFolderConfirmState, DeleteMultipleSessionsConfirmState };
export { SortMenu } from './archive/SortMenu';
export { FolderCard, SortableFolderCard, FolderCardOverlay, NewFolderCard } from './archive/FolderCard';
export { DraggableSessionCard, SortableSessionCard, FolderSessionCardOverlay } from './archive/SessionCard';
export { FolderDetailView } from './archive/FolderDetailView';
export {
  FolderModal,
  DeleteFolderConfirmModal,
  DeleteMultipleSessionsConfirmModal,
  AddSessionsToFolderModal,
  DEFAULT_FOLDER_COLOR,
  FOLDER_COLORS,
} from './archive/FolderModals';
export { ArchiveSelectionBar } from './archive/ArchiveSelectionBar';
export { FullTextResultList } from './archive/FullTextResults';

export function ArchivePage({
  sessions, total, folders, onFoldersChange,
  onPreview, onOpenFile, onDeleteSession, onDeleteMultipleSessions, onRefresh,
  onRetryFailedRevisionBlocks, onNotification,
}: ArchivePageProps) {
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [folderModal, setFolderModal] = useState<FolderModalState | null>(null);
  const [deleteFolderConfirm, setDeleteFolderConfirm] = useState<DeleteFolderConfirmState | null>(null);
  const [deleteMultipleConfirm, setDeleteMultipleConfirm] = useState<DeleteMultipleSessionsConfirmState | null>(null);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeDragFolderId, setActiveDragFolderId] = useState<string | null>(null);

  const folderDndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleFolderDragStart = useCallback((event: DragStartEvent) => {
    setActiveDragFolderId(String(event.active.id));
  }, []);

  const handleFolderDragEnd = useCallback((event: DragEndEvent) => {
    setActiveDragFolderId(null);
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = folders.findIndex(f => f.id === String(active.id));
    const newIndex = folders.findIndex(f => f.id === String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    onFoldersChange(arrayMove(folders, oldIndex, newIndex));
  }, [folders, onFoldersChange]);

  const [sharingSession, setSharingSession] = useState<ArchiveSession | null>(null);
  const [isImporting, setIsImporting] = useState(false);

  const handleImportSbobina = useCallback(async () => {
    if (isImporting) return;
    setIsImporting(true);
    try {
      if (window.pywebview?.api?.import_sbobina_package) {
        const res = await window.pywebview.api.import_sbobina_package();
        if (res.ok) {
          onRefresh?.();
        } else if (!res.cancelled && res.error) {
          if (onNotification) {
            onNotification('Importazione non riuscita', res.error, 'error');
          } else {
            reportClientError('Importazione non riuscita:', res.error);
          }
        }
      }
    } catch (e) {
      if (onNotification) {
        onNotification('Importazione non riuscita', String(e), 'error');
      } else {
        reportClientError('Importazione non riuscita:', e);
      }
    } finally {
      setIsImporting(false);
    }
  }, [isImporting, onNotification, onRefresh]);

  const handleRefresh = useCallback(async () => {
    if (isRefreshing || !onRefresh) return;
    setIsRefreshing(true);
    try {
      await Promise.all([onRefresh(), new Promise<void>(r => setTimeout(r, 600))]);
    } finally {
      setIsRefreshing(false);
    }
  }, [isRefreshing, onRefresh]);

  const sessionsByDir = useMemo(() => {
    const map = new Map<string, ArchiveSession>();
    for (const s of sessions) map.set(normalizeSessionPath(s.session_dir), s);
    return map;
  }, [sessions]);

  const sessionFolderMap = useMemo(() => {
    const map = new Map<string, ArchiveFolder>();
    for (const f of folders) for (const d of f.session_dirs) map.set(normalizeSessionPath(d), f);
    return map;
  }, [folders]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const editorSessionsMap = useMemo(() => loadAllEditorSessions(), [sessions]);

  const lastOpenedOrModifiedSessionData = useMemo(() => {
    if (!sessions || sessions.length === 0) return null;
    let bestSession: ArchiveSession | null = null;
    let maxTime = -1;
    let bestOpenedAtMs = 0;
    let bestSavedAtMs = 0;
    let bestCompletedAtMs = 0;

    for (const s of sessions) {
      const openedAtMs = getOpenedAtMs(s, editorSessionsMap);
      const completedAtMs = s.completed_at_iso ? new Date(s.completed_at_iso).getTime() : 0;
      const savedAtMs = editorSessionsMap[s.session_dir]?.savedAt
        ?? editorSessionsMap[s.html_path]?.savedAt
        ?? 0;

      const time = Math.max(openedAtMs, completedAtMs, savedAtMs);
      if (time > maxTime) {
        maxTime = time;
        bestSession = s;
        bestOpenedAtMs = openedAtMs;
        bestSavedAtMs = savedAtMs;
        bestCompletedAtMs = completedAtMs;
      }
    }

    if (!bestSession || maxTime <= 0) return null;

    const isOpenedRecently = bestOpenedAtMs >= bestCompletedAtMs && bestOpenedAtMs >= bestSavedAtMs && bestOpenedAtMs > 0;
    const isSavedRecently = bestSavedAtMs > bestOpenedAtMs && bestSavedAtMs >= bestCompletedAtMs;

    return {
      session: bestSession,
      activityTimeMs: maxTime,
      isOpened: isOpenedRecently,
      isSaved: isSavedRecently,
      folder: sessionFolderMap.get(normalizeSessionPath(bestSession.session_dir)),
    };
  }, [sessions, editorSessionsMap, sessionFolderMap]);

  const {
    search,
    setSearch,
    sort,
    setSort,
    searchFocused,
    setSearchFocused,
    searchInputRef,
    fullTextMode,
    setFullTextMode,
    ftSort,
    setFtSort,
    ftResults,
    sortedFtResults,
    ftTotal,
    isSearching,
    ftError,
    allSortedSessions,
  } = useArchiveSearch({
    sessions,
    editorSessionsMap,
  });

  // ── Courses: filter pills over the list ──
  const [courseFilter, setCourseFilter] = useState<string | null>(null);
  const courses = useMemo(() => {
    const counts = new Map<string, { name: string; count: number }>();
    for (const s of sessions) {
      const name = String(s.course || '').trim();
      if (!name) continue;
      const key = name.toLowerCase();
      const entry = counts.get(key) ?? { name, count: 0 };
      entry.count += 1;
      counts.set(key, entry);
    }
    return Array.from(counts.values()).sort((a, b) => a.name.localeCompare(b.name, 'it'));
  }, [sessions]);
  const courseNames = useMemo(() => courses.map(c => c.name), [courses]);
  const unassignedCount = useMemo(() => sessions.filter(s => !String(s.course || '').trim()).length, [sessions]);
  useEffect(() => {
    if (courseFilter && courseFilter !== '__none__' && !courses.some(c => c.name.toLowerCase() === courseFilter.toLowerCase())) {
      setCourseFilter(null);
    }
  }, [courseFilter, courses]);

  const sessionPageData = useMemo(() => {
    if (!courseFilter) return allSortedSessions;
    if (courseFilter === '__none__') return allSortedSessions.filter(s => !String(s.course || '').trim());
    return allSortedSessions.filter(s => String(s.course || '').trim().toLowerCase() === courseFilter.toLowerCase());
  }, [allSortedSessions, courseFilter]);

  const handleSetCourse = useCallback(async (sessionDir: string, course: string | null) => {
    const api = window.pywebview?.api;
    if (!api?.set_session_course) return;
    try {
      const res = await api.set_session_course(sessionDir, course);
      if (!res?.ok) {
        onNotification?.('Corso non salvato', res?.error || 'Errore sconosciuto', 'error');
        return;
      }
      await onRefresh?.();
    } catch (e) {
      onNotification?.('Corso non salvato', String(e), 'error');
    }
  }, [onNotification, onRefresh]);

  const handleRename = useCallback(async (sessionDir: string, title: string) => {
    const api = window.pywebview?.api;
    if (!api?.set_session_title) return;
    try {
      const res = await api.set_session_title(sessionDir, title);
      if (!res?.ok) {
        onNotification?.('Nome non salvato', res?.error || 'Errore sconosciuto', 'error');
        return;
      }
      await onRefresh?.();
    } catch (e) {
      onNotification?.('Nome non salvato', String(e), 'error');
    }
  }, [onNotification, onRefresh]);

  const {
    selectedSessionDirs,
    assignToFolder,
    removeFromFolder,
    toggleSelectSession,
    selectAllSessions,
    handleDeselectOrRestore,
    clearSelection,
    bulkAssignToFolder,
    bulkRemoveFromFolders,
    handleOpenDeleteMultiple,
  } = useArchiveSelection({
    sessions,
    folders,
    onFoldersChange,
    sessionPageData,
    onDeleteMultipleSessions,
    setDeleteMultipleConfirm,
  });

  useEffect(() => {
    if (selectedFolderId && !folders.find(f => f.id === selectedFolderId)) {
      setSelectedFolderId(null);
    }
  }, [folders, selectedFolderId]);

  const selectedFolder = selectedFolderId ? folders.find(f => f.id === selectedFolderId) ?? null : null;

  const handleFolderSave = (name: string, color?: string) => {
    if (!folderModal) return;
    const finalColor = color || DEFAULT_FOLDER_COLOR;
    if (folderModal.type === 'create') {
      const pending = folderModal.pendingSessionDirs ?? [];
      const pendingNorm = new Set(pending.map(d => normalizeSessionPath(d)));
      const newFolder: ArchiveFolder = {
        id: crypto.randomUUID(),
        name: name.trim(),
        color: finalColor,
        session_dirs: pending,
      };
      const updated = folders.map(f => ({
        ...f,
        session_dirs: f.session_dirs.filter(d => !pendingNorm.has(normalizeSessionPath(d))),
      }));
      onFoldersChange([...updated, newFolder]);
      clearSelection();
    } else {
      onFoldersChange(folders.map(f =>
        f.id === folderModal.folder.id ? { ...f, name: name.trim(), color: finalColor } : f,
      ));
    }
    setFolderModal(null);
  };

  const handleFolderDelete = () => {
    if (!deleteFolderConfirm) return;
    onFoldersChange(folders.filter(f => f.id !== deleteFolderConfirm.folder.id));
    if (selectedFolderId === deleteFolderConfirm.folder.id) {
      setSelectedFolderId(null);
    }
    setDeleteFolderConfirm(null);
  };

  const handleBulkDeleteSessions = () => {
    if (!deleteMultipleConfirm) return;
    deleteMultipleConfirm.sessions.forEach(s => onDeleteSession(s.sessionDir, s.name));
    clearSelection();
    setDeleteMultipleConfirm(null);
  };

  const renderModals = () => (
    <>
      <AnimatePresence>
        {folderModal && (
          <FolderModal
            state={folderModal}
            onClose={() => setFolderModal(null)}
            onSave={handleFolderSave}
          />
        )}
      </AnimatePresence>
      <AnimatePresence>
        {deleteFolderConfirm && (
          <DeleteFolderConfirmModal
            folder={deleteFolderConfirm.folder}
            onClose={() => setDeleteFolderConfirm(null)}
            onConfirm={handleFolderDelete}
          />
        )}
      </AnimatePresence>
      <AnimatePresence>
        {deleteMultipleConfirm && (
          <DeleteMultipleSessionsConfirmModal
            sessions={deleteMultipleConfirm.sessions}
            onClose={() => setDeleteMultipleConfirm(null)}
            onConfirm={handleBulkDeleteSessions}
          />
        )}
      </AnimatePresence>
      {sharingSession && (
        <ShareExportModal
          session={sharingSession}
          onClose={() => setSharingSession(null)}
        />
      )}
    </>
  );

  if (selectedFolder) {
    return (
      <>
        <FolderDetailView
          folder={selectedFolder}
          allFolders={folders}
          sessionsByDir={sessionsByDir}
          editorSessionsMap={editorSessionsMap}
          onBack={() => setSelectedFolderId(null)}
          onEdit={() => setFolderModal({ type: 'edit', folder: selectedFolder })}
          onDelete={() => setDeleteFolderConfirm({ folder: selectedFolder })}
          onRemoveSession={dir => removeFromFolder(dir, selectedFolder.id)}
          onRenameSession={(dir, title) => void handleRename(dir, title)}
          onRemoveMultipleSessions={dirs => bulkRemoveFromFolders(dirs)}
          onAddSession={dir => assignToFolder(dir, selectedFolder.id)}
          onAddMultipleSessions={dirs => bulkAssignToFolder(selectedFolder.id, dirs)}
          onReorderSessions={dirs => onFoldersChange(folders.map(f =>
            f.id === selectedFolder.id ? { ...f, session_dirs: dirs } : f,
          ))}
          onAssignMultipleToFolder={(dirs, fId) => bulkAssignToFolder(fId, dirs)}
          onNewFolder={() => setFolderModal({ type: 'create' })}
          onPreview={onPreview}
          onOpenFile={onOpenFile}
          onDeleteSession={onDeleteSession}
          onDeleteMultipleSessions={handleOpenDeleteMultiple}
          onRetryFailedRevisionBlocks={onRetryFailedRevisionBlocks}
          onShareSession={setSharingSession}
        />
        {renderModals()}
      </>
    );
  }

  return (
    <div className="flex flex-col gap-6 w-full">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-[1.75rem] font-semibold tracking-tight" style={{ color: 'var(--text-primary)' }}>
            Archivio
          </h1>
          <span className="status-pill">{total != null && total > sessions.length ? total : sessions.length}</span>
        </div>
      </div>

      {/* Folders grid — always visible, first card is "new folder" */}
      <DndContext
        sensors={folderDndSensors}
        onDragStart={handleFolderDragStart}
        onDragEnd={handleFolderDragEnd}
      >
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
          <NewFolderCard onClick={() => setFolderModal({ type: 'create' })} />
          <SortableContext items={folders.map(f => f.id)} strategy={rectSortingStrategy}>
            {folders.map(folder => (
              <SortableFolderCard
                key={folder.id}
                folder={folder}
                sessionsByDir={sessionsByDir}
                onNavigate={() => setSelectedFolderId(folder.id)}
                onEdit={() => setFolderModal({ type: 'edit', folder })}
                onDelete={() => setDeleteFolderConfirm({ folder })}
              />
            ))}
          </SortableContext>
        </div>
        <DragOverlay>
          {activeDragFolderId ? (() => {
            const f = folders.find(x => x.id === activeDragFolderId);
            return f ? <FolderCardOverlay folder={f} sessionsByDir={sessionsByDir} /> : null;
          })() : null}
        </DragOverlay>
      </DndContext>

      {/* Mini Section: Ultima sbobina aperta / modificata */}
      {lastOpenedOrModifiedSessionData && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
              Ultima sbobina aperta / modificata
            </span>
          </div>
          <div
            onClick={() => onPreview(
              lastOpenedOrModifiedSessionData.session.html_path,
              lastOpenedOrModifiedSessionData.session.name,
              lastOpenedOrModifiedSessionData.session.input_path,
              undefined,
              lastOpenedOrModifiedSessionData.session.session_dir,
            )}
            className="archive-session-card flex items-center justify-between gap-4 p-4 cursor-pointer group/recent transition-all hover:border-[var(--border-strong)]"
          >
            <div className="flex items-center gap-3.5 min-w-0 flex-1">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 transition-transform group-hover/recent:scale-105"
                style={{ background: 'var(--accent-subtle)', color: 'var(--accent-text)' }}
              >
                <FileText className="w-5 h-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
                    {lastOpenedOrModifiedSessionData.session.name}
                  </p>
                  {lastOpenedOrModifiedSessionData.folder && (
                    <FolderIndicatorChip folder={lastOpenedOrModifiedSessionData.folder} />
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2 mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                  {lastOpenedOrModifiedSessionData.isOpened ? (
                    <span className="inline-flex items-center gap-1 shrink-0" title={`Ultima apertura: ${new Date(lastOpenedOrModifiedSessionData.activityTimeMs).toLocaleString('it-IT')}`}>
                      <Eye className="w-3 h-3" style={{ opacity: 0.7 }} />
                      Aperto {formatRelativeTime(lastOpenedOrModifiedSessionData.activityTimeMs)}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 shrink-0" title={`Ultima modifica: ${new Date(lastOpenedOrModifiedSessionData.activityTimeMs).toLocaleString('it-IT')}`}>
                      <Pencil className="w-3 h-3" style={{ opacity: 0.7 }} />
                      {lastOpenedOrModifiedSessionData.isSaved ? 'Modificato' : 'Completato'} {formatRelativeTime(lastOpenedOrModifiedSessionData.activityTimeMs)}
                    </span>
                  )}
                  {lastOpenedOrModifiedSessionData.session.effective_model && (
                    <>
                      <span className="w-1 h-1 rounded-full" style={{ background: 'var(--border-default)' }} />
                      <span>{shortModelName(lastOpenedOrModifiedSessionData.session.effective_model)}</span>
                    </>
                  )}
                </div>
              </div>
            </div>
            <button
              type="button"
              className="recent-session-action cursor-pointer"
            >
              <span>Riprendi</span>
              <ArrowRight className="w-3.5 h-3.5 recent-session-arrow" />
            </button>
          </div>
        </div>
      )}

      {/* Unfiled sessions */}
      <div className="flex flex-col gap-3 flex-1 min-h-0">
        <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
          Tutte le sbobine
        </h3>

        {courses.length > 0 && (
          <div className="course-pills" role="tablist" aria-label="Corsi">
            <button type="button" role="tab" aria-selected={!courseFilter} className={`course-pill${!courseFilter ? ' is-active' : ''}`} onClick={() => setCourseFilter(null)}>
              Tutti <span>{sessions.length}</span>
            </button>
            {courses.map(c => (
              <button
                key={c.name}
                type="button"
                role="tab"
                aria-selected={courseFilter?.toLowerCase() === c.name.toLowerCase()}
                className={`course-pill${courseFilter?.toLowerCase() === c.name.toLowerCase() ? ' is-active' : ''}`}
                onClick={() => setCourseFilter(c.name)}
              >
                {c.name} <span>{c.count}</span>
              </button>
            ))}
            {unassignedCount > 0 && (
              <button type="button" role="tab" aria-selected={courseFilter === '__none__'} className={`course-pill is-quiet${courseFilter === '__none__' ? ' is-active' : ''}`} onClick={() => setCourseFilter('__none__')}>
                Senza corso <span>{unassignedCount}</span>
              </button>
            )}
          </div>
        )}

        {/* Search + Sort + Actions */}
        <div className="archive-sticky-toolbar sticky top-0 z-20 py-2 -my-2 bg-[var(--bg-base)]/95 backdrop-blur-md flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <div className="search-pill-wrap">
              {isSearching
                ? <Loader2 className="search-pill-icon w-3.5 h-3.5 animate-spin" />
                : <Search className="search-pill-icon w-3.5 h-3.5" />}
              <input
                ref={searchInputRef}
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                onFocus={() => setSearchFocused(true)}
                onBlur={() => setSearchFocused(false)}
                placeholder={fullTextMode ? 'Cerca nel contenuto...' : 'Cerca per nome...'}
                className="search-pill-input"
              />
              <AnimatePresence>
                {search.trim().length > 0 ? (
                  <motion.button
                    key="clear"
                    initial={{ opacity: 0, scale: 0.7 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.7 }}
                    transition={{ duration: 0.1 }}
                    onClick={() => { setSearch(''); searchInputRef.current?.focus(); }}
                    className="search-pill-clear"
                    aria-label="Cancella ricerca"
                  >
                    <X className="w-3 h-3" />
                  </motion.button>
                ) : !searchFocused ? (
                  <motion.span
                    key="hint"
                    className="search-pill-hint"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.12 }}
                  >
                    <kbd>/</kbd>
                  </motion.span>
                ) : null}
              </AnimatePresence>
            </div>
            <button
              type="button"
              onClick={() => { setFullTextMode(m => !m); setSearch(''); }}
              className="filter-chip w-9 p-0 flex items-center justify-center group/ft"
              style={fullTextMode ? { color: 'var(--accent-text)', borderColor: 'var(--accent-text)', background: 'var(--accent-subtle)' } : undefined}
              title={fullTextMode ? 'Testo completo (Attivo - Clicca per disattivare)' : 'Testo completo (Ricerca nel contenuto)'}
              aria-label="Testo completo"
            >
              <FileSearch className="w-4 h-4 transition-transform duration-200 opacity-80 group-hover/ft:opacity-100 group-hover/ft:scale-110" />
            </button>
            <SortMenu
              sort={fullTextMode ? ftSort : sort}
              onSortChange={s => {
                if (fullTextMode) {
                  setFtSort(s);
                } else {
                  setSort(s);
                }
              }}
              options={fullTextMode ? FULL_TEXT_SORT_OPTIONS : SORT_OPTIONS}
            />
            <div className="ml-auto flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={handleImportSbobina}
                disabled={isImporting}
                className="filter-chip w-9 p-0 flex items-center justify-center group/import"
                title="Importa Sbobina (.sbobina)"
                aria-label="Importa Sbobina"
              >
                {isImporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4 transition-transform duration-200 opacity-80 group-hover/import:opacity-100 group-hover/import:scale-110 group-hover/import:-translate-y-0.5" />}
              </button>
              {onRefresh && (
                <button
                  type="button"
                  onClick={handleRefresh}
                  disabled={isRefreshing}
                  className="filter-chip w-9 p-0 flex items-center justify-center shrink-0 group/refresh"
                  title="Aggiorna archivio"
                  aria-label="Aggiorna archivio"
                >
                  <RefreshCw className={`w-4 h-4 transition-transform duration-500 ease-out ${isRefreshing ? 'animate-spin' : 'opacity-80 group-hover/refresh:opacity-100 group-hover/refresh:rotate-180 group-hover/refresh:scale-105'}`} />
                </button>
              )}
            </div>
          </div>
          {!fullTextMode && search.trim().length > 0 && (
            <span className="search-results-count">
              {allSortedSessions.length === 0
                ? 'Nessun risultato'
                : allSortedSessions.length === 1
                  ? '1 risultato'
                  : `${allSortedSessions.length} risultati`}
            </span>
          )}
          {fullTextMode && ftResults !== null && !isSearching && (
            <span className="search-results-count">
              {ftError
                ? ftError
                : ftResults.length === 0
                  ? `Nessun risultato per «${search.trim()}»`
                  : ftTotal !== null && ftTotal > ftResults.length
                    ? `${ftResults.length}+ sbobine trovate`
                    : ftResults.length === 1
                      ? '1 sbobina corrisponde'
                      : `${ftResults.length} sbobine corrispondono`}
            </span>
          )}
          {fullTextMode && search.trim().length > 0 && search.trim().length < 3 && (
            <span className="search-results-count">Digita almeno 3 caratteri</span>
          )}
        </div>

        <div className="flex flex-col gap-3">
          {!fullTextMode && sessionPageData.length === 0 && sessions.length === 0 && (
            <div className="py-12 text-center" style={{ color: 'var(--text-muted)' }}>
              <img src={MASCOT.sleep} alt="" className="w-40 mx-auto mb-3 select-none" draggable={false} />
              <p className="text-sm font-semibold">Ancora niente qui: le lezioni finite arrivano in archivio.</p>
            </div>
          )}

          {!fullTextMode && sessionPageData.length === 0 && sessions.length > 0 && search.trim() && (
            <div className="py-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
              {`Nessun risultato per "${search}"`}
            </div>
          )}

          {fullTextMode && (
            <div className="py-1">
              <FullTextResultList
                query={search.trim()}
                results={sortedFtResults}
                isSearching={isSearching}
                onPreview={(r) => onPreview(r.html_path, r.name, undefined, undefined, r.session_dir, search.trim())}
              />
              {ftResults !== null && ftResults.length === 0 && !isSearching && search.trim().length >= 3 && !ftError && (
                <div className="py-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
                  Nessun risultato nel testo delle sbobine per &ldquo;{search.trim()}&rdquo;
                </div>
              )}
            </div>
          )}

          {!fullTextMode && (
            <div className="py-1">
              <div className="flex flex-col gap-3">
                {sessionPageData.map(session => (
                  <DraggableSessionCard
                    key={session.session_dir}
                    session={session}
                    allFolders={folders}
                    currentFolder={sessionFolderMap.get(normalizeSessionPath(session.session_dir))}
                    editorSessionsMap={editorSessionsMap}
                    selected={selectedSessionDirs.has(session.session_dir)}
                    onToggleSelect={() => toggleSelectSession(session.session_dir)}
                    onAssignToFolder={fId => assignToFolder(session.session_dir, fId)}
                    onRemoveFromFolder={() => {
                      const f = sessionFolderMap.get(normalizeSessionPath(session.session_dir));
                      if (f) removeFromFolder(session.session_dir, f.id);
                    }}
                    onPreview={onPreview}
                    onOpenFile={onOpenFile}
                    onDeleteSession={onDeleteSession}
                    onRetryFailedRevisionBlocks={onRetryFailedRevisionBlocks}
                    onShareSession={setSharingSession}
                    courses={courseNames}
                    onSetCourse={(dir, course) => void handleSetCourse(dir, course)}
                    onRename={(dir, title) => void handleRename(dir, title)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Selection Action Bar */}
      <AnimatePresence>
        {selectedSessionDirs.size > 0 && (
          <ArchiveSelectionBar
            selectedCount={selectedSessionDirs.size}
            totalCount={sessionPageData.length}
            folders={folders}
            onSelectAll={selectAllSessions}
            onDeselectAll={handleDeselectOrRestore}
            onAssignToFolder={fId => bulkAssignToFolder(fId)}
            onNewFolder={() => setFolderModal({ type: 'create', pendingSessionDirs: Array.from(selectedSessionDirs) })}
            hasAssignedFolder={Array.from(selectedSessionDirs).some(d => sessionFolderMap.has(normalizeSessionPath(d)))}
            onRemoveFromFolder={() => bulkRemoveFromFolders()}
            onDeleteSelected={() => handleOpenDeleteMultiple()}
            onClose={clearSelection}
          />
        )}
      </AnimatePresence>

      {/* Archive modals */}
      {renderModals()}

    </div>
  );
}
