"""source_catalogue provenance: a harvested version records which peer catalogue it came from."""
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import OntologyVersion
from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, run_ingestion


def _turtle(name: str) -> bytes:
    return (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"<http://example.org/{name}> a owl:Ontology .\n"
    ).encode()


async def _ingest(db_session, request: IngestionRequest) -> OntologyVersion:
    p = "ontoexplorer.modules.ingestion.pipeline."
    with ExitStack() as stack:
        stack.enter_context(patch(p + "store_ontology", MagicMock(return_value="ont/ver/sha.ttl")))
        stack.enter_context(patch(p + "bulk_load_bytes", MagicMock(return_value=3)))
        stack.enter_context(patch(p + "resolve_imports_sparql", MagicMock(return_value={})))
        stack.enter_context(patch(p + "_extract_ontology_iri_sparql", MagicMock(return_value=None)))
        stack.enter_context(patch(p + "_extract_version_iri_sparql", MagicMock(return_value=None)))
        stack.enter_context(patch(p + "_write_fair_metadata", new=AsyncMock()))
        # Celery fan-out (no broker in tests): stub every task the pipeline .delay()s.
        for task in ("reason_ontology", "index_ontology", "detect_profile",
                     "detect_meta_profile", "compute_diff"):
            stack.enter_context(patch(f"ontoexplorer.modules.jobs.tasks.{task}",
                                      MagicMock(delay=MagicMock()), create=True))
        result = await run_ingestion(db_session, request)
    row = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.id == result.version_id)
    )
    return row.scalar_one()


@pytest.mark.anyio
async def test_request_source_catalogue_persists_on_version(db_session):
    ver = await _ingest(
        db_session,
        IngestionRequest(raw_bytes=_turtle("HarvestProvA"), source_catalogue="peer-x"),
    )
    assert ver.source_catalogue == "peer-x"


@pytest.mark.anyio
async def test_source_catalogue_defaults_null(db_session):
    ver = await _ingest(db_session, IngestionRequest(raw_bytes=_turtle("HarvestProvB")))
    assert ver.source_catalogue is None


def test_ingest_ontology_task_accepts_source_catalogue():
    import inspect
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    params = inspect.signature(ingest_ontology.run).parameters
    assert "source_catalogue" in params
    assert params["source_catalogue"].default is None
