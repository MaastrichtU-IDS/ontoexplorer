# OntoExplorer documentation

Detailed documentation for every feature. Sections are grouped into **using the
catalogue** (no account needed), **submitting & maintaining ontologies** (account
needed), and **programmatic access**.

- [Using the catalogue](#using-the-catalogue)
  - [Catalogue & browse](#catalogue--browse)
  - [Ontology pages](#ontology-pages)
  - [Search](#search)
  - [Entity browser & term pages](#entity-browser--term-pages)
  - [FAIR assessment](#fair-assessment)
  - [OWL 2 profiles & reasoning](#owl-2-profiles--reasoning)
  - [Label & definition coverage](#label--definition-coverage)
  - [Vocabulary reuse](#vocabulary-reuse)
  - [Versions & diffs](#versions--diffs)
- [Submitting & maintaining ontologies](#submitting--maintaining-ontologies)
  - [Accounts & sign-in](#accounts--sign-in)
  - [Submitting an ontology](#submitting-an-ontology)
  - [The quality gate](#the-quality-gate)
  - [Keeping an ontology current](#keeping-an-ontology-current)
  - [Your dashboard](#your-dashboard)
- [Programmatic access](#programmatic-access)
  - [REST API & API keys](#rest-api--api-keys)
  - [SPARQL endpoint & gallery](#sparql-endpoint--gallery)
  - [Webhooks](#webhooks)

---

## Using the catalogue

### Catalogue & browse

The **Ontologies** page (`/ontologies`) lists the whole catalogue. The list is
server-paged and loads as you scroll, so first paint is fast regardless of
catalogue size. Each row shows the ontology's display name, source tags, latest
version, and headline counts.

**Filters** narrow the list; the server is authoritative for every one, so counts
stay correct across pages:

- **Group / source** — the registry or community an ontology came from (LOV, the
  OBO Foundry, BioPortal, upper-level sets).
- **Expressivity** — the language tier of the latest version (RDF, RDFS,
  RDFS-plus, OWL).
- **Licence** — filter by the latest version's detected SPDX licence, or by
  *No licence* for ontologies with none detected.
- **Language** — BCP-47 language codes present in the ontology's labels.

The page also has tabbed views for **Coverage** and **OWL profiles** (see below),
reachable directly at `/ontologies?tab=coverage` and `?tab=profiles`.

### Ontology pages

An ontology's page (`/ontologies/{shortname}`) is its home. It shows:

- **Identity & metadata** — the canonical IRI, title, description, and the
  platform's bleed-aware resolved title (which avoids showing an imported
  ontology's title by mistake).
- **Versions** — every ingested version, ordered by a *version-aware* sort (by
  declared version, not merely by ingest date), with the default version marked.
  Open a specific version at `/ontologies/{shortname}/{version}`.
- **Statistics** — triples, classes, properties, individuals, and more, computed
  from the stored graph.
- **FAIR report** — the per-version FAIR scorecard (see [FAIR assessment](#fair-assessment)).
- **Terms** — entry points into the ontology's classes and properties, each
  linking to its [term page](#entity-browser--term-pages).
- **IRI resolvability** — whether the ontology's IRI content-negotiates to RDF,
  re-checked periodically.

### Search

**Search** (`/search`) finds entities — classes, properties, and individuals —
across *every* ontology at once, not just within one. It combines:

- **Lexical search** over labels, synonyms, and definitions (fast prefix and
  keyword matching); and
- **Semantic search** using vector embeddings, so a query matches conceptually
  related terms even when the wording differs.

Results carry each entity's ontology, label, definition, and type, and link
through to the term page. The home page also offers a quick search box and a set
of example ontologies to start from.

### Entity browser & term pages

The **Entity browser** (`/browse`) is a structured way to explore terms across the
catalogue without starting from a query — useful for discovery.

A **term page** (reached by following any entity) shows a single class or
property in depth: its labels and synonyms, definitions, types, the ontology and
version it belongs to, its place in the class hierarchy (parents/children), and
its provenance. Hierarchy relationships come from the precomputed class-hierarchy
edges, so navigation is immediate.

### FAIR assessment

OntoExplorer computes a **FAIR report** for every ontology version, aligned with
the **FOOPS!** check set: **19 checks** across the four FAIR principles —
**F**indable, **A**ccessible, **I**nteroperable, **R**eusable. Each check is
scored from durable signals the pipeline already captures (IRI resolvability,
content-negotiation to RDF, licence presence and compliance, OWL profile and
language tier, vocabulary reuse and import closure, and term label/definition
coverage), so the report is a transparent function of real evidence — not an
opaque number.

- On an **ontology page**, the FAIR report shows the overall score, the four
  principle sub-scores, and each individual check with its pass/fail and the
  evidence behind it — so a maintainer sees exactly what to fix.
- The **FAIR dashboard** (`/fair`) rolls the scores up across the whole catalogue:
  the mean overall score with its spread (± standard deviation), the mean and
  spread per principle, a score distribution, and per-check pass rates.
- **FAIR over time** — the dashboard tracks the catalogue's FAIR scores across
  daily snapshots, so you can see whether the corpus is improving. (The trend
  chart fills in as snapshots accumulate.)

Unlike a one-shot external scan, these scores are recomputed continuously and
self-heal: change an input (assert a licence, re-resolve an IRI) and only the
affected checks recompute.

### OWL 2 profiles & reasoning

For every version the strict OWL parser can read, OntoExplorer computes **OWL 2
profile membership** — whether the ontology falls within the **EL**, **QL**,
**RL**, and **DL** profiles — together with **violation details** (the axiom types
and counts that put it outside a profile). This is backed by an automated
reasoner.

Every version also receives a **language-expressivity tier** (RDF, RDFS,
RDFS-plus, OWL) derived from the constructs it actually uses; this is computed
from the stored graph and is available even for versions the strict profiler
cannot parse. The **OWL profiles** view (`/ontologies?tab=profiles`) summarises
profile membership across the catalogue.

### Label & definition coverage

The **Coverage** view (`/ontologies?tab=coverage`) reports how completely an
ontology's terms carry human-readable **labels** and **definitions** — a key
Reusability signal. Coverage is computed from the entity index and surfaced both
per ontology and across the catalogue.

### Vocabulary reuse

OntoExplorer measures **vocabulary reuse** — the degree to which an ontology
builds on existing, widely-used vocabularies rather than minting everything
afresh — and its **import closure**. Reuse feeds the Interoperable FAIR signals
and is shown on the ontology page.

### Versions & diffs

Every ontology keeps its **full version history**. OntoExplorer selects the
default version by declared version order (version-aware), so a later ingest of an
older snapshot never visually downgrades an ontology.

The **Compare / diff** feature (`/compare`) computes a **semantic diff** between
two versions: added, removed, and modified axioms, rendered in readable terms
(including OWL restriction and class-expression frames), with the predecessor
chosen by version order. Diffs are computed against an in-memory copy of the two
graphs for speed.

---

## Submitting & maintaining ontologies

### Accounts & sign-in

Sign in with your **platform account** (`/login`). One platform account signs you
in through **ORCID, GitHub, or email**, brokered by Keycloak — you don't manage a
separate OntoExplorer password.

For security, identities are matched **only** by the identity provider plus your
stable account id at that provider. Accounts are **never** linked by email address
(that would be an account-takeover vector), so signing in with a different
provider that happens to share your email creates a distinct account.

Your verified email (when your provider supplies one) is used only for
**transactional notifications about your own content** — never marketing. The
platform emails you when a version you submitted is **held for review**, when its
**OWL 2 profile can't be computed**, as a **reminder** that a version is still held,
when a long-held version is **set aside**, and when your **uploader/maintainer
request** is decided. Detection of a new **upstream release** shows as an in-app
badge, not an email. If your provider supplies no email, these notices appear
in-app instead.

### Submitting an ontology

Adding a **new** ontology to the catalogue requires **uploader rights**, which are
granted by the OntoExplorer team. Sign in, then request them from your dashboard
with a short rationale; an admin approves or declines. (Admins, and anyone on the
operator's upload allowlist, already have them.) Until you are granted uploader
rights, the submit action returns a clear "not allowed to add ontologies" message
rather than ingesting.

Once you have uploader rights, **Add ontology** (`/dashboard/add`) submits an
ontology for ingestion. You can provide a resolvable **IRI** (content-negotiated)
or a direct **URL** to the RDF document; an upload size cap applies. Submission
enqueues an ingestion job you can follow under **Submissions**
(`/dashboard/submissions`), which shows each job's stage and outcome, with a detail
view per job (`/dashboard/submissions/{taskId}`).

Ingestion is fully automated: fetch → parse → resolve the import closure → store →
run the quality gate → build the index, embeddings, hierarchy, profiles, and FAIR
report. Failures are reported with a clear reason (for example, an unparseable
document or an IRI that does not return RDF).

**Maintaining an existing ontology.** To claim or correct an ontology that is
already in the catalogue, request **maintainer rights** over it (a per-ontology
request, again with a rationale). An admin approves it, after which you can edit
that ontology's metadata and trigger re-checks. Uploader and maintainer requests
are both reviewed by the OntoExplorer team; you can see a request's status from
your dashboard.

### The quality gate

Before a new version becomes **ready** (publicly listed), it must pass a quality
gate:

- **Licence** — a licence must be detected and on the compliance allowlist.
- **Title** — the ontology must carry a usable title.
- **Minimum content** — the document must contain at least one triple; an **empty
  fetch is rejected outright** rather than stored.

A version that fails the gate is held as **needs review** (visible to you, not
listed publicly) with the specific reasons, so you know exactly what to correct.
Your earlier ready version stays live and is never replaced by a failing one.

### Keeping an ontology current

OntoExplorer detects new upstream releases for you:

- **Update polling** — a scheduled sweep re-checks each ontology's canonical IRI
  for a newer release, comparing against the version-aware default and using
  conditional requests (ETag / Last-Modified) to stay cheap. When a newer,
  **versioned** release is found it flags an **update available** badge (and fires
  the `ontology.update_available` [webhook](#webhooks)); a change that carries no
  parseable version (for instance, an IRI that has started serving a landing page)
  is flagged for your review rather than ingested automatically.
- **Auto-sync** (opt-in, per ontology) — when enabled, a confirmed versioned
  update is ingested automatically; the new version still passes the quality gate
  before it goes live.
- **GitHub push** — for an ontology whose source is a GitHub-hosted file, a commit
  can trigger re-ingestion **immediately**, without waiting for the next poll (see
  below).
- **Check now** — you can trigger an update check on demand.

#### Re-ingesting on a GitHub commit

If your ontology's source file lives in a GitHub repository, you can have a push
re-ingest it the moment you commit, by adding a **repository webhook** that points
at OntoExplorer's inbound receiver:

1. In your repo, go to **Settings → Webhooks → Add webhook**.
2. **Payload URL:** `https://<ontoexplorer-host>/api/v1/inbound/github`
3. **Content type:** `application/json`.
4. **Secret:** the value the OntoExplorer operator gives you — deliveries are
   rejected unless their HMAC signature matches, so an unsigned or wrong-secret
   push is refused.
5. Choose **Just the push event** and save.

On each push, OntoExplorer looks at the files your commits **added or modified** and
matches them, by URL, against the source of every registered ontology — trying both
the `raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}` form and the repo's
**GitHub Pages** URL where it publishes one. Every ontology whose registered source
matches a changed file is re-ingested through the normal pipeline and quality gate,
so the push only needs to touch the file an ontology was actually registered from.

A few practical notes: the ontology must already be registered with a source URL
that matches one of those forms (a commit can refresh an existing ontology, not add
a brand-new one); the push must be on the branch or tag that URL refers to; and
inbound GitHub sync is only active when the operator has configured the shared
secret — otherwise the receiver returns *501 Not configured*. If you'd rather not
run a webhook, update polling will still pick the change up on its next sweep.

> **Building with OntoStart?** Collections generated from the
> [OntoStart template](https://github.com/micheldumontier/ontostart-template) can
> register and refresh their ontologies here directly from **CI** — no repository
> webhook needed. Add an OntoExplorer **API key** (write scope) as the
> `ONTOEXPLORER_TOKEN` secret of the repo's `ontostart-secrets` environment, and
> every push to `main` submits the freshly published versions. This path
> authenticates as *your* account, so it both **refreshes** existing ontologies and
> **registers** new ones you publish.

### Your dashboard

The **Dashboard** (`/dashboard`) is your workspace:

- **Submissions** — track ingestion jobs and their outcomes.
- **Stats** (`/dashboard/stats`) — figures for your ontologies.
- **API keys** (`/dashboard/keys`) — create and revoke keys for the REST API.
- **Webhooks** (`/dashboard/webhooks`) — subscribe to events.
- **Profile** (`/dashboard/profile`) — your account details.

---

## Programmatic access

### REST API & API keys

OntoExplorer exposes a documented **REST API** over the catalogue — ontologies,
versions, entities, search, FAIR, statistics, and more. Create a personal **API
key** under **Dashboard → API keys** (`/dashboard/keys`) and send it as a bearer
token:

```
Authorization: Bearer <your-api-key>
```

Keys are shown once at creation and stored only as a hash; revoke a key any time.
Read endpoints are public; write endpoints (submitting and managing your own
ontologies) require a key with the appropriate scope.

### SPARQL endpoint & gallery

The **SPARQL** page (`/sparql`) runs queries against the catalogue's graph store
and renders the results. The **gallery** (`/sparql/gallery`) collects ready-made
example queries you can open, run, and adapt — a quick way to learn the data
model and answer common questions.

### Webhooks

**Webhooks** (`/dashboard/webhooks`) deliver an HTTP `POST` to a URL you choose
whenever one of your subscribed events happens, so you can wire OntoExplorer into
your own automation.

**Setting one up.** From **Dashboard → Webhooks**, register a webhook with:

- **Payload URL** — the HTTPS endpoint we `POST` to.
- **Events** — one or more of the event types listed below.
- **Secret** (optional, recommended) — a shared string we use to sign each delivery
  so you can verify it really came from OntoExplorer.

From the same page you can send a **test event**, view a webhook's **delivery
history** (status, HTTP response code, attempt count), and delete it.
Programmatically the same operations are `POST`/`GET`/`DELETE /api/v1/webhooks`,
`POST /api/v1/webhooks/{id}/test`, and `GET /api/v1/webhooks/{id}/deliveries`.

**Events you can subscribe to:**

- `ontology.ingested` — a new version finished ingesting.
- `ontology.update_available` — a newer upstream release of an ontology was detected.
- `version.deprecated` — a version was deprecated.
- `reasoning.completed` / `reasoning.failed` — OWL reasoning finished / failed.
- `indexing.completed` — the entity index finished building.
- `justification.completed` / `justification.failed` — an entailment justification
  finished / failed.

**Delivery format.** Each delivery is a JSON `POST` of the event payload, with
these headers:

- `X-OntoExplorer-Event` — the event type.
- `X-OntoExplorer-Delivery` — a unique id for this delivery.
- `X-OntoExplorer-Signature` — present when you set a secret: `sha256=<hex>`, the
  HMAC-SHA256 of the raw request body keyed by your secret. Recompute it on your
  side and compare to authenticate the request before trusting the payload.

A delivery that doesn't return a `2xx` response is marked **failed** and recorded in
the webhook's delivery history.

---

*Routes and exact figures above describe the current deployment; where a feature
is opt-in or account-scoped it is noted. For anything not covered here, see
[Contact](contact.md).*
