export const GEMINI_KEY_PATTERN = /^(AIza[0-9A-Za-z_-]{20,}|AQ\.[0-9A-Za-z_-]{20,})$/;

/** Normalise a session directory path so that Windows backslashes, trailing
 * slashes and letter-case differences are ignored when comparing paths.
 *
 * NOTE: `.toLowerCase()` is applied unconditionally on every platform.
 * This is safe for the current Windows-only target (NTFS is case-insensitive),
 * but would need revisiting if the app is ported to a case-sensitive filesystem
 * (Linux/macOS) where two paths that differ only in case are distinct. */
export function normalizeSessionPath(path?: string): string {
  return String(path || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}
const _ERROR_MAP: Record<string, string> = {
  phase1_degenerate_output: 'Trascrizione interrotta: testo non valido anche dopo il retry automatico.',
  quota_daily_limit_phase1: 'Quota API giornaliera esaurita — riprova domani, oppure aggiungi una chiave di riserva nelle impostazioni.',
  quota_daily_limit_phase2: 'Quota API esaurita durante la revisione — riprova domani, oppure aggiungi una chiave di riserva nelle impostazioni.',
  bad_request_phase1: 'Richiesta non valida durante la trascrizione (errore 400).',
  autosave_failed: 'Errore critico: salvataggio sessione fallito ripetutamente. Disco pieno o directory non scrivibile?',
  session_collision: 'Questo file sembra corrispondere a una sbobina già completata ma con contenuto diverso. Apri Impostazioni → Sessioni per risolvere.',
  regenerate_prompt_timeout: 'Nessuna scelta ricevuta sulla ripresa entro 120 secondi. Sessione salvata: clicca Riprendi per continuare.',
  html_export_failed: 'Errore durante il salvataggio del file di output.',
  html_export_missing: 'File di output non trovato dopo il salvataggio.',
  processing_failed: 'Elaborazione non completata.',
  api_key_mancante: 'API key mancante o non valida.',
  phase1_all_models_unavailable: 'Tutti i modelli AI temporaneamente non disponibili.',
  revision_failed_blocks: 'Alcuni blocchi sono stati inclusi non revisionati.',
};

const _RESUMABLE_ERRORS = new Set([
  'quota_daily_limit_phase1',
  'quota_daily_limit_phase2',
  'phase1_all_models_unavailable',
  'regenerate_prompt_timeout',
]);

function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

export function isQuotaError(raw: string | undefined): boolean {
  if (!raw) return false;
  const r = raw.trim();
  return r === 'quota_daily_limit_phase1' || r === 'quota_daily_limit_phase2';
}

export function isResumableError(raw: string | undefined): boolean {
  if (!raw) return false;
  const r = raw.trim();
  return _RESUMABLE_ERRORS.has(r);
}

export function isPausedError(raw: string | undefined, detail?: string): boolean {
  if (!raw) return false;
  const r = raw.trim();
  const d = String(detail || '').trim();
  return r === 'regenerate_prompt_timeout' || d === 'api_key_prompt_timeout';
}

const _NETWORK_ERROR_PATTERNS = [
  'getaddrinfo',
  'connecterror',
  'connection refused',
  'connection reset',
  'connection aborted',
  'network is unreachable',
  'network unreachable',
  'connessione assente',
  'connessione di rete non disponibile',
  'nessuna connessione a internet',
  'name or service not known',
  'temporary failure in name resolution',
  'enotfound',
  'econnrefused',
  'errno 11001',
  'errno 10051',
  'errno 10054',
  'errno 10060',
  'errno 10061',
];

export function isNetworkError(detail?: string): boolean {
  if (!detail) return false;
  const d = detail.toLowerCase();
  return _NETWORK_ERROR_PATTERNS.some(marker => d.includes(marker));
}

export function errorLabel(raw: string | undefined, detail?: string): string {
  if (!raw) return 'Elaborazione non completata.';
  const r = raw.trim();
  const d = String(detail || '').trim();
  if (r === 'offline' || (r === 'processing_failed' && isNetworkError(d))) {
    return 'Nessuna connessione a Internet rilevata. Verifica la tua connessione di rete e riprova.';
  }
  if ((r === 'quota_daily_limit_phase1' || r === 'quota_daily_limit_phase2') && d === 'api_key_prompt_timeout') {
    return 'Attesa chiave API scaduta. Sessione salvata — riprendi quando vuoi.';
  }
  if (r in _ERROR_MAP) return _ERROR_MAP[r];
  if (r.startsWith('phase1_chunk_failed_')) {
    const chunkNum = r.replace('phase1_chunk_failed_', '');
    if (isNetworkError(d)) {
      return `Errore di connessione al blocco ${chunkNum}: impossibile raggiungere i server Google. Verifica la connessione a Internet e clicca Riprendi.`;
    }
    const cleanD = d.replace(/CircuitBreakerExhaustedError:\s*/gi, '').replace(/RuntimeError:\s*/gi, '').trim();
    const detailText = cleanD ? ` Dettaglio: ${sentence(cleanD)}` : '';
    return `Errore al blocco ${chunkNum} dopo 4 tentativi.${detailText} Clicca Riprendi per continuare dal blocco ${chunkNum}.`;
  }
  return r;
}

export const formatSize = (bytes: number): string => {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
};

export const formatRelativeTime = (timestampMs: number): string => {
  const diffMs = Date.now() - timestampMs;
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return 'adesso';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} minut${diffMin === 1 ? 'o' : 'i'} fa`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH} or${diffH === 1 ? 'a' : 'e'} fa`;
  const diffDays = Math.floor(diffH / 24);
  if (diffDays === 1) return 'ieri';
  if (diffDays < 7) return `${diffDays} giorni fa`;
  return new Date(timestampMs).toLocaleDateString('it-IT', { day: 'numeric', month: 'short', year: 'numeric' });
};

