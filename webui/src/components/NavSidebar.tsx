import { memo, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { motion } from 'motion/react';
import { Bell, Moon, SlidersHorizontal, Sun, Terminal } from 'lucide-react';
import type { AppStatus } from '../appState';
import type { QuotaSnapshot } from '../bridge';
import { Wordmark } from './brand/Wordmark';
import { MASCOT } from './brand/mascot';
import { STORAGE_KEYS } from '../storageKeys';

export type ActivePage = 'queue' | 'archive';

interface NavSidebarProps {
  activePage: ActivePage;
  setActivePage: (page: ActivePage) => void;
  apiReady: boolean;
  bridgeDelayed: boolean;
  hasApiKey: boolean;
  isApiKeyValid: boolean;
  appState: AppStatus;
  themeMode: 'light' | 'dark';
  setThemeMode: Dispatch<SetStateAction<'light' | 'dark'>>;
  showConsole: boolean;
  setShowConsole: (v: boolean) => void;
  setIsSettingsOpen: (v: boolean) => void;
  hasPendingUpdate: boolean;
  consoleDisabled: boolean;
  unreadNotificationsCount: number;
  isNotificationsOpen: boolean;
  setIsNotificationsOpen: Dispatch<SetStateAction<boolean>>;
  shakeBell: boolean;
  /** Lessons waiting or running, shown next to "Lezioni". */
  queueCount?: number;
  /** Requests of today: always shown in the top bar. */
  quota?: QuotaSnapshot | null;
}

const bellVariants = {
  shake: {
    rotate: [0, -15, 15, -15, 15, -10, 10, -5, 5, 0],
    transition: { duration: 0.5, ease: 'easeInOut' as const },
  },
  idle: { rotate: 0 },
};

/** Top bar: brand on the left, two destinations and a few round buttons on the right. */
export const NavSidebar = memo(function NavSidebar({
  activePage, setActivePage,
  apiReady, bridgeDelayed, hasApiKey, isApiKeyValid, appState,
  themeMode, setThemeMode,
  showConsole, setShowConsole,
  setIsSettingsOpen,
  hasPendingUpdate,
  consoleDisabled,
  unreadNotificationsCount,
  isNotificationsOpen,
  setIsNotificationsOpen,
  shakeBell,
  queueCount = 0,
  quota = null,
}: NavSidebarProps) {
  const apiStatus = !apiReady
    ? (bridgeDelayed ? 'error' : 'warning')
    : !hasApiKey ? 'muted'
    : !isApiKeyValid ? 'warning'
    : 'ok';

  const apiStatusLabel = !apiReady
    ? (bridgeDelayed ? 'Bridge in ritardo' : 'Connessione…')
    : !hasApiKey ? 'Configura API'
    : !isApiKeyValid ? 'Chiave non valida'
    : 'API pronta';

  const consoleUnavailable = !hasApiKey || !isApiKeyValid || consoleDisabled;

  return (
    <header className="app-topbar">
      <div className="app-brand">
        <img src={MASCOT.wave} alt="" className="brand-mascot" draggable={false} />
        <Wordmark />
        <span className={`api-dot is-${apiStatus}${appState === 'processing' ? ' is-live' : ''}`} aria-label={apiStatusLabel} title={apiStatusLabel} role="img" />
      </div>

      <nav className="app-nav" aria-label="Navigazione">
        <button
          type="button"
          className={`sidebar-nav-item topbar-link${activePage === 'queue' ? ' is-active' : ''}`}
          aria-current={activePage === 'queue' ? 'page' : undefined}
          aria-label="Lezioni"
          onClick={() => setActivePage('queue')}
        >
          Lezioni
          {queueCount > 0 && <span className="topbar-count">· {queueCount}</span>}
          {appState === 'processing' && <span className="topbar-live" aria-hidden="true" />}
        </button>
        <button
          type="button"
          className={`sidebar-nav-item topbar-link${activePage === 'archive' ? ' is-active' : ''}`}
          aria-current={activePage === 'archive' ? 'page' : undefined}
          aria-label="Archivio"
          onClick={() => setActivePage('archive')}
        >
          Archivio
        </button>

        {quota && <QuotaBox quota={quota} />}

        <span className="topbar-sep" aria-hidden="true" />

        <RoundButton
          label={unreadNotificationsCount > 0 ? `Notifiche (${unreadNotificationsCount})` : 'Notifiche'}
          ariaLabel="Apri notifiche"
          active={isNotificationsOpen}
          onClick={() => setIsNotificationsOpen(prev => !prev)}
          badge={unreadNotificationsCount > 0 ? 'alert' : undefined}
        >
          <motion.span variants={bellVariants} animate={shakeBell ? 'shake' : 'idle'} style={{ display: 'inline-flex' }}>
            <Bell size={17} strokeWidth={2.2} />
          </motion.span>
        </RoundButton>
        <RoundButton
          label={consoleUnavailable ? 'Console non disponibile' : 'Console'}
          ariaLabel="Mostra console"
          active={showConsole}
          disabled={consoleUnavailable}
          onClick={() => {
            const next = !showConsole;
            setShowConsole(next);
            try { localStorage.setItem(STORAGE_KEYS.SHOW_CONSOLE, String(next)); } catch (_) { /* ignore */ }
          }}
        >
          <Terminal size={17} strokeWidth={2.2} />
        </RoundButton>
        <RoundButton
          label={themeMode === 'dark' ? 'Tema chiaro' : 'Tema scuro'}
          active={false}
          onClick={() => setThemeMode(prev => prev === 'dark' ? 'light' : 'dark')}
          className="theme-toggle-btn"
        >
          {themeMode === 'dark' ? <Sun size={17} strokeWidth={2.2} /> : <Moon size={17} strokeWidth={2.2} />}
        </RoundButton>
        <RoundButton
          label={hasPendingUpdate ? 'Impostazioni (Nuova versione)' : 'Impostazioni'}
          ariaLabel="Apri impostazioni"
          active={false}
          onClick={() => setIsSettingsOpen(true)}
          badge={hasPendingUpdate ? 'accent' : undefined}
        >
          <SlidersHorizontal size={17} strokeWidth={2.2} />
        </RoundButton>
      </nav>
    </header>
  );
});

function RoundButton({
  children, label, ariaLabel, active, onClick, disabled, badge, className = '',
}: {
  children: ReactNode;
  label: string;
  ariaLabel?: string;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  badge?: 'alert' | 'accent';
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel || label}
      title={label}
      disabled={disabled}
      aria-pressed={active || undefined}
      className={`round-button${active ? ' is-active' : ''} ${className}`.trim()}
    >
      {children}
      {badge && <span className={`round-button-badge is-${badge}`} aria-hidden="true" />}
    </button>
  );
}

