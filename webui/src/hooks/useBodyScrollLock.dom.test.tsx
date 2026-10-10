import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useBodyScrollLock } from './useBodyScrollLock';

describe('useBodyScrollLock', () => {
  it('sets body overflow to hidden when modal is open', () => {
    renderHook(() => useBodyScrollLock(true));
    expect(document.body.style.overflow).toBe('hidden');
  });

  it('sets body overflow to unset when modal is closed', () => {
    document.body.style.overflow = 'hidden';
    renderHook(() => useBodyScrollLock(false));
    expect(document.body.style.overflow).toBe('unset');
  });

  it('restores overflow on unmount', () => {
    const { unmount } = renderHook(() => useBodyScrollLock(true));
    expect(document.body.style.overflow).toBe('hidden');
    unmount();
    expect(document.body.style.overflow).toBe('unset');
  });

  it('resets paddingRight to 0 when closed', () => {
    renderHook(() => useBodyScrollLock(false));
    expect(document.body.style.paddingRight).toBe('0px');
  });
});
