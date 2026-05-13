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


@pytest.mark.anyio
async def test_ingestion_stores_source_url(db_session):
    """run_ingestion sets source_url on the created OntologyVersion."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, run_ingestion
    from ontoexplorer.modules.ingestion.source_resolver import ResolvedSource, SourceMode

    _TURTLE = b"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/SrcUrlOntology> a owl:Ontology .
"""
    _SOURCE_URL = "https://raw.githubusercontent.com/owner/repo/main/onto.ttl"

    mock_source = ResolvedSource(
        data=_TURTLE,
        content_type="text/turtle",
        final_url=_SOURCE_URL,
        mode=SourceMode.URL,
    )

    # Patch at the pipeline module level (where names are bound after import)
    with (
        patch("ontoexplorer.modules.ingestion.pipeline.resolve_url", return_value=mock_source),
        patch("ontoexplorer.modules.ingestion.pipeline.store_ontology",
              MagicMock(return_value="ont/ver/sha.ttl")),
        patch("ontoexplorer.modules.ingestion.pipeline.bulk_load_bytes",
              MagicMock(return_value=3)),
        patch("ontoexplorer.modules.ingestion.pipeline.resolve_imports_sparql",
              MagicMock(return_value={})),
        patch("ontoexplorer.modules.ingestion.pipeline._extract_ontology_iri_sparql",
              MagicMock(return_value=None)),
        patch("ontoexplorer.modules.ingestion.pipeline._extract_version_iri_sparql",
              MagicMock(return_value=None)),
        patch("ontoexplorer.modules.ingestion.pipeline._write_fair_metadata", new=AsyncMock()),
        patch("ontoexplorer.modules.jobs.tasks.reason_ontology",
              MagicMock(delay=MagicMock()), create=True),
        patch("ontoexplorer.modules.jobs.tasks.index_ontology",
              MagicMock(delay=MagicMock()), create=True),
    ):
        result = await run_ingestion(
            db_session,
            IngestionRequest(url=_SOURCE_URL),
        )

    from sqlalchemy import select
    ver_row = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.id == result.version_id)
    )
    ver = ver_row.scalar_one()
    assert ver.source_url == _SOURCE_URL
