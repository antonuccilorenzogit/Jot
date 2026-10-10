/**
 * Centralized registry of all localStorage keys used across the webui application.
 */
export const STORAGE_KEYS = {
  SHOW_CONSOLE: 'show_console',
  AUTO_CONTINUE: 'auto_continue',
  NOTIFICATIONS_ENABLED: 'notifications_enabled',
  EDITOR_ZOOM: 'editor_zoom',
  HAS_SESSIONS_V1: 'jot.has_sessions.v1',
  EDITOR_SESSIONS_V1: 'jot.editor-sessions.v1',
  QUEUE_V1: 'jot.queue.v1',
  NOTIFICATIONS_V1: 'jot.notifications.v1',
  BROWSER_INSTANCE_V1: 'jot.browser-instance.v1',
  THEME_V1: 'jot.theme.v1',
  CONFIG_RECOVERY_PREFIX: 'jot.config-recovery-dismissed.v1:',
  LAST_SEEN_APP_VERSION_V1: 'jot.last-seen-app-version.v1',
} as const;

export type StorageKey = (typeof STORAGE_KEYS)[keyof typeof STORAGE_KEYS];
