import type { FileItem } from './appState';
import type { ArchiveSession } from './bridge';

type ArchiveLookup = {
  byPath: Map<string, ArchiveSession[]>;
  byMeta: Map<string, ArchiveSession[]>;
};

function normalizeKey(value?: string): string {
  return String(value ?? '').trim().toLowerCase();
}

function archiveMetaKey(session: ArchiveSession): string | null {
  const size = Number(session.input_size ?? 0);
  const dur = Math.round(Number(session.duration_sec ?? 0));
  if (size <= 0 || dur <= 0) return null;
  return `${normalizeKey(session.name)}::${size}::${dur}`;
}

export function filterArchiveSessionsByInputPath(
  inputPath: string | undefined,
  archiveSessions: Iterable<ArchiveSession>,
): ArchiveSession[] {
  const normalizedPath = normalizeKey(inputPath);
  if (!normalizedPath) return [];

  const matches: ArchiveSession[] = [];
  const seenSessionDirs = new Set<string>();

  for (const session of archiveSessions) {
    if (normalizeKey(session.input_path) !== normalizedPath) continue;
    if (seenSessionDirs.has(session.session_dir)) continue;
    seenSessionDirs.add(session.session_dir);
    matches.push(session);
  }

  return matches;
}

export function buildArchiveLookup(archiveSessions: ArchiveSession[]): ArchiveLookup {
  const byPath = new Map<string, ArchiveSession[]>();
  const byMeta = new Map<string, ArchiveSession[]>();

  for (const session of archiveSessions) {
    const normalizedPath = normalizeKey(session.input_path);
    if (normalizedPath) {
      const pathBucket = byPath.get(normalizedPath);
      if (pathBucket) pathBucket.push(session);
      else byPath.set(normalizedPath, [session]);
    }

    const mk = archiveMetaKey(session);
    if (mk) {
      const metaBucket = byMeta.get(mk);
      if (metaBucket) metaBucket.push(session);
      else byMeta.set(mk, [session]);
    }
  }

  return { byPath, byMeta };
}

export function getArchiveMatchesForFile(
  file: Pick<FileItem, 'name' | 'path' | 'size' | 'duration'>,
  archiveLookup: ArchiveLookup,
): ArchiveSession[] {
  const normalizedPath = normalizeKey(file.path);
  if (normalizedPath) {
    const pathMatches = filterArchiveSessionsByInputPath(normalizedPath, archiveLookup.byPath.get(normalizedPath) ?? []);
    if (pathMatches.length > 0) return pathMatches;
  }

  const size = Number(file.size ?? 0);
  const dur = Math.round(Number(file.duration ?? 0));
  if (size > 0 && dur > 0) {
    const mk = `${normalizeKey(file.name)}::${size}::${dur}`;
    const metaMatches = archiveLookup.byMeta.get(mk);
    if (metaMatches && metaMatches.length > 0) return metaMatches;
  }

  return [];
}
