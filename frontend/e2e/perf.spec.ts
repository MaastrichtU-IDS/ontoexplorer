import { test, expect } from '@playwright/test'
import { ONTOLOGIES, ROUTES, SEARCH_TERMS, BUDGETS } from './fixtures'
import { installVitals, collectPageMetrics, ApiRecorder, verdict, record } from './helpers/metrics'

// Perf is timing-sensitive: run single-worker (E2E_PERF=1 → workers:1) so
// timings aren't skewed by parallel load. NOT `serial` — one page's budget
// breach must not skip the rest of the size ladder.

// Apply "modest laptop" throttling on the `throttled` chromium project only.
test.beforeEach(async ({ page, browserName }, testInfo) => {
  await installVitals(page)
  if (testInfo.project.name === 'throttled' && browserName === 'chromium') {
    const cdp = await page.context().newCDPSession(page)
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })
    await cdp.send('Network.enable')
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (0.75 * 1024 * 1024) / 8,
    })
  }
})

async function measurePage(page: any, testInfo: any, name: string, url: string, ready: () => Promise<void>) {
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
    verdicts: { lcp: verdict(m.lcp, BUDGETS.LCP), fcp: verdict(m.fcp, BUDGETS.FCP), cls: verdict(m.cls, BUDGETS.CLS), ttfb: verdict(m.ttfb, BUDGETS.TTFB), apiP95: verdict(a.p95, BUDGETS.apiP95) },
  })
  // Never a hard fail on timing (a slow run shouldn't red the whole suite), but
  // surface the worst regressions loudly so they can't be ignored.
  expect.soft(m.lcp ?? 0, `${name}: LCP within poor budget`).toBeLessThan(BUDGETS.LCP.poor + 1)
  expect.soft(a.errors.length, `${name}: no API errors (${a.errors.map((e: any) => e.path).join(', ')})`).toBe(0)
  return { m, a, wall }
}

test('home page load', async ({ page }, testInfo) => {
  await measurePage(page, testInfo, 'home', ROUTES.home, async () => {
    await expect(page.getByRole('heading', { name: 'OntoExplorer' })).toBeVisible()
  })
})

test('ontologies list load', async ({ page }, testInfo) => {
  await measurePage(page, testInfo, 'ontologies-list', ROUTES.ontologies, async () => {
    await expect(page.locator('.ontology-row').first()).toBeVisible({ timeout: 20_000 })
  })
})

for (const o of ONTOLOGIES) {
  test(`ontology page + tree render — ${o.slug} (${o.entities} entities)`, async ({ page }, testInfo) => {
    const { wall } = await measurePage(page, testInfo, `ontology:${o.slug}`, ROUTES.ontology(o.slug), async () => {
      // Class tree renders its first row.
      await expect(page.locator('[data-iri]').first()).toBeVisible({ timeout: 30_000 })
    })
    await record(testInfo, { kind: 'treeRender', slug: o.slug, entities: o.entities, ms: wall, verdict: verdict(wall, BUDGETS.treeRender) })

    // Expand the first expandable node and time children appearing.
    const toggle = page.locator('[data-iri] [data-toggle]').first()
    if (await toggle.count()) {
      const before = await page.locator('[data-iri]').count()
      const t0 = Date.now()
      await toggle.click()
      await expect.poll(async () => page.locator('[data-iri]').count(), { timeout: 10_000 }).toBeGreaterThan(before)
      const ms = Date.now() - t0
      await record(testInfo, { kind: 'treeExpand', slug: o.slug, ms, verdict: verdict(ms, BUDGETS.treeExpand) })
      expect.soft(ms, `${o.slug}: tree expand within poor budget`).toBeLessThan(BUDGETS.treeExpand.poor + 1)
    }
  })
}

test('search latency (keyword)', async ({ page }, testInfo) => {
  const api = new ApiRecorder(page)
  await page.goto(ROUTES.search, { waitUntil: 'domcontentloaded' })
  const box = page.getByPlaceholder(/expression or entity label/i).first()
  await expect(box).toBeVisible({ timeout: 20_000 })
  for (const [label, term] of [['common', SEARCH_TERMS.common], ['rare', SEARCH_TERMS.rare]] as const) {
    api.reset()
    await box.fill(term)
    const t0 = Date.now()
    await box.press('Enter')
    // Results list, empty-state, or a stable "no results" — whichever settles.
    await page.waitForLoadState('networkidle').catch(() => {})
    const ms = Date.now() - t0
    const a = api.summary()
    await record(testInfo, { kind: 'search', term: label, ms, api: { p95: a.p95, count: a.count, errors: a.errors.length }, verdict: verdict(ms, BUDGETS.searchResults) })
    expect.soft(ms, `search "${label}" within poor budget`).toBeLessThan(BUDGETS.searchResults.poor + 1)
  }
})

test('autocomplete latency', async ({ page }, testInfo) => {
  const api = new ApiRecorder(page)
  await page.goto(ROUTES.home, { waitUntil: 'domcontentloaded' })
  const box = page.getByPlaceholder(/Search classes, properties/i).first()
  if (!(await box.count())) test.skip(true, 'no global autocomplete box on home')
  await box.click()
  api.reset()
  const t0 = Date.now()
  await box.type('cell', { delay: 40 })
  // Wait for the autocomplete request to resolve.
  await page.waitForResponse((r) => /autocomplete|search/.test(r.url()), { timeout: 5000 }).catch(() => {})
  const ms = Date.now() - t0
  const a = api.summary()
  await record(testInfo, { kind: 'autocomplete', ms, api: { p95: a.p95 }, verdict: verdict(ms, BUDGETS.autocomplete) })
})
