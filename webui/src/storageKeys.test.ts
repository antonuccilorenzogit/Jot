import { describe, expect, it } from 'vitest';
import { STORAGE_KEYS } from './storageKeys';

describe('STORAGE_KEYS', () => {
  it('contains expected unique keys', () => {
    const values = Object.values(STORAGE_KEYS);
    const uniqueValues = new Set(values);
    expect(values.length).toBe(uniqueValues.size);
    expect(STORAGE_KEYS.SHOW_CONSOLE).toBe('show_console');
    expect(STORAGE_KEYS.AUTO_CONTINUE).toBe('auto_continue');
    expect(STORAGE_KEYS.NOTIFICATIONS_ENABLED).toBe('notifications_enabled');
  });
});