export function shortModelName(model: string): string {
  if (!model) return '';
  return model.replace(/^models\//, '').replace(/^gemini-/, '').trim() || model;
}

export const formatDuration = (seconds: number, fallback = ''): string => {
  if (!seconds) return fallback;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s.toString().padStart(2, '0')}s`;
  return `${s}s`;
};

export interface ImageOptimizationOptions {
  maxWidth?: number;
  maxHeight?: number;
  quality?: number;
  format?: 'image/jpeg' | 'image/png' | 'image/webp';
}

export function calculateOptimalDimensions(
  width: number,
  height: number,
  maxWidth = 1600,
  maxHeight = 1600
): { width: number; height: number } {
  if (width <= 0 || height <= 0) {
    return { width: Math.max(1, width), height: Math.max(1, height) };
  }
  if (width <= maxWidth && height <= maxHeight) {
    return { width, height };
  }
  const ratio = Math.min(maxWidth / width, maxHeight / height);
  return {
    width: Math.max(1, Math.round(width * ratio)),
    height: Math.max(1, Math.round(height * ratio)),
  };
}

export const readFileAsDataUrl = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('Lettura immagine fallita.'));
    reader.readAsDataURL(file);
  });

export const optimizeDataUrlImage = async (
  dataUrl: string,
  options: ImageOptimizationOptions = {}
): Promise<string> => {
  if (!dataUrl || typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/')) {
    return dataUrl;
  }

  if (dataUrl.startsWith('data:image/svg+xml') || dataUrl.startsWith('data:image/gif')) {
    return dataUrl;
  }

  const {
    maxWidth = 1600,
    maxHeight = 1600,
    quality = 0.85,
    format = 'image/jpeg',
  } = options;

  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return dataUrl;
  }

  return new Promise<string>((resolve) => {
    try {
      const img = new Image();
      img.onload = () => {
        try {
          const srcWidth = img.naturalWidth || img.width;
          const srcHeight = img.naturalHeight || img.height;

          if (!srcWidth || !srcHeight) {
            resolve(dataUrl);
            return;
          }

          const { width, height } = calculateOptimalDimensions(
            srcWidth,
            srcHeight,
            maxWidth,
            maxHeight
          );

          if (
            format === 'image/jpeg' &&
            dataUrl.startsWith('data:image/jpeg') &&
            srcWidth <= maxWidth &&
            srcHeight <= maxHeight &&
            dataUrl.length < 200_000
          ) {
            resolve(dataUrl);
            return;
          }

          const canvas = document.createElement('canvas');
          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            resolve(dataUrl);
            return;
          }

          if (format === 'image/jpeg') {
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, width, height);
          }

          ctx.drawImage(img, 0, 0, width, height);

          let optimizedDataUrl = canvas.toDataURL(format, quality);

          if (format === 'image/jpeg' && !optimizedDataUrl.startsWith('data:image/jpeg')) {
            const jpegDataUrl = canvas.toDataURL('image/jpeg', quality);
            if (jpegDataUrl.startsWith('data:image/jpeg')) {
              optimizedDataUrl = jpegDataUrl;
            }
          }

          if (
            dataUrl.startsWith(format) &&
            srcWidth <= maxWidth &&
            srcHeight <= maxHeight &&
            dataUrl.length > 0 &&
            dataUrl.length < optimizedDataUrl.length
          ) {
            resolve(dataUrl);
          } else {
            resolve(optimizedDataUrl);
          }
        } catch {
          resolve(dataUrl);
        }
      };
      img.onerror = () => {
        resolve(dataUrl);
      };
      img.src = dataUrl;
    } catch {
      resolve(dataUrl);
    }
  });
};

export const EDITOR_CONTENT_WIDTH_PX = 634;

export const clampWidthPercent = (value: unknown): number => {
  const numeric = typeof value === 'number' ? value : Number.parseFloat(String(value ?? '56'));
  if (!Number.isFinite(numeric)) return 56;
  return Math.min(100, Math.max(20, Math.round(numeric)));
};

const LATEX_SYMBOLS: Record<string, string> = {
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', varepsilon: 'ε', zeta: 'ζ', eta: 'η',
  theta: 'θ', vartheta: 'ϑ', iota: 'ι', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π',
  rho: 'ρ', sigma: 'σ', tau: 'τ', upsilon: 'υ', phi: 'φ', varphi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π', Sigma: 'Σ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω',
  cdot: '·', times: '×', div: '÷', pm: '±', mp: '∓', le: '≤', leq: '≤', ge: '≥', geq: '≥', neq: '≠', ne: '≠',
  approx: '≈', sim: '∼', equiv: '≡', propto: '∝', infty: '∞', partial: '∂', nabla: '∇', sum: 'Σ', prod: 'Π',
  int: '∫', oint: '∮', to: '→', rightarrow: '→', leftarrow: '←', Rightarrow: '⇒', Leftrightarrow: '⇔',
  leftrightarrow: '↔', in: '∈', notin: '∉', subset: '⊂', subseteq: '⊆', cup: '∪', cap: '∩', forall: '∀',
  exists: '∃', degree: '°', circ: '∘', ldots: '…', cdots: '⋯', dots: '…', quad: ' ', qquad: '  ', ',': ' ',
};
const SUPERSCRIPTS: Record<string, string> = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '+': '⁺', '-': '⁻', 'n': 'ⁿ', 'i': 'ⁱ' };
const SUBSCRIPTS: Record<string, string> = { '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉', '+': '₊', '-': '₋' };

function mapScript(text: string, table: Record<string, string>, mark: string): string {
  const chars = Array.from(text);
  return chars.every(c => table[c]) ? chars.map(c => table[c]).join('') : `${mark}(${text})`;
}

/** Readable plain-text version of a LaTeX formula for apps without math support. */
export function latexToReadable(latex: string): string {
  let out = String(latex || '').replace(/\\(left|right|big|Big|bigg|Bigg)\b/g, '');
  // innermost groups first, so nested formulas unfold step by step
  for (let i = 0; i < 5; i += 1) {
    out = out
      .replace(/\^\{([^{}]*)\}/g, (_m, a) => mapScript(a, SUPERSCRIPTS, '^'))
      .replace(/_\{([^{}]*)\}/g, (_m, a) => mapScript(a, SUBSCRIPTS, '_'))
      .replace(/\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}/g, '$1')
      .replace(/\\(?:d|t)?frac\{([^{}]*)\}\{([^{}]*)\}/g, (_m, a, b) => `(${a})/(${b})`)
      .replace(/\\sqrt\{([^{}]*)\}/g, (_m, a) => `√(${a})`);
  }
  out = out
    .replace(/\^(\w)/g, (_m, a) => mapScript(a, SUPERSCRIPTS, '^'))
    .replace(/_(\w)/g, (_m, a) => mapScript(a, SUBSCRIPTS, '_'))
    .replace(/\\([A-Za-z]+|,)/g, (m, name) => LATEX_SYMBOLS[name] ?? name)
    .replace(/[{}]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return out;
}

/** Google Docs cannot paste KaTeX: formulas become readable text (blocks centred and in italics). */
function replaceMathForDocs(doc: Document): void {
  doc.querySelectorAll('[data-math-block]').forEach(node => {
    const p = doc.createElement('p');
    p.setAttribute('style', 'text-align:center;font-style:italic;');
    p.textContent = latexToReadable(node.getAttribute('data-math-block') || '');
    node.replaceWith(p);
  });
  doc.querySelectorAll('[data-math]').forEach(node => {
    const span = doc.createElement('span');
    span.setAttribute('style', 'font-style:italic;');
    span.textContent = latexToReadable(node.getAttribute('data-math') || '');
    node.replaceWith(span);
  });
}

export const prepareHtmlForClipboard = async (html: string): Promise<string> => {
  if (!html || typeof html !== 'string') {
    return html;
  }

  if (typeof DOMParser === 'undefined') {
    return html;
  }

  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<body>${html}</body>`, 'text/html');
    replaceMathForDocs(doc);
    const images = Array.from(doc.body.querySelectorAll<HTMLImageElement>('img'));

    if (!images.length) {
      return doc.body.innerHTML;
    }

    await Promise.all(
      images.map(async (img) => {
        const parentContainer = img.closest('[data-editor-image]') as HTMLElement | null;

        let widthPercent = 56;
        if (parentContainer?.hasAttribute('data-width')) {
          widthPercent = clampWidthPercent(parentContainer.getAttribute('data-width'));
        } else if (img.hasAttribute('data-width')) {
          widthPercent = clampWidthPercent(img.getAttribute('data-width'));
        } else if (img.getAttribute('width')) {
          const px = Number.parseFloat(img.getAttribute('width') || '');
          if (Number.isFinite(px) && px > 0) {
            widthPercent = clampWidthPercent(Math.round((px / EDITOR_CONTENT_WIDTH_PX) * 100));
          }
        } else if (img.style.width && img.style.width.endsWith('%')) {
          widthPercent = clampWidthPercent(img.style.width);
        }

        const targetPx = Math.round((EDITOR_CONTENT_WIDTH_PX * widthPercent) / 100);

        img.setAttribute('width', String(targetPx));
        img.setAttribute(
          'style',
          `display:block;width:${widthPercent}%;max-width:100%;height:auto;margin:0 auto;padding:0;text-align:center;`
        );
        img.setAttribute('align', 'center');

        if (parentContainer) {
          parentContainer.setAttribute(
            'style',
            'width:100%;max-width:100%;position:relative;float:none;margin:14px auto;margin-left:auto;margin-right:auto;display:block;clear:both;text-align:center;'
          );
          parentContainer.setAttribute('align', 'center');
        }

        const src = img.getAttribute('src');
        if (src && src.startsWith('data:image/')) {
          const resampled = await optimizeDataUrlImage(src, {
            format: 'image/jpeg',
            maxWidth: targetPx,
            maxHeight: Math.round(targetPx * 3),
            quality: 0.92,
          });
          if (resampled) {
            img.setAttribute('src', resampled);
          }
        }
      })
    );

    return doc.body.innerHTML;
  } catch {
    return html;
  }
};

