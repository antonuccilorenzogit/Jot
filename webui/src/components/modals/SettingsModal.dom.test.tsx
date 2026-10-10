import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SettingsModal,
  type SettingsAuthProps,
  type SettingsModelsProps,
  type SettingsUpdaterProps,
  type SettingsStorageProps,
  type SettingsModalProps,
  type SettingsUpdateInstallState,
} from './SettingsModal';
import type { ModelOption } from '../../bridge';
import { STORAGE_KEYS } from '../../storageKeys';

const motionCache = new Map<string, React.ForwardRefExoticComponent<React.PropsWithoutRef<Record<string, unknown>> & React.RefAttributes<unknown>>>();
vi.mock('motion/react', () => ({
  motion: new Proxy({}, {
    get: (_: unknown, tag: string | symbol) => {
      if (typeof tag !== 'string') return undefined;
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

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

interface MakePropsOverrides {
  isOpen?: boolean;
  onClose?: () => void;
  appendConsole?: (msg: string) => void;
  onSettingsSaved?: () => Promise<unknown> | unknown;
  auth?: Partial<SettingsAuthProps>;
  models?: Partial<SettingsModelsProps>;
  updater?: Partial<SettingsUpdaterProps>;
  storage?: Partial<SettingsStorageProps>;
  apiKey?: string;
  setApiKey?: (key: string) => void;
  hasProtectedKey?: boolean;
  fallbackKeys?: string[];
  configuredFallbackKeyCount?: number;
  setFallbackKeys?: React.Dispatch<React.SetStateAction<string[]>>;
  preferredModel?: string;
  setPreferredModel?: (model: string) => void;
  fallbackModels?: string[];
  setFallbackModels?: React.Dispatch<React.SetStateAction<string[]>>;
  availableModels?: ModelOption[];
  latestVersion?: string | null;
  checkForUpdates?: (force?: boolean) => void;
  isCheckingUpdate?: boolean;
  hasChecked?: boolean;
  checkFailed?: boolean;
  updateInstallState?: SettingsUpdateInstallState;
  onInstallUpdate?: (version: string) => Promise<void>;
  onSessionRootMoved?: (payload?: { oldRoot?: string; newRoot?: string }) => void;
}

const makeProps = (overrides: MakePropsOverrides = {}): SettingsModalProps => ({
  isOpen: overrides.isOpen ?? true,
  onClose: overrides.onClose ?? vi.fn(),
  appendConsole: overrides.appendConsole ?? vi.fn(),
  onSettingsSaved: overrides.onSettingsSaved,
  auth: {
    apiKey: overrides.apiKey ?? overrides.auth?.apiKey ?? 'AIzaSyTest123456',
    setApiKey: overrides.setApiKey ?? overrides.auth?.setApiKey ?? vi.fn(),
    hasProtectedKey: overrides.hasProtectedKey ?? overrides.auth?.hasProtectedKey ?? false,
    fallbackKeys: overrides.fallbackKeys ?? overrides.auth?.fallbackKeys ?? [],
    setFallbackKeys: overrides.setFallbackKeys ?? overrides.auth?.setFallbackKeys ?? vi.fn(),
    configuredFallbackKeyCount: overrides.configuredFallbackKeyCount ?? overrides.auth?.configuredFallbackKeyCount ?? 0,
  },
  models: {
    preferredModel: overrides.preferredModel ?? overrides.models?.preferredModel ?? 'gemini-2.5-flash',
    setPreferredModel: overrides.setPreferredModel ?? overrides.models?.setPreferredModel ?? vi.fn(),
    fallbackModels: overrides.fallbackModels ?? overrides.models?.fallbackModels ?? [],
    setFallbackModels: overrides.setFallbackModels ?? overrides.models?.setFallbackModels ?? vi.fn(),
    availableModels: overrides.availableModels ?? overrides.models?.availableModels ?? [],
  },
  updater: {
    latestVersion: overrides.latestVersion !== undefined ? overrides.latestVersion : (overrides.updater?.latestVersion ?? null),
    checkForUpdates: overrides.checkForUpdates ?? overrides.updater?.checkForUpdates ?? vi.fn(),
    isCheckingUpdate: overrides.isCheckingUpdate ?? overrides.updater?.isCheckingUpdate ?? false,
    hasChecked: overrides.hasChecked ?? overrides.updater?.hasChecked ?? true,
    checkFailed: overrides.checkFailed ?? overrides.updater?.checkFailed ?? false,
    updateInstallState: overrides.updateInstallState ?? overrides.updater?.updateInstallState,
    onInstallUpdate: overrides.onInstallUpdate ?? overrides.updater?.onInstallUpdate,
  },
  storage: {
    onSessionRootMoved: overrides.onSessionRootMoved ?? overrides.storage?.onSessionRootMoved,
  },
});

beforeEach(() => {
  setPywebview(undefined);
  localStorage.removeItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED);
});

afterEach(() => {
  setPywebview(undefined);
});

describe('SettingsModal — model parameters chunk display', () => {
  it('keeps the saved modal open when credentials are session-only', async () => {
    const onClose = vi.fn();
    setPywebview({ save_settings: vi.fn().mockResolvedValue({ ok: true, credential_storage: { primary: 'session_only', fallback: 'absent' } }) });
    render(<SettingsModal {...makeProps({ onClose })} />);
    await act(async () => { fireEvent.click(screen.getByText('Salva e Chiudi')); });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText('Credenziali temporanee')).toBeTruthy();
    expect(screen.getByText(/al riavvio saranno disponibili/)).toBeTruthy();
  });

  it('does not display technical chunk duration or temperature parameters in UI', async () => {
    const models = [
      { id: 'gemini-3.6-flash', label: 'Gemini 3.6 Flash', summary: '', default_chunk_minutes: 15 },
      { id: 'gemini-3.7-flash', label: 'Gemini 3.7 Flash', summary: '', default_chunk_minutes: 15 },
    ];
    render(
      <SettingsModal {...makeProps({ availableModels: models, preferredModel: 'gemini-3.6-flash' })} />,
    );
    await act(async () => {
      fireEvent.click(screen.getAllByText('Generale')[0].closest('button')!);
    });
    expect(screen.queryByText('15 min')).toBeNull();
    expect(screen.queryByText(/Durata blocco/i)).toBeNull();
  });
});

describe('SettingsModal — diagnostics environment pending checks', () => {
  it.each(['success', 'failure', 'rejection'] as const)(
    'ignores a stale background %s after a newer connection check', async outcome => {
      vi.useFakeTimers();
      const usage = (count: number) => ({ ok: true, result: { telemetry: { requests_sent: count } } });
      let resolvePoll!: (value: unknown) => void;
      let rejectPoll!: (reason: Error) => void;
      const getUsage = vi.fn().mockResolvedValue(usage(7));
      setPywebview({ get_api_usage: getUsage });
      const { unmount } = render(<SettingsModal {...makeProps()} />);
      try {
        await act(async () => {});
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' })); });
        getUsage.mockImplementationOnce(() => new Promise((resolve, reject) => {
          resolvePoll = resolve;
          rejectPoll = reject;
        }));
        await act(async () => { vi.advanceTimersByTime(10_000); });
        getUsage.mockResolvedValue(usage(9));
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Generale' })); });
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Verifica connessione' })); });
        expect(getUsage.mock.lastCall?.[4]).toBe(true);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' })); });
        expect(screen.getByText('9')).toBeTruthy();
        await act(async () => {
          if (outcome === 'rejection') rejectPoll(new Error('Delayed bridge failure'));
          else resolvePoll(outcome === 'success' ? usage(7) : { ok: false });
        });
        expect(screen.getByText('9')).toBeTruthy();
        expect(screen.queryByText('7')).toBeNull();
        expect(screen.queryByText('Attività non disponibile.')).toBeNull();
      } finally {
        unmount();
        vi.useRealTimers();
      }
    },
  );

  it('keeps the current request busy when a superseded request finishes', async () => {
    vi.useFakeTimers();
    let resolveOld!: (value: unknown) => void;
    let resolveCurrent!: (value: unknown) => void;
    const usage = { ok: true, result: { telemetry: { requests_sent: 9 } } };
    const getUsage = vi.fn().mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveCurrent = resolve; }))
      .mockResolvedValue(usage);
    setPywebview({ get_api_usage: getUsage });
    const { unmount } = render(<SettingsModal {...makeProps()} />);
    try {
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' })); });
      expect(getUsage).toHaveBeenCalledTimes(2);
      await act(async () => { resolveOld(usage); });
      expect(screen.getByText('Aggiornamento attività…')).toBeTruthy();
      await act(async () => { vi.advanceTimersByTime(10_000); });
      expect(getUsage).toHaveBeenCalledTimes(2);
      await act(async () => { resolveCurrent(usage); });
      expect(screen.queryByText('Aggiornamento attività…')).toBeNull();
      expect(screen.getByText('9')).toBeTruthy();
      await act(async () => { vi.advanceTimersByTime(10_000); });
      expect(getUsage).toHaveBeenCalledTimes(3);
    } finally {
      unmount();
      vi.useRealTimers();
    }
  });

  it('refreshes activity locally every 10 seconds only while diagnostics is open', async () => {
    vi.useFakeTimers();
    const getUsage = vi.fn().mockResolvedValue({ ok: true, result: { telemetry: { requests_sent: 7 } } });
    setPywebview({ get_api_usage: getUsage });
    const props = makeProps();
    const { rerender, unmount } = render(<SettingsModal {...props} />);
    try {
      await act(async () => {});
      getUsage.mockClear();
      await act(async () => { vi.advanceTimersByTime(20_000); });
      expect(getUsage).not.toHaveBeenCalled();
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' })); });
      expect(screen.queryByRole('button', { name: 'Aggiorna attività di oggi' })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Riprova' })).toBeNull();
      getUsage.mockResolvedValue({ ok: true, result: { telemetry: { requests_sent: 8 } } });
      getUsage.mockClear();
      await act(async () => { vi.advanceTimersByTime(10_000); });
      expect(getUsage).toHaveBeenCalledTimes(1);
      expect(getUsage.mock.calls[0][4]).toBe(false);
      expect(screen.getByText('8')).toBeTruthy();
      expect(screen.queryByText('Aggiornamento attività…')).toBeNull();
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Archiviazione' })); });
      getUsage.mockClear();
      await act(async () => { vi.advanceTimersByTime(20_000); });
      expect(getUsage).not.toHaveBeenCalled();
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' })); });
      await act(async () => { rerender(<SettingsModal {...props} isOpen={false} />); });
      getUsage.mockClear();
      await act(async () => { vi.advanceTimersByTime(20_000); });
      expect(getUsage).not.toHaveBeenCalled();
    } finally {
      unmount();
      vi.useRealTimers();
    }
  });

  it('offers a local retry when activity loading fails', async () => {
    const getUsage = vi.fn().mockResolvedValue({ ok: false });
    setPywebview({ get_api_usage: getUsage });
    render(<SettingsModal {...makeProps()} />);
    await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' })); });
    expect(screen.getByText('Attività non disponibile.')).toBeTruthy();
    getUsage.mockResolvedValue({ ok: true, result: { telemetry: { requests_sent: 9 } } });
    getUsage.mockClear();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Riprova' })); });
    expect(getUsage).toHaveBeenCalledTimes(1);
    expect(getUsage.mock.calls[0][4]).toBe(false);
    expect(screen.getByText('9')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Riprova' })).toBeNull();
  });

  it('shows pending environment checks with "da verificare" status initially', async () => {
    render(
      <SettingsModal
        {...makeProps({
          apiKey: 'test-api-key',
          preferredModel: 'gemini-2.5-flash',
        })}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByText('Diagnostica').closest('button')!);
    });


    expect(screen.getByText('API Key Gemini')).toBeDefined();
    expect(screen.getByText('FFmpeg')).toBeDefined();
    expect(screen.getByText('Config locale')).toBeDefined();
    expect(screen.getByText('Cartella sessioni/output')).toBeDefined();

    const statusBadges = screen.getAllByText('da verificare');
    expect(statusBadges.length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByText('In attesa di verifica')).toBeNull();
  });
});

describe('SettingsModal — save behavior', () => {
  it('restores unsaved keys and models when Annulla closes and reopens the modal', () => {
    const primaryKey = 'AIzaABCDEFGHIJKLMNOPQRST';
    const originalFallback = 'AIzaBBBBBBBBBBBBBBBBBBBB';
    const addedFallback = 'AIzaCCCCCCCCCCCCCCCCCCCC';
    const availableModels = [
      { id: 'gemini-primary', label: 'Gemini Primary', summary: '', default_chunk_minutes: 15 },
      { id: 'gemini-alternate', label: 'Gemini Alternate', summary: '', default_chunk_minutes: 15 },
    ];

    function StatefulSettingsHarness() {
      const [isOpen, setIsOpen] = React.useState(true);
      const [apiKey, setApiKey] = React.useState(primaryKey);
      const [fallbackKeys, setFallbackKeys] = React.useState([originalFallback]);
      const [preferredModel, setPreferredModel] = React.useState('gemini-primary');
      const [fallbackModels, setFallbackModels] = React.useState(['gemini-alternate']);

      return (
        <>
          <button type="button" onClick={() => setIsOpen(true)}>Riapri</button>
          <SettingsModal
            {...makeProps({
              isOpen,
              onClose: () => setIsOpen(false),
              apiKey,
              setApiKey,
              fallbackKeys,
              setFallbackKeys,
              preferredModel,
              setPreferredModel,
              fallbackModels,
              setFallbackModels,
              availableModels,
            })}
          />
        </>
      );
    }

    render(<StatefulSettingsHarness />);

    const input = screen.getByLabelText('Nuova chiave di riserva');
    fireEvent.change(input, { target: { value: addedFallback } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    expect(screen.getByText('3 chiavi')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Gemini Primary/i }));
    fireEvent.click(screen.getByRole('option', { name: /Gemini Alternate/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Annulla' }));
    fireEvent.click(screen.getByRole('button', { name: 'Riapri' }));

    expect(screen.getByText('2 chiavi')).toBeTruthy();
    expect(screen.queryByText('...CCCC')).toBeNull();
    expect(screen.getByRole('button', { name: /Gemini Primary/i })).toBeTruthy();
  });

  it('lets the mobile content column shrink so the footer remains inside the modal', () => {
    render(<SettingsModal {...makeProps()} />);

    const footer = screen.getByText('Salva e Chiudi').closest('.modal-footer');
    const contentColumn = footer?.parentElement;

    expect(contentColumn?.className).toContain('min-h-0');
    expect(contentColumn?.className).not.toMatch(/(?:^|\s)h-full(?:\s|$)/);
  });

  it('starts each settings tab at the top after scrolling the previous tab', () => {
    render(<SettingsModal {...makeProps()} />);
    const content = screen.getByRole('heading', { name: 'Generale' }).closest('.app-scroll')!;
    content.scrollTop = 250;
    fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' }));
    expect(content.scrollTop).toBe(0);
    expect(screen.getByRole('button', { name: 'Diagnostica' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('button', { name: 'Generale' }).getAttribute('aria-current')).toBeNull();
  });

  it('missing bridge: modal stays open, inline error displayed, console notified', async () => {
    const onClose = vi.fn();
    const appendConsole = vi.fn();

    render(<SettingsModal {...makeProps()} onClose={onClose} appendConsole={appendConsole} />);

    await act(async () => {
      fireEvent.click(screen.getByText('Salva e Chiudi'));
    });

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByText(/Bridge Python non disponibile/i)).not.toBeNull();
    expect(appendConsole).toHaveBeenCalledTimes(1);
    expect(appendConsole).toHaveBeenCalledWith(
      expect.stringMatching(/❌.*non disponibile|non disponibile.*❌/s),
    );
  });

  it('save_settings returns {ok:false}: modal stays open and shows backend error', async () => {
    const mockSave = vi.fn().mockResolvedValue({ ok: false, error: 'quota esaurita' });
    setPywebview({ save_settings: mockSave });
    const onClose = vi.fn();

    render(<SettingsModal {...makeProps()} onClose={onClose} />);

    await act(async () => {
      fireEvent.click(screen.getByText('Salva e Chiudi'));
    });

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByText(/quota esaurita/i)).not.toBeNull();
  });

  it('successful save: onClose called and no inline error shown', async () => {
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ save_settings: mockSave });
    const onClose = vi.fn();

    render(<SettingsModal {...makeProps()} onClose={onClose} />);

    await act(async () => {
      fireEvent.click(screen.getByText('Salva e Chiudi'));
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Bridge Python non disponibile/i)).toBeNull();
  });

  it('successful save: refreshes settings before closing', async () => {
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ save_settings: mockSave });
    const onClose = vi.fn();
    const onSettingsSaved = vi.fn().mockResolvedValue(undefined);

    render(<SettingsModal {...makeProps()} onClose={onClose} onSettingsSaved={onSettingsSaved} />);

    await act(async () => {
      fireEvent.click(screen.getByText('Salva e Chiudi'));
    });

    expect(onSettingsSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSettingsSaved.mock.invocationCallOrder[0]).toBeLessThan(onClose.mock.invocationCallOrder[0]);
  });

  it('sends an explicit empty key when removing an inaccessible protected primary', async () => {
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ save_settings: mockSave });

    render(
      <SettingsModal
        {...makeProps({ apiKey: '', hasProtectedKey: true, fallbackKeys: [] })}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Opzioni chiave principale' }));
    fireEvent.click(screen.getByRole('button', { name: 'Rimuovi chiave' }));
    fireEvent.click(screen.getByRole('button', { name: 'Rimuovi' }));

    await act(async () => {
      fireEvent.click(screen.getByText('Salva e Chiudi'));
    });

    expect(mockSave).toHaveBeenCalledWith('', [], 'gemini-2.5-flash', []);
  });

  it('preserves configured fallback keys when masked values were not edited', async () => {
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ save_settings: mockSave });

    render(
      <SettingsModal
        {...makeProps({ fallbackKeys: [], configuredFallbackKeyCount: 2 })}
      />
    );

    await act(async () => {
      fireEvent.click(screen.getByText('Salva e Chiudi'));
    });

    expect(mockSave).toHaveBeenCalledWith(
      'AIzaSyTest123456',
      null,
      'gemini-2.5-flash',
      [],
    );
  });

  it('backdrop click when idle: onClose NOT called', () => {
    const onClose = vi.fn();
    const { container } = render(<SettingsModal {...makeProps()} onClose={onClose} />);
    const backdrop = container.querySelector('.modal-overlay') as HTMLElement;
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape key when idle', () => {
    const onClose = vi.fn();
    render(<SettingsModal {...makeProps()} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('double-click: save_settings called only once, onClose called only once', async () => {
    let resolveFirst!: (val: { ok: boolean }) => void;
    const firstPromise = new Promise<{ ok: boolean }>(res => { resolveFirst = res; });
    const mockSave = vi.fn().mockReturnValueOnce(firstPromise);
    setPywebview({ save_settings: mockSave });
    const onClose = vi.fn();

    render(<SettingsModal {...makeProps()} onClose={onClose} />);

    const button = screen.getByText('Salva e Chiudi');
    fireEvent.click(button);
    fireEvent.click(button);

    await act(async () => { resolveFirst({ ok: true }); });

    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('backdrop click while saving: onClose NOT called', async () => {
    let resolveFirst!: (val: { ok: boolean }) => void;
    const firstPromise = new Promise<{ ok: boolean }>(res => { resolveFirst = res; });
    const mockSave = vi.fn().mockReturnValueOnce(firstPromise);
    setPywebview({ save_settings: mockSave });
    const onClose = vi.fn();

    const { container } = render(<SettingsModal {...makeProps()} onClose={onClose} />);

    fireEvent.click(screen.getByText('Salva e Chiudi'));

    const backdrop = container.querySelector('.absolute.inset-0') as HTMLElement;
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => { resolveFirst({ ok: true }); });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Annulla button click while saving: onClose NOT called', async () => {
    let resolveFirst!: (val: { ok: boolean }) => void;
    const firstPromise = new Promise<{ ok: boolean }>(res => { resolveFirst = res; });
    const mockSave = vi.fn().mockReturnValueOnce(firstPromise);
    setPywebview({ save_settings: mockSave });
    const onClose = vi.fn();

    render(<SettingsModal {...makeProps()} onClose={onClose} />);

    fireEvent.click(screen.getByText('Salva e Chiudi'));

    const cancelButton = screen.getByRole('button', { name: 'Annulla' });
    fireEvent.click(cancelButton);
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => { resolveFirst({ ok: true }); });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('SettingsModal — session info race condition', () => {
  it('stale fetch discarded on open→close→reopen: loading not cleared prematurely', async () => {
    let resolveFirst!: (val: unknown) => void;
    let resolveSecond!: (val: unknown) => void;
    const firstPromise = new Promise(res => { resolveFirst = res; });
    const secondPromise = new Promise(res => { resolveSecond = res; });
    const mockGetInfo = vi.fn()
      .mockReturnValueOnce(firstPromise)
      .mockReturnValueOnce(secondPromise);
    setPywebview({ get_session_storage_info: mockGetInfo });

    const { rerender } = render(<SettingsModal {...makeProps()} isOpen={true} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });

    rerender(<SettingsModal {...makeProps()} isOpen={false} />);
    rerender(<SettingsModal {...makeProps()} isOpen={true} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });



    await act(async () => { resolveFirst({ ok: true, total_bytes: 999999, total_sessions: 7777 }); });

    expect(screen.queryByText('Calcolo…')).not.toBeNull();   // loading NOT prematurely cleared
    expect(screen.queryByText(/7777/)).toBeNull();            // stale data NOT applied

    await act(async () => { resolveSecond({ ok: true, total_bytes: 1024, total_sessions: 3 }); });

    expect(screen.queryByText('Calcolo…')).toBeNull();
    expect(screen.queryByText(/3 sbobine/)).not.toBeNull();
  });
});

describe('SettingsModal — main-section interactions', () => {
  it('offers copying the saved primary key without revealing it', () => {
    render(<SettingsModal {...makeProps()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Opzioni chiave principale' }));
    expect(screen.getByRole('button', { name: 'Copia chiave' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Mostra in chiaro' })).toBeNull();
  });

  it('calls setApiKey when API key is added to empty settings', async () => {
    const setApiKey = vi.fn();
    render(<SettingsModal {...makeProps({ apiKey: '', setApiKey })} />);
    const input = screen.getByPlaceholderText(/Inserisci chiave principale/);
    fireEvent.change(input, { target: { value: 'AIzaSy1234567890123456789' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    expect(setApiKey).toHaveBeenCalledWith('AIzaSy1234567890123456789');
  });

  it('calls setFallbackKeys when a fallback key is added', async () => {
    const setFallbackKeys = vi.fn();
    render(<SettingsModal {...makeProps({ setFallbackKeys })} />);
    const input = screen.getByLabelText('Nuova chiave di riserva');
    fireEvent.change(input, { target: { value: 'AIzaSyFallbackKey123456789' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    expect(setFallbackKeys).toHaveBeenCalledWith(['AIzaSyFallbackKey123456789']);
  });

  it('keeps notification changes in draft across tabs until a successful save', async () => {
    const saveSettings = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ save_settings: saveSettings });
    render(<SettingsModal {...makeProps()} />);
    const toggle = screen.getByRole('switch');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' }));
    fireEvent.click(screen.getByRole('button', { name: 'Generale' }));
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('false');
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Salva e Chiudi' }));
    });
    expect(saveSettings).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED)).toBe('false');
  });

  it.each(['Annulla', 'Chiudi finestra', 'Escape'])('discards notification drafts with %s and reloads saved state on reopening', (closeAction) => {
    localStorage.setItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED, 'false');
    const onClose = vi.fn();
    const props = makeProps({ onClose });
    const { rerender } = render(<SettingsModal {...props} />);
    fireEvent.click(screen.getByRole('switch'));
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('true');
    if (closeAction === 'Escape') {
      fireEvent.keyDown(window, { key: 'Escape' });
    } else {
      fireEvent.click(screen.getByRole('button', { name: closeAction }));
    }
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED)).toBe('false');
    rerender(<SettingsModal {...props} isOpen={false} />);
    rerender(<SettingsModal {...props} isOpen />);
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('false');
  });

  it('preserves saved notification preferences when saving settings fails', async () => {
    localStorage.setItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED, 'true');
    setPywebview({ save_settings: vi.fn().mockResolvedValue({ ok: false, error: 'Errore di salvataggio' }) });
    const onClose = vi.fn();
    render(<SettingsModal {...makeProps({ onClose })} />);
    fireEvent.click(screen.getByRole('switch'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Salva e Chiudi' }));
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED)).toBe('true');
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('false');
  });

  it('only allows revealing the new key input', () => {
    render(<SettingsModal {...makeProps()} />);
    expect(screen.queryByRole('button', { name: 'Mostra chiavi' })).toBeNull();
    const input = screen.getByLabelText('Nuova chiave di riserva');
    expect(input.getAttribute('type')).toBe('password');
    fireEvent.click(screen.getByRole('button', { name: 'Mostra nuova chiave' }));
    expect(input.getAttribute('type')).toBe('text');
  });

  it('calls open_url when aistudio link is clicked', async () => {
    const openUrl = vi.fn();
    setPywebview({ open_url: openUrl });
    render(<SettingsModal {...makeProps()} />);
    fireEvent.click(screen.getByText(/Ottieni gratis su aistudio/));
    expect(openUrl).toHaveBeenCalledWith('https://aistudio.google.com/apikey');
  });

  it('opens confirmation modal and removes API key when confirmed', async () => {
    const setApiKey = vi.fn();
    const setFallbackKeys = vi.fn();
    render(
      <SettingsModal
        {...makeProps({
          apiKey: 'AIzaSyPrimary1234567890',
          fallbackKeys: ['AIzaSyReserve1111111111'],
          setApiKey,
          setFallbackKeys,
        })}
      />
    );

    const kebab = screen.getByRole('button', { name: 'Opzioni chiave principale' });
    fireEvent.click(kebab);

    const removeBtn = screen.getByRole('button', { name: 'Rimuovi chiave' });
    fireEvent.click(removeBtn);

    expect(screen.getByText('Rimuovi chiave API')).toBeTruthy();
    expect(screen.getByText(/La Chiave Riserva 1 verrà promossa automaticamente a nuova chiave principale/i)).toBeTruthy();

    const confirmBtn = screen.getByRole('button', { name: 'Rimuovi' });
    fireEvent.click(confirmBtn);

    expect(setApiKey).toHaveBeenCalledWith('AIzaSyReserve1111111111');
    expect(setFallbackKeys).toHaveBeenCalledWith([]);
  });
});

describe('SettingsModal — session folder and cleanup', () => {
  it('calls open_session_folder when folder button is clicked', async () => {
    const openFolder = vi.fn();
    setPywebview({ open_session_folder: openFolder });
    render(<SettingsModal {...makeProps()} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });
    fireEvent.click(screen.getByTitle('Apri cartella sessioni'));
    expect(openFolder).toHaveBeenCalledTimes(1);
  });

  it('calls cleanup_old_sessions for incomplete cleanup and shows result', async () => {
    const cleanupFn = vi.fn()
      .mockResolvedValueOnce({ ok: true, removed: 0, candidates: 3, freed_bytes: 1024, preserved_completed: 2 })
      .mockResolvedValueOnce({ ok: true, removed: 3, candidates: 3, freed_bytes: 1024, preserved_completed: 2 });
    setPywebview({ cleanup_old_sessions: cleanupFn });
    render(<SettingsModal {...makeProps()} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle(/Conta ed elimina tutte le elaborazioni incomplete/));
    });
    expect(await screen.findByText(/Sbobine interessate: 3/)).toBeTruthy();
    expect(cleanupFn).toHaveBeenCalledTimes(1);
    expect(cleanupFn).toHaveBeenCalledWith(0, true);

    await act(async () => {
      fireEvent.click(screen.getByText('Elimina incomplete'));
    });
    await vi.waitFor(() =>
      expect(screen.getByText(/Rimoss/)).toBeTruthy(),
    );
    expect(screen.getByText(/sbobine completate preservate/)).toBeTruthy();
    expect(cleanupFn).toHaveBeenCalledTimes(2);
    expect(cleanupFn).toHaveBeenLastCalledWith(0, false);
  });

  it('counts completed notes before dangerous cleanup and deletes only after confirmation', async () => {
    const cleanupCompletedFn = vi.fn()
      .mockResolvedValueOnce({ ok: true, removed: 0, candidates: 4, freed_bytes: 2048 })
      .mockResolvedValueOnce({ ok: true, removed: 4, candidates: 4, freed_bytes: 2048 });
    setPywebview({ cleanup_completed_sessions: cleanupCompletedFn });
    render(<SettingsModal {...makeProps()} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle(/Conta ed elimina sbobine completate/));
    });
    expect(await screen.findByText(/Sbobine interessate: 4/)).toBeTruthy();
    expect(cleanupCompletedFn).toHaveBeenCalledTimes(1);
    expect(cleanupCompletedFn).toHaveBeenCalledWith(30, true);

    await act(async () => {
      fireEvent.click(screen.getByText('Elimina sbobine completate'));
    });
    await vi.waitFor(() =>
      expect(screen.getByText(/Eliminate 4 sbobine completate/)).toBeTruthy(),
    );
    expect(cleanupCompletedFn).toHaveBeenCalledTimes(2);
    expect(cleanupCompletedFn).toHaveBeenLastCalledWith(30, false);
  });

  it('dismisses cleanup notification when close button is clicked', async () => {
    const cleanupFn = vi.fn()
      .mockResolvedValueOnce({ ok: true, removed: 0, candidates: 2, freed_bytes: 512 })
      .mockResolvedValueOnce({ ok: true, removed: 2, candidates: 2, freed_bytes: 512 });
    setPywebview({ cleanup_old_sessions: cleanupFn });
    render(<SettingsModal {...makeProps()} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle(/Conta ed elimina tutte le elaborazioni incomplete/));
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Elimina incomplete'));
    });
    await vi.waitFor(() =>
      expect(screen.getByText(/Rimosse 2 elaborazioni incomplete/)).toBeTruthy(),
    );

    const closeBtn = screen.getByRole('button', { name: 'Chiudi notifica' });
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    expect(screen.queryByText(/Rimosse 2 elaborazioni incomplete/)).toBeNull();
  });

  it('auto-dismisses cleanup notification after 5 seconds', async () => {
    vi.useFakeTimers();
    try {
      const cleanupFn = vi.fn()
        .mockResolvedValueOnce({ ok: true, removed: 0, candidates: 1, freed_bytes: 256 })
        .mockResolvedValueOnce({ ok: true, removed: 1, candidates: 1, freed_bytes: 256 });
      setPywebview({ cleanup_old_sessions: cleanupFn });
      render(<SettingsModal {...makeProps()} />);
      await act(async () => {
        fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
      });
      await act(async () => {
        fireEvent.click(screen.getByTitle(/Conta ed elimina tutte le elaborazioni incomplete/));
      });
      await act(async () => {
        fireEvent.click(screen.getByText('Elimina incomplete'));
      });
      expect(screen.getByText(/Rimossa 1 elaborazione incompleta/)).toBeTruthy();

      await act(async () => {
        vi.advanceTimersByTime(5100);
      });

      expect(screen.queryByText(/Rimossa 1 elaborazione incompleta/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('resets cleanup result when modal is closed and reopened', async () => {
    const cleanupFn = vi.fn()
      .mockResolvedValueOnce({ ok: true, removed: 0, candidates: 1, freed_bytes: 256 })
      .mockResolvedValueOnce({ ok: true, removed: 1, candidates: 1, freed_bytes: 256 });
    setPywebview({ cleanup_old_sessions: cleanupFn });
    const props = { ...makeProps(), isOpen: true };
    const { rerender } = render(<SettingsModal {...props} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle(/Conta ed elimina tutte le elaborazioni incomplete/));
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Elimina incomplete'));
    });
    await vi.waitFor(() =>
      expect(screen.getByText(/Rimossa 1 elaborazione incompleta/)).toBeTruthy(),
    );

    // Close the modal
    rerender(<SettingsModal {...props} isOpen={false} />);

    // Reopen the modal
    rerender(<SettingsModal {...props} isOpen={true} />);

    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });

    // Cleanup result should be reset to null
    expect(screen.queryByText(/Rimossa 1 elaborazione incompleta/)).toBeNull();
  });

  it('triggers onSessionRootMoved when move completes successfully', async () => {
    const onSessionRootMoved = vi.fn();
    const askFolder = vi.fn().mockResolvedValue({ ok: true, path: 'D:\\new_sessions' });
    const moveRoot = vi.fn().mockResolvedValue({ ok: true, started: true });
    const moveStatus = vi.fn().mockResolvedValue({
      status: 'done',
      moved: 5,
      total: 5,
      old_root: 'C:\\old_sessions',
      new_root: 'D:\\new_sessions',
    });
    const getStorageInfo = vi.fn().mockResolvedValue({
      ok: true,
      total_bytes: 1024,
      total_sessions: 5,
      session_root: 'D:\\new_sessions',
    });

    setPywebview({
      ask_session_folder: askFolder,
      move_session_root: moveRoot,
      get_session_move_status: moveStatus,
      get_session_storage_info: getStorageInfo,
    });

    render(<SettingsModal {...makeProps({ onSessionRootMoved })} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Archiviazione').closest('button')!);
    });


    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Cambia cartella' }));
    });
    expect(askFolder).toHaveBeenCalledTimes(1);

    // Confirmation dialog appears
    expect(await screen.findByText('Spostare la cartella sessioni?')).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByText('Sposta'));
    });

    expect(moveRoot).toHaveBeenCalledWith('D:\\new_sessions');

    await vi.waitFor(() => {
      expect(onSessionRootMoved).toHaveBeenCalledWith({
        oldRoot: 'C:\\old_sessions',
        newRoot: 'D:\\new_sessions',
      });
    });
  });
});

