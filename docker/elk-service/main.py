"""ELK OWL-EL Reasoning Service — FastAPI application."""
from __future__ import annotations

import io
import logging
import os
import uuid
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
from classifier import classify
from justification import compute_justifications

log = logging.getLogger("elk-service")
logging.basicConfig(level=logging.INFO)

_JUSTIFICATION_TIME_LIMIT = int(os.getenv("JUSTIFICATION_TIME_LIMIT_SECONDS", "300"))

app = FastAPI(title="ELK Reasoning Service", version="2.0.0")


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


@app.post("/classify")
def run_classify(req: ClassifyRequest):
    """Run OWL-EL classification and persist result in Redis."""
    try:
        g = rdflib.Graph()
        g.parse(io.StringIO(req.ntriples), format="nt")
    except Exception as exc:
        raise HTTPException(422, f"Failed to parse N-Triples: {exc}")

    result = classify(g, req.version_id)
    store_classification(result)

    return {
        "version_id": result.version_id,
        "class_count": result.class_count,
        "unsatisfiable_count": len(result.unsatisfiable),
        "duration_ms": result.duration_ms,
        "cached": True,
    }


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
    try:
        import signal

        def _handler(signum, frame):
            raise TimeoutError("justification time limit exceeded")

        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(_JUSTIFICATION_TIME_LIMIT)
        try:
            justs = compute_justifications(g, result, req.sub, sup, req.max_justifications)
        finally:
            signal.alarm(0)
    except TimeoutError:
        timed_out = True
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
        raise HTTPException(409, "Reasoning not yet completed for this version — submit via POST /classify")
    return result


def _reconstruct_graph_from_traces(result) -> rdflib.Graph:
    """Reconstruct input axioms from the recorded proof traces."""
    g = rdflib.Graph()
    seen: set[str] = set()
    for steps in result.proof_traces.values():
        for step in steps:
            for ax in step.get("axioms", []):
                if ax not in seen and not ax.startswith("_:"):
                    seen.add(ax)
                    try:
                        g.parse(data=ax, format="nt")
                    except Exception:
                        pass
    return g
