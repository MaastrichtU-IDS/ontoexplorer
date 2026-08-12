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
    store_classification,
    store_classification_error,
    store_input_axioms,
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


# ── Request / Response models ─────────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    ntriples: str
    version_id: str
    reasoner: str | None = None
    # EL-closure fast path: when True, a DL backend (rustdl) skips the SROIQ
    # tableau and classifies via EL saturation only — complete for EL-profile
    # ontologies and orders of magnitude faster on large ones (e.g. GO). The
    # API sets this when the ontology is in the OWL 2 EL profile. Ignored by
    # backends that don't support it.
    saturation_only: bool = False


class JustificationRequest(BaseModel):
    sub: str
    sup: str | None = None
    type: str | None = None          # "unsatisfiable" when sup is omitted
    max_justifications: int = 1      # 0 = find all
    reasoner: str | None = None


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


@app.post("/classify", status_code=202)
def run_classify(req: ClassifyRequest):
    """Start OWL-EL classification in background; poll GET /classify/{version_id} for result."""
    reasoner = req.reasoner or default_reasoner()
    try:
        backend = get_backend(reasoner)
    except KeyError:
        raise HTTPException(422, f"unknown reasoner '{reasoner}'")

    # If already cached, this is a no-op re-submit — return 202 and the caller will GET it
    if load_classification(req.version_id, reasoner) is not None:
        return {"version_id": req.version_id, "reasoner": reasoner, "status": "done"}

    if (req.version_id, reasoner) in _in_progress:
        return {"version_id": req.version_id, "reasoner": reasoner, "status": "running"}

    _in_progress.add((req.version_id, reasoner))

    def _run(version_id: str) -> None:
        try:
            result = backend.classify_ntriples(
                req.ntriples, version_id, saturation_only=req.saturation_only
            )
            # IMPORTANT: store input_axioms BEFORE classification. GET /classify/
            # {vid} returns 200 as soon as the classification cache key exists
            # (it doesn't gate on _in_progress when the result is already in
            # Redis). If we wrote classification first, a follow-up
            # /justification call could race ahead of the input_axioms write
            # — which is exactly what bit ordo: 80 MB gzip takes ~5 s, leaving
            # a window where the inference looks "done" but justification
            # gets an empty input graph and returns no justifications.
            store_input_axioms(version_id, req.ntriples, reasoner)
            store_classification(result, reasoner)
        except Exception as exc:
            log.exception("classify_background_error", extra={"version_id": version_id})
            # Surface the failure via the cache so /classify GET can return
            # 500 instead of staying at 409 forever (the previous behaviour).
            store_classification_error(
                version_id, f"{type(exc).__name__}: {exc}"[:1000], reasoner,
            )
        finally:
            _in_progress.discard((version_id, reasoner))

    _classifier_pool.submit(_run, req.version_id)
    return {"version_id": req.version_id, "reasoner": reasoner, "status": "running"}


@app.get("/classify/{version_id}")
def get_classification(version_id: str, reasoner: str = Query(default_reasoner())):
    result = _load_or_404(version_id, reasoner)
    from dataclasses import asdict
    return asdict(result)


@app.get("/classify/{version_id}/superclasses")
def get_superclasses(version_id: str, cls: str, direct: bool = False,
                      reasoner: str = Query(default_reasoner())):
    result = _load_or_404(version_id, reasoner)
    if cls not in result.superclasses and cls not in result.direct_superclasses:
        raise HTTPException(404, "Class not found in classification index")
    if direct:
        return {"class": cls, "superclasses": result.direct_superclasses.get(cls, []), "direct": True}
    return {"class": cls, "superclasses": result.superclasses.get(cls, []), "direct": False}


@app.get("/classify/{version_id}/subclasses")
def get_subclasses(version_id: str, cls: str, direct: bool = False,
                    reasoner: str = Query(default_reasoner())):
    result = _load_or_404(version_id, reasoner)
    if cls not in result.subclasses and cls not in result.direct_subclasses:
        raise HTTPException(404, "Class not found in classification index")
    if direct:
        return {"class": cls, "subclasses": result.direct_subclasses.get(cls, []), "direct": True}
    return {"class": cls, "subclasses": result.subclasses.get(cls, []), "direct": False}


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
    import time
    reasoner = req.reasoner or default_reasoner()
    try:
        backend = get_backend(reasoner)
    except KeyError:
        raise HTTPException(422, f"unknown reasoner '{reasoner}'")
    if "justify" not in backend.info.capabilities:
        raise HTTPException(422, f"reasoner '{reasoner}' does not support justifications")

    _load_or_404(version_id, reasoner)  # ensure classification exists

    sup = req.sup if req.sup else str(rdflib.OWL.Nothing)

    # Check cache first
    cached = load_justification(version_id, req.sub, sup, req.max_justifications, reasoner)
    if cached:
        return cached

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
        sets, fmt = backend.justify(ntriples, req.sub, sup, req.max_justifications)
    except Exception:
        sets, fmt = [], "ntriples"
        log.exception("justification_compute_failed", extra={
            "version_id": version_id, "sub": req.sub, "sup": sup,
        })

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    response = {
        "justification_id": str(uuid.uuid4()),
        "version_id": version_id,
        "reasoner": reasoner,
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
