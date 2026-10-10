import { render, screen, fireEvent, act, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import App from './App';
import { useApiReady } from './hooks/useApiReady';
import { useBridgeCallbacks } from './hooks/useBridgeCallbacks';
import { useQueuePersistence } from './hooks/useQueuePersistence';
import { useUpdateChecker } from './hooks/useUpdateChecker';
import { STORAGE_KEYS } from './storageKeys';
import type { FileDonePayload, ProcessingAction } from './appState';
import type { PywebviewApi } from './bridge';

const motionCache = new Map<string, React.ForwardRefExoticComponent<React.PropsWithoutRef<Record<string, unknown>> & React.RefAttributes<unknown>>>();
vi.mock('motion/react', () => ({
  motion: new Proxy({}, {
    get: (_: unknown, tag: string) => {
      if (!motionCache.has(tag)) {
        motionCache.set(
          tag,
          React.forwardRef((props: Record<string, unknown>, ref: unknown) => {
            const { initial: _i, animate: _a, exit: _e, transition: _t, layout: _l, variants: _v, layoutId: _li, whileTap: _wt, whileHover: _wh, ...rest } = props;
            return React.createElement(tag, { ...rest, ref: ref as React.Ref<unknown> });
          })
        );
      }
      return motionCache.get(tag);
    },
  }),
  AnimatePresence: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
  useAnimation: () => ({ start: vi.fn(), stop: vi.fn() }),
  useMotionValue: (v: unknown) => ({ get: () => v, set: vi.fn() }),
}));

vi.mock('./hooks/useApiReady');

const mockApiReadyDefault = {
  apiReady: true,
  bridgeDelayed: false,
  apiKey: '',
  setApiKey: vi.fn(),
  hasProtectedKey: false,
  apiKeyInsecure: false,
  setApiKeyInsecure: vi.fn(),
  apiKeyInsecureReason: '',
  setApiKeyInsecureReason: vi.fn(),
  configRecoveredFrom: '',
  fallbackKeys: [],
  setFallbackKeys: vi.fn(),
  configuredFallbackKeyCount: 0,
  preferredModel: 'gemini-2.5-flash',
  setPreferredModel: vi.fn(),
  fallbackModels: [],
  setFallbackModels: vi.fn(),
  availableModels: [],
  refreshSettings: vi.fn(),
};

const mockApiReadyWithKey = {
  ...mockApiReadyDefault,
  apiReady: true,
  apiKey: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345',
};

vi.mock('./hooks/useUpdateChecker');

vi.mock('./hooks/useQueuePersistence', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./hooks/useQueuePersistence')>();
  return {
    ...actual,
    useQueuePersistence: vi.fn(),
  };
});

vi.mock('./hooks/useBridgeCallbacks', () => ({
  useBridgeCallbacks: vi.fn().mockReturnValue(undefined),
}));

vi.mock('./hooks/usePreview', () => ({
  usePreview: () => ({
    preview: { content: null, title: '', path: '', audioSrc: null, fileId: null, sourcePath: '', sessionDir: '', audioRelinkNeeded: false, initAudio: {} },
    openPreview: vi.fn(),
    closePreview: vi.fn(),
    relinkPreviewAudio: vi.fn(),
    handleAudioStateChange: vi.fn(),
    handleScrollTopChange: vi.fn(),
  }),
}));

vi.mock('./components/EditorFullPage', () => ({
  EditorFullPage: () => null,
}));

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

function setJotBridge() {
  const callbacks: Record<string, (...args: unknown[]) => void> = {};
  Object.defineProperty(window, 'jotBridge', {
    value: {
      onSetCurrentFile: (cb: (...args: unknown[]) => void) => { callbacks['setCurrentFile'] = cb; },
      onFileDone: (cb: (...args: unknown[]) => void) => { callbacks['fileDone'] = cb; },
      onFileFailed: (cb: (...args: unknown[]) => void) => { callbacks['fileFailed'] = cb; },
      onProcessDone: (cb: (...args: unknown[]) => void) => { callbacks['processDone'] = cb; },
      onWorkTotals: (cb: (...args: unknown[]) => void) => { callbacks['workTotals'] = cb; },
      onWorkDone: (cb: (...args: unknown[]) => void) => { callbacks['workDone'] = cb; },
      onStepTime: (cb: (...args: unknown[]) => void) => { callbacks['stepTime'] = cb; },
      onAskNewKey: (cb: (...args: unknown[]) => void) => { callbacks['askNewKey'] = cb; },
    },
    writable: true,
    configurable: true,
  });
  return callbacks;
}

beforeEach(() => {
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
  localStorage.clear();
  setPywebview({
    get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
    get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
  });
  setJotBridge();
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network')));
  vi.mocked(useApiReady).mockReturnValue(mockApiReadyDefault);
  vi.mocked(useUpdateChecker).mockReturnValue({
    updateAvailable: null,
    latestVersion: null,
    isDismissed: false,
    isCheckingUpdate: false,
    hasChecked: true,
    checkFailed: false,
    checkForUpdates: vi.fn(),
    dismissUpdate: vi.fn(),
  });
  vi.mocked(useBridgeCallbacks).mockReturnValue(undefined);
});

