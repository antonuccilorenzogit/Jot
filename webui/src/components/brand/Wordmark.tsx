import { memo } from 'react';

/** "jot." — lowercase name with the yellow dot. */
export const Wordmark = memo(function Wordmark({ className = '', label = 'jot' }: { className?: string; label?: string }) {
  return (
    <span className={`jot-wordmark ${className}`.trim()} aria-label={label} role="img">
      <span aria-hidden="true">jot</span>
      <span className="jot-dot" aria-hidden="true" />
    </span>
  );
});
