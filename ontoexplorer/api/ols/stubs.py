"""OLS4-compat stubs for unsupported surfaces.

These endpoints return 501 Not Implemented with an explanatory body.
The shim implements Tier 1 (full backend) and Tier 2 (derived UI widgets);
Tier 3 surfaces have no backing data, so we surface them as stubs that
explain why they're not available.

All routes return:
    {"error": "not_implemented", "message": "…", "ols_path": "<path>"}

Route registration order is critical: this router should be included
BEFORE classes_v2.router in router.py so that more-specific stub paths
(e.g. /api/v2/classes/{iri}/llm_embedding) match before the generic
/api/v2/classes/{iri_path:path} catch-all.

Also include BEFORE terms.router so /api/ontologies/{onto}/terms/preferredRoots
matches before the /api/ontologies/{onto}/terms/{iri_path:path} catch-all.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


def _stub(request: Request, reason: str) -> JSONResponse:
    """Return a 501 Not Implemented response with the given reason."""
    return JSONResponse(
        status_code=501,
        content={
            "error": "not_implemented",
            "message": reason,
            "ols_path": request.url.path,
        },
    )


# ---------------------------------------------------------------------------
# Text annotation / NER
# ---------------------------------------------------------------------------


@router.get("/api/v2/tag_text")
@router.post("/api/v2/tag_text")
async def tag_text_stub(request: Request) -> JSONResponse:
    """Stub: Text annotation / NER not implemented."""
    return _stub(request, "Text annotation / NER not implemented")


# ---------------------------------------------------------------------------
# Curation metadata
# ---------------------------------------------------------------------------


@router.get("/api/v2/curation_sources")
async def curation_sources_stub(request: Request) -> JSONResponse:
    """Stub: SSSOM mapping sources not implemented."""
    return _stub(request, "SSSOM mapping sources not implemented")


# ---------------------------------------------------------------------------
# Ontology grouping
# ---------------------------------------------------------------------------


@router.get("/api/v2/ontologies/by-tag")
async def ontologies_by_tag_stub(request: Request) -> JSONResponse:
    """Stub: Ontology tag grouping not implemented."""
    return _stub(request, "Ontology tag grouping not implemented")


@router.get("/api/v2/ontologies/by-domain")
async def ontologies_by_domain_stub(request: Request) -> JSONResponse:
    """Stub: Ontology domain grouping not implemented."""
    return _stub(request, "Ontology domain grouping not implemented")


# ---------------------------------------------------------------------------
# Term curation
# ---------------------------------------------------------------------------


@router.get("/api/ontologies/{ontology_id}/terms/preferredRoots")
async def preferred_roots_stub(ontology_id: str, request: Request) -> JSONResponse:
    """Stub: Preferred roots curation not implemented."""
    return _stub(request, "Preferred roots curation not implemented")


# ---------------------------------------------------------------------------
# LLM embedding write surfaces
# ---------------------------------------------------------------------------


@router.post("/api/v2/classes/llm_embedding")
async def class_embedding_write_stub(request: Request) -> JSONResponse:
    """Stub: Raw embedding write surface not exposed."""
    return _stub(request, "Raw embedding write surface not exposed")


@router.post("/api/v2/ontologies/{ontology_id}/classes/llm_embedding")
async def class_embedding_write_scoped_stub(
    ontology_id: str, request: Request
) -> JSONResponse:
    """Stub: Raw embedding write surface not exposed."""
    return _stub(request, "Raw embedding write surface not exposed")


# ---------------------------------------------------------------------------
# LLM embedding read surfaces (per-class, pairwise)
# ---------------------------------------------------------------------------


@router.get("/api/v2/classes/{iri_path:path}/llm_embedding")
async def class_embedding_read_stub(
    iri_path: str, request: Request
) -> JSONResponse:
    """Stub: Per-class embedding read not exposed (bandwidth)."""
    return _stub(request, "Per-class embedding read not exposed (bandwidth)")


@router.get("/api/v2/classes/{class1_iri}/llm_similarity/{class2_iri:path}")
async def llm_similarity_pair_stub(
    class1_iri: str, class2_iri: str, request: Request
) -> JSONResponse:
    """Stub: Pairwise embedding similarity not implemented."""
    return _stub(
        request,
        "Pairwise embedding similarity not implemented (use /llm_similar instead)",
    )
