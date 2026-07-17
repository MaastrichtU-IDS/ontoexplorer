"""Ontologies REST API — submit, list, metadata, versions, terms, download, deprecate."""

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.reasoning import (
    ClassNotFoundError,
    ReasoningNotReadyError,
    request_justification as elk_request_justification,
    subclasses as elk_subclasses,
    superclasses as elk_superclasses,
)
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import get_current_user, require_auth
from ontoexplorer.modules.storage.minio_client import fetch_ontology

router = APIRouter(prefix="/api/v1/ontologies", tags=["ontologies"])

_RDF_FORMATS = {"text/turtle": "turtle", "application/rdf+xml": "xml", "application/n-triples": "nt"}

# ── OWL class-expression resolver ─────────────────────────────────────────────

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def _rdf_list_items(store, graph_node, list_node) -> list:
    """Walk an rdf:List and return its items as pyoxigraph term objects."""
    import pyoxigraph
    RDF_FIRST = pyoxigraph.NamedNode(_RDF + "first")
    RDF_REST  = pyoxigraph.NamedNode(_RDF + "rest")
    RDF_NIL   = pyoxigraph.NamedNode(_RDF + "nil")
    items, current = [], list_node
    for _ in range(200):
        if isinstance(current, pyoxigraph.NamedNode) and current.value == RDF_NIL.value:
            break
        firsts = list(store.quads_for_pattern(current, RDF_FIRST, None, graph_node))
        if firsts:
            items.append(firsts[0].object)
        rests = list(store.quads_for_pattern(current, RDF_REST, None, graph_node))
        current = rests[0].object if rests else None
        if current is None:
            break
    return items


def _build_class_expr(store, graph_node, node, label_fn, depth: int = 0) -> dict:
    """Recursively build an AST dict for a pyoxigraph node (OWL class expression)."""
    import pyoxigraph
    if depth > 10:
        return {"type": "unknown"}

    if isinstance(node, pyoxigraph.NamedNode):
        return {"type": "named", "iri": node.value, "label": label_fn(node.value)}

    if not isinstance(node, pyoxigraph.BlankNode):
        return {"type": "literal", "value": node.value if hasattr(node, "value") else str(node)}

    # Collect all predicates of this blank node
    props: dict[str, list] = {}
    for quad in store.quads_for_pattern(node, None, None, graph_node):
        props.setdefault(quad.predicate.value, []).append(quad.object)

    # Restriction (owl:onProperty present)
    on_prop_list = props.get(_OWL + "onProperty", [])
    if on_prop_list:
        prop_ast = _build_class_expr(store, graph_node, on_prop_list[0], label_fn, depth + 1)

        for owl_pred, kw in [(_OWL + "someValuesFrom", "some"), (_OWL + "allValuesFrom", "only")]:
            fl = props.get(owl_pred, [])
            if fl:
                return {"type": kw, "property": prop_ast,
                        "filler": _build_class_expr(store, graph_node, fl[0], label_fn, depth + 1)}

        hv = props.get(_OWL + "hasValue", [])
        if hv:
            return {"type": "value", "property": prop_ast,
                    "filler": _build_class_expr(store, graph_node, hv[0], label_fn, depth + 1)}

        for owl_pred, kw in [
            (_OWL + "minCardinality", "min"), (_OWL + "maxCardinality", "max"),
            (_OWL + "exactCardinality", "exactly"),
            (_OWL + "minQualifiedCardinality", "min"), (_OWL + "maxQualifiedCardinality", "max"),
            (_OWL + "exactQualifiedCardinality", "exactly"),
        ]:
            cl = props.get(owl_pred, [])
            if cl:
                n = cl[0].value if hasattr(cl[0], "value") else str(cl[0])
                result: dict = {"type": kw, "property": prop_ast, "n": n}
                on_cls = props.get(_OWL + "onClass", [])
                if on_cls:
                    result["filler"] = _build_class_expr(store, graph_node, on_cls[0], label_fn, depth + 1)
                return result

        return {"type": "unknown"}

    # Complement
    comp = props.get(_OWL + "complementOf", [])
    if comp:
        return {"type": "not", "operand": _build_class_expr(store, graph_node, comp[0], label_fn, depth + 1)}

    # Intersection / Union
    for owl_pred, kw in [(_OWL + "intersectionOf", "and"), (_OWL + "unionOf", "or")]:
        ll = props.get(owl_pred, [])
        if ll:
            items = _rdf_list_items(store, graph_node, ll[0])
            return {"type": kw, "operands": [
                _build_class_expr(store, graph_node, it, label_fn, depth + 1) for it in items
            ]}

    # OneOf
    oo = props.get(_OWL + "oneOf", [])
    if oo:
        items = _rdf_list_items(store, graph_node, oo[0])
        return {"type": "one_of", "individuals": [
            _build_class_expr(store, graph_node, it, label_fn, depth + 1) for it in items
        ]}

    return {"type": "unknown"}


def _find_subclass_path(store, g_iri: str, sub_iri: str, sup_iri: str, label_fn) -> list[list[dict]]:
    """BFS over asserted rdfs:subClassOf edges to find a minimal named-class path sub → sup."""
    import pyoxigraph as ox
    from collections import deque

    RDFS_SC   = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
    graph_node = ox.NamedNode(g_iri)

    queue: deque[tuple[str, list[str]]] = deque([(sub_iri, [sub_iri])])
    visited: set[str] = {sub_iri}

    while queue:
        current, path = queue.popleft()
        if len(path) > 20:
            continue
        for quad in store.quads_for_pattern(ox.NamedNode(current), RDFS_SC, None, graph_node):
            if not isinstance(quad.object, ox.NamedNode):
                continue
            nxt = quad.object.value
            if nxt == sup_iri:
                full = path + [sup_iri]
                return [[
                    {
                        "sub": {"type": "named", "iri": full[i],     "label": label_fn(full[i])},
                        "rel": "subClassOf",
                        "sup": {"type": "named", "iri": full[i + 1], "label": label_fn(full[i + 1])},
                    }
                    for i in range(len(full) - 1)
                ]]
            if nxt not in visited and len(visited) < 10_000:
                visited.add(nxt)
                queue.append((nxt, path + [nxt]))
    return []


def _render_justification(ntriples_list: list[str], label_fn) -> list[dict]:
    """Parse a list of N-Triple strings and render each OWL axiom as a ClassExprNode AST dict."""
    import io
    import pyoxigraph
    JUST_GRAPH = pyoxigraph.NamedNode("urn:just")
    temp_store = pyoxigraph.Store()
    all_nt = "\n".join(ntriples_list)
    try:
        temp_store.bulk_load(io.BytesIO(all_nt.encode()), "application/n-triples", to_graph=JUST_GRAPH)
    except Exception:
        for nt in ntriples_list:
            try:
                temp_store.bulk_load(io.BytesIO(nt.strip().encode()), "application/n-triples", to_graph=JUST_GRAPH)
            except Exception:
                pass

    RDFS_SC = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
    OWL_EC  = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#equivalentClass")
    OWL_DW  = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#disjointWith")

    axioms: list[dict] = []
    seen: set[str] = set()
    # disjointWith is included because it's load-bearing for unsatisfiability
    # justifications (e.g., for "C ⊑ Nothing" the disjointness of C's parents is
    # often the cornerstone axiom). The frontend's JustificationAxiom type
    # already supports rel="disjointWith".
    for pred, rel in [(RDFS_SC, "subClassOf"), (OWL_EC, "equivalentClass"), (OWL_DW, "disjointWith")]:
        for quad in temp_store.quads_for_pattern(None, pred, None, JUST_GRAPH):
            s_key = quad.subject.value if isinstance(quad.subject, pyoxigraph.NamedNode) else str(quad.subject)
            o_key = quad.object.value  if isinstance(quad.object,  pyoxigraph.NamedNode) else str(quad.object)
            dedup = f"{s_key}|{rel}|{o_key}"
            if dedup in seen:
                continue
            seen.add(dedup)
            sub_ast = _build_class_expr(temp_store, JUST_GRAPH, quad.subject, label_fn)
            sup_ast = _build_class_expr(temp_store, JUST_GRAPH, quad.object,  label_fn)
            if sub_ast.get("type") != "unknown" and sup_ast.get("type") != "unknown":
                axioms.append({"sub": sub_ast, "rel": rel, "sup": sup_ast})
    return axioms


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
    from ontoexplorer.clients import reasoning as _reasoning
    from ontoexplorer.config import get_settings as _get_settings
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    content_type = request.headers.get("content-type", "")
    owner_id = user.id if user else None
    loop = asyncio.get_event_loop()

    is_multipart = "multipart/form-data" in content_type and file

    # Read the request body exactly once (the ASGI stream can't be re-read),
    # then reuse it for both reasoner resolution and the iri/url/content branches.
    form = None
    body: dict = {}
    if is_multipart:
        form = await request.form()
    else:
        try:
            body = await request.json()
        except Exception:
            body = {}

    # Reasoner: from body/form, else app default; validate against the service.
    req_reasoner = form.get("reasoner") if form is not None else body.get("reasoner")
    chosen_reasoner = req_reasoner or _get_settings().default_reasoner
    available = await _reasoning.available_reasoner_names()
    if chosen_reasoner not in available:
        raise HTTPException(
            status_code=422,
            detail=f"unknown or unavailable reasoner '{chosen_reasoner}'; available: {sorted(available)}",
        )
    reasoner = chosen_reasoner

    if is_multipart:
        raw = await file.read()
        task = await loop.run_in_executor(
            None,
            lambda: ingest_ontology.delay(
                raw_bytes_hex=raw.hex(),
                filename=file.filename,
                content_type=file.content_type,
                owner_id=owner_id,
                reasoner=reasoner,
            ),
        )
        return {"task_id": task.id, "status": "queued"}

    groups = [g for g in (body.get("groups") or []) if g] or None
    if "iri" in body:
        task = await loop.run_in_executor(
            None,
            lambda: ingest_ontology.delay(iri=body["iri"], owner_id=owner_id, groups=groups, reasoner=reasoner),
        )
    elif "url" in body:
        task = await loop.run_in_executor(
            None,
            lambda: ingest_ontology.delay(url=body["url"], owner_id=owner_id, groups=groups, reasoner=reasoner),
        )
    elif "content" in body:
        raw = body["content"].encode()
        task = await loop.run_in_executor(
            None,
            lambda: ingest_ontology.delay(
                raw_bytes_hex=raw.hex(),
                content_type=body.get("format"),
                owner_id=owner_id,
                groups=groups,
                reasoner=reasoner,
            ),
        )
    else:
        raise HTTPException(status_code=422, detail="Provide 'iri', 'url', 'content', or a file upload")

    return {"task_id": task.id, "status": "queued"}


# ── Patch ─────────────────────────────────────────────────────────────────────

import re as _re

_SHORTNAME_RE = _re.compile(r'^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$')


