import { renderHook, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useOnlineStatus } from './useOnlineStatus';

describe('useOnlineStatus', () => {
  it('defaults to true or navigator.onLine', () => {
    const { result } = renderHook(() => useOnlineStatus());
    expect(typeof result.current).toBe('boolean');
  });

  it('updates state and invokes callback on offline and online events', () => {
    const onStatusChange = vi.fn();
    const { result } = renderHook(() => useOnlineStatus(onStatusChange));

    act(() => {
      window.dispatchEvent(new Event('offline'));
    });
    expect(result.current).toBe(false);
    expect(onStatusChange).toHaveBeenCalledWith(false);

    act(() => {
      window.dispatchEvent(new Event('online'));
    });
    expect(result.current).toBe(true);
    expect(onStatusChange).toHaveBeenCalledWith(true);
  });
});
