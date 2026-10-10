import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import { Check, ChevronRight, MoreVertical } from 'lucide-react';

export type KebabMenuItem =
  | {
      label: string;
      icon?: React.ReactNode;
      danger?: boolean;
      disabled?: boolean;
      onClick?: () => void;
      children?: KebabMenuItem[];
      checked?: boolean;
    }
  | { separator: true };

interface KebabMenuProps {
  items: KebabMenuItem[];
  align?: 'left' | 'right';
  buttonClassName?: string;
  ariaLabel?: string;
  title?: string;
}

interface DropdownPos {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
  maxHeight?: number;
  opensUp?: boolean;
}

interface SubmenuPos {
  top: number;
  left?: number;
  right?: number;
  maxHeight: number;
  opensLeft: boolean;
}

export function KebabMenu({ items, align = 'right', buttonClassName, ariaLabel, title }: KebabMenuProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<DropdownPos | null>(null);
  const [activeSubmenuIndex, setActiveSubmenuIndex] = useState<number | null>(null);
  const [submenuPos, setSubmenuPos] = useState<SubmenuPos | null>(null);

  const buttonRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const submenuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const openSubmenuTimerRef = useRef<ReturnType<typeof setTimeout>>(null);
  const closeSubmenuTimerRef = useRef<ReturnType<typeof setTimeout>>(null);

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;

    const computePos = () => {
      if (!buttonRef.current) return;
      const rect = buttonRef.current.getBoundingClientRect();
      const menuHeight = dropdownRef.current
        ? dropdownRef.current.offsetHeight
        : items.reduce((acc, item) => acc + ('separator' in item ? 5 : 36), 8);

      const spaceBelow = window.innerHeight - rect.bottom - 12;
      const spaceAbove = rect.top - 12;

      const opensUp = spaceBelow < menuHeight && spaceAbove > spaceBelow;
      const maxHeight = Math.max(120, opensUp ? spaceAbove : spaceBelow);

      const newPos: DropdownPos = {
        maxHeight,
        opensUp,
      };

      if (opensUp) {
        newPos.bottom = Math.max(8, window.innerHeight - rect.top + 4);
      } else {
        newPos.top = Math.max(8, rect.bottom + 4);
      }

      if (align === 'right') {
        newPos.right = Math.max(8, window.innerWidth - rect.right);
      } else {
        newPos.left = Math.max(8, rect.left);
      }

      setPos(newPos);
    };

    computePos();
    const rafId = requestAnimationFrame(computePos);
    return () => cancelAnimationFrame(rafId);
  }, [open, items, align]);

  // Compute submenu positioning whenever activeSubmenuIndex changes
  useLayoutEffect(() => {
    if (activeSubmenuIndex === null || !dropdownRef.current) {
      setSubmenuPos(null);
      return;
    }
    const itemEl = itemRefs.current[activeSubmenuIndex];
    if (!itemEl) return;

    const computeSubmenu = () => {
      if (!itemEl || !dropdownRef.current) return;
      const itemRect = itemEl.getBoundingClientRect();
      const parentRect = dropdownRef.current.getBoundingClientRect();

      const spaceRight = window.innerWidth - parentRect.right - 8;
      const spaceLeft = parentRect.left - 8;

      const opensLeft = spaceRight < 220 && spaceLeft >= spaceRight;

      let left: number | undefined;
      let right: number | undefined;

      if (opensLeft) {
        right = Math.max(8, window.innerWidth - parentRect.left + 4);
      } else {
        left = Math.max(8, parentRect.right + 4);
      }

      const maxHeight = Math.min(280, Math.max(120, window.innerHeight - 24));
      const top = Math.max(8, Math.min(itemRect.top - 4, window.innerHeight - maxHeight - 12));

      setSubmenuPos({ top, left, right, maxHeight, opensLeft });
    };

    computeSubmenu();
    const rafId = requestAnimationFrame(computeSubmenu);
    return () => cancelAnimationFrame(rafId);
  }, [activeSubmenuIndex, align]);

  useEffect(() => {
    if (!open) {
      setActiveSubmenuIndex(null);
      itemRefs.current = [];
      return;
    }
    const handleOutside = (e: MouseEvent | PointerEvent) => {
      const target = e.target as Node;
      if (buttonRef.current && buttonRef.current.contains(target)) return;
      if (dropdownRef.current && dropdownRef.current.contains(target)) return;
      if (submenuRef.current && submenuRef.current.contains(target)) return;
      setOpen(false);
      setActiveSubmenuIndex(null);
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        if (activeSubmenuIndex !== null) {
          setActiveSubmenuIndex(null);
        } else {
          setOpen(false);
        }
      }
    };
    const handleScroll = (e: Event) => {
      const target = e.target;
      if (
        target instanceof Node &&
        (dropdownRef.current?.contains(target) || submenuRef.current?.contains(target))
      ) {
        return;
      }
      setOpen(false);
      setActiveSubmenuIndex(null);
    };
    const handleResize = () => {
      setOpen(false);
      setActiveSubmenuIndex(null);
    };

    document.addEventListener('pointerdown', handleOutside, true);
    document.addEventListener('mousedown', handleOutside, true);
    document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('scroll', handleScroll, { capture: true, passive: true });
    window.addEventListener('resize', handleResize, { passive: true });

    return () => {
      document.removeEventListener('pointerdown', handleOutside, true);
      document.removeEventListener('mousedown', handleOutside, true);
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('scroll', handleScroll, { capture: true });
      window.removeEventListener('resize', handleResize);
      if (openSubmenuTimerRef.current) clearTimeout(openSubmenuTimerRef.current);
      if (closeSubmenuTimerRef.current) clearTimeout(closeSubmenuTimerRef.current);
    };
  }, [open, activeSubmenuIndex]);

  const handleItemMouseEnter = (index: number, hasChildren: boolean) => {
    if (closeSubmenuTimerRef.current) {
      clearTimeout(closeSubmenuTimerRef.current);
      closeSubmenuTimerRef.current = null;
    }
    const item = items[index];
    if (item && !('separator' in item) && item.disabled) {
      if (activeSubmenuIndex !== null) {
        closeSubmenuTimerRef.current = setTimeout(() => {
          setActiveSubmenuIndex(null);
        }, 120);
      }
      return;
    }
    if (hasChildren) {
      if (openSubmenuTimerRef.current) clearTimeout(openSubmenuTimerRef.current);
      openSubmenuTimerRef.current = setTimeout(() => {
        setActiveSubmenuIndex(index);
      }, 50);
    } else {
      if (openSubmenuTimerRef.current) {
        clearTimeout(openSubmenuTimerRef.current);
        openSubmenuTimerRef.current = null;
      }
      if (activeSubmenuIndex !== null) {
        closeSubmenuTimerRef.current = setTimeout(() => {
          setActiveSubmenuIndex(null);
        }, 120);
      }
    }
  };

  const handleItemMouseLeave = () => {
    if (openSubmenuTimerRef.current) {
      clearTimeout(openSubmenuTimerRef.current);
      openSubmenuTimerRef.current = null;
    }
    if (activeSubmenuIndex !== null) {
      closeSubmenuTimerRef.current = setTimeout(() => {
        setActiveSubmenuIndex(null);
      }, 180);
    }
  };

  const handleSubmenuMouseEnter = () => {
    if (closeSubmenuTimerRef.current) {
      clearTimeout(closeSubmenuTimerRef.current);
      closeSubmenuTimerRef.current = null;
    }
  };

  const handleSubmenuMouseLeave = () => {
    if (closeSubmenuTimerRef.current) clearTimeout(closeSubmenuTimerRef.current);
    closeSubmenuTimerRef.current = setTimeout(() => {
      setActiveSubmenuIndex(null);
    }, 180);
  };

  const opensUp = pos?.opensUp ?? false;
  const activeItem = activeSubmenuIndex !== null ? items[activeSubmenuIndex] : null;
  const activeChildren = activeItem && 'children' in activeItem ? activeItem.children : null;

  return (
    <>
      <button
        ref={buttonRef}
        onClick={e => {
          e.stopPropagation();
          setOpen(v => !v);
        }}
        onPointerDown={e => e.stopPropagation()}
        onMouseDown={e => e.stopPropagation()}
        className={`icon-button compact-icon-button ${buttonClassName ?? ''}`.trim()}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 4,
          background: open ? 'var(--sidebar-active-bg)' : undefined,
          color: open ? 'var(--text-primary)' : 'var(--text-secondary)',
          borderRadius: 8,
          cursor: 'pointer',
        }}
        aria-label={ariaLabel || 'Altre opzioni'}
        title={title || ariaLabel || 'Altre opzioni'}
      >
        <MoreVertical className="w-4 h-4" />
      </button>

      {createPortal(
        <AnimatePresence>
          {open && pos && (
            <motion.div
              key="kebab-dropdown"
              ref={dropdownRef}
              initial={{ opacity: 0, y: opensUp ? 4 : -4, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: opensUp ? 4 : -4, scale: 0.97 }}
              transition={{ duration: 0.12 }}
              style={{
                position: 'fixed',
                ...(pos.top !== undefined ? { top: pos.top } : { bottom: pos.bottom }),
                ...(pos.right !== undefined ? { right: pos.right } : { left: pos.left }),
                maxHeight: pos.maxHeight,
                overflowY: 'auto',
                zIndex: 9999,
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-default)',
                borderRadius: 12,
                boxShadow: 'var(--shadow-strong)',
                minWidth: 210,
                padding: 4,
              }}
              onClick={e => e.stopPropagation()}
            >
              {items.map((item, i) => {
                if ('separator' in item) {
                  return <div key={`sep-${i}`} style={{ height: 1, background: 'var(--border-subtle)', margin: '2px 0' }} />;
                }
                const hasChildren = Boolean(item.children && item.children.length > 0);
                const isSubmenuActive = activeSubmenuIndex === i;

                return (
                  <button
                    key={`item-${i}-${item.label}`}
                    ref={el => {
                      itemRefs.current[i] = el;
                    }}
                    disabled={item.disabled}
                    aria-haspopup={hasChildren ? 'true' : undefined}
                    aria-expanded={hasChildren ? isSubmenuActive : undefined}
                    title={item.label}
                    onMouseEnter={() => handleItemMouseEnter(i, hasChildren)}
                    onMouseLeave={handleItemMouseLeave}
                    onClick={e => {
                      e.stopPropagation();
                      if (item.disabled) return;
                      if (hasChildren) {
                        if (openSubmenuTimerRef.current) clearTimeout(openSubmenuTimerRef.current);
                        if (closeSubmenuTimerRef.current) clearTimeout(closeSubmenuTimerRef.current);
                        setActiveSubmenuIndex(prev => (prev === i ? null : i));
                      } else {
                        item.onClick?.();
                        setOpen(false);
                        setActiveSubmenuIndex(null);
                        buttonRef.current?.focus();
                      }
                    }}
                    className={`kebab-item ${item.danger ? 'is-danger' : ''} ${isSubmenuActive ? 'is-active' : ''}`.trim()}
                    style={item.disabled ? { opacity: 0.4, cursor: 'default' } : undefined}
                  >
                    {item.icon && <span className="shrink-0 w-4 h-4 flex items-center justify-center">{item.icon}</span>}
                    <span className="truncate flex-1">{item.label}</span>
                    {item.checked && (
                      <Check className="w-3.5 h-3.5 shrink-0 ml-2 text-[var(--accent-text)]" />
                    )}
                    {hasChildren && (
                      <ChevronRight className="w-3.5 h-3.5 shrink-0 ml-2 opacity-60" />
                    )}
                  </button>
                );
              })}
            </motion.div>
          )}

          {open && activeChildren && activeChildren.length > 0 && submenuPos && (
            <motion.div
              key="kebab-submenu"
              ref={submenuRef}
              initial={{ opacity: 0, x: submenuPos.opensLeft ? 4 : -4, scale: 0.97 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: submenuPos.opensLeft ? 4 : -4, scale: 0.97 }}
              transition={{ duration: 0.1 }}
              onMouseEnter={handleSubmenuMouseEnter}
              onMouseLeave={handleSubmenuMouseLeave}
              className="app-scroll"
              style={{
                position: 'fixed',
                top: submenuPos.top,
                ...(submenuPos.right !== undefined ? { right: submenuPos.right } : { left: submenuPos.left }),
                maxHeight: submenuPos.maxHeight,
                overflowY: 'auto',
                zIndex: 10000,
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-default)',
                borderRadius: 12,
                boxShadow: 'var(--shadow-strong)',
                minWidth: 200,
                maxWidth: 280,
                padding: 4,
              }}
              onClick={e => e.stopPropagation()}
            >
              {activeChildren.map((child, j) => {
                if ('separator' in child) {
                  return <div key={`subsep-${j}`} style={{ height: 1, background: 'var(--border-subtle)', margin: '2px 0' }} />;
                }
                return (
                  <button
                    key={`subitem-${j}-${child.label}`}
                    title={child.label}
                    disabled={child.disabled}
                    onClick={e => {
                      e.stopPropagation();
                      if (child.disabled) return;
                      child.onClick?.();
                      setOpen(false);
                      setActiveSubmenuIndex(null);
                      buttonRef.current?.focus();
                    }}
                    className={`kebab-item ${child.danger ? 'is-danger' : ''}`.trim()}
                    style={child.disabled ? { opacity: 0.4, cursor: 'default' } : undefined}
                  >
                    {child.icon && <span className="shrink-0 w-4 h-4 flex items-center justify-center">{child.icon}</span>}
                    <span className="truncate flex-1">{child.label}</span>
                    {child.checked && (
                      <Check className="w-3.5 h-3.5 shrink-0 ml-2 text-[var(--accent-text)]" />
                    )}
                  </button>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
