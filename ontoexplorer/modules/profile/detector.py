from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
from ontoexplorer.models.db import OntologyProfile, OntologyVersion
from ontoexplorer.modules.profile.registry import (
    ALL_PROPS, IRI_TO_ROLE, MOD_DEFINITION, MOD_PREF_LABEL, default_profile,
)

_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


async def load_profile(db: AsyncSession, version_id: str) -> dict[str, list[str]]:
    """Return stored profile props for a version, or curated defaults if none exists."""
    result = await db.execute(
        select(OntologyProfile).where(OntologyProfile.version_id == version_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return default_profile()
    p = default_profile()
    return {
        "label_props": row.label_props or p["label_props"],
        "definition_props": row.definition_props or p["definition_props"],
        "elucidation_props": row.elucidation_props or p["elucidation_props"],
        "synonym_props": row.synonym_props or p["synonym_props"],
        "deprecated_props": row.deprecated_props or p["deprecated_props"],
        "example_props": row.example_props or p["example_props"],
    }


async def run_detection(db: AsyncSession, version_id: str, ontology_id: str = "") -> None:
    """Detect annotation property usage in Oxigraph and write/update ontology_profiles row."""
    if not ontology_id:
        r = await db.execute(
            select(OntologyVersion.ontology_id).where(OntologyVersion.id == version_id)
        )
        ontology_id = r.scalar_one()

    named_graph = graph_iri(ontology_id, version_id)

    class_count = await asyncio.to_thread(_count_classes, named_graph)

    counts: dict[str, int] = {}
    for iris in ALL_PROPS.values():
        for iri in iris:
            counts[iri] = await asyncio.to_thread(_count_property_usage, named_graph, iri)

    mod_label = await asyncio.to_thread(_get_mod_declaration, named_graph, MOD_PREF_LABEL)
    mod_def = await asyncio.to_thread(_get_mod_declaration, named_graph, MOD_DEFINITION)

    role_props: dict[str, list[str]] = {
        "label": _build_role_list(ALL_PROPS["label"], counts, mod_label),
        "definition": _build_role_list(ALL_PROPS["definition"], counts, mod_def),
        "elucidation": _build_role_list(ALL_PROPS["elucidation"], counts, None),
        "synonym": _build_role_list(ALL_PROPS["synonym"], counts, None),
        "deprecated": _build_role_list(ALL_PROPS["deprecated"], counts, None),
        "example": _build_role_list(ALL_PROPS["example"], counts, None),
    }

    threshold = max(1, int(class_count * 0.05))
    unknown = await asyncio.to_thread(_find_unknown_props, named_graph, class_count, threshold)

    all_candidate_iris = list({
        iri for iris in ALL_PROPS.values() for iri in iris if counts.get(iri, 0) > 0
    } | {u["iri"] for u in unknown})
    labels = await asyncio.to_thread(_get_prop_labels, named_graph, all_candidate_iris)

    candidates: dict = {
        role: [
            {
                "iri": iri,
                "count": counts.get(iri, 0),
                "mod_declared": iri in (mod_label, mod_def),
                "label": labels.get(iri),
            }
            for iri in ALL_PROPS[role]
            if counts.get(iri, 0) > 0
        ]
        for role in ALL_PROPS
    }
    candidates["unknown"] = [{**u, "label": labels.get(u["iri"])} for u in unknown]

    existing = (
        await db.execute(
            select(OntologyProfile).where(OntologyProfile.version_id == version_id)
        )
    ).scalar_one_or_none()

    if existing:
        existing.label_props = role_props["label"]
        existing.definition_props = role_props["definition"]
        existing.elucidation_props = role_props["elucidation"]
        existing.synonym_props = role_props["synonym"]
        existing.deprecated_props = role_props["deprecated"]
        existing.example_props = role_props["example"]
        existing.candidates_data = candidates
        existing.status = "auto_detected"
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(OntologyProfile(
            version_id=version_id,
            label_props=role_props["label"],
            definition_props=role_props["definition"],
            elucidation_props=role_props["elucidation"],
            synonym_props=role_props["synonym"],
            deprecated_props=role_props["deprecated"],
            example_props=role_props["example"],
            candidates_data=candidates,
            status="auto_detected",
        ))

    await db.commit()


def _get_prop_labels(named_graph: str, iris: list[str]) -> dict[str, str]:
    """Return rdfs:label values for a list of property IRIs found in the named graph."""
    if not iris:
        return {}
    values_clause = " ".join(f"<{iri}>" for iri in iris)
    q = f"""
        SELECT ?prop ?label WHERE {{
            GRAPH <{named_graph}> {{
                VALUES ?prop {{ {values_clause} }}
                ?prop <{_RDFS_LABEL}> ?label .
                FILTER(LANG(?label) = "en" || LANG(?label) = "")
            }}
        }}
    """
    result: dict[str, str] = {}
    for row in sparql_query(q):
        iri = row["prop"].value
        if iri not in result:
            result[iri] = row["label"].value
    return result


def _count_property_usage(named_graph: str, property_iri: str) -> int:
    q = f"""
        SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{
            GRAPH <{named_graph}> {{
                ?s a <http://www.w3.org/2002/07/owl#Class> .
                ?s <{property_iri}> ?o .
            }}
        }}
    """
    rows = list(sparql_query(q))
    if rows and hasattr(rows[0]["n"], "value"):
        return int(rows[0]["n"].value)
    return 0


def _count_classes(named_graph: str) -> int:
    q = f"""
        SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{
            GRAPH <{named_graph}> {{
                ?s a <http://www.w3.org/2002/07/owl#Class> .
                FILTER(isIRI(?s))
            }}
        }}
    """
    rows = list(sparql_query(q))
    if rows and hasattr(rows[0]["n"], "value"):
        return int(rows[0]["n"].value)
    return 0


def _get_mod_declaration(named_graph: str, predicate: str) -> str | None:
    q = f"""
        SELECT ?v WHERE {{
            GRAPH <{named_graph}> {{
                ?o a <http://www.w3.org/2002/07/owl#Ontology> .
                ?o <{predicate}> ?v .
            }}
        }} LIMIT 1
    """
    rows = list(sparql_query(q))
    if rows and "v" in rows[0] and hasattr(rows[0]["v"], "value"):
        return rows[0]["v"].value
    return None


def _build_role_list(
    iris: list[str],
    counts: dict[str, int],
    mod_override: str | None,
) -> list[str]:
    """Return IRIs with count > 0, sorted by count descending, MOD-declared IRI at position 0."""
    detected = sorted(
        [iri for iri in iris if counts.get(iri, 0) > 0],
        key=lambda i: counts[i],
        reverse=True,
    )
    if mod_override and mod_override in iris:
        if mod_override in detected:
            detected.remove(mod_override)
        detected.insert(0, mod_override)
    return detected


def _find_unknown_props(
    named_graph: str, class_count: int, threshold: int
) -> list[dict]:
    """Return annotation properties used on > threshold classes and not in the curated registry.

    Does not require the property to be declared as owl:AnnotationProperty in the named graph,
    since built-in vocabulary (rdfs:label, rdfs:comment, etc.) is used without re-declaration.
    """
    q = f"""
        SELECT ?prop (COUNT(DISTINCT ?s) AS ?n) WHERE {{
            GRAPH <{named_graph}> {{
                ?s a <http://www.w3.org/2002/07/owl#Class> .
                ?s ?prop ?o .
                FILTER(isIRI(?s))
                FILTER(isLiteral(?o))
            }}
        }}
        GROUP BY ?prop
        HAVING (COUNT(DISTINCT ?s) > {threshold})
    """
    unknown = []
    for row in sparql_query(q):
        iri = row["prop"].value
        if iri not in IRI_TO_ROLE:
            count = int(row["n"].value)
            pct = round(count / class_count, 2) if class_count > 0 else 0.0
            unknown.append({"iri": iri, "count": count, "pct_of_classes": pct})
    unknown.sort(key=lambda x: x["count"], reverse=True)
    return unknown
