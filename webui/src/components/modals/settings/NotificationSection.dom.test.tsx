import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NotificationSection } from './NotificationSection';
import { STORAGE_KEYS } from '../../../storageKeys';

describe('NotificationSection', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders title and default enabled switch', () => {
    render(<NotificationSection notificationsEnabled onChange={vi.fn()} />);
    expect(screen.getByText('Notifiche di sistema')).toBeTruthy();
    const toggle = screen.getByRole('switch');
    expect(toggle.getAttribute('aria-checked')).toBe('true');
  });

  it('requests a draft change without writing to localStorage', () => {
    const onChange = vi.fn();
    const { rerender } = render(<NotificationSection notificationsEnabled onChange={onChange} />);
    const toggle = screen.getByRole('switch');

    fireEvent.click(toggle);
    expect(onChange).toHaveBeenLastCalledWith(false);
    expect(localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED)).toBeNull();

    rerender(<NotificationSection notificationsEnabled={false} onChange={onChange} />);
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenLastCalledWith(true);
    expect(localStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED)).toBeNull();
  });

  it('prevents changes while saving', () => {
    const onChange = vi.fn();
    render(<NotificationSection notificationsEnabled onChange={onChange} disabled />);
    fireEvent.click(screen.getByRole('switch'));
    expect(onChange).not.toHaveBeenCalled();
  });
});
