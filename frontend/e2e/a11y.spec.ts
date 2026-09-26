import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { ROUTES } from './fixtures'
import { record } from './helpers/metrics'

// WCAG 2.1 A/AA. We report every violation but only hard-fail on `critical` +
// `serious` so cosmetic AA nits don't block, while real blockers do.
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

const PAGES: Array<{ name: string; url: string; ready: string; exclude?: string[] }> = [
  { name: 'home', url: ROUTES.home, ready: 'h1' },
  { name: 'ontologies', url: ROUTES.ontologies, ready: '.ontology-row' },
  { name: 'ontology:bfo', url: ROUTES.ontology('bfo'), ready: '[data-iri]' },
  { name: 'search', url: ROUTES.search, ready: 'input' },
  // The embedded YASGUI SPARQL widget is a third-party component — its own tab
  // list (aria-required-children), editor textarea / endpoint autocomplete
  // (missing labels) and toolbar greys (contrast) can't be brought to AA without
  // forking it. Exclude its subtree so this gate enforces OUR page chrome; the
  // syntax-token colours we *do* control are themed for AA in Sparql.css. (#192)
  { name: 'sparql', url: ROUTES.sparql, ready: 'body', exclude: ['.yasgui'] },
]

for (const p of PAGES) {
  test(`a11y — ${p.name}`, async ({ page }, testInfo) => {
    await page.goto(p.url, { waitUntil: 'domcontentloaded' })
    await page.locator(p.ready).first().waitFor({ state: 'visible', timeout: 25_000 }).catch(() => {})
    let builder = new AxeBuilder({ page }).withTags(TAGS)
    for (const sel of p.exclude ?? []) builder = builder.exclude(sel)
    const results = await builder.analyze()
    const byImpact = results.violations.reduce<Record<string, number>>((acc, v) => {
      acc[v.impact || 'unknown'] = (acc[v.impact || 'unknown'] || 0) + v.nodes.length
      return acc
    }, {})
    await record(testInfo, {
      kind: 'a11y', page: p.name, total: results.violations.length, byImpact,
      violations: results.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length })),
    })
    const blockers = results.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious')
    expect.soft(blockers, `${p.name}: ${blockers.map((v) => `${v.id}(${v.impact})`).join(', ')}`).toEqual([])
  })
}
