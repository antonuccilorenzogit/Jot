import { useCallback, useRef, useState } from 'react';
import type { PywebviewApi, UpdateDownloadProgressPayload } from '../bridge';

export type UpdateInstallStatus = UpdateDownloadProgressPayload['status'] | 'idle';

export type UpdateInstallState = {
  version: string | null;
  status: UpdateInstallStatus;
  bytesDone: number;
  bytesTotal: number;
  error: string | null;
};

export const UPDATE_INSTALL_IDLE: UpdateInstallState = {
  version: null,
  status: 'idle',
  bytesDone: 0,
  bytesTotal: 0,
  error: null,
};

export function formatUpdateInstallError(error?: string): string {
  const raw = String(error || '').trim();
  if (raw === 'uac_denied') {
    return 'Installazione annullata: la richiesta UAC è stata rifiutata. L’app resta aperta; puoi riprovare o scaricare manualmente da GitHub.';
  }
  if (raw === 'permission_denied') {
    return 'Permesso negato per /Applications: scarica il DMG da GitHub e trascina l’app in /Applications con Finder.';
  }
  if (/checksum|integrit/i.test(raw)) {
    return raw || 'Verifica integrità fallita: scarica manualmente da GitHub.';
  }
  return raw || 'Aggiornamento fallito.';
}

