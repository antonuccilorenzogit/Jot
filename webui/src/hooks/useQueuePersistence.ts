import { type Dispatch, useEffect, useLayoutEffect, useRef } from 'react';
import type { FileItem, ProcessingAction } from '../appState';
import { STORAGE_KEYS } from '../storageKeys';

const QUEUE_STORAGE_KEY = STORAGE_KEYS.QUEUE_V1;

export function serializeQueueFile(file: FileItem): Record<string, unknown> {
  return {
    id: file.id,
    name: file.name,
    size: file.size,
    duration: file.duration,
    path: file.path,
    status: file.status,
    outputHtml: file.outputHtml,
    outputDir: file.outputDir,
    errorText: file.errorText,
    errorDetail: file.errorDetail,
    completedAt: file.completedAt,
    primaryModel: file.primaryModel,
    effectiveModel: file.effectiveModel,
    completionStatus: file.completionStatus,
    revisionFailedBlocks: file.revisionFailedBlocks,
    resumeSession: file.resumeSession,
    allowCompletedDestroy: file.allowCompletedDestroy,
    ...(file.kind === 'notes' ? { kind: 'notes', notes: file.notes } : {}),
    ...(file.title ? { title: file.title } : {}),
    ...(file.course ? { course: file.course } : {}),
    ...(file.lesson ? { lesson: file.lesson } : {}),
  };
}

function restoreLesson(lesson: FileItem['lesson']): FileItem['lesson'] | undefined {
  if (!lesson || typeof lesson !== 'object') return undefined;
  const text = (v: unknown) => (v ? String(v) : undefined);
  const restored = {
    slidesPath: text(lesson.slidesPath),
    slidesName: text(lesson.slidesName),
    slidesCount: lesson.slidesCount ? Number(lesson.slidesCount) : undefined,
    bookPath: text(lesson.bookPath),
    bookName: text(lesson.bookName),
    bookPages: text(lesson.bookPages),
  };
  return restored.slidesPath || restored.bookPath ? restored : undefined;
}

export function deserializeQueueFile(file: Partial<FileItem>, index: number): FileItem {
  return {
    id: String(file.id || `restored-${index}`),
    name: String(file.name || `file-${index}`),
    size: Number(file.size || 0),
    duration: Number(file.duration || 0),
    path: file.path ? String(file.path) : undefined,
    status: file.status === 'done' ? 'done' : file.status === 'error' ? 'error' : 'queued',
    progress: file.status === 'done' ? 100 : 0,
    phase: file.status === 'done' ? 3 : 0,
    outputHtml: file.outputHtml ? String(file.outputHtml) : undefined,
    outputDir: file.outputDir ? String(file.outputDir) : undefined,
    errorText: file.errorText ? String(file.errorText) : undefined,
    errorDetail: file.errorDetail ? String(file.errorDetail) : undefined,
    completedAt: file.completedAt ? Number(file.completedAt) : undefined,
    primaryModel: file.primaryModel ? String(file.primaryModel) : undefined,
    effectiveModel: file.effectiveModel ? String(file.effectiveModel) : undefined,
    completionStatus: file.completionStatus === 'completed_with_warnings' ? 'completed_with_warnings' : 'completed',
    revisionFailedBlocks: Array.isArray(file.revisionFailedBlocks)
      ? file.revisionFailedBlocks.map(Number).filter(n => Number.isFinite(n) && n > 0)
      : [],
    resumeSession: file.resumeSession === false ? false : undefined,
    allowCompletedDestroy: file.allowCompletedDestroy ? true : undefined,
    ...(file.kind === 'notes'
      ? {
          kind: 'notes' as const,
          notes: {
            slides: Number(file.notes?.slides || 0),
            bookPath: file.notes?.bookPath ? String(file.notes.bookPath) : undefined,
            bookName: file.notes?.bookName ? String(file.notes.bookName) : undefined,
            bookPages: file.notes?.bookPages ? String(file.notes.bookPages) : undefined,
            slidesPerChunk: file.notes?.slidesPerChunk ? Number(file.notes.slidesPerChunk) : undefined,
            bookMode: file.notes?.bookMode === 'auto' ? 'auto' : file.notes?.bookMode === 'full' ? 'full' : undefined,
          },
        }
      : {}),
    ...(file.title ? { title: String(file.title) } : {}),
    ...(file.course ? { course: String(file.course) } : {}),
    ...(restoreLesson(file.lesson) ? { lesson: restoreLesson(file.lesson) } : {}),
  };
}

export function loadPersistedQueue(): FileItem[] {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return [];
    const raw = window.localStorage.getItem(QUEUE_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return [];
    return parsed.map(deserializeQueueFile);
  } catch {
    return [];
  }
}

export function useQueuePersistence(
  files: FileItem[],
  structuralVersion: number,
  dispatch: Dispatch<ProcessingAction>,
  appendConsole: (msg: string) => void,
) {
  const hasRestoredQueueRef = useRef(false);
  const filesRef = useRef(files);
  useLayoutEffect(() => {
    filesRef.current = files;
  }, [files]);

  useEffect(() => {
    if (hasRestoredQueueRef.current) return;
    hasRestoredQueueRef.current = true;
    if (filesRef.current.length > 0) {
      appendConsole(`Coda ripristinata: ${filesRef.current.length} file.`);
      return;
    }
    try {
      const restoredFiles = loadPersistedQueue();
      if (restoredFiles.length === 0) return;

      dispatch({ type: 'queue/add', files: restoredFiles });
      appendConsole(`Coda ripristinata: ${restoredFiles.length} file.`);
    } catch (error) {
      appendConsole(`[ERRORE] Ripristino coda fallito: ${error}`);
    }
  }, [appendConsole, dispatch]);

  useEffect(() => {
    if (structuralVersion === 0) return; // skip initial mount – restore hasn’t run yet
    try {
      const currentFiles = filesRef.current;
      if (currentFiles.length === 0) {
        window.localStorage.removeItem(QUEUE_STORAGE_KEY);
        return;
      }
      const persisted = currentFiles.map(serializeQueueFile);
      window.localStorage.setItem(QUEUE_STORAGE_KEY, JSON.stringify(persisted));
    } catch (error) {
      appendConsole(`[ERRORE] Persistenza coda fallita: ${error}`);
    }
  }, [structuralVersion, appendConsole]);
}
