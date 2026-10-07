"""Global cross-ontology search — GET /api/v1/search."""
import asyncio
import hashlib
import json as _json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.reasoning import ReasoningNotReadyError
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import get_current_user
from ontoexplorer.modules.search.evaluator import AmbiguousLabelError, evaluate
from ontoexplorer.modules.search.lang import resolve_lang
from ontoexplorer.modules.search.mos_parser import ParseError, NamedClass, parse
from ontoexplorer.modules.search.semantic import semantic_search
from ontoexplorer.modules.search.versions import (
    latest_ready_version as _get_latest_version_or_404,
    latest_ready_versions as _latest_ingested_versions,
)

router = APIRouter(prefix="/api/v1", tags=["search"])

_SEARCH_CACHE_TTL = 60  # seconds
_AUTOCOMPLETE_CACHE_TTL = 60  # seconds


def _search_cache_key(
    q: str, limit: int, lang: str | None, semantic: bool, backend: str = "redis",
    types: list[str] | None = None,
) -> str:
    types_part = ",".join(sorted(types)) if types else ""
    payload = f"{q}\x1f{limit}\x1f{lang or ''}\x1f{int(semantic)}\x1f{backend}\x1f{types_part}"
    h = hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()
    return f"search:result:{h}"


def _autocomplete_cache_key(
    q: str, cursor: int, limit: int, ontology_ids: list[str], lang: str | None
) -> str:
    ont_part = ",".join(sorted(ontology_ids))
    payload = f"{q}\x1f{cursor}\x1f{limit}\x1f{ont_part}\x1f{lang or ''}"
    h = hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()
    # v8: after `inverse`, offer `(` (Protégé-style parenthesized property).
    return f"search:autocomplete:v8:{h}"


def _is_expression(node) -> bool:
    return not isinstance(node, NamedClass)


# ── Repository-wide languages ─────────────────────────────────────────────────

# Repository-wide language inventory changes only when an ontology is (re)indexed;
# the home page loads it on every visit. Cache it, and derive the version list from
# Postgres (latest ready version per ontology) rather than SCANning the whole Redis
# keyspace for meta keys — that scan was the ~9-11s cold cost at ~1900 ontologies.
_REPO_LANGS_CACHE_KEY = "repo:languages:v3"
_REPO_LANGS_TTL = 300  # seconds


@router.get("/languages", summary="All languages present across indexed ontologies")
async def get_repository_languages(db: AsyncSession = Depends(get_db)):
    """Aggregate language tags across the latest ready version of each ontology."""
    import asyncio
    import json as _json

    from sqlalchemy import func

    from ontoexplorer.modules.search.indexer import _get_redis
    r = _get_redis()
    cached = await asyncio.to_thread(r.get, _REPO_LANGS_CACHE_KEY)
    if cached:
        return _json.loads(cached)

    # Latest ready version per ontology (same source as /stats/public) — a fast
    # indexed query, instead of scanning Redis for every meta key.
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    vr = await db.execute(
        select(OntologyVersion.id).join(
            subq,
            (OntologyVersion.ontology_id == subq.c.ontology_id)
            & (OntologyVersion.created_at == subq.c.max_created),
        )
    )
    version_ids = list(vr.scalars().all())

    # Aggregate language tags from entity_index across the latest-ready versions
    # (#242 Stage 2 — was a pipelined hgetall over the Redis `:langs` hashes). One
    # grouped query over the labels JSONB.
    from ontoexplorer.modules.search.lang import canonical_lang
    from sqlalchemy import bindparam, text as _text
    counts: dict[str, int] = {}
    if version_ids:
        sql = _text(
            "SELECT k AS lang, count(*) AS n "
            "FROM entity_index, jsonb_object_keys(labels) AS k "
            "WHERE version_id IN :vids GROUP BY k"
        ).bindparams(bindparam("vids", expanding=True))
        for lang, n in (await db.execute(sql, {"vids": version_ids})).all():
            key = canonical_lang(lang)
            counts[key] = counts.get(key, 0) + int(n)
    result = sorted(
        [{"lang": k, "label_count": v} for k, v in counts.items()],
        key=lambda x: x["lang"],
    )
    try:
        await asyncio.to_thread(r.set, _REPO_LANGS_CACHE_KEY, _json.dumps(result), ex=_REPO_LANGS_TTL)
    except Exception:
        pass
    return result


