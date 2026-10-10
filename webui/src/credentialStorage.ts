import type { CredentialStorage } from './bridge';

export function credentialStorageWarning(storage?: CredentialStorage, legacyPlaintext = false): string {
  const warnings: string[] = [];
  if (storage?.primary === 'session_only' || storage?.fallback === 'session_only') {
    warnings.push('La protezione del sistema non ha consentito di salvare tutte le credenziali. Le modifiche alle chiavi valgono solo per questa sessione; al riavvio saranno disponibili le ultime credenziali salvate.');
  }
  if (legacyPlaintext || storage?.primary === 'legacy_plaintext' || storage?.fallback === 'legacy_plaintext') {
    warnings.push('Credenziali presenti in chiaro nel file di configurazione. La migrazione protetta non è riuscita. Riprova il salvataggio quando la protezione del sistema è disponibile.');
  }
  return warnings.join(' ');
}
