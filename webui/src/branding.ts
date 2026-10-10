// App branding — change these to rename the app everywhere
export const APP_NAME = 'jot';
export const APP_SHORT = 'Sbobinatura';
export const APP_WINDOW_TITLE = 'jot';
export const GITHUB_REPO = 'antonuccilorenzogit/Jot';
/** Automatic update checks against the GitHub releases of this repository. */
export const UPDATE_CHECKS_ENABLED = true;
export const GITHUB_URL = `https://github.com/${GITHUB_REPO}`;
export const GITHUB_RELEASES_URL = `${GITHUB_URL}/releases/latest`;
export const GITHUB_API_RELEASES_URL = `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`;

// Injected at build time by Vite from package.json — do not hardcode here.
declare const __APP_VERSION__: string;
export const APP_VERSION: string = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'v0.0.0';
