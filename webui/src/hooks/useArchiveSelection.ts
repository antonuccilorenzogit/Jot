import { useCallback, useEffect, useRef, useState } from 'react';
import type { ArchiveFolder, ArchiveSession } from '../bridge';
import { normalizeSessionPath } from '../utils';
import type { DeleteMultipleSessionsConfirmState } from '../components/archive/types';

export interface UseArchiveSelectionOptions {
  sessions: ArchiveSession[];
  folders: ArchiveFolder[];
  onFoldersChange: (folders: ArchiveFolder[]) => void;
  sessionPageData: ArchiveSession[];
  onDeleteMultipleSessions?: (sessions: { sessionDir: string; name: string }[]) => void;
  setDeleteMultipleConfirm: React.Dispatch<React.SetStateAction<DeleteMultipleSessionsConfirmState | null>>;
}

export function useArchiveSelection({
  sessions,
  folders,
  onFoldersChange,
  sessionPageData,
  onDeleteMultipleSessions,
  setDeleteMultipleConfirm,
}: UseArchiveSelectionOptions) {
  const [selectedSessionDirs, setSelectedSessionDirs] = useState<Set<string>>(new Set());
  const prevManualSelectionRef = useRef<Set<string> | null>(null);

  useEffect(() => {
    if (selectedSessionDirs.size === 0) return;
    const existingDirs = new Set(sessions.map((s) => normalizeSessionPath(s.session_dir)));
    setSelectedSessionDirs((prev) => {
      const filtered = new Set([...prev].filter((d) => existingDirs.has(normalizeSessionPath(d))));
      return filtered.size === prev.size ? prev : filtered;
    });
  }, [sessions, selectedSessionDirs.size]);

  const assignToFolder = useCallback(
    (sessionDir: string, folderId: string) => {
      const normTarget = normalizeSessionPath(sessionDir);
      const next = folders.map((f) => {
        if (f.id === folderId) {
          if (f.session_dirs.some((d) => normalizeSessionPath(d) === normTarget)) return f;
          return { ...f, session_dirs: [...f.session_dirs, sessionDir] };
        }
        return { ...f, session_dirs: f.session_dirs.filter((d) => normalizeSessionPath(d) !== normTarget) };
      });
      onFoldersChange(next);
    },
    [folders, onFoldersChange]
  );

  const removeFromFolder = useCallback(
    (sessionDir: string, folderId: string) => {
      const normTarget = normalizeSessionPath(sessionDir);
      const next = folders.map((f) =>
        f.id === folderId
          ? { ...f, session_dirs: f.session_dirs.filter((d) => normalizeSessionPath(d) !== normTarget) }
          : f
      );
      onFoldersChange(next);
    },
    [folders, onFoldersChange]
  );

  const toggleSelectSession = useCallback((dir: string) => {
    setSelectedSessionDirs((prev) => {
      const next = new Set(prev);
      if (next.has(dir)) next.delete(dir);
      else next.add(dir);
      prevManualSelectionRef.current = next.size > 0 ? new Set(next) : null;
      return next;
    });
  }, []);

  const selectAllSessions = useCallback(() => {
    if (selectedSessionDirs.size < sessionPageData.length && selectedSessionDirs.size > 0) {
      prevManualSelectionRef.current = new Set(selectedSessionDirs);
    }
    setSelectedSessionDirs(new Set(sessionPageData.map((s) => s.session_dir)));
  }, [sessionPageData, selectedSessionDirs]);

  const handleDeselectOrRestore = useCallback(() => {
    if (
      prevManualSelectionRef.current &&
      prevManualSelectionRef.current.size > 0 &&
      prevManualSelectionRef.current.size < sessionPageData.length
    ) {
      setSelectedSessionDirs(new Set(prevManualSelectionRef.current));
      prevManualSelectionRef.current = null;
    } else {
      setSelectedSessionDirs(new Set());
      prevManualSelectionRef.current = null;
    }
  }, [sessionPageData.length]);

  const clearSelection = useCallback(() => {
    setSelectedSessionDirs(new Set());
    prevManualSelectionRef.current = null;
  }, []);

  const bulkAssignToFolder = useCallback(
    (folderId: string, customDirs?: string[]) => {
      const targetDirs = customDirs ?? Array.from(selectedSessionDirs);
      const normDirSet = new Set(targetDirs.map((d) => normalizeSessionPath(d)));
      const next = folders.map((f) => {
        if (f.id === folderId) {
          const existingNorm = new Set(f.session_dirs.map((d) => normalizeSessionPath(d)));
          const toAdd = targetDirs.filter((d) => !existingNorm.has(normalizeSessionPath(d)));
          return { ...f, session_dirs: [...f.session_dirs, ...toAdd] };
        }
        return { ...f, session_dirs: f.session_dirs.filter((d) => !normDirSet.has(normalizeSessionPath(d))) };
      });
      onFoldersChange(next);
      if (!customDirs) clearSelection();
    },
    [folders, onFoldersChange, selectedSessionDirs, clearSelection]
  );

  const bulkRemoveFromFolders = useCallback(
    (customDirs?: string[]) => {
      const targetDirs = customDirs ?? Array.from(selectedSessionDirs);
      const normDirSet = new Set(targetDirs.map((d) => normalizeSessionPath(d)));
      const next = folders.map((f) => ({
        ...f,
        session_dirs: f.session_dirs.filter((d) => !normDirSet.has(normalizeSessionPath(d))),
      }));
      onFoldersChange(next);
      if (!customDirs) clearSelection();
    },
    [folders, onFoldersChange, selectedSessionDirs, clearSelection]
  );

  const handleOpenDeleteMultiple = useCallback(
    (targets?: { sessionDir: string; name: string }[]) => {
      const list =
        targets ??
        sessionPageData
          .filter((s) => selectedSessionDirs.has(s.session_dir))
          .map((s) => ({ sessionDir: s.session_dir, name: s.name }));
      if (list.length === 0) return;
      if (onDeleteMultipleSessions) {
        onDeleteMultipleSessions(list);
      } else {
        setDeleteMultipleConfirm({ sessions: list });
      }
    },
    [sessionPageData, selectedSessionDirs, onDeleteMultipleSessions, setDeleteMultipleConfirm]
  );

  return {
    selectedSessionDirs,
    setSelectedSessionDirs,
    assignToFolder,
    removeFromFolder,
    toggleSelectSession,
    selectAllSessions,
    handleDeselectOrRestore,
    clearSelection,
    bulkAssignToFolder,
    bulkRemoveFromFolders,
    handleOpenDeleteMultiple,
  };
}
