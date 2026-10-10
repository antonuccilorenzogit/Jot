declare global {
  interface Window {
    elDesktopStartup?: {
      validate: (version: string) => boolean;
      settingsStarted: () => Promise<boolean>;
      ready: () => Promise<boolean>;
    };
  }
}

export function validateDesktopBuild(version: string): void {
  if (document.querySelector('meta[name="jot-startup"]') && !window.elDesktopStartup) {
    throw new Error('Il controllo di avvio dell’interfaccia non è stato caricato.');
  }
  if (window.elDesktopStartup && !window.elDesktopStartup.validate(version)) {
    throw new Error('La versione dell’interfaccia non corrisponde alla build avviata.');
  }
}

export async function beginDesktopSettingsLoad(): Promise<void> {
  if (window.elDesktopStartup && !await window.elDesktopStartup.settingsStarted()) {
    throw new Error('Avvio del caricamento delle impostazioni non confermato.');
  }
}

export async function completeDesktopStartup(): Promise<void> {
  if (window.elDesktopStartup && !await window.elDesktopStartup.ready()) {
    throw new Error('Verifica del collegamento al motore Python non riuscita.');
  }
}
