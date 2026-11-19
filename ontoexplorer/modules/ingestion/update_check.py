"""Detect whether an ontology has a newer upstream release.

The authoritative place to poll is the ontology's own resolvable **IRI**
(content-negotiated), NOT the ``source_url`` a past version happened to be
ingested from. For aggregator ingests that ``source_url`` is a frozen, dated
snapshot permalink (e.g. a LOV ``/versions/<date>.n3``, or a BioPortal
``/download`` pinned to one release) which can never change — so the old
behaviour of re-hashing it always reported "up to date" even when the maintainer
had published a new version at the canonical IRI.

So: prefer the IRI (conneg), fall back to ``source_url`` only when there is no
IRI. And compare against the ontology's *version-aware* default version (the
highest ``version_iri``), not merely the most recently ingested one, so a stale
aggregator snapshot that was ingested last is not treated as the baseline.

A ``version_iri`` / ``versionInfo`` **semantic guard** on top of the sha-256
trip-wire prevents two failure modes: churning on non-semantic byte changes
(regenerated timestamps, serialiser differences) and *regressing* when an
upstream republishes an OLDER file under the same IRI.
"""
from __future__ import annotations

import hashlib
import io
import re

import httpx
import pyoxigraph

# Content negotiation for an IRI fetch — ask for the common RDF syntaxes.
RDF_ACCEPT = ("text/turtle, application/rdf+xml;q=0.9, application/n-triples;q=0.8, "
              "application/ld+json;q=0.7, */*;q=0.1")
_OWL = "http://www.w3.org/2002/07/owl#"


def _fetchable(url: str | None) -> bool:
    """Only http(s) URLs can be polled. Many ontology IRIs are non-dereferenceable
    (``urn:uuid:…``) or malformed by a bad export (an unexpanded XML entity like
    ``&obo;miapa.owl``); handing those to httpx just errors every sweep."""
    return bool(url) and url.lower().startswith(("http://", "https://"))


def fetch_target(ont, version) -> tuple[str | None, bool]:
    """Where to poll for *ont*'s latest release: ``(url, use_conneg)``.

    The resolvable IRI first (content-negotiated), the default version's
    ``source_url`` only as a fallback — and only when it is an http(s) URL we can
    actually fetch. ``(None, False)`` when neither is fetchable, so the poll
    reports no_source and skips rather than erroring on a urn:/garbage IRI every
    cycle.
    """
    iri = getattr(ont, "iri", None)
    if _fetchable(iri):
        return iri, True
    src = getattr(version, "source_url", None) if version is not None else None
    if _fetchable(src):
        return src, False
    return None, False


def version_key(version_str: str | None) -> tuple[int, ...]:
    """Integer-group key for a ``version_iri`` / ``versionInfo`` string, e.g.
    ``.../v1.62/...`` -> ``(1, 62)``; ``2024-05-01`` -> ``(2024, 5, 1)``. Empty
    tuple when there are no digits. Mirrors search.versions._version_key's parse
    so display ordering and this guard agree."""
    if not version_str:
        return ()
    return tuple(int(n) for n in re.findall(r"\d+", version_str))


def extract_upstream_version(body: bytes | str) -> str | None:
    """Best-effort ``owl:versionIRI`` / ``owl:versionInfo`` from raw RDF bytes of
    any syntax (RDF/XML, Turtle, N-Triples). Regex-based and format-agnostic — it
    only feeds the semantic guard, so a miss (``None``) just means "can't tell,
    don't block". Never parses the whole graph (polls must stay cheap)."""
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body
    patterns = (
        r'versionIRI[^>]*?resource\s*=\s*["\']([^"\']+)["\']',   # RDF/XML attribute
        r'owl:versionIRI\s+<([^>]+)>',                           # Turtle (prefixed)
        re.escape(_OWL) + r'versionIRI>\s*<([^>]+)>',            # N-Triples / full IRI
        r'versionInfo[^>]*>\s*([^<]{1,40})<',                    # RDF/XML versionInfo element
        r'owl:versionInfo\s+"([^"]{1,40})"',                    # Turtle versionInfo literal
    )
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip()
            # A usable version carries a number (semver or date); a digitless capture
            # (e.g. the bare word "version" from a loose versionInfo) is noise — skip
            # it and try the next pattern, so the badge never shows a junk "version".
            if any(ch.isdigit() for ch in val):
                return val
    return None


# Syntaxes we try when counting triples of a fetched body. pyoxigraph parses from a
# media-type string; the Content-Type header (when RDF) is tried first, then the rest.
_COUNT_MIMES = ("text/turtle", "application/rdf+xml", "application/n-triples",
                "application/ld+json")


