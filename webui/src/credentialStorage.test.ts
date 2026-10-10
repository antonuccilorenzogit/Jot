import { describe, expect, it } from 'vitest';
import { credentialStorageWarning } from './credentialStorage';

describe('credential storage warnings', () => {
  it('keeps protected and absent credentials quiet', () => {
    expect(credentialStorageWarning()).toBe('');
    expect(credentialStorageWarning({ primary: 'protected', fallback: 'absent' })).toBe('');
  });
  it('explains restart behavior for process-only fallback credentials', () => {
    const warning = credentialStorageWarning({ primary: 'protected', fallback: 'session_only' });
    expect(warning).toContain('solo per questa sessione');
    expect(warning).toContain('ultime credenziali salvate');
    expect(warning).not.toContain('in chiaro');
  });
  it('retains the warning about old plaintext beneath a temporary replacement', () => {
    const warning = credentialStorageWarning({ primary: 'session_only', fallback: 'absent' }, true);
    expect(warning).toContain('solo per questa sessione');
    expect(warning).toContain('in chiaro');
  });
  it('reports both temporary changes and existing plaintext when groups differ', () => {
    const warning = credentialStorageWarning({ primary: 'session_only', fallback: 'legacy_plaintext' });
    expect(warning).toContain('al riavvio');
    expect(warning).toContain('in chiaro');
  });
});
