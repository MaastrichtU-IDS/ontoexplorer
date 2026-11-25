"""The catalogue acronym on an IngestionRequest reaches the shortname (#476 follow-up).

Covers the threading hop the pure `derive_shortname` tests and the mocked-``delay``
runner test cannot: a real `_ensure_ontology` run deriving the shortname from
`IngestionRequest.source_acronym` when the IRI tail is useless.
"""
import uuid

from sqlalchemy import select

from ontoexplorer.models.db import Ontology
from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, _ensure_ontology


async def _shortname_for(db, iri: str, **req_kwargs) -> str | None:
    oid, created = await _ensure_ontology(db, iri, IngestionRequest(iri=iri, **req_kwargs))
    assert created is True
    row = (await db.execute(select(Ontology).where(Ontology.id == oid))).scalar_one()
    return row.shortname


async def test_source_acronym_becomes_shortname_when_iri_tail_is_useless(db_session):
    # The AgroPortal shape: the content/source IRI tail is "download"; the acronym rescues it.
    iri = f"https://data.agroportal.eu/ontologies/HVDC-{uuid.uuid4().hex[:6]}/download"
    assert await _shortname_for(db_session, iri, source_acronym="HVDC") == "hvdc"


async def test_source_acronym_none_falls_back_to_iri_tail(db_session):
    # Non-harvested ingest: no acronym → unchanged IRI-tail behaviour.
    tail = f"petvocab{uuid.uuid4().hex[:6]}"
    iri = f"http://example.org/{tail}"
    assert await _shortname_for(db_session, iri, source_acronym=None) == tail


async def test_distinct_acronyms_do_not_collide(db_session):
    # Two artefacts sharing the same useless "/download" tail stay distinct via their acronyms.
    base = uuid.uuid4().hex[:6]
    a = await _shortname_for(db_session, f"https://data.agroportal.eu/ontologies/CO_320-{base}/download", source_acronym=f"CO_320_{base}")
    b = await _shortname_for(db_session, f"https://data.agroportal.eu/ontologies/CO_321-{base}/download", source_acronym=f"CO_321_{base}")
    assert a != b
    assert a == f"co_320_{base}" and b == f"co_321_{base}"