describe('SettingsModal — model section', () => {
  it('renders primary model select and default badge without summary description', async () => {
    const models = [
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', summary: '', default_chunk_minutes: 12 },
      { id: 'gemini-3.6-flash', label: 'Gemini 3.6 Flash', summary: '', default_chunk_minutes: 15 },
    ];
    render(
      <SettingsModal
        {...makeProps({
          availableModels: models,
          preferredModel: 'gemini-2.5-flash',
        })}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getAllByText('Generale')[0].closest('button')!);
    });
    expect(screen.getByText('Modello di trascrizione')).toBeTruthy();
    expect(screen.getAllByText('Default').length).toBeGreaterThan(0);
    expect(screen.queryByText('Fast and capable')).toBeNull();
  });

  it('calls setPreferredModel when another model is selected', async () => {
    const models = [
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', summary: 'Fast', default_chunk_minutes: 12 },
      { id: 'gemini-3.6-flash', label: 'Gemini 3.6 Flash', summary: 'Successore consigliato', default_chunk_minutes: 15 },
    ];
    const setPreferredModel = vi.fn();
    render(
      <SettingsModal
        {...makeProps({
          availableModels: models,
          preferredModel: 'gemini-2.5-flash',
          setPreferredModel,
        })}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getAllByText('Generale')[0].closest('button')!);
    });
    const trigger = screen.getByRole('button', { name: /Gemini 2.5 Flash/i });
    fireEvent.click(trigger);
    const option = screen.getByRole('option', { name: /Gemini 3.6 Flash/i });
    fireEvent.click(option);
    expect(setPreferredModel).toHaveBeenCalledWith('gemini-3.6-flash');
  });
});

