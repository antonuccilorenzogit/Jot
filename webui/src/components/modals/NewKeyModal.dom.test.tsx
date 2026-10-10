import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NewKeyModal } from './NewKeyModal';

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

beforeEach(() => setPywebview(undefined));
afterEach(() => setPywebview(undefined));

describe('NewKeyModal', () => {
  it('renders nothing when isOpen is false', () => {
    render(<NewKeyModal isOpen={false} onClose={vi.fn()} />);
    expect(screen.queryByText('Esaurimento quota')).toBeNull();
  });

  it('shows modal content when isOpen is true', () => {
    render(<NewKeyModal isOpen onClose={vi.fn()} />);
    expect(screen.getByText('Esaurimento quota')).toBeTruthy();
    expect(screen.getByPlaceholderText('Incolla qui la nuova API Key...')).toBeTruthy();
  });

  it('shows initial hint text when input is empty', () => {
    render(<NewKeyModal isOpen onClose={vi.fn()} />);
    expect(screen.getByText('Inserisci una chiave Gemini valida per continuare.')).toBeTruthy();
  });

  it('shows valid format message for valid key', () => {
    render(<NewKeyModal isOpen onClose={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('Incolla qui la nuova API Key...'), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    expect(screen.getByText('Formato chiave valido.')).toBeTruthy();
  });

  it('shows invalid format message for bad key', () => {
    render(<NewKeyModal isOpen onClose={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('Incolla qui la nuova API Key...'), {
      target: { value: 'bad-key' },
    });
    expect(screen.getByText(/La chiave non sembra valida/)).toBeTruthy();
  });

  it('Continua button is disabled when key is invalid', () => {
    render(<NewKeyModal isOpen onClose={vi.fn()} />);
    const btn = screen.getByText('Continua').closest('button') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('calls onClose and answer_new_key(null) when Sospendi elaborazione is clicked', () => {
    const onClose = vi.fn();
    const answerNewKey = vi.fn();
    setPywebview({ answer_new_key: answerNewKey });
    render(<NewKeyModal isOpen onClose={onClose} />);
    fireEvent.click(screen.getByText('Sospendi elaborazione'));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(answerNewKey).toHaveBeenCalledWith(null);
  });

  it('shows clear quota exhausted message and direct input on open', () => {
    render(<NewKeyModal isOpen onClose={vi.fn()} />);
    expect(screen.getByText(/Tutte le chiavi API configurate hanno esaurito la quota/)).toBeTruthy();
    expect(screen.getByPlaceholderText('Incolla qui la nuova API Key...')).toBeTruthy();
  });

  it('calls answer_new_key with key and onClose when valid key is submitted', () => {
    const onClose = vi.fn();
    const answerNewKey = vi.fn();
    setPywebview({ answer_new_key: answerNewKey });
    render(<NewKeyModal isOpen onClose={onClose} />);
    fireEvent.change(screen.getByPlaceholderText('Incolla qui la nuova API Key...'), {
      target: { value: 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345' },
    });
    fireEvent.click(screen.getByText('Continua'));
    expect(answerNewKey).toHaveBeenCalledWith('AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when X button is clicked', () => {
    const onClose = vi.fn();
    render(<NewKeyModal isOpen onClose={onClose} />);
    fireEvent.click(screen.getByLabelText('Chiudi finestra'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not close when backdrop overlay is clicked', () => {
    const onClose = vi.fn();
    const { container } = render(<NewKeyModal isOpen onClose={onClose} />);
    const backdrop = container.querySelector('.modal-overlay') as HTMLElement;
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape key press', () => {
    const onClose = vi.fn();
    render(<NewKeyModal isOpen onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('resets input when modal reopens', () => {
    const { rerender } = render(<NewKeyModal isOpen onClose={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('Incolla qui la nuova API Key...'), {
      target: { value: 'some-key' },
    });
    rerender(<NewKeyModal isOpen={false} onClose={vi.fn()} />);
    rerender(<NewKeyModal isOpen onClose={vi.fn()} />);
    expect((screen.getByPlaceholderText('Incolla qui la nuova API Key...') as HTMLInputElement).value).toBe('');
  });
});
