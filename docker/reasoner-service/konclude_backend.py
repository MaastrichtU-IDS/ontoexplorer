"""Konclude backend (prebuilt binary subprocess). Classify + consistency only."""
from __future__ import annotations

import shutil
from registry import ReasonerInfo
from classifier import ClassificationResult

_KONCLUDE_BIN = shutil.which("Konclude")


class KoncludeBackend:
    info = ReasonerInfo(
        name="konclude", profile="OWL 2 (all profiles)",
        capabilities=frozenset({"classify", "consistency"}),
        available=_KONCLUDE_BIN is not None,
    )

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
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

        superclasses: dict[str, list[str]] = defaultdict(list)
        unsatisfiable: list[str] = []
        for s, _, o in g.triples((None, RDFS_SUB, None)):
            if not (isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef)):
                continue
            su, ob = str(s), str(o)
            if ob == OWL_NOTHING and su != OWL_NOTHING:
                if su not in unsatisfiable:
                    unsatisfiable.append(su)
                continue
            if su == ob or su == OWL_NOTHING or ob == OWL_THING or (su, ob) in asserted:
                continue
            superclasses[su].append(ob)

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

    def justify(self, ntriples, sub, sup, max_justifications):
        raise NotImplementedError("Konclude has no justification facility")
