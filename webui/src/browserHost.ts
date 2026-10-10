import type { FileDescriptor } from './appState';
import type { PywebviewApi } from './bridge';
import { STORAGE_KEYS } from './storageKeys';

export interface HostCapabilities {
  fileUpload: boolean;
  fileDrop: boolean;
  nativeFolderPicker: boolean;
  openLocalPath: boolean;
  osNotifications: boolean;
  updateInstallation: boolean;
  realPipeline: boolean;
  credentialPersistence: boolean;
  windowControls: boolean;
}

const DESKTOP_CAPABILITIES: HostCapabilities = {
  fileUpload: true,
  fileDrop: true,
  nativeFolderPicker: true,
  openLocalPath: true,
  osNotifications: true,
  updateInstallation: true,
  realPipeline: true,
  credentialPersistence: true,
  windowControls: true,
};

let hostCapabilities: HostCapabilities = DESKTOP_CAPABILITIES;

export function getHostCapabilities(): HostCapabilities {
  return hostCapabilities;
}

let sessionToken = '';
let lastSequence = 0;
type BrowserBridgeEvent = { sequence?: number; name?: string; payload?: unknown };
const pendingBridgeEvents: BrowserBridgeEvent[] = [];
let pendingBridgeDrainTimer: ReturnType<typeof setTimeout> | null = null;

const BROWSER_TRANSIENT_STORAGE_KEYS = [
  STORAGE_KEYS.HAS_SESSIONS_V1,
  STORAGE_KEYS.EDITOR_SESSIONS_V1,
  STORAGE_KEYS.QUEUE_V1,
  STORAGE_KEYS.NOTIFICATIONS_V1,
] as const;

function isolateBrowserStorage(instanceToken: string) {
  try {
    if (window.localStorage.getItem(STORAGE_KEYS.BROWSER_INSTANCE_V1) === instanceToken) return;
    for (const key of BROWSER_TRANSIENT_STORAGE_KEYS) {
      window.localStorage.removeItem(key);
    }
    window.localStorage.setItem(STORAGE_KEYS.BROWSER_INSTANCE_V1, instanceToken);
  } catch (_) {
    // Browser storage is optional; the isolated backend remains authoritative.
  }
}

function drainPendingBridgeEvents() {
  pendingBridgeDrainTimer = null;
  const bridge = window.jotBridge as unknown as Record<string, (payload: unknown) => void> | null | undefined;
  if (!bridge) {
    if (pendingBridgeEvents.length > 0) {
      pendingBridgeDrainTimer = setTimeout(drainPendingBridgeEvents, 10);
    }
    return;
  }

  while (pendingBridgeEvents.length > 0) {
    const msg = pendingBridgeEvents.shift()!;
    if (msg.name && typeof bridge[msg.name] === 'function') {
      bridge[msg.name](msg.payload);
    }
    if (typeof msg.sequence === 'number') {
      lastSequence = msg.sequence;
    }
  }
}

function queueBridgeEvent(msg: BrowserBridgeEvent) {
  pendingBridgeEvents.push(msg);
  if (pendingBridgeDrainTimer === null) {
    pendingBridgeDrainTimer = setTimeout(drainPendingBridgeEvents, 0);
  }
}

function getApiBaseUrl(): string {
  if (typeof window === 'undefined') return '';
  // When running in Vite dev (port 3000), FastAPI is usually on port 8000 or 8080.
  // Vite proxy or direct port resolution:
  return '';
}

async function callRpc<T = unknown>(method: string, ...args: unknown[]): Promise<T> {
  const url = `${getApiBaseUrl()}/api/rpc/${encodeURIComponent(method)}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Session-Token': sessionToken,
    },
    credentials: 'include',
    body: JSON.stringify({ args }),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || data.error || `RPC error HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function promptFileInput(multiple: boolean, accept: string): Promise<FileList | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = multiple;
    input.accept = accept;
    input.style.display = 'none';

    input.onchange = () => {
      resolve(input.files);
      input.remove();
    };
    input.oncancel = () => {
      resolve(null);
      input.remove();
    };

    document.body.appendChild(input);
    input.click();
  });
}

