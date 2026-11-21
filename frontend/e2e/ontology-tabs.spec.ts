import { test, expect } from '@playwright/test'
import { ONTOLOGY_TABS, FEATURE_ONTOLOGY, ROUTES, BUDGETS } from './fixtures'
import { installVitals, ApiRecorder, verdict, record } from './helpers/metrics'

// The OntologyPage right-pane detail tabs — Coverage, OWL Profile, Reuse, FAIR —
// are the per-version quality metrics and were previously uncovered by e2e. Each
// test lands on a fully-profiled ontology (FEATURE_ONTOLOGY), clicks the tab, and
// asserts the tab's own content mounts (not merely that the button highlighted),
// its data call fires without error, and it renders within the interaction budget.
// (History/compare is covered separately in compare.spec.ts.)

test.beforeEach(async ({ page }) => {
  await installVitals(page)
})

for (const tab of ONTOLOGY_TABS) {
  test(`ontology tab renders — ${tab.key} (${FEATURE_ONTOLOGY})`, async ({ page }, testInfo) => {
    const api = new ApiRecorder(page)
    await page.goto(ROUTES.ontology(FEATURE_ONTOLOGY), { waitUntil: 'domcontentloaded' })
    // Right pane is present once the class tree's first row shows.
    await expect(page.locator('[data-iri]').first()).toBeVisible({ timeout: 30_000 })

    api.reset()
    const t0 = Date.now()
    await page.getByRole('button', { name: tab.button }).click()
    // The content region must show the tab's signature text — proof it mounted and
    // the data arrived, not a spinner or the "No version available" fallback.
    await expect(page.getByText(tab.ready).first()).toBeVisible({ timeout: 20_000 })
    const ms = Date.now() - t0
    const a = api.summary()

    await record(testInfo, {
      kind: 'treeRender', slug: `${FEATURE_ONTOLOGY}:${tab.key}`, ms,
      api: { count: a.count, p95: a.p95, errors: a.errors.length, slowest: a.slowest },
      verdict: verdict(ms, BUDGETS.treeExpand),
    })
    expect.soft(a.errors.length, `${tab.key}: no API errors (${a.errors.map((e) => e.path).join(', ')})`).toBe(0)
    expect.soft(ms, `${tab.key}: tab render within poor budget`).toBeLessThan(BUDGETS.searchResults.poor + 1)

    // Must not surface a "pending"/"unavailable" placeholder on a fully-profiled
    // ontology — those strings mean the metric silently failed to load.
    await expect(page.getByText(/no version available|report yet|reindex pending/i)).toHaveCount(0)
  })
}

// The documentation-coverage breakdown (own vs reused/imported vocabularies) lives
// inside the FAIR tab and is the newest metric (0.4.211). Assert the three
// provenance rows render, closing the loop on the "is a reused predicate's
// label/definition actually imported?" question the feature answers.
test(`FAIR tab shows the documentation-coverage breakdown — ${FEATURE_ONTOLOGY}`, async ({ page }) => {
  await page.goto(ROUTES.ontology(FEATURE_ONTOLOGY), { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-iri]').first()).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: /^fair$/i }).click()
  await expect(page.getByText(/Documentation coverage/i).first()).toBeVisible({ timeout: 20_000 })
  // Own-terms and the all-entities rollup rows are always present; the reused row
  // appears when the ontology references external vocabularies (SIO does).
  await expect(page.getByText(/own terms/i).first()).toBeVisible()
  await expect(page.getByText(/all entities/i).first()).toBeVisible()
})
