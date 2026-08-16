"""ELK OWL-EL Reasoning Service — FastAPI application."""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

import rdflib
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from cache import (
    invalidate_version,
    load_classification,
    load_classification_error,
    load_input_axioms,
    load_justification,
    store_classification_error,
    class_is_known,
    has_per_class_index,
    load_class_entry,
    store_per_class,
    store_justification,
)
from registry import default_reasoner, get_backend, list_reasoners

log = logging.getLogger("elk-service")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ELK Reasoning Service", version="2.0.0")

# Single-threaded executor so classifications are serialized (classifier is not thread-safe)
_classifier_pool = ThreadPoolExecutor(max_workers=1)
# Track (version_id, reasoner) pairs in progress so GET /classify/{id} returns 409 while running
_in_progress: set[tuple[str, str]] = set()

# km-backed incremental EL++ reasoning sessions (transient, in-memory).
from incremental_km import KmError, OutOfFragment, SessionStore  # noqa: E402
_incremental_sessions = SessionStore()


# ── Request / Response models ─────────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    ntriples: str
    version_id: str
    reasoner: str | None = None
    # Reasoner-specific parameters (from the selected reasoner profile), e.g.
    # rustdl {saturation_only, per_pair_timeout_ms, global_timeout_ms} or km
    # {route}. Each backend reads the keys it knows; others ignore them.
    params: dict = {}
    # Deprecated alias, folded into params.saturation_only when params omits it —
    # kept so an older API still triggers EL saturation during a rolling deploy.
    saturation_only: bool = False
    # Force recomputation: invalidate any cached classification for this version
    # first (params changed → the (version, reasoner) cache key alone is stale).
    force: bool = False


class JustificationRequest(BaseModel):
    sub: str
    sup: str | None = None
    type: str | None = None          # "unsatisfiable" when sup is omitted
    max_justifications: int = 1      # 0 = find all
    reasoner: str | None = None
    cache_only: bool = False         # return cached result or a miss marker; never compute


class ConsistencyRequest(BaseModel):
    ntriples: str
    ofn: str = ""
    reasoner: str = "rustdl"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        from cache import _redis
        _redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"status": "ok", "redis": "ok" if redis_ok else "error"}


@app.get("/reasoners")
def get_reasoners():
    from dataclasses import asdict
    return [
        {**asdict(info), "capabilities": sorted(info.capabilities)}
        for info in list_reasoners()
    ]


def _ofn_to_ntriples(ofn: str) -> str:
    """OWL functional-syntax axioms -> N-Triples (via py-horned-owl + pyoxigraph),
    wrapping in Ontology(...) exactly like the incremental assert path."""
    import io
    import pyhornedowl
    import pyoxigraph
    wrapped = "Ontology(\n" + ofn.strip() + "\n)"
    onto = pyhornedowl.open_ontology_from_string(wrapped, serialization="ofn")
    rdfxml = onto.save_to_string(serialization="rdf")
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(rdfxml.encode("utf-8")), format=pyoxigraph.RdfFormat.RDF_XML)
    return pyoxigraph.serialize(
        (q.triple for q in store.quads_for_pattern(None, None, None, None)),
        format=pyoxigraph.RdfFormat.N_TRIPLES,
    ).decode("utf-8")


@app.post("/consistency")
def consistency(req: ConsistencyRequest):
    reasoner = req.reasoner or default_reasoner()
    try:
        backend = get_backend(reasoner)
    except KeyError:
        raise HTTPException(422, f"unknown reasoner '{reasoner}'")
    combined = req.ntriples
    if req.ofn.strip():
        combined = (req.ntriples or "") + "\n" + _ofn_to_ntriples(req.ofn)
    result = backend.classify_ntriples(combined, version_id="_adhoc_consistency_", params={})
    unsat = list(result.unsatisfiable)
    inconsistent = "http://www.w3.org/2002/07/owl#Thing" in unsat
    return {"inconsistent": inconsistent, "unsatisfiable_classes": unsat, "reasoner": reasoner}


