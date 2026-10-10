import React, { useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Info,
  Loader2,
  Sparkles,
} from 'lucide-react';
import type { NotificationMessage } from '../NotificationDropdown';
import { formatRelativeTime } from '../../utils';
import {
  getActionColor,
  getCategoryBadgeStyle,
  getCategoryLabel,
  getItemBackground,
} from './notificationTheme';

export interface NotificationItemProps {
  notification: NotificationMessage;
  onMarkAsRead: (id: string) => void;
  onDelete: (id: string) => void;
  onNotificationClick?: (notification: NotificationMessage) => void;
}

export function NotificationItem({
  notification,
  onMarkAsRead,
  onDelete,
  onNotificationClick,
}: NotificationItemProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const handleAction = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isLoading || !notification.action) return;
    setIsLoading(true);
    setErrorText(null);
    try {
      await notification.action.onAction();
      notification.onDismiss?.();
      onDelete(notification.id);
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : String(err));
      setIsLoading(false);
    }
  };

  const getIconBadge = () => {
    if (notification.category === 'update') {
      return (
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
          style={{
            background: 'var(--accent-subtle)',
            color: 'var(--accent-text)',
          }}
        >
          <Sparkles className="w-4 h-4" />
        </div>
      );
    }

    if (notification.type === 'info') {
      return (
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
          style={{
            background: 'var(--accent-subtle)',
            color: 'var(--accent-text)',
          }}
        >
          <Info className="w-4 h-4" />
        </div>
      );
    }

    switch (notification.type) {
      case 'success':
        return (
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
            style={{
              background: 'var(--success-subtle)',
              color: 'var(--success-text)',
            }}
          >
            <CheckCircle2 className="w-4 h-4" />
          </div>
        );
      case 'warning':
        return (
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
            style={{
              background: 'var(--warning-subtle)',
              color: 'var(--warning-text)',
            }}
          >
            <AlertTriangle className="w-4 h-4" />
          </div>
        );
      case 'error':
        return (
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
            style={{
              background: 'var(--error-subtle)',
              color: 'var(--error-text)',
            }}
          >
            <AlertCircle className="w-4 h-4" />
          </div>
        );
      default:
        return (
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
            style={{
              background: 'var(--accent-subtle)',
              color: 'var(--accent-text)',
            }}
          >
            <Info className="w-4 h-4" />
          </div>
        );
    }
  };

  const actionColor = getActionColor(notification.category, notification.type);

  return (
    <div
      data-notification-id={notification.id}
      onClick={() => {
        if (!notification.read) onMarkAsRead(notification.id);
        onNotificationClick?.(notification);
      }}
      className={`notification-item ${!notification.read ? 'is-unread ' : ''}group relative flex items-start gap-3 px-4 py-3 border-b border-[var(--border-subtle)] last:border-b-0 cursor-pointer transition-all duration-150 hover:brightness-[0.98] dark:hover:brightness-[1.08]`}
      style={{
        background: getItemBackground(notification.type, notification.category),
      }}
    >
      {/* Type icon in soft squircle badge */}
      {getIconBadge()}

      {/* Main content body */}
      <div className="flex flex-1 flex-col gap-1 min-w-0 pr-6">
        {/* Top line: unread dot + title + category */}
        <div className="flex items-center gap-1.5 min-w-0">
          {!notification.read && (
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0 animate-pulse"
              style={{
                background:
                  notification.category === 'update' || notification.type === 'info'
                    ? 'var(--accent-text)'
                    : notification.type === 'warning'
                    ? 'var(--warning-text)'
                    : notification.type === 'error'
                    ? 'var(--error-text)'
                    : 'var(--accent-text)',
              }}
              title="Non letta"
            />
          )}
          <h4 className="text-xs leading-snug truncate font-semibold text-[var(--text-primary)]">
            {notification.title}
          </h4>
          <span
            className="text-[9px] font-medium px-1.5 py-0.2 rounded shrink-0"
            style={getCategoryBadgeStyle(notification.category, notification.type)}
          >
            {getCategoryLabel(notification.category)}
          </span>
        </div>

        {/* Message body */}
        <p className="text-xs leading-relaxed break-words" style={{ color: 'var(--text-secondary)' }}>
          {notification.message}
        </p>

        {/* Inline error feedback if action failed */}
        {errorText && (
          <div className="flex items-center gap-1 text-[10px] mt-0.5" style={{ color: 'var(--error-text)' }}>
            <AlertCircle className="w-3 h-3 shrink-0" />
            <span>
              {errorText}
              {notification.action?.errorSuffix ? ` — ${notification.action.errorSuffix}` : ''}
            </span>
          </div>
        )}

        {/* Bottom line: Action link on Left, Timestamp aligned on Right */}
        <div className="flex items-center justify-between mt-1 text-[11px] gap-2">
          {notification.action ? (
            <button
              type="button"
              onClick={handleAction}
              disabled={isLoading}
              className="text-[11px] font-medium inline-flex items-center gap-1 hover:underline transition-all"
              style={{
                color: actionColor,
                background: 'none',
                border: 'none',
                padding: 0,
                cursor: isLoading ? 'default' : 'pointer',
                opacity: isLoading ? 0.7 : 1,
              }}
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-2.5 h-2.5 animate-spin" />
                  <span>{notification.action.loadingLabel ?? 'Caricamento…'}</span>
                </>
              ) : (
                <>
                  <span>{notification.action.label}</span>
                  <ArrowRight className="w-2.5 h-2.5 opacity-70" />
                </>
              )}
            </button>
          ) : (
            <div />
          )}

          {/* Timestamp aligned on the right */}
          <span className="text-[11px] shrink-0 ml-auto" style={{ color: 'var(--text-faint)' }}>
            {formatRelativeTime(notification.timestamp)}
          </span>
        </div>
      </div>

      {/* Quick Dismiss / Archive Button (hover) */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          notification.onDismiss?.();
          onDelete(notification.id);
        }}
        disabled={isLoading}
        className="absolute top-3 right-3 p-1 rounded-md opacity-0 group-hover:opacity-100 hover:bg-neutral-500/15 transition-all text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        title="Archivia"
        aria-label="Archivia notifica"
        style={{ cursor: isLoading ? 'default' : 'pointer' }}
      >
        <Check className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
