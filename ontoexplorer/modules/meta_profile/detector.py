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


async def run_meta_detection(
    db: AsyncSession, version_id: str, ontology_id: str = ""
) -> None:
    """Detect ontology-level metadata from the owl:Ontology node and write profile row."""
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

    candidates: dict = {
        role: [
            {"iri": iri, "values": triples[iri]}
            for iri in iris
            if iri in triples
        ]
        for role, iris in ALL_META_ROLES.items()
    }
    candidates["unknown"] = [
        {"iri": pred, "values": vals}
        for pred, vals in triples.items()
        if pred not in ALL_KNOWN_IRIS
    ]

    row_kwargs = {f"{role}_props": props for role, props in role_props.items()}

    existing = (
        await db.execute(
            select(OntologyMetaProfile).where(OntologyMetaProfile.version_id == version_id)
        )
    ).scalar_one_or_none()

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
            ont.shortname = resolved["shortname"]
            await db.commit()


def _fetch_onto_triples(named_graph: str, onto_iri: str) -> dict[str, list[dict]]:
    """Return all predicate->value entries on the owl:Ontology node."""
    q = f"""
        SELECT ?pred ?obj WHERE {{
            GRAPH <{named_graph}> {{
                <{onto_iri}> ?pred ?obj .
            }}
        }}
    """
    triples: dict[str, list[dict]] = {}
    for row in sparql_query(q):
        pred = row["pred"].value
        obj = row["obj"]
        entry = {
            "value": obj.value,
            "is_iri": isinstance(obj, pyoxigraph.NamedNode),
            "language": getattr(obj, "language", None),
        }
        triples.setdefault(pred, []).append(entry)
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
