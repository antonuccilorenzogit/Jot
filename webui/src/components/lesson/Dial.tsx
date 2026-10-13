import { memo, type ReactNode } from 'react';

/** Polar helpers shared by the dials (0 degrees = 12 o'clock). */
function point(cx: number, r: number, deg: number): string {
  const a = ((deg - 90) * Math.PI) / 180;
  return `${(cx + r * Math.cos(a)).toFixed(2)} ${(cx + r * Math.sin(a)).toFixed(2)}`;
}

function arc(cx: number, r: number, from: number, to: number): string {
  const large = to - from > 180 ? 1 : 0;
  return `M${point(cx, r, from)}A${r} ${r} 0 ${large} 1 ${point(cx, r, to)}`;
}

function tickPath(size: number, count: number, outer: number, minor: number, major: number, every: number): string {
  const cx = size / 2;
  let d = '';
  for (let i = 0; i < count; i += 1) {
    const deg = (i / count) * 360;
    d += `M${point(cx, outer, deg)}L${point(cx, i % every === 0 ? major : minor, deg)}`;
  }
  return d;
}

const SOURCE_SIZE = 184;
const SOURCE_TICKS = tickPath(SOURCE_SIZE, 60, 88, 84, 81, 5);

export interface SourceDialProps {
  label: string;
  /** Accessible description of the dial button. */
  ariaLabel: string;
  value?: ReactNode;
  unit?: string;
  filled: boolean;
  /** Ring colour when filled; muted when the source cannot be used yet. */
  ringMuted?: boolean;
  busy?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

export const SourceDial = memo(function SourceDial({ label, ariaLabel, value, unit, filled, ringMuted, busy, disabled, onClick }: SourceDialProps) {
  return (
    <button
      type="button"
      className={`source-dial${filled ? ' is-filled' : ''}${busy ? ' is-busy' : ''}`}
      aria-label={ariaLabel}
      onClick={onClick}
      disabled={disabled}
      data-source={label.toLowerCase()}
    >
      <svg width={SOURCE_SIZE} height={SOURCE_SIZE} viewBox={`0 0 ${SOURCE_SIZE} ${SOURCE_SIZE}`} aria-hidden="true">
        <path d={SOURCE_TICKS} className="dial-ticks" strokeWidth="1.4" strokeLinecap="round" />
        {filled && <circle cx="92" cy="92" r="76" fill="none" className={ringMuted ? 'dial-ring is-muted' : 'dial-ring'} strokeWidth="3.5" />}
      </svg>
      <span className="source-dial-face">
        {filled ? (
          <>
            <span className={`source-dial-value${String(value ?? '').length > 6 ? ' is-long' : String(value ?? '').length > 4 ? ' is-mid' : ''}`}>{value}</span>
            {unit && <span className="source-dial-unit">{unit}</span>}
          </>
        ) : (
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true" className="source-dial-plus">
            <path d="M12 5v14M5 12h14" />
          </svg>
        )}
      </span>
    </button>
  );
});

const PROGRESS_SIZE = 340;
const PROGRESS_TICKS = tickPath(PROGRESS_SIZE, 120, 162, 159, 156, 10);

export interface ProgressDialProps {
  total: number;
  done: number;
  /** 1-based index of the segment in progress, 0 = none. */
  active: number;
  /** Second stage (revision/done): completed segments turn dark. */
  tone: 'accent' | 'ink' | 'muted';
  overline: string;
  big: ReactNode;
  suffix?: string;
  caption?: string;
  ariaLabel: string;
}

export const ProgressDial = memo(function ProgressDial({ total, done, active, tone, overline, big, suffix, caption, ariaLabel }: ProgressDialProps) {
  const segments = Math.max(1, Math.min(60, total || 1));
  const gap = segments > 30 ? 2 : 5;
  const span = 360 / segments;
  let doneD = '';
  let activeD = '';
  let pendingD = '';
  for (let i = 0; i < segments; i += 1) {
    const d = arc(PROGRESS_SIZE / 2, 146, i * span + gap / 2, (i + 1) * span - gap / 2);
    if (i < done) doneD += d;
    else if (i === active - 1) activeD += d;
    else pendingD += d;
  }
  return (
    <div className={`progress-dial tone-${tone}`} role="img" aria-label={ariaLabel}>
      <svg width={PROGRESS_SIZE} height={PROGRESS_SIZE} viewBox={`0 0 ${PROGRESS_SIZE} ${PROGRESS_SIZE}`} aria-hidden="true">
        <path d={PROGRESS_TICKS} className="dial-ticks" strokeWidth="1.2" strokeLinecap="round" />
        {pendingD && <path d={pendingD} fill="none" className="dial-pending" strokeWidth="10" strokeLinecap="round" />}
        {activeD && <path d={activeD} fill="none" className="dial-active" strokeWidth="10" strokeLinecap="round" />}
        {doneD && <path d={doneD} fill="none" className="dial-done" strokeWidth="10" strokeLinecap="round" />}
      </svg>
      <div className="progress-dial-face">
        <span className="progress-dial-overline">{overline}</span>
        <span className="progress-dial-big">
          {big}
          {suffix && <span className="progress-dial-suffix">{suffix}</span>}
        </span>
        {caption && <span className="progress-dial-caption">{caption}</span>}
      </div>
    </div>
  );
});

export interface QuotaDialProps {
  used: number;
  limit: number;
  /** requests still available today (all keys and models) */
  remaining?: number;
  label?: string;
}

export const QuotaDial = memo(function QuotaDial({ used, limit, remaining, label }: QuotaDialProps) {
  const caption = label ?? (remaining != null ? `Richieste · restano ${remaining}` : 'Richieste');
  const safeLimit = Math.max(1, limit);
  const shown = Math.max(0, Math.min(used, safeLimit));
  const circ = 2 * Math.PI * 46;
  const filled = (circ * shown) / safeLimit;
  return (
    <div className="quota-dial-wrap">
      <div className="quota-dial" role="img" aria-label={`${used} richieste usate su ${limit} oggi`}>
        <svg width="120" height="120" viewBox="0 0 120 120" aria-hidden="true">
          <circle cx="60" cy="60" r="46" fill="none" className="dial-pending" strokeWidth="6" />
          {shown > 0 && (
            <circle
              cx="60"
              cy="60"
              r="46"
              fill="none"
              className="quota-dial-fill"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${filled.toFixed(2)} ${(circ - filled + 0.01).toFixed(2)}`}
              transform="rotate(-90 60 60)"
            />
          )}
        </svg>
        <span className="quota-dial-face">
          {used}
          <span className="quota-dial-limit">/{limit}</span>
        </span>
      </div>
      <span className="quota-dial-label">{caption}</span>
    </div>
  );
});
