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
import re

import httpx

# Content negotiation for an IRI fetch — ask for the common RDF syntaxes.
RDF_ACCEPT = ("text/turtle, application/rdf+xml;q=0.9, application/n-triples;q=0.8, "
              "application/ld+json;q=0.7, */*;q=0.1")
_OWL = "http://www.w3.org/2002/07/owl#"


def fetch_target(ont, version) -> tuple[str | None, bool]:
    """Where to poll for *ont*'s latest release: ``(url, use_conneg)``.

    The resolvable IRI first (content-negotiated), the default version's
    ``source_url`` only as a fallback. ``(None, False)`` when neither exists.
    """
    iri = getattr(ont, "iri", None)
    if iri:
        return iri, True
    src = getattr(version, "source_url", None) if version is not None else None
    if src:
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
            return m.group(1).strip()
    return None


async def check_for_update(ont, version, *, timeout: float = 120.0) -> dict:
    """Poll *ont*'s canonical location and classify the result against *version*
    (its version-aware default version). Returns a dict with ``status`` one of:

    * ``no_source``       — no IRI and no source_url to poll
    * ``fetch_error``     — the poll request failed (``detail`` carries why)
    * ``up_to_date``      — identical sha-256 to the current version
    * ``older_skipped``   — content changed but its version is strictly OLDER
    * ``update_available``— changed and not older (``fetch_url``/``use_conneg``
                            say where/how to ingest it; ``fetched_version`` the
                            detected upstream version string if any)
    """
    url, use_conneg = fetch_target(ont, version)
    if not url:
        return {"status": "no_source"}
    headers = {"Accept": RDF_ACCEPT} if use_conneg else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.content
    except httpx.HTTPStatusError as exc:
        return {"status": "fetch_error", "http_status": exc.response.status_code,
                "detail": f"HTTP {exc.response.status_code}", "fetch_url": url}
    except Exception as exc:  # noqa: BLE001 — surface any fetch failure to the caller
        return {"status": "fetch_error", "detail": str(exc), "fetch_url": url}

    new_sha = hashlib.sha256(body).hexdigest()
    cur_sha = getattr(version, "sha256", None) if version is not None else None
    if cur_sha and new_sha == cur_sha:
        return {"status": "up_to_date", "fetch_url": url, "use_conneg": use_conneg}

    fetched_version = extract_upstream_version(body)
    cur_version_iri = getattr(version, "version_iri", None) if version is not None else None
    fk, ck = version_key(fetched_version), version_key(cur_version_iri)
    if fk and ck and fk < ck:
        return {"status": "older_skipped", "fetch_url": url, "use_conneg": use_conneg,
                "fetched_version": fetched_version, "current_version": cur_version_iri}

    return {"status": "update_available", "fetch_url": url, "use_conneg": use_conneg,
            "new_sha256": new_sha, "fetched_version": fetched_version,
            "current_version": cur_version_iri}
