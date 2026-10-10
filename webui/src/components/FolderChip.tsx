import type { ArchiveFolder } from '../bridge';
import { DEFAULT_FOLDER_COLOR } from './archive/types';

// Tiny shared chip — kept separate so QueueFileCard can import it
// without creating a QueueFileCard → ArchivePage circular dependency.
export function FolderIndicatorChip({ folder }: { folder: Pick<ArchiveFolder, 'name' | 'color'> }) {
  const folderColor = folder.color || DEFAULT_FOLDER_COLOR;
  return (
    <span
      className="folder-indicator-chip"
      style={{ '--folder-color': folderColor } as React.CSSProperties}
      title={`Raccolta: ${folder.name}`}
    >
      <span className="folder-color-dot is-small" />
      <span>{folder.name}</span>
    </span>
  );
}
