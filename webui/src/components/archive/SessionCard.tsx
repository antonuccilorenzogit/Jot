import { useState, type MouseEvent } from 'react';
import {
  AlertTriangle, Check, ChevronLeft, ChevronRight, Download, ExternalLink,
  Eye, FileText, Folder, FolderOpen, GraduationCap, NotebookPen, Pencil, RotateCcw, Trash2, X,
} from 'lucide-react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { ArchiveFolder, ArchiveSession } from '../../bridge';
import { loadAllEditorSessions, type EditorSession } from '../../editorSessions';
import { formatRelativeTime, shortModelName } from '../../utils';
import { KebabMenu, type KebabMenuItem } from '../KebabMenu';
import { FolderIndicatorChip } from '../FolderChip';
import { type ArchivePageProps, getOpenedAtMs, DEFAULT_FOLDER_COLOR } from './types';

/** "Apri sintesi" and "Apri cartella del corso" when the lesson has them. */
function courseOutputItems(
  session: ArchiveSession,
  onPreview: ArchivePageProps['onPreview'],
  onOpenFile: ArchivePageProps['onOpenFile'],
): KebabMenuItem[] {
  const items: KebabMenuItem[] = [];
  if (session.summary_html) {
    const summaryHtml = session.summary_html;
    const day = session.lesson_date ? ` ${session.lesson_date.split('-').reverse().join('-')}` : '';
    items.push({
      label: 'Apri sintesi',
      icon: <NotebookPen className="w-3.5 h-3.5" />,
      onClick: () => onPreview(summaryHtml, `S${day}`, session.input_path, undefined, session.session_dir),
    });
  }
  if (session.course_folder) {
    const folder = session.course_folder;
    items.push({
      label: 'Apri cartella del corso',
      icon: <GraduationCap className="w-3.5 h-3.5" />,
      onClick: () => onOpenFile(folder),
    });
  }
  return items;
}


