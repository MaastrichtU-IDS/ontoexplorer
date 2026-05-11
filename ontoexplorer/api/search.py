"""MOS Search API — GET /search and GET /autocomplete per ontology version."""
import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ontologies import _get_version_or_404
from ontoexplorer.clients.reasoning import ReasoningNotReadyError
from ontoexplorer.database import get_db
from ontoexplorer.modules.auth.dependencies import get_current_user
from ontoexplorer.modules.search.autocomplete import get_completions
from ontoexplorer.modules.search.evaluator import AmbiguousLabelError, evaluate
from ontoexplorer.modules.search.indexer import entity_lookup
from ontoexplorer.modules.search.mos_parser import ParseError, parse, NamedClass, And, Or, Not

router = APIRouter(
    prefix="/api/v1/ontologies/{ontology_id}/{version_id}",
    tags=["search"],
)


def _is_expression(node) -> bool:
    """True if the AST contains any restriction or boolean operator (not just a bare NamedClass)."""
    if isinstance(node, NamedClass):
        return False
    return True


@router.get("/search", summary="MOS entity lookup or expression query")
async def search(
    ontology_id: str,
    version_id: str,
    q: str = Query(..., description="Entity label, CURIE, IRI, or MOS expression"),
    mode: str = Query("auto", description="auto | entity | expression"),
    limit: int = Query(20, ge=1, le=200),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)

    # Determine effective mode
    effective_mode = mode
    ast = None
    if mode in ("auto", "expression"):
        try:
            ast = parse(q)
            if mode == "auto":
                effective_mode = "expression" if _is_expression(ast) else "entity"
        except ParseError as exc:
            if mode == "expression":
                return JSONResponse(
                    status_code=400,
                    content={"error": "parse_error", "message": str(exc)},
                )
            effective_mode = "entity"

    if effective_mode == "entity":
        results = await asyncio.to_thread(entity_lookup, version_id, q, None, limit)
        return {
            "mode": "entity",
            "query": q,
            "results": [
                {"iri": r["iri"], "label": r["label"], "short": r["short"], "match_type": "entity"}
                for r in results
            ],
            "count": len(results),
            "truncated": len(results) >= limit,
        }

    # Expression mode
    try:
        search_results = await evaluate(ast, version_id)
    except AmbiguousLabelError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": "ambiguous_label",
                "label": exc.label,
                "candidates": exc.candidates,
            },
        )
    except ReasoningNotReadyError:
        return JSONResponse(
            status_code=503,
            content={"error": "not_classified"},
        )

    trimmed = search_results[:limit]
    return {
        "mode": "expression",
        "query": q,
        "results": [
            {"iri": r.iri, "label": r.label, "short": r.short, "match_type": r.match_type}
            for r in trimmed
        ],
        "count": len(trimmed),
        "truncated": len(search_results) > limit,
    }


@router.get("/autocomplete", summary="Context-sensitive MOS autocomplete")
async def autocomplete(
    ontology_id: str,
    version_id: str,
    q: str = Query(..., description="Partial MOS expression text"),
    cursor: int = Query(-1, description="Byte offset of cursor (-1 = end of q)"),
    limit: int = Query(10, ge=1, le=50),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    effective_cursor = cursor if cursor >= 0 else len(q)
    completions = await asyncio.to_thread(
        get_completions, q, effective_cursor, version_id, limit
    )
    from ontoexplorer.modules.search.mos_parser import partial_parse
    ctx = partial_parse(q, effective_cursor)
    return {
        "completions": [
            {"text": c.text, "type": c.type, "iri": c.iri, "short": c.short, "insert": c.insert}
            for c in completions
        ],
        "context": ctx.token_type.lower(),
    }
