import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import path from 'path';
import { defineConfig } from 'vite';

const packageInfo = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8')) as { version: string };
const version = (process.env.JOT_BUILD_VERSION ?? packageInfo.version).replace(/^v/, '');
const backendPort = Number.parseInt(process.env.JOT_BACKEND_PORT ?? '8000', 10);

export default defineConfig({
  plugins: [react(), tailwindcss(), {
    name: 'desktop-build-version',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'desktop-build.json', source: JSON.stringify({ version }) });
    },
  }],
  define: {
    __APP_VERSION__: JSON.stringify(`v${version}`),
    'process.env': {},
    global: 'globalThis',
  },
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, '.'),
    },
  },
  oxc: {
    drop: ['console', 'debugger'],
  } as Record<string, unknown>,
  build: {
    target: 'esnext',
    chunkSizeWarningLimit: 1000,
  },
  server: {
    port: 3000,
    hmr: true,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
