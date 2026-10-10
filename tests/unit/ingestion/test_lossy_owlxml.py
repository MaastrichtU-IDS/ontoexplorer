"""#311: refuse the lossy OWL/XML-structural-flatten ingest form.

Some LOV `.n3` dumps (gci, dfc, dfc-p, dfc-t, IIoT) are an OWL/XML document tree
flattened into RDF: blank nodes typed owl:Declaration/owl:IRI/owl:AbbreviatedIRI,
with the real entity IRIs/labels absent and ZERO IRI-typed subjects. They index
to 0 terms and no converter can recover the names, so the ingester must refuse
them rather than persist a silently-invisible "ready" version. These tests pin
the detector's verdict and its safety gate (never block a vocab that has real
entities, or a legitimately metadata-only wrapper).
"""
import pytest

from ontoexplorer.modules.ingestion.lossy_owlxml import (
    LossyOwlXmlIngest,
    lossy_owlxml_report,
)


class _Term:
    """Mimics a pyoxigraph Literal binding: has `.value` and str()."""
    def __init__(self, v):
        self.value = str(v)

    def __str__(self):
        return self.value


class _Row:
    def __init__(self, n):
        self._n = _Term(n)

    def __getitem__(self, key):
        assert key == "n"
        return self._n


def _fake_query(structural: int, entities: int):
    """Return a query fn that answers the structural-count query with `structural`
    and the entity-count query with `entities`, recording which queries ran."""
    seen = []

    def query(sparql: str):
        seen.append(sparql)
        if "owl#Declaration" in sparql:        # the VALUES-based structural query
            return [_Row(structural)]
        if "isIRI(?s) && isIRI(?t)" in sparql:  # the real-entity query
            return [_Row(entities)]
        raise AssertionError(f"unexpected query: {sparql}")

    query.seen = seen  # type: ignore[attr-defined]
    return query


def test_report_flags_lossy_owlxml_flatten():
    """Structural artifacts present AND zero IRI-typed entities → refuse."""
    q = _fake_query(structural=1814, entities=0)
    report = lossy_owlxml_report("urn:ontology:gci:v1", query=q)
    assert report is not None
    assert report["structural_count"] == 1814
    assert report["entity_count"] == 0
    assert "OWL/XML structural serialization" in report["message"]


def test_report_dormant_when_no_structural_artifacts():
    """No owl:Declaration/owl:IRI/owl:AbbreviatedIRI → not this bug; the entity
    query must not even run (fast path)."""
    q = _fake_query(structural=0, entities=0)
    report = lossy_owlxml_report("urn:ontology:50kgazetteer:v1", query=q)
    assert report is None
    # Only the structural query ran — the entity count was never needed.
    assert len(q.seen) == 1
    assert "owl#Declaration" in q.seen[0]


def test_report_does_not_block_vocab_with_real_entities():
    """Structural artifacts can co-occur with real IRI entities (a partially
    flattened but still-usable file); such a graph is NOT refused."""
    q = _fake_query(structural=5, entities=42)
    report = lossy_owlxml_report("urn:ontology:hybrid:v1", query=q)
    assert report is None


def test_detector_failure_never_blocks_ingest():
    """A detector error must return None (fail open), never raise into the
    ingest pipeline."""
    def boom(_sparql):
        raise RuntimeError("oxigraph unreachable")

    assert lossy_owlxml_report("urn:ontology:x:v1", query=boom) is None


def test_exception_is_a_plain_exception():
    """LossyOwlXmlIngest is a terminal error type the ingest task matches on."""
    assert issubclass(LossyOwlXmlIngest, Exception)


def test_ingest_task_treats_lossy_as_terminal_no_retry(monkeypatch):
    """Regression guard for the wiring: when the pipeline raises LossyOwlXmlIngest,
    `ingest_ontology` must re-raise it WITHOUT retrying — exactly like
    OntologyAccessDenied. A reorder of the except clauses, or dropping
    LossyOwlXmlIngest from the terminal tuple, would make this fail (it would
    instead be swallowed into self.retry)."""
    from ontoexplorer.modules.jobs import tasks

    async def _raise_lossy(*_a, **_k):
        raise LossyOwlXmlIngest("flattened dump")

    # Replace the pipeline body so no real infra is touched; the task's own
    # try/except is what's under test.
    monkeypatch.setattr(tasks, "_ingest_tracked", _raise_lossy)

    retried = {"called": False}

    def _retry(*_a, **_k):
        retried["called"] = True
        raise AssertionError("ingest_ontology retried a terminal lossy ingest")

    monkeypatch.setattr(type(tasks.ingest_ontology), "retry", _retry, raising=False)

    with pytest.raises(LossyOwlXmlIngest):
        tasks.ingest_ontology(raw_bytes_hex=b"<rdf/>".hex())
    assert retried["called"] is False