@router.patch("/{ontology_id}", summary="Update ontology metadata (shortname)")
async def patch_ontology(
    ontology_id: str,
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    ontology = await _get_ontology_or_404(db, ontology_id)

    if ontology.owner_id is not None and ontology.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the owner")

    if "shortname" in body:
        shortname = body["shortname"]
        if shortname is not None:
            if not _SHORTNAME_RE.match(shortname):
                raise HTTPException(
                    status_code=422,
                    detail="Shortname must be 2–64 characters: lowercase letters, digits, hyphens, underscores; must start and end with a letter or digit",
                )
            conflict = await db.execute(
                select(Ontology).where(Ontology.shortname == shortname, Ontology.id != ontology_id)
            )
            if conflict.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Shortname already taken")
        ontology.shortname = shortname

    if "auto_sync" in body and body["auto_sync"] is not None:
        ontology.auto_sync = bool(body["auto_sync"])

    if "groups" in body:
        raw = body["groups"]
        ontology.groups = [g for g in (raw if isinstance(raw, list) else []) if g]

    if "preferred_lang" in body:
        ontology.preferred_lang = body["preferred_lang"] or None

    if "title" in body:
        ontology.title = body["title"] or None

    await db.commit()
    await db.refresh(ontology)
    return _ontology_dict(ontology)


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("", summary="List ontologies")
async def list_ontologies(
    q: str | None = Query(None, description="Keyword filter on ontology name, IRI, or description"),
    group: str | None = Query(None, description="Filter by group tag (upper, obo, fair, biomedical)"),
    profile: str | None = Query(None, description="Filter by OWL 2 profile: el | rl | ql | dl"),
    reuses: str | None = Query(None, description="Filter: latest version reuses this prefix"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    import json as _json
    from sqlalchemy import func

    # Validate ?profile= param early (before any DB work)
    if profile is not None:
        from ontoexplorer.modules.owl_profile.registry import PROFILE_NAMES
        profile = profile.lower()
        if profile not in PROFILE_NAMES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid profile '{profile}'. Must be one of: {', '.join(PROFILE_NAMES)}",
            )

    # When filtering by q or profile we must load all and filter in Python.
    # At current scale (~24 ontologies) this is negligible; revisit if catalog grows large.
    stmt = select(Ontology).order_by(Ontology.created_at.desc())
    if group:
        import json as _json_grp
        from sqlalchemy import text
        if group == "other":
            stmt = stmt.where(func.jsonb_array_length(Ontology.groups) == 0)
        else:
            stmt = stmt.where(text("groups @> cast(:grp as jsonb)").bindparams(grp=_json_grp.dumps([group])))
    if not q and not profile and not reuses:
        stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    ontologies = result.scalars().all()

    # Batch-load the latest version per ontology in one SQL query
    ontology_ids = [o.id for o in ontologies]
    latest_by_oid: dict = {}
    if ontology_ids:
        subq = (
            select(
                OntologyVersion.ontology_id,
                func.max(OntologyVersion.created_at).label("max_created"),
            )
            .where(OntologyVersion.ontology_id.in_(ontology_ids))
            .group_by(OntologyVersion.ontology_id)
            .subquery()
        )
        vr = await db.execute(
            select(OntologyVersion).join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
        )
        for v in vr.scalars().all():
            latest_by_oid[v.ontology_id] = v

    # Batch-load cached stats from Redis (no Oxigraph queries)
    stats_by_vid: dict = {}
    langs_by_vid: dict[str, list[dict]] = {}
    try:
        from ontoexplorer.modules.search.indexer import _get_redis, _stats_cache_key, _langs_key
        r = _get_redis()
        pipe = r.pipeline(transaction=False)
        vid_list = [v.id for v in latest_by_oid.values()]
        for vid in vid_list:
            pipe.get(_stats_cache_key(vid))
        stats_raws = pipe.execute()
        for vid, raw in zip(vid_list, stats_raws):
            if raw:
                stats_by_vid[vid] = _json.loads(raw)
        # Batch-load language counts for indexed versions
        from ontoexplorer.modules.search.lang import canonical_lang
        pipe2 = r.pipeline(transaction=False)
        for vid in vid_list:
            pipe2.hgetall(_langs_key(vid))
        langs_raws = pipe2.execute()
        for vid, mapping in zip(vid_list, langs_raws):
            if not mapping:
                continue
            counts: dict[str, int] = {}
            for lang, cnt in mapping.items():
                key = canonical_lang(lang)
                if not key:  # skip empty-string untagged entries
                    continue
                counts[key] = counts.get(key, 0) + int(cnt)
            if counts:
                langs_by_vid[vid] = sorted(
                    ({"lang": k, "label_count": v} for k, v in counts.items()),
                    key=lambda x: x["lang"],
                )
    except Exception:
        pass

    # Batch-load resolved metadata from ontology_meta_profiles
    from ontoexplorer.models.db import OntologyMetaProfile
    meta_by_oid: dict[str, dict] = {}
    if ontology_ids:
        subq2 = (
            select(
                OntologyVersion.ontology_id,
                func.max(OntologyVersion.created_at).label("max_created"),
            )
            .where(
                OntologyVersion.ontology_id.in_(ontology_ids),
                OntologyVersion.status == "ready",
            )
            .group_by(OntologyVersion.ontology_id)
            .subquery()
        )
        mr = await db.execute(
            select(OntologyVersion.ontology_id, OntologyMetaProfile.resolved)
            .join(
                subq2,
                (OntologyVersion.ontology_id == subq2.c.ontology_id)
                & (OntologyVersion.created_at == subq2.c.max_created),
            )
            .join(OntologyMetaProfile, OntologyMetaProfile.version_id == OntologyVersion.id)
        )
        for row in mr.all():
            meta_by_oid[row.ontology_id] = row.resolved or {}

    rows = []
    for o in ontologies:
        d = _ontology_dict(o)
        v = latest_by_oid.get(o.id)
        if v:
            d["latest_version"] = _version_dict(v)
            s = stats_by_vid.get(v.id, {})
            d["class_count"] = s.get("class_count")
            d["property_count"] = s.get("property_count")
            d["object_property_count"] = s.get("object_property_count")
            d["datatype_property_count"] = s.get("datatype_property_count")
            d["annotation_property_count"] = s.get("annotation_property_count")
            d["triple_count"] = s.get("triple_count") or v.triple_count
            d["individual_count"] = s.get("individual_count")
            d["languages"] = langs_by_vid.get(v.id, [])
            meta = meta_by_oid.get(o.id, {})
            d["label"] = o.title or meta.get("title") or s.get("label") or ""
            d["description"] = meta.get("description") or s.get("description") or ""
        else:
            d["latest_version"] = None
            d["class_count"] = None
            d["property_count"] = None
            d["object_property_count"] = None
            d["datatype_property_count"] = None
            d["annotation_property_count"] = None
            d["triple_count"] = None
            d["individual_count"] = None
            d["languages"] = []
            meta = meta_by_oid.get(o.id, {})
            d["label"] = o.title or meta.get("title") or ""
            d["description"] = meta.get("description") or ""
        rows.append(d)

    # OWL 2 profile filter: keep only ontologies whose latest ready version is in the profile.
    if profile:
        from ontoexplorer.api.owl_profile import filter_ontology_ids_by_profile
        all_ids = [r["id"] for r in rows]
        matching_ids = await filter_ontology_ids_by_profile(db, all_ids, profile)
        rows = [r for r in rows if r["id"] in matching_ids]

    # Reuse filter: keep only ontologies whose latest ready version reuses target_prefix
    if reuses:
        from ontoexplorer.api.reuse import filter_ontology_ids_by_reuse
        all_ids = [r["id"] for r in rows]
        matching_ids = await filter_ontology_ids_by_reuse(db, all_ids, reuses.lower())
        rows = [r for r in rows if r["id"] in matching_ids]

    # Python-side filter + ranked sort when q is present.
    # Primary rank:
    #   0 → exact match on derived short name or IRI
    #   1 → substring in short name or IRI  (canonical identifiers)
    #   2 → substring in label              (ontology's own title metadata)
    #   3 → substring in description only
    # Within rank 1, secondary sort is match-target length (shorter = tighter match).
    if q:
        ql = q.lower()

        def _rank_score(r: dict) -> tuple[int, int]:
            shortname = (r.get("shortname") or "").lower()
            iri       = (r.get("iri") or "").lower()
            label     = (r.get("label") or "").lower()
            desc      = (r.get("description") or "").lower()
            # Prefer explicit shortname; fall back to last IRI path segment
            seg  = iri.rstrip("/").rsplit("/", 1)[-1] if iri else ""
            name = shortname or seg
            if name == ql or iri == ql:
                return (0, 0)
            if ql in name or ql in iri:
                return (1, len(name))   # shorter name → tighter match → sorts first
            if ql in label:
                return (2, len(label))
            if ql in desc:
                return (3, 0)
            return (99, 0)

        ranked = [(r, _rank_score(r)) for r in rows]
        rows = [r for r, score in sorted(ranked, key=lambda x: x[1]) if score[0] < 99]
        rows = rows[offset: offset + limit]
    elif profile or reuses:
        # Profile or reuse filter already applied above; now apply pagination
        rows = rows[offset: offset + limit]

    return {"ontologies": rows, "offset": offset, "limit": limit}


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
    import asyncio
    version = await _get_version_or_404(db, ontology_id, version_id)
    data = await asyncio.to_thread(fetch_ontology, version.minio_key)
    ext = version.minio_key.rsplit(".", 1)[-1] if "." in version.minio_key else "owl"
    content_types = {
        "owl": "application/rdf+xml", "ttl": "text/turtle",
        "nt": "application/n-triples", "jsonld": "application/ld+json",
        "obo": "text/plain", "omn": "text/plain",
    }
    media_type = content_types.get(ext.lower(), "application/octet-stream")
    filename = version.minio_key.rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{ontology_id}/{version_id}/stats", summary="VoID statistics for a version")
async def version_stats(ontology_id: str, version_id: str, db: AsyncSession = Depends(get_db)):
    import asyncio
    import json as _json

    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.search.indexer import _meta_key, _get_redis, _stats_cache_key, _SEARCH_TTL

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
        raw = r.hgetall(_meta_key(version_id))
        if raw:
            # Convert string values to int where possible (schema v2 stores as strings)
            index_meta = {
                k: (int(v) if v.isdigit() else v)
                for k, v in raw.items()
            }
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
        r.setex(_stats_cache_key(version_id), _SEARCH_TTL, _json.dumps(result))
    except Exception:
        pass

    return result


@router.get("/{ontology_id}/{version_id}/languages", summary="Languages present in the search index")
async def get_languages(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    import asyncio
    await _get_version_or_404(db, ontology_id, version_id)

    def _read_langs():
        from ontoexplorer.modules.search.indexer import _get_redis, _langs_key, _meta_key
        from ontoexplorer.modules.search.lang import canonical_lang
        r = _get_redis()
        meta = r.hgetall(_meta_key(version_id))
        if meta.get("schema_version") != "v2":
            return []
        raw = r.hgetall(_langs_key(version_id))
        merged: dict[str, int] = {}
        for lang, cnt in raw.items():
            key = canonical_lang(lang)
            merged[key] = merged.get(key, 0) + int(cnt)
        return sorted(
            ({"lang": k, "label_count": v} for k, v in merged.items()),
            key=lambda x: x["lang"],
        )

    return await asyncio.to_thread(_read_langs)


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
_RDF_PROPERTY = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#Property>"
_PROP_UNION = " UNION ".join(f"{{ ?entity a {t} }}" for t in _PROP_TYPES)
_PROP_UNION = f"{_PROP_UNION} UNION {{ ?entity a {_RDF_PROPERTY} }}"

_OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


_PROP_SUBTYPE_FILTER = {
    # rdf:Property is the RDFS fallback used by vocabularies like Schema.org
    "object_property":     f"{{ ?entity a owl:ObjectProperty }} UNION {{ ?entity a {_RDF_PROPERTY} }}",
    "data_property":       "{ ?entity a owl:DatatypeProperty }",
    "annotation_property": "{ ?entity a owl:AnnotationProperty }",
}

# Subtype → subPropertyOf child type filter (for child queries)
_PROP_SUBTYPE_CHILD_FILTER = {
    "object_property":     f"{{ ?class a owl:ObjectProperty }} UNION {{ ?class a {_RDF_PROPERTY} }}",
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
    hide_obsolete: bool = Query(True, description="Exclude owl:deprecated terms"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    lang: str | None = Query(None, description="Preferred BCP-47 language tag for labels"),
    db: AsyncSession = Depends(get_db),
):
    import asyncio
    import json as _json

    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.oxigraph import get_store, graph_iri

    is_root = parent is None or parent == "root"
    g = graph_iri(ontology_id, version_id)
    is_prop_subtype = entity_type in _PROP_SUBTYPE_FILTER
    is_any_property = entity_type == "property" or is_prop_subtype
    is_individual = entity_type == "individual"

    # Individuals: flat paginated list, never a tree
    if is_individual:
        _NOT_DEPRECATED_IND = (
            'FILTER NOT EXISTS { ?entity owl:deprecated ?_d . FILTER(str(?_d) = "true") }'
            if hide_obsolete else ""
        )
        _lang_filter = "lang(?label) = '' || lang(?label) = 'en'" + (f" || lang(?label) = '{lang}'" if lang and lang != "en" else "")
        if is_root:
            ind_q = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT DISTINCT ?entity ?label WHERE {{
                    GRAPH <{g}> {{
                        ?entity a owl:NamedIndividual .
                        FILTER(isIRI(?entity))
                        {_NOT_DEPRECATED_IND}
                        OPTIONAL {{
                            ?entity rdfs:label ?label .
                            FILTER({_lang_filter})
                        }}
                    }}
                }}
                ORDER BY ?label ?entity
                LIMIT {limit} OFFSET {offset}
            """
        else:
            ind_q = f"""
                PREFIX owl: <http://www.w3.org/2002/07/owl#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT DISTINCT ?entity ?label WHERE {{
                    GRAPH <{g}> {{
                        ?entity a owl:NamedIndividual .
                        ?entity a <{parent}> .
                        FILTER(isIRI(?entity))
                        {_NOT_DEPRECATED_IND}
                        OPTIONAL {{
                            ?entity rdfs:label ?label .
                            FILTER({_lang_filter})
                        }}
                    }}
                }}
                ORDER BY ?label ?entity
                LIMIT {limit} OFFSET {offset}
            """

        def _run_individuals(s, q):
            seen: dict[str, tuple[str | None, int, str | None]] = {}
            for row in s.query(q):
                iri = row["entity"].value
                lbl_node = row["label"]
                label = lbl_node.value if (lbl_node is not None and hasattr(lbl_node, "value")) else None
                lang_tag = (lbl_node.language if hasattr(lbl_node, "language") else None) if lbl_node is not None else None
                score = _label_score(lang_tag)
                prev = seen.get(iri)
                if prev is None or score > prev[1]:
                    seen[iri] = (label, score, lang_tag)
            return [{"iri": iri, "label": lbl, "lang": lt, "has_children": False} for iri, (lbl, _, lt) in seen.items()]

        terms = await asyncio.to_thread(_run_individuals, get_store(), ind_q)
        return {"terms": terms, "offset": offset, "limit": limit, "parent": parent}

    # Serve root requests from Redis cache when available
    if is_root and offset == 0 and not hide_inverse:
        try:
            from ontoexplorer.modules.search.indexer import _get_redis
            _r = _get_redis()
            _cache_key = f"terms_root:{version_id}:{entity_type}:{limit}:{int(hide_obsolete)}:{lang or ''}"
            _cached = _r.get(_cache_key)
            if _cached:
                return _json.loads(_cached)
        except Exception:
            pass

    store = get_store()

    _OWL_THING_STR = "http://www.w3.org/2002/07/owl#Thing"

    def _row_label(row) -> str | None:
        lbl = row["label"]
        return lbl.value if (lbl is not None and hasattr(lbl, "value")) else None

    def _row_lang(row) -> str | None:
        lbl = row["label"]
        if lbl is None or not hasattr(lbl, "language"):
            return None
        return lbl.language  # None for untagged literals, str for lang-tagged

    def _label_score(lang_tag: str | None) -> int:
        """Prefer preferred lang > English > untagged > anything else."""
        if lang and lang_tag == lang: return 3
        if lang_tag == "en": return 2
        if lang_tag is None or lang_tag == "": return 1
        return 0

    def _deduped_terms(s, q) -> list[dict]:
        """Run query and deduplicate by IRI, picking the best-language label."""
        seen: dict[str, tuple[str | None, int, str | None]] = {}
        for row in s.query(q):
            iri = row["class"].value
            lbl = _row_label(row)
            lt = _row_lang(row)
            score = _label_score(lt)
            prev = seen.get(iri)
            if prev is None or score > prev[1]:
                seen[iri] = (lbl, score, lt)
        rows = [{"iri": iri, "label": lbl, "lang": lt} for iri, (lbl, _, lt) in seen.items()]
        rows.sort(key=lambda t: (t["label"] or t["iri"]).lower())
        return rows

    _NOT_DEPRECATED_CLASS = (
        'FILTER NOT EXISTS { ?class owl:deprecated ?_d . FILTER(str(?_d) = "true") }'
        if hide_obsolete else ""
    )
    _NOT_DEPRECATED_ENTITY = (
        'FILTER NOT EXISTS { ?entity owl:deprecated ?_d . FILTER(str(?_d) = "true") }'
        if hide_obsolete else ""
    )

    if is_root:
        # Two-pass root detection avoids correlated FILTER NOT EXISTS (O(n²) on large ontologies).
        # Pass 1: all entities with labels. Pass 2: entities that have a named parent. Subtract in Python.
        _NOT_DEPRECATED = _NOT_DEPRECATED_CLASS

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
                        {_NOT_DEPRECATED_ENTITY}
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
                        {{ ?class a owl:Class }} UNION {{ ?class a rdfs:Class }}
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
                        {{ ?class a owl:Class }} UNION {{ ?class a rdfs:Class }}
                        {{ ?parent a owl:Class }} UNION {{ ?parent a rdfs:Class }}
                        FILTER(isIRI(?class) && isIRI(?parent) && str(?parent) != "{_OWL_THING_STR}")
                    }}
                }}
            """

        def _run_root_two_pass(s, aq, nrq, off, lim):
            seen: dict[str, tuple[str | None, int, str | None]] = {}
            for row in s.query(aq):
                iri = row["class"].value
                lbl = _row_label(row)
                lt = _row_lang(row)
                score = _label_score(lt)
                prev = seen.get(iri)
                if prev is None or score > prev[1]:
                    seen[iri] = (lbl, score, lt)
            non_roots = {row["class"].value for row in s.query(nrq)}
            roots = [(iri, lbl, lt) for iri, (lbl, _, lt) in seen.items() if iri not in non_roots]
            roots.sort(key=lambda x: (x[1] or x[0]).lower())
            return roots[off: off + lim]

        page = await asyncio.to_thread(_run_root_two_pass, store, all_q, non_root_q, offset, limit)
        terms = [{"iri": iri, "label": lbl, "lang": lt} for iri, lbl, lt in page]

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
                        {_NOT_DEPRECATED_ENTITY}
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
                        {_NOT_DEPRECATED_ENTITY}
                        OPTIONAL {{ ?class rdfs:label ?label }}
                    }}
                }}
                ORDER BY ?class
                LIMIT {limit} OFFSET {offset}
            """

        terms = await asyncio.to_thread(_deduped_terms, store, query)

    elif parent.startswith("http"):
        # Direct subclasses of the given parent IRI
        query = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?label WHERE {{
                GRAPH <{g}> {{
                    {{ ?class a owl:Class }} UNION {{ ?class a rdfs:Class }}
                    FILTER(isIRI(?class))
                    {_NOT_DEPRECATED_CLASS}
                    ?class rdfs:subClassOf <{parent}> .
                    OPTIONAL {{ ?class rdfs:label ?label }}
                }}
            }}
            ORDER BY ?class
            LIMIT {limit} OFFSET {offset}
        """

        terms = await asyncio.to_thread(_deduped_terms, store, query)

    else:
        # Fallback: all named classes
        query = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?label WHERE {{
                GRAPH <{g}> {{
                    {{ ?class a owl:Class }} UNION {{ ?class a rdfs:Class }}
                    FILTER(isIRI(?class))
                    {_NOT_DEPRECATED_CLASS}
                    OPTIONAL {{ ?class rdfs:label ?label }}
                }}
            }}
            ORDER BY ?class
            LIMIT {limit} OFFSET {offset}
        """

        terms = await asyncio.to_thread(_deduped_terms, store, query)

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
                        {{ ?child a owl:Class }} UNION {{ ?child a rdfs:Class }}
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

    # Augment terms with source (imported-from) using a Redis pipeline batch read
    try:
        from ontoexplorer.modules.search.indexer import _get_redis, _iri_key
        _r = _get_redis()
        _pipe = _r.pipeline(transaction=False)
        for t in terms:
            _pipe.hget(_iri_key(version_id, t["iri"]), "source")
        for t, src in zip(terms, _pipe.execute()):
            t["source"] = src or ""
    except Exception:
        for t in terms:
            t.setdefault("source", "")

    response = {"terms": terms, "offset": offset, "limit": limit, "parent": parent}

    # Cache root results so the second load (and every panel re-open) is instant (skip for hide_inverse)
    if is_root and offset == 0 and not hide_inverse:
        try:
            from ontoexplorer.modules.search.indexer import _get_redis
            _r = _get_redis()
            _cache_key = f"terms_root:{version_id}:{entity_type}:{limit}:{int(hide_obsolete)}:{lang or ''}"
            _r.setex(_cache_key, 300, _json.dumps(response))
        except Exception:
            pass

    return response


def _sparql_term_props(store, props_q: str, sub_q: str) -> tuple[list, list[str]]:
    """Run two SPARQL queries for term detail synchronously (called via asyncio.to_thread)."""
    prop_rows = list(store.query(props_q))
    sub_iris = [r["sub"].value for r in store.query(sub_q)] if prop_rows else []
    return prop_rows, sub_iris


def _sparql_usage(store, q: str, label_fn) -> list[dict]:
    """Run property-usage SPARQL query and assemble rows (called via asyncio.to_thread)."""
    result = []
    for row in store.query(q):
        cls_iri = row["class"].value
        relation = row["relation"].value if row["relation"] is not None else "subClassOf"
        rtype = row["restrictType"].value if row["restrictType"] else "?"
        filler = row["filler"]
        filler_val = filler.value if filler is not None else None
        filler_label: str | None = None
        if filler_val and (filler_val.startswith("http") or filler_val.startswith("urn:")):
            filler_label = label_fn(filler_val)
        result.append({
            "class_iri":    cls_iri,
            "class_label":  label_fn(cls_iri),
            "relation":     relation,
            "restriction":  rtype,
            "filler_iri":   filler_val if filler_val and filler_val.startswith("http") else None,
            "filler_label": filler_label or filler_val,
        })
    return result


def _sparql_class_usage(store, cu_q: str, disj_q: str, label_fn, adc_map: dict, term_iri: str) -> list[dict]:
    """Run class-usage SPARQL queries and assemble rows (called via asyncio.to_thread)."""
    seen: set[str] = set()
    result: list[dict] = []
    for row in store.query(cu_q):
        cls_iri = row["class"].value
        relation = row["relation"].value if row["relation"] is not None else "subClassOf"
        prop_iri = row["prop"].value if row["prop"] else None
        rtype = row["restrictType"].value if row["restrictType"] else "?"
        key = f"{cls_iri}||{relation}||{prop_iri}||{rtype}"
        if key not in seen:
            seen.add(key)
            result.append({
                "class_iri":      cls_iri,
                "class_label":    label_fn(cls_iri),
                "relation":       relation,
                "property_iri":   prop_iri,
                "property_label": label_fn(prop_iri) if prop_iri else None,
                "restriction":    rtype,
            })
    for row in store.query(disj_q):
        cls_iri = row["class"].value
        key = f"{cls_iri}||disjointWith"
        if key not in seen:
            seen.add(key)
            result.append({
                "class_iri":      cls_iri,
                "class_label":    label_fn(cls_iri),
                "relation":       "disjointWith",
                "property_iri":   None,
                "property_label": None,
                "restriction":    "",
            })
    for co_iri in adc_map.get(term_iri, []):
        key = f"{co_iri}||disjointWith"
        if key not in seen:
            seen.add(key)
            result.append({
                "class_iri":      co_iri,
                "class_label":    label_fn(co_iri),
                "relation":       "disjointWith",
                "property_iri":   None,
                "property_label": None,
                "restriction":    "",
            })
    result.sort(key=lambda x: (x["class_label"] or x["class_iri"]).lower())
    return result


_TERM_DETAIL_CACHE_TTL = 300  # 5 minutes — term details are essentially static within a version


def _term_detail_cache_key(ontology_id: str, version_id: str, term_iri: str, lang: str | None) -> str:
    import hashlib
    payload = f"{ontology_id}\x1f{version_id}\x1f{term_iri}\x1f{lang or ''}"
    h = hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()
    # v4: ClassRef items in term-detail now carry `source` for chip rendering.
    return f"search:term:v4:{h}"


@router.get("/{ontology_id}/{version_id}/terms/{term_iri:path}", summary="Term detail")
async def get_term(
    ontology_id: str,
    version_id: str,
    term_iri: str,
    lang: str | None = Query(None, description="BCP-47 language tag"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    import asyncio
    import json as _json_cache
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

    version = await _get_version_or_404(db, ontology_id, version_id)

    # Response cache — repeat clicks across a session are essentially free.
    _r_cache = _get_redis()
    _cache_key = _term_detail_cache_key(ontology_id, version_id, term_iri, lang)
    _cached = await asyncio.to_thread(_r_cache.get, _cache_key)
    if _cached:
        return _json_cache.loads(_cached)

    store = get_store()
    g_iri = graph_iri(ontology_id, version_id)

    # Fetch raw asserted properties + asserted subclasses (both blocking — run in thread)
    props_query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?pred ?obj (lang(?obj) AS ?lang) WHERE {{
            GRAPH <{g_iri}> {{
                <{term_iri}> ?pred ?obj .
                FILTER(isIRI(?obj) || isLiteral(?obj))
            }}
        }}
    """
    asserted_sub_query = f"""
        SELECT ?sub WHERE {{
            GRAPH <{g_iri}> {{
                ?sub <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{term_iri}> .
                FILTER(isIRI(?sub))
            }}
        }}
        ORDER BY ?sub
    """
    prop_rows, asserted_sub_iris = await asyncio.to_thread(
        _sparql_term_props, store, props_query, asserted_sub_query
    )
    if not prop_rows:
        raise HTTPException(status_code=404, detail="Term not found in this ontology version")

    properties: dict[str, list] = {}
    properties_typed: dict[str, list] = {}
    for row in prop_rows:
        pred = row["pred"].value
        obj_node = row["obj"]
        obj_val = obj_node.value
        _lang_node = row["lang"]
        lang_tag = _lang_node.value if (_lang_node is not None and _lang_node.value) else None
        properties.setdefault(pred, []).append(obj_val)
        properties_typed.setdefault(pred, []).append({"value": obj_val, "lang": lang_tag})

    # Determine is_property up front — ELK only classifies classes, so for
    # properties we skip both ELK calls (saves ~2-3 s wall-clock per property page).
    _OWL_PROP_TYPES = {
        "http://www.w3.org/2002/07/owl#ObjectProperty",
        "http://www.w3.org/2002/07/owl#DatatypeProperty",
        "http://www.w3.org/2002/07/owl#AnnotationProperty",
    }
    rdf_types = set(properties.get("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", []))
    is_property = bool(rdf_types & _OWL_PROP_TYPES)

    # Inferred sub/superclasses from ELK — run concurrently, ignore if not ready
    async def _elk_subclasses():
        try:
            return await elk_subclasses(version_id, term_iri, direct=False, reasoner=version.reasoner)
        except (ReasoningNotReadyError, ClassNotFoundError):
            return {}
        except Exception:
            return {}

    async def _elk_superclasses():
        try:
            return await elk_superclasses(version_id, term_iri, direct=False, reasoner=version.reasoner)
        except (ReasoningNotReadyError, ClassNotFoundError):
            return {}
        except Exception:
            return {}

    if is_property:
        elk_sub_result = elk_sup_result = {}
    else:
        elk_sub_result, elk_sup_result = await asyncio.gather(
            _elk_subclasses(), _elk_superclasses()
        )

    _OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
    _OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
    # owl:Thing is filtered (noise — every class is a subclass of Thing).
    # owl:Nothing is NOT filtered out of superclasses — when ELK reports
    # `<C> ⊑ owl:Nothing` it means C is unsatisfiable, and the UI explicitly
    # wants to surface that. Symmetric: don't filter Thing out of subclasses
    # because Thing is rarely (only-for-inconsistent-ontologies) reported as a
    # subclass of anything.
    inferred_sub_iris: list[str] = [
        s for s in elk_sub_result.get("subclasses", [])
        if s != _OWL_THING
    ]
    inferred_sup_iris: list[str] = [
        s for s in elk_sup_result.get("superclasses", [])
        if s != _OWL_THING
    ]

    # Asserted superclasses — named-class targets of rdfs:subClassOf
    RDFS_SC = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
    asserted_sup_iris = [v for v in properties.get(RDFS_SC, [])
                         if v.startswith("http://") or v.startswith("https://") or v.startswith("urn:")]


    # Resolve labels from Redis index — bulk-pipelined to avoid one round-trip
    # per IRI (the dominant cost on the cold path for terms with many relationships).
    r = _get_redis()
    _label_cache: dict[str, str] = {}
    # Map IRI → import-source short-name (e.g. 'bfo', 'iao'). Empty/missing
    # means the IRI is native to this ontology — frontend renders no chip.
    _source_cache: dict[str, str] = {}

    def _fallback(iri: str) -> str:
        fragment = iri.rstrip("/")
        return fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]

    def _resolve_labels(iris) -> None:
        """Bulk-prefetch labels for any IRIs not already in the cache (one round-trip)."""
        missing = [i for i in dict.fromkeys(iris) if i and i not in _label_cache]
        if not missing:
            return
        pipe = r.pipeline(transaction=False)
        for i in missing:
            pipe.hgetall(_iri_key(version_id, i))
        for i, detail in zip(missing, pipe.execute()):
            _label_cache[i] = (detail or {}).get("label") or _fallback(i)
            if detail and detail.get("source"):
                _source_cache[i] = detail["source"]

    def _label(iri: str) -> str:
        cached = _label_cache.get(iri)
        if cached is not None:
            return cached
        # Fallback for IRIs discovered late (e.g. inside recursive _build_class_expr).
        detail = r.hgetall(_iri_key(version_id, iri))
        label = (detail or {}).get("label") or _fallback(iri)
        _label_cache[iri] = label
        if detail and detail.get("source"):
            _source_cache[iri] = detail["source"]
        return label

    def _term_list(iris: list[str]) -> list[dict]:
        _resolve_labels(iris)
        items = [
            {"iri": iri, "label": _label(iri), "source": _source_cache.get(iri, "")}
            for iri in iris
        ]
        items.sort(key=lambda t: (t["label"] or t["iri"]).lower())
        return items

    # Prefetch labels for everything we already know we'll need. Postgres
    # `entity_index` is the source of truth for the search/keyword stack and now
    # for label lookups too — one SQL round-trip serves any number of IRIs.
    # IRIs not in entity_index (blank-node-derived expressions discovered late
    # in `_build_class_expr`) fall back to a Redis HGETALL in `_label()` below.
    _pre_iris: list[str] = []
    _pre_iris.extend(asserted_sub_iris)
    _pre_iris.extend(inferred_sub_iris)
    _pre_iris.extend(asserted_sup_iris)
    _pre_iris.extend(inferred_sup_iris)
    for _vals in properties.values():
        for _v in _vals:
            if isinstance(_v, str) and _v.startswith(("http://", "https://", "urn:")):
                _pre_iris.append(_v)

    if _pre_iris:
        _unique_pre = list(dict.fromkeys(_pre_iris))
        _pg_label_rows = (await db.execute(
            text("""
                SELECT iri, primary_label, source
                FROM entity_index
                WHERE version_id = :vid AND iri = ANY(:iris)
            """),
            {"vid": version_id, "iris": _unique_pre},
        )).all()
        for row in _pg_label_rows:
            _label_cache[row.iri] = row.primary_label
            if row.source:
                _source_cache[row.iri] = row.source
        # IRIs not in entity_index get the fragment fallback up-front so we
        # don't fall back to Redis on every miss.
        for _i in _unique_pre:
            _label_cache.setdefault(_i, _fallback(_i))

    # All ancestors: asserted direct parents first, then ELK-inferred (ELK strips asserted parents from its output)
    _all_ancestor_iris: list[str] = list(dict.fromkeys(asserted_sup_iris + inferred_sup_iris))

    import pyoxigraph as _ox

    # ── Sync Oxigraph block ──────────────────────────────────────────────────
    # All blank-node / quad-pattern walks bundled into one threaded function so
    # the entire block runs concurrently with the SPARQL queries below.
    def _compute_oxigraph_block() -> dict:
        _graph_node   = _ox.NamedNode(g_iri)
        _term_node    = _ox.NamedNode(term_iri)
        _RDFS_SC_NODE = _ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
        _OWL_EQ_CLASS = _ox.NamedNode(_OWL + "equivalentClass")
        _OWL_DISJOINT_NODE = _ox.NamedNode(_OWL + "disjointWith")
        _OWL_ADC_NODE      = _ox.NamedNode(_OWL + "AllDisjointClasses")
        _OWL_MEMBERS_NODE  = _ox.NamedNode(_OWL + "members")
        _OWL_DISJOINT_UNION_NODE = _ox.NamedNode(_OWL + "disjointUnionOf")
        _RDF_TYPE_NODE     = _ox.NamedNode(_RDF + "type")

        # Superclass expressions — blank-node targets of rdfs:subClassOf
        superclass_expressions: list[dict] = []
        for _quad in store.quads_for_pattern(_term_node, _RDFS_SC_NODE, None, _graph_node):
            if isinstance(_quad.object, _ox.BlankNode):
                _expr = _build_class_expr(store, _graph_node, _quad.object, _label)
                if _expr.get("type") != "unknown":
                    superclass_expressions.append(_expr)

        # NOTE: inferred_superclass_expressions and inferred_disjoint_with —
        # both ancestor-walking loops — moved to the lazy /expanded endpoint.

        # Equivalent classes (owl:equivalentClass)
        equivalent_to: list[dict] = []
        for _quad in store.quads_for_pattern(_term_node, _OWL_EQ_CLASS, None, _graph_node):
            _expr = _build_class_expr(store, _graph_node, _quad.object, _label)
            if _expr.get("type") != "unknown":
                equivalent_to.append(_expr)

        # Disjoint with (owl:disjointWith)
        disjoint_with: list[dict] = []
        for _quad in store.quads_for_pattern(_term_node, _OWL_DISJOINT_NODE, None, _graph_node):
            _expr = _build_class_expr(store, _graph_node, _quad.object, _label)
            if _expr.get("type") != "unknown":
                disjoint_with.append(_expr)

        # AllDisjointClasses map: iri → co-member IRIs
        _adc_map: dict[str, list[str]] = {}
        for _q in store.quads_for_pattern(None, _RDF_TYPE_NODE, _OWL_ADC_NODE, _graph_node):
            _mem_qs = list(store.quads_for_pattern(_q.subject, _OWL_MEMBERS_NODE, None, _graph_node))
            if not _mem_qs:
                continue
            _miris = [
                m.value for m in _rdf_list_items(store, _graph_node, _mem_qs[0].object)
                if isinstance(m, _ox.NamedNode)
            ]
            for _miri in _miris:
                _adc_map.setdefault(_miri, []).extend(o for o in _miris if o != _miri)

        # NOTE: inferred_disjoint_with moved to /expanded endpoint.

        # Disjoint union of (owl:disjointUnionOf) — each value is an rdf:List
        disjoint_union_of: list[list[dict]] = []
        for _quad in store.quads_for_pattern(_term_node, _OWL_DISJOINT_UNION_NODE, None, _graph_node):
            _members = [
                _build_class_expr(store, _graph_node, _item, _label)
                for _item in _rdf_list_items(store, _graph_node, _quad.object)
            ]
            if _members:
                disjoint_union_of.append(_members)

        # General class axioms — blank nodes whose rdfs:subClassOf target is this term
        general_class_axioms: list[dict] = []
        for _quad in store.quads_for_pattern(None, _RDFS_SC_NODE, _term_node, _graph_node):
            if isinstance(_quad.subject, _ox.BlankNode):
                _expr = _build_class_expr(store, _graph_node, _quad.subject, _label)
                if _expr.get("type") != "unknown":
                    general_class_axioms.append(_expr)

        return {
            "superclass_expressions": superclass_expressions,
            "equivalent_to": equivalent_to,
            "disjoint_with": disjoint_with,
            "disjoint_union_of": disjoint_union_of,
            "general_class_axioms": general_class_axioms,
            "_adc_map": _adc_map,
        }

    # Default page size for usage/class_usage tables. Frontend renders the first
    # USAGE_PAGE_SIZE rows and offers a "Show more" button (separate endpoint).
    USAGE_PAGE_SIZE = 10
    USAGE_SQL_LIMIT = USAGE_PAGE_SIZE + 1  # +1 to detect has_more without a COUNT query

    # ── Per-query helpers ───────────────────────────────────────────────────
    # Each returns its raw rows; label resolution happens after the gather.
    def _run_usage_query(s) -> list[dict]:
        q = f"""
            PREFIX owl:  <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?relation ?restrictType ?filler WHERE {{
                GRAPH <{g_iri}> {{
                    {{ ?class rdfs:subClassOf ?r . BIND("subClassOf" AS ?relation) }}
                    UNION {{ ?class owl:equivalentClass ?r . BIND("equivalentClass" AS ?relation) }}
                    ?r owl:onProperty <{term_iri}> .
                    FILTER(isIRI(?class))
                    {{ ?r owl:someValuesFrom ?filler . BIND("some" AS ?restrictType) }}
                    UNION {{ ?r owl:allValuesFrom ?filler . BIND("only" AS ?restrictType) }}
                    UNION {{ ?r owl:hasValue ?filler . BIND("value" AS ?restrictType) }}
                    UNION {{ ?r owl:minCardinality ?filler . BIND("min" AS ?restrictType) }}
                    UNION {{ ?r owl:maxCardinality ?filler . BIND("max" AS ?restrictType) }}
                    UNION {{ ?r owl:exactCardinality ?filler . BIND("exactly" AS ?restrictType) }}
                    UNION {{ ?r owl:minQualifiedCardinality ?filler . BIND("min" AS ?restrictType) }}
                    UNION {{ ?r owl:maxQualifiedCardinality ?filler . BIND("max" AS ?restrictType) }}
                    UNION {{ ?r owl:exactQualifiedCardinality ?filler . BIND("exactly" AS ?restrictType) }}
                }}
            }}
            ORDER BY ?class ?relation ?restrictType
            LIMIT {USAGE_SQL_LIMIT}
        """
        return _sparql_usage(s, q, _label)

    def _run_class_usage_queries(s, adc_map: dict) -> list[dict]:
        cu_q = f"""
            PREFIX owl:  <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?class ?relation ?prop ?restrictType WHERE {{
                GRAPH <{g_iri}> {{
                    {{ ?r owl:someValuesFrom <{term_iri}> . ?r owl:onProperty ?prop . BIND("some" AS ?restrictType) }}
                    UNION {{ ?r owl:allValuesFrom <{term_iri}> . ?r owl:onProperty ?prop . BIND("only" AS ?restrictType) }}
                    UNION {{ ?r owl:hasValue <{term_iri}> . ?r owl:onProperty ?prop . BIND("value" AS ?restrictType) }}
                    {{ ?class rdfs:subClassOf ?r . FILTER(isIRI(?class)) BIND("subClassOf" AS ?relation) }}
                    UNION {{ ?class owl:equivalentClass ?r . FILTER(isIRI(?class)) BIND("equivalentClass" AS ?relation) }}
                }}
            }}
            ORDER BY ?class ?relation ?prop
            LIMIT {USAGE_SQL_LIMIT}
        """
        disj_q = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT ?class WHERE {{
                GRAPH <{g_iri}> {{
                    ?class owl:disjointWith <{term_iri}> . FILTER(isIRI(?class))
                }}
            }}
            ORDER BY ?class
            LIMIT {USAGE_SQL_LIMIT}
        """
        return _sparql_class_usage(s, cu_q, disj_q, _label, adc_map, term_iri)

    def _run_schema_props_query(s) -> list[dict]:
        q = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?prop ?range WHERE {{
                GRAPH <{g_iri}> {{
                    {{ ?prop rdfs:domain <{term_iri}> }}
                    UNION {{ ?prop <https://schema.org/domainIncludes> <{term_iri}> }}
                    OPTIONAL {{
                        {{ ?prop rdfs:range ?range }} UNION {{ ?prop <https://schema.org/rangeIncludes> ?range }}
                        FILTER(isIRI(?range))
                    }}
                    FILTER(isIRI(?prop))
                }}
            }}
            ORDER BY ?prop
            LIMIT 200
        """
        return [
            {"prop_iri": row["prop"].value,
             "range_iri": row["range"].value if row["range"] is not None else None}
            for row in s.query(q)
        ]

    def _run_inh_schema_props_query(s, anc_iris: list[str]) -> list[dict]:
        if not anc_iris:
            return []
        anc_values = " ".join(f"<{iri}>" for iri in anc_iris)
        q = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?prop ?range ?ancestor WHERE {{
                GRAPH <{g_iri}> {{
                    {{ ?prop rdfs:domain ?ancestor }}
                    UNION {{ ?prop <https://schema.org/domainIncludes> ?ancestor }}
                    OPTIONAL {{
                        {{ ?prop rdfs:range ?range }} UNION {{ ?prop <https://schema.org/rangeIncludes> ?range }}
                        FILTER(isIRI(?range))
                    }}
                    FILTER(isIRI(?prop))
                    VALUES ?ancestor {{ {anc_values} }}
                }}
            }}
            ORDER BY ?ancestor ?prop
            LIMIT 500
        """
        return [
            {"prop_iri": row["prop"].value,
             "range_iri": row["range"].value if row["range"] is not None else None,
             "from_iri": row["ancestor"].value}
            for row in s.query(q)
        ]

    def _check_is_inverse_target(s) -> bool:
        q = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            ASK {{ GRAPH <{g_iri}> {{ ?p owl:inverseOf <{term_iri}> . FILTER(isIRI(?p)) }} }}
        """
        return bool(s.query(q))

    # ── Run everything concurrently ──────────────────────────────────────────
    # Phase 1 (Oxigraph sync block + direct schema_properties / usage / inverse-target).
    # `inherited_schema_properties` is deferred to the /expanded endpoint because the
    # 30-ancestor VALUES SPARQL is the next slowest piece after ELK.
    _phase1 = [
        asyncio.to_thread(_compute_oxigraph_block),       # 0: includes _adc_map
        asyncio.to_thread(_check_is_inverse_target, store),  # 1
    ]
    if is_property:
        _phase1.append(asyncio.to_thread(_run_usage_query, store))         # 2
    else:
        _phase1.append(asyncio.to_thread(_run_schema_props_query, store))  # 2

    _results_1 = await asyncio.gather(*_phase1)
    _ox_result = _results_1[0]
    is_inverse_target = _results_1[1]

    superclass_expressions          = _ox_result["superclass_expressions"]
    equivalent_to                   = _ox_result["equivalent_to"]
    disjoint_with                   = _ox_result["disjoint_with"]
    disjoint_union_of               = _ox_result["disjoint_union_of"]
    general_class_axioms            = _ox_result["general_class_axioms"]
    _adc_map                        = _ox_result["_adc_map"]
    # Deferred to /expanded — empty in the main response.
    inferred_superclass_expressions: list[dict] = []
    inferred_disjoint_with: list[dict] = []
    inherited_schema_properties: list[dict] = []

    usage: list[dict] = []
    schema_properties: list[dict] = []
    usage_has_more = False
    class_usage_has_more = False

    if is_property:
        _usage_rows = _results_1[2]
        usage_has_more = len(_usage_rows) > USAGE_PAGE_SIZE
        usage = _usage_rows[:USAGE_PAGE_SIZE]
    else:
        _dp_rows = _results_1[2]
        _resolve_labels(
            [r["prop_iri"] for r in _dp_rows]
            + [r["range_iri"] for r in _dp_rows if r["range_iri"]]
        )
        for row in _dp_rows:
            schema_properties.append({
                "prop_iri": row["prop_iri"],
                "prop_label": _label(row["prop_iri"]),
                "range_iri": row["range_iri"],
                "range_label": _label(row["range_iri"]) if row["range_iri"] else None,
            })

    # Phase 2 — class_usage needs _adc_map (only run when this term is a class).
    class_usage: list[dict] = []
    if not is_property:
        _cu_rows = await asyncio.to_thread(_run_class_usage_queries, store, _adc_map)
        class_usage_has_more = len(_cu_rows) > USAGE_PAGE_SIZE
        class_usage = _cu_rows[:USAGE_PAGE_SIZE]

    term_detail = r.hgetall(_iri_key(version_id, term_iri))
    source = term_detail.get("source", "") if term_detail else ""

    _RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
    top_label = (properties.get(_RDFS_LABEL) or [None])[0] or _label(term_iri)

    # Language resolution and typed arrays
    from ontoexplorer.modules.search.lang import resolve_lang
    from ontoexplorer.models.db import Ontology as _Ontology
    from sqlalchemy import select as _select

    _ontology_row = (await db.execute(
        _select(_Ontology).where(_Ontology.id == ontology_id)
    )).scalar_one_or_none()
    effective_lang = resolve_lang(lang, _ontology_row, _user if isinstance(_user, type(None)) is False else None)

    # Predicate sets for label/definition/synonym extraction
    _LABEL_PREDS = {
        "http://www.w3.org/2000/01/rdf-schema#label",
        "http://www.w3.org/2004/02/skos/core#prefLabel",
        "http://www.w3.org/2004/02/skos/core#altLabel",
    }
    _DEFINITION_PREDS = {
        "http://purl.obolibrary.org/obo/IAO_0000115",
        "http://www.w3.org/2004/02/skos/core#definition",
        "http://www.w3.org/2000/01/rdf-schema#comment",
    }
    # IAO_0000600 — semi-formal description used by BFO/OBO for primitive
    # entities that resist a closed-form definition. Surfaced as its own
    # field so the UI can render it directly after the formal definition.
    _ELUCIDATION_PREDS = {
        "http://purl.obolibrary.org/obo/IAO_0000600",
    }
    _SYNONYM_PREDS = {
        "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
        "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
        "http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym",
        "http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym",
    }

    def _dedup_by_value(entries: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out = []
        for e in entries:
            if e["value"] not in seen:
                seen.add(e["value"])
                out.append(e)
        return out

    term_labels       = _dedup_by_value([v for p in _LABEL_PREDS       for v in properties_typed.get(p, [])])
    term_definitions  = _dedup_by_value([v for p in _DEFINITION_PREDS  for v in properties_typed.get(p, [])])
    term_elucidations = _dedup_by_value([v for p in _ELUCIDATION_PREDS for v in properties_typed.get(p, [])])
    term_synonyms     = _dedup_by_value([v for p in _SYNONYM_PREDS     for v in properties_typed.get(p, [])])

    # Primary label: prefer effective_lang if set
    def _typed_primary_label(entries):
        if not entries:
            return term_iri.split("/")[-1]
        if effective_lang:
            found = next((e["value"] for e in entries if e.get("lang") == effective_lang), None)
            if found:
                return found
        return entries[0]["value"]

    typed_label = _typed_primary_label(term_labels)

    # For individuals: resolve rdf:type classes (excluding OWL meta-types) with labels
    _OWL_META = {
        "http://www.w3.org/2002/07/owl#NamedIndividual",
        "http://www.w3.org/2002/07/owl#Class",
        "http://www.w3.org/2002/07/owl#ObjectProperty",
        "http://www.w3.org/2002/07/owl#DatatypeProperty",
        "http://www.w3.org/2002/07/owl#AnnotationProperty",
        "http://www.w3.org/2002/07/owl#Ontology",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property",
        "http://www.w3.org/2000/01/rdf-schema#Class",
    }
    _RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    type_of = []
    if "http://www.w3.org/2002/07/owl#NamedIndividual" in properties.get(_RDF_TYPE, []):
        type_of = _term_list([iri for iri in properties.get(_RDF_TYPE, []) if iri not in _OWL_META])

    # Human-readable label for each predicate IRI used by this term — joined
    # from entity_index (annotation properties in this same ontology version
    # are themselves indexed entities). Frontend renders the predicate column
    # using this map, falling back to a static well-known table and the IRI
    # fragment.
    from ontoexplorer.models.db import EntityIndex as _EntityIndex
    _pred_iris = list(properties_typed.keys())
    property_labels: dict[str, str] = {}
    if _pred_iris:
        _pl_rows = (await db.execute(
            _select(_EntityIndex.iri, _EntityIndex.primary_label).where(
                _EntityIndex.version_id == version_id,
                _EntityIndex.iri.in_(_pred_iris),
            )
        )).all()
        property_labels = {iri: label for iri, label in _pl_rows}

    _payload = {
        "iri": term_iri,
        "label": typed_label if term_labels else top_label,
        "labels": term_labels,
        "definitions": term_definitions,
        "elucidations": term_elucidations,
        "synonyms": term_synonyms,
        "lang": effective_lang,
        "source": source,
        "properties": properties_typed,
        "property_labels": property_labels,
        "type_of": type_of,
        "is_inverse_target": is_inverse_target,
        "superclasses": {
            "asserted": _term_list(asserted_sup_iris),
            "inferred": _term_list(inferred_sup_iris),
        },
        "subclasses": {
            "asserted": _term_list(asserted_sub_iris),
            "inferred": _term_list(inferred_sub_iris),
        },
        "superclass_expressions": superclass_expressions,
        "inferred_superclass_expressions": inferred_superclass_expressions,
        "equivalent_to": equivalent_to,
        "disjoint_with": disjoint_with,
        "inferred_disjoint_with": inferred_disjoint_with,
        "disjoint_union_of": disjoint_union_of,
        "general_class_axioms": general_class_axioms,
        "usage": usage,
        "usage_has_more": usage_has_more,
        "class_usage": class_usage,
        "class_usage_has_more": class_usage_has_more,
        "schema_properties": schema_properties,
        "inherited_schema_properties": inherited_schema_properties,
    }
    await asyncio.to_thread(_r_cache.set, _cache_key, _json_cache.dumps(_payload), _TERM_DETAIL_CACHE_TTL)
    return _payload


@router.get(
    "/{ontology_id}/{version_id}/term-usage/{term_iri:path}",
    summary="Paginated usage / class_usage rows for a term (Show more)",
)
async def get_term_usage_page(
    ontology_id: str,
    version_id: str,
    term_iri: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Return a paginated slice of the usage rows for a term.

    Routes to `usage` (property-onProperty restrictions) if the term is a property,
    otherwise `class_usage` (axioms referencing the term as filler / disjoint).
    Used by the frontend's "Show more" button on term-detail tables.
    """
    import asyncio
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

    await _get_version_or_404(db, ontology_id, version_id)
    store = get_store()
    g_iri = graph_iri(ontology_id, version_id)
    r = _get_redis()

    _label_cache: dict[str, str] = {}

    def _fallback(iri: str) -> str:
        fragment = iri.rstrip("/")
        return fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]

    def _resolve_labels(iris) -> None:
        missing = [i for i in dict.fromkeys(iris) if i and i not in _label_cache]
        if not missing:
            return
        pipe = r.pipeline(transaction=False)
        for i in missing:
            pipe.hgetall(_iri_key(version_id, i))
        for i, detail in zip(missing, pipe.execute()):
            _label_cache[i] = (detail or {}).get("label") or _fallback(i)

    def _label(iri: str) -> str:
        cached = _label_cache.get(iri)
        if cached is not None:
            return cached
        detail = r.hgetall(_iri_key(version_id, iri))
        label = (detail or {}).get("label") or _fallback(iri)
        _label_cache[iri] = label
        return label

    # Determine kind via the term's rdf:type. Cheap: one SPARQL ASK.
    def _is_property(s) -> bool:
        q = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            ASK {{
              GRAPH <{g_iri}> {{
                {{ <{term_iri}> a owl:ObjectProperty }}
                UNION {{ <{term_iri}> a owl:DatatypeProperty }}
                UNION {{ <{term_iri}> a owl:AnnotationProperty }}
              }}
            }}
        """
        return bool(s.query(q))

    is_prop = await asyncio.to_thread(_is_property, store)

    sql_offset = offset
    sql_limit = limit + 1  # +1 to detect has_more

    if is_prop:
        q = f"""
            PREFIX owl:  <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?relation ?restrictType ?filler WHERE {{
                GRAPH <{g_iri}> {{
                    {{ ?class rdfs:subClassOf ?r . BIND("subClassOf" AS ?relation) }}
                    UNION {{ ?class owl:equivalentClass ?r . BIND("equivalentClass" AS ?relation) }}
                    ?r owl:onProperty <{term_iri}> .
                    FILTER(isIRI(?class))
                    {{ ?r owl:someValuesFrom ?filler . BIND("some" AS ?restrictType) }}
                    UNION {{ ?r owl:allValuesFrom ?filler . BIND("only" AS ?restrictType) }}
                    UNION {{ ?r owl:hasValue ?filler . BIND("value" AS ?restrictType) }}
                    UNION {{ ?r owl:minCardinality ?filler . BIND("min" AS ?restrictType) }}
                    UNION {{ ?r owl:maxCardinality ?filler . BIND("max" AS ?restrictType) }}
                    UNION {{ ?r owl:exactCardinality ?filler . BIND("exactly" AS ?restrictType) }}
                    UNION {{ ?r owl:minQualifiedCardinality ?filler . BIND("min" AS ?restrictType) }}
                    UNION {{ ?r owl:maxQualifiedCardinality ?filler . BIND("max" AS ?restrictType) }}
                    UNION {{ ?r owl:exactQualifiedCardinality ?filler . BIND("exactly" AS ?restrictType) }}
                }}
            }}
            ORDER BY ?class ?relation ?restrictType
            OFFSET {sql_offset} LIMIT {sql_limit}
        """
        rows = await asyncio.to_thread(_sparql_usage, store, q, _label)
        has_more = len(rows) > limit
        return {"kind": "property", "offset": offset, "limit": limit,
                "items": rows[:limit], "has_more": has_more}

    # class_usage path needs _adc_map
    import pyoxigraph as _ox
    def _compute_adc_map(s):
        _graph_node = _ox.NamedNode(g_iri)
        _OWL_ADC_NODE     = _ox.NamedNode(_OWL + "AllDisjointClasses")
        _OWL_MEMBERS_NODE = _ox.NamedNode(_OWL + "members")
        _RDF_TYPE_NODE    = _ox.NamedNode(_RDF + "type")
        adc: dict[str, list[str]] = {}
        for q in s.quads_for_pattern(None, _RDF_TYPE_NODE, _OWL_ADC_NODE, _graph_node):
            mem_qs = list(s.quads_for_pattern(q.subject, _OWL_MEMBERS_NODE, None, _graph_node))
            if not mem_qs:
                continue
            miris = [
                m.value for m in _rdf_list_items(s, _graph_node, mem_qs[0].object)
                if isinstance(m, _ox.NamedNode)
            ]
            for miri in miris:
                adc.setdefault(miri, []).extend(o for o in miris if o != miri)
        return adc

    cu_q = f"""
        PREFIX owl:  <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?class ?relation ?prop ?restrictType WHERE {{
            GRAPH <{g_iri}> {{
                {{ ?r owl:someValuesFrom <{term_iri}> . ?r owl:onProperty ?prop . BIND("some" AS ?restrictType) }}
                UNION {{ ?r owl:allValuesFrom <{term_iri}> . ?r owl:onProperty ?prop . BIND("only" AS ?restrictType) }}
                UNION {{ ?r owl:hasValue <{term_iri}> . ?r owl:onProperty ?prop . BIND("value" AS ?restrictType) }}
                {{ ?class rdfs:subClassOf ?r . FILTER(isIRI(?class)) BIND("subClassOf" AS ?relation) }}
                UNION {{ ?class owl:equivalentClass ?r . FILTER(isIRI(?class)) BIND("equivalentClass" AS ?relation) }}
            }}
        }}
        ORDER BY ?class ?relation ?prop
        OFFSET {sql_offset} LIMIT {sql_limit}
    """
    disj_q = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT ?class WHERE {{
            GRAPH <{g_iri}> {{
                ?class owl:disjointWith <{term_iri}> . FILTER(isIRI(?class))
            }}
        }}
        ORDER BY ?class
        OFFSET {sql_offset} LIMIT {sql_limit}
    """
    _adc_map = await asyncio.to_thread(_compute_adc_map, store)
    rows = await asyncio.to_thread(
        _sparql_class_usage, store, cu_q, disj_q, _label, _adc_map, term_iri
    )
    has_more = len(rows) > limit
    return {"kind": "class", "offset": offset, "limit": limit,
            "items": rows[:limit], "has_more": has_more}


# ── Term detail (expanded) ───────────────────────────────────────────────────

_TERM_EXPANDED_CACHE_TTL = 300


def _term_expanded_cache_key(ontology_id: str, version_id: str, term_iri: str, lang: str | None) -> str:
    import hashlib
    payload = f"{ontology_id}\x1f{version_id}\x1fexp\x1f{term_iri}\x1f{lang or ''}"
    h = hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()
    return f"search:term:{h}"


@router.get(
    "/{ontology_id}/{version_id}/term-expanded/{term_iri:path}",
    summary="Lazy-loaded heavy sections of a term — inferred superclass expressions, "
            "inferred disjoint-with, inherited schema_properties",
)
async def get_term_expanded(
    ontology_id: str,
    version_id: str,
    term_iri: str,
    lang: str | None = Query(None, description="BCP-47 language tag (currently unused; reserved)"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """The three sections lifted off the main /terms/{iri} response.

    The main endpoint now returns ~1 s cold because these expensive
    ancestor-walking sections defer here. Frontend fetches this asynchronously
    after the main panel renders, so the user sees most data immediately and
    the inferred-walk results fill in shortly after.
    """
    import asyncio
    import json as _json_cache
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

    version = await _get_version_or_404(db, ontology_id, version_id)

    _r_cache = _get_redis()
    _cache_key = _term_expanded_cache_key(ontology_id, version_id, term_iri, lang)
    _cached = await asyncio.to_thread(_r_cache.get, _cache_key)
    if _cached:
        return _json_cache.loads(_cached)

    store = get_store()
    g_iri = graph_iri(ontology_id, version_id)
    r = _get_redis()

    # Reconstruct the label cache locally (handler-scoped, same as /terms/{iri}).
    _label_cache: dict[str, str] = {}

    def _fallback(iri: str) -> str:
        fragment = iri.rstrip("/")
        return fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]

    def _resolve_labels(iris) -> None:
        missing = [i for i in dict.fromkeys(iris) if i and i not in _label_cache]
        if not missing:
            return
        pipe = r.pipeline(transaction=False)
        for i in missing:
            pipe.hgetall(_iri_key(version_id, i))
        for i, detail in zip(missing, pipe.execute()):
            _label_cache[i] = (detail or {}).get("label") or _fallback(i)

    def _label(iri: str) -> str:
        cached = _label_cache.get(iri)
        if cached is not None:
            return cached
        detail = r.hgetall(_iri_key(version_id, iri))
        label = (detail or {}).get("label") or _fallback(iri)
        _label_cache[iri] = label
        return label

    # Resolve ancestors via ELK (cached). Skip ELK for properties — empty result.
    rdf_types_q = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?t WHERE {{ GRAPH <{g_iri}> {{ <{term_iri}> rdf:type ?t . FILTER(isIRI(?t)) }} }}
    """
    def _get_types(s):
        return [row["t"].value for row in s.query(rdf_types_q)]

    rdf_types = set(await asyncio.to_thread(_get_types, store))
    _PROP_TYPES = {
        "http://www.w3.org/2002/07/owl#ObjectProperty",
        "http://www.w3.org/2002/07/owl#DatatypeProperty",
        "http://www.w3.org/2002/07/owl#AnnotationProperty",
    }
    is_property = bool(rdf_types & _PROP_TYPES)

    asserted_sup_q = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?sup WHERE {{
            GRAPH <{g_iri}> {{ <{term_iri}> rdfs:subClassOf ?sup . FILTER(isIRI(?sup)) }}
        }}
    """
    def _get_asserted_sups(s):
        return [row["sup"].value for row in s.query(asserted_sup_q)]

    asserted_sup_iris = await asyncio.to_thread(_get_asserted_sups, store)

    if not is_property:
        try:
            sup_result = await elk_superclasses(version_id, term_iri, direct=False, reasoner=version.reasoner)
        except Exception:
            sup_result = {}
        _OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        inferred_sup_iris = [s for s in sup_result.get("superclasses", []) if s != _OWL_THING]
    else:
        inferred_sup_iris = []

    _all_ancestor_iris = list(dict.fromkeys(asserted_sup_iris + inferred_sup_iris))

    # Sync Oxigraph block for the two ancestor-walking sections.
    import pyoxigraph as _ox
    import json as _json_mod

    def _compute_expanded_ox() -> dict:
        _graph_node   = _ox.NamedNode(g_iri)
        _RDFS_SC_NODE = _ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
        _OWL_DISJOINT_NODE = _ox.NamedNode(_OWL + "disjointWith")
        _OWL_ADC_NODE      = _ox.NamedNode(_OWL + "AllDisjointClasses")
        _OWL_MEMBERS_NODE  = _ox.NamedNode(_OWL + "members")
        _RDF_TYPE_NODE     = _ox.NamedNode(_RDF + "type")

        # inferred_superclass_expressions
        inferred_superclass_expressions: list[dict] = []
        _seen_expr_keys: set[str] = set()
        for _sup_iri in _all_ancestor_iris[:20]:
            _sup_node = _ox.NamedNode(_sup_iri)
            for _quad in store.quads_for_pattern(_sup_node, _RDFS_SC_NODE, None, _graph_node):
                if isinstance(_quad.object, _ox.BlankNode):
                    _expr = _build_class_expr(store, _graph_node, _quad.object, _label)
                    if _expr.get("type") != "unknown":
                        _key = _json_mod.dumps(_expr, sort_keys=True)
                        if _key not in _seen_expr_keys:
                            _seen_expr_keys.add(_key)
                            inferred_superclass_expressions.append({
                                "expr": _expr,
                                "from_iri": _sup_iri,
                                "from_label": _label(_sup_iri),
                            })
            if len(inferred_superclass_expressions) >= 50:
                break

        # _adc_map (full graph scan; isolated to this endpoint now)
        _adc_map: dict[str, list[str]] = {}
        for _q in store.quads_for_pattern(None, _RDF_TYPE_NODE, _OWL_ADC_NODE, _graph_node):
            _mem_qs = list(store.quads_for_pattern(_q.subject, _OWL_MEMBERS_NODE, None, _graph_node))
            if not _mem_qs:
                continue
            _miris = [
                m.value for m in _rdf_list_items(store, _graph_node, _mem_qs[0].object)
                if isinstance(m, _ox.NamedNode)
            ]
            for _miri in _miris:
                _adc_map.setdefault(_miri, []).extend(o for o in _miris if o != _miri)

        # Prefetch partner labels in one pipeline
        partner_iris: list[str] = []
        for _anc in _all_ancestor_iris:
            partner_iris.extend(_adc_map.get(_anc, []))
        _resolve_labels(partner_iris)

        # inferred_disjoint_with — walk ancestors; pairwise + AllDisjointClasses
        inferred_disjoint_with: list[dict] = []
        _seen_disjoint_keys: set[str] = set()
        for _sup_iri in _all_ancestor_iris:
            _sup_node = _ox.NamedNode(_sup_iri)
            for _quad in store.quads_for_pattern(_sup_node, _OWL_DISJOINT_NODE, None, _graph_node):
                _expr = _build_class_expr(store, _graph_node, _quad.object, _label)
                if _expr.get("type") != "unknown":
                    _key = _json_mod.dumps(_expr, sort_keys=True)
                    if _key not in _seen_disjoint_keys:
                        _seen_disjoint_keys.add(_key)
                        inferred_disjoint_with.append({
                            "expr": _expr, "from_iri": _sup_iri, "from_label": _label(_sup_iri),
                        })
            for _partner_iri in _adc_map.get(_sup_iri, []):
                _expr = {"type": "named", "iri": _partner_iri, "label": _label(_partner_iri)}
                _key = _json_mod.dumps(_expr, sort_keys=True)
                if _key not in _seen_disjoint_keys:
                    _seen_disjoint_keys.add(_key)
                    inferred_disjoint_with.append({
                        "expr": _expr, "from_iri": _sup_iri, "from_label": _label(_sup_iri),
                    })

        return {
            "inferred_superclass_expressions": inferred_superclass_expressions,
            "inferred_disjoint_with": inferred_disjoint_with,
        }

    # inherited_schema_properties (only meaningful for classes with ancestors)
    def _run_inh_schema(s):
        _anc_iris = _all_ancestor_iris[:30]
        if not _anc_iris:
            return []
        anc_values = " ".join(f"<{iri}>" for iri in _anc_iris)
        q = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?prop ?range ?ancestor WHERE {{
                GRAPH <{g_iri}> {{
                    {{ ?prop rdfs:domain ?ancestor }}
                    UNION {{ ?prop <https://schema.org/domainIncludes> ?ancestor }}
                    OPTIONAL {{
                        {{ ?prop rdfs:range ?range }} UNION {{ ?prop <https://schema.org/rangeIncludes> ?range }}
                        FILTER(isIRI(?range))
                    }}
                    FILTER(isIRI(?prop))
                    VALUES ?ancestor {{ {anc_values} }}
                }}
            }}
            ORDER BY ?ancestor ?prop
            LIMIT 500
        """
        return [
            {"prop_iri": row["prop"].value,
             "range_iri": row["range"].value if row["range"] is not None else None,
             "from_iri": row["ancestor"].value}
            for row in s.query(q)
        ]

    if is_property:
        ox_result, idp_rows = await asyncio.gather(
            asyncio.to_thread(_compute_expanded_ox),
            asyncio.to_thread(lambda s: [], store),  # no-op, keeps result tuple shape
        )
    else:
        ox_result, idp_rows = await asyncio.gather(
            asyncio.to_thread(_compute_expanded_ox),
            asyncio.to_thread(_run_inh_schema, store),
        )

    # Bulk-resolve labels for inherited_schema_properties rows.
    _resolve_labels(
        [r["prop_iri"] for r in idp_rows]
        + [r["range_iri"] for r in idp_rows if r["range_iri"]]
        + [r["from_iri"] for r in idp_rows]
    )
    inherited_schema_properties = [
        {
            "prop_iri": r["prop_iri"],
            "prop_label": _label(r["prop_iri"]),
            "range_iri": r["range_iri"],
            "range_label": _label(r["range_iri"]) if r["range_iri"] else None,
            "from_iri": r["from_iri"],
            "from_label": _label(r["from_iri"]),
        }
        for r in idp_rows
    ]

    payload = {
        "inferred_superclass_expressions": ox_result["inferred_superclass_expressions"],
        "inferred_disjoint_with":          ox_result["inferred_disjoint_with"],
        "inherited_schema_properties":     inherited_schema_properties,
    }
    await asyncio.to_thread(_r_cache.set, _cache_key, _json_cache.dumps(payload), _TERM_EXPANDED_CACHE_TTL)
    return payload


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
            GRAPH <{inferred_iri}> {{ ?sub rdfs:subClassOf ?sup . FILTER(isIRI(?sub) && isIRI(?sup)) }}
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
    version = await _get_version_or_404(db, ontology_id, version_id)
    try:
        return await elk_superclasses(version_id, cls, direct=direct, reasoner=version.reasoner)
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
    version = await _get_version_or_404(db, ontology_id, version_id)
    try:
        return await elk_subclasses(version_id, cls, direct=direct, reasoner=version.reasoner)
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
    lang: str | None = Query(None, description="Preferred BCP-47 language tag for labels"),
    hide_obsolete: bool = Query(True, description="Exclude owl:deprecated terms"),
    db: AsyncSession = Depends(get_db),
):
    """Return direct inferred subclasses from ELK with labels resolved from the Redis index.

    Uses the full cached classification result so a single ELK call covers all nodes.
    Root request (cls=owl:Thing) returns classes with no direct inferred superclass.
    """
    import json as _json
    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.reasoning import get_classification
    from ontoexplorer.modules.search.indexer import _get_redis, _iri_key, _deprecated_key

    try:
        classification = await get_classification(version_id)
    except Exception:
        return {"terms": [], "reasoning_available": False}

    r = _get_redis()
    deprecated_iris: set[str] = r.smembers(_deprecated_key(version_id)) if hide_obsolete else set()

    def _compute() -> dict:
        elk_direct: dict[str, list[str]] = classification.get("direct_superclasses", {})
        elk_all:    dict[str, list[str]] = classification.get("superclasses", {})
        # ELK doesn't put owl:Nothing in direct_superclasses even for unsat
        # classes — they need to be looked up from the separate `unsatisfiable`
        # list. Treat that list as if those classes had owl:Nothing as a direct
        # parent so the inferred tree can place them under it.
        unsat_iris: set[str] = set(classification.get("unsatisfiable", []))
        # owl:Thing is filtered (it's the universal root; every class trivially
        # subclasses it — noise). owl:Nothing is KEPT as a navigable parent so
        # unsatisfiable classes appear under it (Protégé-style "broken corner").
        _excluded = {_OWL_THING}

        def _direct_parents(c: str) -> list[str]:
            if c in elk_direct:
                parents = [p for p in elk_direct[c] if p not in _excluded]
            else:
                raw = [p for p in elk_all.get(c, []) if p not in _excluded]
                parents = [p for p in raw
                           if not any(p in elk_all.get(q, []) for q in raw if q != p)]
            # If ELK marked this class as unsatisfiable, include owl:Nothing as
            # a direct parent — Protégé convention.
            if c in unsat_iris and _OWL_NOTHING not in parents:
                parents.append(_OWL_NOTHING)
            return parents

        # Include classes that appear only as parents (values) — ELK omits
        # owl:Thing as a superclass, so single-root ontologies like SULO have
        # their root only in the values, never as a key.
        all_classes = set(elk_direct.keys()) | set(elk_all.keys()) | unsat_iris
        for parents in elk_direct.values():
            all_classes.update(parents)
        for parents in elk_all.values():
            all_classes.update(parents)
        all_classes -= {_OWL_THING}
        if hide_obsolete:
            all_classes -= deprecated_iris

        # Pre-build children index (O(N)) so has_children lookups are O(1) not O(N²).
        children_of: dict[str, set[str]] = {}
        for c in all_classes:
            for p in _direct_parents(c):
                children_of.setdefault(p, set()).add(c)

        # When unsat classes exist, surface owl:Nothing as a synthetic top-level
        # node so the user can expand into the population of unsatisfiable
        # classes from the inferred tree's root.
        nothing_children = children_of.get(_OWL_NOTHING, set())

        if cls == _OWL_THING:
            roots = sorted(c for c in all_classes if not _direct_parents(c))
            if nothing_children:
                roots = [_OWL_NOTHING] + roots
            child_iris = roots
        elif cls == _OWL_NOTHING:
            child_iris = sorted(nothing_children)
        else:
            child_iris = sorted(children_of.get(cls, []))

        # Batch all Redis label lookups into a single pipeline round-trip.
        pipe = r.pipeline(transaction=False)
        for iri in child_iris:
            pipe.hgetall(_iri_key(version_id, iri))
        details_list = pipe.execute()

        def _label_and_lang(detail: dict) -> tuple[str, str | None]:
            if detail:
                if lang and detail.get("labels"):
                    labels = _json.loads(detail["labels"])
                    match = next((e for e in labels if e.get("lang") == lang), None)
                    if match:
                        return match["value"], lang
                    untagged = next((e for e in labels if not e.get("lang")), None)
                    if untagged:
                        return untagged["value"], None
                if detail.get("label"):
                    return detail["label"], None
            return None, None

        terms = []
        for iri, detail in zip(child_iris, details_list):
            label, lang_tag = _label_and_lang(detail)
            if label is None:
                fragment = iri.rstrip("/")
                label = fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]
            term: dict = {"iri": iri, "label": label, "has_children": bool(children_of.get(iri))}
            source = (detail or {}).get("source")
            if source:
                term["source"] = source
            if lang_tag:
                term["lang"] = lang_tag
            # ELK-detected unsat classes get the red `is_unsatisfiable` flag.
            if iri in unsat_iris:
                term["is_unsatisfiable"] = True
            # The synthetic owl:Nothing node — annotate so the frontend renders
            # it with the same softer-red treatment as in the asserted tree.
            if iri == _OWL_NOTHING:
                term["unsat_children_count"] = len(nothing_children)
            terms.append(term)

        return {"terms": terms, "reasoning_available": True}

    return await asyncio.to_thread(_compute)


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
        seen: dict[str, tuple[str | None, int]] = {}
        for row in s.query(q):
            iri = row["ancestor"].value
            lbl_node = row["label"]
            label = lbl_node.value if (lbl_node is not None and hasattr(lbl_node, "value")) else None
            lang = (lbl_node.language if hasattr(lbl_node, "language") else None) if lbl_node is not None else None
            score = 2 if lang == "en" else (1 if lang is None or lang == "" else 0)
            prev = seen.get(iri)
            if prev is None or score > prev[1]:
                seen[iri] = (label, score)
        return [{"iri": iri, "label": lbl} for iri, (lbl, _) in seen.items()]

    ancestors_out = await asyncio.to_thread(_run, store, query)
    return {"ancestors": ancestors_out}


class JustificationRequest(BaseModel):
    sub: str
    sup: str | None = None
    type: str | None = None         # "unsatisfiable" when sup is omitted
    max_justifications: int = 1     # 0 = find all


@router.get("/{ontology_id}/{version_id}/justification", summary="Justifications for a subclass inference")
async def get_justification(
    ontology_id: str,
    version_id: str,
    sub: str = Query(..., description="Subclass IRI"),
    sup: str = Query(..., description="Superclass IRI"),
    max_justifications: int = Query(3, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
):
    import asyncio
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

    await _get_version_or_404(db, ontology_id, version_id)

    r = _get_redis()

    def _label(iri: str) -> str:
        detail = r.hgetall(_iri_key(version_id, iri))
        if detail and detail.get("label"):
            return detail["label"]
        fragment = iri.rstrip("/")
        return fragment.split("#")[-1] if "#" in fragment else fragment.split("/")[-1]

    # Try ELK first — uses proof traces, handles complex inferences (CR3/CR4/CR5)
    rendered: list[list[dict]] = []
    try:
        elk_result = await asyncio.wait_for(
            elk_request_justification(version_id, sub, sup, max_justifications),
            timeout=60.0,
        )
        if elk_result.get("timed_out"):
            return {"justifications": [], "timed_out": True, "reasoning_available": True}
        rendered = [
            _render_justification(just_ntriples, _label)
            for just_ntriples in elk_result.get("justifications", [])
            if just_ntriples
        ]
    except Exception:
        pass  # Fall through to BFS

    # Fallback: BFS over asserted subClassOf edges in Oxigraph
    # Covers transitive chains even when ELK proof traces are unavailable.
    if not rendered:
        store  = get_store()
        g_iri  = graph_iri(ontology_id, version_id)
        rendered = await asyncio.to_thread(_find_subclass_path, store, g_iri, sub, sup, _label)

    return {"justifications": rendered, "timed_out": False, "reasoning_available": True}


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
        from ontoexplorer.modules.search.indexer import _get_redis, _stats_cache_key
        _get_redis().delete(_stats_cache_key(version_id))
    except Exception:
        pass  # Non-fatal

    # Drop entity_index rows for the deprecated version so they don't waste
    # space (the SQL search filter excludes them anyway, but the rows persist).
    try:
        await db.execute(
            text("DELETE FROM entity_index WHERE version_id = :vid"),
            {"vid": version_id},
        )
        await db.commit()
    except Exception:
        pass  # Non-fatal

    # Drop shared cross-process search caches so deprecated results disappear immediately.
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        _r = _get_redis()
        for _pattern in ("search:result:*", "search:autocomplete:*", "search:term:*"):
            for _k in _r.scan_iter(_pattern, count=500):
                _r.delete(_k)
    except Exception:
        pass

    return {"detail": f"Version {version_id} deprecated"}


@router.delete("/{ontology_id}", summary="Delete an ontology and all its versions")
async def delete_ontology(
    ontology_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    ontology = await _get_ontology_or_404(db, ontology_id)
    await db.delete(ontology)
    await db.commit()
    return Response(status_code=204)


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
    return {"id": o.id, "iri": o.iri, "shortname": o.shortname, "title": o.title, "groups": o.groups or [], "auto_sync": o.auto_sync, "created_at": o.created_at.isoformat()}


def _version_dict(v: OntologyVersion) -> dict:
    return {
        "id": v.id,
        "ontology_id": v.ontology_id,
        "version_iri": v.version_iri,
        "format": v.format,
        "status": v.status,
        "sha256": v.sha256,
        "triple_count": v.triple_count,
        "download_url": f"/api/v1/ontologies/{v.ontology_id}/{v.id}/download",
        "created_at": v.created_at.isoformat(),
    }


def _negotiate_response(request: Request, data: dict, subject_iri: str | None = None) -> Response:
    accept = request.headers.get("accept", "application/json")
    if "text/turtle" in accept or "application/rdf+xml" in accept:
        import rdflib
        from rdflib import Literal, URIRef
        from rdflib.namespace import DCTERMS
        g = rdflib.Graph()
        subj = URIRef(subject_iri or data.get("iri", "urn:unknown"))
        for k, v in data.items():
            if v is not None:
                g.add((subj, DCTERMS[k], Literal(str(v))))
        fmt = "turtle" if "text/turtle" in accept else "xml"
        ct = "text/turtle" if fmt == "turtle" else "application/rdf+xml"
        return Response(content=g.serialize(format=fmt), media_type=ct)
    return JSONResponse(data)