/** Requests used today over all keys and models, and how many are left. */
function QuotaBox({ quota }: { quota: QuotaSnapshot }) {
  const share = quota.limit > 0 ? quota.remaining / quota.limit : 0;
  const tone = quota.remaining <= 0 ? 'is-empty' : share < 0.15 ? 'is-low' : '';
  const shortName = (m: string) => m.replace(/^gemini-/, '').replace(/-flash$/, ' Flash');
  const detail = [
    `${quota.used} richieste usate oggi su ${quota.limit} disponibili${quota.keys ? ` (${quota.keys} ${quota.keys === 1 ? 'chiave' : 'chiavi'})` : ''}.`,
    ...(quota.per_model || []).map(m => `${shortName(m.model)}: ne restano ${m.remaining} su ${m.limit}`),
    'Contano anche le richieste fallite (es. server occupato): Google le conta. Si azzerano alle 9.',
  ].join('\n');
  return (
    <span className={`topbar-quota ${tone}`.trim()} title={detail} aria-label={`Richieste di oggi: ${quota.used} usate su ${quota.limit}, ne restano ${quota.remaining}`}>
      <span className="topbar-quota-main">{quota.used}<span className="topbar-quota-of">/{quota.limit}</span></span>
      <span className="topbar-quota-left">restano {quota.remaining}</span>
    </span>
  );
}
