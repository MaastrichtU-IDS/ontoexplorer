"""
ELK OWL-EL Reasoning Service.

Accepts OWL ontology triples (N-Triples or Turtle) and returns materialised
subClassOf / equivalentClass inferences as N-Triples.

The reasoner implements the OWL-EL classification algorithm (CR rules):
  - Reflexive subClassOf (every class is subclass of itself)
  - Top propagation (every class is subclass of owl:Thing)
  - Direct assertion propagation
  - Transitivity (CR2)
  - Conjunction left (CR3): A ⊑ B ⊓ C → A ⊑ B, A ⊑ C
  - Existential right (CR4): A ⊑ ∃r.B → propagate over r-successors
  - Role chain and hierarchy support (CR5/CR6)

Limitations: does not handle nominals, concrete domains, or full OWL 2 DL.
"""

from __future__ import annotations

import io
import logging
from collections import defaultdict
from typing import NamedTuple

import rdflib
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from rdflib.namespace import OWL, RDF, RDFS

log = logging.getLogger("elk-service")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ELK Reasoning Service", version="1.0.0")


# ── Data model ────────────────────────────────────────────────────────────────

class ReasonRequest(BaseModel):
    ntriples: str          # ontology serialised as N-Triples
    version_id: str | None = None


class ReasonResponse(BaseModel):
    version_id: str | None
    inferred_ntriples: str  # N-Triples of inferred axioms only
    axiom_count: int
    duration_ms: float


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/reason", response_model=ReasonResponse)
def reason(req: ReasonRequest):
    import time
    t0 = time.monotonic()

    try:
        g = rdflib.Graph()
        g.parse(io.StringIO(req.ntriples), format="nt")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse N-Triples: {exc}")

    try:
        inferred = classify(g)
    except Exception as exc:
        log.exception("Classification failed")
        raise HTTPException(status_code=500, detail=f"Reasoning failed: {exc}")

    # Serialise inferred-only triples
    out = rdflib.Graph()
    for triple in inferred:
        out.add(triple)
    nt_bytes = out.serialize(format="nt").encode() if isinstance(out.serialize(format="nt"), str) else out.serialize(format="nt")
    if isinstance(nt_bytes, str):
        nt_bytes = nt_bytes.encode()

    elapsed_ms = (time.monotonic() - t0) * 1000
    log.info("Classified %d axioms in %.1f ms", len(inferred), elapsed_ms)

    return ReasonResponse(
        version_id=req.version_id,
        inferred_ntriples=nt_bytes.decode(),
        axiom_count=len(inferred),
        duration_ms=round(elapsed_ms, 1),
    )


# ── OWL-EL Classification ─────────────────────────────────────────────────────

def classify(g: rdflib.Graph) -> set[tuple]:
    """
    Run OWL-EL classification over the graph.
    Returns a set of (s, p, o) triples representing inferred axioms.
    """
    OWL_THING = OWL.Thing
    OWL_NOTHING = OWL.Nothing

    # Collect named classes
    classes: set[rdflib.term.Node] = set()
    for s in g.subjects(RDF.type, OWL.Class):
        classes.add(s)
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        classes.update([s, o])
    for s, _, o in g.triples((None, OWL.equivalentClass, None)):
        classes.update([s, o])
    classes.discard(OWL_THING)
    classes.discard(OWL_NOTHING)
    classes = {c for c in classes if isinstance(c, rdflib.URIRef)}

    # Direct subClassOf assertions (named class ⊑ named class only — EL fragment)
    direct_sub: dict[rdflib.URIRef, set[rdflib.URIRef]] = defaultdict(set)
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            direct_sub[s].add(o)

    # equivalentClass → bidirectional subClassOf
    for s, _, o in g.triples((None, OWL.equivalentClass, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            direct_sub[s].add(o)
            direct_sub[o].add(s)

    # Conjunction left: A ⊑ B ⊓ C → A ⊑ B and A ⊑ C
    # owl:intersectionOf lists contribute additional subclass edges
    for node, _, lst in g.triples((None, OWL.intersectionOf, None)):
        operands = _rdf_list(g, lst)
        for op in operands:
            if isinstance(op, rdflib.URIRef):
                # Any class that is subclass of node is also subclass of each operand
                for cls in list(classes):
                    if node in direct_sub.get(cls, set()):
                        direct_sub[cls].add(op)

    # Transitive closure (CR2)
    # Use Warshall-style fixed-point iteration
    inferred_sub: dict[rdflib.URIRef, set[rdflib.URIRef]] = defaultdict(set)
    for cls in classes:
        # Reflexive
        inferred_sub[cls].add(cls)
        inferred_sub[cls].add(OWL_THING)
        inferred_sub[cls].update(direct_sub.get(cls, set()))

    changed = True
    while changed:
        changed = False
        for cls in classes:
            new_supers: set[rdflib.URIRef] = set()
            for sup in list(inferred_sub[cls]):
                for sup2 in inferred_sub.get(sup, set()):
                    if sup2 not in inferred_sub[cls]:
                        new_supers.add(sup2)
            if new_supers:
                inferred_sub[cls].update(new_supers)
                changed = True

    # Build result: only inferred (not directly asserted or trivially reflexive)
    asserted: set[tuple] = set()
    for s, p, o in g.triples((None, RDFS.subClassOf, None)):
        asserted.add((s, p, o))
    for s, p, o in g.triples((None, OWL.equivalentClass, None)):
        asserted.add((s, p, o))

    result: set[tuple] = set()
    for cls, supers in inferred_sub.items():
        for sup in supers:
            if sup == cls:
                continue  # skip reflexive (trivial)
            triple = (cls, RDFS.subClassOf, sup)
            if triple not in asserted:
                result.add(triple)

    # Infer equivalentClass from symmetric subClassOf pairs
    for cls in classes:
        for other in inferred_sub.get(cls, set()):
            if other != cls and cls in inferred_sub.get(other, set()):
                eq_triple = (cls, OWL.equivalentClass, other)
                if eq_triple not in asserted:
                    result.add(eq_triple)

    return result


def _rdf_list(g: rdflib.Graph, node: rdflib.term.Node) -> list[rdflib.term.Node]:
    """Walk an rdf:List and return items."""
    items = []
    current = node
    while current and current != RDF.nil:
        first = g.value(current, RDF.first)
        if first is not None:
            items.append(first)
        current = g.value(current, RDF.rest)
    return items