describe('SettingsModal — version status display', () => {
  it('checkFailed=true: shows network-error message, hides "✓ Sei aggiornato"', () => {
    render(<SettingsModal {...makeProps({ checkFailed: true, latestVersion: null, hasChecked: true, isCheckingUpdate: false })} />);
    expect(screen.queryByText(/Sei aggiornato/)).toBeNull();
    expect(screen.getByText(/non riuscita/i)).toBeTruthy();
  });

  it('checkFailed=false, hasChecked=true: shows "✓ Sei aggiornato"', () => {
    render(<SettingsModal {...makeProps({ checkFailed: false, latestVersion: null, hasChecked: true, isCheckingUpdate: false })} />);
    expect(screen.getByText(/Sei aggiornato/)).toBeTruthy();
    expect(screen.queryByText(/non riuscita/i)).toBeNull();
  });

  it('isCheckingUpdate=true: shows neither status row', () => {
    render(<SettingsModal {...makeProps({ checkFailed: false, latestVersion: null, hasChecked: true, isCheckingUpdate: true })} />);
    expect(screen.queryByText(/Sei aggiornato/)).toBeNull();
    expect(screen.queryByText(/non riuscita/i)).toBeNull();
  });

  it('shows shared async install error state', () => {
    render(
      <SettingsModal
        {...makeProps({
          latestVersion: 'v2.0.0',
          updateInstallState: {
            version: 'v2.0.0',
            status: 'error',
            bytesDone: 0,
            bytesTotal: 0,
            error: 'Verifica integrità fallita: il file scaricato non corrisponde al checksum atteso.',
          },
        })}
      />,
    );

    expect(screen.getByText(/Verifica integrità fallita/i)).toBeTruthy();
  });

  it('shows shared async install success state', () => {
    render(
      <SettingsModal
        {...makeProps({
          latestVersion: 'v2.0.0',
          updateInstallState: {
            version: 'v2.0.0',
            status: 'done',
            bytesDone: 10,
            bytesTotal: 10,
            error: null,
          },
        })}
      />,
    );

    expect(screen.getByText(/Installer avviato/i)).toBeTruthy();
  });
});

