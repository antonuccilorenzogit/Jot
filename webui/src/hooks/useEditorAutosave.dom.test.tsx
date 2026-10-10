import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useEditorAutosave } from './useEditorAutosave';

function setPywebview(api: Record<string, unknown> | undefined) {
  Object.defineProperty(window, 'pywebview', {
    value: api === undefined ? undefined : { api },
    writable: true,
    configurable: true,
  });
}

describe('useEditorAutosave', () => {
  it.each(['rejection', 'exception'])('allows discard after a close-time save %s without retrying on unmount', async failure => {
    const saveMock = failure === 'exception'
      ? vi.fn().mockRejectedValue(new Error('Bridge unavailable'))
      : vi.fn().mockResolvedValue({ ok: false, saved: false });
    setPywebview({ save_html_content: saveMock });
    const onClose = vi.fn();
    const { result, unmount } = renderHook(() => useEditorAutosave({
      htmlPath: '/failed-close.html', previewContent: '<p>Original</p>',
      getHtmlRef: { current: () => '<p>Unsaved changes</p>' }, onClose,
    }));
    act(() => result.current.scheduleAutosave());
    await act(async () => { await result.current.flushAndClose(); });
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => { await result.current.flushAndClose(); });
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    expect(saveMock).toHaveBeenCalledTimes(1);
  });

  beforeEach(() => {
    vi.useFakeTimers();
    setPywebview(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    setPywebview(undefined);
  });

  it('schedules debounced autosave when content changes', async () => {
    const saveMock = vi.fn().mockResolvedValue({ ok: true, saved: true });
    setPywebview({ save_html_content: saveMock });

    let currentHtml = '<p>Initial</p>';
    const getHtmlRef = { current: () => currentHtml };
    const onClose = vi.fn();

    const { result } = renderHook(() =>
      useEditorAutosave({
        htmlPath: '/path/to/test.html',
        previewContent: '<p>Initial</p>',
        getHtmlRef,
        onClose,
      })
    );

    expect(result.current.autosaveStatus).toBe('idle');
    expect(result.current.isDirtyRef.current).toBe(false);

    // Modify content and schedule autosave
    currentHtml = '<p>Updated content</p>';
    act(() => {
      result.current.scheduleAutosave();
    });

    expect(result.current.isDirtyRef.current).toBe(true);

    // Advance timer to trigger autosave (700ms)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(750);
    });

    expect(saveMock).toHaveBeenCalledWith('/path/to/test.html', '<p>Updated content</p>', expect.any(Number));
    expect(result.current.autosaveStatus).toBe('saved');
    expect(result.current.isDirtyRef.current).toBe(false);

    // After 1500ms saved status returns to idle
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(result.current.autosaveStatus).toBe('idle');
  });

  it('registers window global dirty content and flush hooks', async () => {
    const saveMock = vi.fn().mockResolvedValue({ ok: true, saved: true });
    setPywebview({ save_html_content: saveMock });

    let currentHtml = '<p>Initial</p>';
    const getHtmlRef = { current: () => currentHtml };
    const onClose = vi.fn();

    const { result } = renderHook(() =>
      useEditorAutosave({
        htmlPath: '/path/to/test.html',
        previewContent: '<p>Initial</p>',
        getHtmlRef,
        onClose,
      })
    );

    currentHtml = '<p>Dirty</p>';
    act(() => {
      result.current.scheduleAutosave();
    });

    const globalObj = window as unknown as Record<string, () => unknown>;
    expect(typeof globalObj.__jotGetDirtyEditorContent).toBe('function');
    expect(globalObj.__jotGetDirtyEditorContent()).toEqual({
      path: '/path/to/test.html',
      content: '<p>Dirty</p>',
    });

    // Flush dirty content
    const flushFn = globalObj.__jotFlushPendingAutosave as () => Promise<boolean>;
    let flushResult = false;
    await act(async () => {
      flushResult = await flushFn();
    });

    expect(flushResult).toBe(true);
    expect(saveMock).toHaveBeenCalledWith('/path/to/test.html', '<p>Dirty</p>', expect.any(Number));
  });

  it('flushes dirty changes and calls onClose in flushAndClose', async () => {
    const saveMock = vi.fn().mockResolvedValue({ ok: true, saved: true });
    setPywebview({ save_html_content: saveMock });

    let currentHtml = '<p>Initial</p>';
    const getHtmlRef = { current: () => currentHtml };
    const onClose = vi.fn();

    const { result } = renderHook(() =>
      useEditorAutosave({
        htmlPath: '/path/to/test.html',
        previewContent: '<p>Initial</p>',
        getHtmlRef,
        onClose,
      })
    );

    currentHtml = '<p>Closing content</p>';
    act(() => {
      result.current.scheduleAutosave();
    });

    await act(async () => {
      await result.current.flushAndClose();
    });

    expect(saveMock).toHaveBeenCalledWith('/path/to/test.html', '<p>Closing content</p>', expect.any(Number));
    expect(onClose).toHaveBeenCalled();
  });

  it('exposes imperative dirty getter and flush through saveControllerRef', async () => {
    const saveMock = vi.fn().mockResolvedValue({ ok: true, saved: true });
    setPywebview({ save_html_content: saveMock });

    let currentHtml = '<p>Initial</p>';
    const getHtmlRef = { current: () => currentHtml };
    const onClose = vi.fn();
    const saveControllerRef = { current: null };

    const { result, unmount } = renderHook(() =>
      useEditorAutosave({
        htmlPath: '/path/to/test.html',
        previewContent: '<p>Initial</p>',
        getHtmlRef,
        onClose,
        saveControllerRef,
      })
    );

    expect(saveControllerRef.current).not.toBeNull();
    expect(saveControllerRef.current?.getDirtyContent()).toBeNull();

    currentHtml = '<p>Dirty</p>';
    act(() => {
      result.current.scheduleAutosave();
    });

    expect(saveControllerRef.current?.getDirtyContent()).toEqual({
      path: '/path/to/test.html',
      content: '<p>Dirty</p>',
    });

    let flushed = false;
    await act(async () => {
      flushed = await saveControllerRef.current!.flushPendingAutosave();
    });
    expect(flushed).toBe(true);
    expect(saveMock).toHaveBeenCalledWith('/path/to/test.html', '<p>Dirty</p>', expect.any(Number));

    unmount();
    expect(saveControllerRef.current).toBeNull();
  });
});
