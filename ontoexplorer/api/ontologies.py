"""Ontologies REST API — submit, list, metadata, versions, terms, download, deprecate."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.reasoning import (
    ClassNotFoundError,
    ReasoningNotReadyError,
    consistency as elk_consistency,
    subclasses as elk_subclasses,
    superclasses as elk_superclasses,
)
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import get_current_user, require_auth
from ontoexplorer.modules.storage.minio_client import ontology_download_url

router = APIRouter(prefix="/api/v1/ontologies", tags=["ontologies"])

_RDF_FORMATS = {"text/turtle": "turtle", "application/rdf+xml": "xml", "application/n-triples": "nt"}


# ── Submit ─────────────────────────────────────────────────────────────────────

class SubmitByIri(BaseModel):
    iri: str


class SubmitByUrl(BaseModel):
    url: str


@router.post("", summary="Submit ontology by IRI, URL, or file upload")
async def submit_ontology(
    request: Request,
    file: UploadFile | None = File(default=None),
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    content_type = request.headers.get("content-type", "")
    owner_id = user.id if user else None

    if "multipart/form-data" in content_type and file:
        raw = await file.read()
        task = ingest_ontology.delay(
            raw_bytes_hex=raw.hex(),
            filename=file.filename,
            content_type=file.content_type,
            owner_id=owner_id,
        )
        return {"task_id": task.id, "status": "queued"}

    body = await request.json()
    if "iri" in body:
        task = ingest_ontology.delay(iri=body["iri"], owner_id=owner_id)
    elif "url" in body:
        task = ingest_ontology.delay(url=body["url"], owner_id=owner_id)
    elif "content" in body:
        raw = body["content"].encode()
        task = ingest_ontology.delay(
            raw_bytes_hex=raw.hex(),
            content_type=body.get("format"),
            owner_id=owner_id,
        )
    else:
        raise HTTPException(status_code=422, detail="Provide 'iri', 'url', 'content', or a file upload")

    return {"task_id": task.id, "status": "queued"}


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("", summary="List ontologies")
async def list_ontologies(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ontology).order_by(Ontology.created_at.desc()).offset(offset).limit(limit))
    ontologies = result.scalars().all()
    return {"ontologies": [_ontology_dict(o) for o in ontologies], "offset": offset, "limit": limit}


# ── Single ontology metadata ───────────────────────────────────────────────────

@router.get("/{ontology_id}", summary="Ontology metadata")
async def get_ontology(ontology_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    ontology = await _get_ontology_or_404(db, ontology_id)
    data = _ontology_dict(ontology)
    return _negotiate_response(request, data, subject_iri=ontology.iri)


@router.get("/{ontology_id}/versions", summary="All versions with provenance")
async def list_versions(ontology_id: str, db: AsyncSession = Depends(get_db)):
    await _get_ontology_or_404(db, ontology_id)
    result = await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .order_by(OntologyVersion.created_at.desc())
    )
    versions = result.scalars().all()
    return {"versions": [_version_dict(v) for v in versions]}


@router.get("/{ontology_id}/{version_id}", summary="Specific version metadata")
async def get_version(ontology_id: str, version_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    version = await _get_version_or_404(db, ontology_id, version_id)
    data = _version_dict(version)
    return _negotiate_response(request, data)


# ── Download ───────────────────────────────────────────────────────────────────

@router.get("/{ontology_id}/{version_id}/download", summary="Download ontology artifact")
async def download_version(ontology_id: str, version_id: str, db: AsyncSession = Depends(get_db)):
    version = await _get_version_or_404(db, ontology_id, version_id)
    url = ontology_download_url(version.minio_key)
    return RedirectResponse(url=url)


# ── Terms ──────────────────────────────────────────────────────────────────────

@router.get("/{ontology_id}/{version_id}/terms", summary="List terms (classes)")
async def list_terms(
    ontology_id: str,
    version_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    import pyoxigraph

    store = get_store()
    named_graph = pyoxigraph.NamedNode(graph_iri(ontology_id, version_id))

    query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?class ?label WHERE {{
            GRAPH <{graph_iri(ontology_id, version_id)}> {{
                ?class a owl:Class .
                OPTIONAL {{ ?class rdfs:label ?label }}
            }}
        }}
        ORDER BY ?class
        LIMIT {limit} OFFSET {offset}
    """
    results = store.query(query)
    terms = []
    for row in results:
        terms.append({
            "iri": str(row["class"]),
            "label": str(row["label"]) if row.get("label") else None,
        })
    return {"terms": terms, "offset": offset, "limit": limit}


