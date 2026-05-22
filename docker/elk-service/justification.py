"""
Justification computation for OWL-EL inferences.

Algorithm:
1. Find all input axioms (N-Triple strings) that are used anywhere in
   the proof trace for the target inference.
2. Greedily shrink the set (remove axioms that are not load-bearing)
   by re-running classification on the reduced graph.
3. For multiple justifications, use the hitting-set approach:
   after finding one justification J, add a blocking constraint
   (exclude at least one axiom from J) and search again.

The per-step entailment check (`_entails`) routes through the same backend
the rest of the service uses: when CLASSIFIER_BACKEND=whelk (the default),
it goes via whelk_classifier.classify_ntriples (Rust EL reasoner, ~100x
faster than the legacy CR1–6 classifier on small inputs). This both
matches semantics with the main /classify path and dramatically reduces
the hitting-set wall time — the algorithm does O(N) entailment checks
during greedy shrink.
"""
from __future__ import annotations

import io
import itertools
import os
from typing import Sequence

import rdflib

from classifier import ClassificationResult, classify as _rdflib_classify

_CLASSIFIER_BACKEND = os.getenv("CLASSIFIER_BACKEND", "whelk").lower()


def compute_justifications(
    graph: rdflib.Graph,
    result: ClassificationResult,
    sub: str,
    sup: str,
    max_justifications: int = 1,
) -> list[list[str]]:
    """
    Return a list of minimal justifications for the inference sub ⊑ sup.

    Each justification is a list of N-Triple strings (original axioms).
    max_justifications=0 means find all (may be expensive).
    Returns [] if the inference is not present in result.
    """
    # Verify inference is present
    if sup == str(rdflib.OWL.Nothing):
        if sub not in result.unsatisfiable:
            return []
    else:
        if sup not in result.superclasses.get(sub, []) and sup not in result.direct_superclasses.get(sub, []):
            return []

    # Whelk persistent-reasoner fast path: build ontology + reasoner once,
    # mutate via remove_axiom + flush across the entire greedy walk. The
    # upstream bug that originally blocked this (py-whelk's index_remove was
    # a no-op stub, so flush() never invalidated after remove) has been
    # fixed in our patched py-whelk wheel; see test_pywhelk_flush_after_remove.
    # Falls back to the per-call rebuild path if anything in the chain isn't
    # available.
    if _CLASSIFIER_BACKEND == "whelk" and sup != str(rdflib.OWL.Nothing):
        try:
            return _compute_justifications_persistent(
                graph, sub, sup, max_justifications,
            )
        except _PersistentUnavailable:
            pass  # fall through to the per-call path

    all_axioms = _extract_all_axioms(graph)
    if not all_axioms:
        return []

    justifications: list[list[str]] = []
    excluded: list[frozenset[str]] = []  # hitting sets to block

    limit = max_justifications if max_justifications > 0 else 999

    while len(justifications) < limit:
        candidate = _find_one_justification(all_axioms, sub, sup, excluded)
        if candidate is None:
            break
        justifications.append(candidate)
        excluded.append(frozenset(candidate))

    return justifications


def _find_one_justification(
    all_axioms: list[str],
    sub: str,
    sup: str,
    excluded: list[frozenset[str]],
) -> list[str] | None:
    """Find one minimal justification not blocked by any set in excluded."""
    # Start with all axioms and greedily remove non-load-bearing ones
    candidate = list(all_axioms)

    # Apply exclusion: must contain at least one axiom NOT in each excluded set.
    # Remove one axiom from each excluded justification to force a different path.
    for ex_set in excluded:
        for ax in list(ex_set):
            if ax in candidate:
                candidate = [a for a in candidate if a != ax]
                break

    if not _entails(candidate, sub, sup):
        return None

    # Greedy minimisation: try removing each axiom.
    #
    # Single-pass greedy can leave non-load-bearing axioms in the result
    # when intermediate `minimal` states confuse the entailment check (we
    # observed whelk returning False for "remove X" at certain candidate
    # sizes even though X is post-hoc removable). Fixed-point loop catches
    # those — re-walk the surviving set until a full pass makes no change.
    minimal = list(candidate)
    while True:
        before_size = len(minimal)
        for ax in list(minimal):
            reduced = [a for a in minimal if a != ax]
            if _entails(reduced, sub, sup):
                minimal = reduced
        if len(minimal) == before_size:
            break

    return minimal if minimal else None


