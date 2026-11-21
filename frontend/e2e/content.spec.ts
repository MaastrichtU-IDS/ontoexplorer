import { test, expect } from '@playwright/test'
import { CONTENT_PAGES, LOGIN, REDIRECTS } from './fixtures'
import { installVitals, measureNav, record } from './helpers/metrics'

// Static/content surfaces: the markdown pages (about/docs/privacy/contact), the
// sign-in page, and the pure client-side redirects. These carry no heavy data
// but are part of "the whole site": they must render, be error-free, and (for a
// marketing/first-visit page) load fast. Timing is soft; functional breakage and
// API errors fail.

test.beforeEach(async ({ page }) => {
  await installVitals(page)
})

for (const p of CONTENT_PAGES) {
  test(`content page loads — ${p.name}`, async ({ page }, testInfo) => {
    await measureNav(page, testInfo, `content:${p.name}`, p.url, async () => {
      // MarkdownPage renders the leading `#` as the page H1.
      await expect(page.locator('.markdown-page h1').first()).toBeVisible({ timeout: 15_000 })
    })
    // The rendered H1 is the expected page, not a wrong/blank route.
    await expect(page.getByRole('heading', { level: 1, name: p.heading }).first()).toBeVisible()
    // Body copy actually rendered (markdown produced more than just the H1).
    const paras = await page.locator('.markdown-page p').count()
    expect.soft(paras, `${p.name}: has body copy`).toBeGreaterThan(0)
  })
}

test('login page offers the platform sign-in and no stray direct-provider buttons', async ({ page }, testInfo) => {
  await measureNav(page, testInfo, 'login', LOGIN.url, async () => {
    await expect(page.getByRole('heading', { name: LOGIN.heading })).toBeVisible({ timeout: 15_000 })
  })
  // The single sign-in affordance is present and actionable…
  await expect(page.getByRole('button', { name: /platform account/i })).toBeVisible()
  // …and the retired direct ORCID/GitHub buttons are gone (#431 regression guard).
  await expect(page.getByRole('button', { name: /sign in with (orcid|github)/i })).toHaveCount(0)
})

for (const r of REDIRECTS) {
  test(`redirect — ${r.from} lands on its tabbed destination`, async ({ page }) => {
    await page.goto(r.from, { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(r.to, { timeout: 15_000 })
  })
}

// /compare is a component redirect to the cross-ontology compare surface; it must
// resolve to the ontologies page (its exact query is version-dependent, so we only
// assert it leaves /compare for /ontologies rather than dead-ending).
test('redirect — /compare resolves to the ontologies compare surface', async ({ page }, testInfo) => {
  const failed: string[] = []
  page.on('response', (resp) => {
    if (resp.status() >= 400 && /\/api\//.test(resp.url()) && !/\/auth\/me\b/.test(resp.url()))
      failed.push(`${resp.status()} ${new URL(resp.url()).pathname}`)
  })
  await page.goto('/compare', { waitUntil: 'domcontentloaded' })
  await expect(page).toHaveURL(/\/ontologies/, { timeout: 15_000 })
  await record(testInfo, { kind: 'errors', page: 'redirect:/compare', consoleErrors: [], failedRequests: failed })
  expect.soft(failed, '/compare redirect: failed API requests').toEqual([])
})
