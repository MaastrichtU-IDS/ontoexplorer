"""OLS4-compat Solr-style search endpoints.

Implements three routes at /ols/api/...:

  GET /api/search   — full-text search across all indexed ontologies
  GET /api/select   — autocomplete-tuned prefix search
  GET /api/suggest  — lightweight label-only suggestions

All three return a Solr-style JSON envelope (responseHeader / response /
facet_counts / highlighting) rather than the HAL envelope used elsewhere.

Accepted-but-ignored parameters (v1):
  slim, fieldList, queryFields, childrenOf, allChildrenOf, exact
These are accepted to maintain wire compatibility with OLS4 clients but have
no effect on results in this implementation.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._shapes import derive_obo_id
from ontoexplorer.api.ols._solr import solr_envelope
from ontoexplorer.database import get_db
from ontoexplorer.modules.search.versions import latest_ready_versions

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ols_type(internal_type: str) -> str:
    """Map internal entity type to OLS-shaped type string.

    ``object_property``, ``data_property``, and ``annotation_property``
    all collapse to ``"property"`` in OLS4 output.
    """
    # SKOS concepts collapse to "class" in OLS output — OLS4 has no concept type,
    # and concepts are the class-like browsable terms of a vocabulary.
    if internal_type in ("class", "concept"):
        return "class"
    if internal_type.endswith("_property") or internal_type == "property":
        return "property"
    if internal_type == "individual":
        return "individual"
    return internal_type or "class"


_ALL_ENTITY_TYPES = (
    "class", "object_property", "data_property", "annotation_property", "individual",
    "concept",
)


def _entity_index_types(ols_type: str | None) -> list[str] | None:
    """Map the OLS ``type=`` query param to entity_index.type values (inclusion).

    class→[class, concept], individual→[individual], property→the three property
    sub-types. ``ontology``/unknown/None → None (no filter). Concepts ride with
    "class" to match the _ols_type output mapping.
    """
    if ols_type == "class":
        return ["class", "concept"]
    if ols_type == "individual":
        return ["individual"]
    if ols_type == "property":
        return ["object_property", "data_property", "annotation_property"]
    return None


def _excluded_types(ols_type: str | None) -> frozenset[str] | None:
    """The complement of `_entity_index_types`, for pg_autocomplete's exclusion filter."""
    inc = _entity_index_types(ols_type)
    if not inc:
        return None
    return frozenset(t for t in _ALL_ENTITY_TYPES if t not in inc)


def _build_doc(r: dict, ont_id: str) -> dict[str, Any]:
    """Convert an entity_lookup result dict to an OLS search document."""
    iri = r.get("iri", "")
    short = r.get("short", "") or ""
    return {
        "id": iri,
        "iri": iri,
        "label": r.get("label", "") or r.get("primary_label", ""),
        "short_form": short,
        "obo_id": derive_obo_id(short),
        "ontology_name": ont_id,
        "ontology_prefix": ont_id.upper(),
        "type": _ols_type(r.get("type", "")),
        "is_defining_ontology": (
            r.get("source") == ont_id or not r.get("source")
        ),
        "description": [],
        "synonyms": [],
    }


# ---------------------------------------------------------------------------
# /api/search
# ---------------------------------------------------------------------------

