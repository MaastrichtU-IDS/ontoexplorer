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
from ontoexplorer.modules.search.indexer import entity_lookup, entity_lookup_multi, normalise_label
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
# the home page loads it on every visit. Cache it, and compute it with pipelined
# Redis reads — the previous per-version round-trips took ~9s across ~1900 ontologies.
_REPO_LANGS_CACHE_KEY = "repo:languages:v2"
_REPO_LANGS_TTL = 300  # seconds


@router.get("/languages", summary="All languages present across indexed ontologies")
async def get_repository_languages():
    """Aggregate language tags from every indexed ontology version in Redis."""
    import asyncio
    import json as _json

    def _aggregate() -> list[dict]:
        from ontoexplorer.modules.search.indexer import _get_redis, _langs_key
        from ontoexplorer.modules.search.lang import canonical_lang
        r = _get_redis()

        cached = r.get(_REPO_LANGS_CACHE_KEY)
        if cached:
            return _json.loads(cached)

        prefix = "search:meta:"
        meta_keys = list(r.scan_iter(f"{prefix}*", count=5000))

        # Keep only v2-schema versions — one pipelined batch instead of a full
        # hgetall round-trip per key.
        pipe = r.pipeline(transaction=False)
        for k in meta_keys:
            pipe.hget(k, "schema_version")
        schema_versions = pipe.execute()
        version_ids = [
            k[len(prefix):] for k, sv in zip(meta_keys, schema_versions) if sv == "v2"
        ]

        # Fetch every version's language counts in a single pipelined batch.
        pipe2 = r.pipeline(transaction=False)
        for vid in version_ids:
            pipe2.hgetall(_langs_key(vid))
        lang_maps = pipe2.execute()

        counts: dict[str, int] = {}
        for mapping in lang_maps:
            for lang, count in (mapping or {}).items():
                key = canonical_lang(lang)
                counts[key] = counts.get(key, 0) + int(count)

        result = sorted(
            [{"lang": k, "label_count": v} for k, v in counts.items()],
            key=lambda x: x["lang"],
        )
        try:
            r.set(_REPO_LANGS_CACHE_KEY, _json.dumps(result), ex=_REPO_LANGS_TTL)
        except Exception:
            pass
        return result

    return await asyncio.to_thread(_aggregate)


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
        if backend == "pg":
            # Postgres-backed path: one SQL query over entity_index, no fan-out.
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
        else:
            # Redis-backed path: cross-version multi-pipeline.
            # Fetch more candidates per version than the final limit so that exact
            # matches in any ontology are not discarded before global re-ranking.
            per_version = max(limit, 20)

            version_ids = [str(v.id) for v in versions]
            ont_by_vid = {str(v.id): str(v.ontology_id) for v in versions}
            per_vid = await asyncio.to_thread(entity_lookup_multi, version_ids, q, None, per_version)

            for vid in version_ids:
                for row in per_vid.get(vid, []):
                    row["version_id"] = vid
                    row["ontology_id"] = ont_by_vid[vid]
                    row.setdefault("type", "")
                    if row["iri"] not in seen_iris:
                        seen_iris.add(row["iri"])
                        merged.append(row)

            # Re-rank globally: exact label match → prefix → word-suffix, then alpha.
            norm_q = normalise_label(q)

            def _global_rank(row: dict) -> tuple:
                lbl = normalise_label(row.get("label", ""))
                if lbl == norm_q:
                    return (0, lbl)
                if lbl.startswith(norm_q):
                    return (1, lbl)
                return (2, lbl)

            merged.sort(key=_global_rank)
            if types:
                merged = [r for r in merged if r.get("type") in types]
            merged = merged[:limit]

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

    async def search_one_expression(v: OntologyVersion) -> list[dict]:
        try:
            results = await evaluate(ast, str(v.id), str(v.ontology_id), lang=effective_lang, reasoner=v.reasoner)
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

    nested = await asyncio.gather(*[search_one_expression(v) for v in versions])
    for rows in nested:
        for row in rows:
            if row["iri"] not in seen_iris:
                seen_iris.add(row["iri"])
                merged.append(row)
                if len(merged) >= limit:
                    break
        if len(merged) >= limit:
            break

    return {"mode": "expression", "query": q, "results": merged[:limit],
            "count": len(merged[:limit]), "truncated": len(merged) > limit,
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
        results = await asyncio.to_thread(entity_lookup, version_id, q, None, limit)
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
        search_results = await evaluate(ast, version_id, ontology_id, lang=effective_lang, direct=direct, reasoner=version.reasoner)
    except AmbiguousLabelError as exc:
        return JSONResponse(status_code=422, content={
            "error": "ambiguous_label", "label": exc.label, "candidates": exc.candidates,
        })
    except ReasoningNotReadyError:
        return JSONResponse(status_code=503, content={"error": "not_classified"})

    trimmed = search_results[:limit]
    return {
        "mode": "expression", "query": q, "version_id": version_id,
        "results": [
            {"iri": r.iri, "label": r.label, "short": r.short, "match_type": r.match_type,
             "type": "class",
             "lang": r.lang, "cross_language": r.cross_language}
            for r in trimmed
        ],
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