describe('SettingsModal — validate environment', () => {
  it('shows validation summary after clicking Verifica ambiente', async () => {
    const models = [
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', summary: 'Fast', default_chunk_minutes: 12 },
    ];
    const validateFn = vi.fn().mockResolvedValue({
      ok: true,
      result: {
        ok: true,
        summary: 'Ambiente OK',
        checks: [
          { id: 'ffmpeg', label: 'ffmpeg', status: 'ok', message: 'ffmpeg trovato' },
        ],
      },
    });
    setPywebview({ validate_environment: validateFn });
    render(
      <SettingsModal
        {...makeProps({
          availableModels: models,
          preferredModel: 'gemini-2.5-flash',
        })}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByText('Diagnostica').closest('button')!);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle('Verifica ambiente'));
    });
    await vi.waitFor(() => expect(screen.getByText('Ambiente OK')).toBeTruthy());
    expect(screen.getByText('FFmpeg')).toBeTruthy();
  });

  it('resets validation result when preferredModel changes', async () => {
    const models = [
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', summary: 'Fast', default_chunk_minutes: 12 },
      { id: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash', summary: 'New', default_chunk_minutes: 15 },
    ];
    const validateFn = vi.fn().mockResolvedValue({
      ok: true,
      result: {
        ok: true,
        summary: 'Ambiente OK',
        checks: [
          { id: 'ffmpeg', label: 'ffmpeg', status: 'ok', message: 'ffmpeg trovato' },
        ],
      },
    });
    setPywebview({ validate_environment: validateFn });
    const props = makeProps({
      availableModels: models,
      preferredModel: 'gemini-2.5-flash',
      isOpen: true,
    });
    const { rerender } = render(<SettingsModal {...props} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Diagnostica').closest('button')!);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle('Verifica ambiente'));
    });
    await vi.waitFor(() => expect(screen.getByText('Ambiente OK')).toBeTruthy());

    // Change preferredModel
    rerender(<SettingsModal {...props} models={{ ...props.models, preferredModel: 'gemini-3.5-flash' }} />);

    // Expect 'Ambiente OK' to be cleared (since validationResult is set to null)
    expect(screen.queryByText('Ambiente OK')).toBeNull();
  });

  it('resets validation result when modal is closed and reopened', async () => {
    const models = [
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', summary: 'Fast', default_chunk_minutes: 12 },
    ];
    const validateFn = vi.fn().mockResolvedValue({
      ok: true,
      result: {
        ok: true,
        summary: 'Ambiente OK',
        checks: [
          { id: 'ffmpeg', label: 'ffmpeg', status: 'ok', message: 'ffmpeg trovato' },
        ],
      },
    });
    setPywebview({ validate_environment: validateFn });
    const props = makeProps({
      availableModels: models,
      preferredModel: 'gemini-2.5-flash',
      isOpen: true,
    });
    const { rerender } = render(<SettingsModal {...props} />);
    await act(async () => {
      fireEvent.click(screen.getByText('Diagnostica').closest('button')!);
    });
    await act(async () => {
      fireEvent.click(screen.getByTitle('Verifica ambiente'));
    });
    await vi.waitFor(() => expect(screen.getByText('Ambiente OK')).toBeTruthy());

    // Close the modal
    rerender(<SettingsModal {...props} isOpen={false} />);

    // Reopen the modal
    rerender(<SettingsModal {...props} isOpen={true} />);

    await act(async () => {
      fireEvent.click(screen.getByText('Diagnostica').closest('button')!);
    });

    // Expect 'Ambiente OK' to be cleared and state reset
    expect(screen.queryByText('Ambiente OK')).toBeNull();
    const statusBadges = screen.getAllByText('da verificare');
    expect(statusBadges.length).toBeGreaterThanOrEqual(4);
  });

  it('puts activity first in diagnostics and keeps refresh with the keys in General', async () => {
    render(
      <SettingsModal
        {...makeProps({
          apiKey: 'test-api-key',
        })}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' }));
    });

    expect(screen.getByRole('heading', { name: 'Diagnostica' })).toBeTruthy();
    const activity = screen.getByText('Attività di oggi');
    const checks = screen.getByText('Verifica ambiente');
    expect(activity.compareDocumentPosition(checks) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(activity.closest('details')).toBeNull();
    expect(screen.queryByText('Quote per modello')).toBeNull();
    expect(screen.getByRole('button', { name: 'Chiudi' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Salva e Chiudi' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Annulla' })).toBeNull();
  });

  it('keeps save and cancel in diagnostics when general settings have pending changes', async () => {
    const props = makeProps();
    const { rerender } = render(<SettingsModal {...props} />);
    rerender(<SettingsModal {...props} models={{ ...props.models, preferredModel: 'gemini-3.5-flash' }} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Diagnostica' }));
    });
    expect(screen.getByRole('button', { name: 'Salva e Chiudi' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Annulla' })).toBeTruthy();
  });

  it('renders sidebar tabs in the correct order: Generale, Archiviazione, Diagnostica', () => {
    const { container } = render(
      <SettingsModal
        {...makeProps({
          apiKey: 'test-api-key',
        })}
      />,
    );

    const sidebar = container.querySelector('nav[aria-label="Sezioni delle impostazioni"]');
    expect(sidebar).toBeTruthy();
    const buttons = sidebar ? Array.from(sidebar.querySelectorAll('button')) : [];
    const buttonTexts = buttons.map(b => b.textContent?.trim() || '');
    expect(buttonTexts).toHaveLength(3);
    expect(buttonTexts[0]).toContain('Generale');
    expect(buttonTexts[1]).toContain('Archiviazione');
    expect(buttonTexts[2]).toContain('Diagnostica');
  });
});
