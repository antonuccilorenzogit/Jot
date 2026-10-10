import { useCallback, useEffect, useState } from 'react';
import { MASCOT } from './mascot';
import { Wordmark } from './Wordmark';

const SEEN_KEY = 'jot.splash.v1';
export const SPLASH_MS = 4200;
const REDUCED_MS = 1100;
// Unit tests render the whole app: no opening animation there.
const IS_TEST_RUN = typeof process !== 'undefined' && Boolean(process.env?.VITEST);

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  } catch {
    return false;
  }
}

function alreadySeen(): boolean {
  try {
    return sessionStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

function markSeen(): void {
  try { sessionStorage.setItem(SEEN_KEY, '1'); } catch { /* private mode */ }
}

/**
 * Opening screen: the puppy waddles in from the left balancing a pile of
 * books, trips, sits down to read, writes "jot.", waves and hops away to the
 * right. One click (or any key) skips it. Shown once per window.
 */
export function SplashScreen({ force = false, onDone }: { force?: boolean; onDone?: () => void }) {
  const [visible, setVisible] = useState(() => force || (!IS_TEST_RUN && !alreadySeen()));
  const [reduced] = useState(prefersReducedMotion);

  const finish = useCallback(() => {
    markSeen();
    setVisible(false);
    onDone?.();
  }, [onDone]);

  useEffect(() => {
    if (!visible) return;
    const timer = window.setTimeout(finish, reduced ? REDUCED_MS : SPLASH_MS);
    const onKey = () => finish();
    window.addEventListener('keydown', onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('keydown', onKey);
    };
  }, [visible, reduced, finish]);

  if (!visible) return null;

  return (
    <div
      className={`jot-splash${reduced ? ' is-reduced' : ''}`}
      role="presentation"
      onClick={finish}
      data-testid="splash"
    >
      <div className="jot-splash-stage" aria-hidden="true">
        <div className="jot-splash-ground" />
        <div className="jot-splash-walker">
          <div className="jot-pose pose-books">
            <img src={MASCOT.books} alt="" draggable={false} />
          </div>
          <div className="jot-splash-bonk">!</div>
          <div className="jot-pose pose-read">
            <img src={MASCOT.read} alt="" draggable={false} />
          </div>
          <div className="jot-pose pose-wave">
            <img src={MASCOT.wave} alt="" draggable={false} />
          </div>
        </div>
        <div className="jot-splash-word">
          <Wordmark />
        </div>
      </div>
      <span className="jot-splash-skip">Clicca per saltare</span>
    </div>
  );
}
