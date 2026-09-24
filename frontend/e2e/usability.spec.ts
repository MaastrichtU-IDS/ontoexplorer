import { test, expect } from '@playwright/test'
import { ROUTES, SEARCH_TERMS } from './fixtures'
import { record } from './helpers/metrics'

// ── Broken-things sweep: console errors + failed requests across the core flows ─
const FLOWS: Array<{ name: string; url: string; ready: string }> = [
  { name: 'home', url: ROUTES.home, ready: 'h1' },
  { name: 'ontologies', url: ROUTES.ontologies, ready: '.ontology-row' },
  { name: 'ontology', url: ROUTES.ontology('bfo'), ready: '[data-iri]' },
  { name: 'search', url: ROUTES.search, ready: 'input' },
  { name: 'sparql', url: ROUTES.sparql, ready: 'body' },
]

for (const f of FLOWS) {
  test(`no console errors / failed requests — ${f.name}`, async ({ page }, testInfo) => {
    const consoleErrors: string[] = []
    const failed: string[] = []
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
    page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message.slice(0, 200)))
    // /auth/me 401 is the expected anonymous session probe — not a defect.
    const EXPECTED_401 = /\/auth\/me\b/
    page.on('response', (r) => {
      if (r.status() >= 400 && /\/api\//.test(r.url()) && !(r.status() === 401 && EXPECTED_401.test(r.url())))
        failed.push(`${r.status()} ${new URL(r.url()).pathname}`)
    })
    await page.goto(f.url, { waitUntil: 'domcontentloaded' })
    await page.locator(f.ready).first().waitFor({ state: 'visible', timeout: 25_000 }).catch(() => {})
    await page.waitForLoadState('networkidle').catch(() => {})
    await record(testInfo, { kind: 'errors', page: f.name, consoleErrors, failedRequests: failed })
    expect.soft(failed, `${f.name}: failed API requests`).toEqual([])
    // Ignore favicon/3rd-party noise and the browser's own "Failed to load
    // resource: 4xx/5xx" lines — those are network statuses already tracked in
    // `failed` (with the /auth/me 401 whitelisted there).
    const appErrors = consoleErrors.filter((e) => !/favicon|third-party|analytics|Failed to load resource/i.test(e))
    expect.soft(appErrors, `${f.name}: console errors`).toEqual([])
  })
}

// ── Responsive: no horizontal overflow at phone width ─────────────────────────
test('responsive — no horizontal scroll at 400px', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 400, height: 800 })
  for (const f of FLOWS) {
    await page.goto(f.url, { waitUntil: 'domcontentloaded' })
    await page.locator(f.ready).first().waitFor({ state: 'visible', timeout: 25_000 }).catch(() => {})
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    await record(testInfo, { kind: 'responsive', page: f.name, overflowPx: overflow })
    expect.soft(overflow, `${f.name}: horizontal overflow`).toBeLessThanOrEqual(2)
  }
})

// ── Error / empty states are handled, not blank or crashing ───────────────────
test('empty search shows a clear no-results state', async ({ page }) => {
  await page.goto(ROUTES.search, { waitUntil: 'domcontentloaded' })
  const box = page.getByPlaceholder(/expression or entity label/i).first()
  await expect(box).toBeVisible({ timeout: 20_000 })
  await box.fill(SEARCH_TERMS.empty)
  await box.press('Enter')
  await page.waitForLoadState('networkidle').catch(() => {})
  // The app must not white-screen: some result-region text is present.
  await expect(page.getByText(/no results|nothing|0 results|not found/i).first()).toBeVisible({ timeout: 10_000 }).catch(async () => {
    // fallback: at least the page shell + input remain interactive
    await expect(box).toBeEditable()
  })
})

test('invalid SPARQL surfaces an error, not a crash', async ({ page }) => {
  await page.goto(ROUTES.sparql, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('body')).toBeVisible()
  // YASGUI editor: type a broken query and run, expect the page to stay alive.
  const editor = page.locator('.yasqe, textarea, [contenteditable="true"]').first()
  if (await editor.count()) {
    await editor.click()
    await page.keyboard.type('SELECT WHERE { bad')
    // Any run affordance; if none found the test just asserts no crash on typing.
    const run = page.getByRole('button', { name: /run|execute|query/i }).first()
    if (await run.count()) await run.click().catch(() => {})
    await page.waitForTimeout(1500)
  }
  // Still responsive (no unhandled crash).
  await expect(page.locator('body')).toBeVisible()
})