/** The lesson name; becomes a text field while it is being renamed. */
function SessionTitle({ name, editing, onSave, onCancel }: {
  name: string;
  editing: boolean;
  onSave: (title: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(name);
  if (!editing) {
    return <p className="text-sm font-semibold truncate tracking-tight text-[var(--text-primary)]">{name}</p>;
  }
  const commit = () => {
    const clean = draft.trim().replace(/\s+/g, ' ');
    if (clean && clean !== name) onSave(clean);
    else onCancel();
  };
  return (
    <input
      autoFocus
      aria-label="Nuovo nome della sbobina"
      value={draft}
      maxLength={120}
      onChange={e => setDraft(e.target.value)}
      onClick={e => e.stopPropagation()}
      onPointerDown={e => e.stopPropagation()}
      onFocus={e => e.currentTarget.select()}
      onKeyDown={e => {
        e.stopPropagation();
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') onCancel();
      }}
      onBlur={commit}
      className="w-full text-sm font-semibold tracking-tight rounded-md px-1.5 py-0.5 bg-[var(--bg-input)] text-[var(--text-primary)] border border-[var(--accent-text)] outline-none"
    />
  );
}

function renameItem(onRename: ((sessionDir: string, title: string) => void) | undefined, start: () => void): KebabMenuItem[] {
  return onRename ? [{ label: 'Rinomina', icon: <Pencil className="w-3.5 h-3.5" />, onClick: start }] : [];
}

export interface DraggableSessionCardProps {
  session: ArchiveSession;
  allFolders: ArchiveFolder[];
  currentFolder?: ArchiveFolder;
  editorSessionsMap?: Record<string, EditorSession>;
  selected?: boolean;
  onToggleSelect?: () => void;
  onAssignToFolder: (folderId: string) => void;
  onRemoveFromFolder: () => void;
  onPreview: ArchivePageProps['onPreview'];
  onOpenFile: ArchivePageProps['onOpenFile'];
  onDeleteSession: ArchivePageProps['onDeleteSession'];
  onRetryFailedRevisionBlocks?: ArchivePageProps['onRetryFailedRevisionBlocks'];
  onShareSession?: (session: ArchiveSession) => void;
  courses?: string[];
  onSetCourse?: (sessionDir: string, course: string | null) => void;
  onRename?: (sessionDir: string, title: string) => void;
}

export function DraggableSessionCard({
  session,
  allFolders,
  currentFolder,
  editorSessionsMap,
  selected,
  onToggleSelect,
  onAssignToFolder,
  onRemoveFromFolder,
  onPreview,
  onOpenFile,
  onDeleteSession,
  onRetryFailedRevisionBlocks,
  onShareSession,
  courses = [],
  onSetCourse,
  onRename,
}: DraggableSessionCardProps) {
  const [renaming, setRenaming] = useState(false);
  const ts = session.completed_at_iso ? new Date(session.completed_at_iso).getTime() : 0;
  const openedAtMs = getOpenedAtMs(session, editorSessionsMap ?? loadAllEditorSessions());
  const [isRetryingBlocks, setIsRetryingBlocks] = useState(false);
  const failedBlockCount = session.revision_failed_blocks?.length ?? 0;
  const hasRevisionWarnings = session.completion_status === 'completed_with_warnings' || failedBlockCount > 0;
  const canRetryBlocks = failedBlockCount > 0 && Boolean(onRetryFailedRevisionBlocks);

  const handleRetryBlocks = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (!canRetryBlocks || isRetryingBlocks) return;
    setIsRetryingBlocks(true);
    try {
      await onRetryFailedRevisionBlocks?.(session.session_dir);
    } finally {
      setIsRetryingBlocks(false);
    }
  };

  const folderChildren: KebabMenuItem[] = [
    ...(currentFolder ? [{
      label: `Rimuovi da "${currentFolder.name}"`,
      icon: <X className="w-3.5 h-3.5" />,
      onClick: onRemoveFromFolder,
    } as KebabMenuItem] : []),
    ...(currentFolder && allFolders.length > 0 ? [{ separator: true } as KebabMenuItem] : []),
    ...allFolders.map(f => ({
      label: f.name,
      icon: <span className="w-3 h-3 rounded-full inline-block" style={{ background: f.color || DEFAULT_FOLDER_COLOR }} />,
      checked: currentFolder?.id === f.id,
      onClick: () => onAssignToFolder(f.id),
    })),
  ];

  const courseChildren: KebabMenuItem[] = onSetCourse ? [
    ...courses.map(c => ({
      label: c,
      checked: (session.course || '').toLowerCase() === c.toLowerCase(),
      onClick: () => onSetCourse(session.session_dir, c),
    })),
    ...(session.course ? [
      ...(courses.length > 0 ? [{ separator: true } as KebabMenuItem] : []),
      { label: 'Nessun corso', icon: <X className="w-3.5 h-3.5" />, onClick: () => onSetCourse(session.session_dir, null) } as KebabMenuItem,
    ] : []),
  ] : [];

  const kebabItems: KebabMenuItem[] = [
    {
      label: 'Apri cartella',
      icon: <FolderOpen className="w-3.5 h-3.5" />,
      onClick: () => onOpenFile(session.html_path.replace(/[/\\][^/\\]+$/, '') || session.html_path),
    },
    {
      label: 'Apri nel browser',
      icon: <ExternalLink className="w-3.5 h-3.5" />,
      onClick: () => onOpenFile(session.html_path),
    },
    ...renameItem(onRename, () => setRenaming(true)),
    ...courseOutputItems(session, onPreview, onOpenFile),
    ...(onShareSession ? [{
      label: 'Esporta Sbobina...',
      icon: <Download className="w-3.5 h-3.5" />,
      onClick: () => onShareSession(session),
    } as KebabMenuItem] : []),
    ...(folderChildren.length > 0 ? [
      { separator: true } as KebabMenuItem,
      {
        label: 'Raccolta',
        icon: <Folder className="w-3.5 h-3.5" />,
        children: folderChildren,
      } as KebabMenuItem,
    ] : []),
    ...(courseChildren.length > 0 ? [{
      label: 'Corso',
      icon: <GraduationCap className="w-3.5 h-3.5" />,
      children: courseChildren,
    } as KebabMenuItem] : []),
    { separator: true },
    {
      label: 'Elimina',
      icon: <Trash2 className="w-3.5 h-3.5" />,
      danger: true,
      onClick: () => onDeleteSession(session.session_dir, session.name),
    },
  ];

  return (
    <div
      onClick={() => { if (!renaming) onPreview(session.html_path, session.name, session.input_path, undefined, session.session_dir); }}
      className={`archive-session-card flex items-center justify-between gap-3 px-4 py-3 cursor-pointer group/card ${selected ? 'is-selected' : ''} ${hasRevisionWarnings && !selected ? 'is-warning' : ''}`.trim()}
      style={{
        ...(hasRevisionWarnings && !selected ? { borderColor: 'var(--warning-ring)' } : {}),
      }}
    >
      <div className="flex items-center gap-3 min-w-0 flex-1">
        {onToggleSelect && (
          <button
            type="button"
            onClick={e => {
              e.stopPropagation();
              onToggleSelect();
            }}
            className={`w-4 h-4 rounded flex items-center justify-center transition-all shrink-0 cursor-pointer ${
              selected
                ? 'bg-[var(--accent-text)] text-[var(--btn-primary-text)]'
                : 'border border-[var(--border-strong)] bg-[var(--bg-input)] hover:border-[var(--accent-text)] opacity-70 group-hover/card:opacity-100'
            }`}
            aria-label={selected ? `Deseleziona ${session.name}` : `Seleziona ${session.name}`}
            title={selected ? 'Deseleziona' : 'Seleziona'}
          >
            {selected && <Check className="w-3 h-3 stroke-[3]" />}
          </button>
        )}
        <FileText className="w-4 h-4 shrink-0 transition-transform duration-200 group-hover/card:scale-105" style={{ color: hasRevisionWarnings ? 'var(--warning-text)' : 'var(--text-muted)' }} />

        <div className="min-w-0 flex-1">
          <SessionTitle
            key={renaming ? 'edit' : 'view'}
            name={session.name}
            editing={renaming}
            onCancel={() => setRenaming(false)}
            onSave={title => { setRenaming(false); onRename?.(session.session_dir, title); }}
          />
          <div className="flex items-center gap-2 mt-0.5 text-xs min-w-0 flex-nowrap overflow-hidden" style={{ color: 'var(--text-muted)' }}>
            {ts > 0 && <span className="shrink-0">{formatRelativeTime(ts)}</span>}
            {session.course && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0 font-semibold">{session.course}</span></>
            )}
            {session.sources && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0">{['Audio', session.sources.slides_name ? 'slide' : null, session.sources.book_name ? 'libro' : null].filter(Boolean).join(' + ')}</span></>
            )}
            {session.kind === 'notes' && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0" title={session.notes_info?.book_name ? `Slide + libro (${session.notes_info.book_name}${session.notes_info.book_pages ? `, p. ${session.notes_info.book_pages}` : ''})` : 'Appunti generati dalle slide'}>{session.notes_info?.book_name ? 'Appunti: slide + libro' : 'Appunti da slide'}</span></>
            )}
            {session.effective_model && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0">{shortModelName(session.effective_model)}</span></>
            )}
            {openedAtMs > 0 && (
              <>
                <span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} />
                <span className="inline-flex items-center gap-1 shrink-0" title={`Ultima apertura: ${new Date(openedAtMs).toLocaleString('it-IT')}`}>
                  <Eye className="w-3 h-3 text-muted" style={{ opacity: 0.65 }} />
                  Aperto {formatRelativeTime(openedAtMs)}
                </span>
              </>
            )}
            {currentFolder && (
              <>
                <span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} />
                <FolderIndicatorChip folder={currentFolder} />
              </>
            )}
            {hasRevisionWarnings && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0" style={{ color: 'var(--warning-text)', fontWeight: 600 }}>Completata con avvisi</span></>
            )}
            {failedBlockCount > 0 && (
              <>
                <span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} />
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--warning-text)] shrink-0">
                  <AlertTriangle className="w-3 h-3" />{failedBlockCount} {failedBlockCount === 1 ? 'blocco non revisionato' : 'blocchi non revisionati'}
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1.5 shrink-0" onClick={e => e.stopPropagation()}>
        {canRetryBlocks && (
          <button
            type="button"
            onClick={handleRetryBlocks}
            disabled={isRetryingBlocks}
            className="icon-button compact-icon-button text-[var(--warning-text)] hover:bg-[var(--warning-subtle)] group/retry"
            style={{ opacity: isRetryingBlocks ? 0.65 : 1 }}
            title="Riprova solo i blocchi inclusi senza revisione"
            aria-label="Riprova revisione"
          >
            <RotateCcw className={`w-4 h-4 transition-transform duration-500 ease-out ${isRetryingBlocks ? 'animate-spin' : 'group-hover/retry:-rotate-180 group-hover/retry:scale-105'}`} />
            <span className="sr-only">{isRetryingBlocks ? 'Riprovo…' : 'Riprova revisione'}</span>
          </button>
        )}
        <KebabMenu items={kebabItems} />
      </div>
    </div>
  );
}

