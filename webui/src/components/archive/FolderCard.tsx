import { useMemo } from 'react';
import { FolderPlus, Pencil, Trash2 } from 'lucide-react';
import { useSortable } from '@dnd-kit/sortable';
import type { ArchiveFolder, ArchiveSession } from '../../bridge';
import { DEFAULT_FOLDER_COLOR } from './types';
import { normalizeSessionPath } from '../../utils';
import { KebabMenu, type KebabMenuItem } from '../KebabMenu';

export interface FolderCardProps {
  folder: ArchiveFolder;
  sessionsByDir: Map<string, ArchiveSession>;
  onNavigate: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export function FolderCard({
  folder,
  sessionsByDir,
  onNavigate,
  onEdit,
  onDelete,
}: FolderCardProps) {
  const count = useMemo(
    () => folder.session_dirs.filter(d => sessionsByDir.has(normalizeSessionPath(d))).length,
    [folder.session_dirs, sessionsByDir],
  );

  const kebabItems: KebabMenuItem[] = [
    {
      label: 'Modifica',
      icon: <Pencil className="w-3.5 h-3.5" />,
      onClick: onEdit,
    },
    {
      label: 'Elimina',
      icon: <Trash2 className="w-3.5 h-3.5" />,
      danger: true,
      onClick: onDelete,
    },
  ];

  return (
    <div
      className="folder-card cursor-pointer group/folder"
      style={{ '--folder-color': folder.color || DEFAULT_FOLDER_COLOR } as React.CSSProperties}
      onClick={onNavigate}
    >
      <div className="flex items-center gap-3 px-4 pt-3 pb-1">
        <span className="folder-color-dot is-large" />
        <span className="flex-1 text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
          {folder.name}
        </span>
        <div onClick={e => e.stopPropagation()}>
          <KebabMenu items={kebabItems} />
        </div>
      </div>
      <div className="px-4 pb-3">
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {count === 1 ? '1 lezione' : `${count} lezioni`}
        </p>
      </div>
    </div>
  );
}

export function SortableFolderCard({
  folder,
  sessionsByDir,
  onNavigate,
  onEdit,
  onDelete,
}: FolderCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: folder.id });

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: transform ? `translate3d(${transform.x}px,${transform.y}px,0) scaleX(${transform.scaleX}) scaleY(${transform.scaleY})` : undefined,
        transition,
        opacity: isDragging ? 0.4 : 1,
        touchAction: 'none',
        cursor: isDragging ? 'grabbing' : 'grab',
      }}
      {...attributes}
      {...listeners}
    >
      <FolderCard
        folder={folder}
        sessionsByDir={sessionsByDir}
        onNavigate={onNavigate}
        onEdit={onEdit}
        onDelete={onDelete}
      />
    </div>
  );
}

export function FolderCardOverlay({
  folder,
  sessionsByDir,
}: {
  folder: ArchiveFolder;
  sessionsByDir: Map<string, ArchiveSession>;
}) {
  const count = folder.session_dirs.filter(d => sessionsByDir.has(normalizeSessionPath(d))).length;
  return (
    <div
      className="folder-card opacity-95 pointer-events-none cursor-grabbing"
      style={{
        '--folder-color': folder.color || DEFAULT_FOLDER_COLOR,
        boxShadow: 'var(--shadow-strong)',
      } as React.CSSProperties}
    >
      <div className="flex items-center gap-3 px-4 pt-3 pb-1">
        <span className="folder-color-dot is-large" />
        <span className="flex-1 text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
          {folder.name}
        </span>
      </div>
      <div className="px-4 pb-3">
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {count === 1 ? '1 lezione' : `${count} lezioni`}
        </p>
      </div>
    </div>
  );
}

export function NewFolderCard({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="folder-card folder-card-new cursor-pointer w-full text-left group/newfolder"
    >
      <FolderPlus className="w-5 h-5 transition-transform duration-200 group-hover/newfolder:scale-105" style={{ color: 'var(--accent-text)' }} />
      <span className="text-xs font-semibold" style={{ color: 'var(--accent-text)' }}>Nuova raccolta</span>
    </button>
  );
}
