"""Reject an ingest that parses to zero triples (an empty fetch, not an ontology).

A source that loads no triples — an HTML landing page, an empty SPARQL
``describe``, a dead mirror — must be refused, not persisted as a ``needs_review``
draft the quality gate holds and update polling keeps recreating. These pin the
terminal (no-retry) task wiring for the guard.
"""
import pytest

from ontoexplorer.modules.ingestion.pipeline import EmptyIngest


def test_empty_ingest_is_a_terminal_exception():
    assert issubclass(EmptyIngest, Exception)


def test_ingest_task_treats_empty_as_terminal_no_retry(monkeypatch):
    """Wiring guard: when the pipeline raises EmptyIngest, ``ingest_ontology`` must
    re-raise it WITHOUT retrying — exactly like OntologyAccessDenied /
    LossyOwlXmlIngest. Dropping EmptyIngest from the terminal tuple would instead
    swallow it into ``self.retry``."""
    from ontoexplorer.modules.jobs import tasks

    async def _raise_empty(*_a, **_k):
        raise EmptyIngest("zero triples")

    # Replace the pipeline body so no real infra is touched; the task's own
    # try/except is what's under test.
    monkeypatch.setattr(tasks, "_ingest_tracked", _raise_empty)

    retried = {"called": False}

    def _retry(*_a, **_k):
        retried["called"] = True
        raise AssertionError("ingest_ontology retried a terminal empty ingest")

    monkeypatch.setattr(type(tasks.ingest_ontology), "retry", _retry, raising=False)

    with pytest.raises(EmptyIngest):
        tasks.ingest_ontology(raw_bytes_hex=b"<rdf/>".hex())
    assert retried["called"] is False
