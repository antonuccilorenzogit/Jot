import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ArchiveSession, SearchSessionResult } from '../bridge';
import { getOpenedAtMs, type SortOption } from '../components/archive/types';

export interface UseArchiveSearchOptions {
  sessions: ArchiveSession[];
  editorSessionsMap: Record<string, { openedAt?: number; savedAt?: number }>;
}

export function useArchiveSearch({
  sessions,
  editorSessionsMap,
}: UseArchiveSearchOptions) {
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortOption>('newest');
  const [searchFocused, setSearchFocused] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [fullTextMode, setFullTextMode] = useState(false);
  const [ftSort, setFtSort] = useState<SortOption>('relevance');
  const [ftResults, setFtResults] = useState<SearchSessionResult[] | null>(null);
  const [ftTotal, setFtTotal] = useState<number | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [ftError, setFtError] = useState<string | null>(null);
  const ftDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchGenRef = useRef(0);

  const sortSessions = useCallback(
    (arr: ArchiveSession[]) => {
      const q = search.trim().toLowerCase();
      const filtered = q ? arr.filter((s) => s.name.toLowerCase().includes(q)) : arr;
      return [...filtered].sort((a, b) => {
        if (sort === 'name') {
          return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
        }
        if (sort === 'recently_opened') {
          const oa = getOpenedAtMs(a, editorSessionsMap);
          const ob = getOpenedAtMs(b, editorSessionsMap);
          if (oa !== ob) return ob - oa;
        }
        const ta = a.completed_at_iso ? new Date(a.completed_at_iso).getTime() : 0;
        const tb = b.completed_at_iso ? new Date(b.completed_at_iso).getTime() : 0;
        return sort === 'oldest' ? ta - tb : tb - ta;
      });
    },
    [search, sort, editorSessionsMap]
  );

  const allSortedSessions = useMemo(() => sortSessions(sessions), [sessions, sortSessions]);

  const sortedFtResults = useMemo(() => {
    if (!ftResults) return null;
    if (ftSort === 'relevance') return ftResults;
    return [...ftResults].sort((a, b) => {
      if (ftSort === 'name') {
        return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
      }
      if (ftSort === 'recently_opened') {
        const oa =
          editorSessionsMap[a.session_dir]?.openedAt ??
          editorSessionsMap[a.html_path]?.openedAt ??
          (a.completed_at_iso ? new Date(a.completed_at_iso).getTime() : 0);
        const ob =
          editorSessionsMap[b.session_dir]?.openedAt ??
          editorSessionsMap[b.html_path]?.openedAt ??
          (b.completed_at_iso ? new Date(b.completed_at_iso).getTime() : 0);
        if (oa !== ob) return ob - oa;
      }
      const ta = a.completed_at_iso ? new Date(a.completed_at_iso).getTime() : 0;
      const tb = b.completed_at_iso ? new Date(b.completed_at_iso).getTime() : 0;
      return ftSort === 'oldest' ? ta - tb : tb - ta;
    });
  }, [ftResults, ftSort, editorSessionsMap]);

  useEffect(() => {
    if (ftDebounceRef.current) clearTimeout(ftDebounceRef.current);
    const q = search.trim();
    if (!fullTextMode || q.length < 3) {
      searchGenRef.current++;
      setFtResults(null);
      setFtTotal(null);
      setFtError(null);
      setIsSearching(false);
      return;
    }
    setIsSearching(true);
    setFtError(null);
    const gen = ++searchGenRef.current;
    ftDebounceRef.current = setTimeout(async () => {
      try {
        const res = await window.pywebview?.api?.search_sessions?.(q, 100);
        if (searchGenRef.current !== gen) return;
        if (res?.ok) {
          setFtResults(res.results ?? []);
          setFtTotal(res.total ?? res.results?.length ?? 0);
        } else {
          setFtError(res?.error ?? 'Errore durante la ricerca');
          setFtResults([]);
          setFtTotal(null);
        }
      } catch {
        if (searchGenRef.current !== gen) return;
        setFtError('Errore durante la ricerca');
        setFtResults([]);
        setFtTotal(null);
      } finally {
        if (searchGenRef.current === gen) setIsSearching(false);
      }
    }, 400);
    return () => {
      if (ftDebounceRef.current) clearTimeout(ftDebounceRef.current);
    };
  }, [fullTextMode, search]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== '/') return;
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement).isContentEditable) return;
      e.preventDefault();
      searchInputRef.current?.focus();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  return {
    search,
    setSearch,
    sort,
    setSort,
    searchFocused,
    setSearchFocused,
    searchInputRef,
    fullTextMode,
    setFullTextMode,
    ftSort,
    setFtSort,
    ftResults,
    sortedFtResults,
    ftTotal,
    isSearching,
    ftError,
    sortSessions,
    allSortedSessions,
  };
}