export const convertWebpImagesInHtml = async (html: string): Promise<string> => {
  return prepareHtmlForClipboard(html);
};

export const readAndOptimizeImageAsDataUrl = async (
  file: File,
  options: ImageOptimizationOptions = {}
): Promise<string> => {
  const rawDataUrl = await readFileAsDataUrl(file);
  return optimizeDataUrlImage(rawDataUrl, options);
};

export const DEFAULT_MODEL = 'gemini-2.5-flash';

export const MODEL_ORDER: string[] = [
  'gemini-2.5-flash',
  'gemini-3.5-flash',
  'gemini-3.6-flash',
  'gemini-3.7-flash',
  'gemini-3.8-flash',
];

export const MODEL_DISPLAY_NAMES: Record<string, string> = {
  'gemini-2.5-flash': 'Gemini 2.5 Flash',
  'gemini-3.5-flash': 'Gemini 3.5 Flash',
  'gemini-3.6-flash': 'Gemini 3.6 Flash',
  'gemini-3.7-flash': 'Gemini 3.7 Flash',
  'gemini-3.8-flash': 'Gemini 3.8 Flash',
};

export function getModelDisplayName(modelId: string): string {
  const cleaned = (modelId || '').trim();
  return MODEL_DISPLAY_NAMES[cleaned] || cleaned;
}

