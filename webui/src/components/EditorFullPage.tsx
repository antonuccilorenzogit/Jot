import React, { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ArrowLeft, Check, Copy, ExternalLink, FileDown, FileText, FileType, Headphones, Loader2, Moon, Plus, Sun } from 'lucide-react';
import { clickedTimeChip, requestAudioSeek, sectionTimeFor } from '../audioSeek';
import type { Heading } from './RichTextEditor';
import { normalizePreviewHtmlContent } from '../previewHtml';
import { prepareHtmlForClipboard } from '../utils';
import { ConfirmActionModal } from './modals/ConfirmActionModal';
import { useTheme } from '../hooks/useTheme';
import { useEditorAutosave, type EditorSaveController } from '../hooks/useEditorAutosave';
import { STORAGE_KEYS } from '../storageKeys';
import { getHostCapabilities } from '../browserHost';

const LazyAudioPlayer = React.lazy(() =>
  import('./AudioPlayer').then(m => ({ default: m.AudioPlayer }))
);
const LazyRichTextEditor = React.lazy(() =>
  import('./RichTextEditor').then(m => ({ default: m.RichTextEditor }))
);

export interface EditorDocumentProps {
  content: string | null;
  title: string;
  htmlPath: string;
  initScrollTop?: number;
  initialSearchTerm?: string;
}

export interface EditorAudioProps {
  src: string | null;
  relinkNeeded: boolean;
  onRelink: () => Promise<boolean | undefined>;
  onRemoveAudio?: () => Promise<boolean | undefined> | void;
  init: { time?: number; playbackRate?: number; volume?: number };
  onStateChange: (state: { currentTime: number; playbackRate: number; volume: number }) => void;
}

export interface EditorThemeProps {
  mode?: 'light' | 'dark';
  setMode?: React.Dispatch<React.SetStateAction<'light' | 'dark'>>;
}

export interface EditorFullPageProps {
  document?: EditorDocumentProps;
  audio?: EditorAudioProps;
  theme?: EditorThemeProps;
  onClose: () => void;
  onScrollTopChange?: (scrollTop: number) => void;
  saveControllerRef?: React.RefObject<EditorSaveController | null>;

  // Flat props for backwards compatibility
  previewContent?: string | null;
  previewTitle?: string;
  htmlPath?: string;
  audioSrc?: string | null;
  audioRelinkNeeded?: boolean;
  onRelink?: () => Promise<boolean | undefined>;
  onRemoveAudio?: () => Promise<boolean | undefined> | void;
  previewInitAudio?: { time?: number; playbackRate?: number; volume?: number };
  previewInitScrollTop?: number | undefined;
  initialSearchTerm?: string;
  themeMode?: 'light' | 'dark';
  setThemeMode?: React.Dispatch<React.SetStateAction<'light' | 'dark'>>;
  onAudioStateChange?: (state: { currentTime: number; playbackRate: number; volume: number }) => void;
}

