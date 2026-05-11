# OntoExplorer Web UI — Design Spec

## Goal

A React + TypeScript SPA that gives users a discovery-first interface for browsing and querying ontologies. The front page enables immediate search; Browse and Search are distinct full-featured sections; a Dashboard handles account management.

---

## Tech Stack

- React 18 + TypeScript + Vite (already scaffolded in `frontend/`)
- React Router v6 (already installed)
- TanStack Query v5 (already installed) — all API calls go through query hooks
- Recharts (already installed) — Stats charts
- No additional UI library — styled with plain CSS/CSS variables for full control

---

## App Shell

Top nav bar always visible. Four nav items: **OntoExplorer** (logo/home), **Browse**, **Search**, **Dashboard**. Right side: **Sign in** button when unauthenticated; user avatar + dropdown (Profile, Sign out) when authenticated.

All dashboard routes redirect to `/login` when unauthenticated.

---

## Routes

| Path | Page | Auth required |
|---|---|---|
| `/` | Home — search hero | No |
| `/browse` | Browse — ontology list | No |
| `/browse/:oid/:vid` | Browse — ontology selected, class tree | No |
| `/browse/:oid/:vid/term/:iri` | Full-page term view | No |
| `/search` | MOS expression search | No |
| `/dashboard` | My Ontologies | Yes |
| `/dashboard/keys` | API Keys | Yes |
| `/dashboard/webhooks` | Webhooks | Yes |
| `/dashboard/stats` | Stats | Yes |
| `/login` | OAuth provider selector | No |
| `/auth/:provider/callback` | OAuth callback handler | No |

---

## Pages

### Home (`/`)

**Layout**: centered search bar near top. Below it, two side-by-side panels update as the user types.

**Search bar**:
- Placeholder: *"Search terms, ontologies, CURIEs, or MOS expressions…"*
- Ontology selector pill to the left of the input — defaults to **All** for entity search; becomes required (shows validation error) when the query is detected as a MOS expression
- Mode badge in the bar corner: `entity` or `expression` (driven by the API `auto` mode response)
- Live autocomplete fires inside `'…'` quotes — same completions as the Search page
- Inline error display for 422 (ambiguous label, shows candidate CURIEs to click) and 503 (not classified, links to job status)

**Left panel — Terms**:
- Empty state: recently indexed terms
- On query: label, CURIE, ontology name, entity type badge (Class / Property / Individual)
- Clicking a result navigates to `/browse/:oid/:vid/term/:iri`

**Right panel — Ontologies**:
- Empty state: all ontologies sorted by class count
- On query: ontology name, version, class count, one-line description
- Clicking a result navigates to `/browse/:oid/:vid`
- For MOS expression queries: shows which ontology/version was searched

---

### Browse (`/browse`, `/browse/:oid/:vid`)

**Layout**: two panes separated by a drag handle. Left pane width is resizable and saved to `localStorage`.

**Left pane**:
- Ontology list at the top: name, version badge, class count. Clicking selects the ontology.
- Version selector dropdown above the tree when an ontology is selected.
- Class tree below: lazy-loaded — expanding a node fetches direct children via `GET /api/v1/ontologies/:oid/:vid/terms?parent=:iri`. Root nodes loaded on ontology select.

**Right pane — Term detail panel** (split):
- Top half: term label, CURIE, definition, entity type badge, synonyms, superclass links (each link navigates the tree to that class)
- Bottom half: subclass mini-list — top 10 children, "N more…" link loads all
- "Open full page →" link in top-right corner

Empty state (no ontology selected): prompt to pick an ontology from the left.

---

### Full-Page Term View (`/browse/:oid/:vid/term/:iri`)

Full-width page. Breadcrumb at top: Browse → Ontology name → … → Term label.

Sections:
1. **Header**: label, CURIE, type badge, IRI (copyable)
2. **Definition**: full text
3. **Synonyms**: exact, related, broad, narrow — grouped by type
4. **Hierarchy**: superclasses list (each linkable), subclasses list (paginated, 20 per page)
5. **Axioms**: all OWL axioms rendered as human-readable MOS where possible, raw RDF otherwise
6. **Annotations**: all remaining annotation properties (skos mappings, schema:name, oboInOwl provenance, etc.)
7. **Provenance**: ontology name, version, indexed at timestamp

---

### Search (`/search`)

**Layout**: ontology selector + MOS search bar across the top. Results list below.

**Ontology selector**: required dropdown — no "All" option (ELK classification is per-version). Defaults to the most recently browsed ontology if available.

**MOS search bar**:
- Live autocomplete: fires on `'` character, prefix-scans Redis, shows entity completions with CURIE disambiguation and keyword suggestions (`some`, `and`, `or`, `not`, `only`, `min`, `max`, `exactly`, `value`, `Self`)
- Autocomplete inserts closing `'` automatically
- Mode badge: `entity` or `expression`

**Results list**: each result shows label, CURIE, match type badge (`elk` / `sparql` / `entity`), one-line definition. Clicking navigates to `/browse/:oid/:vid/term/:iri`.