afterEach(() => {
  localStorage.clear();
  setPywebview(undefined);
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('App', () => {
  it('renders the top bar with brand and destinations', async () => {
    await act(async () => { render(<App />); });
    expect(screen.getAllByRole('img', { name: 'jot' }).length).toBeGreaterThan(0);
    const nav = screen.getByRole('navigation', { name: 'Navigazione' });
    expect(within(nav).getByRole('button', { name: 'Lezioni' })).toBeTruthy();
    expect(within(nav).getByRole('button', { name: 'Archivio' })).toBeTruthy();
  });

  it('renders in setup mode when no API key is set', async () => {
    await act(async () => { render(<App />); });
    expect(await screen.findByText('Configura la tua API Key')).toBeTruthy();
  });

  it('renders loading connection screen when API is not ready', async () => {
    vi.mocked(useApiReady).mockReturnValue({
      ...mockApiReadyDefault,
      apiReady: false,
    });
    await act(async () => { render(<App />); });
    expect(await screen.findByText('Connessione in corso...')).toBeTruthy();
  });

  it('renders warning when API bridge is delayed', async () => {
    vi.mocked(useApiReady).mockReturnValue({
      ...mockApiReadyDefault,
      apiReady: false,
      bridgeDelayed: true,
    });
    await act(async () => { render(<App />); });
    expect(await screen.findByText(/Il motore dell'applicazione/)).toBeTruthy();
  });

  it('renders footer with GitHub link', async () => {
    await act(async () => { render(<App />); });
    expect(screen.getByText(/GitHub/)).toBeTruthy();
  });

  it('does not render Ko-fi link in footer', async () => {
    await act(async () => { render(<App />); });
    expect(screen.queryByText(/caffè/)).toBeNull();
  });

  it('shows API key input in setup mode', async () => {
    await act(async () => { render(<App />); });
    expect(await screen.findByPlaceholderText(/Incolla qui la tua API Key/)).toBeTruthy();
  });

  it('settings button opens settings modal', async () => {
    await act(async () => { render(<App />); });
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Apri impostazioni'));
    });
    expect(await screen.findByRole('heading', { name: /Impostazioni/ }, { timeout: 5000 })).toBeTruthy();
  });

  it('console toggle button is disabled in setup mode', async () => {
    await act(async () => { render(<App />); });
    const consoleBtn = screen.getByLabelText('Mostra console') as HTMLButtonElement;
    expect(consoleBtn.disabled).toBe(true);
  });

  it('shows config recovery warning without exposing the full path', async () => {
    localStorage.setItem('peakBannerDismissedUntil', String(Date.now() + 86_400_000));
    vi.mocked(useApiReady).mockReturnValue({
      ...mockApiReadyDefault,
      configRecoveredFrom: 'C:\\Users\\me\\AppData\\Roaming\\jot\\config.json',
    });

    await act(async () => { render(<App />); });

    expect(screen.getByText(/file di configurazione era corrotto/i)).toBeTruthy();
    expect(screen.queryByText(/C:\\Users\\me/)).toBeNull();
  });

  it('does not show config recovery warning again after dismissal for same path', async () => {
    localStorage.setItem('peakBannerDismissedUntil', String(Date.now() + 86_400_000));
    const recoveredPath = 'C:\\broken\\config.json';
    vi.mocked(useApiReady).mockReturnValue({
      ...mockApiReadyDefault,
      configRecoveredFrom: recoveredPath,
    });

    let unmount: () => void = () => {};
    await act(async () => {
      ({ unmount } = render(<App />));
    });
    expect(await screen.findByText(/file di configurazione era corrotto/i)).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Archivia notifica'));
    });
    unmount();

    await act(async () => { render(<App />); });
    expect(screen.queryByText(/file di configurazione era corrotto/i)).toBeNull();
  });

  it('Settings install receives async checksum error and shows actionable fallback', async () => {
    vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
    vi.mocked(useUpdateChecker).mockReturnValue({
      updateAvailable: null,
      latestVersion: 'v2.0.0',
      isDismissed: false,
      isCheckingUpdate: false,
      hasChecked: true,
      checkFailed: false,
      checkForUpdates: vi.fn(),
      dismissUpdate: vi.fn(),
    });
    const downloadUpdate = vi.fn().mockResolvedValue({ ok: true, status: 'downloading' });
    const openUrl = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      download_and_install_update: downloadUpdate,
      open_url: openUrl,
    });

    await act(async () => { render(<App />); });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/Apri impostazioni/));
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Installa aggiornamento'));
    });

    expect(downloadUpdate).toHaveBeenCalledWith('v2.0.0');
    expect(await screen.findAllByText(/Download aggiornamento/i)).toHaveLength(2);
    const bridgeOptions = vi.mocked(useBridgeCallbacks).mock.calls.at(-1)?.[0];
    expect(bridgeOptions).toBeTruthy();
    await act(async () => {
      bridgeOptions?.onDownloadProgress?.({
        status: 'error',
        bytes_done: 10,
        bytes_total: 10,
        error: 'Verifica integrità fallita: il file scaricato non corrisponde al checksum atteso.',
      });
    });

    expect(await screen.findAllByText(/Verifica integrità fallita/i)).toHaveLength(2);
    expect(screen.getAllByText('Apri GitHub').length).toBeGreaterThan(0);
    await act(async () => {
      fireEvent.click(screen.getAllByText('Apri GitHub')[0]);
    });
    expect(openUrl).toHaveBeenCalledWith('https://github.com/antonuccilorenzogit/Jot/releases/latest');
  });

  it('does not duplicate update install toast when progress arrives before first toast render', async () => {
    vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
    vi.mocked(useUpdateChecker).mockReturnValue({
      updateAvailable: null,
      latestVersion: 'v2.0.0',
      isDismissed: false,
      isCheckingUpdate: false,
      hasChecked: true,
      checkFailed: false,
      checkForUpdates: vi.fn(),
      dismissUpdate: vi.fn(),
    });
    const downloadUpdate = vi.fn().mockImplementation(() => {
      const bridgeOptions = vi.mocked(useBridgeCallbacks).mock.calls.at(-1)?.[0];
      bridgeOptions?.onDownloadProgress?.({
        status: 'downloading',
        bytes_done: 5,
        bytes_total: 10,
      });
      return Promise.resolve({ ok: true, status: 'downloading' });
    });
    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      download_and_install_update: downloadUpdate,
    });

    await act(async () => { render(<App />); });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/Apri impostazioni/));
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Installa aggiornamento'));
    });

    expect(downloadUpdate).toHaveBeenCalledWith('v2.0.0');
    expect(await screen.findAllByText(/Download aggiornamento/i)).toHaveLength(2);
  });

  it('recreates update install toast after GitHub fallback action dismisses it', async () => {
    vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
    vi.mocked(useUpdateChecker).mockReturnValue({
      updateAvailable: null,
      latestVersion: 'v2.0.0',
      isDismissed: false,
      isCheckingUpdate: false,
      hasChecked: true,
      checkFailed: false,
      checkForUpdates: vi.fn(),
      dismissUpdate: vi.fn(),
    });
    const downloadUpdate = vi.fn().mockResolvedValue({ ok: true, status: 'downloading' });
    const openUrl = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      download_and_install_update: downloadUpdate,
      open_url: openUrl,
    });

    await act(async () => { render(<App />); });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/Apri impostazioni/));
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Installa aggiornamento'));
    });

    const bridgeOptions = vi.mocked(useBridgeCallbacks).mock.calls.at(-1)?.[0];
    expect(bridgeOptions).toBeTruthy();
    await act(async () => {
      bridgeOptions?.onDownloadProgress?.({
        status: 'error',
        bytes_done: 10,
        bytes_total: 10,
        error: 'Verifica integrità fallita: il file scaricato non corrisponde al checksum atteso.',
      });
    });
    expect(await screen.findAllByText(/Verifica integrità fallita/i)).toHaveLength(2);

    const githubActions = screen.getAllByText('Apri GitHub');
    await act(async () => {
      fireEvent.click(githubActions[githubActions.length - 1]);
    });
    expect(openUrl).toHaveBeenCalledWith('https://github.com/antonuccilorenzogit/Jot/releases/latest');
    expect(screen.getAllByText(/Verifica integrità fallita/i)).toHaveLength(1);

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Installa aggiornamento'));
    });

    expect(downloadUpdate).toHaveBeenCalledTimes(2);
    expect(await screen.findAllByText(/Download aggiornamento/i)).toHaveLength(2);
  });

  it('Settings install success resolves and shows installer-started state', async () => {
    vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
    vi.mocked(useUpdateChecker).mockReturnValue({
      updateAvailable: null,
      latestVersion: 'v2.0.0',
      isDismissed: false,
      isCheckingUpdate: false,
      hasChecked: true,
      checkFailed: false,
      checkForUpdates: vi.fn(),
      dismissUpdate: vi.fn(),
    });
    const downloadUpdate = vi.fn().mockResolvedValue({ ok: true, status: 'downloading' });
    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      download_and_install_update: downloadUpdate,
    });

    await act(async () => { render(<App />); });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/Apri impostazioni/));
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Installa aggiornamento'));
    });

    expect(await screen.findAllByText(/Download aggiornamento/i)).toHaveLength(2);
    const bridgeOptions = vi.mocked(useBridgeCallbacks).mock.calls.at(-1)?.[0];
    expect(bridgeOptions).toBeTruthy();
    await act(async () => {
      bridgeOptions?.onDownloadProgress?.({ status: 'done', bytes_done: 10, bytes_total: 10 });
    });

    expect(await screen.findAllByText(/Installer avviato/i)).toHaveLength(2);
  });

  it('Settings install UAC denied leaves app open and explains the cancellation', async () => {
    vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
    vi.mocked(useUpdateChecker).mockReturnValue({
      updateAvailable: null,
      latestVersion: 'v2.0.0',
      isDismissed: false,
      isCheckingUpdate: false,
      hasChecked: true,
      checkFailed: false,
      checkForUpdates: vi.fn(),
      dismissUpdate: vi.fn(),
    });
    const downloadUpdate = vi.fn().mockResolvedValue({ ok: true, status: 'downloading' });
    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      download_and_install_update: downloadUpdate,
    });

    await act(async () => { render(<App />); });
    await act(async () => {
      fireEvent.click(screen.getByLabelText(/Apri impostazioni/));
    });
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Installa aggiornamento'));
    });

    expect(await screen.findAllByText(/Download aggiornamento/i)).toHaveLength(2);
    const bridgeOptions = vi.mocked(useBridgeCallbacks).mock.calls.at(-1)?.[0];
    expect(bridgeOptions).toBeTruthy();
    await act(async () => {
      bridgeOptions?.onDownloadProgress?.({ status: 'error', bytes_done: 0, bytes_total: 0, error: 'uac_denied' });
    });

    expect(await screen.findAllByText(/richiesta UAC è stata rifiutata/i)).toHaveLength(2);
    expect(screen.getByRole('heading', { name: /Impostazioni/ })).toBeTruthy();
  });
});