export function sortModelsByVersion<T extends { id?: string } | string>(models: T[]): T[] {
  const getVersionKey = (item: T): string => {
    const id = typeof item === 'string' ? item : item.id || '';
    return id.toLowerCase().trim();
  };

  return [...models].sort((a, b) => {
    const keyA = getVersionKey(a);
    const keyB = getVersionKey(b);
    const idxA = MODEL_ORDER.indexOf(keyA);
    const idxB = MODEL_ORDER.indexOf(keyB);
    if (idxA !== -1 && idxB !== -1) return idxA - idxB;
    if (idxA !== -1) return -1;
    if (idxB !== -1) return 1;
    return keyA.localeCompare(keyB, undefined, { numeric: true });
  });
}

/**
 * Compare two semver-like version strings (e.g. 'v2.6.0' and '2.5.1').
 * Returns > 0 if a > b, < 0 if a < b, 0 if equal.
 */
export function compareVersions(a: string, b: string): number {
  const parse = (v: string) => String(v || '').replace(/^v/, '').split('.').map(p => parseInt(p, 10) || 0);
  const [aMaj = 0, aMin = 0, aPatch = 0] = parse(a);
  const [bMaj = 0, bMin = 0, bPatch = 0] = parse(b);
  return aMaj !== bMaj ? aMaj - bMaj : aMin !== bMin ? aMin - bMin : aPatch - bPatch;
}
