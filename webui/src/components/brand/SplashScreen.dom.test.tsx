import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { SPLASH_MS, SplashScreen } from './SplashScreen';

afterEach(() => {
  vi.useRealTimers();
  sessionStorage.clear();
});

describe('SplashScreen', () => {
  it('is hidden during unit tests unless forced', () => {
    render(<SplashScreen />);
    expect(screen.queryByTestId('splash')).toBeNull();
  });

  it('plays once, then hides itself', () => {
    vi.useFakeTimers();
    const onDone = vi.fn();
    render(<SplashScreen force onDone={onDone} />);
    expect(screen.getByTestId('splash')).toBeTruthy();
    expect(screen.getByTestId('splash').querySelector('.jot-wordmark')).toBeTruthy();
    act(() => { vi.advanceTimersByTime(SPLASH_MS + 10); });
    expect(screen.queryByTestId('splash')).toBeNull();
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem('jot.splash.v1')).toBe('1');
  });

  it('a click skips it', () => {
    const onDone = vi.fn();
    render(<SplashScreen force onDone={onDone} />);
    fireEvent.click(screen.getByTestId('splash'));
    expect(screen.queryByTestId('splash')).toBeNull();
    expect(onDone).toHaveBeenCalled();
  });
});
