import { memo } from 'react';
import { Plus, UploadCloud } from 'lucide-react';

interface DropZoneProps {
  isDragging: boolean;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onClick: () => void;
  compact?: boolean;
}

export const DropZone = memo(function DropZone({ isDragging, onDragOver, onDragLeave, onDrop, onClick, compact = false }: DropZoneProps) {
  if (compact) {
    return (
      <div
        onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop} onClick={onClick}
        className={`dropzone-compact cursor-pointer flex items-center gap-3 px-4 group/compact${isDragging ? ' is-dragging' : ''}`}
        role="button"
        tabIndex={0}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onClick();
          }
        }}
        aria-label="Aggiungi file audio o video"
      >
        <Plus className={`w-4 h-4 shrink-0 transition-colors ${isDragging ? 'text-[var(--accent-bg)]' : 'text-[var(--text-muted)] group-hover/compact:text-[var(--accent-text)]'}`} />
        <span className={`text-sm transition-colors ${isDragging ? 'text-[var(--accent-bg)] font-medium' : 'text-[var(--text-secondary)] group-hover/compact:text-[var(--text-primary)] font-normal'}`}>
          {isDragging ? 'Rilascia qui per aggiungere' : 'Trascina file o clicca per aggiungere'}
        </span>
        <span className="ml-auto text-xs hidden sm:block text-[var(--text-faint)]">
          .mp3 .m4a .mp4 ...
        </span>
      </div>
    );
  }

  return (
    <div
      onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop} onClick={onClick}
      className={`dropzone-card relative cursor-pointer flex flex-col items-center justify-center py-10 px-6 text-center group/dropzone${isDragging ? ' is-dragging' : ''}`}
      role="button"
      tabIndex={0}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
      aria-label="Trascina i file qui o clicca per sfogliare"
    >
      <div className={`dropzone-icon-container ${isDragging ? 'is-dragging' : ''}`}>
        <UploadCloud className="w-6 h-6" />
      </div>
      <h3 className="text-base font-semibold mb-1 text-[var(--text-primary)] tracking-tight">Trascina i file qui</h3>
      <p className="text-xs max-w-xs text-[var(--text-muted)]">
        .mp3 · .m4a · .wav · .mp4 · .mkv · .webm · .ogg · .flac · .aac
      </p>
      <div className="dropzone-browse-button">
        Sfoglia file
      </div>
    </div>
  );
});
