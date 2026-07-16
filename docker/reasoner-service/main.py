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
    load_classification_error,
    load_input_axioms,
    load_justification,
    store_classification,
    store_classification_error,
    store_input_axioms,
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
            result = None
            if _whelk_classify_nt is not None and ntriples_for_worker is not None:
                try:
                    result = _whelk_classify_nt(ntriples_for_worker, version_id)
                except Exception as exc:
                    # horned-owl is strict about OWL property-type discipline
                    # (a property can be ObjectProperty XOR DataProperty XOR
                    # AnnotationProperty). Some widely-used metadata vocabs
                    # (dcterms, dcat) play loose with this and conflate
                    # dcterms:creator ≡ foaf:maker across type boundaries —
                    # the parser raises ValidityError and we'd otherwise stay
                    # stuck at 409 forever. Fall back to the legacy rdflib
                    # classifier which is forgiving of these patterns.
                    log.warning(
                        "whelk_parse_failed; falling back to rdflib backend "
                        "(vid=%s, error=%s)", version_id, exc,
                    )
                    if graph_for_worker is None:
                        # Whelk path skipped the rdflib parse — do it now for fallback.
                        graph_for_worker_local = rdflib.Graph()
                        graph_for_worker_local.parse(io.StringIO(req.ntriples), format="nt")
                        result = _rdflib_classify(graph_for_worker_local, version_id)
                    else:
                        result = _rdflib_classify(graph_for_worker, version_id)
            else:
                result = classify(graph_for_worker, version_id)
            # IMPORTANT: store input_axioms BEFORE classification. GET /classify/
            # {vid} returns 200 as soon as the classification cache key exists
            # (it doesn't gate on _in_progress when the result is already in
            # Redis). If we wrote classification first, a follow-up
            # /justification call could race ahead of the input_axioms write
            # — which is exactly what bit ordo: 80 MB gzip takes ~5 s, leaving
            # a window where the inference looks "done" but justification
            # gets an empty input graph and returns no justifications.
            store_input_axioms(version_id, req.ntriples)
            store_classification(result)
        except Exception as exc:
            log.exception("classify_background_error", extra={"version_id": version_id})
            # Surface the failure via the cache so /classify GET can return
            # 500 instead of staying at 409 forever (the previous behaviour).
            store_classification_error(
                version_id, f"{type(exc).__name__}: {exc}"[:1000],
            )
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

    # Justification needs the original asserted axioms. Prefer the input-axioms
    # cache populated at classification time (works for any backend). Fall back
    # to proof-trace reconstruction for older cache entries that pre-date the
    # input_axioms key. If both miss, justifications will come back empty.
    g_loaded = _load_input_graph(version_id)
    if g_loaded is not None and len(g_loaded) > 0:
        g = g_loaded
    else:
        # Pre-input-axioms-cache classifications (proof-trace backend or old
        # cached results) — reconstruct from proof_traces.
        g = _reconstruct_graph_from_traces(result)

    t0 = time.monotonic()
    timed_out = False
    # Direct call (no ThreadPoolExecutor): py-whelk + pyhornedowl rely on
    # PyO3 objects whose lifetimes/handles don't transfer cleanly to a
    # worker thread. The previous executor-based timeout was found to
    # return empty results in ~1ms for some ontologies (e.g. ordo) when
    # the executor's worker couldn't initialise the reasoner state.
    # The trade-off: we lose the per-request internal timeout. Uvicorn's
    # request lifetime is still bounded by the client's HTTP timeout, and
    # the per-step is_entailed calls are bounded by ontology size.
    try:
        justs = compute_justifications(g, result, req.sub, sup, req.max_justifications)
    except Exception:
        justs = []
        log.exception("justification_compute_failed", extra={
            "version_id": version_id, "sub": req.sub, "sup": sup,
        })

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
    if result is not None:
        return result
    err = load_classification_error(version_id)
    if err is not None:
        raise HTTPException(500, f"Classification failed: {err}")
    if version_id in _in_progress:
        raise HTTPException(409, "Reasoning in progress — poll again shortly")
    raise HTTPException(409, "Reasoning not yet completed for this version — submit via POST /classify")


def _load_input_graph(version_id: str) -> rdflib.Graph | None:
    """Load the cached input N-Triples for a version and parse into an rdflib graph.

    Returns None when no input-axioms cache entry exists (the version was
    classified before this cache layer existed). Callers should fall back to
    the legacy proof-trace reconstruction in that case.
    """
    ntriples = load_input_axioms(version_id)
    if not ntriples:
        return None
    g = rdflib.Graph()
    try:
        g.parse(io.StringIO(ntriples), format="nt")
    except Exception:
        log.exception("input_axioms_parse_failed", extra={"version_id": version_id})
        return None
    return g


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