export function formatUpdateInstallStatus(state: UpdateInstallState): string {
  if (state.status === 'downloading') {
    const percent = state.bytesTotal > 0 ? ` ${Math.round((state.bytesDone / state.bytesTotal) * 100)}%` : '';
    return `Download aggiornamento${percent}…`;
  }
  if (state.status === 'verifying') return 'Verifica integrità aggiornamento…';
  if (state.status === 'installing') return 'Installazione aggiornamento…';
  if (state.status === 'done') return 'Installer avviato. Segui le istruzioni per completare l’aggiornamento.';
  if (state.status === 'error') return `Aggiornamento non riuscito: ${state.error ?? 'errore sconosciuto'}`;
  return '';
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface UseUpdateInstallerOptions {
  latestVersion: string | null;
  appendConsole: (msg: string) => void;
  upsertNotification: (
    title: string,
    message: string,
    type: 'info' | 'warning' | 'error' | 'success',
    category: 'update' | 'system' | 'processing',
    options?: {
      persistent?: boolean;
      dedupeKey?: string;
      actionType?: 'retry_failed_revision_blocks' | 'install_update' | 'open_github' | 'open_settings';
      actionData?: unknown;
    },
  ) => void;
  removeNotificationByDedupeKey?: (dedupeKey: string) => void;
}

export function useUpdateInstaller({
  latestVersion,
  appendConsole,
  upsertNotification,
  removeNotificationByDedupeKey,
}: UseUpdateInstallerOptions) {
  const [updateInstallState, setUpdateInstallState] = useState<UpdateInstallState>(UPDATE_INSTALL_IDLE);
  const updateInstallStateRef = useRef<UpdateInstallState>(UPDATE_INSTALL_IDLE);
  const downloadCompletionRef = useRef<{ version: string; resolve: () => void; reject: (e: Error) => void } | null>(null);
  const updateInstallPromiseRef = useRef<Promise<void> | null>(null);

  const applyUpdateInstallState = useCallback((next: UpdateInstallState) => {
    updateInstallStateRef.current = next;
    setUpdateInstallState(next);
  }, []);

  const upsertUpdateInstallNotification = useCallback(
    (message: string, type: 'warning' | 'info', actionType?: 'install_update' | 'open_github', actionData?: unknown) => {
      upsertNotification(
        'Installazione aggiornamento',
        message,
        type,
        'update',
        {
          persistent: true,
          dedupeKey: 'update-install',
          actionType,
          actionData,
        },
      );
    },
    [upsertNotification],
  );

  const installUpdate = useCallback(
    async (version: string) => {
      if (updateInstallPromiseRef.current && downloadCompletionRef.current?.version === version) {
        return updateInstallPromiseRef.current;
      }
      const api = window.pywebview?.api;
      if (!api?.download_and_install_update) {
        const message = 'Bridge aggiornamenti non disponibile.';
        applyUpdateInstallState({ version, status: 'error', bytesDone: 0, bytesTotal: 0, error: message });
        upsertUpdateInstallNotification(`Aggiornamento non riuscito: ${message}`, 'warning', 'open_github');
        throw new Error(message);
      }

      applyUpdateInstallState({ version, status: 'downloading', bytesDone: 0, bytesTotal: 0, error: null });
      removeNotificationByDedupeKey?.('update-available');
      upsertUpdateInstallNotification('Download aggiornamento…', 'info');

      const completion = new Promise<void>((resolve, reject) => {
        downloadCompletionRef.current = { version, resolve, reject };
      });
      const trackedCompletion = completion.finally(() => {
        updateInstallPromiseRef.current = null;
      });
      updateInstallPromiseRef.current = trackedCompletion;

      let result: Awaited<ReturnType<NonNullable<PywebviewApi['download_and_install_update']>>>;
      try {
        result = await api.download_and_install_update(version);
      } catch (error: unknown) {
        const message = formatUpdateInstallError(getErrorMessage(error));
        if (downloadCompletionRef.current?.version === version) downloadCompletionRef.current = null;
        updateInstallPromiseRef.current = null;
        appendConsole(`❌ Aggiornamento fallito: ${message}`);
        applyUpdateInstallState({
          version,
          status: 'error',
          bytesDone: updateInstallStateRef.current.version === version ? updateInstallStateRef.current.bytesDone : 0,
          bytesTotal: updateInstallStateRef.current.version === version ? updateInstallStateRef.current.bytesTotal : 0,
          error: message,
        });
        upsertUpdateInstallNotification(`Aggiornamento non riuscito: ${message}`, 'warning', 'open_github');
        throw new Error(message);
      }
      if (!result?.ok) {
        const message = formatUpdateInstallError(result?.error);
        downloadCompletionRef.current = null;
        updateInstallPromiseRef.current = null;
        applyUpdateInstallState({ version, status: 'error', bytesDone: 0, bytesTotal: 0, error: message });
        appendConsole(`❌ Aggiornamento fallito: ${message}`);
        upsertUpdateInstallNotification(`Aggiornamento non riuscito: ${message}`, 'warning', 'open_github');
        throw new Error(message);
      }
      return trackedCompletion;
    },
    [appendConsole, applyUpdateInstallState, removeNotificationByDedupeKey, upsertUpdateInstallNotification],
  );

  const handleDownloadProgress = useCallback(
    (data: UpdateDownloadProgressPayload) => {
      const currentDownload = downloadCompletionRef.current;
      const version = currentDownload?.version ?? updateInstallStateRef.current.version ?? latestVersion;
      const messageState: UpdateInstallState = {
        version,
        status: data.status,
        bytesDone: data.bytes_done,
        bytesTotal: data.bytes_total,
        error: data.status === 'error' ? formatUpdateInstallError(data.error) : null,
      };
      applyUpdateInstallState(messageState);
      if (data.status === 'done') {
        upsertUpdateInstallNotification(formatUpdateInstallStatus(messageState), 'info');
        currentDownload?.resolve();
        downloadCompletionRef.current = null;
      } else if (data.status === 'error') {
        const message = messageState.error ?? 'Errore sconosciuto';
        appendConsole(`❌ Aggiornamento fallito: ${message}`);
        upsertUpdateInstallNotification(formatUpdateInstallStatus(messageState), 'warning', 'open_github');
        currentDownload?.reject(new Error(message));
        downloadCompletionRef.current = null;
      } else {
        upsertUpdateInstallNotification(formatUpdateInstallStatus(messageState), 'info');
      }
    },
    [appendConsole, applyUpdateInstallState, latestVersion, upsertUpdateInstallNotification],
  );

  return {
    updateInstallState,
    updateInstallStateRef,
    installUpdate,
    handleDownloadProgress,
    applyUpdateInstallState,
  };
}
