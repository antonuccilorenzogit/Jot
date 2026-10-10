import { reportClientError } from '../diagnostics';
import { useCallback, useState } from 'react';
import { normalizeSessionPath } from '../utils';
import type { EditorSaveController } from './useEditorAutosave';

export interface UseRegenerateDialogOptions {
  previewContent: string | null;
  previewSessionDir: string;
  closePreview: () => void;
  editorControllerRef?: React.RefObject<EditorSaveController | null>;
}

export function useRegenerateDialog({
  previewContent,
  previewSessionDir,
  closePreview,
  editorControllerRef,
}: UseRegenerateDialogOptions) {
  const [regeneratePrompt, setRegeneratePrompt] = useState<{ filename: string; mode?: 'completed' | 'resume'; sessionDir?: string } | null>(null);
  const [regenDirtyConfirm, setRegenDirtyConfirm] = useState<{ filename: string } | null>(null);
  const isPreviewOpen = previewContent !== null;

  const handleRegenerateAnswer = useCallback(async (ans: boolean | null) => {
    const currentPrompt = regeneratePrompt;
    setRegeneratePrompt(null);
    try {
      if (ans === true && isPreviewOpen) {
        const regenDir = normalizeSessionPath(currentPrompt?.sessionDir);
        const previewDir = normalizeSessionPath(previewSessionDir);
        if (regenDir && previewDir && regenDir === previewDir) {
          const ctrl = editorControllerRef?.current;
          const dirtyContent = ctrl
            ? ctrl.getDirtyContent()
            : (window as unknown as Record<string, () => unknown>).__jotGetDirtyEditorContent?.();
          if (dirtyContent) {
            const flushFn = ctrl?.flushPendingAutosave
              ?? (window as unknown as Record<string, () => Promise<boolean>>).__jotFlushPendingAutosave;
            if (flushFn) {
              const flushed = await flushFn();
              if (!flushed) {
                try {
                  if (window.pywebview?.api?.answer_regenerate) await window.pywebview.api.answer_regenerate(false);
                } catch (e) { reportClientError('Failed to send regen cancel after flush error:', e); }
                return;
              }
            }
            setRegenDirtyConfirm({ filename: currentPrompt?.filename ?? '' });
            return;
          }
          const cancelFn = ctrl?.cancelPendingAutosave
            ?? (window as unknown as Record<string, () => void>).__jotCancelPendingAutosave;
          cancelFn?.();
          closePreview();
        }
      }
      if (window.pywebview?.api?.answer_regenerate) await window.pywebview.api.answer_regenerate(ans);
    } catch (e) { reportClientError('Failed to send answer to Python:', e); }
  }, [closePreview, editorControllerRef, isPreviewOpen, previewSessionDir, regeneratePrompt]);

  const handleRegenDirtyConfirm = useCallback(async () => {
    setRegenDirtyConfirm(null);
    const ctrl = editorControllerRef?.current;
    const cancelFn = ctrl?.cancelPendingAutosave
      ?? (window as unknown as Record<string, () => void>).__jotCancelPendingAutosave;
    cancelFn?.();
    closePreview();
    try {
      if (window.pywebview?.api?.answer_regenerate) await window.pywebview.api.answer_regenerate(true);
    } catch (e) { reportClientError('Failed to send regen answer:', e); }
  }, [closePreview, editorControllerRef]);

  const handleRegenDirtyCancel = useCallback(async () => {
    setRegenDirtyConfirm(null);
    try {
      if (window.pywebview?.api?.answer_regenerate) await window.pywebview.api.answer_regenerate(false);
    } catch (e) { reportClientError('Failed to send regen cancel:', e); }
  }, []);

  return {
    regeneratePrompt,
    setRegeneratePrompt,
    regenDirtyConfirm,
    setRegenDirtyConfirm,
    handleRegenerateAnswer,
    handleRegenDirtyConfirm,
    handleRegenDirtyCancel,
  };
}