def count_triples(body: bytes, content_type: str | None = None) -> int | None:
    """Best-effort triple count of a fetched body via a throwaway in-memory parse.

    Returns the count when the bytes parse as RDF in some common syntax, and
    ``None`` when they do not parse at all — a strong "this is not an ontology"
    signal (an HTML landing page, a 404 body, an empty SPARQL result page). Only
    the poll's regression guard uses it, so it must never raise and never touch
    the real store. The `bulk_load` blank-node renaming is irrelevant here: we
    only want the quad count."""
    hint = (content_type or "").split(";")[0].strip().lower()
    ordered = ([hint] if hint in _COUNT_MIMES else []) + [m for m in _COUNT_MIMES if m != hint]
    for mime in ordered:
        try:
            store = pyoxigraph.Store()
            store.bulk_load(io.BytesIO(body), mime)
            return len(store)
        except Exception:  # noqa: BLE001 — unparseable in this syntax; try the next
            continue
    return None


async def check_for_update(ont, version, *, timeout: float = 120.0,
                           etag: str | None = None, last_modified: str | None = None) -> dict:
    """Poll *ont*'s canonical location and classify the result against *version*
    (its version-aware default version). Returns a dict with ``status`` one of:

    * ``no_source``       — no IRI and no source_url to poll
    * ``fetch_error``     — the poll request failed (``detail`` carries why)
    * ``up_to_date``      — unchanged: a 304 (conditional GET) or identical sha-256
    * ``older_skipped``   — content changed but its version is strictly OLDER
    * ``unversioned_change`` — changed, but the fetched body declares NO parseable
                            version, so we can't confirm it is a genuine newer
                            release. This is the shape a degraded IRI takes (now
                            serving an HTML landing page or an empty SPARQL result)
                            and must never be auto-ingested — the caller notifies
                            the owner instead. Carries ``fetched_triple_count`` /
                            ``current_triple_count`` so the regression is visible.
    * ``update_available``— changed, carries a version, and that version is not
                            older (``fetch_url``/``use_conneg`` say where/how to
                            ingest it; ``fetched_version`` the detected version)

    ``etag`` / ``last_modified`` (from a previous poll) are sent as
    ``If-None-Match`` / ``If-Modified-Since`` so an unchanged upstream answers 304
    with no body. The result carries the response's ``etag`` / ``last_modified``
    for the caller to persist for next time.
    """
    url, use_conneg = fetch_target(ont, version)
    if not url:
        return {"status": "no_source"}
    headers = {"Accept": RDF_ACCEPT} if use_conneg else {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 304:
                return {"status": "up_to_date", "fetch_url": url, "use_conneg": use_conneg,
                        "not_modified": True, "etag": etag, "last_modified": last_modified}
            resp.raise_for_status()
            body = resp.content
            resp_etag = resp.headers.get("etag")
            resp_last_modified = resp.headers.get("last-modified")
            resp_content_type = resp.headers.get("content-type")
    except httpx.HTTPStatusError as exc:
        return {"status": "fetch_error", "http_status": exc.response.status_code,
                "detail": f"HTTP {exc.response.status_code}", "fetch_url": url}
    except Exception as exc:  # noqa: BLE001 — surface any fetch failure to the caller
        return {"status": "fetch_error", "detail": str(exc), "fetch_url": url}

    new_sha = hashlib.sha256(body).hexdigest()
    validators = {"etag": resp_etag, "last_modified": resp_last_modified}
    cur_sha = getattr(version, "sha256", None) if version is not None else None
    if cur_sha and new_sha == cur_sha:
        return {"status": "up_to_date", "fetch_url": url, "use_conneg": use_conneg, **validators}

    fetched_version = extract_upstream_version(body)
    cur_version_iri = getattr(version, "version_iri", None) if version is not None else None
    fk, ck = version_key(fetched_version), version_key(cur_version_iri)
    if fk and ck and fk < ck:
        return {"status": "older_skipped", "fetch_url": url, "use_conneg": use_conneg,
                "fetched_version": fetched_version, "current_version": cur_version_iri, **validators}

    if not fk:
        # Content changed but carries no parseable version. We cannot confirm this is
        # a real newer release, and this is exactly how a degraded IRI reads (an HTML
        # landing page, an empty SPARQL `describe`): the sha trips every sweep. Flag it
        # as an unversioned change so the caller only NOTIFIES — never auto-ingests —
        # and surface the triple delta (None = didn't parse as RDF at all) so the owner
        # can see the regression at a glance.
        cur_tc = getattr(version, "triple_count", None) if version is not None else None
        return {"status": "unversioned_change", "fetch_url": url, "use_conneg": use_conneg,
                "new_sha256": new_sha, "fetched_version": fetched_version,
                "current_version": cur_version_iri,
                "fetched_triple_count": count_triples(body, resp_content_type),
                "current_triple_count": cur_tc, **validators}

    return {"status": "update_available", "fetch_url": url, "use_conneg": use_conneg,
            "new_sha256": new_sha, "fetched_version": fetched_version,
            "current_version": cur_version_iri, **validators}
