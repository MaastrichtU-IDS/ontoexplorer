"""OWL-EL classifier implementing CR1–CR6 with proof trace recording."""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

OWL_THING    = str(OWL.Thing)
OWL_NOTHING  = str(OWL.Nothing)


def _nt(node) -> str:
    """Format an rdflib node as N-Triples syntax (blank nodes as _:xxx, IRIs as <xxx>)."""
    if isinstance(node, rdflib.BNode):
        return f"_:{node}"
    return f"<{node}>"


def _nt_str(s: str) -> str:
    """Format a string (already-converted node) as N-Triples syntax."""
    if "://" in s or s.startswith("urn:"):
        return f"<{s}>"
    return f"_:{s}"


def _serialize_list_axioms(graph: rdflib.Graph, node, lst) -> list[str]:
    """Return N-Triple strings for `node owl:intersectionOf list` including the full RDF list."""
    from rdflib.namespace import RDF as _RDF
    sub_g = rdflib.Graph()
    sub_g.add((node, OWL.intersectionOf, lst))
    current = lst
    for _ in range(200):
        if not isinstance(current, rdflib.BNode):
            break
        first = graph.value(current, _RDF.first)
        rest = graph.value(current, _RDF.rest)
        if first is not None:
            sub_g.add((current, _RDF.first, first))
        if rest is not None:
            sub_g.add((current, _RDF.rest, rest))
        if rest is None or str(rest) == str(_RDF.nil):
            break
        current = rest
    return [line.strip() for line in sub_g.serialize(format="nt").splitlines() if line.strip()]


@dataclass
class ClassificationResult:
    version_id: str
    classified_at: str
    class_count: int
    superclasses: dict[str, list[str]]         # all inferred (not asserted)
    subclasses: dict[str, list[str]]            # inverse of superclasses
    direct_superclasses: dict[str, list[str]]   # asserted only
    direct_subclasses: dict[str, list[str]]     # asserted only (inverted)
    unsatisfiable: list[str]
    proof_traces: dict[str, list[dict]]         # "sub|sup" -> steps
    duration_ms: float


_TRACE_CLASS_LIMIT = 5_000  # disable proof traces for ontologies larger than this