def _entails(axioms: list[str], sub: str, sup: str) -> bool:
    """Return True if the given axiom set entails sub ⊑ sup.

    Dispatches to the same classifier backend the service is using for the
    main /classify path. The whelk path is the default and is dramatically
    faster on small inputs (no JVM startup, no rdflib reparse) — important
    because greedy-shrink calls _entails O(N) times.
    """
    if _CLASSIFIER_BACKEND == "whelk":
        return _entails_via_whelk(axioms, sub, sup)
    return _entails_via_rdflib(axioms, sub, sup)


def _entails_via_whelk(axioms: list[str], sub: str, sup: str) -> bool:
    """Whelk-backed entailment check. Cheapest path: join axioms back into
    an N-Triples string and reuse `whelk_classifier.classify_ntriples`,
    which is the same code path /classify takes."""
    nt = "\n".join(axioms)
    if not nt.strip():
        return False
    try:
        from whelk_classifier import classify_ntriples
        r = classify_ntriples(nt, "_check")
    except Exception:
        return False
    if sup == str(rdflib.OWL.Nothing):
        return sub in r.unsatisfiable
    return (sup in r.superclasses.get(sub, []) or
            sup in r.direct_superclasses.get(sub, []))


def _entails_via_rdflib(axioms: list[str], sub: str, sup: str) -> bool:
    """Legacy rdflib-based entailment check (CR1–6 classifier)."""
    g = rdflib.Graph()
    try:
        g.parse(data="\n".join(axioms), format="nt")
    except Exception:
        for ax in axioms:
            try:
                g.parse(data=ax, format="nt")
            except Exception:
                pass
    if len(g) == 0:
        return False
    try:
        r = _rdflib_classify(g, "_check")
    except Exception:
        return False
    if sup == str(rdflib.OWL.Nothing):
        return sub in r.unsatisfiable
    return (sup in r.superclasses.get(sub, []) or
            sup in r.direct_superclasses.get(sub, []))


def _extract_all_axioms(graph: rdflib.Graph) -> list[str]:
    """Serialise graph as N-Triples, one line per axiom, preserving blank node IDs."""
    nt_text = graph.serialize(format="nt")
    return [line.strip() for line in nt_text.splitlines() if line.strip()]


# ── Persistent-reasoner fast path ─────────────────────────────────────────────
#
# Builds the whelk reasoner ONCE for the full input ontology, then mutates
# in-place via onto.remove_axiom + reasoner.flush(). Skips the per-call
# pyoxigraph + RDF/XML + horned-owl-load tax on every greedy step.
#
# Requires the patched py-whelk wheel (the upstream 0.4.0 release has a
# broken index_remove that silently drops removes; flush() then re-asserts
# the same ontology it already had, leaving is_entailed in a stale state).
# Our patched wheel adds a pending_remove queue symmetric to pending_insert
# and applies it in flush. See test_pywhelk_flush_after_remove.

class _PersistentUnavailable(RuntimeError):
    """Raised when this path can't be used (missing dep, parse failure, etc).
    Caller falls back to the per-call rebuild path."""