# ── Global search ─────────────────────────────────────────────────────────────

@router.get("/search", summary="Cross-ontology entity or MOS expression search")
async def global_search(
    q: str = Query(..., min_length=1, description="Entity label, CURIE, IRI, or MOS expression"),
    mode: str = Query("auto", description="auto | entity | expression"),
    limit: int = Query(20, ge=1, le=200),
    lang: str | None = Query(None, description="BCP-47 language tag for preferred results"),
    semantic: bool = Query(False, description="Include vector semantic results"),
    backend: str = Query("pg", description="Search backend: pg (default, Postgres entity_index) | redis (legacy)"),
    types: list[str] = Query(
        default=[],
        description="Filter by entity_index type: class | object_property | data_property | annotation_property | individual. Empty = all.",
    ),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    effective_lang = lang or (getattr(_user, 'preferred_lang', None) if isinstance(_user, User) else None)
    # Drop unknown values so we never silently pass-through and return nothing.
    _ALLOWED_TYPES = {"class", "object_property", "data_property", "annotation_property", "individual"}
    types = [t for t in types if t in _ALLOWED_TYPES]

    # Short-TTL response cache for entity-mode queries (the hot path from the homepage).
    # MOS-expression queries are not cached — they depend on reasoning state.
    cache_key = _search_cache_key(q, limit, effective_lang, semantic, backend, types=types)
    from ontoexplorer.modules.search.indexer import _get_redis
    _r = _get_redis()
    cached = await asyncio.to_thread(_r.get, cache_key)
    if cached:
        return _json.loads(cached)

    versions = await _latest_ingested_versions(db)
    if not versions:
        return {"mode": "entity", "query": q, "results": [], "count": 0, "truncated": False}

    # Determine effective mode and parse once
    q_stripped = q.strip()
    if q_stripped.startswith("http://") or q_stripped.startswith("https://"):
        effective_mode = "entity"
        ast = None
    else:
        effective_mode = mode
        ast = None
        if mode in ("auto", "expression"):
            try:
                ast = parse(q)
                if mode == "auto":
                    effective_mode = "expression" if _is_expression(ast) else "entity"
            except ParseError as exc:
                if mode == "expression":
                    return JSONResponse(status_code=400, content={"error": "parse_error", "message": str(exc)})
                effective_mode = "entity"

    seen_iris: set[str] = set()
    merged: list[dict] = []

    if effective_mode == "entity":
        # Postgres-backed path: one SQL query over entity_index, no fan-out. The
        # legacy Redis fan-out (entity_lookup_multi) was retired in #242 Stage 2;
        # `backend` is accepted for API compatibility but always resolves to pg.
        from ontoexplorer.modules.search.pg_search import pg_entity_search, rrf_merge
        kw_results = await pg_entity_search(
            db, q, limit * 2 if semantic else limit, types=types or None
        )

        if semantic and len(q) >= 3:
            version_id_strs = [str(v.id) for v in versions]
            sem_results = await semantic_search(q, db, version_id_strs, limit=limit * 2)
            # semantic_search doesn't know about entity_index types, so apply
            # the type filter post-hoc — otherwise unfiltered semantic hits
            # leak past the user's chip selection during RRF fusion.
            if types:
                sem_results = [r for r in sem_results if r.get("type") in types]
            # Hybrid mode: RRF-fuse keyword + semantic, return a single ranked list.
            merged = rrf_merge(kw_results, sem_results, limit)
            payload = {
                "mode": "entity", "query": q, "results": merged,
                "count": len(merged), "truncated": len(merged) >= limit,
                "semantic_results": [],  # already fused into `results`
                "fusion": "rrf",
            }
            await asyncio.to_thread(_r.set, cache_key, _json.dumps(payload), _SEARCH_CACHE_TTL)
            return payload
        else:
            merged = kw_results[:limit]

        sem_results: list[dict] = []
        if semantic and len(q) >= 3:
            version_id_strs = [str(v.id) for v in versions]
            sem_results = await semantic_search(q, db, version_id_strs, limit=10)
            if types:
                sem_results = [r for r in sem_results if r.get("type") in types]

        payload = {
            "mode": "entity", "query": q, "results": merged,
            "count": len(merged), "truncated": len(merged) >= limit,
            "semantic_results": sem_results,
        }
        await asyncio.to_thread(_r.set, cache_key, _json.dumps(payload), _SEARCH_CACHE_TTL)
        return payload

    # Expression mode — evaluate against each version separately
    warnings: list[dict] = []

    # Prebuild the entity_index resolvers for all versions in ONE query (#242
    # Workstream B) — the per-version evaluate() below runs under asyncio.gather on
    # the shared db session, so it must not query the DB itself. Scope the resolver
    # to the labels THIS query references, so one expression search never loads the
    # whole catalogue's entity_index into the api pod.
    from ontoexplorer.modules.search.evaluator import (
        build_resolvers, enrich_labels, _collect_refs, resolver_can_resolve,
    )
    _refs, _needs_classes = _collect_refs(ast)
    _resolvers = await build_resolvers(
        db, [str(v.id) for v in versions], _refs, need_classes=_needs_classes)

    # #277: only evaluate versions whose entity_index actually contains the query's
    # terms. A version that can't resolve them returns [] anyway. The ref-scoped
    # resolvers were already prefetched above, so this filter is free.
    _candidates = [v for v in versions if resolver_can_resolve(_resolvers[str(v.id)], _refs)]

    # #277: and of those, only evaluate versions that are ALREADY classified. A bare
    # get_classification() TRIGGERS on-demand reasoning for an unreasoned version
    # (seconds to minutes each), so a global expression query must never reason
    # synchronously — it reports matches from already-reasoned ontologies and skips
    # the rest (one pipelined EXISTS, no reasoner calls).
    from ontoexplorer.clients.reasoning import filter_already_classified
    _ready = await filter_already_classified([(str(v.id), v.reasoner) for v in _candidates])
    _skipped_unclassified = sum(1 for v in _candidates if str(v.id) not in _ready)
    _candidates = [v for v in _candidates if str(v.id) in _ready]

    # Bound how many cached-classification fetches run at once (each can be a large
    # payload; don't stampede the reasoner / event loop).
    _sem = asyncio.Semaphore(8)

    async def search_one_expression(v: OntologyVersion) -> list[dict]:
        try:
            async with _sem:
                results = await evaluate(ast, str(v.id), str(v.ontology_id),
                                         _resolvers[str(v.id)], lang=effective_lang, reasoner=v.reasoner)
            # MOS class expressions always yield classes — tag explicitly so the
            # UI badge renders and the chip filter compares like-for-like.
            return [
                {"iri": r.iri, "label": r.label, "short": r.short, "match_type": r.match_type,
                 "type": "class",
                 "version_id": str(v.id), "ontology_id": str(v.ontology_id),
                 "lang": r.lang, "cross_language": r.cross_language}
                for r in results
            ]
        except AmbiguousLabelError as exc:
            warnings.append({
                "type": "ambiguous_label",
                "label": exc.label,
                "ontology_id": str(v.ontology_id),
                "candidates": [{"iri": c.get("iri"), "short": c.get("short")} for c in exc.candidates],
            })
            return []
        except (ReasoningNotReadyError, Exception):
            return []

    nested = await asyncio.gather(*[search_one_expression(v) for v in _candidates])
    for rows in nested:
        for row in rows:
            if row["iri"] not in seen_iris:
                seen_iris.add(row["iri"])
                merged.append(row)
                if len(merged) >= limit:
                    break
        if len(merged) >= limit:
            break

    # Result labels (subclasses/fillers, unknown until evaluation) are not in the
    # ref-scoped resolver — restore them here in one batched lookup over the final
    # capped set (runs after gather, so no concurrent DB on the shared session).
    capped = merged[:limit]
    await enrich_labels(db, capped, effective_lang)
    if _skipped_unclassified:
        # Transparency: a term may exist in ontologies that aren't reasoned yet; those
        # can't contribute to an expression result until their pipeline classifies them.
        warnings.append({
            "type": "versions_skipped_unclassified",
            "count": _skipped_unclassified,
        })
    return {"mode": "expression", "query": q, "results": capped,
            "count": len(capped), "truncated": len(merged) > limit,
            "semantic_results": [], "warnings": warnings}


# ── Per-ontology search (latest version) ──────────────────────────────────────

@router.get("/ontologies/{ontology_id}/search",
            summary="Search within an ontology (latest version)")
async def ontology_search(
    ontology_id: str,
    q: str = Query(..., description="Entity label, CURIE, IRI, or MOS expression"),
    mode: str = Query("auto", description="auto | entity | expression"),
    limit: int = Query(20, ge=1, le=200),
    lang: str | None = Query(None, description="BCP-47 language tag"),
    semantic: bool = Query(False, description="Include vector semantic results"),
    direct: bool = Query(False, description="Return direct subclasses only (no transitive expansion)"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_latest_version_or_404(db, ontology_id)
    version_id = str(version.id)
    ontology_row = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()
    effective_lang = resolve_lang(lang, ontology_row, _user if isinstance(_user, User) else None)

    q_stripped = q.strip()
    if q_stripped.startswith("http://") or q_stripped.startswith("https://"):
        effective_mode = "entity"
        ast = None
    else:
        effective_mode = mode
        ast = None
        if mode in ("auto", "expression"):
            try:
                ast = parse(q)
                if mode == "auto":
                    effective_mode = "expression" if _is_expression(ast) else "entity"
            except ParseError as exc:
                if mode == "expression":
                    return JSONResponse(status_code=400, content={"error": "parse_error", "message": str(exc)})
                effective_mode = "entity"

    if effective_mode == "entity":
        # Postgres entity_index scoped to this version (#242 Stage 1): replaces the
        # Redis prefix-zset + per-IRI hash lookup. Same tiered ranking as /search.
        from ontoexplorer.modules.search.pg_search import pg_entity_search
        results = await pg_entity_search(db, q, limit, version_id=version_id)
        sem_results: list[dict] = []
        if semantic and len(q) >= 3:
            sem_results = await semantic_search(q, db, [version_id], limit=10)
        return {
            "mode": "entity", "query": q, "version_id": version_id,
            "results": [
                {"iri": r["iri"], "label": r["label"], "short": r["short"],
                 "type": r.get("type", ""), "match_type": "entity"}
                for r in results
            ],
            "count": len(results), "truncated": len(results) >= limit,
            "semantic_results": sem_results,
        }

    try:
        from ontoexplorer.modules.search.evaluator import (
            build_resolver, enrich_labels, _collect_refs,
        )
        _refs, _needs_classes = _collect_refs(ast)
        _resolver = await build_resolver(db, version_id, _refs, need_classes=_needs_classes)
        search_results = await evaluate(ast, version_id, ontology_id, _resolver, lang=effective_lang, direct=direct, reasoner=version.reasoner)
    except AmbiguousLabelError as exc:
        return JSONResponse(status_code=422, content={
            "error": "ambiguous_label", "label": exc.label, "candidates": exc.candidates,
        })
    except ReasoningNotReadyError:
        return JSONResponse(status_code=503, content={"error": "not_classified"})

    trimmed = search_results[:limit]
    _rows = [
        {"iri": r.iri, "label": r.label, "short": r.short, "match_type": r.match_type,
         "type": "class", "version_id": version_id,
         "lang": r.lang, "cross_language": r.cross_language}
        for r in trimmed
    ]
    # Restore result labels not in the ref-scoped resolver (see fan-out above).
    await enrich_labels(db, _rows, effective_lang)
    for _row in _rows:
        _row.pop("version_id", None)
    return {
        "mode": "expression", "query": q, "version_id": version_id,
        "results": _rows,
        "count": len(trimmed), "truncated": len(search_results) > limit,
        "semantic_results": [],
    }


# ── Global cross-ontology autocomplete ────────────────────────────────────────

@router.get("/autocomplete", summary="Cross-ontology MOS autocomplete")
async def global_autocomplete(
    q: str = Query(..., description="Partial MOS expression text"),
    cursor: int = Query(-1, description="Byte offset of cursor (-1 = end of q)"),
    limit: int = Query(10, ge=1, le=50),
    ontology_ids: list[str] = Query(default=[]),
    lang: str | None = Query(None, description="BCP-47 language tag"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    effective_cursor = cursor if cursor >= 0 else len(q)

    # Short-TTL response cache — autocomplete fires per-keystroke, so the same
    # prefix is requested repeatedly across users.
    cache_key = _autocomplete_cache_key(q, effective_cursor, limit, ontology_ids, lang)
    from ontoexplorer.modules.search.indexer import _get_redis
    _r = _get_redis()
    cached = await asyncio.to_thread(_r.get, cache_key)
    if cached:
        return _json.loads(cached)

    # Single shared MOS autocomplete implementation, scoped to the selected
    # ontologies (empty = all). When specific ontologies are selected, resolve
    # their latest-version graphs so filler suggestions work here too; skip when
    # scope is "all" (querying every graph for fillers is too broad).
    filler_scope = None
    if ontology_ids:
        from ontoexplorer.clients.oxigraph import graph_iri
        sel = set(ontology_ids)
        filler_scope = [
            (str(v.id), graph_iri(str(v.ontology_id), str(v.id)))
            for v in await _latest_ingested_versions(db)
            if str(v.ontology_id) in sel
        ][:25]
    from ontoexplorer.modules.search.autocomplete import mos_autocomplete
    completions, ctx = await mos_autocomplete(
        db, q, effective_cursor, limit, ontology_ids=ontology_ids or None,
        filler_scope=filler_scope)

    payload = {
        "completions": completions,
        "context": ctx.token_type.lower(),
        "replace_from": ctx.token_start,
        "replace_to": effective_cursor,
    }
    await asyncio.to_thread(_r.set, cache_key, _json.dumps(payload), _AUTOCOMPLETE_CACHE_TTL)
    return payload


# ── Per-ontology autocomplete (latest version) ────────────────────────────────

@router.get("/ontologies/{ontology_id}/autocomplete",
            summary="MOS autocomplete for an ontology (latest version)")
async def ontology_autocomplete(
    ontology_id: str,
    q: str = Query(..., description="Partial MOS expression text"),
    cursor: int = Query(-1, description="Byte offset of cursor (-1 = end of q)"),
    limit: int = Query(10, ge=1, le=50),
    lang: str | None = Query(None, description="BCP-47 language tag"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_latest_version_or_404(db, ontology_id)
    version_id = str(version.id)
    effective_cursor = cursor if cursor >= 0 else len(q)
    from ontoexplorer.clients.oxigraph import graph_iri
    from ontoexplorer.modules.search.autocomplete import mos_autocomplete
    completions, ctx = await mos_autocomplete(
        db, q, effective_cursor, limit, version_id=version_id,
        filler_scope=[(version_id, graph_iri(ontology_id, version_id))],
    )
    return {
        "version_id": version_id,
        "completions": completions,
        "context": ctx.token_type.lower(),
        "replace_from": ctx.token_start,
        "replace_to": effective_cursor,
    }