def classify(graph: rdflib.Graph, version_id: str) -> ClassificationResult:
    """Run OWL-EL classification and return a ClassificationResult."""
    from datetime import datetime, timezone
    t0 = time.monotonic()

    classes: set[str] = _collect_classes(graph)
    asserted_sub = _collect_asserted_subclass(graph, classes)  # cls -> set of direct supers
    equiv_pairs  = _collect_equiv(graph, classes)
    exists_sups  = _collect_existential_supers(graph)   # (role, filler) -> set of named sups
    role_hier    = _collect_role_hierarchy(graph)        # role -> set of super-roles
    disjoints    = _collect_disjointness(graph, classes) # cls -> set of disjoint classes

    record_traces = len(classes) <= _TRACE_CLASS_LIMIT

    # Forward index: cls -> set of all inferred supers (starts with asserted + reflexive + Thing)
    inferred: dict[str, set[str]] = defaultdict(set)
    for cls in classes:
        inferred[cls].add(OWL_THING)
        inferred[cls].update(asserted_sub.get(cls, set()))
        for equiv in equiv_pairs.get(cls, set()):
            inferred[cls].add(equiv)
            inferred[equiv].add(cls)

    # Handle A equivalentClass/subClassOf _:n where _:n is an anonymous intersection or
    # restriction — add the blank node string to inferred[A] so CR3 can fire.
    # subClassOf with BNode objects appears in reconstructed proof-trace graphs.
    for pred in (OWL.equivalentClass, RDFS.subClassOf):
        for s, _, o in graph.triples((None, pred, None)):
            if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.BNode):
                cls_str = str(s)
                if cls_str in classes:
                    inferred[cls_str].add(str(o))

    # Proof trace: "sub|sup" -> list of steps (disabled for large ontologies)
    traces: dict[str, list[dict]] = {}

    def _record(sub: str, sup: str, rule: str, premises: list[str], axioms: list[str]) -> None:
        if not record_traces:
            return
        key = f"{sub}|{sup}"
        if key not in traces:
            traces[key] = []
        traces[key].append({"rule": rule, "premises": premises,
                             "conclusion": f"{_short(sub)} ⊑ {_short(sup)}", "axioms": axioms})

    # ── CR3: conjunction left — A ⊑ B ⊓ C → A ⊑ B, A ⊑ C ────────────────────
    for node, _, lst in graph.triples((None, OWL.intersectionOf, None)):
        operands = _rdf_list(graph, lst)
        for cls in list(classes):
            if str(node) in inferred.get(cls, set()) or str(node) in asserted_sub.get(cls, set()):
                for op in operands:
                    op_str = str(op)
                    if isinstance(op, rdflib.URIRef) and op_str not in inferred[cls]:
                        inferred[cls].add(op_str)
                        _record(cls, op_str, "CR3",
                                [f"{_short(cls)} ⊑ {_short(str(node))}", f"{_short(str(node))} = {' ⊓ '.join(_short(str(o)) for o in operands if isinstance(o, rdflib.URIRef))}"],
                                [f"<{cls}> <{RDFS.subClassOf}> {_nt(node)} ."]
                                + _serialize_list_axioms(graph, node, lst))

    # ── CR4: existential propagation — A ⊑ ∃r.B and ∃r.B ⊑ D → A ⊑ D ────────
    # Collect A → [(role, filler)] from owl:someValuesFrom restrictions.
    # asserted_sub only holds named-class superclasses; blank-node restrictions
    # must be found by scanning subClassOf triples directly.
    a_exists: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for s, _, o in graph.triples((None, RDFS.subClassOf, None)):
        if not isinstance(s, rdflib.URIRef):
            continue
        cls_str = str(s)
        if cls_str not in classes:
            continue
        # o may be a blank node (restriction) or a named class
        role = graph.value(o, OWL.onProperty)
        filler = graph.value(o, OWL.someValuesFrom)
        if role is not None and filler is not None:
            a_exists[cls_str].append((str(role), str(filler)))

    # Also collect existential restrictions from equivalentClass intersections.
    # For A equivalentClass intersection([B, restriction(P some F), ...]),
    # treat A as having the existential A ⊑ ∃P.F so CR4 can fire.
    for s, _, o in graph.triples((None, OWL.equivalentClass, None)):
        if not isinstance(s, rdflib.URIRef):
            continue
        cls_str = str(s)
        if cls_str not in classes:
            continue
        # Check for direct restriction (A equivalentClass restriction(...))
        role = graph.value(o, OWL.onProperty)
        filler = graph.value(o, OWL.someValuesFrom)
        if role is not None and filler is not None:
            a_exists[cls_str].append((str(role), str(filler)))
            continue
        # Check for intersection (A equivalentClass intersectionOf([..., restriction(...), ...]))
        inter_list = graph.value(o, OWL.intersectionOf)
        if inter_list is not None:
            for item in _rdf_list(graph, inter_list):
                role = graph.value(item, OWL.onProperty)
                filler = graph.value(item, OWL.someValuesFrom)
                if role is not None and filler is not None:
                    a_exists[cls_str].append((str(role), str(filler)))
    # Also collect ∃r.B ⊑ D GCIs from all restrictions (already done in
    # _collect_existential_supers, but also add any found via GCI on blank nodes)
    for restr, _, _ in graph.triples((None, RDF.type, OWL.Restriction)):
        role = graph.value(restr, OWL.onProperty)
        filler = graph.value(restr, OWL.someValuesFrom)
        if role is None or filler is None:
            continue
        role_str   = str(role)
        filler_str = str(filler)
        for _, _, gci_sup in graph.triples((restr, RDFS.subClassOf, None)):
            if isinstance(gci_sup, rdflib.URIRef):
                exists_sups.setdefault((role_str, filler_str), set()).add(str(gci_sup))

    for cls, exist_list in a_exists.items():
        for (role, filler) in exist_list:
            # Direct GCIs on this existential
            for sup in exists_sups.get((role, filler), set()):
                if sup not in inferred[cls]:
                    inferred[cls].add(sup)
                    _record(cls, sup, "CR4",
                            [f"{_short(cls)} ⊑ ∃{_short(role)}.{_short(filler)}",
                             f"∃{_short(role)}.{_short(filler)} ⊑ {_short(sup)}"],
                            [f"{_nt_str(cls)} <{RDFS.subClassOf}> _:restr .",
                             f"_:restr <{OWL.onProperty}> {_nt_str(role)} .",
                             f"_:restr <{OWL.someValuesFrom}> {_nt_str(filler)} .",
                             f"_:restr <{RDFS.subClassOf}> {_nt_str(sup)} ."])

            # ── CR5: role hierarchy — r ⊑ s means ∃r.B ⊑ ∃s.B ───────────────
            for super_role in role_hier.get(role, set()):
                for sup in exists_sups.get((super_role, filler), set()):
                    if sup not in inferred[cls]:
                        inferred[cls].add(sup)
                        _record(cls, sup, "CR5",
                                [f"{_short(role)} ⊑ {_short(super_role)}",
                                 f"{_short(cls)} ⊑ ∃{_short(role)}.{_short(filler)}",
                                 f"∃{_short(super_role)}.{_short(filler)} ⊑ {_short(sup)}"],
                                [f"<{role}> <{RDFS.subPropertyOf}> <{super_role}> .",
                                 f"<{cls}> <{RDFS.subClassOf}> _:restr .",
                                 f"_:restr2 <{RDFS.subClassOf}> <{sup}> ."])

    # ── CR2: transitivity fixed-point ─────────────────────────────────────────
    changed = True
    while changed:
        changed = False
        for cls in classes:
            new_sups: set[str] = set()
            for sup in list(inferred[cls]):
                for sup2 in inferred.get(sup, set()):
                    if sup2 not in inferred[cls] and sup2 != cls:
                        new_sups.add(sup2)
                        _record(cls, sup2, "CR2",
                                [f"{_short(cls)} ⊑ {_short(sup)}", f"{_short(sup)} ⊑ {_short(sup2)}"],
                                [f"{_nt_str(cls)} <{RDFS.subClassOf}> {_nt_str(sup)} .",
                                 f"{_nt_str(sup)} <{RDFS.subClassOf}> {_nt_str(sup2)} ."])
            if new_sups:
                inferred[cls].update(new_sups)
                changed = True

    # ── CR6: unsatisfiability — A ⊑ B and A ⊑ C and B disjointWith C ─────────
    unsatisfiable: list[str] = []
    for cls in classes:
        sups = inferred[cls]
        for b in list(sups):
            for c in disjoints.get(b, set()):
                if c in sups and cls not in unsatisfiable:
                    unsatisfiable.append(cls)
                    inferred[cls].add(OWL_NOTHING)
                    _record(cls, OWL_NOTHING, "CR6",
                            [f"{_short(cls)} ⊑ {_short(b)}", f"{_short(cls)} ⊑ {_short(c)}",
                             f"{_short(b)} disjointWith {_short(c)}"],
                            [f"{_nt_str(cls)} <{RDFS.subClassOf}> {_nt_str(b)} .",
                             f"{_nt_str(cls)} <{RDFS.subClassOf}> {_nt_str(c)} .",
                             f"{_nt_str(b)} <{OWL.disjointWith}> {_nt_str(c)} ."])

    # Build result — superclasses contains only inferred (not directly asserted)
    asserted_all: set[tuple[str, str]] = set()
    for cls, sups in asserted_sub.items():
        for sup in sups:
            asserted_all.add((cls, sup))
    for cls, eqs in equiv_pairs.items():
        for eq in eqs:
            asserted_all.add((cls, eq))
            asserted_all.add((eq, cls))

    def _is_named_iri(s: str) -> bool:
        return "://" in s or s.startswith("urn:")

    superclasses: dict[str, list[str]] = {}
    subclasses:   dict[str, list[str]] = defaultdict(list)
    for cls in classes:
        inf_sups = [s for s in inferred[cls]
                    if s != cls and (cls, s) not in asserted_all and _is_named_iri(s)
                    and s not in (OWL_THING, OWL_NOTHING)]
        superclasses[cls] = inf_sups
        for sup in inf_sups:
            subclasses[sup].append(cls)

    # direct_superclasses: asserted subClassOf + equivalentClass-derived (both are "asserted")
    direct_sup: dict[str, list[str]] = defaultdict(list)
    for cls, sups in asserted_sub.items():
        direct_sup[cls].extend(sups)
    for cls, eqs in equiv_pairs.items():
        for eq in eqs:
            if eq not in direct_sup[cls]:
                direct_sup[cls].append(eq)

    direct_subs: dict[str, list[str]] = defaultdict(list)
    for cls, sups in direct_sup.items():
        for sup in sups:
            direct_subs[sup].append(cls)

    from datetime import datetime, timezone
    return ClassificationResult(
        version_id=version_id,
        classified_at=datetime.now(timezone.utc).isoformat(),
        class_count=len(classes),
        superclasses=superclasses,
        subclasses=dict(subclasses),
        direct_superclasses=dict(direct_sup),
        direct_subclasses=dict(direct_subs),
        unsatisfiable=unsatisfiable,
        proof_traces=traces,
        duration_ms=round((time.monotonic() - t0) * 1000, 1),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_classes(g: rdflib.Graph) -> set[str]:
    classes: set[str] = set()
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, rdflib.URIRef):
            classes.add(str(s))
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        if isinstance(s, rdflib.URIRef):
            classes.add(str(s))
        if isinstance(o, rdflib.URIRef):
            classes.add(str(o))
    classes.discard(str(OWL.Thing))
    classes.discard(str(OWL.Nothing))
    return classes


