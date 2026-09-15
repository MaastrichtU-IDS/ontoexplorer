"""rustdl backend (owl-dl-py PyO3 binding). Classify + native justify."""
from __future__ import annotations

import importlib.util
from registry import ReasonerInfo
from classifier import ClassificationResult


def _rustdl_version() -> str:
    try:
        import importlib.metadata as _md
        return _md.version("rustdl")
    except Exception:
        return ""


class RustdlBackend:
    info = ReasonerInfo(
        name="rustdl", profile="DL (SROIQ)",
        capabilities=frozenset({"classify", "consistency", "justify"}),
        available=importlib.util.find_spec("rustdl") is not None,
        version=_rustdl_version(),
        param_schema=(
            {"key": "saturation_only", "type": "bool", "default": False,
             "label": "EL saturation only",
             "help": "Skip the SROIQ tableau and classify via EL closure only — "
                     "complete for EL-profile ontologies and far faster. Auto-enabled "
                     "for EL-profile ontologies even when unset."},
            {"key": "per_pair_timeout_ms", "type": "int", "default": 200, "min": 0,
             "label": "Per-pair timeout (ms)",
             "help": "Max time per pairwise subsumption test in tableau mode. 0 = unbounded."},
            {"key": "global_timeout_ms", "type": "int", "default": 60000, "min": 0,
             "label": "Global timeout (ms)",
             "help": "Max total wall time in tableau mode; a run exceeding it returns "
                     "incomplete. 0 = unbounded."},
        ),
    )

    def classify_ntriples(
        self, ntriples: str, version_id: str, params: dict | None = None
    ) -> ClassificationResult:
        import io, time, os, logging
        from collections import defaultdict
        from datetime import datetime, timezone
        import pyoxigraph
        import rustdl

        params = params or {}
        saturation_only = bool(params.get("saturation_only", False))
        per_pair_timeout_ms = int(params.get(
            "per_pair_timeout_ms", os.getenv("RUSTDL_PER_PAIR_TIMEOUT_MS", "200")))
        global_timeout_ms = int(params.get(
            "global_timeout_ms", os.getenv("RUSTDL_GLOBAL_DEADLINE_MS", "60000")))

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

        # saturation_only skips the SROIQ tableau and classifies via EL closure
        # only — complete for EL-profile ontologies and dramatically faster on
        # large ones (the per-pair tableau is O(n²) and OOMs/times out on e.g.
        # GO's tens of thousands of classes). The API sets this for EL-profile
        # ontologies; the per-pair/global bounds are irrelevant in that mode.
        if saturation_only:
            logging.getLogger("reasoner-service").info(
                "rustdl_saturation_only version_id=%s", version_id)
        cls = rustdl.classify_bytes(
            rdfxml, format="rdf-xml",
            per_pair_timeout_ms=per_pair_timeout_ms,
            global_timeout_ms=global_timeout_ms,
            saturation_only=saturation_only,
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

        # Build the inferred transitive `superclasses` closure.
        #
        # We must NOT call cls.superclasses_of(c) per class: that recomputes a
        # traversal each call (~48 ms/call measured on GO), so ~52k classes take
        # ~40 min and several GB — the reason GO appeared to "hang". Instead read
        # the precomputed DIRECT inferred subsumers (cls.direct_subsumers(c) is
        # ~0.003 ms/call) once, then compute the transitive closure ourselves in
        # a single near-linear pass. Verified on GO to reproduce superclasses_of
        # exactly (0 mismatches over a 1.4k-class sample) in ~0.5s total.
        direct_inf: dict[str, list[str]] = {
            c: [s for s in cls.direct_subsumers(c) if s != c and s != OWL_THING]
            for c in classes
        }
        _closure: dict[str, set[str]] = {}
        _state: dict[str, int] = {}  # 0/absent = unvisited, 1 = on-stack, 2 = done

        def _ancestors(start: str) -> set[str]:
            # Iterative DFS post-order so deep GO hierarchies can't blow the
            # Python recursion limit; memoized so each node is expanded once.
            stack = [(start, iter(direct_inf.get(start, ())))]
            _state[start] = 1
            while stack:
                node, it = stack[-1]
                advanced = False
                for parent in it:
                    if _state.get(parent, 0) == 0:
                        _state[parent] = 1
                        stack.append((parent, iter(direct_inf.get(parent, ()))))
                        advanced = True
                        break
                if advanced:
                    continue
                stack.pop()
                acc: set[str] = set()
                for parent in direct_inf.get(node, ()):  # noqa: PLR1704
                    acc.add(parent)
                    acc |= _closure.get(parent, set())
                _closure[node] = acc
                _state[node] = 2
            return _closure[start]

        superclasses: dict[str, list[str]] = {}
        for c in classes:
            if _state.get(c, 0) != 2:
                _ancestors(c)
            inferred = [s for s in _closure[c] if s != c and s != OWL_THING and (c, s) not in asserted]
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

    def justify(self, ntriples: str, sub: str, sup: str,
                max_justifications: int, version_id: str | None = None
                ) -> tuple[list[list[str]], str]:
        import logging
        import os
        import tempfile
        import rustdl

        OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
        query = ["unsat", sub] if sup == OWL_NOTHING else ["subclass", sub, sup]

        def _run(path: str) -> list[list[str]]:
            if max_justifications == 1:
                one = rustdl.justify(path, query)
                return [one] if one else []
            return rustdl.justify_all(path, query, max_justifications)

        # rustdl.justify re-parses + re-classifies on every call (no reuse API).
        # Feeding it the OWL-functional (.ofn) serialization instead of RDF/XML
        # is materially faster (smaller source, faster parser) — measured ~45s ->
        # ~32s of internal time on GO — and we cache the .ofn per version so the
        # ~14s pyhornedowl build is paid once, not per justify. On any failure of
        # the .ofn path we fall back to the original RDF/XML materialisation, so
        # correctness never depends on the round-trip succeeding.
        ofn = self._version_ofn(ntriples, version_id)
        if ofn is not None:
            fd, path = tempfile.mkstemp(suffix=".ofn")
            try:
                with os.fdopen(fd, "w") as fh:
                    fh.write(ofn)
                return _run(path), "manchester"
            except Exception:
                logging.getLogger("reasoner-service").warning(
                    "rustdl_justify_ofn_fallback version_id=%s", version_id,
                    exc_info=True)
            finally:
                os.unlink(path)

        # Fallback: materialise the NT as RDF/XML (.rdf) and justify from that.
        path = self._materialise_rdfxml(ntriples)
        try:
            return _run(path), "manchester"
        finally:
            os.unlink(path)

    @staticmethod
    def _materialise_rdfxml(ntriples: str) -> str:
        """NT -> RDF/XML on disk; returns the temp file path (caller unlinks)."""
        import io, os, tempfile
        import pyoxigraph
        store = pyoxigraph.Store()
        store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                        format=pyoxigraph.RdfFormat.N_TRIPLES)
        rdfxml = pyoxigraph.serialize(
            (q.triple for q in store.quads_for_pattern(None, None, None, None)),
            format=pyoxigraph.RdfFormat.RDF_XML,
        )
        fd, path = tempfile.mkstemp(suffix=".rdf")
        with os.fdopen(fd, "wb") as fh:
            fh.write(rdfxml)
        return path

    @staticmethod
    def _version_ofn(ntriples: str, version_id: str | None) -> str | None:
        """The version's OWL-functional serialization, cached in Redis. Built
        lazily (NT -> RDF/XML -> pyhornedowl -> .ofn) on first use, then reused.
        Returns None if it cannot be built or pyhornedowl is unavailable."""
        import logging
        log = logging.getLogger("reasoner-service")
        try:
            from cache import load_ontology_ofn, store_ontology_ofn
        except Exception:
            return None
        if version_id:
            try:
                cached = load_ontology_ofn(version_id)
                if cached is not None:
                    return cached
            except Exception:
                log.warning("rustdl_ofn_cache_read_failed version_id=%s",
                            version_id, exc_info=True)
        try:
            import io
            import pyoxigraph
            import pyhornedowl
            store = pyoxigraph.Store()
            store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                            format=pyoxigraph.RdfFormat.N_TRIPLES)
            rdfxml = pyoxigraph.serialize(
                (q.triple for q in store.quads_for_pattern(None, None, None, None)),
                format=pyoxigraph.RdfFormat.RDF_XML,
            )
            onto = pyhornedowl.open_ontology_from_string(
                bytes(rdfxml).decode("utf-8", "replace"), "rdf")
            ofn = onto.save_to_string("ofn")
        except Exception:
            log.warning("rustdl_ofn_build_failed version_id=%s", version_id,
                        exc_info=True)
            return None
        if version_id:
            try:
                store_ontology_ofn(version_id, ofn)
            except Exception:
                log.warning("rustdl_ofn_cache_write_failed version_id=%s",
                            version_id, exc_info=True)
        return ofn
