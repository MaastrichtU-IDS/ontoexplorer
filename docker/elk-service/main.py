"""ELK OWL-EL Reasoning Service — FastAPI application."""
from __future__ import annotations

import io
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import rdflib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from cache import (
    invalidate_version,
    load_classification,
    load_justification,
    store_classification,
    store_justification,
)
from classifier import classify as _rdflib_classify
from justification import compute_justifications

# Backend switch: "whelk" (default, py-whelk/whelk-rs) or "rdflib" (legacy).
# When CLASSIFIER_BACKEND=rdflib we keep the old CR1–CR6 classifier — useful
# for regression testing and as a fallback while proof-trace-driven
# justifications haven't been migrated yet.
_CLASSIFIER_BACKEND = os.getenv("CLASSIFIER_BACKEND", "whelk").lower()
if _CLASSIFIER_BACKEND == "whelk":
    from whelk_classifier import classify as _whelk_classify
    from whelk_classifier import classify_ntriples as _whelk_classify_nt
    classify = _whelk_classify
else:
    classify = _rdflib_classify
    _whelk_classify_nt = None

log = logging.getLogger("elk-service")
logging.basicConfig(level=logging.INFO)
log.info("classifier_backend_selected backend=%s", _CLASSIFIER_BACKEND)

_JUSTIFICATION_TIME_LIMIT = int(os.getenv("JUSTIFICATION_TIME_LIMIT_SECONDS", "300"))

app = FastAPI(title="ELK Reasoning Service", version="2.0.0")

# Single-threaded executor so classifications are serialized (classifier is not thread-safe)
_classifier_pool = ThreadPoolExecutor(max_workers=1)
# Track in-progress version IDs so GET /classify/{id} returns 409 while running
_in_progress: set[str] = set()


# ── Request / Response models ─────────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    ntriples: str
    version_id: str


class JustificationRequest(BaseModel):
    sub: str
    sup: str | None = None
    type: str | None = None          # "unsatisfiable" when sup is omitted
    max_justifications: int = 1      # 0 = find all


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


@app.post("/classify", status_code=202)
def run_classify(req: ClassifyRequest):
    """Start OWL-EL classification in background; poll GET /classify/{version_id} for result."""
    # If already cached, this is a no-op re-submit — return 202 and the caller will GET it
    existing = load_classification(req.version_id)
    if existing is not None:
        return {"version_id": req.version_id, "status": "done"}

    if req.version_id in _in_progress:
        return {"version_id": req.version_id, "status": "running"}

    # For the whelk backend we skip the rdflib parse here — it would be
    # redundant since whelk_classifier.classify_ntriples uses pyoxigraph
    # (Rust) to convert NT → RDF/XML directly. On ordo this saves ~10s.
    # The rdflib backend still needs the parsed graph upfront.
    if _whelk_classify_nt is not None:
        ntriples_for_worker: str | None = req.ntriples
        graph_for_worker: rdflib.Graph | None = None
    else:
        try:
            graph_for_worker = rdflib.Graph()
            graph_for_worker.parse(io.StringIO(req.ntriples), format="nt")
        except Exception as exc:
            raise HTTPException(422, f"Failed to parse N-Triples: {exc}")
        ntriples_for_worker = None

    _in_progress.add(req.version_id)

    def _run(version_id: str) -> None:
        try:
            if _whelk_classify_nt is not None and ntriples_for_worker is not None:
                result = _whelk_classify_nt(ntriples_for_worker, version_id)
            else:
                result = classify(graph_for_worker, version_id)
            store_classification(result)
        except Exception:
            log.exception("classify_background_error", extra={"version_id": version_id})
        finally:
            _in_progress.discard(version_id)

    _classifier_pool.submit(_run, req.version_id)
    return {"version_id": req.version_id, "status": "running"}


@app.get("/classify/{version_id}")
def get_classification(version_id: str):
    result = _load_or_404(version_id)
    from dataclasses import asdict
    return asdict(result)


@app.get("/classify/{version_id}/superclasses")
def get_superclasses(version_id: str, cls: str, direct: bool = False):
    result = _load_or_404(version_id)
    if cls not in result.superclasses and cls not in result.direct_superclasses:
        raise HTTPException(404, "Class not found in classification index")
    if direct:
        return {"class": cls, "superclasses": result.direct_superclasses.get(cls, []), "direct": True}
    return {"class": cls, "superclasses": result.superclasses.get(cls, []), "direct": False}


@app.get("/classify/{version_id}/subclasses")
def get_subclasses(version_id: str, cls: str, direct: bool = False):
    result = _load_or_404(version_id)
    if cls not in result.subclasses and cls not in result.direct_subclasses:
        raise HTTPException(404, "Class not found in classification index")
    if direct:
        return {"class": cls, "subclasses": result.direct_subclasses.get(cls, []), "direct": True}
    return {"class": cls, "subclasses": result.subclasses.get(cls, []), "direct": False}


@app.get("/classify/{version_id}/consistency")
def get_consistency(version_id: str):
    result = _load_or_404(version_id)
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
    result = _load_or_404(version_id)

    sup = req.sup if req.sup else str(rdflib.OWL.Nothing)

    # Check cache first
    cached = load_justification(version_id, req.sub, sup, req.max_justifications)
    if cached:
        return cached

    # Reconstruct graph from inferred + direct axioms stored in proof traces
    g = _reconstruct_graph_from_traces(result)

    t0 = time.monotonic()
    timed_out = False
    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
            _fut = _ex.submit(compute_justifications, g, result, req.sub, sup, req.max_justifications)
            try:
                justs = _fut.result(timeout=_JUSTIFICATION_TIME_LIMIT)
            except concurrent.futures.TimeoutError:
                timed_out = True
                justs = []
    except Exception:
        timed_out = False
        justs = []

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    justification_id = str(uuid.uuid4())

    response = {
        "justification_id": justification_id,
        "version_id": version_id,
        "sub": req.sub,
        "sup": sup,
        "justifications_requested": req.max_justifications,
        "justifications_found": len(justs),
        "minimal": not timed_out,
        "timed_out": timed_out,
        "justifications": justs,
        "proof_traces": [result.proof_traces.get(f"{req.sub}|{sup}", [])],
        "duration_ms": elapsed_ms,
    }

    store_justification(version_id, req.sub, sup, req.max_justifications, response)
    return response


@app.get("/classify/{version_id}/justification/{justification_id}")
def get_justification(version_id: str, justification_id: str):
    raise HTTPException(501, "Use GET /classify/{version_id}?sub=...&sup=... to retrieve justifications")


@app.delete("/classify/{version_id}")
def invalidate(version_id: str):
    invalidate_version(version_id)
    return {"detail": f"Cache invalidated for version {version_id}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_or_404(version_id: str):
    result = load_classification(version_id)
    if result is None:
        if version_id in _in_progress:
            raise HTTPException(409, "Reasoning in progress — poll again shortly")
        raise HTTPException(409, "Reasoning not yet completed for this version — submit via POST /classify")
    return result


def _reconstruct_graph_from_traces(result) -> rdflib.Graph:
    """Reconstruct input axioms from the recorded proof traces."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for steps in result.proof_traces.values():
        for step in steps:
            for ax in step.get("axioms", []):
                if ax not in seen_set:
                    seen_set.add(ax)
                    seen.append(ax)
    g = rdflib.Graph()
    # Parse all axioms together so blank node IDs stay consistent across triples.
    try:
        g.parse(data="\n".join(seen), format="nt")
    except Exception:
        for ax in seen:
            try:
                g.parse(data=ax, format="nt")
            except Exception:
                pass
    return g
