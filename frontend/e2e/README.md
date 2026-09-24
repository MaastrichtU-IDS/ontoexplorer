# OntoExplorer end-to-end: performance, usability & accessibility

Playwright suite that measures the site the way a user experiences it — page load
(Core Web Vitals), interaction latency (tree render/expand, search, autocomplete),
API response times, accessibility (axe/WCAG 2.1 A/AA), responsive layout, error
states, and cross-browser behavior.

## Run

```bash
cd frontend
npm install
npm run e2e:install            # one-time: browser binaries
npm run e2e                    # all projects against the dev deployment
npm run e2e -- --project=chromium          # one browser
E2E_PERF=1 npm run e2e -- --project=chromium --project=throttled   # stable perf run
node e2e/report.mjs            # -> e2e-report/SUMMARY.md (+ console)
npm run e2e:report             # open the Playwright HTML report
```

Target another environment:

```bash
E2E_BASE_URL=http://localhost:4173 npm run e2e     # local `npm run build && npm run preview`
E2E_ONTOLOGIES="bfo:57,mondo:59269" npm run e2e    # override fixtures if slugs drift
```

## What's covered
- **perf.spec.ts** — Web Vitals + timed journeys per size fixture (tiny→giant), plus a
  `throttled` project (4× CPU + Fast-3G) modeling a modest laptop.
- **a11y.spec.ts** — axe on home / list / ontology / search / sparql.
- **usability.spec.ts** — console-error & failed-request sweep, 400px responsive
  overflow, empty-search and invalid-SPARQL error states.
- **flows.spec.ts** — cross-browser functional smoke (navigation, tree select, search→open, SPARQL).

Budgets live in `fixtures.ts`. Timing checks are `expect.soft` so a slow run reports
everything rather than aborting; functional breakage fails hard. Metrics stream to
`e2e-report/metrics.ndjson`; `report.mjs` aggregates them.
