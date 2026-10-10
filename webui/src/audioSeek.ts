/** Jump the open lesson audio to a given second ("[[t=…]]" markers in the notes). */
export const AUDIO_SEEK_EVENT = 'jot:seek-audio';

export interface AudioSeekDetail {
  time: number;
  play?: boolean;
}

export function requestAudioSeek(time: number, play = true): void {
  if (!Number.isFinite(time) || time < 0) return;
  window.dispatchEvent(new CustomEvent<AudioSeekDetail>(AUDIO_SEEK_EVENT, { detail: { time, play } }));
}

/** Seconds of the section that contains `target` (its heading or the closest one above). */
export function sectionTimeFor(target: Element, root: Element): number | null {
  const own = target.closest('[data-t]');
  if (own && root.contains(own)) return Number(own.getAttribute('data-t'));
  let block: Element | null = target;
  while (block && block.parentElement && block.parentElement !== root) block = block.parentElement;
  let cursor: Element | null = block;
  while (cursor) {
    const time = cursor.getAttribute?.('data-t');
    if (time !== null && time !== undefined && /^\d+$/.test(time)) return Number(time);
    cursor = cursor.previousElementSibling;
  }
  return null;
}

/** True when the click landed on the time chip drawn before a heading (::before). */
export function clickedTimeChip(heading: Element, clientX: number): boolean {
  const rect = heading.getBoundingClientRect();
  let chipWidth = 72;
  try {
    const before = window.getComputedStyle(heading, '::before');
    const width = Number.parseFloat(before.width);
    const margin = Number.parseFloat(before.marginRight) || 0;
    if (Number.isFinite(width) && width > 0) chipWidth = width + margin;
  } catch (_) { /* jsdom */ }
  return clientX - rect.left <= chipWidth;
}
