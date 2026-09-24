import type { Page, TestInfo } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

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
