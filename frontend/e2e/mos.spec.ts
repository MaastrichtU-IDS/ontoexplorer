import { test, expect, type Page, type Locator } from '@playwright/test'
import { ROUTES, REPRESENTATIVE, BUDGETS } from './fixtures'
import { installVitals, record, verdict } from './helpers/metrics'

// ── Manchester OWL Syntax (MOS) expression query ──────────────────────────────
// Two surfaces, both driven by SearchBar (submit on Enter) + an `expression`-mode
// /search request:
//   • Front page — Home "Query" mode (<MOSQuery/>). With no ontology selected it
//     fans out ONE /search?mode=expression per ontology in scope, up to the
//     500-row catalogue cap — a request storm, most returning `not_classified`.
//   • Ontology page — left-pane "Query" tab (<MOSQueryPane/>): a single-ontology
//     expression search.
//
// "It doesn't work smoothly" is mostly that unscoped front-page fan-out. These
// tests pin the functional contract that currently holds (the surface must reach
// a usable terminal state without hanging or white-screening, and the
// single-ontology pane must NOT storm), and record latency + fan-out size so the
// roughness is quantified in the report rather than asserted away. The fan-out
// size is a diagnostic annotation, not a pass/fail gate — fixing it is an app
// change (scope/batch the fan-out), not a test change.

test.beforeEach(async ({ page }) => {
  await installVitals(page)
})

// A bare token → a single named class → "subclasses" relation. Common enough to
// hit real matches across the catalogue, which is what makes the fan-out bite.
const MOS_TERM = 'cell'

// A per-ontology expression search: /api/v1/ontologies/<oid>/<vid>/search?… . Used
// by the ontology-page pane (one per query) — and, in the OLD front-page design,
// fanned out up to ~500 at once (the storm this change removes).
const EXPR_RE = /\/ontologies\/[^/]+\/[^/]+\/search\?[^ ]*mode=expression/

// The cross-ontology expression search the front page now uses instead:
// /api/v1/search?…mode=expression (no ontology path segments). ONE request serves
// the whole catalogue (server-side pre-filter + skip-unclassified).
const GLOBAL_EXPR_RE = /\/api\/v1\/search\?[^ ]*mode=expression/

// Every terminal (non-spinner) message either surface renders — no-match,
// relation-specific empties, reasoning-not-ready, ambiguous, and the
// unresolved-term detail ("'<q>' not found in this ontology's index").
const TERMINAL_MSG =
  /no results|no superclasses|no classes equivalent|reasoning is still running|reasoning not ready|classification is not ready|try again in a few minutes|ambiguous label|not found in this ontology|term not found/i

// Count the expression-mode searches a flow fires, tallied by HTTP status. The
// backend returns 503 `not_classified` when the ontology's EL classification
// (which MOS needs) isn't ready — the dominant failure mode in practice.
function recordExpressionSearches(page: Page) {
  const calls: { status: number }[] = []
  page.on('response', (r) => {
    if (EXPR_RE.test(r.url())) calls.push({ status: r.status() })
  })
  return {
    count: () => calls.length,
    summary() {
      const byStatus: Record<string, number> = {}
      for (const c of calls) byStatus[c.status] = (byStatus[c.status] || 0) + 1
      return {
        count: calls.length,
        errors: calls.filter((c) => c.status >= 400).length,
        notClassified: calls.filter((c) => c.status === 503).length,
        byStatus,
      }
    },
  }
}

// Read the visible terminal message (if any) so the report shows what the user
// actually saw — e.g. the misleading "'cell' not found in this ontology's index".
async function visibleMessage(page: Page): Promise<string | null> {
  const el = page.getByText(TERMINAL_MSG).first()
  return (await el.count()) ? (await el.textContent().catch(() => null))?.trim() ?? null : null
}

// Fail only on a real white-screen crash.
function watchForCrash(page: Page) {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message.slice(0, 200)))
  return errors
}

// Terminal = the surface settled into something a user can act on: a result row,
// OR a clear message once the query has actually run. A visible result row is
// accepted immediately. A message (no-results / superclasses / equivalent /
// reasoning-not-ready / unresolved) is accepted only when the "Searching…"
// spinner is gone AND at least `minRequests` expression searches have fired — this
// rejects the front page's premature "No results" flash shown before the ontology
// catalogue has even loaded (empty scope → nothing searched yet).
async function waitForMosTerminal(
  page: Page,
  resultRow: Locator,
  messages: RegExp,
  opts: { minRequests: number; firedCount: () => number; timeout?: number },
) {
  await expect
    .poll(
      async () => {
        if ((await resultRow.count()) > 0 && (await resultRow.first().isVisible().catch(() => false))) return true
        const searching = await page.getByText(/^Searching…$/).isVisible().catch(() => false)
        const hasMsg = await page.getByText(messages).first().isVisible().catch(() => false)
        return hasMsg && !searching && opts.firedCount() >= opts.minRequests
      },
      { timeout: opts.timeout ?? 45_000, intervals: [400, 800, 1500, 2500] },
    )
    .toBeTruthy()
}