@router.get("/api/search")
async def search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    ontology: str | None = Query(
        None, description="CSV of ontology IDs to restrict search (e.g. 'go,chebi')"
    ),
    type: str | None = Query(
        None, description="Entity type filter: class | property | individual | ontology"
    ),
    groupField: str | None = Query(  # noqa: N803
        None, description="Set to 'iri' to deduplicate results by IRI across versions"
    ),
    rows: int = Query(10, ge=1, le=500, description="Page size (default 10, max 500)"),
    start: int = Query(0, ge=0, description="Zero-based result offset"),
    lang: str | None = Query(
        None,
        description="Language preference (accepted but not applied at lookup level in v1)",
    ),
    local: bool = Query(
        False,
        description="When true, only return entities whose source matches the host ontology",
    ),
    obsoletes: bool = Query(
        False,
        description="When true, include obsolete terms (accepted; obsolete flag not tracked in v1)",
    ),
    exact: bool = Query(
        False,
        description="When true, prefer exact label matches (accepted; ranking is best-effort)",
    ),
    slim: str | None = Query(None, description="Slim subset filter (accepted but ignored in v1)"),
    fieldList: str | None = Query(  # noqa: N803
        None, description="CSV field list for projection (accepted but ignored in v1)"
    ),
    queryFields: str | None = Query(  # noqa: N803
        None, description="CSV query fields (accepted but ignored in v1)"
    ),
    childrenOf: str | None = Query(  # noqa: N803
        None, description="CSV parent IRIs to restrict results (accepted but ignored in v1)"
    ),
    allChildrenOf: str | None = Query(  # noqa: N803
        None, description="CSV ancestor IRIs to restrict results (accepted but ignored in v1)"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full-text entity search across all indexed ontologies.

    Returns a Solr-style envelope with ``responseHeader``, ``response``,
    ``facet_counts``, and ``highlighting`` keys.  The ``response.docs`` array
    contains flat entity documents shaped for OLS4 clients.

    Supported parameters (applied):
      q, ontology, type, groupField, rows, start, lang (accepted), local,
      obsoletes (accepted), exact (accepted)

    Accepted-but-ignored in v1:
      slim, fieldList, queryFields, childrenOf, allChildrenOf
    """
    from ontoexplorer.modules.search.pg_search import pg_entity_search

    t0 = time.time()

    # Resolve the optional ?ontology= CSV to the latest-ready ontology_ids to scope.
    ontology_ids: list[str] | None = None
    if ontology:
        wanted = {o.strip() for o in ontology.split(",")}
        versions = await latest_ready_versions(db)
        ontology_ids = [str(v.ontology_id) for v in versions if str(v.ontology_id) in wanted]
        if not ontology_ids:
            qtime = int((time.time() - t0) * 1000)
            return solr_envelope([], total=0, start=start, rows=rows,
                                 q_params=dict(request.query_params), qtime_ms=qtime)

    # One cross-version SQL query over entity_index (#242 Stage 2 — replaces the
    # per-version Redis entity_lookup fan-out). Over-fetch for local filter + paging.
    fetch_limit = rows + start + 50
    results = await pg_entity_search(
        db, q, fetch_limit, types=_entity_index_types(type), ontology_ids=ontology_ids,
    )

    seen_iris: set[str] = set()
    docs: list[dict] = []
    for r in results:
        ont_id = str(r.get("ontology_id") or "")
        # local filter: only include entities whose source is this ontology
        if local and r.get("source") and r["source"] != ont_id:
            continue
        iri = r.get("iri", "")
        # pg_entity_search already dedups by IRI; groupField kept for API parity.
        if groupField == "iri" and iri in seen_iris:
            continue
        seen_iris.add(iri)
        docs.append(_build_doc(r, ont_id))

    qtime = int((time.time() - t0) * 1000)
    sliced = docs[start: start + rows]
    return solr_envelope(
        sliced,
        total=len(docs),
        start=start,
        rows=rows,
        q_params=dict(request.query_params),
        qtime_ms=qtime,
    )


# ---------------------------------------------------------------------------
# /api/select
# ---------------------------------------------------------------------------

@router.get("/api/select")
async def select(
    request: Request,
    q: str = Query(..., min_length=1, description="Prefix search query"),
    ontology: str | None = Query(None, description="CSV of ontology IDs to restrict search"),
    type: str | None = Query(
        None, description="Entity type filter: class | property | individual | ontology"
    ),
    rows: int = Query(10, ge=1, le=500, description="Page size (default 10, max 500)"),
    start: int = Query(0, ge=0, description="Zero-based result offset"),
    lang: str | None = Query(None, description="Language preference"),
    groupField: str | None = Query(  # noqa: N803
        None, description="Set to 'iri' to deduplicate results by IRI"
    ),
    local: bool = Query(False, description="Only return defining-ontology entities"),
    obsoletes: bool = Query(False, description="Include obsoletes (accepted, not tracked in v1)"),
    exact: bool = Query(False, description="Exact match preference (accepted, best-effort)"),
    slim: str | None = Query(None, description="Slim subset (accepted but ignored in v1)"),
    fieldList: str | None = Query(None, description="Field projection (accepted but ignored)"),  # noqa: N803
    queryFields: str | None = Query(None, description="Query fields (accepted but ignored)"),  # noqa: N803
    childrenOf: str | None = Query(None, description="Parent IRI filter (accepted but ignored)"),  # noqa: N803
    allChildrenOf: str | None = Query(None, description="Ancestor IRI filter (accepted but ignored)"),  # noqa: N803
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Autocomplete-tuned prefix search using the autocomplete pipeline.

    Uses ``mos_autocomplete`` (cursor-aware MOS autocomplete, entity_index-backed)
    for each indexed version, then aggregates and paginates the results.  Label-only completions
    (``iri=None``) are included as lightweight docs.

    Accepted-but-ignored in v1: slim, fieldList, queryFields, childrenOf, allChildrenOf
    """
    from ontoexplorer.modules.search.pg_search import pg_autocomplete_entities

    t0 = time.time()

    ontology_ids: list[str] | None = None
    if ontology:
        wanted = {o.strip() for o in ontology.split(",")}
        versions = await latest_ready_versions(db)
        ontology_ids = [str(v.ontology_id) for v in versions if str(v.ontology_id) in wanted]
        if not ontology_ids:
            qtime = int((time.time() - t0) * 1000)
            return solr_envelope([], total=0, start=start, rows=rows,
                                 q_params=dict(request.query_params), qtime_ms=qtime)

    # Postgres entity_index autocomplete (#242 Stage 2 — replaces the per-version
    # Redis prefix-zset completions). Type filter via the exclusion complement.
    fetch_limit = rows + start + 20
    completions = await pg_autocomplete_entities(
        db, q, fetch_limit,
        excluded_types=_excluded_types(type),
        ontology_ids=ontology_ids,
    )

    seen_iris: set[str] = set()
    docs: list[dict] = []
    for c in completions:
        iri = c.get("iri")
        if groupField == "iri" and iri and iri in seen_iris:
            continue
        if iri:
            seen_iris.add(iri)
        short = c.get("short") or ""
        ont_id = str(c.get("ontology_id") or "")
        docs.append({
            "id": iri,
            "iri": iri,
            "label": c.get("label", ""),
            "short_form": short,
            "obo_id": derive_obo_id(short) if short else None,
            "ontology_name": ont_id,
            "ontology_prefix": ont_id.upper(),
            "type": _ols_type(c.get("type", "")),
            "is_defining_ontology": True,
            "description": [],
            "synonyms": [],
        })

    qtime = int((time.time() - t0) * 1000)
    sliced = docs[start: start + rows]
    return solr_envelope(
        sliced,
        total=len(docs),
        start=start,
        rows=rows,
        q_params=dict(request.query_params),
        qtime_ms=qtime,
    )


# ---------------------------------------------------------------------------
# /api/suggest
# ---------------------------------------------------------------------------

@router.get("/api/suggest")
async def suggest(
    request: Request,
    q: str = Query(..., min_length=1, description="Suggestion query prefix"),
    ontology: str | None = Query(None, description="CSV of ontology IDs"),
    rows: int = Query(10, ge=1, le=100, description="Max suggestions returned"),
    lang: str | None = Query(None, description="Language preference"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Lightweight label-only suggestion list.

    Returns a minimal Solr envelope where each doc contains only
    ``{"autosuggest": "<label>"}``.  Designed for fast type-ahead widgets that
    do not need full entity metadata.
    """
    from ontoexplorer.modules.search.pg_search import pg_autocomplete_entities

    t0 = time.time()

    ontology_ids: list[str] | None = None
    if ontology:
        wanted = {o.strip() for o in ontology.split(",")}
        versions = await latest_ready_versions(db)
        ontology_ids = [str(v.ontology_id) for v in versions if str(v.ontology_id) in wanted]
        if not ontology_ids:
            qtime = int((time.time() - t0) * 1000)
            return solr_envelope([], total=0, start=0, rows=rows,
                                 q_params=dict(request.query_params), qtime_ms=qtime)

    # Over-fetch so cross-ontology label dedup still fills `rows` (#242 Stage 2).
    completions = await pg_autocomplete_entities(
        db, q, rows + 20, ontology_ids=ontology_ids,
    )

    # Collect unique labels in insertion order
    seen_labels: set[str] = set()
    docs: list[dict] = []
    for c in completions:
        label = c.get("label")
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        docs.append({"autosuggest": label})
        if len(docs) >= rows:
            break

    qtime = int((time.time() - t0) * 1000)
    return solr_envelope(
        docs,
        total=len(docs),
        start=0,
        rows=rows,
        q_params=dict(request.query_params),
        qtime_ms=qtime,
    )
