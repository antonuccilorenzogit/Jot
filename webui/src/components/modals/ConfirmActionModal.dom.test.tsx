import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmActionModal } from './ConfirmActionModal';

const baseProps = {
  isOpen: true,
  title: 'Conferma azione',
  description: 'Sei sicuro di voler procedere?',
  confirmLabel: 'Elimina',
  onClose: vi.fn(),
  onConfirm: vi.fn(),
};

describe('ConfirmActionModal', () => {
  it('renders title and description when open', () => {
    render(<ConfirmActionModal {...baseProps} />);
    expect(screen.getByText('Conferma azione')).toBeTruthy();
    expect(screen.getByText('Sei sicuro di voler procedere?')).toBeTruthy();
    expect(screen.getByRole('alertdialog').getAttribute('aria-modal')).toBe('true');
  });

  it('focuses the safe action when opened and restores the previous focus when closed', () => {
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    trigger.focus();

    const { rerender } = render(<ConfirmActionModal {...baseProps} />);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Annulla' }));

    rerender(<ConfirmActionModal {...baseProps} isOpen={false} />);
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    render(<ConfirmActionModal {...baseProps} onClose={onClose} />);

    fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('keeps Tab focus inside the dialog', () => {
    render(<ConfirmActionModal {...baseProps} />);
    const closeButton = screen.getByRole('button', { name: 'Chiudi finestra' });
    const confirmButton = screen.getByRole('button', { name: 'Elimina' });

    confirmButton.focus();
    fireEvent.keyDown(confirmButton, { key: 'Tab' });
    expect(document.activeElement).toBe(closeButton);

    closeButton.focus();
    fireEvent.keyDown(closeButton, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(confirmButton);
  });

  it('renders confirm and cancel buttons', () => {
    render(<ConfirmActionModal {...baseProps} />);
    expect(screen.getByText('Elimina')).toBeTruthy();
    expect(screen.getByText('Annulla')).toBeTruthy();
  });

  it('uses custom cancelLabel when provided', () => {
    render(<ConfirmActionModal {...baseProps} cancelLabel="No grazie" />);
    expect(screen.getByText('No grazie')).toBeTruthy();
  });

  it('calls onConfirm when confirm button is clicked', () => {
    const onConfirm = vi.fn();
    render(<ConfirmActionModal {...baseProps} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByText('Elimina'));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when cancel button is clicked', () => {
    const onClose = vi.fn();
    render(<ConfirmActionModal {...baseProps} onClose={onClose} />);
    fireEvent.click(screen.getByText('Annulla'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when X button is clicked', () => {
    const onClose = vi.fn();
    render(<ConfirmActionModal {...baseProps} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText('Chiudi finestra'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not call onClose when backdrop overlay is clicked', () => {
    const onClose = vi.fn();
    const { container } = render(<ConfirmActionModal {...baseProps} onClose={onClose} />);
    const backdrop = container.querySelector('.modal-overlay') as HTMLElement;
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('renders nothing when isOpen is false', () => {
    render(<ConfirmActionModal {...baseProps} isOpen={false} />);
    expect(screen.queryByText('Conferma azione')).toBeNull();
  });
});