@app.post("/classify", status_code=202)
def run_classify(req: ClassifyRequest):
    """Start OWL-EL classification in background; poll GET /classify/{version_id} for result."""
    reasoner = req.reasoner or default_reasoner()
    try:
        get_backend(reasoner)  # validate; the isolated worker resolves it again
    except KeyError:
        raise HTTPException(422, f"unknown reasoner '{reasoner}'")

    # Effective params: profile params, with the deprecated saturation_only flag
    # folded in when the caller didn't put it in params.
    params = dict(req.params or {})
    if req.saturation_only and "saturation_only" not in params:
        params["saturation_only"] = True

    # A forced (re)reason drops any cached classification/error for the version so
    # new params actually take effect (the cache key is (version, reasoner) only).
    if req.force:
        from cache import invalidate_version
        invalidate_version(req.version_id)

    # If already cached, this is a no-op re-submit — return 202 and the caller will GET it
    if load_classification(req.version_id, reasoner) is not None:
        return {"version_id": req.version_id, "reasoner": reasoner, "status": "done"}

    if (req.version_id, reasoner) in _in_progress:
        return {"version_id": req.version_id, "reasoner": reasoner, "status": "running"}

    _in_progress.add((req.version_id, reasoner))

    def _run(version_id: str) -> None:
        # Classify in an ISOLATED child process (classify_worker.py). A backend
        # that segfaults, aborts, or exhausts memory (e.g. rustdl on certain
        # large ontologies) then only kills that short-lived child — it can't
        # take down this service or trigger a crash-restart loop. The child
        # writes the result (input_axioms then classification, same ordering as
        # before) straight to Redis; here we only watch its exit / timeout and
        # record a clean error on failure so GET /classify returns 500 instead
        # of hanging at 409 forever.
        import json
        import os
        import subprocess
        import sys
        import tempfile

        timeout_s = int(os.getenv("REASONER_CLASSIFY_TIMEOUT_S", "3300"))
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".nt", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(req.ntriples)
                tmp_path = tmp.name

            worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "classify_worker.py")
            try:
                proc = subprocess.run(
                    [sys.executable, worker, tmp_path, version_id, reasoner,
                     json.dumps(params)],
                    timeout=timeout_s, capture_output=True, text=True,
                )
            except subprocess.TimeoutExpired:
                log.error("classify_timeout version_id=%s reasoner=%s after=%ss",
                          version_id, reasoner, timeout_s)
                store_classification_error(
                    version_id,
                    f"classification timed out after {timeout_s}s", reasoner,
                )
                return

            if proc.returncode != 0:
                tail = (proc.stderr or "").strip()[-600:]
                log.error("classify_worker_failed version_id=%s reasoner=%s rc=%s stderr=%s",
                          version_id, reasoner, proc.returncode, tail)
                store_classification_error(
                    version_id,
                    f"classifier process exited {proc.returncode} "
                    f"(crash/OOM/abort): {tail}"[:1000],
                    reasoner,
                )
            # returncode 0 → the child already stored input_axioms + classification.
        except Exception as exc:
            log.exception("classify_background_error", extra={"version_id": version_id})
            store_classification_error(
                version_id, f"{type(exc).__name__}: {exc}"[:1000], reasoner,
            )
        finally:
            _in_progress.discard((version_id, reasoner))
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    _classifier_pool.submit(_run, req.version_id)
    return {"version_id": req.version_id, "reasoner": reasoner, "status": "running"}


@app.get("/classify/{version_id}")
def get_classification(version_id: str, reasoner: str = Query(default_reasoner())):
    result = _load_or_404(version_id, reasoner)
    from dataclasses import asdict
    return asdict(result)


def _relations_or_404(version_id: str, reasoner: str, cls: str, kind: str) -> tuple[list, list]:
    """(transitive, direct) lists for one class — (all, direct) in that order.

    Reads the per-class hashes, which cost one HGET each. Falls back to the
    whole blob only for classifications cached before those were written; that
    read is 8.5 s and ~539 MB on a DRON-sized ontology, so it must never be the
    normal path.
    """
    all_map = "superclasses" if kind == "superclasses" else "subclasses"
    direct_map = f"direct_{all_map}"

    if has_per_class_index(version_id, reasoner):
        if not class_is_known(version_id, reasoner, cls):
            raise HTTPException(404, "Class not found in classification index")
        return (
            load_class_entry(version_id, reasoner, all_map, cls) or [],
            load_class_entry(version_id, reasoner, direct_map, cls) or [],
        )

    result = _load_or_404(version_id, reasoner)
    # Backfill on the way out: this request already paid to parse the blob, so
    # write the per-class entries and let every later one be an HGET. Without
    # it a classification predating this would reload 539 MB forever.
    try:
        store_per_class(result, reasoner)
    except Exception:
        pass
    all_d = getattr(result, all_map)
    direct_d = getattr(result, direct_map)
    if cls not in all_d and cls not in direct_d:
        raise HTTPException(404, "Class not found in classification index")
    return all_d.get(cls, []), direct_d.get(cls, [])


@app.get("/classify/{version_id}/superclasses")
def get_superclasses(version_id: str, cls: str, direct: bool = False,
                      reasoner: str = Query(default_reasoner())):
    all_sup, direct_sup = _relations_or_404(version_id, reasoner, cls, "superclasses")
    if direct:
        return {"class": cls, "superclasses": direct_sup, "direct": True}
    return {"class": cls, "superclasses": all_sup, "direct": False}


