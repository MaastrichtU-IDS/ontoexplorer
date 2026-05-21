"""Fixtures specific to integration tests."""
import uuid

import pytest

from ontoexplorer.models.db import SavedQuery, User

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"

STARTERS = [
    {
        "name": "All classes in scope",
        "description": "Every owl:Class declared in the scoped named graphs, with rdfs:label if any.",
        "category": "Exploration",
        "tags": ["owl", "class"],
        "query_text": "SELECT DISTINCT ?cls WHERE { GRAPH ?g { ?cls a <http://www.w3.org/2002/07/owl#Class> } } LIMIT 200",
    },
    {
        "name": "All properties in scope",
        "description": "Every property in the scoped graphs.",
        "category": "Exploration",
        "tags": ["owl", "property"],
        "query_text": "SELECT DISTINCT ?p WHERE { GRAPH ?g { ?p a <http://www.w3.org/2002/07/owl#ObjectProperty> } } LIMIT 200",
    },
    {
        "name": "All named individuals in scope",
        "description": "Every owl:NamedIndividual declared in the scoped graphs.",
        "category": "Exploration",
        "tags": ["owl", "individual"],
        "query_text": "SELECT DISTINCT ?ind WHERE { GRAPH ?g { ?ind a <http://www.w3.org/2002/07/owl#NamedIndividual> } } LIMIT 200",
    },
    {
        "name": "Find term by label",
        "description": "Replace 'search text' with a partial or exact label.",
        "category": "Term lookup",
        "tags": ["label", "search"],
        "query_text": "SELECT ?term ?label WHERE { GRAPH ?g { ?term <http://www.w3.org/2000/01/rdf-schema#label> ?label . FILTER(CONTAINS(LCASE(STR(?label)), \"search text\")) } } LIMIT 100",
    },
    {
        "name": "Subclasses of class",
        "description": "Replace <URI_HERE> with a class IRI.",
        "category": "Term lookup",
        "tags": ["subclass", "hierarchy"],
        "query_text": "SELECT ?sub WHERE { GRAPH ?g { ?sub <http://www.w3.org/2000/01/rdf-schema#subClassOf> <URI_HERE> } }",
    },
    {
        "name": "Inferred subClassOf chain",
        "description": "Use the Inferred reasoning mode.",
        "category": "Reasoning",
        "tags": ["inferred", "subclass"],
        "query_text": "SELECT ?ancestor WHERE { GRAPH ?g { <URI_HERE> <http://www.w3.org/2000/01/rdf-schema#subClassOf>+ ?ancestor } }",
    },
    {
        "name": "Equivalents of class",
        "description": "Replace <URI_HERE> with a class IRI.",
        "category": "Reasoning",
        "tags": ["equivalent"],
        "query_text": "SELECT ?eq WHERE { GRAPH ?g { <URI_HERE> <http://www.w3.org/2002/07/owl#equivalentClass> ?eq } }",
    },
    {
        "name": "OWL 2 DL violations: punning",
        "description": "Entities used as both class and individual.",
        "category": "Profile",
        "tags": ["dl", "violation", "punning"],
        "query_text": "SELECT DISTINCT ?entity WHERE { GRAPH ?g { ?entity a <http://www.w3.org/2002/07/owl#Class> . ?entity a <http://www.w3.org/2002/07/owl#NamedIndividual> } }",
    },
    {
        "name": "OWL 2 EL violations: universal restrictions",
        "description": "owl:allValuesFrom restrictions are not permitted in OWL 2 EL.",
        "category": "Profile",
        "tags": ["el", "violation"],
        "query_text": "SELECT DISTINCT ?restriction WHERE { GRAPH ?g { ?restriction a <http://www.w3.org/2002/07/owl#Restriction> ; <http://www.w3.org/2002/07/owl#allValuesFrom> ?type } }",
    },
    {
        "name": "Triples in V2 not in V1",
        "description": "Asymmetric diff between two version graphs.",
        "category": "Diff",
        "tags": ["diff", "version"],
        "query_text": "SELECT ?s ?p ?o WHERE { GRAPH <V2_URI_HERE> { ?s ?p ?o } FILTER NOT EXISTS { GRAPH <V1_URI_HERE> { ?s ?p ?o } } } LIMIT 200",
    },
]


@pytest.fixture(autouse=True, scope="session")
async def seed_starters(engine):
    """Seed the system user and starter queries into the in-memory test DB."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        # Create system user (idempotent)
        from sqlalchemy import select as sa_select

        existing = await session.execute(
            sa_select(User).where(User.id == SYSTEM_USER_ID)
        )
        if existing.scalar_one_or_none() is None:
            session.add(User(id=SYSTEM_USER_ID, display_name="System"))
            await session.flush()

        # Seed starters (idempotent by name)
        for s in STARTERS:
            existing_sq = await session.execute(
                sa_select(SavedQuery).where(
                    SavedQuery.name == s["name"],
                    SavedQuery.is_starter == True,  # noqa: E712
                )
            )
            if existing_sq.scalar_one_or_none() is None:
                session.add(
                    SavedQuery(
                        id=str(uuid.uuid4()),
                        user_id=SYSTEM_USER_ID,
                        name=s["name"],
                        description=s["description"],
                        query_text=s["query_text"],
                        tags=s["tags"],
                        is_public=True,
                        is_starter=True,
                        category=s["category"],
                    )
                )
        await session.commit()
