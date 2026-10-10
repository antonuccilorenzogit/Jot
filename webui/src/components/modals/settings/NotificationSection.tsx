import React from 'react';
import { Bell } from 'lucide-react';

interface NotificationSectionProps {
  notificationsEnabled: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
}

export const NotificationSection: React.FC<NotificationSectionProps> = React.memo(({
  notificationsEnabled,
  onChange,
  disabled = false,
}) => {

  return (
    <div className="flex items-center justify-between gap-4">
      <div className="space-y-1 min-w-0">
        <div className="flex items-center gap-2">
          <Bell className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">
            Notifiche di sistema
          </h3>
        </div>
        <p className="text-xs text-[var(--text-secondary)]">
          Avvisami al completamento dell&apos;elaborazione di ciascuna sbobina.
        </p>
      </div>

      <button
        type="button"
        role="switch"
        aria-checked={notificationsEnabled}
        onClick={() => onChange(!notificationsEnabled)}
        disabled={disabled}
        aria-label="Attiva o disattiva notifiche di sistema"
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-[var(--accent-ring)] disabled:opacity-50 disabled:cursor-not-allowed ${
          notificationsEnabled ? 'bg-[var(--accent-bg)]' : 'bg-[var(--bg-input)] ring-1 ring-[var(--border-strong)]'
        }`}
      >
        <span
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
            notificationsEnabled ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  );
});

NotificationSection.displayName = 'NotificationSection';