@app.get("/classify/{version_id}/subclasses")
def get_subclasses(version_id: str, cls: str, direct: bool = False,
                    reasoner: str = Query(default_reasoner())):
    all_sub, direct_sub = _relations_or_404(version_id, reasoner, cls, "subclasses")
    if direct:
        return {"class": cls, "subclasses": direct_sub, "direct": True}
    return {"class": cls, "subclasses": all_sub, "direct": False}


@app.get("/classify/{version_id}/consistency")
def get_consistency(version_id: str, reasoner: str = Query(default_reasoner())):
    result = _load_or_404(version_id, reasoner)
    return {
        "version_id": version_id,
        "consistent": len(result.unsatisfiable) == 0,
        "unsatisfiable_classes": result.unsatisfiable,
        "unsatisfiable_count": len(result.unsatisfiable),
    }


@app.post("/classify/{version_id}/justification")
def compute_justification_endpoint(version_id: str, req: JustificationRequest):
    """
    Synchronously compute justification(s) and cache result.
    Long-running; called by the compute_justification Celery task.
    """
    import os
    import time
    # `reasoner` is the CLASSIFYING reasoner — used only to locate the version's
    # input axioms and to key the justification cache. Justification itself is a
    # property of the ontology + entailment, not of the classifier, so we run it
    # through a dedicated justifier (rustdl by default) that works for every
    # version — including konclude/km ones, which have no native justify.
    reasoner = req.reasoner or default_reasoner()
    try:
        get_backend(reasoner)
    except KeyError:
        raise HTTPException(422, f"unknown reasoner '{reasoner}'")

    justifier_name = os.getenv("JUSTIFY_REASONER", "rustdl")
    try:
        justifier = get_backend(justifier_name)
    except KeyError:
        raise HTTPException(422, f"justifier '{justifier_name}' is not registered")
    if not justifier.info.available or "justify" not in justifier.info.capabilities:
        raise HTTPException(422, f"justifier '{justifier_name}' is unavailable")

    sup = req.sup if req.sup else str(rdflib.OWL.Nothing)

    # Check cache first (cheap Redis read — do this before the classification
    # existence check so a cache-only peek stays fast and side-effect free).
    cached = load_justification(version_id, req.sub, sup, req.max_justifications, reasoner)
    if cached:
        return cached

    # cache_only: the caller just wants to know whether a result is ready. Never
    # run the (long) computation — return a miss marker so the app can dispatch a
    # background job instead of blocking the request.
    if req.cache_only:
        return {"cached": False, "computing": False, "justifications": []}

    _load_or_404(version_id, reasoner)  # ensure classification exists

    ntriples = load_input_axioms(version_id, reasoner) or ""

    t0 = time.monotonic()
    # Direct call (no ThreadPoolExecutor): py-whelk + pyhornedowl rely on
    # PyO3 objects whose lifetimes/handles don't transfer cleanly to a
    # worker thread. The previous executor-based timeout was found to
    # return empty results in ~1ms for some ontologies (e.g. ordo) when
    # the executor's worker couldn't initialise the reasoner state.
    # The trade-off: we lose the per-request internal timeout. Uvicorn's
    # request lifetime is still bounded by the client's HTTP timeout, and
    # the per-step is_entailed calls are bounded by ontology size.
    try:
        sets, fmt = justifier.justify(ntriples, req.sub, sup, req.max_justifications,
                                      version_id=version_id)
    except Exception:
        sets, fmt = [], "ntriples"
        log.exception("justification_compute_failed", extra={
            "version_id": version_id, "sub": req.sub, "sup": sup,
            "justifier": justifier_name,
        })

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    response = {
        "justification_id": str(uuid.uuid4()),
        "version_id": version_id,
        "reasoner": reasoner,        # the classifying reasoner
        "justifier": justifier_name,  # the reasoner that produced the justification
        "sub": req.sub,
        "sup": sup,
        "format": fmt,
        "justifications_requested": req.max_justifications,
        "justifications_found": len(sets),
        "minimal": True,
        "timed_out": False,
        "justifications": sets,
        "proof_traces": [],
        "duration_ms": elapsed_ms,
    }

    store_justification(version_id, req.sub, sup, req.max_justifications, reasoner, response)
    return response


@app.get("/classify/{version_id}/justification/{justification_id}")
def get_justification(version_id: str, justification_id: str):
    raise HTTPException(501, "Use GET /classify/{version_id}?sub=...&sup=... to retrieve justifications")


@app.delete("/classify/{version_id}")
def invalidate(version_id: str):
    invalidate_version(version_id)
    return {"detail": f"Cache invalidated for version {version_id}"}


# ── Incremental EL++ reasoning (km) ───────────────────────────────────────────
# A stateful session over one ontology: add/remove/change axioms and query
# subsumption without re-classifying. EL++ only (km rejects non-EL fragments).
# Sessions are transient (in-memory; dropped on restart).