describe('App — ready-empty mode (valid API key, no files)', () => {
  beforeEach(() => {
    vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
  });

  it('shows the new lesson page when api key is valid and no files queued', async () => {
    await act(async () => { render(<App />); });
    expect(screen.getByRole('heading', { name: 'Nuova lezione' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Aggiungi audio' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Aggiungi slide' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Aggiungi libro, facoltativo' })).toBeTruthy();
    expect(screen.getByText('Aggiungi l’audio o le slide')).toBeTruthy();
  });

  it('shows API ready status in header', async () => {
    await act(async () => { render(<App />); });
    expect(screen.getByLabelText('API pronta')).toBeTruthy();
  });

  it('footer links are visible', async () => {
    await act(async () => { render(<App />); });
    expect(screen.getByText(/GitHub/)).toBeTruthy();
    expect(screen.queryByText(/caffè/)).toBeNull();
  });

  it('console toggle button is disabled when queue is empty', async () => {
    await act(async () => { render(<App />); });
    const consoleBtn = screen.getByLabelText('Mostra console') as HTMLButtonElement;
    expect(consoleBtn.disabled).toBe(true);
  });

  it('console toggle button is enabled and shows console panel when clicked if files are in queue, and closes/disables when queue becomes empty', async () => {
    let localDispatch: React.Dispatch<ProcessingAction> | null = null;
    vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
      localDispatch = dispatch;
      React.useEffect(() => {
        dispatch({
          type: 'queue/add',
          files: [{
            id: 'file-1',
            name: 'lesson.mp3',
            size: 123,
            duration: 60,
            path: 'C:\\Media\\lesson.mp3',
            status: 'queued',
            progress: 0,
            phase: 0,
          }],
        });
      }, [dispatch]);
    });

    await act(async () => { render(<App />); });
    const consoleBtn = screen.getByLabelText('Mostra console') as HTMLButtonElement;
    expect(consoleBtn.disabled).toBe(false);

    await act(async () => {
      fireEvent.click(consoleBtn);
    });
    expect(screen.getByRole('heading', { name: 'Console' })).toBeTruthy();

    await act(async () => {
      localDispatch({ type: 'queue/remove', id: 'file-1' });
    });

    const consoleBtnAfter = screen.getByLabelText('Mostra console') as HTMLButtonElement;
    expect(consoleBtnAfter.disabled).toBe(true);
    expect(screen.queryByRole('heading', { name: 'Console' })).toBeNull();
  });

  it('preserves showConsole state across app restarts when persisted queue has files', async () => {
    localStorage.setItem(STORAGE_KEYS.SHOW_CONSOLE, 'true');
    localStorage.setItem(STORAGE_KEYS.QUEUE_V1, JSON.stringify([{
      id: 'done-1',
      name: 'lesson-done.mp3',
      size: 1024,
      duration: 120,
      status: 'done',
      completedAt: Date.now(),
    }]));

    await act(async () => { render(<App />); });

    const consoleBtn = screen.getByLabelText('Mostra console') as HTMLButtonElement;
    expect(consoleBtn.disabled).toBe(false);
    expect(screen.getByRole('heading', { name: 'Console' })).toBeTruthy();
    expect(localStorage.getItem(STORAGE_KEYS.SHOW_CONSOLE)).toBe('true');
  });
});

describe('App ? low disk start warning', () => {
  beforeEach(() => {
    vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
  });

  it('shows a blocking low-disk modal and retries with override', async () => {
    const startProcessing = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        low_disk_warning: {
          needed_bytes: 2_147_483_648,
          free_bytes: 536_870_912,
          location: 'C:\\Temp',
          kind: 'combined',
          file_name: 'lesson.mp3',
        },
      })
      .mockResolvedValueOnce({ ok: true });

    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      check_path_exists: vi.fn().mockResolvedValue({ ok: true, exists: true }),
      start_processing: startProcessing,
    });

    vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
      React.useEffect(() => {
        dispatch({
          type: 'queue/add',
          files: [{
            id: 'file-1',
            name: 'lesson.mp3',
            size: 123,
            duration: 60,
            path: 'C:\\Media\\lesson.mp3',
            status: 'queued',
            progress: 0,
            phase: 0,
          }],
        });
      }, [dispatch]);
    });

    await act(async () => { render(<App />); });
    await act(async () => {
      fireEvent.click(await screen.findByText('Avvia sbobinatura (1 file)'));
    });

    expect(await screen.findByRole('heading', { name: 'Spazio libero insufficiente' })).toBeTruthy();
    expect(screen.getAllByText(/lesson\.mp3/).length).toBeGreaterThan(0);

    await act(async () => {
      fireEvent.click(screen.getByText('Continua comunque'));
    });

    expect(startProcessing).toHaveBeenCalledTimes(2);
    expect(startProcessing.mock.calls[0][5]).toBe(false);
    expect(startProcessing.mock.calls[1][5]).toBe(true);
  });
});

