import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-server API proxy target. Defaults to a local backend; set VITE_API_PROXY
// to point the dev server at a remote deployment (e.g. the dev cluster) — useful
// for running the frontend or e2e checks against real data without a local API.
const API_PROXY = process.env.VITE_API_PROXY || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API_PROXY, changeOrigin: true, secure: true },
      '/auth': { target: API_PROXY, changeOrigin: true, secure: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: API_PROXY, changeOrigin: true, secure: true },
      '/auth': { target: API_PROXY, changeOrigin: true, secure: true },
    },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Vitest owns the unit tests under src/. The Playwright specs live in e2e/
    // and import '@playwright/test' — keep them out of vitest's collection.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
