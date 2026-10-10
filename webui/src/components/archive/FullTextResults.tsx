import { FileSearch, Loader2 } from 'lucide-react';
import type { SearchSessionResult } from '../../bridge';
import { formatRelativeTime } from '../../utils';

interface FullTextResultListProps {
  query: string;
  results: SearchSessionResult[] | null;
  isSearching: boolean;
  onPreview: (r: SearchSessionResult) => void;
}

export function FullTextResultList({
  query,
  results,
  isSearching,
  onPreview,
}: FullTextResultListProps) {
  if (query.length < 3) return null;

  if (isSearching) {
    return (
      <div className="py-8 flex items-center justify-center gap-2 text-sm" style={{ color: 'var(--text-muted)' }}>
        <Loader2 className="w-4 h-4 animate-spin" />
        Ricerca in corso…
      </div>
    );
  }

  if (!results || results.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {results.map(result => (
        <button
          key={result.session_dir}
          onClick={() => onPreview(result)}
          className="archive-session-card w-full text-left px-4 py-3 flex flex-col gap-2 group/search"
          style={{ cursor: 'pointer' }}
        >
          <div className="flex items-center gap-2">
            <FileSearch className="w-4 h-4 shrink-0 transition-transform duration-200 group-hover/search:scale-105" style={{ color: 'var(--accent-text)' }} />
            <span className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>{result.name}</span>
            {result.completed_at_iso && (
              <span className="text-xs shrink-0" style={{ color: 'var(--text-muted)' }}>
                {formatRelativeTime(new Date(result.completed_at_iso).getTime())}
              </span>
            )}
            <span className="ml-auto text-xs px-1.5 py-0.5 rounded-full shrink-0" style={{ background: 'var(--accent-subtle)', color: 'var(--accent-text)' }}>
              {result.match_count === 1 ? '1 occorrenza' : `${result.match_count} occorrenze`}
            </span>
          </div>
          <div className="flex flex-col gap-1.5 pl-6">
            {result.snippets.map((s, i) => (
              <p key={i} className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                {s.before && <span>…{s.before} </span>}
                <mark className="search-highlight px-0.5 font-semibold">{s.match}</mark>
                {s.after && <span> {s.after}…</span>}
              </p>
            ))}
          </div>
        </button>
      ))}
    </div>
  );
}
