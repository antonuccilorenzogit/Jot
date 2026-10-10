import { useCallback, useEffect, useRef, useState } from 'react';
import { APP_NAME } from '../branding';

export function useConsole() {
  const [consoleLogs, setConsoleLogs] = useState<string[]>([
    `[${new Date().toLocaleTimeString()}] ${APP_NAME} avviato.`,
  ]);
  const pendingLogsRef = useRef<string[]>([]);
  const logRafRef = useRef<number | null>(null);

  const appendConsole = useCallback((msg: string) => {
    pendingLogsRef.current.push(`[${new Date().toLocaleTimeString()}] ${msg}`);
    if (logRafRef.current === null) {
      logRafRef.current = requestAnimationFrame(() => {
        logRafRef.current = null;
        const batch = pendingLogsRef.current.splice(0);
        setConsoleLogs(prev => {
          const next = prev.length + batch.length > 300
            ? [...prev, ...batch].slice(-300)
            : [...prev, ...batch];
          return next;
        });
      });
    }
  }, []);

  // Cleanup RAF on unmount to prevent setState on unmounted component
  useEffect(() => {
    return () => {
      if (logRafRef.current !== null) {
        cancelAnimationFrame(logRafRef.current);
        logRafRef.current = null;
      }
    };
  }, []);

  return { consoleLogs, appendConsole };
}
