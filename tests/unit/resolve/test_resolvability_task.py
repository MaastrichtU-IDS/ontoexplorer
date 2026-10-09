import contextlib

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import Ontology
from ontoexplorer.modules.jobs.tasks import _apply_resolvability


class _Resp:
    def __init__(self, status, ct, url):
        self.status_code, self.headers, self.url = status, {"content-type": ct}, url


class _FakeClient:
    def __init__(self, resp): self._resp = resp
    def __enter__(self): return self
    def __exit__(self, *a): return False
    @contextlib.contextmanager
    def stream(self, *a, **k): yield self._resp


@pytest.mark.anyio
async def test_apply_resolvability_marks_true(db_session):
    o = Ontology(iri="https://w3id.org/sulo-rt/", shortname="sulo-rt", title="S")
    db_session.add(o); await db_session.commit()
    await _apply_resolvability(
        db_session, o.id,
        client_factory=lambda: _FakeClient(_Resp(200, "text/turtle", "https://x/sulo.ttl")),
    )
    got = (await db_session.execute(select(Ontology).where(Ontology.id == o.id))).scalar_one()
    assert got.resolvable is True
    assert got.resolve_checked_at is not None
    assert got.resolve_detail["http_status"] == 200


@pytest.mark.anyio
async def test_apply_resolvability_marks_false_for_html(db_session):
    o = Ontology(iri="https://example.org/o-rt", shortname="o-rt", title="O")
    db_session.add(o); await db_session.commit()
    await _apply_resolvability(
        db_session, o.id,
        client_factory=lambda: _FakeClient(_Resp(200, "text/html", "https://example.org/o")),
    )
    got = (await db_session.execute(select(Ontology).where(Ontology.id == o.id))).scalar_one()
    assert got.resolvable is False
