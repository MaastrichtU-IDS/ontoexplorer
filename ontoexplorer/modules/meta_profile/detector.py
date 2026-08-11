from __future__ import annotations

import asyncio

import pyoxigraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion
from ontoexplorer.modules.meta_profile.registry import (
    ALL_KNOWN_IRIS,
    ALL_META_ROLES,
    MULTI_VALUE_ROLES,
    ROLE_RESOLVED_KEY,
)

_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


async def run_meta_detection(
    db: AsyncSession, version_id: str, ontology_id: str = "", force: bool = False
) -> None:
    """Detect ontology-level metadata from the owl:Ontology node and write profile row.

    `force=False` (auto paths: ingestion, admin reindex) preserves a
    `user_confirmed` profile — it refreshes only the candidate list and leaves the
    user's role mappings/resolved values untouched, so a reindex never silently
    reverts a manual mapping. `force=True` (the explicit Re-detect action) always
    re-derives.
    """
    if not ontology_id:
        r = await db.execute(
            select(OntologyVersion.ontology_id).where(OntologyVersion.id == version_id)
        )
        ontology_id = r.scalar_one()

    r2 = await db.execute(select(Ontology.iri).where(Ontology.id == ontology_id))
    onto_iri = r2.scalar_one()

    named_graph = graph_iri(ontology_id, version_id)
    triples = await asyncio.to_thread(_fetch_onto_triples, named_graph, onto_iri)

    role_props: dict[str, list[str]] = {
        role: _build_role_props(iris, triples)
        for role, iris in ALL_META_ROLES.items()
    }
    resolved = _resolve_values(triples, role_props)

    all_pred_iris = list(triples.keys())
    labels = await asyncio.to_thread(_get_prop_labels, named_graph, all_pred_iris)

    candidates: dict = {
        role: [
            {"iri": iri, "values": triples[iri], "label": labels.get(iri)}
            for iri in iris
            if iri in triples
        ]
        for role, iris in ALL_META_ROLES.items()
    }
    candidates["unknown"] = [
        {"iri": pred, "values": vals, "label": labels.get(pred)}
        for pred, vals in triples.items()
        if pred not in ALL_KNOWN_IRIS
    ]

    row_kwargs = {f"{role}_props": props for role, props in role_props.items()}

    existing = (
        await db.execute(
            select(OntologyMetaProfile).where(OntologyMetaProfile.version_id == version_id)
        )
    ).scalar_one_or_none()

    if existing and existing.status == "user_confirmed" and not force:
        # Preserve the user's confirmed mapping across re-index / auto re-detect;
        # only refresh candidates so the editor still lists current predicates.
        existing.candidates_data = candidates
        await db.commit()
        return

    if existing:
        for col, val in row_kwargs.items():
            setattr(existing, col, val)
        existing.resolved = resolved
        existing.candidates_data = candidates
        existing.status = "auto_detected"
    else:
        db.add(OntologyMetaProfile(
            version_id=version_id,
            **row_kwargs,
            resolved=resolved,
            candidates_data=candidates,
            status="auto_detected",
        ))

    await db.commit()

    if resolved.get("shortname"):
        r3 = await db.execute(select(Ontology).where(Ontology.id == ontology_id))
        ont = r3.scalar_one_or_none()
        if ont and not ont.shortname:
            try:
                ont.shortname = resolved["shortname"]
                await db.commit()
            except Exception:
                await db.rollback()


def _get_prop_labels(named_graph: str, iris: list[str]) -> dict[str, str]:
    """Return rdfs:label values for a list of predicate IRIs found in the named graph."""
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


_OWL_ONTOLOGY = "http://www.w3.org/2002/07/owl#Ontology"
_OWL_IMPORTS = "http://www.w3.org/2002/07/owl#imports"


def _fetch_onto_triples(named_graph: str, onto_iri: str) -> dict[str, list[dict]]:
    """Return all predicate->value entries on the owl:Ontology node.

    Queries the stored IRI directly first.  Falls back to any owl:Ontology node that
    is not an owl:imports target — this handles ontologies that declare the ontology
    header on a blank node ([] a owl:Ontology ; rdfs:label "…") where onto_iri is
    the submission URL, not the actual blank-node subject.
    """
    triples: dict[str, list[dict]] = {}

    def _collect(sparql: str) -> None:
        for row in sparql_query(sparql):
            pred = row["pred"].value
            obj = row["obj"]
            triples.setdefault(pred, []).append({
                "value": obj.value,
                "is_iri": isinstance(obj, pyoxigraph.NamedNode),
                "language": getattr(obj, "language", None),
            })

    _collect(f"""
        SELECT ?pred ?obj WHERE {{
            GRAPH <{named_graph}> {{
                <{onto_iri}> ?pred ?obj .
            }}
        }}
    """)

    # If the direct-IRI query found no title predicates, the ontology header is likely
    # on a blank node.  Re-query for any owl:Ontology subject that isn't an import target
    # so we don't accidentally pick up metadata from a loaded owl:imports dependency.
    title_iris = ALL_META_ROLES["title"]
    if not any(iri in triples for iri in title_iris):
        _collect(f"""
            SELECT ?pred ?obj WHERE {{
                GRAPH <{named_graph}> {{
                    ?onto a <{_OWL_ONTOLOGY}> .
                    FILTER NOT EXISTS {{
                        GRAPH <{named_graph}> {{ ?other <{_OWL_IMPORTS}> ?onto . }}
                    }}
                    ?onto ?pred ?obj .
                }}
            }}
        """)

    return triples


def _build_role_props(iris: list[str], triples: dict[str, list[dict]]) -> list[str]:
    """Return registered IRIs that are present in the triples, in registry priority order."""
    return [iri for iri in iris if iri in triples]


def _resolve_values(
    triples: dict[str, list[dict]],
    role_props: dict[str, list[str]],
) -> dict:
    """Extract resolved scalar/list values using the role->IRI mapping."""
    resolved: dict = {}
    for role, props in role_props.items():
        key = ROLE_RESOLVED_KEY[role]
        if role in MULTI_VALUE_ROLES:
            values: list[str] = []
            for iri in props:
                for entry in triples.get(iri, []):
                    v = entry["value"]
                    if v not in values:
                        values.append(v)
            resolved[key] = values
        else:
            value = None
            for iri in props:
                entries = triples.get(iri, [])
                if entries:
                    en = next((e for e in entries if e.get("language") == "en"), None)
                    value = (en or entries[0])["value"]
                    break
            resolved[key] = value
    return resolved
