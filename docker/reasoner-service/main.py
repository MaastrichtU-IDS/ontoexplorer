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
    import os
    import time
    # `reasoner` is the CLASSIFYING reasoner — used only to locate the version's
    # input axioms and to key the justification cache. Justification itself is a
    # property of the ontology + entailment, not of the classifier, so we run it
    # through a dedicated justifier (rustdl by default) that works for every
    # version — including konclude/km/rdflib ones, which have no native justify.
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
        sets, fmt = justifier.justify(ntriples, req.sub, sup, req.max_justifications)
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
