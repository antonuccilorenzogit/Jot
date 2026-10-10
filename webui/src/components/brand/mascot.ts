/** Poses of the mascot (public/mascot/*.png, transparent background). */
export const MASCOT = {
  books: './mascot/books.png',
  pencil: './mascot/pencil.png',
  read: './mascot/read.png',
  sleep: './mascot/sleep.png',
  wave: './mascot/wave.png',
} as const;

export type MascotPose = keyof typeof MASCOT;
