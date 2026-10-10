import { memo, useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Copy } from 'lucide-react';
import type { AppStatus } from '../appState';

interface ConsolePanelProps {
  consoleLogs: string[];
  lastConsoleMessage: string;
  appState: AppStatus;
  isConsoleExpanded?: boolean;
  setIsConsoleExpanded?: (expanded: boolean | ((prev: boolean) => boolean)) => void;
}

export const ConsolePanel = memo(function ConsolePanel({
  consoleLogs,
  lastConsoleMessage,
  appState,
  isConsoleExpanded: propIsConsoleExpanded,
  setIsConsoleExpanded: propSetIsConsoleExpanded,
}: ConsolePanelProps) {
  const [localIsExpanded, setLocalIsExpanded] = useState(false);
  const isConsoleExpanded = propIsConsoleExpanded !== undefined ? propIsConsoleExpanded : localIsExpanded;
  const setIsConsoleExpanded = propSetIsConsoleExpanded !== undefined ? propSetIsConsoleExpanded : setLocalIsExpanded;

  const [isCopied, setIsCopied] = useState(false);
  const consoleScrollRef = useRef<HTMLDivElement>(null);
  const isMouseInConsoleRef = useRef(false);

  useEffect(() => {
    if (!isConsoleExpanded || isMouseInConsoleRef.current) return;
    const el = consoleScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [consoleLogs, isConsoleExpanded]);

  return (
    <div className="console-shell console-shell-subtle">
      <div className="px-5 py-3 flex items-center justify-between" style={{ background: 'var(--console-header)', borderBottom: '1px solid var(--console-border, var(--border-subtle))' }}>
        <h2 className="text-xs font-semibold uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--console-heading)' }}>
          <span className={`w-2 h-2 rounded-full ${appState === 'processing' ? 'animate-pulse' : ''}`} style={appState !== 'processing' ? { background: 'var(--console-heading)' } : { background: 'var(--processing-dot)' }} />
          Console
        </h2>
        <div className="flex items-center gap-1">
          {isConsoleExpanded && (
            <button
              onClick={() => {
                navigator.clipboard.writeText(consoleLogs.join('\n'));
                setIsCopied(true);
                setTimeout(() => setIsCopied(false), 2000);
              }}
              className="p-1.5 rounded-md hover:bg-[var(--border-subtle)] transition-colors"
              title={isCopied ? 'Copiato!' : 'Copia tutto'}
              style={{ color: isCopied ? 'var(--console-success, var(--success-text))' : 'var(--console-heading)', transition: 'color 0.2s' }}
            >
              {isCopied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          )}
          <button
            onClick={() => setIsConsoleExpanded(prev => !prev)}
            className="p-1.5 rounded-md hover:bg-[var(--border-subtle)] transition-colors"
            title={isConsoleExpanded ? 'Riduci' : 'Espandi'}
            style={{ color: 'var(--console-heading)' }}
          >
            <ChevronDown size={15} style={{ transform: isConsoleExpanded ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }} />
          </button>
        </div>
      </div>
      {isConsoleExpanded ? (
        <div
          ref={consoleScrollRef}
          className="console-scroll p-4 overflow-y-auto font-mono text-xs space-y-1 h-52 select-text"
          style={{ color: 'var(--console-text)', background: 'var(--console-bg)', whiteSpace: 'pre-wrap' }}
          onMouseEnter={() => { isMouseInConsoleRef.current = true; }}
          onMouseLeave={() => { isMouseInConsoleRef.current = false; }}
        >
          {consoleLogs.map((log, i) => {
            const color = log.includes('Errore') || log.includes('❌') || log.includes('[!]') || log.includes('Annullamento') ? 'var(--console-error, var(--error-text))'
              : log.includes('COMPLETATA') || log.includes('✅') ? 'var(--console-success, var(--success-text))'
              : log.includes('⚠') ? 'var(--console-warning, var(--warning-text))' : 'var(--console-text)';
            const match = log.match(/^\[\d{2}:\d{2}:\d{2}\]/);
            if (match) {
              const ts = match[0];
              const rest = log.slice(ts.length);
              return <div key={i}><span style={{ color: 'var(--console-muted, var(--text-muted))' }}>{ts}</span><span style={{ color }}>{rest}</span></div>;
            }
            return <div key={i} style={{ color }}>{log}</div>;
          })}
        </div>
      ) : (
        <div className="px-5 pt-3 pb-4 text-[13px] leading-5" style={{ color: 'var(--console-text)', background: 'var(--console-bg)' }}>
          {lastConsoleMessage}
        </div>
      )}
    </div>
  );
});
