import { useCallback, useEffect, useRef, useState } from 'react';
import type { SaveHtmlResult } from '../bridge';
import { nextHtmlAutosaveGeneration, seedHtmlAutosaveGeneration } from '../autosaveGeneration';

const isSaveCommitted = (res: SaveHtmlResult) => res.ok && res.saved !== false;
export type AutosaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface EditorSaveController {
  getDirtyContent: () => { path: string; content: string } | null;
  flushPendingAutosave: () => Promise<boolean>;
  cancelPendingAutosave: () => void;
}

export interface UseEditorAutosaveOptions {
  htmlPath: string;
  previewContent: string | null;
  getHtmlRef: React.MutableRefObject<(() => string) | null>;
  onClose: () => void;
  saveControllerRef?: React.RefObject<EditorSaveController | null>;
}

export function useEditorAutosave({
  htmlPath,
  previewContent,
  getHtmlRef,
  onClose,
  saveControllerRef,
}: UseEditorAutosaveOptions) {
  const [autosaveStatus, setAutosaveStatus] = useState<AutosaveStatus>('idle');
  const isDirtyRef = useRef(false);
  const lastPersistedRef = useRef(previewContent ?? '');
  const autosaveTimerRef = useRef<number | null>(null);
  const [autosaveGenSeed] = useState(() => seedHtmlAutosaveGeneration(htmlPath));
  const autosaveGenRef = useRef(autosaveGenSeed);
  const saveErrorOnCloseRef = useRef(false);
  const htmlPathRef = useRef(htmlPath);

  useEffect(() => {
    htmlPathRef.current = htmlPath;
    autosaveGenRef.current = seedHtmlAutosaveGeneration(htmlPath);
  }, [htmlPath]);

  useEffect(() => {
    lastPersistedRef.current = previewContent ?? '';
    isDirtyRef.current = false;
    saveErrorOnCloseRef.current = false;
    setAutosaveStatus('idle');
  }, [previewContent]);

  useEffect(() => {
    const autosaveGenRefAtCleanup = autosaveGenRef;
    const getHtmlAtCleanup = getHtmlRef;
    return () => {
      if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
      if (!isDirtyRef.current || saveErrorOnCloseRef.current) return;
      const path = htmlPathRef.current;
      const snap = getHtmlAtCleanup.current?.() ?? '';
      if (path && snap && snap !== lastPersistedRef.current) {
        const gen = nextHtmlAutosaveGeneration(path);
        autosaveGenRefAtCleanup.current = gen;
        void window.pywebview?.api?.save_html_content(path, snap, gen);
      }
    };
  }, [getHtmlRef]);

  const getDirtyContent = useCallback((): { path: string; content: string } | null => {
    if (!isDirtyRef.current) return null;
    const path = htmlPathRef.current;
    if (!path) return null;
    const snap = getHtmlRef.current?.() ?? '';
    if (snap === lastPersistedRef.current) return null;
    return { path, content: snap };
  }, [getHtmlRef]);

  const cancelPendingAutosave = useCallback(() => {
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    isDirtyRef.current = false;
  }, []);

  const flushPendingAutosave = useCallback(async (): Promise<boolean> => {
    if (!isDirtyRef.current) return true;
    if (saveErrorOnCloseRef.current) return false;
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    const path = htmlPathRef.current;
    const snap = getHtmlRef.current?.() ?? '';
    if (!path) return true;
    if (snap && snap !== lastPersistedRef.current && window.pywebview?.api?.save_html_content) {
      const gen = nextHtmlAutosaveGeneration(path);
      autosaveGenRef.current = gen;
      try {
        const res = await window.pywebview.api.save_html_content(path, snap, gen);
        if (isSaveCommitted(res)) {
          lastPersistedRef.current = snap;
          if (gen === autosaveGenRef.current) isDirtyRef.current = false;
          return true;
        }
        saveErrorOnCloseRef.current = true;
        setAutosaveStatus('error');
        return false;
      } catch (_) {
        saveErrorOnCloseRef.current = true;
        setAutosaveStatus('error');
        return false;
      }
    }
    return true;
  }, [getHtmlRef]);

  useEffect(() => {
    if (saveControllerRef) {
      saveControllerRef.current = {
        getDirtyContent,
        flushPendingAutosave,
        cancelPendingAutosave,
      };
    }
    const win = window as unknown as Record<string, unknown>;
    win.__jotGetDirtyEditorContent = getDirtyContent;
    win.__jotFlushPendingAutosave = flushPendingAutosave;
    win.__jotCancelPendingAutosave = cancelPendingAutosave;
    return () => {
      if (saveControllerRef) {
        saveControllerRef.current = null;
      }
      delete win.__jotGetDirtyEditorContent;
      delete win.__jotFlushPendingAutosave;
      delete win.__jotCancelPendingAutosave;
    };
  }, [saveControllerRef, getDirtyContent, flushPendingAutosave, cancelPendingAutosave]);

  const flushAndClose = useCallback(async () => {
    if (saveErrorOnCloseRef.current) {
      cancelPendingAutosave();
    } else if (!await flushPendingAutosave()) return;
    onClose();
  }, [flushPendingAutosave, cancelPendingAutosave, onClose]);

  const scheduleAutosave = useCallback(() => {
    if (!htmlPath || previewContent === null) return;
    isDirtyRef.current = true;
    saveErrorOnCloseRef.current = false;
    if (autosaveTimerRef.current) window.clearTimeout(autosaveTimerRef.current);
    const savedForPath = htmlPath;
    const gen = nextHtmlAutosaveGeneration(savedForPath);
    autosaveGenRef.current = gen;
    autosaveTimerRef.current = window.setTimeout(async () => {
      if (!isDirtyRef.current || !window.pywebview?.api?.save_html_content) return;
      const snap = getHtmlRef.current?.() ?? '';
      if (snap === lastPersistedRef.current) {
        isDirtyRef.current = false;
        return;
      }

      setAutosaveStatus('saving');
      try {
        const res = await window.pywebview.api.save_html_content(savedForPath, snap, gen);
        if (htmlPathRef.current !== savedForPath) return;
        if (gen !== autosaveGenRef.current) return;
        if (isSaveCommitted(res)) {
          lastPersistedRef.current = snap;
          isDirtyRef.current = false;
          setAutosaveStatus('saved');
        } else {
          setAutosaveStatus('error');
        }
      } catch {
        setAutosaveStatus('error');
      }
    }, 700);
  }, [htmlPath, previewContent, getHtmlRef]);

  useEffect(() => {
    if (autosaveStatus !== 'saved') return;
    let cancelled = false;
    const id = window.setTimeout(() => {
      if (!cancelled) setAutosaveStatus('idle');
    }, 1500);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [autosaveStatus]);

  return {
    autosaveStatus,
    isDirtyRef,
    lastPersistedRef,
    scheduleAutosave,
    flushAndClose,
  };
}