async function uploadSelectedFiles(fileList: FileList | File[]): Promise<FileDescriptor[]> {
  const formData = new FormData();
  for (const file of Array.from(fileList)) {
    formData.append('files', file);
  }

  const res = await fetch(`${getApiBaseUrl()}/api/upload`, {
    method: 'POST',
    headers: {
      'X-Session-Token': sessionToken,
    },
    credentials: 'include',
    body: formData,
  });

  if (!res.ok) {
    throw new Error(`Upload fallito (HTTP ${res.status})`);
  }
  const data = await res.json();
  return (data.files || []) as FileDescriptor[];
}

function setupWebSocket() {
  if (typeof WebSocket === 'undefined') return;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const wsUrl = `${protocol}//${host}/api/events?token=${encodeURIComponent(sessionToken)}&last_sequence=${lastSequence}`;

  const ws = new WebSocket(wsUrl);

  ws.onmessage = (event) => {
    try {
      queueBridgeEvent(JSON.parse(event.data) as BrowserBridgeEvent);
    } catch (e) {
      console.error('Errore parsing evento WebSocket:', e);
    }
  };

  ws.onclose = () => {
    // Reconnect after brief delay, refreshing token in case server restarted
    setTimeout(async () => {
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/bootstrap`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          if (data.session_token) sessionToken = data.session_token;
        }
      } catch (_) {}
      setupWebSocket();
    }, 2000);
  };
}

export function createBrowserPywebviewApi(): PywebviewApi {

  return {
    load_settings: () => callRpc('load_settings'),
    save_settings: (apiKey, fallbackKeys, preferredModel, fallbackModels) =>
      callRpc('save_settings', apiKey, fallbackKeys, preferredModel, fallbackModels),
    check_path_exists: (path) => callRpc('check_path_exists', path),
    start_processing: (files, apiKey, resumeSession, preferredModel, fallbackModels, overrideLowDisk, forceRetry) =>
      callRpc('start_processing', files, apiKey, resumeSession, preferredModel, fallbackModels, overrideLowDisk, forceRetry),
    stop_processing: () => callRpc('stop_processing'),
    is_processing_active: () => callRpc('is_processing_active'),
    answer_regenerate: (regenerate) => callRpc('answer_regenerate', regenerate),
    answer_new_key: (key) => callRpc('answer_new_key', key),
    read_html_content: (path) => callRpc('read_html_content', path),
    save_html_content: (path, content, generation) => callRpc('save_html_content', path, content, generation),
    validate_environment: (apiKey, checkApiKey, preferredModel, fallbackModels) =>
      callRpc('validate_environment', apiKey, checkApiKey, preferredModel, fallbackModels),
    get_session_storage_info: () => callRpc('get_session_storage_info'),
    cleanup_old_sessions: (maxAgeDays, dryRun) => callRpc('cleanup_old_sessions', maxAgeDays, dryRun),
    cleanup_completed_sessions: (maxAgeDays, dryRun) => callRpc('cleanup_completed_sessions', maxAgeDays, dryRun),
    get_completed_sessions: (limit) => callRpc('get_completed_sessions', limit),
    delete_session: (sessionDir) => callRpc('delete_session', sessionDir),
    update_session_input_path: (sessionDir, newPath) => callRpc('update_session_input_path', sessionDir, newPath),
    remove_session_audio: (sessionDir) => callRpc('remove_session_audio', sessionDir),
    touch_session_opened: (sessionDir) => callRpc('touch_session_opened', sessionDir),
    get_archive_folders: () => callRpc('get_archive_folders'),
    save_archive_folders: (folders) => callRpc('save_archive_folders', folders),
    search_sessions: (query, limit) => callRpc('search_sessions', query, limit),
    retry_failed_revision_blocks: (sessionDir) => callRpc('retry_failed_revision_blocks', sessionDir),
    get_api_usage: (apiKey, fallbackKeys, preferredModel, fallbackModels, forceRefresh) =>
      callRpc('get_api_usage', apiKey, fallbackKeys, preferredModel, fallbackModels, forceRefresh),
    get_diagnostic_report: (apiKey, fallbackKeys, preferredModel, fallbackModels) =>
      callRpc('get_diagnostic_report', apiKey, fallbackKeys, preferredModel, fallbackModels),
    save_theme_preference: (theme) => callRpc('save_theme_preference', theme),
    set_browser_scenario: (scenario) => callRpc('set_browser_scenario', scenario),

    // File picking and uploads
    ask_files: async () => {
      const files = await promptFileInput(true, 'audio/*,video/*,.mp3,.m4a,.wav,.ogg,.opus,.mp4,.mov,.mkv');
      if (!files || files.length === 0) return [];
      return uploadSelectedFiles(files);
    },
    upload_browser_files: (files) => uploadSelectedFiles(files),
    ask_media_file: async () => {
      const files = await promptFileInput(false, 'audio/*,video/*,.mp3,.m4a,.wav,.ogg,.opus,.mp4,.mov,.mkv');
      if (!files || files.length === 0) return null;
      const uploaded = await uploadSelectedFiles(files);
      return uploaded[0] || null;
    },
    collect_dropped_files: async (_names) => {
      return { ok: true };
    },

    // Package import/export
    import_sbobina_package: async () => {
      const files = await promptFileInput(false, '.sbobina,.zip');
      if (!files || files.length === 0) return { ok: false, cancelled: true };
      const formData = new FormData();
      formData.append('package', files[0]);
      const res = await fetch(`${getApiBaseUrl()}/api/upload_package`, {
        method: 'POST',
        headers: { 'X-Session-Token': sessionToken },
        credentials: 'include',
        body: formData,
      });
      return res.json();
    },
    export_sbobina_package: async (sessionDir, exportType) => {
      const downloadUrl = `${getApiBaseUrl()}/api/export_package?session_dir=${encodeURIComponent(sessionDir)}&export_type=${encodeURIComponent(exportType || 'full')}`;
      const res = await fetch(downloadUrl, {
        headers: { 'X-Session-Token': sessionToken },
        credentials: 'include',
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || data.error || `Esportazione fallita (HTTP ${res.status})`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get('content-disposition') || '';
      const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
      const filename = filenameMatch ? decodeURIComponent(filenameMatch[1].replace(/"/g, '')) : 'sbobina.sbobina';
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objectUrl);
      return { ok: true, target_path: filename };
    },

    // Streaming media
    stream_media_file: async (path, sessionDir) => {
      const query = new URLSearchParams();
      if (path) query.set('path', path);
      if (sessionDir) query.set('session_dir', sessionDir);
      const res = await fetch(`${getApiBaseUrl()}/api/media/resolve?${query}`, {
        headers: { 'X-Session-Token': sessionToken },
        credentials: 'include',
      });
      if (!res.ok) {
        return { ok: false, has_audio: false, error: `Streaming non disponibile (HTTP ${res.status})` };
      }
      const data = await res.json();
      return data as { ok: boolean; url?: string; has_audio?: boolean; error?: string };
    },

    // Browser fallbacks for desktop-only features
    open_url: async (url) => {
      window.open(url, '_blank');
      return { ok: true };
    },
    open_file: async (_path) => {
      return { ok: false, error: 'Disponibile nell’app desktop' };
    },
    show_notification: async () => {},
    flash_window: async () => ({ ok: true }),
    close_window: async () => ({ ok: true }),
    open_session_folder: async () => ({ ok: false, error: 'Disponibile nell’app desktop' }),
    ask_session_folder: async () => ({ ok: false, error: 'Disponibile nell’app desktop' }),
    move_session_root: async () => ({ ok: false, error: 'Disponibile nell’app desktop' }),
    get_session_move_status: async () => ({ status: 'idle', error: 'Disponibile nell’app desktop' }),
    download_and_install_update: async () => ({ ok: false, error: 'Disponibile nell’app desktop' }),
    open_logs_folder: async () => ({ ok: false, error: 'Disponibile nell’app desktop' }),
  };
}

export async function initBrowserHost(): Promise<boolean> {
  if (typeof window === 'undefined') return false;

  // If running inside pywebview desktop, pywebview host takes absolute priority
  if (window.pywebview?.api) {
    return false;
  }

  try {
    const res = await fetch(`${getApiBaseUrl()}/api/bootstrap`, { credentials: 'include' });
    if (!res.ok) {
      console.warn('Bootstrap FastAPI non disponibile (HTTP ' + res.status + ')');
      return false;
    }
    const data = await res.json();
    sessionToken = data.session_token || '';
    isolateBrowserStorage(sessionToken);
    lastSequence = Number(data.event_sequence || 0);
    if (data.capabilities) {
      hostCapabilities = { ...DESKTOP_CAPABILITIES, ...data.capabilities };
    }

    window.pywebview = {
      api: createBrowserPywebviewApi(),
    };

    setupWebSocket();

    window.dispatchEvent(new Event('pywebviewready'));
    return true;
  } catch (err) {
    console.warn('Inizializzazione browser host non riuscita:', err);
    return false;
  }
}
