"""kobayashi-marust (km) backend — prebuilt Rust binary subprocess.

km is a sound consequence-based reasoner for SROIQ / OWL 2 DL. We feed it
OWL/XML (same conversion Konclude uses) and run `km classify`, which emits JSON:

    {"consistent": bool,
     "subsumptions": [[sub_iri, sup_iri], ...],   # full transitive closure
     "unsatisfiable": [iri, ...],
     "dropped": int}                              # axioms dropped as out-of-fragment

Unlike Konclude, `subsumptions` is already the transitive closure of named
subsumptions (like whelk/rustdl), so no closure reconstruction is needed.
Classify + consistency only; km has soundness certificates, not user-facing
justifications.
"""
from __future__ import annotations

import shutil
from registry import ReasonerInfo
from classifier import ClassificationResult

_KM_BIN = shutil.which("km")


class KmBackend:
    info = ReasonerInfo(
        name="km", profile="SROIQ / OWL 2 DL",
        capabilities=frozenset({"classify", "consistency"}),
        available=_KM_BIN is not None,
    )

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
        import io, json, time, tempfile, subprocess, os, logging, shutil as _sh
        from collections import defaultdict
        from datetime import datetime, timezone
        import pyoxigraph
        import pyhornedowl

        OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
        t0 = time.monotonic()

        # NT -> RDF/XML -> OWL/XML (km reads OWL/XML with --format owlxml). Using
        # the structural owx frontend matches Konclude's proven path and sidesteps
        # km's stricter "RDF-to-OWL conversion must be complete or decline" rule.
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
        in_owx = os.path.join(tmp, "in.owx")
        try:
            with open(in_owx, "w") as fh:
                fh.write(owx)
            proc = subprocess.run(
                [os.getenv("KM_BIN", "km"), "classify", "--format", "owlxml", in_owx],
                capture_output=True, text=True, timeout=600,
            )
        finally:
            _sh.rmtree(tmp, ignore_errors=True)

        # Exit 3 is km's honest "out of supported fragment" decline; anything
        # else non-zero is a real failure. Surface both clearly.
        if proc.returncode == 3:
            raise ValueError(f"km declined (out of fragment): {proc.stderr.strip()}")
        if proc.returncode != 0:
            raise RuntimeError(
                f"km classify failed (exit {proc.returncode}): {proc.stderr.strip()}")

        result = json.loads(proc.stdout)

        # Asserted subClassOf / equivalentClass from the input (to exclude from
        # the inferred `superclasses` and to fill `direct_superclasses` — mirrors
        # konclude_backend / rustdl_backend).
        RDFS_SUB = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
        OWL_EQUIV = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#equivalentClass")
        RDF_TYPE = pyoxigraph.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
        OWL_CLASS = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#Class")
        asserted: set[tuple[str, str]] = set()
        direct_sup: dict[str, list[str]] = defaultdict(list)
        classes: set[str] = set()
        for q in store.quads_for_pattern(None, RDFS_SUB, None, None):
            if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
                classes.add(q.subject.value); classes.add(q.object.value)
                if q.subject.value != q.object.value:
                    asserted.add((q.subject.value, q.object.value))
                    direct_sup[q.subject.value].append(q.object.value)
        for q in store.quads_for_pattern(None, OWL_EQUIV, None, None):
            if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
                s, o = q.subject.value, q.object.value
                classes.add(s); classes.add(o)
                if s != o:
                    asserted.add((s, o)); asserted.add((o, s))
                    if o not in direct_sup[s]:
                        direct_sup[s].append(o)
        for q in store.quads_for_pattern(None, RDF_TYPE, OWL_CLASS, None):
            if isinstance(q.subject, pyoxigraph.NamedNode):
                classes.add(q.subject.value)

        # km's `subsumptions` is the full closure of named pairs. Keep the
        # inferred-only edges: drop self, owl:Thing/Nothing endpoints, and
        # asserted pairs. owl:Nothing supers go to `unsatisfiable`.
        superclasses: dict[str, list[str]] = defaultdict(list)
        unsatisfiable: list[str] = list(result.get("unsatisfiable", []))
        for pair in result.get("subsumptions", []):
            sub, sup = pair[0], pair[1]
            classes.add(sub); classes.add(sup)
            if sup == OWL_NOTHING and sub != OWL_NOTHING:
                if sub not in unsatisfiable:
                    unsatisfiable.append(sub)
                continue
            if sub == sup or sub == OWL_NOTHING or sup == OWL_THING:
                continue
            if (sub, sup) in asserted:
                continue
            superclasses[sub].append(sup)

        superclasses = {k: sorted(set(v)) for k, v in superclasses.items() if v}

        subclasses: dict[str, list[str]] = defaultdict(list)
        for c, sups in superclasses.items():
            for s in sups:
                subclasses[s].append(c)
        direct_subs: dict[str, list[str]] = defaultdict(list)
        for c, sups in direct_sup.items():
            for s in sups:
                direct_subs[s].append(c)

        dropped = int(result.get("dropped", 0) or 0)
        if dropped:
            logging.getLogger("reasoner-service").warning(
                "km_dropped_axioms version_id=%s dropped=%d (result may be incomplete)",
                version_id, dropped)

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
        raise NotImplementedError("km has no justification facility (soundness certificates only)")
