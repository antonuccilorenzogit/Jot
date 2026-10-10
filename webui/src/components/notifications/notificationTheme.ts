import type { NotificationMessage } from '../NotificationDropdown';

export interface CaretStyle {
  fill: string;
  stroke: string;
}

export function getCategoryLabel(category: NotificationMessage['category']) {
  switch (category) {
    case 'processing':
      return 'Elaborazione';
    case 'update':
      return 'Aggiornamento';
    case 'system':
    default:
      return 'Sistema';
  }
}

export function getItemBackground(
  type: NotificationMessage['type'],
  category: NotificationMessage['category']
) {
  if (category === 'update' || type === 'info') {
    return 'var(--accent-subtle)';
  }

  switch (type) {
    case 'success':
      return 'var(--success-subtle)';
    case 'warning':
      return 'var(--warning-subtle)';
    case 'error':
      return 'var(--error-subtle)';
    default:
      return 'transparent';
  }
}

export function getCategoryBadgeStyle(
  category: NotificationMessage['category'],
  type: NotificationMessage['type']
) {
  if (category === 'update' || type === 'info') {
    return {
      background: 'var(--accent-subtle)',
      color: 'var(--accent-text)',
    };
  }
  switch (type) {
    case 'success':
      return {
        background: 'var(--success-subtle)',
        color: 'var(--success-text)',
      };
    case 'warning':
      return {
        background: 'var(--warning-subtle)',
        color: 'var(--warning-text)',
      };
    case 'error':
      return {
        background: 'var(--error-subtle)',
        color: 'var(--error-text)',
      };
    default:
      return {
        background: 'var(--border-subtle)',
        color: 'var(--text-muted)',
      };
  }
}

export function getActionColor(
  category: NotificationMessage['category'],
  type: NotificationMessage['type']
) {
  if (category === 'update' || type === 'info') {
    return 'var(--accent-text)';
  }
  switch (type) {
    case 'warning':
      return 'var(--warning-text)';
    case 'error':
      return 'var(--error-text)';
    case 'success':
    default:
      return 'var(--accent-text)';
  }
}

export function getCaretStyle(
  type?: NotificationMessage['type'],
  category?: NotificationMessage['category']
): CaretStyle {
  if (category === 'update' || type === 'info') {
    return {
      fill: 'url(#caret-grad-info)',
      stroke: 'color-mix(in srgb, var(--accent-bg) 14%, var(--bg-elevated, #ffffff))',
    };
  }
  switch (type) {
    case 'success':
      return {
        fill: 'url(#caret-grad-success)',
        stroke: 'color-mix(in srgb, var(--success-bg) 14%, var(--bg-elevated, #ffffff))',
      };
    case 'warning':
      return {
        fill: 'url(#caret-grad-warning)',
        stroke: 'color-mix(in srgb, var(--warning-bg) 14%, var(--bg-elevated, #ffffff))',
      };
    case 'error':
      return {
        fill: 'url(#caret-grad-error)',
        stroke: 'color-mix(in srgb, var(--error-bg) 14%, var(--bg-elevated, #ffffff))',
      };
    default:
      return {
        fill: 'var(--bg-elevated, #ffffff)',
        stroke: 'var(--bg-elevated, #ffffff)',
      };
  }
}