def _compute_justifications_persistent(
    graph: rdflib.Graph,
    sub: str,
    sup: str,
    max_justifications: int,
) -> list[list[str]]:
    try:
        import io
        import pyhornedowl
        import pyoxigraph
        import pywhelk
        from pyhornedowl import model
    except ImportError as exc:
        raise _PersistentUnavailable(f"required modules missing: {exc}") from exc

    nt_text = graph.serialize(format="nt")
    nt_bytes = nt_text.encode("utf-8") if isinstance(nt_text, str) else nt_text
    if not nt_bytes.strip():
        return []

    try:
        triples_iter = pyoxigraph.parse(io.BytesIO(nt_bytes), format=pyoxigraph.RdfFormat.N_TRIPLES)
        rdfxml_bytes = pyoxigraph.serialize(triples_iter, format=pyoxigraph.RdfFormat.RDF_XML)
        onto = pyhornedowl.open_ontology_from_string(rdfxml_bytes.decode("utf-8"), serialization="rdf")
        reasoner = pywhelk.create_reasoner(onto)
    except Exception as exc:
        raise _PersistentUnavailable(f"ontology load failed: {exc}") from exc

    try:
        sco_query = model.SubClassOf(onto.class_(sub), onto.class_(sup))
    except Exception as exc:
        raise _PersistentUnavailable(f"could not construct query axiom: {exc}") from exc

    if not reasoner.is_entailed(sco_query):
        return []

    # Restrict candidates to axiom types that can carry EL inference paths.
    # Class declarations and annotation assertions are skipped — they can't
    # be load-bearing for SubClassOf(sub, sup).
    _CONSIDERED = {
        "SubClassOf", "EquivalentClasses", "DisjointClasses",
        "SubObjectPropertyOf", "EquivalentObjectProperties",
        "ObjectPropertyDomain", "ObjectPropertyRange",
        "TransitiveObjectProperty",
    }
    all_candidates: list = []
    for ax in onto.get_axioms():
        if type(ax.component).__name__ in _CONSIDERED:
            all_candidates.append(ax.component)

    # IRI-connectivity pre-filter. Restrict to axioms whose named-entity
    # footprint connects to {sub, sup} via transitive closure: an axiom is
    # potentially load-bearing only if it shares at least one IRI with the
    # accumulating "relevant" set, which in turn pulls in that axiom's other
    # IRIs. Fixed-point until no growth. This is essentially a one-shot
    # ⊥-module extraction restricted to EL — sound under EL semantics
    # (axioms with disjoint IRI signature from sub/sup can never contribute
    # to derivations reaching sub ⊑ sup).
    #
    # On ordo we observed this cuts the candidate set from ~28K to <100,
    # turning a 10+ min greedy walk into seconds.
    candidates = _filter_iri_connected(all_candidates, sub, sup)

    justifications: list[list[str]] = []
    excluded_ids: list[set[int]] = []
    limit = max_justifications if max_justifications > 0 else 999

    while len(justifications) < limit:
        survivors = _persistent_find_one(
            onto, reasoner, candidates, sco_query, excluded_ids,
        )
        if survivors is None:
            break
        nt_lines = _axioms_to_nt(survivors, graph)
        if not nt_lines:
            break
        justifications.append(nt_lines)
        excluded_ids.append({id(ax) for ax in survivors})

    return justifications


def _persistent_find_one(onto, reasoner, candidates, sco_query, excluded_ids):
    """One iteration of justification discovery using the persistent reasoner.

    Each excluded set blocks supersets of a previously-found justification.
    We enforce blocking by removing one excluded axiom from `onto` for the
    duration of this attempt; restored at the end.
    """
    blocked_axioms = []
    for ex_ids in excluded_ids:
        for ax in candidates:
            if id(ax) in ex_ids:
                onto.remove_axiom(ax)
                blocked_axioms.append(ax)
                break  # only block ONE axiom per excluded set
    reasoner.flush()
    try:
        if not reasoner.is_entailed(sco_query):
            return None

        # Fixed-point greedy shrink. Start from the (un-blocked) candidate set.
        survivors = [ax for ax in candidates if ax not in blocked_axioms]
        while True:
            before = len(survivors)
            idx = 0
            while idx < len(survivors):
                ax = survivors[idx]
                try:
                    onto.remove_axiom(ax)
                except Exception:
                    idx += 1
                    continue
                reasoner.flush()
                if reasoner.is_entailed(sco_query):
                    survivors.pop(idx)  # truly removable, leave out
                else:
                    onto.add_axiom(ax)
                    reasoner.flush()
                    idx += 1
            if len(survivors) == before:
                break
        return survivors
    finally:
        # Restore all axioms we touched so the next outer iteration starts
        # from a clean ontology state.
        for ax in blocked_axioms:
            try:
                onto.add_axiom(ax)
            except Exception:
                pass
        # Anything not in `survivors` (i.e. confirmed-removable) was removed
        # during the walk; restore those too for the next iteration.
        if "survivors" in locals():
            for ax in candidates:
                if ax not in survivors and ax not in blocked_axioms:
                    try:
                        onto.add_axiom(ax)
                    except Exception:
                        pass
        reasoner.flush()


