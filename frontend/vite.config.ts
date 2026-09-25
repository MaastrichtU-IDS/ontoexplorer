import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
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
