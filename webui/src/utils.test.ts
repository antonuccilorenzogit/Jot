import { beforeEach, describe, expect, it, vi } from 'vitest';
import { compareVersions, errorLabel, formatDuration, formatRelativeTime, formatSize, isNetworkError, isPausedError, isQuotaError, isResumableError, readFileAsDataUrl, readAndOptimizeImageAsDataUrl, calculateOptimalDimensions, shortModelName, sortModelsByVersion, getModelDisplayName, MODEL_ORDER } from './utils';

describe('isQuotaError', () => {
  it('returns false for undefined', () => {
    expect(isQuotaError(undefined)).toBe(false);
  });

  it('returns true for quota_daily_limit_phase1', () => {
    expect(isQuotaError('quota_daily_limit_phase1')).toBe(true);
  });

  it('returns true for quota_daily_limit_phase2', () => {
    expect(isQuotaError('quota_daily_limit_phase2')).toBe(true);
  });

  it('returns false for non-quota errors', () => {
    expect(isQuotaError('phase1_all_models_unavailable')).toBe(false);
    expect(isQuotaError('html_export_failed')).toBe(false);
  });
});

describe('isResumableError', () => {
  it('returns false for undefined', () => {
    expect(isResumableError(undefined)).toBe(false);
  });

  it('returns false for empty string', () => {
    expect(isResumableError('')).toBe(false);
  });

  it('returns true for quota_daily_limit_phase1', () => {
    expect(isResumableError('quota_daily_limit_phase1')).toBe(true);
  });

  it('returns true for quota_daily_limit_phase2', () => {
    expect(isResumableError('quota_daily_limit_phase2')).toBe(true);
  });

  it('returns true for phase1_all_models_unavailable', () => {
    expect(isResumableError('phase1_all_models_unavailable')).toBe(true);
  });

  it('returns true for regenerate_prompt_timeout', () => {
    expect(isResumableError('regenerate_prompt_timeout')).toBe(true);
  });

  it('returns false for phase1_chunk_failed — persistent failure, not confident-resume', () => {
    expect(isResumableError('phase1_chunk_failed_3')).toBe(false);
  });

  it('returns false for non-resumable errors', () => {
    expect(isResumableError('html_export_failed')).toBe(false);
    expect(isResumableError('processing_failed')).toBe(false);
  });
});

describe('isPausedError', () => {
  it('returns false for undefined and empty', () => {
    expect(isPausedError(undefined)).toBe(false);
    expect(isPausedError('')).toBe(false);
  });

  it('returns true for regenerate_prompt_timeout', () => {
    expect(isPausedError('regenerate_prompt_timeout')).toBe(true);
  });

  it('returns true when detail is api_key_prompt_timeout', () => {
    expect(isPausedError('quota_daily_limit_phase1', 'api_key_prompt_timeout')).toBe(true);
  });

  it('returns false for standard errors', () => {
    expect(isPausedError('quota_daily_limit_phase1')).toBe(false);
    expect(isPausedError('html_export_failed')).toBe(false);
    expect(isPausedError('phase1_chunk_failed_3')).toBe(false);
  });
});

describe('errorLabel', () => {
  it('returns default message for undefined', () => {
    expect(errorLabel(undefined)).toBe('Elaborazione non completata.');
  });

  it('returns default message for empty string', () => {
    expect(errorLabel('')).toBe('Elaborazione non completata.');
  });

  it('returns mapped label for known error key', () => {
    expect(errorLabel('quota_daily_limit_phase1')).toContain('Quota');
  });

  it('returns generic chunk-specific error for phase1_chunk_failed_ prefix', () => {
    const label = errorLabel('phase1_chunk_failed_3');
    expect(label).toContain('blocco 3');
    expect(label).toContain('4 tentativi');
    expect(label).toContain('Riprendi');
    expect(label).not.toContain('rete');
  });

  it('includes stored detail for phase1_chunk_failed_ prefix', () => {
    const label = errorLabel('phase1_chunk_failed_3', 'FFmpeg error: disk full');
    expect(label).toContain('Errore al blocco 3');
    expect(label).toContain('Dettaglio: FFmpeg error: disk full.');
    expect(label).toContain('Riprendi');
  });

  it('maps phase1_chunk_failed_ with getaddrinfo / network detail to friendly Italian network message', () => {
    const label = errorLabel('phase1_chunk_failed_1', 'ConnectError: [Errno 11001] getaddrinfo failed');
    expect(label).toContain('Errore di connessione al blocco 1');
    expect(label).toContain('impossibile raggiungere i server Google');
    expect(label).toContain('Verifica la connessione a Internet e clicca Riprendi');
  });

  it('maps offline error key to friendly network message', () => {
    expect(errorLabel('offline')).toContain('Nessuna connessione a Internet');
  });

  it('correctly identifies network errors via isNetworkError', () => {
    expect(isNetworkError(undefined)).toBe(false);
    expect(isNetworkError('')).toBe(false);
    expect(isNetworkError('FFmpeg error: disk full')).toBe(false);
    expect(isNetworkError('ConnectError: [Errno 11001] getaddrinfo failed')).toBe(true);
    expect(isNetworkError('Connection refused')).toBe(true);
    expect(isNetworkError('network is unreachable')).toBe(true);
    expect(isNetworkError('connessione assente')).toBe(true);
  });

  it('returns API-key timeout label when quota detail marks prompt timeout', () => {
    const label = errorLabel('quota_daily_limit_phase1', 'api_key_prompt_timeout');
    expect(label).toContain('Attesa chiave API scaduta');
    expect(label).toContain('riprendi quando vuoi');
  });

  it('returns raw string for unknown error key', () => {
    expect(errorLabel('some_unknown_error')).toBe('some_unknown_error');
  });

  it('maps autosave_failed to Italian human-readable message', () => {
    expect(errorLabel('autosave_failed')).toContain('salvataggio sessione fallito');
  });

  it('returns raw key for boundary_ai_failed (no Python emitter, no mapping)', () => {
    expect(errorLabel('boundary_ai_failed')).toBe('boundary_ai_failed');
  });

  it('maps session_collision to Italian human-readable message mentioning Impostazioni', () => {
    const label = errorLabel('session_collision');
    expect(label).toContain('sbobina');
    expect(label).toContain('Impostazioni');
  });

  it('maps regenerate_prompt_timeout to a retry-friendly Italian message', () => {
    const label = errorLabel('regenerate_prompt_timeout');
    expect(label).toContain('Nessuna scelta');
    expect(label).toContain('Riprendi');
  });
});

