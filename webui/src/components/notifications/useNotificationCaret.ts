import { useCallback, useEffect, useRef, useState } from 'react';
import type { NotificationMessage } from '../NotificationDropdown';
import { getCaretStyle } from './notificationTheme';

export interface UseNotificationCaretOptions {
  isOpen: boolean;
  align: 'left' | 'right';
  valign: 'top' | 'bottom';
  activeTab: 'all' | 'unread';
  filteredNotifications: NotificationMessage[];
}

export function useNotificationCaret({
  isOpen,
  align,
  valign,
  activeTab,
  filteredNotifications,
}: UseNotificationCaretOptions) {
  const [caretNotification, setCaretNotification] = useState<NotificationMessage | null>(null);
  const caretRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const updateCaretNotification = useCallback(() => {
    if (!isOpen || align !== 'left' || valign !== 'bottom') {
      setCaretNotification(null);
      return;
    }

    const caretEl = caretRef.current;
    const scrollEl = scrollContainerRef.current;
    if (!caretEl || !scrollEl) {
      setCaretNotification(null);
      return;
    }

    const caretRect = caretEl.getBoundingClientRect();
    const scrollRect = scrollEl.getBoundingClientRect();

    // Guard against unmounted/0-size elements in headless/test environments
    if (caretRect.height === 0 || scrollRect.height === 0) {
      setCaretNotification(null);
      return;
    }

    const caretCenterY = caretRect.top + caretRect.height / 2;

    // If caret vertical position is outside the scroll container viewport
    if (caretCenterY < scrollRect.top || caretCenterY > scrollRect.bottom) {
      setCaretNotification(null);
      return;
    }

    const itemEls = scrollEl.querySelectorAll<HTMLElement>('[data-notification-id]');
    let found: NotificationMessage | null = null;
    for (let i = 0; i < itemEls.length; i++) {
      const itemEl = itemEls[i];
      const rect = itemEl.getBoundingClientRect();
      // Check if caret center Y falls within this notification item's visible bounds
      if (caretCenterY >= rect.top && caretCenterY <= rect.bottom) {
        const notifId = itemEl.getAttribute('data-notification-id');
        found = filteredNotifications.find((n) => n.id === notifId) ?? null;
        break;
      }
    }

    setCaretNotification(found);
  }, [isOpen, align, valign, filteredNotifications]);

  useEffect(() => {
    if (!isOpen) {
      setCaretNotification(null);
      return;
    }
    updateCaretNotification();
    const frame = requestAnimationFrame(updateCaretNotification);
    window.addEventListener('resize', updateCaretNotification);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', updateCaretNotification);
    };
  }, [isOpen, activeTab, filteredNotifications, updateCaretNotification]);

  const caretStyle = getCaretStyle(caretNotification?.type, caretNotification?.category);

  return {
    caretRef,
    scrollContainerRef,
    caretNotification,
    caretStyle,
    updateCaretNotification,
  };
}
