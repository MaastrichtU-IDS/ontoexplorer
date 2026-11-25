# Peer-auth-aware ingestion download — design

**Problem.** The gated MOD-API harvest (#475) admits candidates from a configured
federation peer and enqueues each as a normal `ingest_ontology` job carrying the
distribution *download URL*. The ingestion pipeline's source resolver
(`modules/ingestion/source_resolver.py`) fetches that URL with **no auth**. When
the peer's distribution points at the peer's own gated endpoint
(`data.agroportal.eu/ontologies/{acronym}/download`, which requires an API key)
the fetch returns `401` and ingestion fails. Observed live on dev 2026-11-25:
of 47 harvested AgroPortal candidates, 46 failed at download-401; the one success
(Thesaurus INRAE) had a *public* upstream distribution URL (`forge.inrae.fr`).

The federation/harvest **read** path is already auth-aware (the federation client
attaches the peer key); the auth is lost when the candidate becomes an ingest job.

**Goal.** Make the ingestion download fetch attach the configured peer's API key
when — and only when — the target host is a configured peer's host, so gated
peer distributions ingest. Mirror the federation client's security contract
exactly. Never persist the key.

## Security contract (identical to the federation client unless noted)

1. **Attach only to the peer host.** The key is attached only when the request
   URL's host equals a configured peer's base-URL host. `apikey_param` → query
   param (`?{name}={key}`); `bearer` → `Authorization: Bearer {key}` header.
2. **Resolve at fetch time.** The secret is read from the env var named by
   `auth.secret_ref` at call time, never stored in config, never written to
   `source_url` or any DB column.
3. **Never leak across a redirect.** Redirects are followed by hand in the
   authed path. On any hop whose host ≠ the peer host, the key is withheld.
4. **No cleartext key.** Refuse an `https→http` downgrade *while the key would be
   attached* (i.e. a downgrade on the peer host). Same as the federation policy.
5. **Missing secret is not fatal.** An unset env var degrades to an
   unauthenticated request (peer answers 401, surfaced as the normal HTTP error),
   never a crash — matching `_resolve_secret`.
6. **SSRF guard unchanged.** Every hop still goes through `guarded_transport()`.
7. **Size cap unchanged.** The streaming cap (`ingest_max_source_bytes`, checked
   against Content-Length and mid-stream) still applies to the final body.
8. **No secret in logs.** For an `apikey_param` peer the key rides in the query
   string; never log the raw URL or raw exception string on this path.

## Deliberate divergence from the federation JSON path

The federation client **blocks** a redirect to a non-allowlisted host
(`_check_redirect`) because a catalogue fetch should only ever touch configured
peers. A **download** legitimately redirects off-host to a public asset store /
CDN (e.g. a `/download` 302 to S3). So the download path **follows** an off-host
redirect — but **unauthenticated** (key withheld per rule 3), subject to the
SSRF guard and the size cap. The key never leaves the peer host; an off-host hop
is just an ordinary public GET.

## Scope

- Only `resolve_url` and `resolve_iri` gain the authed path (they hit the network);
  `resolve_bytes` is unaffected.
- The common case — a URL whose host matches no configured peer — keeps the
  existing simple `follow_redirects=True` behavior byte-for-byte. The authed
  manual-redirect path runs **only** when a matching peer *and* a resolvable
  secret exist.
- No API, schema, migration, or harvest-layer change. This is a resolver-local
  fix plus a small shared-helper extraction.

## Design: extract the security policy, don't duplicate it

Auth logic is security-critical; two copies will drift. Extract the three pure,
transport-agnostic helpers out of `modules/federation/client.py` into a new
`modules/federation/auth.py`, and have both the (async) federation client and
the (sync) source resolver import them:

- `resolve_secret(auth: PeerAuth | None) -> str | None` — moved verbatim from
  the client's `_resolve_secret` (same env read, same warn-and-degrade).
- `apply_auth(url: httpx.URL, headers, auth, secret, peer_host) -> (url, headers)`
  — moved verbatim from the client's `_apply_auth`.
- `peer_for_host(host: str | None) -> Peer | None` — new: the first configured
  peer whose base-URL host equals `host` (lower-cased), else `None`. Pairs with
  the existing `peer_host_allowlist()` in `config.py`.

The federation client keeps module-level aliases (or imports) so its behavior and
its 18 existing tests stay green unchanged — the extraction is a pure move.

The source resolver's authed fetch reuses `resolve_secret` + `apply_auth`, and
its own small sync redirect loop implements the download redirect policy above
(follow off-host unauthenticated; refuse authed downgrade; re-apply the cap).

## Non-goals / anti-goals

- Do **not** store the key anywhere (not in `source_url`, not in any column).
- Do **not** change the federation client's blocking redirect policy.
- Do **not** attach auth to a host that merely *appears* in the allowlist via a
  different peer unless that peer's own host matches (host match is exact).
- Do **not** retry 401 as if transient (a separate, pre-existing `ingest_ontology`
  retry concern; out of scope here).