describe('formatSize', () => {
  it('formats bytes to KB', () => {
    expect(formatSize(512)).toBe('1 KB');
  });

  it('formats bytes to MB', () => {
    expect(formatSize(1024 * 1024 * 2.5)).toBe('2.5 MB');
  });

  it('formats bytes to GB', () => {
    expect(formatSize(1024 * 1024 * 1024 * 1.2)).toBe('1.2 GB');
  });
});

describe('formatDuration', () => {
  it('returns fallback for 0 seconds', () => {
    expect(formatDuration(0, 'N/A')).toBe('N/A');
  });

  it('formats seconds only', () => {
    expect(formatDuration(45)).toBe('45s');
  });

  it('formats minutes and seconds', () => {
    expect(formatDuration(90)).toBe('1m 30s');
  });

  it('formats hours and minutes', () => {
    expect(formatDuration(3661)).toBe('1h 1m');
  });
});

describe('formatRelativeTime', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:00:00'));
  });

  it('returns "adesso" for very recent', () => {
    expect(formatRelativeTime(Date.now() - 30_000)).toBe('adesso');
  });

  it('returns minutes ago', () => {
    expect(formatRelativeTime(Date.now() - 5 * 60_000)).toBe('5 minuti fa');
  });

  it('returns singular minute for 1 minute ago', () => {
    expect(formatRelativeTime(Date.now() - 61_000)).toBe('1 minuto fa');
  });

  it('returns hours ago', () => {
    expect(formatRelativeTime(Date.now() - 2 * 3600_000)).toBe('2 ore fa');
  });

  it('returns singular for 1 hour ago', () => {
    expect(formatRelativeTime(Date.now() - 3600_000 - 1000)).toBe('1 ora fa');
  });

  it('returns "ieri" for yesterday', () => {
    expect(formatRelativeTime(Date.now() - 25 * 3600_000)).toBe('ieri');
  });

  it('returns days ago for 2-6 days', () => {
    expect(formatRelativeTime(Date.now() - 3 * 24 * 3600_000)).toBe('3 giorni fa');
  });

  it('returns formatted date for older timestamps', () => {
    const old = new Date('2025-11-15').getTime();
    expect(formatRelativeTime(old)).toMatch(/nov|15/i);
  });
});

describe('shortModelName', () => {
  it('returns empty for empty string', () => {
    expect(shortModelName('')).toBe('');
  });

  it('strips models/ prefix', () => {
    expect(shortModelName('models/gemini-2.5-flash')).toBe('2.5-flash');
  });

  it('strips gemini- prefix', () => {
    expect(shortModelName('gemini-2.5-flash')).toBe('2.5-flash');
  });

  it('returns original for non-gemini model', () => {
    expect(shortModelName('claude-3')).toBe('claude-3');
  });
});

describe('readFileAsDataUrl', () => {
  it('resolves on success', async () => {
    const mockResult = 'data:image/png;base64,abc';
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      result = mockResult;
      onload: (() => void) | null = null;
      readAsDataURL() {
        if (this.onload) this.onload();
      }
    };

    try {
      const file = new Blob([]) as File;
      const res = await readFileAsDataUrl(file);
      expect(res).toBe(mockResult);
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
    }
  });

  it('rejects on error', async () => {
    const mockError = new Error('read error');
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      error = mockError;
      onerror: (() => void) | null = null;
      readAsDataURL() {
        if (this.onerror) this.onerror();
      }
    };

    try {
      const file = new Blob([]) as File;
      await expect(readFileAsDataUrl(file)).rejects.toThrow('read error');
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
    }
  });
});

