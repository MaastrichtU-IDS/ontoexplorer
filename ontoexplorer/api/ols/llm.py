"""OLS4-compat LLM endpoints.

Exposes four routes under /api/v2/:
  GET /llm_models                               — static embedder info
  GET /classes/llm_search?q=…                   — global semantic search
  GET /ontologies/{onto}/classes/llm_search?q=… — scoped semantic search
  GET /classes/{iri_path:path}/llm_similar       — nearest-neighbour lookup

Route registration order is critical: this router must be included in
router.py BEFORE the classes_v2 router to prevent the generic
/api/v2/classes/{iri_path:path} catch-all from consuming llm_search and
llm_similar paths.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ontoexplorer.api.ols._common import get_latest_version_or_404
from ontoexplorer.api.ols._envelope import v2_page
from ontoexplorer.api.ols._iri import double_decode_iri
from ontoexplorer.api.ols._shapes import derive_obo_id
from ontoexplorer.database import get_db
from ontoexplorer.modules.search.semantic import semantic_search
from ontoexplorer.modules.search.versions import latest_ready_versions

router = APIRouter()

# ---------------------------------------------------------------------------
# Embedder metadata (static)
# ---------------------------------------------------------------------------

_LLM_MODEL = {
    "id": "nomic-embed-text",
    "modelName": "nomic-embed-text-v1",
    "dimensions": 768,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _db_execute(db: AsyncSession, query, params: dict):
    """Thin wrapper around db.execute so tests can patch it cleanly."""
    return await db.execute(query, params)


def _result_to_v2(r: dict) -> dict:
    """Convert a semantic_search result dict to a v2 class shape with score."""
    return {
        "iri": r["iri"],
        "label": r["label"],
        "short_form": r.get("short", ""),
        "obo_id": derive_obo_id(r.get("short", "")),
        "ontology_name": r["ontology_id"],
        "ontology_prefix": r["ontology_id"].upper(),
        "is_defining_ontology": r.get("source") == r["ontology_id"] or not r.get("source"),
        "type": ["class", "entity"],
        "score": r["score"],
    }


# ---------------------------------------------------------------------------
# GET /api/v2/llm_models
# ---------------------------------------------------------------------------

@router.get("/api/v2/llm_models")
async def llm_models(request: Request):
    """Return static info about the embedded language model in use."""
    return v2_page([_LLM_MODEL], request, total=1, page=0, size=1)


# ---------------------------------------------------------------------------
# GET /api/v2/classes/llm_search
# Must be registered BEFORE the classes_v2 catch-all /api/v2/classes/{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/v2/classes/llm_search")
async def llm_search_global(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    rows: int = Query(10, ge=1, le=500),
    model: str | None = Query(None, description="Ignored; reserved for future use"),
    db: AsyncSession = Depends(get_db),
):
    """Global semantic search across all ready ontology versions."""
    versions = await latest_ready_versions(db)
    vids = [str(v.id) for v in versions]
    results = await semantic_search(q, db, vids, limit=rows)
    items = [_result_to_v2(r) for r in results]
    return v2_page(items, request, total=len(items), page=0, size=rows)


# ---------------------------------------------------------------------------
# GET /api/v2/ontologies/{onto}/classes/llm_search
# Must be registered BEFORE the classes_v2 per-ontology catch-all
# /api/v2/ontologies/{onto}/classes/{iri_path:path}
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies/{ontology_id}/classes/llm_search")
async def llm_search_scoped(
    ontology_id: str,
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    rows: int = Query(10, ge=1, le=500),
    model: str | None = Query(None, description="Ignored; reserved for future use"),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search scoped to one ontology's latest ready version."""
    version = await get_latest_version_or_404(db, ontology_id)
    vids = [str(version.id)]
    results = await semantic_search(q, db, vids, limit=rows)
    items = [_result_to_v2(r) for r in results]
    return v2_page(items, request, total=len(items), page=0, size=rows)


# ---------------------------------------------------------------------------
# GET /api/v2/classes/{iri_path:path}/llm_similar
# Must be registered BEFORE the classes_v2 catch-all /api/v2/classes/{iri_path:path}
# (FastAPI resolves the suffix /llm_similar only if registered first)
# ---------------------------------------------------------------------------

@router.get("/api/v2/classes/{iri_path:path}/llm_similar")
async def llm_similar(
    iri_path: str,
    request: Request,
    rows: int = Query(10, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return the nearest-neighbour embeddings to a stored entity embedding.

    The query entity is excluded from the result set.
    Neighbours are sorted by cosine similarity (highest first).
    """
    iri = double_decode_iri(iri_path)

    # Look up the stored embedding for this IRI (any version)
    src_result = await _db_execute(
        db,
        text("SELECT embedding FROM term_embeddings WHERE entity_iri = :iri LIMIT 1"),
        {"iri": iri},
    )
    src_row = src_result.first()
    if not src_row:
        raise HTTPException(status_code=404, detail=f"No embedding stored for {iri}")

    emb = src_row[0]

    # Nearest neighbours via pgvector cosine distance, excluding self
    neighbour_result = await _db_execute(
        db,
        text(
            "SELECT te.entity_iri AS iri, v.ontology_id, "
            "       1 - (te.embedding <=> :emb) AS score "
            "FROM term_embeddings te JOIN versions v ON v.id = te.version_id "
            "WHERE te.entity_iri != :iri "
            "ORDER BY te.embedding <=> :emb ASC LIMIT :n"
        ),
        {"emb": emb, "iri": iri, "n": rows},
    )
    neighbour_rows = neighbour_result.all()

    items = [
        {
            "iri": row.iri,
            "label": "",
            "ontology_name": row.ontology_id,
            "type": ["class", "entity"],
            "score": round(float(row.score), 4),
        }
        for row in neighbour_rows
    ]
    return v2_page(items, request, total=len(items), page=0, size=rows)
