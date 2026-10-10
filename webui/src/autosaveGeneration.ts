const HTML_AUTOSAVE_GENERATION_MAX = 500;

const htmlAutosaveGenerations = new Map<string, number>();
let lastHtmlAutosaveGeneration = Date.now();

function normalizeHtmlPath(path: string): string {
  return path.trim();
}

function rememberHtmlGeneration(path: string, generation: number): number {
  lastHtmlAutosaveGeneration = Math.max(lastHtmlAutosaveGeneration, generation);
  if (htmlAutosaveGenerations.has(path)) htmlAutosaveGenerations.delete(path);
  htmlAutosaveGenerations.set(path, generation);
  while (htmlAutosaveGenerations.size > HTML_AUTOSAVE_GENERATION_MAX) {
    const oldest = htmlAutosaveGenerations.keys().next().value;
    if (oldest === undefined) break;
    htmlAutosaveGenerations.delete(oldest);
  }
  return generation;
}

export function seedHtmlAutosaveGeneration(path: string): number {
  const normalizedPath = normalizeHtmlPath(path);
  const seed = Math.max(
    htmlAutosaveGenerations.get(normalizedPath) ?? 0,
    lastHtmlAutosaveGeneration,
    Date.now(),
  );
  if (!normalizedPath) {
    lastHtmlAutosaveGeneration = seed;
    return seed;
  }
  return rememberHtmlGeneration(normalizedPath, seed);
}

export function nextHtmlAutosaveGeneration(path: string): number {
  const normalizedPath = normalizeHtmlPath(path);
  const next = Math.max(
    htmlAutosaveGenerations.get(normalizedPath) ?? 0,
    lastHtmlAutosaveGeneration,
    Date.now(),
  ) + 1;
  if (!normalizedPath) {
    lastHtmlAutosaveGeneration = next;
    return next;
  }
  return rememberHtmlGeneration(normalizedPath, next);
}
