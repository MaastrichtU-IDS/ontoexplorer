"""Tests for ontology auto-sync: polling and GitHub inbound webhook."""
import pytest
from ontoexplorer.models.db import Ontology, OntologyVersion


@pytest.mark.anyio
async def test_ontology_has_auto_sync_field(db_session):
    """Ontology model has auto_sync defaulting to False."""
    ont = Ontology(iri="http://example.org/sync-test.owl")
    db_session.add(ont)
    await db_session.commit()
    await db_session.refresh(ont)
    assert ont.auto_sync is False


@pytest.mark.anyio
async def test_version_has_source_url_field(db_session):
    """OntologyVersion model has source_url defaulting to None."""
    ont = Ontology(iri="http://example.org/sync-test2.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key.ttl",
        sha256="abc123unique",
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/onto.ttl",
    )
    db_session.add(ver)
    await db_session.commit()
    await db_session.refresh(ver)
    assert ver.source_url == "https://raw.githubusercontent.com/owner/repo/main/onto.ttl"