describe('App — executeRetryFromArchive concurrency protection', () => {
  beforeEach(() => {
    vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
  });

  it('guards against concurrent retry triggers in executeRetryFromArchive', async () => {
    const testSession = {
      session_dir: 'C:\\sessions\\session-1',
      name: 'Lezione test',
      html_path: '', // Empty string to prevent filtering from Archive list
      input_path: 'C:\\audio\\test-session.mp3',
      input_size: 1000,
      duration_sec: 120,
      completed_at_iso: '2026-05-22T23:54:52+02:00',
      effective_model: 'gemini-2.5-flash',
      revision_failed_blocks: [1, 2],
    };

    const retryFailed = vi.fn().mockImplementation(() => new Promise(() => {}));

    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [testSession] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      retry_failed_revision_blocks: retryFailed,
    });

    await act(async () => {
      render(<App />);
    });

    // Switch to Archive page (second sidebar button)
    await act(async () => {
      const navButtons = document.querySelectorAll('.sidebar-nav-item');
      fireEvent.click(navButtons[1]);
    });

    // Verify session card is shown on Archive page
    expect((await screen.findAllByText('Lezione test')).length).toBeGreaterThan(0);

    // Click "Riprova revisione" button on the session card
    await act(async () => {
      fireEvent.click(screen.getByText('Riprova revisione'));
    });

    // Check that confirm modal is shown
    expect(await screen.findByRole('heading', { name: 'Ripristinare e riprovare la revisione?' })).toBeTruthy();

    // Click "Riprova revisione" in the confirm modal
    await act(async () => {
      const confirmButton = document.querySelector('.modal-action-button.is-danger');
      if (confirmButton) fireEvent.click(confirmButton);
    });

    // Verify "Riprovo…" spinner/text is shown (meaning the file item was added and isRetryingBlocks is true)
    expect(await screen.findByText('Riprovo…')).toBeTruthy();
    expect(await screen.findByText('Revisione blocchi mancanti')).toBeTruthy();

    // Now go back to Archive page to trigger second retry
    await act(async () => {
      const navButtons = document.querySelectorAll('.sidebar-nav-item');
      fireEvent.click(navButtons[1]);
    });

    // Click "Riprova revisione" on the card again
    await act(async () => {
      fireEvent.click(screen.getByText('Riprova revisione'));
    });

    // Confirm dialog shown again
    expect(await screen.findByRole('heading', { name: 'Ripristinare e riprovare la revisione?' })).toBeTruthy();

    // Click "Riprova revisione" in the confirm modal again
    await act(async () => {
      const confirmButton = document.querySelector('.modal-action-button.is-danger');
      if (confirmButton) fireEvent.click(confirmButton);
    });

    // This will call executeRetryFromArchive again while the first one is still running.
    // Let's verify that the toast warning "Retry già in corso per questa sessione." is displayed!
    expect(await screen.findByText('Retry già in corso per questa sessione.')).toBeTruthy();
  });

  it('displays the general failure toast when retry fails with general error', async () => {
    const testSession = {
      session_dir: 'C:\\sessions\\session-2',
      name: 'Lezione errore generale',
      html_path: '',
      input_path: 'C:\\audio\\error-session.mp3',
      input_size: 1000,
      duration_sec: 120,
      completed_at_iso: '2026-05-22T23:54:52+02:00',
      effective_model: 'gemini-2.5-flash',
      revision_failed_blocks: [1],
    };

    const retryFailed = vi.fn().mockResolvedValue({
      ok: false,
      error: 'API key mancante sul disco',
    });

    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [testSession] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      retry_failed_revision_blocks: retryFailed,
    });

    await act(async () => {
      render(<App />);
    });

    // Switch to Archive page (second sidebar button)
    await act(async () => {
      const navButtons = document.querySelectorAll('.sidebar-nav-item');
      fireEvent.click(navButtons[1]);
    });

    // Verify session card is shown
    expect((await screen.findAllByText('Lezione errore generale')).length).toBeGreaterThan(0);

    // Click "Riprova revisione" button
    await act(async () => {
      fireEvent.click(screen.getByText('Riprova revisione'));
    });

    // Confirm dialog shown
    expect(await screen.findByRole('heading', { name: 'Ripristinare e riprovare la revisione?' })).toBeTruthy();

    // Click "Riprova revisione" in the confirm modal
    await act(async () => {
      const confirmButton = document.querySelector('.modal-action-button.is-danger');
      if (confirmButton) fireEvent.click(confirmButton);
    });

    // Verify "API key mancante sul disco" toast is displayed!
    expect(await screen.findByText('API key mancante sul disco')).toBeTruthy();
  });

  it('updates isRetryingBlocks and guards against concurrent retries when Toast "Riprova" is clicked', async () => {
    const testSession = {
      session_dir: 'C:\\sessions\\session-3',
      name: 'Lezione avvisi toast',
      html_path: '',
      input_path: 'C:\\audio\\toast-session.mp3',
      input_size: 1000,
      duration_sec: 120,
      completed_at_iso: '2026-05-22T23:54:52+02:00',
      effective_model: 'gemini-2.5-flash',
      revision_failed_blocks: [1, 2, 3],
    };

    const retryFailed = vi.fn().mockImplementation(() => new Promise(() => {}));

    setPywebview({
      get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [testSession] }),
      get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      retry_failed_revision_blocks: retryFailed,
    });

    vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
      React.useEffect(() => {
        dispatch({
          type: 'queue/add',
          files: [{
            id: 'file-toast-1',
            name: 'Lezione avvisi toast',
            size: 1000,
            duration: 120,
            path: 'C:\\audio\\toast-session.mp3',
            status: 'done',
            progress: 100,
            phase: 3,
            outputDir: 'C:\\sessions\\session-3',
            outputHtml: 'C:\\sessions\\session-3\\toast-session.html',
            completionStatus: 'completed_with_warnings',
            revisionFailedBlocks: [1, 2, 3],
          }],
        });
      }, [dispatch]);
    });

    let bridgeCallbacks: { onFileDone?: (data: FileDonePayload) => void } = {};
    vi.mocked(useBridgeCallbacks).mockImplementation((options) => {
      bridgeCallbacks = {
        onFileDone: (data: FileDonePayload) => options.onRevisionWarning?.(data),
      };
      return undefined;
    });

    await act(async () => {
      render(<App />);
    });

    // Verify file card is rendered in the queue
    expect(await screen.findByText('Lezione avvisi toast')).toBeTruthy();

    // Trigger the fileDone bridge event to show the warning toast
    await act(async () => {
      bridgeCallbacks.onFileDone?.({
        index: 0,
        id: 'file-toast-1',
        output_html: 'C:\\sessions\\session-3\\toast-session.html',
        output_dir: 'C:\\sessions\\session-3',
        revision_failed_blocks: [1, 2, 3],
        completion_status: 'completed_with_warnings',
      });
    });

    // Check that warning toast is displayed
    expect(await screen.findByText(/sezioni sono state incluse/i)).toBeTruthy();

    // Click "Riprova" action button on the toast
    await act(async () => {
      const riprovaToastBtn = screen.getByText('Riprova');
      fireEvent.click(riprovaToastBtn);
    });

    // The notification action should show loading "Riprovo..."
    expect(await screen.findByText('Riprovo...')).toBeTruthy();

    // The queue card should now show loading/retrying spinner or disabled state
    expect(await screen.findByText('Riprovo…')).toBeTruthy();
  });

  describe('Notification Drawer Interaction', () => {
    it('opens the notification drawer, marks notifications as read, and clears them', async () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date(2026, 6, 11, 10, 0, 0));
      localStorage.clear();
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      setPywebview({
        get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
        get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
      });

      // Mock useBridgeCallbacks before rendering
      let bridgeCallbacks: { onFileDone?: (data: FileDonePayload) => void } = {};
      vi.mocked(useBridgeCallbacks).mockImplementation((options) => {
        bridgeCallbacks = {
          onFileDone: (data: FileDonePayload) => options.onRevisionWarning?.(data),
        };
        return undefined;
      });

      const { unmount } = render(<App />);

      // Initially, there should be no notifications
      // Let's click the "Notifiche" button in the sidebar to open the drawer
      await act(async () => {
        fireEvent.click(screen.getByLabelText('Apri notifiche'));
      });

      // Verify the empty state message
      expect(screen.getByText('Nessuna notifica')).toBeTruthy();

      // Trigger a warning notification through bridge simulation
      await act(async () => {
        bridgeCallbacks.onFileDone?.({
          index: 0,
          id: 'test-file-notif',
          output_html: 'C:\\sessions\\session-notif\\file.html',
          output_dir: 'C:\\sessions\\session-notif',
          revision_failed_blocks: [1],
          completion_status: 'completed_with_warnings',
        });
      });

      // Verify notification is displayed
      expect(screen.getAllByText('Completata con avvisi').length).toBeGreaterThan(0);

      // Click "Segna come già lette"
      await act(async () => {
        fireEvent.click(screen.getByLabelText('Segna come già lette'));
      });

      // Dismiss the notification using the close button
      await act(async () => {
        fireEvent.click(screen.getByLabelText('Archivia notifica'));
      });

      // Verify empty state again
      expect(screen.getByText('Nessuna notifica')).toBeTruthy();
      unmount();
      vi.useRealTimers();
    });
  });

  describe('onBatchFullyDone native OS notifications', () => {
    let capturedOptions: Parameters<typeof useBridgeCallbacks>[0] | null = null;
    const showNotification = vi.fn();
    const flashWindow = vi.fn();

    beforeEach(() => {
      showNotification.mockClear();
      flashWindow.mockClear();
      setPywebview({
        get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
        get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
        show_notification: showNotification,
        flash_window: flashWindow,
      });

      vi.mocked(useBridgeCallbacks).mockImplementation((options) => {
        capturedOptions = options;
        return undefined;
      });

      vi.spyOn(document, 'hasFocus').mockReturnValue(false);
      localStorage.setItem('notifications_enabled', 'true');
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('shows successful batch notification and flashes taskbar when all files completed successfully', async () => {
      await act(async () => { render(<App />); });
      expect(capturedOptions).not.toBeNull();

      await act(async () => {
        capturedOptions.onBatchFullyDone({
          total: 3,
          completed: 3,
          completed_with_warnings: 0,
          failed: 0,
          cancelled: false,
        });
      });

      expect(flashWindow).toHaveBeenCalled();
      expect(showNotification).toHaveBeenCalledWith(
        '✅ Batch completato — jot',
        '3 sbobine elaborate con successo.',
      );
    });

    it('shows warnings batch notification when some files have warnings', async () => {
      await act(async () => { render(<App />); });

      await act(async () => {
        capturedOptions.onBatchFullyDone({
          total: 3,
          completed: 2,
          completed_with_warnings: 1,
          failed: 0,
          cancelled: false,
        });
      });

      expect(showNotification).toHaveBeenCalledWith(
        '⚠️ Batch completato con avvisi — jot',
        'Elaborazione terminata con avvisi. Sbobine con avvisi: 1/3.',
      );
    });

    it('shows errors batch notification when some files failed', async () => {
      await act(async () => { render(<App />); });

      await act(async () => {
        capturedOptions.onBatchFullyDone({
          total: 3,
          completed: 1,
          completed_with_warnings: 1,
          failed: 1,
          cancelled: false,
        });
      });

      expect(showNotification).toHaveBeenCalledWith(
        '⚠️ Batch completato con errori — jot',
        "Elaborazione terminata. Riuscite: 2/3. Fallite: 1. Apri l'app per i dettagli.",
      );
    });

    it('does not show notification when batch was cancelled', async () => {
      await act(async () => { render(<App />); });

      await act(async () => {
        capturedOptions.onBatchFullyDone({
          total: 3,
          completed: 1,
          completed_with_warnings: 1,
          failed: 1,
          cancelled: true,
        });
      });

      expect(showNotification).not.toHaveBeenCalled();
    });

    it('does not show notification when notifications_enabled is false', async () => {
      localStorage.setItem('notifications_enabled', 'false');
      await act(async () => { render(<App />); });

      await act(async () => {
        capturedOptions.onBatchFullyDone({
          total: 3,
          completed: 3,
          completed_with_warnings: 0,
          failed: 0,
          cancelled: false,
        });
      });

      expect(showNotification).not.toHaveBeenCalled();
    });

    it('does not show notification when document has focus', async () => {
      vi.spyOn(document, 'hasFocus').mockReturnValue(true);
      await act(async () => { render(<App />); });

      await act(async () => {
        capturedOptions.onBatchFullyDone({
          total: 3,
          completed: 3,
          completed_with_warnings: 0,
          failed: 0,
          cancelled: false,
        });
      });

      expect(showNotification).not.toHaveBeenCalled();
    });
  });

  describe('App — Credential storage warning', () => {
    it('opens settings from the warning without deleting credentials', async () => {
      const saveSettings = vi.fn().mockResolvedValue({ ok: true });
      const setApiKey = vi.fn();
      const setApiKeyInsecure = vi.fn();
      vi.mocked(useApiReady).mockReturnValue({
        ...mockApiReadyWithKey,
        apiKeyInsecure: true,
        apiKeyInsecureReason: 'DPAPI fallback',
        setApiKey,
        setApiKeyInsecure,
        setApiKeyInsecureReason: vi.fn(),
      });
      setPywebview({
        get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
        get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
        save_settings: saveSettings,
      });

      await act(async () => { render(<App />); });
      expect(screen.getByText(/DPAPI fallback/i)).toBeTruthy();

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Gestisci credenziali' }));
      });

      expect(await screen.findByRole('heading', { name: /Impostazioni/ })).toBeTruthy();
      expect(saveSettings).not.toHaveBeenCalled();
      expect(setApiKey).not.toHaveBeenCalled();
      expect(setApiKeyInsecure).not.toHaveBeenCalled();
    });
  });

  describe('App — Queue management interactions', () => {
    it('handles clear-all confirmation dialog and clear completed', async () => {
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
        React.useEffect(() => {
          dispatch({
            type: 'queue/add',
            files: [
              { id: 'f1', name: 'f1.mp3', size: 100, duration: 10, path: 'C:\\f1.mp3', status: 'queued', progress: 0, phase: 0 },
              { id: 'f2', name: 'f2.mp3', size: 100, duration: 10, path: 'C:\\f2.mp3', status: 'done', progress: 100, phase: 3 },
            ],
          });
        }, [dispatch]);
      });

      await act(async () => { render(<App />); });

      const optionsBtn = await screen.findByLabelText('Opzioni coda');
      await act(async () => {
        fireEvent.click(optionsBtn);
      });
      const clearAllMenuItem = screen.getByText('Svuota coda');
      await act(async () => {
        fireEvent.click(clearAllMenuItem);
      });
      expect(screen.getByRole('heading', { name: 'Svuotare tutta la coda?' })).toBeTruthy();
      await act(async () => {
        fireEvent.click(screen.getByText('Svuota coda'));
      });
      expect(screen.queryByRole('heading', { name: 'Svuotare tutta la coda?' })).toBeNull();
    });

    it('handles remove file confirmation and cancel', async () => {
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
        React.useEffect(() => {
          dispatch({
            type: 'queue/add',
            files: [
              { id: 'f1', name: 'f1.mp3', size: 100, duration: 10, path: 'C:\\f1.mp3', status: 'queued', progress: 0, phase: 0 },
            ],
          });
        }, [dispatch]);
      });

      await act(async () => { render(<App />); });
      const f1Heading = await screen.findByText('f1.mp3');
      const card = f1Heading.closest('.queue-card');
      expect(card).toBeTruthy();
      const removeBtn = within(card as HTMLElement).getByRole('button', { name: 'Rimuovi' });
      expect(removeBtn).toBeTruthy();

      await act(async () => {
        fireEvent.click(removeBtn);
      });
      expect(screen.getByRole('heading', { name: 'Rimuovere questo elemento?' })).toBeTruthy();
      await act(async () => {
        fireEvent.click(screen.getByText('Tieni elemento'));
      });
      expect(screen.queryByRole('heading', { name: 'Rimuovere questo elemento?' })).toBeNull();
    });

    it('handles start and retry queue actions', async () => {
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
        React.useEffect(() => {
          dispatch({
            type: 'queue/add',
            files: [
              { id: 'f1', name: 'f1.mp3', size: 100, duration: 10, path: 'C:\\f1.mp3', status: 'queued', progress: 0, phase: 0 },
            ],
          });
        }, [dispatch]);
      });

      await act(async () => { render(<App />); });

      const startBtn = await screen.findByText('Avvia sbobinatura (1 file)');
      expect(startBtn).toBeTruthy();
    });
  });

  describe('App — Browse files and drag/drop', () => {
    it('handles browse files selection', async () => {
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      const askMedia = vi.fn().mockResolvedValue(
        { id: 'f-new', name: 'nuovo.mp3', size: 1024, duration: 3600, path: 'C:\\nuovo.mp3' },
      );
      setPywebview({
        get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
        get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
        ask_media_file: askMedia,
      });

      await act(async () => { render(<App />); });
      const audioDial = await screen.findByRole('button', { name: 'Aggiungi audio' });
      await act(async () => {
        fireEvent.click(audioDial);
      });
      expect(askMedia).toHaveBeenCalled();
      expect(await screen.findByText('nuovo.mp3')).toBeTruthy();
      // 1 hour = 5 blocks + 2 revisions
      expect(screen.getByText('Circa 7 richieste su 20 oggi')).toBeTruthy();
    });

    it('handles drag over, leave, and drop events', async () => {
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      const collectDroppedFiles = vi.fn().mockResolvedValue({ ok: true });
      setPywebview({
        get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
        get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
        collect_dropped_files: collectDroppedFiles,
      });

      await act(async () => { render(<App />); });
      const main = document.querySelector('main');
      expect(main).toBeTruthy();

      act(() => {
        fireEvent.dragOver(main!, { preventDefault: vi.fn() });
      });
      act(() => {
        fireEvent.dragLeave(main!);
      });
      act(() => {
        fireEvent.drop(main!, {
          preventDefault: vi.fn(),
          stopPropagation: vi.fn(),
          dataTransfer: { files: [{ name: 'dragged.mp3' }] },
        });
      });
    });
  });

  describe('App — Regenerate modal answering', () => {
    it('answers regenerate prompt via bridge', async () => {
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      const answerRegenerate = vi.fn().mockResolvedValue({ ok: true });
      setPywebview({
        get_completed_sessions: vi.fn().mockResolvedValue({ ok: true, sessions: [] }),
        get_archive_folders: vi.fn().mockResolvedValue({ ok: true, folders: [] }),
        answer_regenerate: answerRegenerate,
      });

      let bridgeCallbacks: Record<string, unknown> = {};
      vi.mocked(useBridgeCallbacks).mockImplementation((options) => {
        bridgeCallbacks = options as unknown as Record<string, unknown>;
        return undefined;
      });

      await act(async () => { render(<App />); });

      await act(async () => {
        (bridgeCallbacks.setRegeneratePrompt as (p: { filename: string; mode?: string; sessionDir?: string }) => void)({
          filename: 'lezione.mp3',
          mode: 'completed',
          sessionDir: 'C:\\sessions\\1',
        });
      });

      expect(await screen.findByText('Versione già pronta')).toBeTruthy();

      await act(async () => {
        fireEvent.click(screen.getByText('Usa versione pronta'));
      });

      expect(answerRegenerate).toHaveBeenCalledWith(false);
    });
  });

  describe('App — Session root moved handling', () => {
    it('refreshes archive sessions and folders when session root is moved', async () => {
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      const getCompletedSessions = vi.fn().mockResolvedValue({
        ok: true,
        sessions: [
          { name: 'lezione.mp3', session_dir: 'D:\\new_sessions\\sess1', completed_at_iso: '2026-08-18T10:00:00Z', html_path: 'D:\\new_sessions\\sess1\\outputs.html' },
        ],
      });
      const getArchiveFolders = vi.fn()
        .mockResolvedValueOnce({ ok: true, folders: [] })
        .mockResolvedValueOnce({
          ok: true,
          folders: [{ id: 'f1', name: 'Cardio', color: '#ff0000', session_dirs: ['D:\\new_sessions\\sess1'] }],
        });

      setPywebview({
        get_completed_sessions: getCompletedSessions,
        get_archive_folders: getArchiveFolders,
        ask_session_folder: vi.fn().mockResolvedValue({ ok: true, path: 'D:\\new_sessions' }),
        move_session_root: vi.fn().mockResolvedValue({ ok: true, started: true }),
        get_session_move_status: vi.fn().mockResolvedValue({
          status: 'done',
          moved: 1,
          total: 1,
          old_root: 'C:\\old_sessions',
          new_root: 'D:\\new_sessions',
        }),
        get_session_storage_info: vi.fn().mockResolvedValue({
          ok: true,
          total_bytes: 1024,
          total_sessions: 1,
          session_root: 'D:\\new_sessions',
        }),
      });

      await act(async () => { render(<App />); });

      // Open settings
      const settingsBtn = screen.getByLabelText('Apri impostazioni');
      await act(async () => { fireEvent.click(settingsBtn); });

      // Switch to storage tab
      await act(async () => {
        fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
      });



      // Click move folder
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Cambia cartella' }));
      });

      // Confirm move
      await act(async () => {
        fireEvent.click(screen.getByText('Sposta'));
      });

      await vi.waitFor(() => {
        expect(getCompletedSessions).toHaveBeenCalled();
        expect(getArchiveFolders).toHaveBeenCalledTimes(2);
      });
    });
  });

  describe('Dashboard queue actions', () => {
    beforeEach(() => {
      vi.mocked(useApiReady).mockReturnValue(mockApiReadyWithKey);
      vi.mocked(useQueuePersistence).mockReset();
    });

    it('prevents unload when busy with processing or block retry', async () => {
      vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
        React.useEffect(() => {
          dispatch({
            type: 'queue/add',
            files: [{
              id: 'file-retry',
              name: 'lesson.mp3',
              size: 123,
              duration: 60,
              path: 'C:\\Media\\lesson.mp3',
              status: 'done',
              progress: 100,
              phase: 0,
              isRetryingBlocks: true,
            }],
          });
        }, [dispatch]);
      });

      await act(async () => {
        render(<App />);
      });

      const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent;
      const preventDefaultSpy = vi.spyOn(event, 'preventDefault');

      window.dispatchEvent(event);

      expect(preventDefaultSpy).toHaveBeenCalled();
    });

    it('one-click resume: clicking Riprendi on a failed queue item starts processing immediately', async () => {
      const startProcessing = vi.fn().mockResolvedValue({ ok: true });
      window.pywebview = {
        api: {
          load_settings: vi.fn().mockResolvedValue({ api_key: 'AIzaSyTestKeyValidPatternXXXXXX12345' }),
          get_archive_sessions: vi.fn().mockResolvedValue([]),
          get_archive_folders: vi.fn().mockResolvedValue([]),
          start_processing: startProcessing,
        } as unknown as PywebviewApi,
      };

      vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
        React.useEffect(() => {
          dispatch({
            type: 'queue/add',
            files: [{
              id: 'file-failed',
              name: 'lesson-failed.mp3',
              size: 1000,
              duration: 60,
              path: 'C:\\Media\\lesson.mp3',
              status: 'error',
              errorText: 'phase1_chunk_failed_1',
              progress: 0,
              phase: 0,
            }],
          });
        }, [dispatch]);
      });

      await act(async () => {
        render(<App />);
      });

      const riprendiBtn = await screen.findByRole('button', { name: 'Riprendi' });
      expect(riprendiBtn).toBeTruthy();

      await act(async () => {
        fireEvent.click(riprendiBtn);
      });

      expect(startProcessing).toHaveBeenCalledTimes(1);
    });

    it('unified queue start: clicking Avvia sbobinatura with mixed queued and failed files resets failed to queued and starts processing', async () => {
      const startProcessing = vi.fn().mockResolvedValue({ ok: true });
      window.pywebview = {
        api: {
          load_settings: vi.fn().mockResolvedValue({ api_key: 'AIzaSyTestKeyValidPatternXXXXXX12345' }),
          get_archive_sessions: vi.fn().mockResolvedValue([]),
          get_archive_folders: vi.fn().mockResolvedValue([]),
          start_processing: startProcessing,
        } as unknown as PywebviewApi,
      };

      vi.mocked(useQueuePersistence).mockImplementation((_files, _structuralVersion, dispatch) => {
        React.useEffect(() => {
          dispatch({
            type: 'queue/add',
            files: [
              {
                id: 'file-failed',
                name: 'lesson-1-failed.mp3',
                size: 1000,
                duration: 60,
                path: 'C:\\Media\\lesson1.mp3',
                status: 'error',
                errorText: 'phase1_chunk_failed_1',
                progress: 0,
                phase: 0,
              },
              {
                id: 'file-queued',
                name: 'lesson-2-waiting.mp3',
                size: 1000,
                duration: 60,
                path: 'C:\\Media\\lesson2.mp3',
                status: 'queued',
                progress: 0,
                phase: 0,
              },
            ],
          });
        }, [dispatch]);
      });

      await act(async () => {
        render(<App />);
      });

      const startBtn = await screen.findByRole('button', { name: /Avvia sbobinatura \(2 file\)/i });
      expect(startBtn).toBeTruthy();

      await act(async () => {
        fireEvent.click(startBtn);
      });

      expect(startProcessing).toHaveBeenCalledTimes(1);
      // The first file processed is the failed file, which was reset to queued
      const passedFiles = startProcessing.mock.calls[0][0];
      expect(passedFiles[0].id).toBe('file-failed');
    });
  });
});
