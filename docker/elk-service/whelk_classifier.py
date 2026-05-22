"""py-whelk-backed OWL-EL classifier.

Drop-in replacement for `classifier.classify` that produces the same
`ClassificationResult` shape, but routes the heavy reasoning to whelk-rs
(via py-whelk's PyO3 binding to py-horned-owl).

Coverage advantage over the legacy rdflib-based classifier: whelk-rs
implements the canonical Whelk EL calculus; on ORDO it produces ~17K
inferences the legacy backend misses (existential-restriction propagation
through subProperty chains).

Limitation (deliberate, documented): we do NOT emit per-inference proof
traces. The legacy classifier records CR1–CR6 rule applications and the
hitting-set justification algorithm in `main.py` reconstructs the input
graph from them. With whelk we emit `proof_traces={}` and the
`/justification` endpoint will return empty justifications for any
inference derived only by whelk. This is a known follow-up — migrate
justifications to reconstruct from the cached input bytes rather than
from proof traces.
"""
from __future__ import annotations

import io
import time
from collections import defaultdict
from datetime import datetime, timezone

import rdflib

# Reuse the dataclass + a couple of helpers from the legacy classifier so the
# Redis cache contract stays identical regardless of backend.
from classifier import (
    ClassificationResult,
    _collect_asserted_subclass,
    _collect_classes,
    _collect_equiv,
)

OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


def classify_ntriples(ntriples: str, version_id: str) -> ClassificationResult:
    """Classify N-Triples via whelk-rs and project into `ClassificationResult`.

    Fast path used when caller can hand us NT directly (skip rdflib).
    pyoxigraph (Rust) parses the NT once into a Store; that Store is used
    twice: dumped as RDF/XML for py-horned-owl AND queried via SPARQL for
    the asserted-edge bookkeeping. Avoids the redundant rdflib re-parse
    that was costing ~10s on ordo.
    """
    import pyhornedowl
    import pyoxigraph
    import pywhelk

    t0 = time.monotonic()

    nt_bytes = ntriples.encode("utf-8")
    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(nt_bytes), format=pyoxigraph.RdfFormat.N_TRIPLES)
    # Dump RDF/XML by streaming triples out of the Store — RDF/XML doesn't
    # support quads so we can't use Store.dump directly here.
    rdfxml_bytes = pyoxigraph.serialize(
        (q.triple for q in store.quads_for_pattern(None, None, None, None)),
        format=pyoxigraph.RdfFormat.RDF_XML,
    )
    onto = pyhornedowl.open_ontology_from_string(
        rdfxml_bytes.decode("utf-8"), serialization="rdf"
    )
    reasoner = pywhelk.create_reasoner(onto)
    inferred_axioms = reasoner.inferred_axioms()
    return _project_via_oxigraph(store, inferred_axioms, reasoner, version_id, t0)


def classify(graph: rdflib.Graph, version_id: str) -> ClassificationResult:
    """Backward-compatible entry point taking an rdflib graph.

    Slower than `classify_ntriples` because rdflib has to re-serialize the
    graph back to N-Triples before pyoxigraph can re-parse it. Kept so that
    callers wired to the legacy `classifier.classify(graph, ...)` signature
    still work without changes.
    """
    import pyhornedowl
    import pyoxigraph
    import pywhelk

    t0 = time.monotonic()

    nt_str = graph.serialize(format="nt")
    nt_bytes = nt_str.encode("utf-8") if isinstance(nt_str, str) else nt_str
    triples_iter = pyoxigraph.parse(io.BytesIO(nt_bytes), format=pyoxigraph.RdfFormat.N_TRIPLES)
    rdfxml_bytes = pyoxigraph.serialize(triples_iter, format=pyoxigraph.RdfFormat.RDF_XML)
    onto = pyhornedowl.open_ontology_from_string(
        rdfxml_bytes.decode("utf-8"), serialization="rdf"
    )
    reasoner = pywhelk.create_reasoner(onto)
    inferred_axioms = reasoner.inferred_axioms()
    return _project(graph, inferred_axioms, reasoner, version_id, t0)


def _project_via_oxigraph(store, inferred_axioms, reasoner, version_id, t0) -> ClassificationResult:
    """Same as `_project` but reads asserted-edge bookkeeping from a
    pyoxigraph Store (Rust) instead of an rdflib graph. Used by the fast
    NT-bytes entry point to avoid a second rdflib parse."""
    import pyoxigraph  # local import; available wherever this code path runs

    # Collect classes: subjects with rdf:type owl:Class, plus any IRI on
    # either side of rdfs:subClassOf. Mirrors classifier._collect_classes
    # exactly so the cache contract stays bit-identical.
    classes: set[str] = set()
    asserted_sub: dict[str, set[str]] = defaultdict(set)
    equiv_pairs: dict[str, set[str]] = defaultdict(set)
    OWL_CLASS = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#Class")
    RDF_TYPE = pyoxigraph.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    RDFS_SUB = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
    OWL_EQUIV = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#equivalentClass")
    for q in store.quads_for_pattern(None, RDF_TYPE, OWL_CLASS, None):
        if isinstance(q.subject, pyoxigraph.NamedNode):
            classes.add(q.subject.value)
    for q in store.quads_for_pattern(None, RDFS_SUB, None, None):
        if isinstance(q.subject, pyoxigraph.NamedNode):
            classes.add(q.subject.value)
            if isinstance(q.object, pyoxigraph.NamedNode):
                classes.add(q.object.value)
                if q.subject.value != q.object.value:
                    asserted_sub[q.subject.value].add(q.object.value)
    classes.discard(OWL_THING)
    classes.discard(OWL_NOTHING)
    for q in store.quads_for_pattern(None, OWL_EQUIV, None, None):
        if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
            if q.subject.value in classes and q.object.value in classes:
                equiv_pairs[q.subject.value].add(q.object.value)

    return _project_finalize(
        classes, asserted_sub, equiv_pairs,
        inferred_axioms, reasoner, version_id, t0,
    )