test('MOS query — front page "Query" mode is one cross-ontology request, no storm', async ({ page }, testInfo) => {
  // Count both the (legacy) per-ontology fan-out and the new single global call.
  const perOntology = recordExpressionSearches(page)          // EXPR_RE
  const globalCalls: number[] = []
  page.on('response', (r) => { if (GLOBAL_EXPR_RE.test(r.url())) globalCalls.push(r.status()) })
  const crashes = watchForCrash(page)

  await page.goto(ROUTES.home, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'OntoExplorer' })).toBeVisible({ timeout: 20_000 })

  // Switch the front-page mode toggle to the MOS "Query" surface.
  await page.getByRole('button', { name: /^query$/i }).click()
  const box = page.getByPlaceholder(/MOS expression/i)
  await expect(box).toBeVisible({ timeout: 15_000 })

  const t0 = Date.now()
  await box.fill(MOS_TERM)
  await box.press('Enter')

  // The query resolves to a usable terminal state: a result row, or an honest
  // message (incl. the "N ontologies not reasoned yet" note), once the single
  // cross-ontology request has fired.
  const resultRow = page.locator('a[href*="term="]')
  await expect
    .poll(async () => {
      const responded =
        ((await resultRow.count()) > 0) ||
        (await page.getByText(TERMINAL_MSG).first().isVisible().catch(() => false)) ||
        (await page.getByText(/not reasoned yet/i).first().isVisible().catch(() => false))
      return responded && globalCalls.length >= 1
    }, { timeout: 30_000, intervals: [300, 600, 1200] })
    .toBeTruthy()
  const msToRespond = Date.now() - t0

  await page.waitForTimeout(1500)  // let any stray requests surface
  const results = await resultRow.count()
  const message = await visibleMessage(page)

  await record(testInfo, {
    kind: 'mos', surface: 'home', msToRespond, verdict: verdict(msToRespond, BUDGETS.mos),
    globalRequests: globalCalls.length, perOntologyRequests: perOntology.count(),
    resultsShown: results, message,
  })

  // THE regression guard: one query → one cross-ontology request, and NO
  // per-ontology fan-out (the old storm fired up to ~500 of those).
  expect(globalCalls.length, 'home MOS should fire exactly one cross-ontology /search request').toBeLessThanOrEqual(2)
  expect(globalCalls.length, 'home MOS fired no cross-ontology /search request (not wired up?)').toBeGreaterThanOrEqual(1)
  expect(perOntology.count(), 'home MOS must NOT fan out per-ontology requests (the storm)').toBeLessThanOrEqual(2)
  expect(crashes, `home MOS: page errors: ${crashes.join(' | ')}`).toEqual([])
  await expect(page.locator('body')).toBeVisible()
})

for (const slug of REPRESENTATIVE) {
  test(`MOS query — ontology page "Query" tab is single-ontology and actionable — ${slug}`, async ({ page }, testInfo) => {
    const expr = recordExpressionSearches(page)
    const crashes = watchForCrash(page)

    await page.goto(ROUTES.ontology(slug), { waitUntil: 'domcontentloaded' })
    await expect(page.locator('[data-iri]').first()).toBeVisible({ timeout: 30_000 })

    // Switch the left pane from Browse to the Query (MOS) tab.
    await page.getByRole('button', { name: /^query$/i }).click()
    const box = page.getByPlaceholder(/cell, 'cell death', GO/i)
    await expect(box).toBeVisible({ timeout: 15_000 })
    // The empty-state hint tells the user Enter submits — part of the contract.
    await expect(page.getByText(/type a mos expression and press enter/i)).toBeVisible()

    const t0 = Date.now()
    await box.fill(MOS_TERM)
    await box.press('Enter')

    // Pane results are <li><div role="button"> rows; a leaf match has no link.
    const resultRow = page.locator('li:has([role="button"])')
    await waitForMosTerminal(page, resultRow, TERMINAL_MSG, { minRequests: 1, firedCount: expr.count })
    const ms = Date.now() - t0
    const ex = expr.summary()
    const results = await resultRow.count()
    const message = await visibleMessage(page)

    await record(testInfo, {
      kind: 'mos', surface: `ontology:${slug}`, msToTerminal: ms, verdict: verdict(ms, BUDGETS.mos),
      expressionSearches: ex.count, errors: ex.errors, notClassified: ex.notClassified,
      byStatus: ex.byStatus, resultsShown: results, message,
    })

    // The single-ontology pane must NOT storm: one Enter → ~one expression search
    // (allow a stale-time refetch). This is the contract the front page violates.
    expect(ex.count, `${slug} MOS pane fired ${ex.count} expression searches for one query (expected ~1)`).toBeLessThanOrEqual(2)

    // Diagnostic: MOS needs the ontology's EL classification. When it isn't ready
    // the pane can only ever error — flag it rather than letting a green test hide
    // that the feature returns nothing.
    if (ex.notClassified > 0)
      testInfo.annotations.push({ type: 'warning', description: `${slug} MOS: classification not ready (HTTP 503 not_classified) — no expression query can return results` })
    else if (results === 0)
      testInfo.annotations.push({ type: 'warning', description: `${slug} MOS "${MOS_TERM}": 0 results — shown: ${message ?? 'nothing'}` })

    // Happy path: when the query matched, clicking a result selects the term and
    // returns the pane to Browse (the tree reappears).
    if (await resultRow.count()) {
      await resultRow.first().click()
      await expect(page.locator('[data-iri]').first()).toBeVisible({ timeout: 15_000 })
    }

    expect(crashes, `${slug} MOS: page errors: ${crashes.join(' | ')}`).toEqual([])
    await expect(page.locator('body')).toBeVisible()
  })
}
