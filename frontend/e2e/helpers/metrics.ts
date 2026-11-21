import { expect, type Page, type TestInfo } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { BUDGETS } from '../fixtures'

// ── Web Vitals capture ───────────────────────────────────────────────────────
// PerformanceObserver for LCP + CLS is Chromium-only; on firefox/webkit these
// come back null and we fall back to navigation-timing (FCP/TTFB) which is
// broadly supported. Injected before any navigation so it catches the first paint.
export const VITALS_INIT = `
  window.__vitals = { lcp: 0, cls: 0 };
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) window.__vitals.lcp = e.startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) if (!e.hadRecentInput) window.__vitals.cls += e.value;
    }).observe({ type: 'layout-shift', buffered: true });
  } catch {}
`

export interface PageMetrics {
  ttfb: number | null
  fcp: number | null
  domContentLoaded: number | null
  load: number | null
  lcp: number | null
  cls: number | null
  jsBytes: number
  cssBytes: number
  requests: number
}

export async function installVitals(page: Page) {
  await page.addInitScript(VITALS_INIT)
}

export async function collectPageMetrics(page: Page): Promise<PageMetrics> {
  return page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
    const paint = performance.getEntriesByType('paint').find((p) => p.name === 'first-contentful-paint')
    const res = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
    const bytesOf = (re: RegExp) =>
      res.filter((r) => re.test(r.name)).reduce((s, r) => s + (r.encodedBodySize || r.transferSize || 0), 0)
    const v = (window as unknown as { __vitals?: { lcp: number; cls: number } }).__vitals
    return {
      ttfb: nav ? Math.round(nav.responseStart) : null,
      fcp: paint ? Math.round(paint.startTime) : null,
      domContentLoaded: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
      load: nav ? Math.round(nav.loadEventEnd || nav.duration) : null,
      lcp: v && v.lcp ? Math.round(v.lcp) : null,
      cls: v ? Math.round(v.cls * 1000) / 1000 : null,
      jsBytes: bytesOf(/\.js(\?|$)/),
      cssBytes: bytesOf(/\.css(\?|$)/),
      requests: res.length,
    }
  })
}

// ── API latency recorder ─────────────────────────────────────────────────────
// Attaches to the page and records timing of every /api/ XHR during a flow.
export interface ApiCall { path: string; status: number; ms: number }

export class ApiRecorder {
  private calls: ApiCall[] = []
  constructor(page: Page) {
    page.on('response', async (resp) => {
      const url = resp.url()
      if (!/\/api\//.test(url)) return
      const t = resp.request().timing()
      const ms = t.responseEnd > 0 ? Math.round(t.responseEnd) : 0
      try {
        this.calls.push({ path: new URL(url).pathname.replace(/\/[0-9a-f-]{16,}/g, '/:id'), status: resp.status(), ms })
      } catch {}
    })
  }
  reset() { this.calls = [] }
  summary() {
    const ms = this.calls.map((c) => c.ms).filter((n) => n > 0).sort((a, b) => a - b)
    const pct = (p: number) => (ms.length ? ms[Math.min(ms.length - 1, Math.floor((p / 100) * ms.length))] : 0)
    const errors = this.calls.filter((c) => c.status >= 400)
    const slowest = [...this.calls].sort((a, b) => b.ms - a.ms).slice(0, 5)
    return { count: this.calls.length, p50: pct(50), p95: pct(95), errors, slowest }
  }
}

// ── Budgets ──────────────────────────────────────────────────────────────────
export type Verdict = 'good' | 'needs-work' | 'poor' | 'n/a'
export function verdict(value: number | null, b: { good: number; poor: number }): Verdict {
  if (value == null) return 'n/a'
  return value <= b.good ? 'good' : value <= b.poor ? 'needs-work' : 'poor'
}

// ── Shared page-load measurement ───────────────────────────────────────────────
// Navigate to `url`, await `ready()` (the signal the page is usable), then record
// a 'page' metrics row identical in shape to perf.spec's — so report.mjs folds
// these pages into the same Web-Vitals table. Timing never hard-fails (a slow run
// shouldn't red the suite), but API errors on the route are surfaced loudly.
// Call `installVitals(page)` in a beforeEach so LCP/CLS are captured.
export async function measureNav(
  page: Page,
  testInfo: TestInfo,
  name: string,
  url: string,
  ready: () => Promise<void>,
): Promise<{ wall: number; m: PageMetrics; a: ReturnType<ApiRecorder['summary']> }> {
  const api = new ApiRecorder(page)
  const t0 = Date.now()
  await page.goto(url, { waitUntil: 'commit' })
  await ready()
  const wall = Date.now() - t0
  const m = await collectPageMetrics(page)
  const a = api.summary()
  await record(testInfo, {
    kind: 'page', name, url, wallMs: wall, ...m,
    api: { count: a.count, p50: a.p50, p95: a.p95, errors: a.errors.length, slowest: a.slowest },
    verdicts: {
      lcp: verdict(m.lcp, BUDGETS.LCP), fcp: verdict(m.fcp, BUDGETS.FCP),
      cls: verdict(m.cls, BUDGETS.CLS), ttfb: verdict(m.ttfb, BUDGETS.TTFB),
      apiP95: verdict(a.p95, BUDGETS.apiP95),
    },
  })
  expect.soft(m.lcp ?? 0, `${name}: LCP within poor budget`).toBeLessThan(BUDGETS.LCP.poor + 1)
  expect.soft(a.errors.length, `${name}: no API errors (${a.errors.map((e) => e.path).join(', ')})`).toBe(0)
  return { wall, m, a }
}

// ── Result sink ──────────────────────────────────────────────────────────────
// Every measurement is attached to the HTML report AND appended to a single
// NDJSON file so the report generator can aggregate across browsers/specs.
const SINK = path.join(process.cwd(), 'e2e-report', 'metrics.ndjson')
export async function record(testInfo: TestInfo, row: Record<string, unknown>) {
  const entry = { project: testInfo.project.name, title: testInfo.title, ts: Date.now(), ...row }
  await testInfo.attach('metrics', { body: JSON.stringify(entry, null, 2), contentType: 'application/json' })
  try {
    fs.mkdirSync(path.dirname(SINK), { recursive: true })
    fs.appendFileSync(SINK, JSON.stringify(entry) + '\n')
  } catch {}
}
