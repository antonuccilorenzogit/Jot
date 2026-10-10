import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import { ArrowUpDown, Check } from 'lucide-react';
import { type SortOption, SORT_OPTIONS } from './types';

interface SortMenuProps {
  sort: SortOption;
  onSortChange: (sort: SortOption) => void;
  options?: { id: SortOption; label: string }[];
}

export function SortMenu({ sort, onSortChange, options = SORT_OPTIONS }: SortMenuProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left?: number; right?: number; opensUp?: boolean } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const computePos = () => {
      if (!buttonRef.current) return;
      const rect = buttonRef.current.getBoundingClientRect();
      const menuHeight = options.length * 36 + 20;
      const spaceBelow = window.innerHeight - rect.bottom - 12;
      const spaceAbove = rect.top - 12;
      const opensUp = spaceBelow < menuHeight && spaceAbove > spaceBelow;

      setPos({
        opensUp,
        top: opensUp ? undefined : rect.bottom + 4,
        bottom: opensUp ? window.innerHeight - rect.top + 4 : undefined,
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 245)),
      });
    };
    computePos();
    const rafId = requestAnimationFrame(computePos);
    return () => cancelAnimationFrame(rafId);
  }, [open, options.length]);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (e: globalThis.MouseEvent | PointerEvent) => {
      const target = e.target as Node;
      if (buttonRef.current?.contains(target) || dropdownRef.current?.contains(target)) return;
      setOpen(false);
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    const handleClose = () => setOpen(false);
    document.addEventListener('pointerdown', handleOutside, true);
    document.addEventListener('mousedown', handleOutside, true);
    document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('scroll', handleClose, { capture: true, passive: true });
    window.addEventListener('resize', handleClose, { passive: true });
    return () => {
      document.removeEventListener('pointerdown', handleOutside, true);
      document.removeEventListener('mousedown', handleOutside, true);
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('scroll', handleClose, { capture: true });
      window.removeEventListener('resize', handleClose);
    };
  }, [open]);

  const currentOption = options.find(o => o.id === sort) ?? options[0];

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(o => !o)}
        className="filter-chip w-9 p-0 flex items-center justify-center transition-colors group/sort"
        style={open ? { color: 'var(--accent-text)', borderColor: 'var(--accent-text)', background: 'var(--accent-subtle)' } : undefined}
        title={`Ordinamento: ${currentOption?.label ?? ''}`}
        aria-label="Cambia ordinamento"
      >
        <ArrowUpDown className={`w-4 h-4 transition-transform duration-200 ${open ? 'scale-105 rotate-180 opacity-100' : 'opacity-80 group-hover/sort:opacity-100 group-hover/sort:scale-110 group-hover/sort:-translate-y-0.5'}`} />
      </button>

      {createPortal(
        <AnimatePresence>
          {open && pos && (
            <motion.div
              ref={dropdownRef}
              initial={{ opacity: 0, scale: 0.95, y: pos.opensUp ? 4 : -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: pos.opensUp ? 4 : -4 }}
              transition={{ duration: 0.1, ease: 'easeOut' }}
              style={{
                position: 'fixed',
                ...(pos.top !== undefined ? { top: pos.top } : { bottom: pos.bottom }),
                ...(pos.left !== undefined ? { left: pos.left } : { right: pos.right }),
                zIndex: 9999,
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-default)',
                borderRadius: 12,
                boxShadow: 'var(--shadow-strong)',
                minWidth: 200,
                width: 'max-content',
                padding: 4,
              }}
              onClick={e => e.stopPropagation()}
            >
              {options.map(opt => {
                const isSelected = sort === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => {
                      onSortChange(opt.id);
                      setOpen(false);
                    }}
                    className={`kebab-item ${isSelected ? 'is-active' : ''}`}
                  >
                    <span className="w-3.5 h-3.5 flex items-center justify-center shrink-0">
                      {isSelected && <Check className="w-3.5 h-3.5" style={{ color: 'var(--accent-text)' }} />}
                    </span>
                    <span>{opt.label}</span>
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
