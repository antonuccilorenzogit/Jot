import React, { useState } from 'react';
import { motion } from 'motion/react';
import {
  BellOff,
  CheckCheck,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { NotificationItem } from './notifications/NotificationItem';
import { useNotificationCaret } from './notifications/useNotificationCaret';

export interface NotificationAction {
  label: string;
  type: 'retry_failed_revision_blocks' | 'install_update' | 'open_github' | 'open_settings';
  data?: unknown;
  loadingLabel?: string;
  errorSuffix?: string;
}

export interface NotificationMessage {
  id: string;
  title: string;
  message: string;
  type: 'info' | 'warning' | 'error' | 'success';
  category: 'processing' | 'update' | 'system';
  timestamp: number;
  read: boolean;
  persistent?: boolean;
  dedupeKey?: string;
  action?: NotificationAction & {
    onAction: () => Promise<void>;
  };
  onDismiss?: () => void;
}

export interface NotificationDropdownProps {
  isOpen: boolean;
  onClose: () => void;
  notifications: NotificationMessage[];
  onMarkAsRead: (id: string) => void;
  onMarkAllAsRead: () => void;
  onDelete: (id: string) => void;
  onClearAll?: () => void;
  onNotificationClick?: (notification: NotificationMessage) => void;
  align?: 'left' | 'right';
  leftOffset?: number;
  valign?: 'top' | 'bottom';
  bottomOffset?: number;
}

export function NotificationDropdown({
  isOpen,
  onClose,
  notifications,
  onMarkAsRead,
  onMarkAllAsRead,
  onDelete,
  onClearAll,
  onNotificationClick,
  align = 'right',
  leftOffset = 72,
  valign = 'top',
  bottomOffset = 16,
}: NotificationDropdownProps) {
  const [activeTab, setActiveTab] = useState<'all' | 'unread'>('all');
  const unreadCount = notifications.filter((n) => !n.read).length;

  const filteredNotifications = [...notifications]
    .sort((a, b) => b.timestamp - a.timestamp)
    .filter((n) => {
      if (activeTab === 'unread') return !n.read;
      return true;
    });

  const dynamicHeightStyle =
    valign === 'bottom'
      ? `clamp(320px, 52vh, min(480px, calc(100vh - ${bottomOffset + 16}px)))`
      : 'clamp(320px, 52vh, min(480px, calc(100vh - 88px)))';

  const {
    caretRef,
    scrollContainerRef,
    caretStyle,
    updateCaretNotification,
  } = useNotificationCaret({
    isOpen,
    align,
    valign,
    activeTab,
    filteredNotifications,
  });

  return (
    <>
      {/* Backdrop to close on click outside */}
      <motion.div
        key="notification-backdrop"
        initial={false}
        animate={{
          opacity: isOpen ? 1 : 0,
          pointerEvents: isOpen ? 'auto' : 'none',
        }}
        transition={{ duration: 0.12 }}
        onClick={onClose}
        className="fixed inset-0 z-40"
        style={{ background: 'transparent' }}
      />

      {/* Popover Dropdown Container with sleek, subtle ease-out animation */}
      <motion.div
        key="notification-popover"
        role="dialog"
        aria-label="Notifiche"
        initial={false}
        animate={{
          opacity: isOpen ? 1 : 0,
          scale: isOpen ? 1 : 0.98,
          y: isOpen ? 0 : (valign === 'bottom' ? 4 : -4),
          pointerEvents: isOpen ? 'auto' : 'none',
        }}
        transition={{
          duration: isOpen ? 0.14 : 0.1,
          ease: isOpen ? [0.16, 1, 0.3, 1] : 'easeIn',
        }}
        className={`fixed z-50 flex flex-col origin-bottom-left ${
          isOpen ? 'pointer-events-auto' : 'pointer-events-none'
        }`}
        style={{
          transformOrigin: `${valign === 'bottom' ? 'bottom' : 'top'} ${align === 'left' ? 'left' : 'right'}`,
          width: 380,
          height: dynamicHeightStyle,
          maxHeight: `calc(100vh - ${valign === 'bottom' ? bottomOffset + 16 : 88}px)`,
          top: valign === 'bottom' ? undefined : 76,
          bottom: valign === 'bottom' ? bottomOffset : undefined,
          left: align === 'left' ? leftOffset : undefined,
          right: align === 'right' ? 24 : undefined,
        }}
      >
        {/* Left pointer triangle pointing towards the sidebar trigger */}
        {align === 'left' && valign === 'bottom' && (
          <div
            ref={caretRef}
            className="absolute -left-[8px] pointer-events-none z-30 flex items-center"
            style={{ bottom: 48 }}
          >
            <svg
              width="9"
              height="18"
              viewBox="0 0 9 18"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <defs>
                <linearGradient id="caret-grad-info" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="color-mix(in srgb, var(--accent-bg) 14%, var(--bg-elevated, #ffffff))" />
                  <stop offset="100%" stopColor="color-mix(in srgb, var(--accent-bg) 8%, var(--bg-elevated, #ffffff))" />
                </linearGradient>
                <linearGradient id="caret-grad-success" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="color-mix(in srgb, var(--success-bg) 14%, var(--bg-elevated, #ffffff))" />
                  <stop offset="100%" stopColor="color-mix(in srgb, var(--success-bg) 8%, var(--bg-elevated, #ffffff))" />
                </linearGradient>
                <linearGradient id="caret-grad-warning" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="color-mix(in srgb, var(--warning-bg) 14%, var(--bg-elevated, #ffffff))" />
                  <stop offset="100%" stopColor="color-mix(in srgb, var(--warning-bg) 8%, var(--bg-elevated, #ffffff))" />
                </linearGradient>
                <linearGradient id="caret-grad-error" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="color-mix(in srgb, var(--error-bg) 14%, var(--bg-elevated, #ffffff))" />
                  <stop offset="100%" stopColor="color-mix(in srgb, var(--error-bg) 8%, var(--bg-elevated, #ffffff))" />
                </linearGradient>
              </defs>
              <polygon
                points="8.5,0.5 0.5,9 8.5,17.5"
                fill={caretStyle.fill}
              />
              <path
                d="M 8.5 0.5 L 0.5 9 L 8.5 17.5"
                stroke="var(--card-queued-border, var(--border-default))"
                strokeWidth="1"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <line
                x1="8.5"
                y1="1"
                x2="8.5"
                y2="17"
                stroke={caretStyle.stroke}
                strokeWidth="2"
              />
            </svg>
          </div>
        )}

        {/* Inner bordered panel matching design system .notification-dropdown-panel */}
        <div
          className="notification-dropdown-panel relative flex flex-col flex-1 overflow-hidden"
        >
          {/* Header Row: Title & Action Buttons */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)]">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold tracking-tight text-[var(--text-primary)]">
                Notifiche
              </h3>
              {unreadCount > 0 && (
                <span
                  className="px-1.5 py-0.2 text-[10px] rounded-full font-bold leading-tight"
                  style={{
                    background: 'var(--accent-subtle)',
                    color: 'var(--accent-text)',
                  }}
                >
                  {unreadCount}
                </span>
              )}
            </div>

            <div className="flex items-center gap-1">
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={onMarkAllAsRead}
                  className="p-1 rounded-md transition-colors hover:bg-[var(--accent-subtle)] flex items-center justify-center text-[var(--accent-text)] hover:text-[var(--text-primary)]"
                  style={{
                    cursor: 'pointer',
                  }}
                  title="Segna tutte come lette"
                  aria-label="Segna come già lette"
                >
                  <CheckCheck className="w-4 h-4" />
                </button>
              )}
              {notifications.length > 0 && onClearAll && (
                <button
                  type="button"
                  onClick={onClearAll}
                  className="p-1 rounded-md transition-colors hover:bg-[var(--error-subtle)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--error-text)]"
                  style={{
                    cursor: 'pointer',
                  }}
                  title="Cancella tutte le notifiche"
                  aria-label="Cancella tutte le notifiche"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* Minimalist Sub-tabs: Tutte & Non lette with smooth layoutId indicator */}
          <div className="flex items-center gap-4 px-4 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
            <button
              type="button"
              onClick={() => setActiveTab('all')}
              className={`py-2 text-xs transition-colors relative flex items-center gap-1.5 ${
                activeTab === 'all'
                  ? 'font-medium text-[var(--text-primary)]'
                  : 'font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: '12px',
              }}
            >
              <span>Tutte</span>
              {activeTab === 'all' && (
                <motion.span
                  layoutId="activeNotificationTab"
                  className="absolute bottom-0 left-0 right-0 h-[2px] rounded-full"
                  style={{ background: 'var(--accent-text)' }}
                  transition={{ type: 'spring', stiffness: 500, damping: 35 }}
                />
              )}
            </button>

            <button
              type="button"
              onClick={() => setActiveTab('unread')}
              className={`py-2 text-xs transition-colors relative flex items-center gap-1.5 ${
                activeTab === 'unread'
                  ? 'font-medium text-[var(--text-primary)]'
                  : 'font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: '12px',
              }}
            >
              <span>Non lette</span>
              {unreadCount > 0 && (
                <span
                  className="px-1.5 py-0.2 text-[10px] rounded-md font-bold leading-tight"
                  style={{
                    background: 'var(--accent-subtle)',
                    color: 'var(--accent-text)',
                  }}
                >
                  {unreadCount}
                </span>
              )}
              {activeTab === 'unread' && (
                <motion.span
                  layoutId="activeNotificationTab"
                  className="absolute bottom-0 left-0 right-0 h-[2px] rounded-full"
                  style={{ background: 'var(--accent-text)' }}
                  transition={{ type: 'spring', stiffness: 500, damping: 35 }}
                />
              )}
            </button>
          </div>

          {/* Notification items list */}
          <div
            ref={scrollContainerRef}
            onScroll={updateCaretNotification}
            className="flex-1 overflow-y-auto flex flex-col scrollbar-thin"
          >
            {filteredNotifications.length === 0 ? (
              <div
                key={`empty-${activeTab}`}
                className="flex flex-col items-center justify-center gap-2.5 py-12 px-6 text-center h-full"
              >
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center"
                  style={{
                    background: 'var(--accent-subtle)',
                    color: 'var(--accent-text)',
                  }}
                >
                  {activeTab === 'unread' ? (
                    <Sparkles className="w-4 h-4" />
                  ) : (
                    <BellOff className="w-4 h-4 opacity-70" />
                  )}
                </div>
                <h4 className="text-xs font-semibold text-[var(--text-primary)]">
                  {activeTab === 'unread' ? 'Nessuna notifica non letta' : 'Nessuna notifica'}
                </h4>
                <p className="text-[11px] leading-relaxed text-[var(--text-muted)] max-w-[240px]">
                  {activeTab === 'unread'
                    ? 'Tutte le notifiche sono state lette.'
                    : 'Qui troverai gli avvisi su elaborazioni, aggiornamenti e stato del sistema.'}
                </p>
              </div>
            ) : (
              filteredNotifications.map((n) => (
                <NotificationItem
                  key={n.id}
                  notification={n}
                  onMarkAsRead={onMarkAsRead}
                  onDelete={onDelete}
                  onNotificationClick={onNotificationClick}
                />
              ))
            )}
          </div>
        </div>
      </motion.div>
    </>
  );
}