def _project(graph, inferred_axioms, reasoner, version_id, t0) -> ClassificationResult:
    """Shared projection from whelk's inferred-axioms set into ClassificationResult.

    rdflib-based path; kept for `classify(rdflib.Graph)` callers."""
    classes: set[str] = _collect_classes(graph)
    asserted_sub = _collect_asserted_subclass(graph, classes)
    equiv_pairs = _collect_equiv(graph, classes)
    return _project_finalize(
        classes, asserted_sub, equiv_pairs,
        inferred_axioms, reasoner, version_id, t0,
    )


def _project_finalize(classes, asserted_sub, equiv_pairs, inferred_axioms, reasoner, version_id, t0) -> ClassificationResult:

    # Build asserted-pair set once so we can exclude them from `superclasses`
    # (which the legacy contract says contains "all inferred (not asserted)").
    asserted_pairs: set[tuple[str, str]] = set()
    for cls, sups in asserted_sub.items():
        for sup in sups:
            asserted_pairs.add((cls, sup))
    for cls, eqs in equiv_pairs.items():
        for eq in eqs:
            asserted_pairs.add((cls, eq))
            asserted_pairs.add((eq, cls))

    # Whelk's `inferred_axioms()` is the full materialised transitive closure
    # of SubClassOf (including reflexive cls⊑cls and owl:Nothing⊑X). Strip
    # the trivial ones — the legacy backend never reported them either.
    superclasses: dict[str, list[str]] = defaultdict(list)
    for ax in inferred_axioms:
        if type(ax).__name__ != "SubClassOf":
            continue
        try:
            sub = str(ax.sub.first)
            sup = str(ax.sup.first)
        except AttributeError:
            # Sub or sup is a class expression, not a named class — skip.
            continue
        if sub == sup or sub == OWL_NOTHING or sup == OWL_THING:
            continue
        if (sub, sup) in asserted_pairs:
            continue
        superclasses[sub].append(sup)

    # Invert for subclasses lookup.
    subclasses: dict[str, list[str]] = defaultdict(list)
    for cls, sups in superclasses.items():
        for sup in sups:
            subclasses[sup].append(cls)

    # direct_superclasses is the asserted set per the legacy contract.
    direct_sup: dict[str, list[str]] = defaultdict(list)
    for cls, sups in asserted_sub.items():
        direct_sup[cls].extend(sorted(sups))
    for cls, eqs in equiv_pairs.items():
        for eq in eqs:
            if eq not in direct_sup[cls]:
                direct_sup[cls].append(eq)

    direct_subs: dict[str, list[str]] = defaultdict(list)
    for cls, sups in direct_sup.items():
        for sup in sups:
            direct_subs[sup].append(cls)

    # Unsatisfiable classes from whelk.
    unsatisfiable: list[str] = []
    try:
        unsat_classes = reasoner.get_unsatisfiable_classes()
        for c in unsat_classes:
            iri_obj = getattr(c, "first", c)
            unsatisfiable.append(str(iri_obj))
    except Exception:
        # If get_unsatisfiable_classes throws (e.g. method removed in a future
        # py-whelk release), fall back to scanning inferred SubClassOf for
        # `X ⊑ owl:Nothing` triples.
        for ax in inferred_axioms:
            if type(ax).__name__ != "SubClassOf":
                continue
            try:
                sub = str(ax.sub.first)
                sup = str(ax.sup.first)
            except AttributeError:
                continue
            if sup == OWL_NOTHING and sub != OWL_NOTHING and sub not in unsatisfiable:
                unsatisfiable.append(sub)

    return ClassificationResult(
        version_id=version_id,
        classified_at=datetime.now(timezone.utc).isoformat(),
        class_count=len(classes),
        superclasses=dict(superclasses),
        subclasses=dict(subclasses),
        direct_superclasses=dict(direct_sup),
        direct_subclasses=dict(direct_subs),
        unsatisfiable=unsatisfiable,
        # See module docstring — proof traces are intentionally empty for the
        # whelk backend. /justification will return empty results for inferences
        # derived only by whelk until justifications are migrated off traces.
        proof_traces={},
        duration_ms=round((time.monotonic() - t0) * 1000, 1),
    )