describe('calculateOptimalDimensions', () => {
  it('returns original dimensions when within max bounds', () => {
    expect(calculateOptimalDimensions(800, 600, 1600, 1600)).toEqual({ width: 800, height: 600 });
  });

  it('scales down proportionally when width exceeds maxWidth', () => {
    expect(calculateOptimalDimensions(3200, 1600, 1600, 1600)).toEqual({ width: 1600, height: 800 });
  });

  it('scales down proportionally when height exceeds maxHeight', () => {
    expect(calculateOptimalDimensions(1000, 3000, 1600, 1600)).toEqual({ width: 533, height: 1600 });
  });

  it('scales down proportionally when both dimensions exceed max bounds', () => {
    expect(calculateOptimalDimensions(4000, 3000, 1600, 1600)).toEqual({ width: 1600, height: 1200 });
  });

  it('handles edge case of 0 or negative dimensions safely', () => {
    expect(calculateOptimalDimensions(0, 0)).toEqual({ width: 1, height: 1 });
    expect(calculateOptimalDimensions(-10, -20)).toEqual({ width: 1, height: 1 });
  });
});

describe('readAndOptimizeImageAsDataUrl (node environment)', () => {
  it('returns rawDataUrl safely in environment without document/canvas', async () => {
    const mockRawResult = 'data:image/png;base64,originalrawdata';
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      result = mockRawResult;
      onload: (() => void) | null = null;
      readAsDataURL() {
        if (this.onload) this.onload();
      }
    };

    try {
      const file = new File(['pngdata'], 'photo.png', { type: 'image/png' });
      const res = await readAndOptimizeImageAsDataUrl(file);
      expect(res).toBe(mockRawResult);
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
    }
  });

  it('rejects on FileReader error in node environment', async () => {
    const mockError = new Error('read error');
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      error = mockError;
      onerror: (() => void) | null = null;
      readAsDataURL() {
        if (this.onerror) this.onerror();
      }
    };

    try {
      const file = new File(['data'], 'photo.png', { type: 'image/png' });
      await expect(readAndOptimizeImageAsDataUrl(file)).rejects.toThrow('read error');
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
    }
  });
});

describe('model sorting and display names', () => {
  it('correctly maps model display names', () => {
    expect(getModelDisplayName('gemini-2.5-flash')).toBe('Gemini 2.5 Flash');
    expect(getModelDisplayName('gemini-3.5-flash')).toBe('Gemini 3.5 Flash');
    expect(getModelDisplayName('gemini-3.6-flash')).toBe('Gemini 3.6 Flash');
    expect(getModelDisplayName('gemini-3.7-flash')).toBe('Gemini 3.7 Flash');
    expect(getModelDisplayName('gemini-3.8-flash')).toBe('Gemini 3.8 Flash');
    expect(getModelDisplayName('unknown-model')).toBe('unknown-model');
  });

  it('sorts models in chronological version order', () => {
    const unordered = [
      'gemini-3.8-flash',
      'gemini-2.5-flash',
      'gemini-3.5-flash',
      'gemini-3.7-flash',
      'gemini-3.6-flash',
    ];
    const sorted = sortModelsByVersion(unordered);
    expect(sorted).toEqual([
      'gemini-2.5-flash',
      'gemini-3.5-flash',
      'gemini-3.6-flash',
      'gemini-3.7-flash',
      'gemini-3.8-flash',
    ]);
  });

  it('sorts objects with id property', () => {
    const objects = [
      { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' },
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
      { id: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
    ];
    const sorted = sortModelsByVersion(objects);
    expect(sorted.map(m => m.id)).toEqual([
      'gemini-2.5-flash',
      'gemini-3.5-flash',
      'gemini-3.8-flash',
    ]);
  });

  it('defines MODEL_ORDER in expected version order', () => {
    expect(MODEL_ORDER).toEqual([
      'gemini-2.5-flash',
      'gemini-3.5-flash',
      'gemini-3.6-flash',
      'gemini-3.7-flash',
      'gemini-3.8-flash',
    ]);
  });
});

describe('compareVersions', () => {
  it('correctly compares semantic versions with or without v prefix', () => {
    expect(compareVersions('v2.6.0', 'v2.5.1')).toBeGreaterThan(0);
    expect(compareVersions('2.6.0', '2.6.0')).toBe(0);
    expect(compareVersions('v2.5.0', 'v2.6.0')).toBeLessThan(0);
    expect(compareVersions('v2.6.0', '2.6.0')).toBe(0);
  });

  it('handles major, minor, and patch differences', () => {
    expect(compareVersions('3.0.0', '2.9.9')).toBeGreaterThan(0);
    expect(compareVersions('2.6.1', '2.6.0')).toBeGreaterThan(0);
    expect(compareVersions('2.6.0', '2.6.1')).toBeLessThan(0);
  });

  it('handles empty or malformed strings gracefully', () => {
    expect(compareVersions('', '')).toBe(0);
    expect(compareVersions('v1', 'v1.0.0')).toBe(0);
  });
});