**Error states**:
- 422 ambiguous label: inline block listing candidate CURIEs; clicking one inserts the disambiguated form `'label (CURIE)'` back into the search box at the right position
- 503 not classified: friendly message + link to `/jobs/:id` status
- 400 parse error (expression mode only): inline message with the parser error text

---

### Dashboard — My Ontologies (`/dashboard`)

Table columns: Name, Latest version, Status badge (queued / ingesting / classified / failed), Class count, Last updated. Clicking a row navigates to `/browse/:oid/:vid`.

**Submit Ontology** button (top right) opens a modal with three tabs:
- *By IRI*: text input for ontology IRI, system fetches with content negotiation
- *By URL*: text input for direct file URL
- *Upload / Paste*: file picker + paste textarea, format auto-detected

After submission: modal closes, a new row appears in the table with status `queued`, polling for updates every 5s via TanStack Query `refetchInterval`.

---

### Dashboard — API Keys (`/dashboard/keys`)

Table: Name, Scopes, Created, Last used. **Create Key** button opens modal (name + scope checkboxes). Raw key shown once in a copy-to-clipboard field after creation. **Revoke** button per row with confirmation dialog.

---

### Dashboard — Webhooks (`/dashboard/webhooks`)

Table: URL, Events, Last delivery (status badge + timestamp). **Add Webhook** opens modal (URL, event multi-select, secret). **Test** button per row triggers `POST /api/v1/webhooks/:id/test`. Delivery history expandable per row showing last 10 deliveries (status, HTTP code, timestamp).

---

### Dashboard — Stats (`/dashboard/stats`)

Four Recharts charts, read-only:
1. Uploads per month (bar chart)
2. Query volume over time (line chart)
3. Reasoning job durations (bar chart, p50/p95)
4. Storage used (area chart)

---

### Login (`/login`)

Three OAuth provider buttons: **Sign in with ORCID**, **Sign in with GitHub**, **Sign in with Google**. Clicking redirects to `GET /auth/:provider/login`. Callback at `/auth/:provider/callback` exchanges code, stores JWT in memory, redirects to original destination.

---

## State Management

- **TanStack Query**: all server state — ontology list, class tree nodes, term detail, search results, autocomplete completions, dashboard data
- **React context**: auth state (JWT token, current user), ontology/version selection
- **localStorage**: left pane width preference, last selected ontology/version

---

## API Client (`frontend/src/lib/api.ts`)

Typed `apiFetch` wrapper:
- Attaches `Authorization: Bearer <token>` when token is present
- On 401: attempts JWT refresh via `POST /auth/refresh`; if refresh fails, clears auth state and redirects to `/login`
- Returns typed response or throws typed error

---

## File Structure

```
frontend/src/
├── pages/
│   ├── Home.tsx              # Search hero + split panels
│   ├── Browse.tsx            # Resizable split pane + class tree + term detail
│   ├── TermPage.tsx          # Full-page term view
│   ├── Search.tsx            # MOS search + autocomplete + results
│   ├── Dashboard.tsx         # My ontologies + submit modal
│   ├── ApiKeys.tsx           # API key management
│   ├── Webhooks.tsx          # Webhook management
│   ├── Stats.tsx             # Usage charts
│   └── Login.tsx             # OAuth provider selector
├── components/
│   ├── NavBar.tsx            # Top nav bar
│   ├── SearchBar.tsx         # Shared search input with autocomplete + mode badge
│   ├── OntologySelector.tsx  # Ontology/version picker dropdown
│   ├── ClassTree.tsx         # Lazy-loaded tree component
│   ├── TermPanel.tsx         # Split term detail panel (Browse right pane)
│   ├── TermDetail.tsx        # Full term detail sections (TermPage)
│   ├── SearchResults.tsx     # Results list with match-type badges
│   ├── SubmitModal.tsx       # Three-tab ontology submission modal
│   └── ResizeHandle.tsx      # Drag handle for left/right pane resize
├── hooks/
│   ├── useOntologies.ts      # TanStack Query: list ontologies
│   ├── useClassTree.ts       # TanStack Query: lazy tree node children
│   ├── useTerm.ts            # TanStack Query: term detail
│   ├── useSearch.ts          # TanStack Query: search + autocomplete
│   └── useAuth.ts            # Auth context + JWT refresh logic
├── lib/
│   ├── api.ts                # Typed fetch wrapper with JWT handling
│   └── auth.ts               # OAuth redirect + token management
└── App.tsx                   # Routes + auth guards
```

---

## Testing

- Component tests with Vitest + React Testing Library for SearchBar (autocomplete interactions), ClassTree (lazy load), TermPanel
- Integration smoke test: mount Browse page with mock API, select ontology, click class, verify term panel populates

---

## Dependencies to Add

- `@testing-library/react` + `@testing-library/user-event` + `vitest` — component tests
- No additional runtime dependencies needed (React Router, TanStack Query, Recharts already in `package.json`)
