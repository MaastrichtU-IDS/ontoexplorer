"""Fixtures for OLS-compat integration tests.

Reuses the shared `app`, `client`, `db_session`, and `anyio_backend` fixtures
from tests/conftest.py.  This file only adds what is specific to OLS tests:
a fake Redis instance and a sample ontology row.
"""
import json
import uuid
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.indexer import _iri_key, _meta_key, _type_key


@pytest.fixture()
def fake_redis():
    """A FakeRedis instance shared across the OLS layer and the indexer."""
    r = fakeredis.FakeRedis(decode_responses=True)
    with (
        patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.ontologies._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.terms._get_redis", return_value=r),
    ):
        yield r


@pytest.fixture()
async def sample_ontology(db_session, fake_redis):
    """Insert a minimal Ontology + ready OntologyVersion and populate the Redis meta hash.

    Uses a UUID-suffixed identifier to avoid UNIQUE constraint failures when the
    session-scoped SQLite engine accumulates rows across tests.
    """
    uid = uuid.uuid4().hex[:8]
    ont = Ontology(
        iri=f"http://example.org/testonto-{uid}.owl",
        shortname=f"testonto{uid}",
        title="Test Ontology",
    )
    db_session.add(ont)
    await db_session.flush()  # get the auto-generated id

    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"testonto/test-{uid}.owl",
        sha256=f"testonto_sha256_{uid}",
        format="owl",
        status="ready",
        version_iri="2025-01-01",
    )
    db_session.add(ver)
    await db_session.commit()

    # Populate the search:meta:{vid} hash that ontologies.py reads via _meta_key
    fake_redis.hset(
        _meta_key(ver.id),
        mapping={
            "class_count": "100",
            "property_count": "5",
            "individual_count": "0",
            "schema_version": "v2",
            "indexed_at": "2025-01-01T00:00:00+00:00",
        },
    )

    yield ont


@pytest.fixture()
async def sample_term(db_session, sample_ontology, fake_redis):
    """Insert one class entity into Redis for the sample ontology's version.

    Also populates the roots cache (terms_root:{vid}:class:100) so the
    /terms/roots endpoint can serve results without needing Oxigraph.
    """
    from sqlalchemy import select

    ontology = sample_ontology

    # Retrieve the version that was committed by sample_ontology
    result = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == ontology.id)
    )
    ver = result.scalar_one()
    vid = str(ver.id)

    iri = "http://example.org/testonto#Foo"

    # Populate entity hash
    fake_redis.hset(
        _iri_key(vid, iri),
        mapping={
            "iri": iri,
            "primary_label": "Foo",
            "label": "Foo",
            "short": "Foo",
            "type": "class",
            "source": ontology.id,
            "labels": json.dumps([{"value": "Foo", "lang": "en"}]),
            "synonyms": json.dumps([]),
            "definitions": json.dumps([]),
        },
    )
    # Register in type set for list endpoint
    fake_redis.sadd(_type_key(vid, "class"), iri)

    # Populate roots cache so /terms/roots works without Oxigraph
    roots_key = f"terms_root:{vid}:class:100"
    fake_redis.set(
        roots_key,
        json.dumps({
            "terms": [{"iri": iri, "label": "Foo", "has_children": False}],
            "offset": 0,
            "limit": 100,
            "parent": "root",
        }),
    )

    yield {"iri": iri, "ontology": ontology, "version_id": vid}
