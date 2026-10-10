import { render, screen, fireEvent, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupPage } from './SetupPage';

const baseProps = {
  hasProtectedKey: false,
  onSaved: vi.fn(),
  preferredModel: 'gemini-2.5-flash',
  fallbackKeys: [],
  fallbackModels: [],
};

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

beforeEach(() => setPywebview(undefined));
afterEach(() => setPywebview(undefined));

describe('SetupPage', () => {
  it('passes temporary credential storage to the queue after setup', async () => {
    const onSaved = vi.fn();
    const storage = { primary: 'session_only', fallback: 'absent' };
    setPywebview({ save_settings: vi.fn().mockResolvedValue({ ok: true, credential_storage: storage }) });
    render(<SetupPage {...baseProps} onSaved={onSaved} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), { target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Salva e inizia/i })); });
    expect(onSaved).toHaveBeenCalledWith('AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345', 'gemini-2.5-flash', storage);
  });

  it('shows "Configura la tua API Key" when no protected key', () => {
    render(<SetupPage {...baseProps} />);
    expect(screen.getByText('Configura la tua API Key')).toBeTruthy();
  });

  it('shows alternative text when hasProtectedKey is true', () => {
    render(<SetupPage {...baseProps} hasProtectedKey />);
    expect(screen.getByText('Chiave API non accessibile')).toBeTruthy();
  });

  it('masks input by default with obscured-text', () => {
    render(<SetupPage {...baseProps} />);
    const input = screen.getByPlaceholderText(/Incolla qui la tua API Key/);
    expect(input.classList.contains('obscured-text')).toBe(true);
    expect(input.getAttribute('data-masked')).toBe('true');
  });

  it('toggles input visibility on eye button click', () => {
    render(<SetupPage {...baseProps} />);
    const input = screen.getByPlaceholderText(/Incolla qui la tua API Key/) as HTMLInputElement;
    expect(input.classList.contains('obscured-text')).toBe(true);
    expect(input.getAttribute('data-masked')).toBe('true');
    fireEvent.click(screen.getByLabelText('Mostra chiave'));
    expect(input.classList.contains('obscured-text')).toBe(false);
    expect(input.getAttribute('data-masked')).toBe('false');
    fireEvent.click(screen.getByLabelText('Nascondi chiave'));
    expect(input.classList.contains('obscured-text')).toBe(true);
    expect(input.getAttribute('data-masked')).toBe('true');
  });

  it('shows valid format hint for a valid AIzaSy key', () => {
    render(<SetupPage {...baseProps} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    expect(screen.getByText(/Formato valido/)).toBeTruthy();
  });

  it('shows invalid format warning for a bad key', () => {
    render(<SetupPage {...baseProps} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), {
      target: { value: 'bad-key' },
    });
    expect(screen.getByText(/Formato non valido/)).toBeTruthy();
  });

  it('Save button is disabled when key is empty', () => {
    render(<SetupPage {...baseProps} />);
    const btn = screen.getAllByText('Salva e inizia').find(
      el => el.closest('button') !== null,
    )?.closest('button') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(true);
  });

  it('shows error when bridge is unavailable on save', async () => {
    render(<SetupPage {...baseProps} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    const saveBtn = screen.getAllByText('Salva e inizia').find(
      el => el.closest('button') !== null,
    )?.closest('button') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(saveBtn);
    });
    await vi.waitFor(() =>
      expect(screen.getByText(/Bridge Python non disponibile/)).toBeTruthy(),
    );
  });

  it('calls open_url when AI Studio link is clicked', () => {
    const openUrl = vi.fn();
    setPywebview({ open_url: openUrl });
    render(<SetupPage {...baseProps} />);
    fireEvent.click(screen.getByText('aistudio.google.com/apikey'));
    expect(openUrl).toHaveBeenCalledWith('https://aistudio.google.com/apikey');
  });

  it('shows error when save_settings returns {ok:false}', async () => {
    const mockSave = vi.fn().mockResolvedValue({ ok: false, error: 'quota esaurita' });
    setPywebview({ save_settings: mockSave });
    render(<SetupPage {...baseProps} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    const saveBtn = screen.getAllByText('Salva e inizia').find(
      el => el.closest('button') !== null,
    )?.closest('button') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(saveBtn);
    });
    await vi.waitFor(() =>
      expect(screen.getByText(/quota esaurita/)).toBeTruthy(),
    );
  });

  it('calls onSaved when save_settings succeeds', async () => {
    const onSaved = vi.fn();
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ save_settings: mockSave });
    render(<SetupPage {...baseProps} onSaved={onSaved} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    const saveBtn = screen.getAllByText('Salva e inizia').find(
      el => el.closest('button') !== null,
    )?.closest('button') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(saveBtn);
    });
    await vi.waitFor(() =>
      expect(onSaved).toHaveBeenCalledWith(
        'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345',
        'gemini-2.5-flash',
      ),
    );
  });

  it('Enter key on valid input triggers save', async () => {
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ save_settings: mockSave });
    render(<SetupPage {...baseProps} />);
    const input = screen.getByPlaceholderText(/Incolla qui la tua API Key/);
    fireEvent.change(input, { target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' } });
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });
    await vi.waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
  });

  it('Enter key on invalid input does NOT trigger save', async () => {
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ save_settings: mockSave });
    render(<SetupPage {...baseProps} />);
    const input = screen.getByPlaceholderText(/Incolla qui la tua API Key/);
    fireEvent.change(input, { target: { value: 'bad-key' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await vi.waitFor(() => expect(mockSave).not.toHaveBeenCalled());
  });

  it('shows throw error when save_settings throws', async () => {
    const mockSave = vi.fn().mockRejectedValue(new Error('network error'));
    setPywebview({ save_settings: mockSave });
    render(<SetupPage {...baseProps} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    const saveBtn = screen.getAllByText('Salva e inizia').find(
      el => el.closest('button') !== null,
    )?.closest('button') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(saveBtn);
    });
    await vi.waitFor(() =>
      expect(screen.getByText(/network error/)).toBeTruthy(),
    );
  });

  it('validates environment before save and displays error if API key check fails', async () => {
    const mockValidate = vi.fn().mockResolvedValue({
      ok: true,
      result: {
        ok: false,
        checks: [
          {
            id: 'api_key',
            label: 'API Key Gemini',
            status: 'error',
            message: 'API key non valida o non attiva.',
            details: '400 API_KEY_INVALID',
          },
        ],
      },
    });
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ validate_environment: mockValidate, save_settings: mockSave });

    render(<SetupPage {...baseProps} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    const saveBtn = screen.getAllByText('Salva e inizia').find(
      el => el.closest('button') !== null,
    )?.closest('button') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(saveBtn);
    });

    await vi.waitFor(() => {
      expect(mockValidate).toHaveBeenCalledTimes(1);
      expect(mockSave).not.toHaveBeenCalled();
      expect(screen.getByText('API key non valida o non attiva.')).toBeTruthy();
    });
  });

  it('automatically falls back to gemini-3.5-flash if primary model returns 404', async () => {
    const onSaved = vi.fn();
    const mockValidate = vi.fn().mockImplementation((_k, _v, model) => {
      if (model === 'gemini-2.5-flash') {
        return Promise.resolve({
          ok: true,
          result: {
            ok: false,
            checks: [
              {
                id: 'api_key',
                status: 'error',
                message: 'Modello primario non accessibile.',
                details: 'gemini-2.5-flash: 404 NOT_FOUND',
              },
            ],
          },
        });
      }
      return Promise.resolve({
        ok: true,
        result: {
          ok: true,
          checks: [
            {
              id: 'api_key',
              status: 'ok',
              message: 'Accesso disponibile per gemini-3.5-flash.',
              details: 'gemini-3.5-flash',
            },
          ],
        },
      });
    });
    const mockSave = vi.fn().mockResolvedValue({ ok: true });
    setPywebview({ validate_environment: mockValidate, save_settings: mockSave });

    render(<SetupPage {...baseProps} preferredModel="gemini-2.5-flash" onSaved={onSaved} />);
    fireEvent.change(screen.getByPlaceholderText(/Incolla qui la tua API Key/), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    const saveBtn = screen.getAllByText('Salva e inizia').find(
      el => el.closest('button') !== null,
    )?.closest('button') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(saveBtn);
    });

    await vi.waitFor(() => {
      expect(mockValidate).toHaveBeenCalledTimes(2);
      expect(mockSave).toHaveBeenCalledWith(
        'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345',
        [],
        'gemini-3.5-flash',
        [],
      );
      expect(onSaved).toHaveBeenCalledWith(
        'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345',
        'gemini-3.5-flash',
      );
    });
  });
});