@router.get("/{ontology_id}/{version_id}/terms/{term_iri:path}", summary="Term detail")
async def get_term(
    ontology_id: str,
    version_id: str,
    term_iri: str,
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.oxigraph import get_store, graph_iri

    store = get_store()
    g_iri = graph_iri(ontology_id, version_id)

    query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?pred ?obj WHERE {{
            GRAPH <{g_iri}> {{
                <{term_iri}> ?pred ?obj .
            }}
        }}
    """
    results = list(store.query(query))
    if not results:
        raise HTTPException(status_code=404, detail="Term not found in this ontology version")

    properties: dict[str, list] = {}
    for row in results:
        pred = str(row["pred"])
        obj = str(row["obj"])
        properties.setdefault(pred, []).append(obj)

    return {"iri": term_iri, "properties": properties}


# ── Inferred axioms ────────────────────────────────────────────────────────────

@router.get("/{ontology_id}/{version_id}/inferred", summary="Inferred subclass axioms from OWL-EL reasoning")
async def list_inferred(
    ontology_id: str,
    version_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Return inferred subClassOf axioms for a version.
    The :inferred named graph is populated by the reason_ontology Celery task.
    Returns 404 if reasoning has not yet completed.
    """
    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.oxigraph import get_store, graph_iri

    store = get_store()
    inferred_iri = graph_iri(ontology_id, version_id, inferred=True)

    query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?sub ?sup WHERE {{
            GRAPH <{inferred_iri}> {{
                ?sub rdfs:subClassOf ?sup .
                FILTER(isIRI(?sub) && isIRI(?sup))
            }}
        }}
        ORDER BY ?sub ?sup
        LIMIT {limit} OFFSET {offset}
    """
    try:
        results = list(store.query(query))
    except Exception:
        results = []

    axioms = [{"subClass": str(r["sub"]), "superClass": str(r["sup"])} for r in results]
    return {
        "version_id": version_id,
        "ontology_id": ontology_id,
        "inferred_graph": inferred_iri,
        "axioms": axioms,
        "offset": offset,
        "limit": limit,
    }


# ── Reasoning query endpoints ──────────────────────────────────────────────────

@router.get("/{ontology_id}/{version_id}/superclasses", summary="Inferred superclasses of a class")
async def get_superclasses(
    ontology_id: str,
    version_id: str,
    cls: str = Query(..., description="Class IRI to look up"),
    direct: bool = Query(False, description="Return only directly asserted superclasses"),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    try:
        return await elk_superclasses(version_id, cls, direct=direct)
    except ReasoningNotReadyError:
        raise HTTPException(409, "Reasoning not yet completed — trigger via POST .../reason")
    except ClassNotFoundError:
        raise HTTPException(404, f"Class {cls!r} not found in classification index")
    except Exception:
        raise HTTPException(503, "Reasoning service unavailable")


@router.get("/{ontology_id}/{version_id}/subclasses", summary="Inferred subclasses of a class")
async def get_subclasses(
    ontology_id: str,
    version_id: str,
    cls: str = Query(..., description="Class IRI to look up"),
    direct: bool = Query(False, description="Return only directly asserted subclasses"),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    try:
        return await elk_subclasses(version_id, cls, direct=direct)
    except ReasoningNotReadyError:
        raise HTTPException(409, "Reasoning not yet completed — trigger via POST .../reason")
    except ClassNotFoundError:
        raise HTTPException(404, f"Class {cls!r} not found in classification index")
    except Exception:
        raise HTTPException(503, "Reasoning service unavailable")


@router.get("/{ontology_id}/{version_id}/consistency", summary="Consistency check for a version")
async def get_consistency(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    try:
        return await elk_consistency(version_id)
    except ReasoningNotReadyError:
        raise HTTPException(409, "Reasoning not yet completed — trigger via POST .../reason")
    except Exception:
        raise HTTPException(503, "Reasoning service unavailable")


class JustificationRequest(BaseModel):
    sub: str
    sup: str | None = None
    type: str | None = None         # "unsatisfiable" when sup is omitted
    max_justifications: int = 1     # 0 = find all


@router.post("/{ontology_id}/{version_id}/justification", summary="Request async justification computation")
async def request_justification(
    ontology_id: str,
    version_id: str,
    body: JustificationRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.modules.jobs.tasks import compute_justification
    task = compute_justification.delay(
        version_id=version_id,
        ontology_id=ontology_id,
        sub=body.sub,
        sup=body.sup,
        max_justifications=body.max_justifications,
    )
    return {"job_id": task.id, "status": "queued", "sub": body.sub, "sup": body.sup}


@router.get("/{ontology_id}/{version_id}/justification/{job_id}", summary="Retrieve justification result")
async def get_justification_result(
    ontology_id: str,
    version_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tracker import get_job
    job = await get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ("pending", "running"):
        return {"job_id": job_id, "status": job.status}
    if job.status == "failed":
        raise HTTPException(500, f"Justification job failed: {job.error}")
    # Job done — result is stored in ELK Redis; retrieve via Celery result backend
    from ontoexplorer.modules.jobs.tasks import celery_app
    result = celery_app.AsyncResult(job_id)
    if result.ready():
        return result.get()
    raise HTTPException(202, "Job complete but result not yet available — retry shortly")


# ── Deprecate ──────────────────────────────────────────────────────────────────

@router.delete("/{ontology_id}/{version_id}", summary="Deprecate a version (soft delete)")
async def deprecate_version(
    ontology_id: str,
    version_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_version_or_404(db, ontology_id, version_id)
    if version.status == "deprecated":
        raise HTTPException(status_code=409, detail="Version is already deprecated")

    await db.execute(
        update(OntologyVersion)
        .where(OntologyVersion.id == version_id)
        .values(status="deprecated")
    )
    await db.commit()

    # Invalidate ELK classification cache for this version
    try:
        from ontoexplorer.clients.reasoning import invalidate_cache
        await invalidate_cache(version_id)
    except Exception:
        pass  # Non-fatal — TTL will expire anyway

    # Invalidate search entity index for this version
    try:
        import asyncio
        from ontoexplorer.modules.search.indexer import invalidate_index
        await asyncio.to_thread(invalidate_index, version_id)
    except Exception:
        pass  # Non-fatal

    return {"detail": f"Version {version_id} deprecated"}


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_ontology_or_404(db: AsyncSession, ontology_id: str) -> Ontology:
    result = await db.execute(select(Ontology).where(Ontology.id == ontology_id))
    ontology = result.scalar_one_or_none()
    if not ontology:
        raise HTTPException(status_code=404, detail="Ontology not found")
    return ontology


async def _get_version_or_404(db: AsyncSession, ontology_id: str, version_id: str) -> OntologyVersion:
    result = await db.execute(
        select(OntologyVersion).where(
            OntologyVersion.id == version_id,
            OntologyVersion.ontology_id == ontology_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _ontology_dict(o: Ontology) -> dict:
    return {"id": o.id, "iri": o.iri, "created_at": o.created_at.isoformat()}


def _version_dict(v: OntologyVersion) -> dict:
    return {
        "id": v.id,
        "ontology_id": v.ontology_id,
        "version_iri": v.version_iri,
        "format": v.format,
        "status": v.status,
        "sha256": v.sha256,
        "download_url": f"/api/v1/ontologies/{v.ontology_id}/{v.id}/download",
        "created_at": v.created_at.isoformat(),
    }


def _negotiate_response(request: Request, data: dict, subject_iri: str | None = None) -> Response:
    accept = request.headers.get("accept", "application/json")
    if "text/turtle" in accept or "application/rdf+xml" in accept:
        import rdflib
        from rdflib import Literal, URIRef
        from rdflib.namespace import DCTERMS, RDF
        g = rdflib.Graph()
        subj = URIRef(subject_iri or data.get("iri", "urn:unknown"))
        for k, v in data.items():
            if v is not None:
                g.add((subj, DCTERMS[k], Literal(str(v))))
        fmt = "turtle" if "text/turtle" in accept else "xml"
        ct = "text/turtle" if fmt == "turtle" else "application/rdf+xml"
        return Response(content=g.serialize(format=fmt), media_type=ct)
    return JSONResponse(data)
