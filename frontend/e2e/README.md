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

### Authenticated dashboard

The dashboard, submissions, keys, webhooks, stats, profile and admin pages sit
behind the platform sign-in (Keycloak `ontoexplorer` realm). To exercise them,
supply a test account; credentials are read from the environment and never
committed:

```bash
E2E_USER='you@example.org' E2E_PASS='…' npm run e2e -- --project=chromium
```

`auth.setup.ts` signs in once and saves the session to `e2e-report/.auth/user.json`
(git-ignored), which the authenticated dashboard specs reuse. Without the two env
vars the sign-in step skips and the authenticated specs skip with it — the
anonymous AuthGuard-redirect checks and everything public still run.

### System libraries

Chromium needs a few shared libs (`libgbm`, `libXdamage`, `libxkbcommon`,
`libwayland-server`). The clean install is `npx playwright install --with-deps`
(needs sudo). Where sudo isn't available, drop those `.so` files in a directory and
run with `LD_LIBRARY_PATH=/path/to/libs npm run e2e`.

## What's covered

Every route in `App.tsx`:

- **perf.spec.ts** — Web Vitals + timed journeys per size fixture (tiny→giant), plus a
  `throttled` project (4× CPU + Fast-3G) modeling a modest laptop.
- **flows.spec.ts** — cross-browser functional smoke (navigation, tree select, search→open, SPARQL).
- **compare.spec.ts** — cross-ontology + per-version diff surfaces and their permalinks.
- **ontology-tabs.spec.ts** — the OntologyPage detail tabs (Coverage, OWL Profile,
  Reuse, FAIR) render their content + data on a fully-profiled ontology, within
  budget and error-free; includes the FAIR documentation-coverage breakdown.
- **browse.spec.ts** — entity browser (`/browse`) list + structured-query modes, and
  the SPARQL query gallery (`/sparql/gallery`) open-in-editor flow.
- **content.spec.ts** — markdown pages (about/docs/privacy/contact), the sign-in page,
  and the `/coverage`, `/owl-profile`, `/compare` redirects.
- **dashboard.spec.ts** — anonymous AuthGuard redirects for every dashboard route
  (no creds needed); authenticated page loads when creds are supplied.
- **a11y.spec.ts** — axe/WCAG 2.1 A/AA across home, list, ontology, search, sparql,
  the content pages, login, browse and the gallery.
- **usability.spec.ts** — console-error & failed-request sweep + 400px responsive
  overflow across all public pages; empty-search and invalid-SPARQL error states.

Budgets live in `fixtures.ts`. Timing checks are `expect.soft` so a slow run reports
everything rather than aborting; functional breakage fails hard. Metrics stream to
`e2e-report/metrics.ndjson`; `report.mjs` aggregates them.