class IncrementalCreateRequest(BaseModel):
    version_id: str | None = None
    reasoner: str | None = None   # which classification's input axioms to load
    ntriples: str | None = None   # or supply the ontology directly


class ChangeRequest(BaseModel):
    add_clauses: list = []
    remove_clause_ids: list = []


class SubsumedRequest(BaseModel):
    sub: str
    sup: str


class AssertAxiomsRequest(BaseModel):
    ofn: str          # one or more OWL functional-syntax axioms (full IRIs)


@app.post("/incremental", status_code=201)
def incremental_create(req: IncrementalCreateRequest):
    if req.ntriples:
        ntriples = req.ntriples
    elif req.version_id:
        ntriples = load_input_axioms(req.version_id, req.reasoner or default_reasoner())
        if not ntriples:
            raise HTTPException(404, "no cached input axioms for that version/reasoner — classify it first")
    else:
        raise HTTPException(422, "provide ntriples or version_id")
    try:
        sid, session = _incremental_sessions.create(ntriples)
    except OutOfFragment as exc:
        raise HTTPException(422, f"ontology is outside km's EL++ fragment: {exc}")
    except KmError as exc:
        raise HTTPException(500, f"km session error: {exc}")
    stats = session.stats()
    return {
        "session_id": sid,
        "revision": session.revision,
        "inconsistent": session.inconsistent,
        "clause_ids": stats.get("clause_ids", []),
        "total_clauses": stats.get("total_clauses"),
    }


def _get_session(session_id: str):
    session = _incremental_sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found (unknown, closed, or evicted)")
    return session


@app.post("/incremental/{session_id}/subsumed")
def incremental_subsumed(session_id: str, req: SubsumedRequest):
    session = _get_session(session_id)
    try:
        entailed = session.is_subsumed_by(req.sub, req.sup)
    except KmError as exc:
        raise HTTPException(500, f"km session error: {exc}")
    return {"sub": req.sub, "sup": req.sup, "entailed": entailed, "revision": session.revision}


@app.post("/incremental/{session_id}/assert")
def incremental_assert(session_id: str, req: SubsumedRequest):
    """Add a hypothetical `sub ⊑ sup` axiom (between two existing named classes)."""
    session = _get_session(session_id)
    try:
        result = session.assert_subclass(req.sub, req.sup)
    except KmError as exc:
        raise HTTPException(422, str(exc))
    if result.get("status") != "ok":
        raise HTTPException(422, f"assert rejected: {result}")
    # Surface the clause id(s) km assigned so the caller can retract this exact
    # axiom later via /change {remove_clause_ids}. km nests them under `update`.
    return {"revision": session.revision, "inconsistent": session.inconsistent,
            "clause_ids": result.get("update", {}).get("added_clause_ids", [])}


@app.post("/incremental/{session_id}/assert_axioms")
def incremental_assert_axioms(session_id: str, req: AssertAxiomsRequest):
    """Add arbitrary EL++ axioms (OWL functional syntax, full IRIs) to the session."""
    session = _get_session(session_id)
    try:
        result = session.assert_axioms(req.ofn)
    except OutOfFragment as exc:
        raise HTTPException(422, f"not EL++ (out of fragment): {exc}")
    except KmError as exc:
        raise HTTPException(422, str(exc))
    if result.get("status") != "ok":
        raise HTTPException(422, f"assert rejected: {result}")
    return {"revision": session.revision, "inconsistent": session.inconsistent,
            "clause_ids": result.get("update", {}).get("added_clause_ids", [])}


@app.post("/incremental/{session_id}/change")
def incremental_change(session_id: str, req: ChangeRequest):
    session = _get_session(session_id)
    try:
        result = session.change(add_clauses=req.add_clauses, remove_clause_ids=req.remove_clause_ids)
    except KmError as exc:
        raise HTTPException(500, f"km session error: {exc}")
    if result.get("status") != "ok":
        raise HTTPException(422, f"change rejected: {result}")
    return {"revision": session.revision, "inconsistent": session.inconsistent, "update": result.get("update")}


@app.get("/incremental/{session_id}/stats")
def incremental_stats(session_id: str):
    return _get_session(session_id).stats()


@app.delete("/incremental/{session_id}")
def incremental_close(session_id: str):
    return {"closed": _incremental_sessions.close(session_id)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_or_404(version_id: str, reasoner: str):
    result = load_classification(version_id, reasoner)
    if result is not None:
        return result
    err = load_classification_error(version_id, reasoner)
    if err is not None:
        raise HTTPException(500, f"Classification failed: {err}")
    if (version_id, reasoner) in _in_progress:
        raise HTTPException(409, "Reasoning in progress — poll again shortly")
    raise HTTPException(409, "Reasoning not yet completed for this version — submit via POST /classify")