def _axioms_to_nt(axioms: list, source_graph: rdflib.Graph) -> list[str]:
    """Convert horned-owl axiom components back to N-Triple strings via
    the source rdflib graph. Heuristic: find triples whose subjects are
    named IRIs mentioned in any surviving axiom AND whose predicate is a
    schema predicate the EL reasoner pays attention to."""
    from rdflib.namespace import OWL, RDFS, RDF
    schema_predicates = {
        RDFS.subClassOf, OWL.equivalentClass, OWL.disjointWith,
        RDFS.subPropertyOf, OWL.equivalentProperty,
        RDFS.domain, RDFS.range,
        OWL.intersectionOf, OWL.unionOf,
        OWL.onProperty, OWL.someValuesFrom, OWL.allValuesFrom,
        RDF.first, RDF.rest,
    }
    iris_of_interest: set[str] = set()
    for ax in axioms:
        iris_of_interest |= _extract_iris_from_axiom(ax)
    out: list[str] = []
    seen: set[tuple] = set()
    for s, p, o in source_graph:
        if isinstance(s, rdflib.URIRef) and str(s) in iris_of_interest and p in schema_predicates:
            triple = (s, p, o)
            if triple in seen:
                continue
            seen.add(triple)
            g = rdflib.Graph()
            g.add(triple)
            out.append(g.serialize(format="nt").strip())
    return out


def _extract_iris_from_axiom(axiom) -> set[str]:
    """Walk an axiom's component structure pulling named-class IRIs."""
    found: set[str] = set()
    seen_ids: set[int] = set()
    stack = [axiom]
    while stack:
        node = stack.pop()
        if id(node) in seen_ids:
            continue
        seen_ids.add(id(node))
        # `Class.first` is an IRI when the class is named.
        if hasattr(node, "first"):
            iri_str = str(node.first)
            if iri_str.startswith("http"):
                found.add(iri_str)
        for attr in ("sub", "sup", "operands", "members", "property",
                     "filler", "object", "subject", "first", "rest"):
            if hasattr(node, attr):
                child = getattr(node, attr)
                if child is not None and id(child) not in seen_ids:
                    stack.append(child)
    return found


_HUB_CUTOFF_DEFAULT = int(os.getenv("JUSTIFICATION_HUB_CUTOFF", "500"))


def _filter_iri_connected(candidates: list, sub: str, sup: str,
                          hub_cutoff: int | None = None) -> list:
    """Return the subset of `candidates` IRI-connected to {sub, sup}.

    Iteratively grows a `relevant` IRI set: every axiom whose footprint
    intersects the current set contributes its other IRIs, until no growth.
    Axioms with footprints disjoint from the closure are dropped — they
    cannot participate in any EL derivation that reaches sub ⊑ sup.

    `hub_cutoff` (default: env JUSTIFICATION_HUB_CUTOFF, fallback 500) is
    a hub-skip heuristic: any IRI mentioned in more than `hub_cutoff`
    candidates is treated as a "hub" and excluded from the propagation set.
    Axioms mentioning a hub still get included (the hub is allowed in
    relevant via its co-mentioned axiom), but the walk doesn't fan out
    through it. This caps the closure size for ontologies like Orphanet
    where a few top-level classification classes are children of thousands.
    On ordo this drops the candidate set from 17K to ~280; on smaller
    ontologies (pizza, ro) it has no effect because no IRI exceeds the
    cutoff. Set `hub_cutoff=0` to disable.

    Mirrors the principle behind ⊥-module extraction (Cuenca-Grau et al.)
    restricted to the EL fragment.
    """
    if hub_cutoff is None:
        hub_cutoff = _HUB_CUTOFF_DEFAULT
    iris_per_ax: list[set[str]] = [_extract_iris_from_axiom(ax) for ax in candidates]
    # Build hub set (IRIs that appear in >= hub_cutoff candidates).
    hubs: set[str] = set()
    if hub_cutoff > 0:
        from collections import Counter
        freq = Counter()
        for ax_iris in iris_per_ax:
            freq.update(ax_iris)
        hubs = {iri for iri, n in freq.items() if n >= hub_cutoff}
    # sub/sup must never be treated as hubs even if they happen to be
    # frequent — otherwise we'd drop the chain immediately.
    hubs.discard(sub)
    hubs.discard(sup)
    relevant: set[str] = {sub, sup}
    while True:
        before = len(relevant)
        for ax_iris in iris_per_ax:
            if ax_iris & relevant:
                # Propagate non-hub IRIs; hubs are bridged but the walk
                # doesn't fan out via them.
                relevant |= (ax_iris - hubs)
        if len(relevant) == before:
            break
    return [ax for ax, ax_iris in zip(candidates, iris_per_ax) if ax_iris & relevant]
