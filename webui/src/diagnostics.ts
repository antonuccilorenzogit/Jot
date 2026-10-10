/** Bounded error reports, including failures before pywebview's bridge is ready. */
type Event = { kind: string; message: string; stack: string };
const pending: Event[] = [];
let installed = false;
let sent = 0;
let draining = false;
let retries = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
const seen = new Set<string>();

async function drain() {
  const api = window.pywebview?.api?.record_frontend_event;
  if (!api || draining || retryTimer !== null) return;
  draining = true;
  try {
    while (pending.length) {
      const event = pending[0];
      try {
        const result = await api(event.kind, event.message, event.stack);
        if (!result.ok) break;
        pending.shift();
        retries = 0;
      } catch { break; }
    }
  } finally {
    draining = false;
    if (pending.length && retries < 3) {
      retries += 1;
      retryTimer = setTimeout(() => {
        retryTimer = null;
        void drain();
      }, 1000);
    }
  }
}

export function reportClientError(source: string, error: unknown = 'Errore senza dettagli') {
  // Keep developer-console behavior; production builds drop this statement,
  // while the explicit bridge report below remains.
  console.error(source, error);
  const message = `${source}: ${error instanceof Error ? error.message : String(error)}`.slice(0, 3000);
  const stack = error instanceof Error ? (error.stack || '').slice(0, 6000) : '';
  enqueue({ kind: source === 'react' ? 'react' : 'error', message, stack });
}

function enqueue(event: Event) {
  const key = `${event.kind}:${event.message}`;
  if (seen.has(key) || sent >= 30 || pending.length >= 20) return;
  seen.add(key);
  sent += 1;
  pending.push(event);
  void drain();
}

export function reportFrontendReady() {
  enqueue({ kind: 'ready', message: '', stack: '' });
}

export function installFrontendDiagnostics() {
  if (installed) return;
  installed = true;
  document.documentElement.dataset.diagnosticsReady = 'true';
  window.addEventListener('pywebviewready', () => { void drain(); });
  window.addEventListener('error', event => reportClientError('window', event.error || event.message));
  window.addEventListener('unhandledrejection', event => {
    const reason = event.reason;
    enqueue({ kind: 'unhandledrejection', message: String(reason instanceof Error ? reason.message : reason).slice(0, 3000), stack: reason instanceof Error ? (reason.stack || '').slice(0, 6000) : '' });
  });
}
