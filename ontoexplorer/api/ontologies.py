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
    import asyncio
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    content_type = request.headers.get("content-type", "")
    owner_id = user.id if user else None
    loop = asyncio.get_event_loop()

    if "multipart/form-data" in content_type and file:
        raw = await file.read()
        task = await loop.run_in_executor(
            None,
            lambda: ingest_ontology.delay(
                raw_bytes_hex=raw.hex(),
                filename=file.filename,
                content_type=file.content_type,
                owner_id=owner_id,
            ),
        )
        return {"task_id": task.id, "status": "queued"}

    body = await request.json()
    if "iri" in body:
        task = await loop.run_in_executor(None, lambda: ingest_ontology.delay(iri=body["iri"], owner_id=owner_id))
    elif "url" in body:
        task = await loop.run_in_executor(None, lambda: ingest_ontology.delay(url=body["url"], owner_id=owner_id))
    elif "content" in body:
        raw = body["content"].encode()
        task = await loop.run_in_executor(
            None,
            lambda: ingest_ontology.delay(
                raw_bytes_hex=raw.hex(),
                content_type=body.get("format"),
                owner_id=owner_id,
            ),
        )
    else:
        raise HTTPException(status_code=422, detail="Provide 'iri', 'url', 'content', or a file upload")

    return {"task_id": task.id, "status": "queued"}


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("", summary="List ontologies")
async def list_ontologies(
    q: str | None = Query(None, description="Keyword filter on ontology ID or IRI"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Ontology)
    if q:
        pattern = f"%{q.lower()}%"
        from sqlalchemy import func
        stmt = stmt.where(
            func.lower(Ontology.id).like(pattern) | func.lower(Ontology.iri).like(pattern)
        )
    stmt = stmt.order_by(Ontology.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
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


_STATS_CACHE_TTL = 86_400  # 24 hours — versions are immutable once ingested


def _stats_cache_key(version_id: str) -> str:
    return f"version_stats:{version_id}"


@router.get("/{ontology_id}/{version_id}/stats", summary="VoID statistics for a version")
async def version_stats(ontology_id: str, version_id: str, db: AsyncSession = Depends(get_db)):
    import asyncio
    import json as _json

    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.search.indexer import _meta_key, _get_redis

    # ── Redis cache read-through ──────────────────────────────────────────────
    try:
        r = _get_redis()
        cached = r.get(_stats_cache_key(version_id))
        if cached:
            return _json.loads(cached)
    except Exception:
        pass

    # ── Compute: all queries run concurrently off the event loop ─────────────
    store = get_store()
    g = graph_iri(ontology_id, version_id)

    def _count(sparql: str) -> int:
        rows = list(store.query(sparql))
        if rows:
            v = rows[0]["n"]
            return int(v.value) if v is not None else 0
        return 0

    (
        triple_count,
        class_count,
        obj_prop_count,
        data_prop_count,
        ann_prop_count,
        ind_count,
    ) = await asyncio.gather(
        asyncio.to_thread(_count, f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{g}> {{ ?s ?p ?o }} }}"),
        asyncio.to_thread(_count, f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{
                GRAPH <{g}> {{ ?c a owl:Class . FILTER(isIRI(?c)) }}
            }}
        """),
        asyncio.to_thread(_count, f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE {{
                GRAPH <{g}> {{ ?p a owl:ObjectProperty . FILTER(isIRI(?p)) }}
            }}
        """),
        asyncio.to_thread(_count, f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE {{
                GRAPH <{g}> {{ ?p a owl:DatatypeProperty . FILTER(isIRI(?p)) }}
            }}
        """),
        asyncio.to_thread(_count, f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE {{
                GRAPH <{g}> {{ ?p a owl:AnnotationProperty . FILTER(isIRI(?p)) }}
            }}
        """),
        asyncio.to_thread(_count, f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE {{
                GRAPH <{g}> {{ ?i a owl:NamedIndividual . FILTER(isIRI(?i)) }}
            }}
        """),
    )

    index_meta: dict = {}
    try:
        raw = r.get(_meta_key(version_id))
        if raw:
            index_meta = _json.loads(raw)
    except Exception:
        pass

    result = {
        "triple_count":              triple_count,
        "class_count":               class_count,
        "property_count":            obj_prop_count + data_prop_count + ann_prop_count,
        "object_property_count":     obj_prop_count,
        "datatype_property_count":   data_prop_count,
        "annotation_property_count": ann_prop_count,
        "individual_count":          ind_count,
        "index_meta":                index_meta,
    }

    # ── Cache result ──────────────────────────────────────────────────────────
    try:
        r.setex(_stats_cache_key(version_id), _STATS_CACHE_TTL, _json.dumps(result))
    except Exception:
        pass

    return result


# ── Ontology document metadata ────────────────────────────────────────────────

@router.get("/{ontology_id}/{version_id}/ontology-metadata", summary="Metadata from the ontology document itself")
async def get_ontology_document_metadata(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return all triples where the subject is the primary owl:Ontology IRI."""
    import asyncio
    from ontoexplorer.clients.oxigraph import get_store, graph_iri

    ontology = await _get_ontology_or_404(db, ontology_id)
    await _get_version_or_404(db, ontology_id, version_id)

    store = get_store()
    g = graph_iri(ontology_id, version_id)
    onto_iri = ontology.iri

    query = f"""
        SELECT ?pred ?obj WHERE {{
            GRAPH <{g}> {{
                <{onto_iri}> ?pred ?obj .
            }}
        }}
        ORDER BY ?pred
    """

    def _run(s, q):
        predicates: dict[str, list] = {}
        for row in s.query(q):
            pred = row["pred"]
            obj = row["obj"]
            if pred is None or obj is None:
                continue
            pred_iri = pred.value
            # Distinguish Literal (has .datatype) from NamedNode/BlankNode
            if hasattr(obj, "datatype"):
                entry: dict = {
                    "value": obj.value,
                    "type": "literal",
                    "language": getattr(obj, "language", None),
                    "datatype": obj.datatype.value if obj.datatype else None,
                }
            else:
                val = obj.value
                if not (val.startswith("http://") or val.startswith("https://") or val.startswith("urn:")):
                    continue  # skip blank nodes
                entry = {"value": val, "type": "iri"}
            predicates.setdefault(pred_iri, []).append(entry)
        return predicates

    predicates = await asyncio.to_thread(_run, store, query)
    return {"ontology_iri": onto_iri, "predicates": predicates}


# ── Terms ──────────────────────────────────────────────────────────────────────

_PROP_TYPES = (
    "owl:ObjectProperty",
    "owl:DatatypeProperty",
    "owl:AnnotationProperty",
)
_PROP_UNION = " UNION ".join(f"{{ ?entity a {t} }}" for t in _PROP_TYPES)

_PROP_SUBTYPE_FILTER = {
    "object_property":     "{ ?entity a owl:ObjectProperty }",
    "data_property":       "{ ?entity a owl:DatatypeProperty }",
    "annotation_property": "{ ?entity a owl:AnnotationProperty }",
}

# Subtype → subPropertyOf child type filter (for child queries)
_PROP_SUBTYPE_CHILD_FILTER = {
    "object_property":     "{ ?class a owl:ObjectProperty }",
    "data_property":       "{ ?class a owl:DatatypeProperty }",
    "annotation_property": "{ ?class a owl:AnnotationProperty }",
}


@router.get("/{ontology_id}/{version_id}/terms", summary="List terms (classes or properties)")
async def list_terms(
    ontology_id: str,
    version_id: str,
    parent: str | None = Query(None, description="'root' for top-level, or an IRI for direct children"),
    entity_type: str = Query("class", description="'class', 'property', 'object_property', 'data_property', or 'annotation_property'"),
    hide_inverse: bool = Query(False, description="Exclude object properties that are the object of owl:inverseOf"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    import asyncio
    import json as _json

    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.oxigraph import get_store, graph_iri

    is_root = parent is None or parent == "root"
    is_prop_subtype = entity_type in _PROP_SUBTYPE_FILTER
    is_any_property = entity_type == "property" or is_prop_subtype

    # Serve root requests from Redis cache when available (skip for hide_inverse — different result set)
    if is_root and offset == 0 and not hide_inverse:
        try:
            from ontoexplorer.modules.search.indexer import _get_redis
            _r = _get_redis()
            _cache_key = f"terms_root:{version_id}:{entity_type}:{limit}"
            _cached = _r.get(_cache_key)
            if _cached:
                return _json.loads(_cached)
        except Exception:
            pass

    store = get_store()
    g = graph_iri(ontology_id, version_id)

    _OWL_THING_STR = "http://www.w3.org/2002/07/owl#Thing"

    def _row_label(row) -> str | None:
        lbl = row["label"]
        return lbl.value if (lbl is not None and hasattr(lbl, "value")) else None

    if is_root:
        # Two-pass root detection avoids correlated FILTER NOT EXISTS (O(n²) on large ontologies).
        # Pass 1: all entities with labels. Pass 2: entities that have a named parent. Subtract in Python.
        _NOT_DEPRECATED = f"FILTER NOT EXISTS {{ ?class owl:deprecated ?_d . FILTER(str(?_d) = \"true\") }}"

        if is_any_property:
            prop_filter = _PROP_SUBTYPE_FILTER.get(entity_type, _PROP_UNION)
            child_type_filter = _PROP_SUBTYPE_CHILD_FILTER.get(entity_type, f"{{ {_PROP_UNION} }}")
            all_q = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?class ?label WHERE {{
                    GRAPH <{g}> {{
                        {{ {prop_filter} }}
                        BIND(?entity AS ?class)
                        FILTER(isIRI(?class))
                        {_NOT_DEPRECATED}
                        OPTIONAL {{ ?class rdfs:label ?label }}
                    }}
                }}
                ORDER BY ?class
            """
            non_root_q = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT DISTINCT ?class WHERE {{
                    GRAPH <{g}> {{
                        ?class rdfs:subPropertyOf ?parent .
                        FILTER(isIRI(?class) && isIRI(?parent))
                        {child_type_filter}
                    }}
                }}
            """
        else:
            all_q = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?class ?label WHERE {{
                    GRAPH <{g}> {{
                        ?class a owl:Class .
                        FILTER(isIRI(?class))
                        {_NOT_DEPRECATED}
                        OPTIONAL {{ ?class rdfs:label ?label }}
                    }}
                }}
                ORDER BY ?class
            """
            non_root_q = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT DISTINCT ?class WHERE {{
                    GRAPH <{g}> {{
                        ?class rdfs:subClassOf ?parent .
                        ?class a owl:Class .
                        ?parent a owl:Class .
                        FILTER(isIRI(?class) && isIRI(?parent) && str(?parent) != "{_OWL_THING_STR}")
                    }}
                }}
            """

        def _run_root_two_pass(s, aq, nrq, off, lim):
            all_rows = []
            for row in s.query(aq):
                all_rows.append((row["class"].value, _row_label(row)))
            non_roots = {row["class"].value for row in s.query(nrq)}
            roots = [(iri, lbl) for iri, lbl in all_rows if iri not in non_roots]
            roots.sort(key=lambda x: (x[1] or x[0]).lower())
            return roots[off: off + lim]

        page = await asyncio.to_thread(_run_root_two_pass, store, all_q, non_root_q, offset, limit)
        terms = [{"iri": iri, "label": lbl} for iri, lbl in page]

    elif is_any_property:
        prop_filter = _PROP_SUBTYPE_FILTER.get(entity_type, _PROP_UNION)
        if parent.startswith("http"):
            query = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?class ?label WHERE {{
                    GRAPH <{g}> {{
                        {{ {prop_filter} }}
                        BIND(?entity AS ?class)
                        FILTER(isIRI(?class))
                        ?class rdfs:subPropertyOf <{parent}> .
                        OPTIONAL {{ ?class rdfs:label ?label }}
                    }}
                }}
                ORDER BY ?class
                LIMIT {limit} OFFSET {offset}
            """
        else:
            query = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?class ?label WHERE {{
                    GRAPH <{g}> {{
                        {{ {prop_filter} }}
                        BIND(?entity AS ?class)
                        FILTER(isIRI(?class))
                        OPTIONAL {{ ?class rdfs:label ?label }}
                    }}
                }}
                ORDER BY ?class
                LIMIT {limit} OFFSET {offset}
            """

        def _run_terms(s, q):
            rows = [{"iri": row["class"].value, "label": _row_label(row)} for row in s.query(q)]
            rows.sort(key=lambda t: (t["label"] or t["iri"]).lower())
            return rows

        terms = await asyncio.to_thread(_run_terms, store, query)

    elif parent.startswith("http"):
        # Direct subclasses of the given parent IRI
        query = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?label WHERE {{
                GRAPH <{g}> {{
                    ?class a owl:Class .
                    FILTER(isIRI(?class))
                    ?class rdfs:subClassOf <{parent}> .
                    OPTIONAL {{ ?class rdfs:label ?label }}
                }}
            }}
            ORDER BY ?class
            LIMIT {limit} OFFSET {offset}
        """

        def _run_terms(s, q):
            rows = [{"iri": row["class"].value, "label": _row_label(row)} for row in s.query(q)]
            rows.sort(key=lambda t: (t["label"] or t["iri"]).lower())
            return rows

        terms = await asyncio.to_thread(_run_terms, store, query)

    else:
        # Fallback: all named classes
        query = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?label WHERE {{
                GRAPH <{g}> {{
                    ?class a owl:Class .
                    FILTER(isIRI(?class))
                    OPTIONAL {{ ?class rdfs:label ?label }}
                }}
            }}
            ORDER BY ?class
            LIMIT {limit} OFFSET {offset}
        """

        def _run_terms(s, q):
            rows = [{"iri": row["class"].value, "label": _row_label(row)} for row in s.query(q)]
            rows.sort(key=lambda t: (t["label"] or t["iri"]).lower())
            return rows

        terms = await asyncio.to_thread(_run_terms, store, query)

    # Filter out inverse object properties when requested
    if hide_inverse and is_any_property and terms:
        inv_q = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT DISTINCT ?prop WHERE {{
                GRAPH <{g}> {{
                    ?anyProp owl:inverseOf ?prop .
                    FILTER(isIRI(?prop) && isIRI(?anyProp))
                }}
            }}
        """

        def _run_inverse(s, q):
            return {row["prop"].value for row in s.query(q)}

        inverse_iris = await asyncio.to_thread(_run_inverse, store, inv_q)
        terms = [t for t in terms if t["iri"] not in inverse_iris]

    # Find which terms have children (single query over the fetched IRIs)
    if terms:
        values_block = " ".join(f"<{t['iri']}>" for t in terms)
        if is_any_property:
            child_q = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT DISTINCT ?parent WHERE {{
                    GRAPH <{g}> {{
                        ?child rdfs:subPropertyOf ?parent .
                        FILTER(isIRI(?child))
                        VALUES ?parent {{ {values_block} }}
                    }}
                }}
            """
        else:
            child_q = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT DISTINCT ?parent WHERE {{
                    GRAPH <{g}> {{
                        ?child rdfs:subClassOf ?parent .
                        ?child a owl:Class .
                        FILTER(isIRI(?child))
                        VALUES ?parent {{ {values_block} }}
                    }}
                }}
            """

        def _run_children(s, q):
            return {row["parent"].value for row in s.query(q)}

        has_children_iris = await asyncio.to_thread(_run_children, store, child_q)
        for t in terms:
            t["has_children"] = t["iri"] in has_children_iris

    response = {"terms": terms, "offset": offset, "limit": limit, "parent": parent}

    # Cache root results so the second load (and every panel re-open) is instant (skip for hide_inverse)
    if is_root and offset == 0 and not hide_inverse:
        try:
            from ontoexplorer.modules.search.indexer import _get_redis
            _r = _get_redis()
            _cache_key = f"terms_root:{version_id}:{entity_type}:{limit}"
            _r.setex(_cache_key, 300, _json.dumps(response))
        except Exception:
            pass

    return response


@router.get("/{ontology_id}/{version_id}/terms/{term_iri:path}", summary="Term detail")
async def get_term(
    ontology_id: str,
    version_id: str,
    term_iri: str,
    db: AsyncSession = Depends(get_db),
):
    import asyncio
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

    await _get_version_or_404(db, ontology_id, version_id)

    store = get_store()
    g_iri = graph_iri(ontology_id, version_id)

    # Fetch raw asserted properties
    props_query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?pred ?obj WHERE {{
            GRAPH <{g_iri}> {{
                <{term_iri}> ?pred ?obj .
                FILTER(isIRI(?obj) || isLiteral(?obj))
            }}
        }}
    """
    prop_rows = list(store.query(props_query))
    if not prop_rows:
        raise HTTPException(status_code=404, detail="Term not found in this ontology version")

    properties: dict[str, list] = {}
    for row in prop_rows:
        pred = row["pred"].value
        obj = row["obj"].value
        properties.setdefault(pred, []).append(obj)

    # Asserted subclasses — named classes that declare subClassOf this term
    asserted_sub_query = f"""
        SELECT ?sub WHERE {{
            GRAPH <{g_iri}> {{
                ?sub <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{term_iri}> .
                FILTER(isIRI(?sub))
            }}
        }}
        ORDER BY ?sub
    """
    asserted_sub_iris = [r["sub"].value for r in store.query(asserted_sub_query)]

    # Inferred sub/superclasses from ELK — run concurrently, ignore if not ready
    async def _elk_subclasses():
        try:
            return await elk_subclasses(version_id, term_iri, direct=False)
        except (ReasoningNotReadyError, ClassNotFoundError):
            return {}
        except Exception:
            return {}

    async def _elk_superclasses():
        try:
            return await elk_superclasses(version_id, term_iri, direct=False)
        except (ReasoningNotReadyError, ClassNotFoundError):
            return {}
        except Exception:
            return {}

    elk_sub_result, elk_sup_result = await asyncio.gather(
        _elk_subclasses(), _elk_superclasses()
    )

    _OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
    _OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
    inferred_sub_iris: list[str] = [
        s for s in elk_sub_result.get("subclasses", [])
        if s not in (_OWL_THING, _OWL_NOTHING)
    ]
    inferred_sup_iris: list[str] = [
        s for s in elk_sup_result.get("superclasses", [])
        if s not in (_OWL_THING, _OWL_NOTHING)
    ]

    # Asserted superclasses — named-class targets of rdfs:subClassOf
    RDFS_SC = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
    asserted_sup_iris = [v for v in properties.get(RDFS_SC, [])
                         if v.startswith("http://") or v.startswith("https://") or v.startswith("urn:")]

    # Resolve labels from Redis index
    r = _get_redis()

    def _label(iri: str) -> str:
        detail = r.hgetall(_iri_key(version_id, iri))
        if detail and detail.get("label"):
            return detail["label"]
        fragment = iri.rstrip("/")
        return fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]

    def _term_list(iris: list[str]) -> list[dict]:
        items = [{"iri": iri, "label": _label(iri)} for iri in iris]
        items.sort(key=lambda t: (t["label"] or t["iri"]).lower())
        return items

    # Property usage — classes that reference this term via owl:onProperty restrictions
    _OWL_PROP_TYPES = {
        "http://www.w3.org/2002/07/owl#ObjectProperty",
        "http://www.w3.org/2002/07/owl#DatatypeProperty",
        "http://www.w3.org/2002/07/owl#AnnotationProperty",
    }
    rdf_types = set(properties.get("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", []))
    is_property = bool(rdf_types & _OWL_PROP_TYPES)

    usage: list[dict] = []
    if is_property:
        usage_query = f"""
            PREFIX owl:  <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?restrictType ?filler WHERE {{
                GRAPH <{g_iri}> {{
                    ?class rdfs:subClassOf ?r .
                    ?r owl:onProperty <{term_iri}> .
                    FILTER(isIRI(?class))
                    {{
                        ?r owl:someValuesFrom ?filler .
                        BIND("some" AS ?restrictType)
                    }} UNION {{
                        ?r owl:allValuesFrom ?filler .
                        BIND("only" AS ?restrictType)
                    }} UNION {{
                        ?r owl:hasValue ?filler .
                        BIND("value" AS ?restrictType)
                    }} UNION {{
                        ?r owl:minCardinality ?filler .
                        BIND("min" AS ?restrictType)
                    }} UNION {{
                        ?r owl:maxCardinality ?filler .
                        BIND("max" AS ?restrictType)
                    }} UNION {{
                        ?r owl:exactCardinality ?filler .
                        BIND("exactly" AS ?restrictType)
                    }} UNION {{
                        ?r owl:minQualifiedCardinality ?filler .
                        BIND("min" AS ?restrictType)
                    }} UNION {{
                        ?r owl:maxQualifiedCardinality ?filler .
                        BIND("max" AS ?restrictType)
                    }} UNION {{
                        ?r owl:exactQualifiedCardinality ?filler .
                        BIND("exactly" AS ?restrictType)
                    }}
                }}
            }}
            ORDER BY ?class ?restrictType
            LIMIT 200
        """
        for row in store.query(usage_query):
            cls_iri   = row["class"].value
            rtype     = row["restrictType"].value if row["restrictType"] else "?"
            filler    = row["filler"]
            filler_val = filler.value if filler is not None else None
            filler_label: str | None = None
            if filler_val and (filler_val.startswith("http") or filler_val.startswith("urn:")):
                filler_label = _label(filler_val)
            usage.append({
                "class_iri":    cls_iri,
                "class_label":  _label(cls_iri),
                "restriction":  rtype,
                "filler_iri":   filler_val if filler_val and filler_val.startswith("http") else None,
                "filler_label": filler_label or filler_val,
            })

    # Is this term the object of owl:inverseOf declared by another property?
    def _check_is_inverse_target(s) -> bool:
        q = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            ASK {{ GRAPH <{g_iri}> {{ ?p owl:inverseOf <{term_iri}> . FILTER(isIRI(?p)) }} }}
        """
        return bool(s.query(q))

    is_inverse_target = await asyncio.to_thread(_check_is_inverse_target, store)

    return {
        "iri": term_iri,
        "label": _label(term_iri),
        "properties": properties,
        "is_inverse_target": is_inverse_target,
        "superclasses": {
            "asserted": _term_list(asserted_sup_iris),
            "inferred": _term_list(inferred_sup_iris),
        },
        "subclasses": {
            "asserted": _term_list(asserted_sub_iris),
            "inferred": _term_list(inferred_sub_iris),
        },
        "usage": usage,
    }


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

    axioms = [{"subClass": r["sub"].value, "superClass": r["sup"].value} for r in results]
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


_OWL_THING    = "http://www.w3.org/2002/07/owl#Thing"
_OWL_NOTHING  = "http://www.w3.org/2002/07/owl#Nothing"


@router.get("/{ontology_id}/{version_id}/inferred-children",
            summary="Direct inferred children of a class (label-resolved)")
async def inferred_children(
    ontology_id: str,
    version_id: str,
    cls: str = Query(_OWL_THING, description="Parent class IRI; defaults to owl:Thing for root"),
    db: AsyncSession = Depends(get_db),
):
    """Return direct inferred subclasses from ELK with labels resolved from the Redis index.

    Uses the full cached classification result so a single ELK call covers all nodes.
    Root request (cls=owl:Thing) returns classes with no direct inferred superclass.
    """
    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.reasoning import get_classification
    from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

    try:
        classification = await get_classification(version_id)
    except Exception:
        return {"terms": [], "reasoning_available": False}

    # ELK splits its hierarchy across two keys:
    #   direct_superclasses — pre-computed direct parents for most classes
    #   superclasses        — partial transitive closure; catches classes ELK's
    #                         direct-parent computation missed (e.g. CCO_0000015)
    # We combine both: prefer direct_superclasses, fall back to deriving from superclasses.
    elk_direct: dict[str, list[str]] = classification.get("direct_superclasses", {})
    elk_all:    dict[str, list[str]] = classification.get("superclasses", {})
    _excluded = {_OWL_THING, _OWL_NOTHING}

    def _direct_parents(c: str) -> list[str]:
        if c in elk_direct:
            return elk_direct[c]
        # Derive from superclasses: keep most-specific (drop p if any sibling q has p in elk_all[q])
        raw = [p for p in elk_all.get(c, []) if p not in _excluded]
        return [p for p in raw
                if not any(p in elk_all.get(q, []) for q in raw if q != p)]

    all_classes = set(elk_direct.keys()) | set(elk_all.keys())

    if cls == _OWL_THING:
        child_iris = sorted(c for c in all_classes if not _direct_parents(c))
    else:
        child_iris = sorted(c for c in all_classes if cls in _direct_parents(c))

    r = _get_redis()

    def _label(iri: str) -> str:
        detail = r.hgetall(_iri_key(version_id, iri))
        if detail and detail.get("label"):
            return detail["label"]
        fragment = iri.rstrip("/")
        return fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]

    def _has_inferred_children(iri: str) -> bool:
        return any(iri in _direct_parents(c) for c in all_classes)

    return {
        "terms": [{"iri": iri, "label": _label(iri), "has_children": _has_inferred_children(iri)} for iri in child_iris],
        "reasoning_available": True,
    }


@router.get("/{ontology_id}/{version_id}/ancestors",
            summary="Ancestor chain for a term (asserted or inferred)")
async def term_ancestors(
    ontology_id: str,
    version_id: str,
    iri: str = Query(..., description="Term IRI"),
    mode: str = Query("asserted", description="'asserted' or 'inferred'"),
    db: AsyncSession = Depends(get_db),
):
    """Return all ancestors (superclasses) of a term so the UI can expand the tree path."""
    await _get_version_or_404(db, ontology_id, version_id)

    if mode == "inferred":
        from ontoexplorer.clients.reasoning import get_classification
        from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

        try:
            classification = await get_classification(version_id)
        except Exception:
            return {"ancestors": [], "reasoning_available": False}

        elk_direct: dict[str, list[str]] = classification.get("direct_superclasses", {})
        elk_all:    dict[str, list[str]] = classification.get("superclasses", {})
        _excl = {_OWL_THING, _OWL_NOTHING}

        def _direct_parents(c: str) -> list[str]:
            if c in elk_direct:
                return elk_direct[c]
            raw = [p for p in elk_all.get(c, []) if p not in _excl]
            return [p for p in raw
                    if not any(p in elk_all.get(q, []) for q in raw if q != p)]

        # Walk up from term to root collecting every ancestor
        ancestors: list[str] = []
        visited: set[str] = set()
        queue = list(_direct_parents(iri))
        while queue:
            p = queue.pop()
            if p in visited or p in _excl:
                continue
            visited.add(p)
            ancestors.append(p)
            queue.extend(_direct_parents(p))

        r = _get_redis()

        def _label(i: str) -> str:
            detail = r.hgetall(_iri_key(version_id, i))
            if detail and detail.get("label"):
                return detail["label"]
            fragment = i.rstrip("/")
            return fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]

        return {
            "ancestors": [{"iri": a, "label": _label(a)} for a in ancestors],
            "reasoning_available": True,
        }

    # Asserted: SPARQL property path rdfs:subClassOf+
    import asyncio
    from ontoexplorer.clients.oxigraph import get_store
    store = get_store()
    g = f"urn:ontology:{ontology_id}:{version_id}"
    query = f"""
        PREFIX owl:  <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?ancestor ?label WHERE {{
            GRAPH <{g}> {{
                <{iri}> rdfs:subClassOf+ ?ancestor .
                ?ancestor a owl:Class .
                FILTER(isIRI(?ancestor))
                FILTER(?ancestor != owl:Thing)
                OPTIONAL {{ ?ancestor rdfs:label ?label }}
            }}
        }}
    """

    def _run(s, q):
        out = []
        for row in s.query(q):
            lbl = row["label"]
            label = lbl.value if (lbl is not None and hasattr(lbl, "value")) else None
            out.append({"iri": row["ancestor"].value, "label": label})
        return out

    ancestors_out = await asyncio.to_thread(_run, store, query)
    return {"ancestors": ancestors_out}


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

    # Invalidate stats cache for this version
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        _get_redis().delete(_stats_cache_key(version_id))
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
