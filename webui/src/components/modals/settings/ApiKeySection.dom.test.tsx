import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiKeySection } from './ApiKeySection';
import type { ApiUsageResult } from '../../../bridge';

describe('ApiKeySection component', () => {
  const defaultProps = {
    apiKey: 'AIzaSyPrimary0123456789012345',
    setApiKey: vi.fn(),
    hasProtectedKey: false,
    apiKeyInsecure: false,
    apiKeyInsecureReason: '',
    fallbackKeys: [],
    setFallbackKeys: vi.fn(),
  };

  it('warns for temporary fallback credentials without claiming plaintext storage', () => {
    render(<ApiKeySection {...defaultProps} credentialStorage={{ primary: 'protected', fallback: 'session_only' }} />);
    expect(screen.getByText('Credenziali temporanee')).toBeTruthy();
    expect(screen.getByText(/solo per questa sessione/)).toBeTruthy();
    expect(screen.queryByText('Memorizzazione in chiaro')).toBeNull();
  });

  it('renders primary API key in the card table and shows count', () => {
    render(<ApiKeySection {...defaultProps} />);

    expect(screen.getByText('Chiave Principale')).toBeTruthy();
    expect(screen.getByText('...2345')).toBeTruthy();
    expect(screen.getByText('1 chiave')).toBeTruthy();
  });

  it('renders existing fallback keys as masked rows (...XXXX)', () => {
    const fallbackKeys = [
      'AIzaSyBackupKey11111111111111ABCD',
      'AIzaSyBackupKey22222222222222WXYZ',
    ];

    render(<ApiKeySection {...defaultProps} fallbackKeys={fallbackKeys} />);

    expect(screen.getByText('...ABCD')).toBeTruthy();
    expect(screen.getByText('...WXYZ')).toBeTruthy();
    expect(screen.getByText('Chiave Riserva 1')).toBeTruthy();
    expect(screen.getByText('Chiave Riserva 2')).toBeTruthy();
    expect(screen.getByText('3 chiavi')).toBeTruthy();
  });

  it('adds a valid fallback key when clicking Aggiungi button', () => {
    const setFallbackKeys = vi.fn();
    render(<ApiKeySection {...defaultProps} setFallbackKeys={setFallbackKeys} />);

    const input = screen.getByLabelText('Nuova chiave di riserva');
    const addButton = screen.getByRole('button', { name: 'Aggiungi chiave di riserva' }) as HTMLButtonElement;

    expect(addButton.disabled).toBe(true);

    fireEvent.change(input, { target: { value: 'AIzaSyValidKey9999999999999999' } });
    expect(addButton.disabled).toBe(false);

    fireEvent.click(addButton);

    expect(setFallbackKeys).toHaveBeenCalledWith(['AIzaSyValidKey9999999999999999']);
  });

  it('sets primary key when adding the first key to an empty configuration', () => {
    const setApiKey = vi.fn();
    render(
      <ApiKeySection
        {...defaultProps}
        apiKey=""
        setApiKey={setApiKey}
      />
    );

    const input = screen.getByLabelText('Nuova chiave di riserva');
    fireEvent.change(input, { target: { value: 'AIzaSyValidPrimary999999999' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(setApiKey).toHaveBeenCalledWith('AIzaSyValidPrimary999999999');
  });

  it('masks a new API key by default and reveals it only on request', () => {
    render(<ApiKeySection {...defaultProps} />);

    const input = screen.getByLabelText('Nuova chiave di riserva') as HTMLInputElement;
    expect(input.type).toBe('password');

    fireEvent.click(screen.getByRole('button', { name: 'Mostra nuova chiave' }));
    expect(input.type).toBe('text');
    expect(screen.getByRole('button', { name: 'Nascondi nuova chiave' })).toBeTruthy();
  });

  it('adds a valid fallback key when pressing Enter', () => {
    const setFallbackKeys = vi.fn();
    render(<ApiKeySection {...defaultProps} setFallbackKeys={setFallbackKeys} />);

    const input = screen.getByLabelText('Nuova chiave di riserva');

    fireEvent.change(input, { target: { value: 'AIzaSyValidKey9999999999999999' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(setFallbackKeys).toHaveBeenCalledWith(['AIzaSyValidKey9999999999999999']);
  });

  it('shows error if the key format is invalid', () => {
    const setFallbackKeys = vi.fn();
    render(<ApiKeySection {...defaultProps} setFallbackKeys={setFallbackKeys} />);

    const input = screen.getByLabelText('Nuova chiave di riserva');
    fireEvent.change(input, { target: { value: 'invalid_key_format' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(setFallbackKeys).not.toHaveBeenCalled();
    expect(screen.getByText(/Formato API key non valido/i)).toBeTruthy();
  });

  it('shows error if the key matches the primary key', () => {
    const setFallbackKeys = vi.fn();
    render(<ApiKeySection {...defaultProps} setFallbackKeys={setFallbackKeys} />);

    const input = screen.getByLabelText('Nuova chiave di riserva');
    fireEvent.change(input, { target: { value: defaultProps.apiKey } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(setFallbackKeys).not.toHaveBeenCalled();
    expect(screen.getByText(/già impostata come chiave principale/i)).toBeTruthy();
  });

  it('shows error if the key is already in the fallback list', () => {
    const setFallbackKeys = vi.fn();
    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={['AIzaSyBackupKey11111111111111ABCD']}
        setFallbackKeys={setFallbackKeys}
      />
    );

    const input = screen.getByLabelText('Nuova chiave di riserva');
    fireEvent.change(input, { target: { value: 'AIzaSyBackupKey11111111111111ABCD' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(setFallbackKeys).not.toHaveBeenCalled();
    expect(screen.getByText(/già presente tra le riserve/i)).toBeTruthy();
  });

  it('supports multiple comma-separated keys typed into input', () => {
    const setFallbackKeys = vi.fn();
    render(<ApiKeySection {...defaultProps} setFallbackKeys={setFallbackKeys} />);

    const input = screen.getByLabelText('Nuova chiave di riserva');
    const bulk = 'AIzaSyKeyOne11111111111111111, AIzaSyKeyTwo22222222222222222, AIzaSyKeyThree3333333333333333';
    fireEvent.change(input, { target: { value: bulk } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(setFallbackKeys).toHaveBeenCalledWith([
      'AIzaSyKeyOne11111111111111111',
      'AIzaSyKeyTwo22222222222222222',
      'AIzaSyKeyThree3333333333333333',
    ]);
  });

  it('supports clipboard paste of multi-line keys', () => {
    const setFallbackKeys = vi.fn();
    render(<ApiKeySection {...defaultProps} setFallbackKeys={setFallbackKeys} />);

    const input = screen.getByLabelText('Nuova chiave di riserva');
    const multiLine = 'AIzaSyPasteOne111111111111111\nAIzaSyPasteTwo222222222222222';
    fireEvent.paste(input, {
      clipboardData: {
        getData: (type: string) => (type === 'text' ? multiLine : ''),
      },
    });

    expect(setFallbackKeys).toHaveBeenCalledWith([
      'AIzaSyPasteOne111111111111111',
      'AIzaSyPasteTwo222222222222222',
    ]);
  });

  it('removes a fallback key after confirmation prompt', () => {
    const setFallbackKeys = vi.fn();
    const fallbackKeys = [
      'AIzaSyBackupKey11111111111111ABCD',
      'AIzaSyBackupKey22222222222222WXYZ',
    ];

    render(<ApiKeySection {...defaultProps} fallbackKeys={fallbackKeys} setFallbackKeys={setFallbackKeys} />);

    const kebab = screen.getByRole('button', { name: 'Opzioni Chiave Riserva 1' });
    fireEvent.click(kebab);

    const removeBtn = screen.getByRole('button', { name: 'Rimuovi chiave' });
    fireEvent.click(removeBtn);

    // Confirmation modal should open
    expect(screen.getByText('Rimuovi chiave API')).toBeTruthy();
    expect(screen.getByText(/Sei sicuro di voler rimuovere Chiave Riserva 1/i)).toBeTruthy();

    // Confirm removal
    const confirmBtn = screen.getByRole('button', { name: 'Rimuovi' });
    fireEvent.click(confirmBtn);

    expect(setFallbackKeys).toHaveBeenCalledWith(['AIzaSyBackupKey22222222222222WXYZ']);
  });

  it('removes primary key and auto-promotes first reserve key after confirmation', () => {
    const setApiKey = vi.fn();
    const setFallbackKeys = vi.fn();
    const fallbackKeys = [
      'AIzaSyBackupKey11111111111111ABCD',
      'AIzaSyBackupKey22222222222222WXYZ',
    ];

    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={fallbackKeys}
        setApiKey={setApiKey}
        setFallbackKeys={setFallbackKeys}
      />
    );

    const kebab = screen.getByRole('button', { name: 'Opzioni chiave principale' });
    fireEvent.click(kebab);

    const removePrimaryBtn = screen.getByRole('button', { name: 'Rimuovi chiave' });
    fireEvent.click(removePrimaryBtn);

    expect(screen.getByText('Rimuovi chiave API')).toBeTruthy();
    expect(screen.getByText(/La Chiave Riserva 1 verrà promossa automaticamente/i)).toBeTruthy();

    const confirmBtn = screen.getByRole('button', { name: 'Rimuovi' });
    fireEvent.click(confirmBtn);

    expect(setApiKey).toHaveBeenCalledWith('AIzaSyBackupKey11111111111111ABCD');
    expect(setFallbackKeys).toHaveBeenCalledWith(['AIzaSyBackupKey22222222222222WXYZ']);
  });

  it('requests explicit deletion when the primary key is protected and inaccessible', () => {
    const setApiKey = vi.fn();
    const onClearProtectedPrimary = vi.fn();

    render(
      <ApiKeySection
        {...defaultProps}
        apiKey=""
        setApiKey={setApiKey}
        hasProtectedKey
        onClearProtectedPrimary={onClearProtectedPrimary}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Opzioni chiave principale' }));
    fireEvent.click(screen.getByRole('button', { name: 'Rimuovi chiave' }));
    fireEvent.click(screen.getByRole('button', { name: 'Rimuovi' }));

    expect(setApiKey).toHaveBeenCalledWith('');
    expect(onClearProtectedPrimary).toHaveBeenCalledTimes(1);
  });

  it('promotes a reserve key to primary and swaps current primary into reserves', () => {
    const setApiKey = vi.fn();
    const setFallbackKeys = vi.fn();
    const fallbackKeys = [
      'AIzaSyBackupKey11111111111111ABCD',
      'AIzaSyBackupKey22222222222222WXYZ',
    ];

    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={fallbackKeys}
        setApiKey={setApiKey}
        setFallbackKeys={setFallbackKeys}
      />
    );

    const kebab = screen.getByRole('button', { name: 'Opzioni Chiave Riserva 2' });
    fireEvent.click(kebab);

    const promoteBtn = screen.getByRole('button', { name: 'Imposta come principale' });
    fireEvent.click(promoteBtn);

    expect(setApiKey).toHaveBeenCalledWith('AIzaSyBackupKey22222222222222WXYZ');
    expect(setFallbackKeys).toHaveBeenCalledWith([
      'AIzaSyBackupKey11111111111111ABCD',
      defaultProps.apiKey,
    ]);
  });

  it('reorders reserve keys with move up and move down buttons', () => {
    const setFallbackKeys = vi.fn();
    const fallbackKeys = [
      'AIzaSyBackupKey11111111111111ABCD',
      'AIzaSyBackupKey22222222222222WXYZ',
      'AIzaSyBackupKey33333333333333KLMN',
    ];

    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={fallbackKeys}
        setFallbackKeys={setFallbackKeys}
      />
    );

    // Move Down on first reserve via Kebab Menu
    const kebab = screen.getByRole('button', { name: 'Opzioni Chiave Riserva 1' });
    fireEvent.click(kebab);

    const moveDownFirst = screen.getByRole('button', { name: 'Sposta giù di priorità' });
    fireEvent.click(moveDownFirst);

    expect(setFallbackKeys).toHaveBeenCalledWith([
      'AIzaSyBackupKey22222222222222WXYZ',
      'AIzaSyBackupKey11111111111111ABCD',
      'AIzaSyBackupKey33333333333333KLMN',
    ]);
  });

  it('keeps saved keys masked after reordering and offers no reveal actions', async () => {
    const firstKey = 'AIzaSyBackupKey11111111111111ABCD';
    const secondKey = 'AIzaSyBackupKey22222222222222WXYZ';
    const { rerender } = render(
      <ApiKeySection {...defaultProps} fallbackKeys={[firstKey, secondKey]} />
    );

    expect(screen.getByText('...2345')).toBeTruthy();
    expect(screen.queryByText(defaultProps.apiKey)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mostra chiavi' })).toBeNull();
    for (const name of ['Opzioni chiave principale', 'Opzioni Chiave Riserva 1']) {
      fireEvent.click(screen.getByRole('button', { name }));
      expect(screen.getByRole('button', { name: 'Copia chiave' })).toBeTruthy();
      expect(screen.queryByRole('button', { name: 'Mostra in chiaro' })).toBeNull();
      fireEvent.click(screen.getByRole('button', { name }));
      await waitFor(() => expect(screen.queryByRole('button', { name: 'Copia chiave' })).toBeNull());
    }

    rerender(<ApiKeySection {...defaultProps} fallbackKeys={[secondKey, firstKey]} />);

    expect(screen.getByText('...ABCD')).toBeTruthy();
    expect(screen.getByText('...WXYZ')).toBeTruthy();
    expect(screen.queryByText(firstKey)).toBeNull();
    expect(screen.queryByText(secondKey)).toBeNull();
  });

  it('copies key to clipboard via kebab menu', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    const fallbackKeys = ['AIzaSyBackupKey11111111111111ABCD'];
    render(<ApiKeySection {...defaultProps} fallbackKeys={fallbackKeys} />);

    const kebab = screen.getByRole('button', { name: 'Opzioni Chiave Riserva 1' });
    fireEvent.click(kebab);

    const copyBtn = screen.getByRole('button', { name: 'Copia chiave' });
    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeTextMock).toHaveBeenCalledWith('AIzaSyBackupKey11111111111111ABCD');
  });

  it('renders live status badges from apiUsage telemetry', () => {
    const mockUsage: ApiUsageResult = {
      credentials: [
        {
          id: 'cred-1',
          masked_key: '...2345',
          label: 'Chiave Principale',
          is_primary: true,
          operational_status: 'temporarily_failing',
          last_error_message: 'Quota esaurita (RPD limit reached)',
          last_error_code: 429,
          key_type: 'standard_legacy',
          project_id: 'test-project',
        },
        {
          id: 'cred-2',
          masked_key: '...ABCD',
          label: 'Chiave Riserva 1',
          is_primary: false,
          operational_status: 'active',
          last_error_message: null,
          last_error_code: null,
          key_type: 'standard_legacy',
          project_id: 'test-project',
        },
      ],
    } as unknown as ApiUsageResult;

    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={['AIzaSyBackupKey11111111111111ABCD']}
        apiUsage={mockUsage}
      />
    );

    expect(screen.getByText('Quota esaurita (oggi)')).toBeTruthy();
    expect(screen.getByText('In uso (riserva)')).toBeTruthy();
  });

  it('matches stale telemetry by key identity after primary promotion', () => {
    const oldPrimary = 'AIzaSyPrimary0123456789012345';
    const promotedKey = 'AIzaSyBackupKey11111111111111ABCD';
    const staleUsage = {
      credentials: [
        {
          masked_key: 'AIzaSy...2345',
          is_primary: true,
          operational_status: 'temporarily_failing',
          last_error_message: 'Quota RPD esaurita',
          last_error_code: 429,
        },
        {
          masked_key: 'AIzaSy...ABCD',
          is_primary: false,
          operational_status: 'active',
          last_error_message: null,
          last_error_code: null,
        },
      ],
    } as unknown as ApiUsageResult;

    render(
      <ApiKeySection
        {...defaultProps}
        apiKey={promotedKey}
        fallbackKeys={[oldPrimary]}
        apiUsage={staleUsage}
      />
    );

    const primaryRow = screen.getByText('Chiave Principale').closest('.justify-between');
    const fallbackRow = screen.getByText('Chiave Riserva 1').closest('.justify-between');
    expect(primaryRow).not.toBeNull();
    expect(fallbackRow).not.toBeNull();
    expect(within(primaryRow as HTMLElement).getByText('Operativa')).toBeTruthy();
    expect(within(fallbackRow as HTMLElement).getByText('Quota esaurita (oggi)')).toBeTruthy();
  });

  it('renders footer caption and handles external link click', () => {
    const openUrlMock = vi.fn();
    (window as unknown as { pywebview: { api: { open_url: typeof openUrlMock } } }).pywebview = {
      api: { open_url: openUrlMock },
    };

    render(<ApiKeySection {...defaultProps} />);

    expect(screen.getByText(/Le chiavi di riserva subentrano in ordine/i)).toBeTruthy();

    const link = screen.getByRole('link', { name: /Ottieni gratis su aistudio\.google\.com/i });
    expect(link).toBeTruthy();

    fireEvent.click(link);
    expect(openUrlMock).toHaveBeenCalledWith('https://aistudio.google.com/apikey');
  });

  it('adds valid keys from a mixed batch and displays notice for skipped duplicates/invalid keys', () => {
    const setFallbackKeys = vi.fn();
    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={['AIzaSyBackupKey11111111111111ABCD']}
        setFallbackKeys={setFallbackKeys}
      />
    );

    const input = screen.getByLabelText('Nuova chiave di riserva');
    const mixedBatch = `AIzaSyValidNewKey22222222222222\nAIzaSyBackupKey11111111111111ABCD\ninvalid_format\n${defaultProps.apiKey}`;
    fireEvent.paste(input, {
      clipboardData: {
        getData: (type: string) => (type === 'text' ? mixedBatch : ''),
      },
    });

    expect(setFallbackKeys).toHaveBeenCalledWith([
      'AIzaSyBackupKey11111111111111ABCD',
      'AIzaSyValidNewKey22222222222222',
    ]);
    expect(screen.getByText(/1 chiave aggiunta\. 3 ignorate/i)).toBeTruthy();
  });

  it('shows error notice when all keys in a batch are invalid or duplicates', () => {
    const setFallbackKeys = vi.fn();
    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={['AIzaSyBackupKey11111111111111ABCD']}
        setFallbackKeys={setFallbackKeys}
      />
    );

    const input = screen.getByLabelText('Nuova chiave di riserva');
    const invalidBatch = `AIzaSyBackupKey11111111111111ABCD\n${defaultProps.apiKey}\ninvalid_format`;
    fireEvent.paste(input, {
      clipboardData: {
        getData: (type: string) => (type === 'text' ? invalidBatch : ''),
      },
    });

    expect(setFallbackKeys).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Nessuna chiave valida aggiunta: le chiavi inserite sono già presenti o non valide\./i)
    ).toBeTruthy();
  });

  it('does not mark fallback keys as "In uso (riserva)" when all keys are exhausted for preferredModel', () => {
    const mockUsage = {
      credentials: [
        {
          masked_key: 'AIzaSy...2345',
          is_primary: true,
          operational_status: 'temporarily_failing',
          exhausted_models: ['gemini-3.5-flash'],
        },
        {
          masked_key: 'AIzaSy...ABCD',
          is_primary: false,
          operational_status: 'active',
          exhausted_models: ['gemini-3.5-flash'],
        },
      ],
    } as unknown as ApiUsageResult;

    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={['AIzaSyBackupKey11111111111111ABCD']}
        preferredModel="gemini-3.5-flash"
        apiUsage={mockUsage}
      />
    );

    // Neither key should be marked as "In uso (riserva)"
    expect(screen.queryByText('In uso (riserva)')).toBeNull();
    // Both should show uniform quota exhausted for Gemini 3.5 Flash
    const badges = screen.getAllByText('Quota esaurita per Gemini 3.5 Flash');
    expect(badges).toHaveLength(2);
  });

  it('skips fallback keys exhausted on preferredModel and promotes first available reserve', () => {
    const mockUsage = {
      credentials: [
        {
          masked_key: 'AIzaSy...2345',
          is_primary: true,
          operational_status: 'temporarily_failing',
          exhausted_models: ['gemini-3.5-flash'],
        },
        {
          masked_key: 'AIzaSy...ABCD',
          is_primary: false,
          operational_status: 'active',
          exhausted_models: ['gemini-3.5-flash'],
        },
        {
          masked_key: 'AIzaSy...WXYZ',
          is_primary: false,
          operational_status: 'active',
          exhausted_models: [],
        },
      ],
    } as unknown as ApiUsageResult;

    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={[
          'AIzaSyBackupKey11111111111111ABCD',
          'AIzaSyBackupKey22222222222222WXYZ',
        ]}
        preferredModel="gemini-3.5-flash"
        apiUsage={mockUsage}
      />
    );

    // Second reserve (WXYZ) should be in use, not first (ABCD)
    expect(screen.getByText('In uso (riserva)')).toBeTruthy();
    const exhaustedBadges = screen.getAllByText('Quota esaurita per Gemini 3.5 Flash');
    expect(exhaustedBadges).toHaveLength(2);
  });

  it('correctly keeps reserve key as "In riserva" with tag when exhausted only on another model', () => {
    const mockUsage = {
      credentials: [
        {
          masked_key: 'AIzaSy...2345',
          is_primary: true,
          operational_status: 'active',
          exhausted_models: ['gemini-2.5-flash'],
        },
        {
          masked_key: 'AIzaSy...ABCD',
          is_primary: false,
          operational_status: 'temporarily_failing',
          exhausted_models: ['gemini-2.5-flash'],
        },
        {
          masked_key: 'AIzaSy...WXYZ',
          is_primary: false,
          operational_status: 'active',
          exhausted_models: [],
        },
      ],
    } as unknown as ApiUsageResult;

    render(
      <ApiKeySection
        {...defaultProps}
        fallbackKeys={[
          'AIzaSyBackupKey11111111111111ABCD',
          'AIzaSyBackupKey22222222222222WXYZ',
        ]}
        preferredModel="gemini-3.5-flash"
        apiUsage={mockUsage}
      />
    );

    // Primary is operative for Gemini 3.5 Flash
    expect(screen.getByText('Operativa')).toBeTruthy();
    // Fallback 1 is in reserve (NOT quota exhausted for current model)
    const inReserveBadges = screen.getAllByText('In riserva');
    expect(inReserveBadges).toHaveLength(2);
    // Both primary and fallback 1 have the tag for 2.5 Flash
    const tags = screen.getAllByText('Esaurita per Gemini 2.5 Flash');
    expect(tags).toHaveLength(2);
  });
});