def _collect_asserted_subclass(g: rdflib.Graph, classes: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            if str(s) in classes and str(o) != str(s):
                result[str(s)].add(str(o))
    return result


def _collect_equiv(g: rdflib.Graph, classes: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, OWL.equivalentClass, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            if str(s) in classes and str(o) in classes:
                result[str(s)].add(str(o))
    return result


def _collect_existential_supers(g: rdflib.Graph) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    for restr, _, _ in g.triples((None, RDF.type, OWL.Restriction)):
        role   = g.value(restr, OWL.onProperty)
        filler = g.value(restr, OWL.someValuesFrom)
        if role is None or filler is None:
            continue
        for _, _, sup in g.triples((restr, RDFS.subClassOf, None)):
            if isinstance(sup, rdflib.URIRef):
                result[(str(role), str(filler))].add(str(sup))
    return result


def _collect_role_hierarchy(g: rdflib.Graph) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, RDFS.subPropertyOf, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            result[str(s)].add(str(o))
    return result


def _collect_disjointness(g: rdflib.Graph, classes: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, OWL.disjointWith, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            result[str(s)].add(str(o))
            result[str(o)].add(str(s))
    return result


def _rdf_list(g: rdflib.Graph, node) -> list:
    items = []
    current = node
    while current and current != RDF.nil:
        first = g.value(current, RDF.first)
        if first is not None:
            items.append(first)
        current = g.value(current, RDF.rest)
    return items


def _short(iri: str) -> str:
    if "#" in iri:
        return iri.split("#")[-1]
    return iri.rstrip("/").split("/")[-1]
