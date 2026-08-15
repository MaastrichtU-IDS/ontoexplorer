"""Konclude backend (prebuilt binary subprocess). Classify + consistency only."""
from __future__ import annotations

import shutil
from registry import ReasonerInfo
from classifier import ClassificationResult

_KONCLUDE_BIN = shutil.which("Konclude")


def _transitive_superclasses(
    parents: dict[str, set[str]], asserted: set[tuple[str, str]]
) -> dict[str, list[str]]:
    """Compute the transitive closure of a child -> direct-parents map and
    return the *inferred-only* superclasses per class (self-loops and
    asserted subsumption/equivalentClass pairs excluded).

    Konclude's `classification -o out.owx` output contains only the direct
    subsumption taxonomy (told + direct-inferred edges), not the full
    transitive closure — unlike whelk (`inferred_axioms()`) and rustdl
    (`superclasses_of()`), which both return the closure natively. This
    walks `parents` per class (DFS with memoization) to reproduce that
    closure, then filters it the same way rustdl_backend.py does:
    ``[s for s in cls.superclasses_of(c) if s != c and (c, s) not in asserted]``.

    A `visiting` cycle guard handles owl:equivalentClass loops (A<->B via
    mutual subClassOf edges) without infinite recursion; those pairs are
    still correctly excluded by the final `asserted` filter regardless of
    traversal order, since equivalentClass pairs are added to `asserted` in
    both directions by the caller.
    """
    memo: dict[str, frozenset[str]] = {}

    def ancestors(c: str, visiting: frozenset[str]) -> frozenset[str]:
        cached = memo.get(c)
        if cached is not None:
            return cached
        if c in visiting:
            return frozenset()  # cycle guard; final filter drops self anyway
        visiting = visiting | {c}
        result: set[str] = set()
        for p in parents.get(c, ()):
            result.add(p)
            result |= ancestors(p, visiting)
        memo[c] = frozenset(result)
        return memo[c]

    nodes: set[str] = set(parents.keys())
    for ps in parents.values():
        nodes |= ps

    superclasses: dict[str, list[str]] = {}
    for c in nodes:
        inferred = sorted(
            p for p in ancestors(c, frozenset())
            if p != c and (c, p) not in asserted
        )
        if inferred:
            superclasses[c] = inferred
    return superclasses


class KoncludeBackend:
    info = ReasonerInfo(
        name="konclude", profile="OWL 2 (all profiles)",
        capabilities=frozenset({"classify", "consistency"}),
        available=_KONCLUDE_BIN is not None,
    )

    def classify_ntriples(
        self, ntriples: str, version_id: str, params: dict | None = None
    ) -> ClassificationResult:
        import io, time, tempfile, subprocess, os, shutil as _sh
        from collections import defaultdict
        from datetime import datetime, timezone
        import pyoxigraph
        import pyhornedowl
        import rdflib

        OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
        RDFS_SUB = rdflib.RDFS.subClassOf
        t0 = time.monotonic()

        # NT -> RDF/XML -> OWL/XML (Konclude reads OWL/XML).
        store = pyoxigraph.Store()
        store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                        format=pyoxigraph.RdfFormat.N_TRIPLES)
        rdfxml = pyoxigraph.serialize(
            (q.triple for q in store.quads_for_pattern(None, None, None, None)),
            format=pyoxigraph.RdfFormat.RDF_XML,
        ).decode("utf-8")
        onto = pyhornedowl.open_ontology_from_string(rdfxml, serialization="rdf")
        owx = onto.save_to_string(serialization="owx")

        tmp = tempfile.mkdtemp()
        in_owx, out_owx = os.path.join(tmp, "in.owx"), os.path.join(tmp, "out.owx")
        try:
            with open(in_owx, "w") as fh:
                fh.write(owx)
            subprocess.run([os.getenv("KONCLUDE_BIN", "Konclude"),
                            "classification", "-w", "AUTO", "-i", in_owx, "-o", out_owx],
                           check=True, capture_output=True, timeout=600)

            # Parse Konclude's inferred output (OWL/XML) back into an rdflib graph.
            inferred = pyhornedowl.open_ontology_from_file(out_owx)
            inferred_rdf = inferred.save_to_string(serialization="rdf")
            g = rdflib.Graph()
            g.parse(io.StringIO(inferred_rdf), format="xml")
        finally:
            _sh.rmtree(tmp, ignore_errors=True)

        asserted: set[tuple[str, str]] = set()
        classes: set[str] = set()

        # Collect asserted subClassOf from the input store.
        RDFS_SUB_NN = pyoxigraph.NamedNode(str(RDFS_SUB))
        OWL_EQUIV = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#equivalentClass")
        direct_sup: dict[str, list[str]] = defaultdict(list)
        for q in store.quads_for_pattern(None, RDFS_SUB_NN, None, None):
            if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
                classes.add(q.subject.value); classes.add(q.object.value)
                if q.subject.value != q.object.value:
                    asserted.add((q.subject.value, q.object.value))
                    direct_sup[q.subject.value].append(q.object.value)

        # Asserted owl:equivalentClass pairs are also asserted subsumption in
        # both directions — exclude them from `superclasses` and surface the
        # partner in `direct_superclasses` (mirrors rustdl_backend.py /
        # whelk_classifier._project_finalize).
        for q in store.quads_for_pattern(None, OWL_EQUIV, None, None):
            if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
                s, o = q.subject.value, q.object.value
                if s != o:
                    asserted.add((s, o))
                    asserted.add((o, s))
                    if o not in direct_sup[s]:
                        direct_sup[s].append(o)

        # Konclude's classification output only carries direct (told +
        # direct-inferred) subClassOf edges, not the full transitive
        # closure — build the direct child->parents map here and derive
        # `superclasses` as its transitive closure below.
        parents: dict[str, set[str]] = defaultdict(set)
        unsatisfiable: list[str] = []
        for s, _, o in g.triples((None, RDFS_SUB, None)):
            if not (isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef)):
                continue
            su, ob = str(s), str(o)
            if ob == OWL_NOTHING and su != OWL_NOTHING:
                if su not in unsatisfiable:
                    unsatisfiable.append(su)
                continue
            if su == ob or su == OWL_NOTHING or ob == OWL_THING:
                continue
            parents[su].add(ob)

        superclasses = _transitive_superclasses(parents, asserted)

        subclasses: dict[str, list[str]] = defaultdict(list)
        for c, sups in superclasses.items():
            for s in sups:
                subclasses[s].append(c)
        direct_subs: dict[str, list[str]] = defaultdict(list)
        for c, sups in direct_sup.items():
            for s in sups:
                direct_subs[s].append(c)

        classes.discard(OWL_THING); classes.discard(OWL_NOTHING)
        return ClassificationResult(
            version_id=version_id,
            classified_at=datetime.now(timezone.utc).isoformat(),
            class_count=len(classes),
            superclasses=dict(superclasses),
            subclasses=dict(subclasses),
            direct_superclasses={k: sorted(v) for k, v in direct_sup.items()},
            direct_subclasses=dict(direct_subs),
            unsatisfiable=unsatisfiable,
            proof_traces={},
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )

    def justify(self, ntriples, sub, sup, max_justifications, version_id=None):
        raise NotImplementedError("Konclude has no justification facility")
