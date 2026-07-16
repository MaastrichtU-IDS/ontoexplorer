"""rustdl backend (owl-dl-py PyO3 binding). Classify + native justify."""
from __future__ import annotations

import importlib.util
from registry import ReasonerInfo
from classifier import ClassificationResult


class RustdlBackend:
    info = ReasonerInfo(
        name="rustdl", profile="DL (SROIQ)",
        capabilities=frozenset({"classify", "consistency", "justify"}),
        available=importlib.util.find_spec("rustdl") is not None,
    )

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
        import io, time, os, logging
        from collections import defaultdict
        from datetime import datetime, timezone
        import pyoxigraph
        import rustdl

        OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
        t0 = time.monotonic()

        # NT -> RDF/XML (same conversion whelk_classifier uses).
        store = pyoxigraph.Store()
        store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                        format=pyoxigraph.RdfFormat.N_TRIPLES)
        rdfxml = pyoxigraph.serialize(
            (q.triple for q in store.quads_for_pattern(None, None, None, None)),
            format=pyoxigraph.RdfFormat.RDF_XML,
        )

        cls = rustdl.classify_bytes(
            rdfxml, format="rdf-xml",
            per_pair_timeout_ms=int(os.getenv("RUSTDL_PER_PAIR_TIMEOUT_MS", "200")),
            global_deadline_ms=int(os.getenv("RUSTDL_GLOBAL_DEADLINE_MS", "60000")),
        )

        # Asserted subClassOf pairs (to exclude from the inferred `superclasses`).
        RDFS_SUB = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
        OWL_EQUIV = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#equivalentClass")
        asserted: set[tuple[str, str]] = set()
        direct_sup: dict[str, list[str]] = defaultdict(list)
        for q in store.quads_for_pattern(None, RDFS_SUB, None, None):
            if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
                if q.subject.value != q.object.value:
                    asserted.add((q.subject.value, q.object.value))
                    direct_sup[q.subject.value].append(q.object.value)

        # Asserted owl:equivalentClass pairs are also asserted subsumption in
        # both directions — exclude them from `superclasses` and surface the
        # partner in `direct_superclasses` (mirrors whelk_classifier._project_finalize).
        for q in store.quads_for_pattern(None, OWL_EQUIV, None, None):
            if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
                s, o = q.subject.value, q.object.value
                if s != o:
                    asserted.add((s, o))
                    asserted.add((o, s))
                    if o not in direct_sup[s]:
                        direct_sup[s].append(o)

        classes = [c for c in cls.classes if c not in (OWL_THING, OWL_NOTHING)]
        superclasses: dict[str, list[str]] = {}
        for c in classes:
            inferred = [s for s in cls.superclasses_of(c)
                        if s != c and s not in (OWL_THING,) and (c, s) not in asserted]
            if inferred:
                superclasses[c] = inferred

        subclasses: dict[str, list[str]] = defaultdict(list)
        for c, sups in superclasses.items():
            for s in sups:
                subclasses[s].append(c)

        direct_subs: dict[str, list[str]] = defaultdict(list)
        for c, sups in direct_sup.items():
            for s in sups:
                direct_subs[s].append(c)

        if not cls.complete:
            logging.getLogger("reasoner-service").warning(
                "rustdl_incomplete version_id=%s timed_out_pairs=%s",
                version_id, cls.timed_out_pairs)

        return ClassificationResult(
            version_id=version_id,
            classified_at=datetime.now(timezone.utc).isoformat(),
            class_count=len(classes),
            superclasses=dict(superclasses),
            subclasses=dict(subclasses),
            direct_superclasses={k: sorted(v) for k, v in direct_sup.items()},
            direct_subclasses=dict(direct_subs),
            unsatisfiable=list(cls.unsatisfiable),
            proof_traces={},
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )

    def justify(self, ntriples, sub, sup, max_justifications):
        raise NotImplementedError  # Task 5
