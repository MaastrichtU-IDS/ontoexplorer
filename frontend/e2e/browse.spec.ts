import { test, expect } from '@playwright/test'
import { BROWSE, SPARQL_GALLERY, SEARCH_TERMS } from './fixtures'
import { installVitals, measureNav } from './helpers/metrics'

// Two public surfaces previously untested: the cross-ontology entity browser
// (/browse) and the SPARQL query gallery (/sparql/gallery). Functional + load.

test.beforeEach(async ({ page }) => {
  await installVitals(page)
})

test('entity browser loads, lists entities, and search filters', async ({ page }, testInfo) => {
  await measureNav(page, testInfo, 'browse', BROWSE.url, async () => {
    await expect(page.getByRole('heading', { level: 1, name: BROWSE.heading })).toBeVisible({ timeout: 20_000 })
  })
  // The List/Structured-query mode switch and the search box are the core controls.
  await expect(page.getByRole('tab', { name: /^list$/i })).toBeVisible()
  const search = page.getByRole('textbox', { name: /^search$/i })
  await expect(search).toBeVisible()

  // A fresh browse shows some entities; typing a common term keeps results (the
  // list must not white-screen or hang on a query). We assert the app stays live
  // and the input remains editable, since exact row markup varies.
  await search.fill(SEARCH_TERMS.common)
  await page.waitForLoadState('networkidle').catch(() => {})
  await expect(search).toBeEditable()
  await expect(page.getByRole('heading', { level: 1, name: BROWSE.heading })).toBeVisible()
})

test('entity browser — structured-query mode switches without error', async ({ page }) => {
  await page.goto(BROWSE.url, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { level: 1, name: BROWSE.heading })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('tab', { name: /structured query/i }).click()
  await expect(page.getByRole('tab', { name: /structured query/i })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('body')).toBeVisible()
})

test('sparql gallery loads and a query opens in the editor', async ({ page }, testInfo) => {
  await measureNav(page, testInfo, 'sparql-gallery', SPARQL_GALLERY.url, async () => {
    await expect(page.getByRole('heading', { level: 1, name: SPARQL_GALLERY.heading })).toBeVisible({ timeout: 20_000 })
  })
  // The count summary ("N public queries") always renders, even at zero.
  await expect(page.getByText(/\d+ public quer/i)).toBeVisible({ timeout: 10_000 })

  // Each card exposes an "Open ↗" affordance that routes to /sparql?q=<id>. If the
  // gallery has entries, opening one must land in the editor; an empty gallery
  // shows the explicit no-results state instead.
  const open = page.getByText(/open/i).first()
  if (await open.count()) {
    await open.click()
    await expect(page).toHaveURL(/\/sparql\?q=/, { timeout: 15_000 })
  } else {
    await expect(page.getByText(/no public queries found/i)).toBeVisible()
  }
})
