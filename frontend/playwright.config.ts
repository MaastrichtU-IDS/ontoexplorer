import { defineConfig, devices } from '@playwright/test'

// Target site. Defaults to the dev deployment; override for local/prod:
//   E2E_BASE_URL=http://localhost:4173 npm run e2e
const BASE_URL = process.env.E2E_BASE_URL || 'https://ontoexplorer.dev.k8s.semanticscience.org'

// Perf runs single-worker for stable timings; correctness/a11y can parallelise.
// Set E2E_PERF=1 to pin workers=1 (used by the perf/latency specs' CI job).
const PERF = process.env.E2E_PERF === '1'

export default defineConfig({
  testDir: './e2e',
  // Cold-load a 60k-entity ontology can be slow; give room but flag it in metrics.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: !PERF,
  workers: PERF ? 1 : undefined,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'e2e-report', open: 'never' }],
    ['json', { outputFile: 'e2e-report/results.json' }],
  ],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    // Real users land without a warm cache the first time.
    ignoreHTTPSErrors: true,
  },
  projects: [
    // Signs in once (if E2E_USER/E2E_PASS are set) and saves storageState for the
    // dashboard-authenticated specs. Runs before the browser projects.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    { name: 'chromium', use: { ...devices['Desktop Chrome'] }, dependencies: ['setup'], testIgnore: /auth\.setup\.ts/ },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] }, dependencies: ['setup'], testIgnore: /auth\.setup\.ts/ },
    { name: 'webkit', use: { ...devices['Desktop Safari'] }, dependencies: ['setup'], testIgnore: /auth\.setup\.ts/ },
    // ~400px phone — the responsive/usability floor.
    { name: 'mobile', use: { ...devices['Pixel 7'] }, dependencies: ['setup'], testIgnore: /auth\.setup\.ts/ },
    // Modest-laptop model: 4x CPU + Fast-3G-ish, applied in-spec via CDP where supported.
    { name: 'throttled', use: { ...devices['Desktop Chrome'] }, dependencies: ['setup'], testIgnore: /auth\.setup\.ts/ },
  ],
})
