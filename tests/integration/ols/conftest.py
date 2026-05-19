"""Fixtures for OLS-compat integration tests.

Reuses the shared `app`, `client`, `db_session`, and `anyio_backend` fixtures
from tests/conftest.py.  This file only adds what is specific to OLS tests:
a fake Redis instance and a sample ontology row.
"""
import uuid
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.indexer import _meta_key


@pytest.fixture()
def fake_redis():
    """A FakeRedis instance shared across the OLS layer and the indexer."""
    r = fakeredis.FakeRedis(decode_responses=True)
    with (
        patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.ontologies._get_redis", return_value=r),
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
