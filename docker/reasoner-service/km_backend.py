"""kobayashi-marust (km) backend — prebuilt Rust binary subprocess.

km is a sound consequence-based reasoner for SROIQ / OWL 2 DL. We build
OWL/XML (same conversion Konclude uses), prepare it for km (km_owx_fix), convert
it to functional syntax and run `km classify`, which emits JSON:

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

import os
import shutil
from registry import ReasonerInfo
from classifier import ClassificationResult

_KM_BIN = shutil.which("km")


class KmBackend:
    info = ReasonerInfo(
        name="km", profile="SROIQ / OWL 2 DL",
        capabilities=frozenset({"classify", "consistency"}),
        available=_KM_BIN is not None,
        version=os.getenv("KM_VERSION", ""),
        param_schema=(
            {"key": "route", "type": "enum", "default": "auto",
             "choices": ["auto", "manual", "default", "default8", "default1",
                         "production_all", "production_all8", "production_all1",
                         "cb_plain16", "cb_plain8", "cb_plain1",
                         "cb_absorb16", "cb_absorb8", "cb_absorb1",
                         "cb_trigger16", "cb_trigger8", "cb_trigger1",
                         "cb_absorb_portfolio16", "elc", "elc_cert"],
             "label": "Route",
             "help": "km reasoning strategy (km classify --route). 'auto' picks a "
                     "route from the ontology profile; the cb_*/elc/production_all "
                     "variants select specific consequence-based engines and "
                     "refuse ontologies they could only approximate (e.g. with "
                     "nominals or rules): use 'auto' for those."},
        ),
    )

    def classify_ntriples(
        self, ntriples: str, version_id: str, params: dict | None = None
    ) -> ClassificationResult:
        import io, json, time, tempfile, subprocess, os, logging, shutil as _sh
        from collections import defaultdict
        from datetime import datetime, timezone
        import pyoxigraph
        import pyhornedowl

        route = (params or {}).get("route", "auto")
        OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
        t0 = time.monotonic()

        # NT -> RDF/XML -> OWL/XML -> functional syntax. Converting with
        # horned-owl rather than handing km RDF matches Konclude's proven path and
        # sidesteps km's stricter "RDF-to-OWL conversion must be complete or
        # decline" rule.
        store = pyoxigraph.Store()
        store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                        format=pyoxigraph.RdfFormat.N_TRIPLES)
        rdfxml = pyoxigraph.serialize(
            (q.triple for q in store.quads_for_pattern(None, None, None, None)),
            format=pyoxigraph.RdfFormat.RDF_XML,
        ).decode("utf-8")
        onto = pyhornedowl.open_ontology_from_string(rdfxml, serialization="rdf")
        owx = onto.save_to_string(serialization="owx")
        # horned-owl's RDF reader drops owl:AllDisjointClasses; reinstate it in the
        # OWL/XML fed to km so disjointness-dependent inferences survive.
        import disjoint_fix
        owx = disjoint_fix.owl_xml_with_disjointness(owx, store)
        # Feed km only the logical content: drop the ontology/version IRI (km
        # mangles IRIs that start with it) and all annotations (km >= v1.4.4
        # rejects reserved annotation properties and non-OWL-2 literal types),
        # drop declarations of built-in IRIs such as xsd:date (km >= v1.4.4
        # rejects them), and declare used-but-undeclared entities (km >= v1.4.4
        # requires it), and expand prefixed names so km reports full IRIs (km
        # #8). All are lossless for classification. See km_owx_fix.
        import km_owx_fix
        owx, _injected = km_owx_fix.prepare_owx_for_km(owx)
        # Hand km functional syntax, not OWL/XML. With --route auto, km <= v1.6.5
        # sends OWL/XML containing DL-safe rules to its slow ht_rules route, while
        # the same content in functional syntax takes the ground-rule path: IAO
        # took 1,238 s as OWL/XML and ~1 s as functional syntax (km #7, fixed in
        # km v1.7.0). With no prefixes left, horned-owl writes every IRI in full.
        ofn = pyhornedowl.open_ontology_from_string(
            owx, serialization="owx").save_to_string(serialization="ofn")
        repairs: dict = {}
        if _injected:
            repairs["injected_km_declarations"] = len(_injected)

        tmp = tempfile.mkdtemp()
        in_ofn = os.path.join(tmp, "in.ofn")
        try:
            with open(in_ofn, "w") as fh:
                fh.write(ofn)
            proc = subprocess.run(
                [os.getenv("KM_BIN", "km"), "classify", "--route", route,
                 "--format", "functional", in_ofn],
                capture_output=True, text=True, timeout=600,
            )
        finally:
            _sh.rmtree(tmp, ignore_errors=True)

        # Exit 3 is km's honest decline: the input is outside the supported
        # fragment, or (km >= v1.6) a forced route would drop constructs and only
        # approximate the answer. Anything else non-zero is a real failure.
        if proc.returncode == 3:
            raise ValueError(f"km declined: {proc.stderr.strip()}")
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
            repairs=repairs,
        )

    def justify(self, ntriples, sub, sup, max_justifications, version_id=None):
        raise NotImplementedError("km has no justification facility (soundness certificates only)")
