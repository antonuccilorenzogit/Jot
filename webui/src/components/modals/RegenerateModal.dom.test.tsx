import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RegenerateModal } from './RegenerateModal';

describe('RegenerateModal', () => {
  it('renders nothing when prompt is null', () => {
    render(<RegenerateModal prompt={null} onAnswer={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.queryByText('Versione già pronta')).toBeNull();
  });

  it('shows "Versione già pronta" title for completed mode', () => {
    render(
      <RegenerateModal
        prompt={{ filename: 'lezione.mp3', mode: 'completed' }}
        onAnswer={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText('Versione già pronta')).toBeTruthy();
    expect(screen.getByText(/lezione\.mp3/)).toBeTruthy();
  });

  it('shows "Ripresa disponibile" title for resume mode', () => {
    render(
      <RegenerateModal
        prompt={{ filename: 'lezione.mp3', mode: 'resume' }}
        onAnswer={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText('Ripresa disponibile')).toBeTruthy();
  });

  it('calls onAnswer(false) for "Usa versione pronta" button in completed mode', () => {
    const onAnswer = vi.fn();
    render(
      <RegenerateModal
        prompt={{ filename: 'x.mp3', mode: 'completed' }}
        onAnswer={onAnswer}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText('Usa versione pronta'));
    expect(onAnswer).toHaveBeenCalledWith(false);
  });

  it('calls onAnswer(true) for "Rigenera da zero" button', () => {
    const onAnswer = vi.fn();
    render(
      <RegenerateModal
        prompt={{ filename: 'x.mp3', mode: 'completed' }}
        onAnswer={onAnswer}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText('Rigenera da zero'));
    expect(onAnswer).toHaveBeenCalledWith(true);
  });

  it('calls onAnswer(false) for "Riprendi da dove eri rimasto" in resume mode', () => {
    const onAnswer = vi.fn();
    render(
      <RegenerateModal
        prompt={{ filename: 'x.mp3', mode: 'resume' }}
        onAnswer={onAnswer}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText('Riprendi da dove eri rimasto'));
    expect(onAnswer).toHaveBeenCalledWith(false);
  });

  it('calls onDismiss when X button is clicked', () => {
    const onDismiss = vi.fn();
    render(
      <RegenerateModal
        prompt={{ filename: 'x.mp3', mode: 'completed' }}
        onAnswer={vi.fn()}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByLabelText('Chiudi finestra'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
