"""Global cross-ontology search — GET /api/v1/search."""
import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.reasoning import ReasoningNotReadyError
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import get_current_user
from ontoexplorer.modules.search.autocomplete import get_completions
from ontoexplorer.modules.search.evaluator import AmbiguousLabelError, evaluate
from ontoexplorer.modules.search.indexer import entity_lookup, normalise_label
from ontoexplorer.modules.search.lang import resolve_lang
from ontoexplorer.modules.search.mos_parser import ParseError, NamedClass, parse
from ontoexplorer.modules.search.semantic import semantic_search
from ontoexplorer.modules.search.versions import (
    latest_ready_version as _get_latest_version_or_404,
    latest_ready_versions as _latest_ingested_versions,
)

router = APIRouter(prefix="/api/v1", tags=["search"])


def _is_expression(node) -> bool:
    return not isinstance(node, NamedClass)


# ── Repository-wide languages ─────────────────────────────────────────────────

@router.get("/languages", summary="All languages present across indexed ontologies")
async def get_repository_languages():
    """Aggregate language tags from every indexed ontology version in Redis."""
    import asyncio

    def _aggregate() -> list[dict]:
        from ontoexplorer.modules.search.indexer import _get_redis, _langs_key
        r = _get_redis()
        counts: dict[str, int] = {}
        prefix = "search:meta:"
        for meta_key in r.scan_iter(f"{prefix}*"):
            meta = r.hgetall(meta_key)
            if meta.get("schema_version") != "v2":
                continue
            version_id = meta_key[len(prefix):]
            for lang, count in r.hgetall(_langs_key(version_id)).items():
                counts[lang] = counts.get(lang, 0) + int(count)
        return sorted(
            [{"lang": k, "label_count": v} for k, v in counts.items()],
            key=lambda x: -x["label_count"],
        )

    return await asyncio.to_thread(_aggregate)


# ── Global search ─────────────────────────────────────────────────────────────

@router.get("/search", summary="Cross-ontology entity or MOS expression search")
async def global_search(
    q: str = Query(..., min_length=1, description="Entity label, CURIE, IRI, or MOS expression"),
    mode: str = Query("auto", description="auto | entity | expression"),
    limit: int = Query(20, ge=1, le=200),
    lang: str | None = Query(None, description="BCP-47 language tag for preferred results"),
    semantic: bool = Query(False, description="Include vector semantic results"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    effective_lang = lang or (getattr(_user, 'preferred_lang', None) if isinstance(_user, User) else None)
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
        # Fetch more candidates per version than the final limit so that exact
        # matches in any ontology are not discarded before global re-ranking.
        per_version = max(limit, 20)

        async def search_one_entity(v: OntologyVersion) -> list[dict]:
            rows = await asyncio.to_thread(entity_lookup, str(v.id), q, None, per_version)
            for r in rows:
                r["version_id"] = str(v.id)
                r["ontology_id"] = str(v.ontology_id)
                r.setdefault("type", "")
            return rows

        nested = await asyncio.gather(*[search_one_entity(v) for v in versions])
        for rows in nested:
            for row in rows:
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
        merged = merged[:limit]

        sem_results: list[dict] = []
        if semantic and len(q) >= 3:
            version_id_strs = [str(v.id) for v in versions]
            sem_results = await semantic_search(q, db, version_id_strs, limit=10)

        return {
            "mode": "entity", "query": q, "results": merged,
            "count": len(merged), "truncated": len(merged) >= limit,
            "semantic_results": sem_results,
        }

    # Expression mode — evaluate against each version separately
    warnings: list[dict] = []

    async def search_one_expression(v: OntologyVersion) -> list[dict]:
        try:
            results = await evaluate(ast, str(v.id), str(v.ontology_id), lang=effective_lang)
            return [
                {"iri": r.iri, "label": r.label, "short": r.short, "match_type": r.match_type,
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
        search_results = await evaluate(ast, version_id, ontology_id, lang=effective_lang, direct=direct)
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
    from ontoexplorer.modules.search.mos_parser import partial_parse

    effective_cursor = cursor if cursor >= 0 else len(q)
    ctx = partial_parse(q, effective_cursor)

    if ontology_ids:
        gathered = await asyncio.gather(
            *[_get_latest_version_or_404(db, oid) for oid in ontology_ids],
            return_exceptions=True,
        )
        versions = [v for v in gathered if isinstance(v, OntologyVersion)]
    else:
        versions = await _latest_ingested_versions(db)

    if not versions:
        return {
            "completions": [],
            "context": ctx.token_type.lower(),
            "replace_from": ctx.token_start,
            "replace_to": effective_cursor,
        }

    # Load ontology shortnames for all versions in one query
    ont_ids = list({str(v.ontology_id) for v in versions})
    ont_rows = (await db.execute(
        select(Ontology).where(Ontology.id.in_(ont_ids))
    )).scalars().all()

    def _shortname(ont: Ontology) -> str:
        if ont.shortname:
            return ont.shortname
        last = ont.iri.rstrip("/#").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        return last

    ont_by_id = {str(o.id): _shortname(o) for o in ont_rows}
    # Map version_id → ontology_shortname
    ver_shortname = {str(v.id): ont_by_id.get(str(v.ontology_id), "") for v in versions}

    all_nested = await asyncio.gather(*[
        asyncio.to_thread(get_completions, q, effective_cursor, str(v.id), limit, lang)
        for v in versions
    ])

    seen_iris: set[str] = set()
    seen_kws: set[str] = set()
    merged: list[tuple] = []  # (Completion, ontology_shortname)
    for v, completions in zip(versions, all_nested):
        sn = ver_shortname.get(str(v.id), "")
        for c in completions:
            if c.iri is None:
                if c.text not in seen_kws:
                    seen_kws.add(c.text)
                    merged.append((c, None))
            elif c.iri not in seen_iris:
                seen_iris.add(c.iri)
                merged.append((c, sn))

    norm_q = normalise_label(ctx.partial or "")

    def _rank(item: tuple) -> tuple:
        c, _ = item
        if c.iri is None:
            return (0, c.text)
        lbl = normalise_label(c.text)
        if lbl == norm_q:
            return (1, lbl)
        if lbl.startswith(norm_q):
            return (2, lbl)
        return (3, lbl)

    merged.sort(key=_rank)
    merged = merged[:limit]

    return {
        "completions": [
            {"text": c.text, "type": c.type, "iri": c.iri, "short": c.short, "insert": c.insert,
             "lang": c.lang, "cross_language": c.cross_language, "ontology_shortname": sn}
            for c, sn in merged
        ],
        "context": ctx.token_type.lower(),
        "replace_from": ctx.token_start,
        "replace_to": effective_cursor,
    }


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
    ontology_row = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()
    effective_lang = resolve_lang(lang, ontology_row, _user if isinstance(_user, User) else None)
    effective_cursor = cursor if cursor >= 0 else len(q)
    completions = await asyncio.to_thread(get_completions, q, effective_cursor, version_id, limit, effective_lang)
    from ontoexplorer.modules.search.mos_parser import partial_parse
    ctx = partial_parse(q, effective_cursor)
    return {
        "version_id": version_id,
        "completions": [
            {"text": c.text, "type": c.type, "iri": c.iri, "short": c.short, "insert": c.insert,
             "lang": c.lang, "cross_language": c.cross_language}
            for c in completions
        ],
        "context": ctx.token_type.lower(),
        "replace_from": ctx.token_start,
        "replace_to": effective_cursor,
    }
