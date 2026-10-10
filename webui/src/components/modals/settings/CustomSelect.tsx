import React, { useState, useRef, useEffect, useLayoutEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';

export interface CustomSelectOption {
  value: string;
  label: string;
  sublabel?: string;
  badge?: string;
  disabled?: boolean;
}

interface CustomSelectProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: CustomSelectOption[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}

export const CustomSelect: React.FC<CustomSelectProps> = React.memo(({
  id,
  value,
  onChange,
  options,
  placeholder = 'Seleziona...',
  className = '',
  disabled = false,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuLayout, setMenuLayout] = useState({ opensUp: false, maxHeight: 240 });

  const selectedOption = options.find(opt => opt.value === value);

  useLayoutEffect(() => {
    if (!isOpen) return;
    const updateLayout = () => {
      const container = containerRef.current;
      const menu = menuRef.current;
      if (!container || !menu) return;
      const rect = container.getBoundingClientRect();
      let top = 0;
      let bottom = window.innerHeight;
      // Stay inside scrollable/clipping ancestors, including the modal's content area.
      for (let parent = container.parentElement; parent; parent = parent.parentElement) {
        if (/(auto|scroll|hidden|clip)/.test(window.getComputedStyle(parent).overflowY)) {
          const bounds = parent.getBoundingClientRect();
          top = Math.max(top, bounds.top + parent.clientTop);
          bottom = Math.min(bottom, bounds.top + parent.clientTop + parent.clientHeight);
        }
      }
      const gap = 6;
      const above = Math.max(0, rect.top - top - gap);
      const below = Math.max(0, bottom - rect.bottom - gap);
      const desiredHeight = Math.min(240, menu.scrollHeight + 2);
      const opensUp = below < desiredHeight && above > below;
      const maxHeight = Math.min(240, opensUp ? above : below);
      setMenuLayout(previous => previous.opensUp === opensUp && previous.maxHeight === maxHeight
        ? previous : { opensUp, maxHeight });
    };
    updateLayout();
    window.addEventListener('resize', updateLayout);
    document.addEventListener('scroll', updateLayout, true);
    return () => {
      window.removeEventListener('resize', updateLayout);
      document.removeEventListener('scroll', updateLayout, true);
    };
  }, [isOpen, options]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent | PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDownGlobal = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) {
        setIsOpen(false);
      }
    };
    document.addEventListener('pointerdown', handleClickOutside, true);
    document.addEventListener('mousedown', handleClickOutside, true);
    document.addEventListener('keydown', handleKeyDownGlobal);
    return () => {
      document.removeEventListener('pointerdown', handleClickOutside, true);
      document.removeEventListener('mousedown', handleClickOutside, true);
      document.removeEventListener('keydown', handleKeyDownGlobal);
    };
  }, [isOpen]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && isOpen) {
      e.stopPropagation();
      setIsOpen(false);
    }
  };

  return (
    <div
      ref={containerRef}
      onKeyDown={handleKeyDown}
      className={`relative w-full ${className}`}
    >
      {/* Hidden Native Select for DOM testing & accessibility */}
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
      >
        {!options.some(o => o.value === value) && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map(opt => (
          <option key={opt.value} value={opt.value} disabled={opt.disabled}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Trigger Button */}
      <button
        id={id}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        onClick={() => setIsOpen(prev => !prev)}
        className="custom-select-trigger w-full flex items-center justify-between gap-3 px-3.5 py-2 rounded-lg bg-[var(--bg-input)] border border-[var(--border-strong)] hover:border-[var(--accent-bg)] text-left text-sm font-semibold transition-all duration-180 focus:outline-none focus:ring-2 focus:ring-[var(--accent-ring)] disabled:opacity-50 disabled:cursor-not-allowed min-h-[40px]"
      >
        <span className="truncate text-sm text-[var(--text-primary)] font-semibold inline-flex items-center gap-2">
          {selectedOption ? (
            <>
              <span className="truncate">{selectedOption.label}</span>
              {selectedOption.badge && (
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--accent-subtle)] text-[var(--accent-text)] border border-[var(--accent-ring)] leading-normal shrink-0">
                  {selectedOption.badge}
                </span>
              )}
              {selectedOption.sublabel && (
                <span className="text-xs text-[var(--text-secondary)] font-normal ml-1.5">
                  ({selectedOption.sublabel})
                </span>
              )}
            </>
          ) : (
            <span className="text-[var(--text-secondary)] font-normal">{placeholder}</span>
          )}
        </span>
        <ChevronDown
          className={`w-4 h-4 text-[var(--text-secondary)] shrink-0 transition-transform duration-200 ${
            isOpen ? 'rotate-180 text-[var(--accent-text)]' : ''
          }`}
        />
      </button>

      {/* Menu Overlay */}
      {isOpen && (
        <div
          ref={menuRef}
          role="listbox"
          style={{ maxHeight: menuLayout.maxHeight, transformOrigin: menuLayout.opensUp ? 'bottom center' : 'top center' }}
          className={`select-dropdown absolute left-0 right-0 ${menuLayout.opensUp ? 'bottom-full mb-1.5' : 'top-full mt-1.5'} z-50 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-default)] overflow-hidden py-1 overflow-y-auto app-scroll`}
        >
          {options.map(opt => {
            const isSelected = opt.value === value;
            return (
              <button
                key={opt.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                disabled={opt.disabled}
                onClick={() => {
                  if (!opt.disabled) {
                    onChange(opt.value);
                    setIsOpen(false);
                  }
                }}
                className={`w-full flex items-center justify-between px-3.5 py-2 text-sm text-left transition-all duration-140 ${
                  opt.disabled
                    ? 'opacity-50 cursor-not-allowed text-[var(--text-secondary)] line-through decoration-[var(--border-strong)]'
                    : isSelected
                    ? 'bg-[var(--accent-subtle)] text-[var(--accent-text)] font-bold'
                    : 'text-[var(--text-primary)] font-medium hover:bg-[var(--bg-hover)]'
                }`}
              >
                <div className="flex items-center gap-2 truncate pr-2">
                  <span className="truncate">{opt.label}</span>
                  {opt.badge && (
                    <span
                      className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border leading-normal shrink-0 ${
                        isSelected
                          ? 'bg-[var(--bg-surface)] text-[var(--accent-text)] border-[var(--accent-ring)]'
                          : 'bg-[var(--accent-subtle)] text-[var(--accent-text)] border-[var(--accent-ring)]'
                      }`}
                    >
                      {opt.badge}
                    </span>
                  )}
                  {opt.sublabel && (
                    <span className="text-xs text-[var(--text-secondary)] font-normal ml-1.5">
                      ({opt.sublabel})
                    </span>
                  )}
                </div>
                {isSelected && <Check className="w-4 h-4 text-[var(--accent-text)] shrink-0 ml-auto" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
});

CustomSelect.displayName = 'CustomSelect';