export function EditorFullPage({
  document: docProp,
  audio: audioProp,
  theme: themeProp,
  onClose,
  onScrollTopChange: propOnScrollTopChange,
  saveControllerRef,
  previewContent: flatPreviewContent,
  previewTitle: flatPreviewTitle,
  htmlPath: flatHtmlPath,
  audioSrc: flatAudioSrc,
  audioRelinkNeeded: flatAudioRelinkNeeded,
  onRelink: flatOnRelink,
  onRemoveAudio: flatOnRemoveAudio,
  previewInitAudio: flatPreviewInitAudio,
  previewInitScrollTop: flatPreviewInitScrollTop,
  initialSearchTerm: flatInitialSearchTerm,
  themeMode: flatThemeMode,
  setThemeMode: flatSetThemeMode,
  onAudioStateChange: flatOnAudioStateChange,
}: EditorFullPageProps) {
  const previewContent = docProp?.content !== undefined ? docProp.content : (flatPreviewContent ?? null);
  const previewTitle = docProp?.title ?? flatPreviewTitle ?? '';
  const htmlPath = docProp?.htmlPath ?? flatHtmlPath ?? '';
  const previewInitScrollTop = docProp?.initScrollTop ?? flatPreviewInitScrollTop;
  const initialSearchTerm = docProp?.initialSearchTerm ?? flatInitialSearchTerm;

  const audioSrc = audioProp?.src !== undefined ? audioProp.src : (flatAudioSrc ?? null);
  const audioRelinkNeeded = audioProp?.relinkNeeded ?? flatAudioRelinkNeeded ?? false;
  const onRelink = audioProp?.onRelink ?? flatOnRelink ?? (() => Promise.resolve(undefined));
  const onRemoveAudio = audioProp?.onRemoveAudio ?? flatOnRemoveAudio;
  const previewInitAudio = audioProp?.init ?? flatPreviewInitAudio ?? {};
  const onAudioStateChange = audioProp?.onStateChange ?? flatOnAudioStateChange ?? (() => {});

  const propThemeMode = themeProp?.mode ?? flatThemeMode;
  const propSetThemeMode = themeProp?.setMode ?? flatSetThemeMode;
  const onScrollTopChange = propOnScrollTopChange ?? (() => {});
  const fallbackTheme = useTheme();
  const themeMode = propThemeMode ?? fallbackTheme.themeMode;
  const setThemeMode = propSetThemeMode ?? fallbackTheme.setThemeMode;
  const [isTocOpen, setIsTocOpen] = useState(false);
  const [headings, setHeadings] = useState<Heading[]>([]);
  const [isCopied, setIsCopied] = useState(false);
  const [relinkSuccess, setRelinkSuccess] = useState(false);
  const [isRelinking, setIsRelinking] = useState(false);
  const [isRemovingAudio, setIsRemovingAudio] = useState(false);
  const [showConfirmRemove, setShowConfirmRemove] = useState(false);
  const relinkTimerRef = useRef<number | null>(null);
  const copiedTimerRef = useRef<number | null>(null);
  const getHtmlRef = useRef<(() => string) | null>(null);

  const [zoomLevel, setZoomLevel] = useState<number>(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.EDITOR_ZOOM);
    if (stored) {
      const n = parseInt(stored, 10);
      if (!isNaN(n) && n >= 50 && n <= 200) return n;
    }
    return 100;
  });

  const handleZoomChange = useCallback((level: number) => {
    const clamped = Math.max(50, Math.min(200, level));
    setZoomLevel(clamped);
    try { localStorage.setItem(STORAGE_KEYS.EDITOR_ZOOM, String(clamped)); } catch (_) {}
  }, []);

  const zoomLevelRef = useRef(zoomLevel);
  useEffect(() => { zoomLevelRef.current = zoomLevel; }, [zoomLevel]);

  useEffect(() => {
    if (copiedTimerRef.current) { window.clearTimeout(copiedTimerRef.current); copiedTimerRef.current = null; }
    setIsCopied(false);
    setRelinkSuccess(false);
    setIsTocOpen(false);
  }, [previewContent]);

  useEffect(() => {
    return () => {
      if (relinkTimerRef.current) window.clearTimeout(relinkTimerRef.current);
      if (copiedTimerRef.current) window.clearTimeout(copiedTimerRef.current);
    };
  }, []);

  const {
    autosaveStatus,
    lastPersistedRef,
    scheduleAutosave,
    flushAndClose,
  } = useEditorAutosave({
    htmlPath,
    previewContent,
    getHtmlRef,
    onClose,
    saveControllerRef,
  });

  useEffect(() => {
    if (previewContent === null) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { void flushAndClose(); return; }
      if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
        e.preventDefault();
        handleZoomChange(zoomLevelRef.current + 10);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === '-') {
        e.preventDefault();
        handleZoomChange(zoomLevelRef.current - 10);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === '0') {
        e.preventDefault();
        handleZoomChange(100);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [previewContent, flushAndClose, handleZoomChange]);

  const handleCopy = async () => {
    const rawHtml = getHtmlRef.current?.() ?? lastPersistedRef.current;
    const normalizedHtml = normalizePreviewHtmlContent(rawHtml);
    const clipboardHtml = await prepareHtmlForClipboard(normalizedHtml);
    const temp = document.createElement('div');
    temp.innerHTML = clipboardHtml;
    try {
      const htmlBlob = new Blob([clipboardHtml], { type: 'text/html' });
      const textBlob = new Blob([temp.textContent || temp.innerText || ''], { type: 'text/plain' });
      await navigator.clipboard.write([new ClipboardItem({ 'text/html': htmlBlob, 'text/plain': textBlob })]);
    } catch (_) { navigator.clipboard.writeText(temp.textContent || temp.innerText || ''); }
    setIsCopied(true);
    if (copiedTimerRef.current) window.clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = window.setTimeout(() => setIsCopied(false), 2000);
  };

  const handleExportPdf = (textOnly = false) => {
    const classes = textOnly ? ['is-printing-notes', 'is-printing-text-only'] : ['is-printing-notes'];
    document.documentElement.classList.remove('is-printing-notes', 'is-printing-text-only');
    document.documentElement.classList.add(...classes);
    const done = () => {
      document.documentElement.classList.remove(...classes);
      window.removeEventListener('afterprint', done);
    };
    window.addEventListener('afterprint', done);
    try {
      window.print();
    } finally {
      // Some hosts never fire afterprint.
      window.setTimeout(done, 1500);
    }
  };

  // Click on the time chip of a section (or Alt+click anywhere in it): the audio jumps there.
  const handleBodyClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!audioSrc) return;
    const target = e.target as Element | null;
    const root = target?.closest('.tiptap-editor .ProseMirror, .tiptap-editor');
    if (!target || !root) return;
    const heading = target.closest('[data-t]');
    if (heading && clickedTimeChip(heading, e.clientX)) {
      e.preventDefault();
      requestAudioSeek(Number(heading.getAttribute('data-t')));
      return;
    }
    if (e.altKey) {
      const time = sectionTimeFor(target, root.querySelector('.ProseMirror') ?? root);
      if (time !== null) {
        e.preventDefault();
        requestAudioSeek(time);
      }
    }
  };

  const scrollToHeading = (heading: Heading) => {
    const { text, level, id } = heading;
    const idx = headings.findIndex(h => h.id === id);
    if (idx === -1) return;
    const occurrencesBefore = headings
      .slice(0, idx)
      .filter(h => h.level === level && h.text.trim() === text.trim())
      .length;
    const els = Array.from(document.querySelectorAll(`.tiptap-editor h${level}`))
      .filter(el => el.textContent?.trim() === text.trim());
    els[occurrencesBefore]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <AnimatePresence>
      {previewContent !== null && (
        <motion.div
          className="editor-fullpage"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12, ease: 'easeOut' }}
        >
          <div className="editor-fullpage-header">
            <button
              className="editor-fullpage-back"
              onClick={() => void flushAndClose()}
              title={autosaveStatus === 'error' ? 'Chiudi senza salvare' : 'Torna indietro'}
              aria-label={autosaveStatus === 'error' ? 'Chiudi senza salvare' : 'Torna indietro'}
            >
              <ArrowLeft className="w-4 h-4" />
            </button>

            <div className="editor-fullpage-title">
              <FileText className="w-4 h-4 shrink-0" style={{ color: 'var(--text-muted)' }} />
              <span className="truncate">{previewTitle}</span>
              <span
                className="editor-autosave-badge shrink-0"
                style={{
                  color:
                    autosaveStatus === 'error' ? 'var(--error-text)'
                    : autosaveStatus === 'saved' ? 'var(--success-text)'
                    : 'var(--text-muted)',
                  borderColor:
                    autosaveStatus === 'error' ? 'var(--error-ring)'
                    : autosaveStatus === 'saved' ? 'var(--success-ring)'
                    : 'var(--border-subtle)',
                }}
              >
                {autosaveStatus === 'saving' ? (
                  <>
                    <Loader2 className="w-3 h-3 animate-spin mr-1.5" />
                    <span>Autosave</span>
                  </>
                ) : autosaveStatus === 'saved' ? (
                  <>
                    <Check className="w-3 h-3 mr-1.5" />
                    <span>Salvato</span>
                  </>
                ) : autosaveStatus === 'error' ? (
                  <span>Errore salvataggio</span>
                ) : (
                  <span>Autosave</span>
                )}
              </span>
            </div>

            <div className="editor-fullpage-actions">
              <button
                onClick={() => void handleCopy()}
                className="icon-button"
                style={isCopied ? { borderColor: 'var(--success-ring)', color: 'var(--success-text)' } : {}}
                title={isCopied ? 'Copiato!' : 'Copia per Google Docs'}
                aria-label="Copia per Google Docs"
              >
                {isCopied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              </button>
              {htmlPath && getHostCapabilities().openLocalPath && (
                <button
                  onClick={() => window.pywebview?.api?.open_file?.(htmlPath)}
                  className="icon-button"
                  title="Apri file HTML"
                  aria-label="Apri file HTML"
                >
                  <ExternalLink className="w-4 h-4" />
                </button>
              )}
              <button
                onClick={() => handleExportPdf()}
                className="icon-button"
                title="Esporta PDF"
                aria-label="Esporta PDF"
              >
                <FileDown className="w-4 h-4" />
              </button>
              <button
                onClick={() => handleExportPdf(true)}
                className="icon-button"
                title="Esporta PDF solo testo (senza immagini)"
                aria-label="Esporta PDF solo testo"
              >
                <FileType className="w-4 h-4" />
              </button>
              <button
                onClick={() => setThemeMode(prev => prev === 'dark' ? 'light' : 'dark')}
                className="icon-button theme-toggle-btn"
                aria-label={themeMode === 'dark' ? 'Attiva tema chiaro' : 'Attiva tema scuro'}
                title={themeMode === 'dark' ? 'Tema chiaro' : 'Tema scuro'}
              >
                {themeMode === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className={`editor-fullpage-body${audioSrc ? ' has-audio-timeline' : ''}`} onClickCapture={handleBodyClick}>
            <Suspense fallback={<div className="p-6 text-sm" style={{ color: 'var(--text-muted)' }}>Caricamento editor...</div>}>
              <LazyRichTextEditor
                key={htmlPath}
                initialContent={previewContent}
                onChange={scheduleAutosave}
                onEditorReady={getHtml => { getHtmlRef.current = getHtml; }}
                initialScrollTop={previewInitScrollTop}
                initialSearchTerm={initialSearchTerm}
                onScrollTopChange={onScrollTopChange}
                onHeadingsChange={setHeadings}
                isTocOpen={isTocOpen}
                onTocToggle={() => setIsTocOpen(p => !p)}
                tocHeadings={headings}
                onScrollToHeading={scrollToHeading}
                zoomLevel={zoomLevel}
                onZoomChange={handleZoomChange}
              />
            </Suspense>

            <div className="editor-fullpage-footer shrink-0 border-t px-4 sm:px-5" style={{ background: 'var(--editor-chrome-bg)', borderColor: 'var(--border-subtle)' }}>
              {audioSrc ? (
                <Suspense fallback={<div className="p-4 text-sm" style={{ color: 'var(--text-muted)' }}>Caricamento player...</div>}>
                  <LazyAudioPlayer
                    src={audioSrc}
                    initialTime={previewInitAudio.time}
                    initialPlaybackRate={previewInitAudio.playbackRate}
                    initialVolume={previewInitAudio.volume}
                    onStateChange={onAudioStateChange}
                    onRelink={onRelink}
                    onRemoveAudio={onRemoveAudio}
                  />
                </Suspense>
              ) : audioRelinkNeeded ? (
                <div className="flex items-center justify-between gap-3 py-3.5">
                  <div className="min-w-0">
                    <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>Audio non trovato</p>
                    <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                      Il file originale è stato spostato. Selezionalo di nuovo per riattivare il player.
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {onRemoveAudio && (
                      <button
                        type="button"
                        onClick={() => setShowConfirmRemove(true)}
                        disabled={isRemovingAudio}
                        className="premium-button-secondary compact-button shrink-0"
                        title="Rimuovi audio dalla sbobina"
                        aria-label="Rimuovi audio dalla sbobina"
                      >
                        {isRemovingAudio ? 'Rimozione...' : 'Rimuovi audio'}
                      </button>
                    )}
                    <button
                      onClick={async () => {
                        if (isRelinking) return;
                        setIsRelinking(true);
                        try {
                          const ok = await onRelink();
                          if (ok) {
                            if (relinkTimerRef.current) window.clearTimeout(relinkTimerRef.current);
                            setRelinkSuccess(true);
                            relinkTimerRef.current = window.setTimeout(() => setRelinkSuccess(false), 3000);
                          }
                        } finally { setIsRelinking(false); }
                      }}
                      disabled={isRelinking}
                      className="premium-button-secondary compact-button shrink-0"
                      style={relinkSuccess ? { borderColor: 'var(--success-ring)', color: 'var(--success-text)' } : {}}
                    >
                      {relinkSuccess ? <><Check className="w-3.5 h-3.5" /> Ricollegato</> : isRelinking ? 'Selezione...' : 'Ricollega audio'}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-between gap-3 py-3.5">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                      style={{ background: 'var(--bg-panel)', color: 'var(--text-muted)' }}
                    >
                      <Headphones className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium leading-none mb-1" style={{ color: 'var(--text-primary)' }}>Nessun audio collegato</p>
                      <p className="text-xs leading-none" style={{ color: 'var(--text-muted)' }}>
                        Collega un file audio per sincronizzarlo con la sbobina.
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={async () => {
                        if (isRelinking) return;
                        setIsRelinking(true);
                        try {
                          const ok = await onRelink();
                          if (ok) {
                            if (relinkTimerRef.current) window.clearTimeout(relinkTimerRef.current);
                            setRelinkSuccess(true);
                            relinkTimerRef.current = window.setTimeout(() => setRelinkSuccess(false), 3000);
                          }
                        } finally {
                          setIsRelinking(false);
                        }
                      }}
                      disabled={isRelinking}
                      className="premium-button compact-button shrink-0 flex items-center gap-1.5"
                    >
                      {isRelinking ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span>Selezione...</span>
                        </>
                      ) : (
                        <>
                          <Plus className="w-3.5 h-3.5" />
                          <span>Aggiungi audio</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          <ConfirmActionModal
            isOpen={showConfirmRemove}
            title="Rimuovere l'audio mancante?"
            description="Il riferimento al file audio verrà rimosso dalla sbobina. Il file sul tuo computer non verrà toccato e potrai aggiungere un nuovo audio in qualsiasi momento."
            confirmLabel={isRemovingAudio ? 'Rimozione...' : 'Rimuovi audio'}
            cancelLabel="Annulla"
            onClose={() => setShowConfirmRemove(false)}
            onConfirm={async () => {
              setShowConfirmRemove(false);
              if (isRemovingAudio) return;
              setIsRemovingAudio(true);
              try {
                await onRemoveAudio?.();
              } finally {
                setIsRemovingAudio(false);
              }
            }}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