export function FolderSessionCardOverlay({
  session,
  folderColor,
}: {
  session: ArchiveSession;
  folderColor: string;
}) {
  const ts = session.completed_at_iso ? new Date(session.completed_at_iso).getTime() : 0;
  const failedBlockCount = session.revision_failed_blocks?.length ?? 0;
  const hasRevisionWarnings = session.completion_status === 'completed_with_warnings' || failedBlockCount > 0;
  return (
    <div
      className="archive-session-card flex items-center justify-between gap-3 px-4 py-3"
      style={{
        pointerEvents: 'none',
        boxShadow: 'var(--shadow-strong)',
        opacity: 0.95,
        cursor: 'grabbing',
        borderColor: hasRevisionWarnings ? 'var(--warning-ring)' : undefined,
        background: hasRevisionWarnings ? 'var(--warning-subtle)' : undefined,
      }}
    >
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <div className="relative flex items-center justify-center shrink-0">
          <FileText className="w-4 h-4" style={{ color: hasRevisionWarnings ? 'var(--warning-text)' : 'var(--text-muted)' }} />
          <span
            className="folder-color-dot absolute -bottom-0.5 -right-1"
            style={{
              '--folder-color': folderColor || DEFAULT_FOLDER_COLOR,
              width: 7,
              height: 7,
            } as React.CSSProperties}
          />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold truncate tracking-tight text-[var(--text-primary)]">{session.name}</p>
          <div className="flex flex-wrap items-center gap-2 mt-0.5 text-xs" style={{ color: 'var(--text-muted)' }}>
            {ts > 0 && <span>{formatRelativeTime(ts)}</span>}
            {session.kind === 'notes' && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0" title={session.notes_info?.book_name ? `Slide + libro (${session.notes_info.book_name}${session.notes_info.book_pages ? `, p. ${session.notes_info.book_pages}` : ''})` : 'Appunti generati dalle slide'}>{session.notes_info?.book_name ? 'Appunti: slide + libro' : 'Appunti da slide'}</span></>
            )}
            {session.effective_model && (
              <><span className="w-1 h-1 rounded-full" style={{ background: 'var(--border-default)' }} /><span>{shortModelName(session.effective_model)}</span></>
            )}
            {hasRevisionWarnings && (
              <><span className="w-1 h-1 rounded-full" style={{ background: 'var(--border-default)' }} /><span style={{ color: 'var(--warning-text)', fontWeight: 600 }}>Completata con avvisi</span></>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export interface SortableSessionCardProps {
  session: ArchiveSession;
  folderColor: string;
  disabled: boolean;
  onRemove: () => void;
  editorSessionsMap?: Record<string, EditorSession>;
  selected?: boolean;
  onToggleSelect?: () => void;
  onPreview: ArchivePageProps['onPreview'];
  onOpenFile: ArchivePageProps['onOpenFile'];
  onDeleteSession: ArchivePageProps['onDeleteSession'];
  onRetryFailedRevisionBlocks?: ArchivePageProps['onRetryFailedRevisionBlocks'];
  onShareSession?: (session: ArchiveSession) => void;
  canMoveToPreviousPage?: boolean;
  canMoveToNextPage?: boolean;
  onMoveToPreviousPage?: () => void;
  onMoveToNextPage?: () => void;
  onRename?: (sessionDir: string, title: string) => void;
}

export function SortableSessionCard({
  session,
  folderColor,
  disabled,
  onRemove,
  editorSessionsMap,
  selected,
  onToggleSelect,
  onPreview,
  onOpenFile,
  onDeleteSession,
  onRetryFailedRevisionBlocks,
  onShareSession,
  canMoveToPreviousPage,
  canMoveToNextPage,
  onMoveToPreviousPage,
  onMoveToNextPage,
  onRename,
}: SortableSessionCardProps) {
  const [renaming, setRenaming] = useState(false);
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: session.session_dir, disabled });

  const ts = session.completed_at_iso ? new Date(session.completed_at_iso).getTime() : 0;
  const openedAtMs = getOpenedAtMs(session, editorSessionsMap ?? loadAllEditorSessions());
  const [isRetryingBlocks, setIsRetryingBlocks] = useState(false);
  const failedBlockCount = session.revision_failed_blocks?.length ?? 0;
  const hasRevisionWarnings = session.completion_status === 'completed_with_warnings' || failedBlockCount > 0;
  const canRetryBlocks = failedBlockCount > 0 && Boolean(onRetryFailedRevisionBlocks);

  const handleRetryBlocks = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (!canRetryBlocks || isRetryingBlocks) return;
    setIsRetryingBlocks(true);
    try {
      await onRetryFailedRevisionBlocks?.(session.session_dir);
    } finally {
      setIsRetryingBlocks(false);
    }
  };

  const kebabItems: KebabMenuItem[] = [
    {
      label: 'Apri cartella',
      icon: <FolderOpen className="w-3.5 h-3.5" />,
      onClick: () => onOpenFile(session.html_path.replace(/[/\\][^/\\]+$/, '') || session.html_path),
    },
    {
      label: 'Apri nel browser',
      icon: <ExternalLink className="w-3.5 h-3.5" />,
      onClick: () => onOpenFile(session.html_path),
    },
    ...renameItem(onRename, () => setRenaming(true)),
    ...courseOutputItems(session, onPreview, onOpenFile),
    ...(onShareSession ? [{
      label: 'Esporta Sbobina...',
      icon: <Download className="w-3.5 h-3.5" />,
      onClick: () => onShareSession(session),
    } as KebabMenuItem] : []),
    { separator: true },
    {
      label: 'Rimuovi dalla cartella',
      icon: <X className="w-3.5 h-3.5" />,
      onClick: onRemove,
    },
    { separator: true },
    {
      label: 'Elimina',
      icon: <Trash2 className="w-3.5 h-3.5" />,
      danger: true,
      onClick: () => onDeleteSession(session.session_dir, session.name),
    },
  ];

  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...(!disabled && !renaming ? listeners : {})}
      onClick={() => { if (!renaming) onPreview(session.html_path, session.name, session.input_path, undefined, session.session_dir); }}
      className={`archive-session-card flex items-center justify-between gap-3 px-4 py-3 group/card ${selected ? 'is-selected' : ''} ${hasRevisionWarnings && !selected ? 'is-warning' : ''}`.trim()}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
        touchAction: disabled ? undefined : 'none',
        cursor: isDragging ? 'grabbing' : disabled ? 'pointer' : 'grab',
        borderColor: hasRevisionWarnings && !selected ? 'var(--warning-ring)' : undefined,
      }}
    >
      <div className="flex items-center gap-3 min-w-0 flex-1">
        {onToggleSelect && (
          <button
            type="button"
            onClick={e => {
              e.stopPropagation();
              onToggleSelect();
            }}
            className={`w-4 h-4 rounded flex items-center justify-center transition-all shrink-0 cursor-pointer ${
              selected
                ? 'bg-[var(--accent-text)] text-[var(--btn-primary-text)]'
                : 'border border-[var(--border-strong)] bg-[var(--bg-input)] hover:border-[var(--accent-text)] opacity-70 group-hover/card:opacity-100'
            }`}
            aria-label={selected ? `Deseleziona ${session.name}` : `Seleziona ${session.name}`}
            title={selected ? 'Deseleziona' : 'Seleziona'}
          >
            {selected && <Check className="w-3 h-3 stroke-[3]" />}
          </button>
        )}
        <div className="relative flex items-center justify-center shrink-0">
          <FileText className="w-4 h-4 transition-transform duration-200 group-hover/card:scale-105" style={{ color: hasRevisionWarnings ? 'var(--warning-text)' : 'var(--text-muted)' }} />
          <span
            className="folder-color-dot absolute -bottom-0.5 -right-1"
            style={{
              '--folder-color': folderColor || DEFAULT_FOLDER_COLOR,
              width: 7,
              height: 7,
            } as React.CSSProperties}
          />
        </div>
        <div className="min-w-0 flex-1">
          <SessionTitle
            key={renaming ? 'edit' : 'view'}
            name={session.name}
            editing={renaming}
            onCancel={() => setRenaming(false)}
            onSave={title => { setRenaming(false); onRename?.(session.session_dir, title); }}
          />
          <div className="flex items-center gap-2 mt-0.5 text-xs min-w-0 flex-nowrap overflow-hidden" style={{ color: 'var(--text-muted)' }}>
            {ts > 0 && <span className="shrink-0">{formatRelativeTime(ts)}</span>}
            {session.course && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0 font-semibold">{session.course}</span></>
            )}
            {session.sources && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0">{['Audio', session.sources.slides_name ? 'slide' : null, session.sources.book_name ? 'libro' : null].filter(Boolean).join(' + ')}</span></>
            )}
            {session.kind === 'notes' && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0" title={session.notes_info?.book_name ? `Slide + libro (${session.notes_info.book_name}${session.notes_info.book_pages ? `, p. ${session.notes_info.book_pages}` : ''})` : 'Appunti generati dalle slide'}>{session.notes_info?.book_name ? 'Appunti: slide + libro' : 'Appunti da slide'}</span></>
            )}
            {session.effective_model && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0">{shortModelName(session.effective_model)}</span></>
            )}
            {openedAtMs > 0 && (
              <>
                <span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} />
                <span className="inline-flex items-center gap-1 shrink-0" title={`Ultima apertura: ${new Date(openedAtMs).toLocaleString('it-IT')}`}>
                  <Eye className="w-3 h-3 text-muted" style={{ opacity: 0.65 }} />
                  Aperto {formatRelativeTime(openedAtMs)}
                </span>
              </>
            )}
            {hasRevisionWarnings && (
              <><span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} /><span className="shrink-0" style={{ color: 'var(--warning-text)', fontWeight: 600 }}>Completata con avvisi</span></>
            )}
            {failedBlockCount > 0 && (
              <>
                <span className="w-1 h-1 rounded-full shrink-0" style={{ background: 'var(--border-default)' }} />
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--warning-text)] shrink-0">
                  <AlertTriangle className="w-3 h-3" />{failedBlockCount} {failedBlockCount === 1 ? 'blocco non revisionato' : 'blocchi non revisionati'}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0" onClick={e => e.stopPropagation()}>
        {canRetryBlocks && (
          <button
            type="button"
            onClick={handleRetryBlocks}
            disabled={isRetryingBlocks}
            className="icon-button compact-icon-button text-[var(--warning-text)] hover:bg-[var(--warning-subtle)] group/retry"
            style={{ opacity: isRetryingBlocks ? 0.65 : 1 }}
            title="Riprova solo i blocchi inclusi senza revisione"
            aria-label="Riprova revisione"
          >
            <RotateCcw className={`w-4 h-4 transition-transform duration-500 ease-out ${isRetryingBlocks ? 'animate-spin' : 'group-hover/retry:-rotate-180 group-hover/retry:scale-105'}`} />
            <span className="sr-only">{isRetryingBlocks ? 'Riprovo…' : 'Riprova revisione'}</span>
          </button>
        )}
        {(onMoveToPreviousPage || onMoveToNextPage) && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onMoveToPreviousPage}
              disabled={!canMoveToPreviousPage}
              className="icon-button compact-icon-button"
              style={{ color: 'var(--text-muted)' }}
              title="Sposta alla pagina precedente"
              aria-label={`Sposta ${session.name} alla pagina precedente`}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={onMoveToNextPage}
              disabled={!canMoveToNextPage}
              className="icon-button compact-icon-button"
              style={{ color: 'var(--text-muted)' }}
              title="Sposta alla pagina successiva"
              aria-label={`Sposta ${session.name} alla pagina successiva`}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}
        <KebabMenu items={kebabItems} />
      </div>
    </div>
  );
}
