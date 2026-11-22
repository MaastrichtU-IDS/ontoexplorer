"""Cross-ontology MOS expression search (`GET /api/v1/search?mode=expression`).

The front-page MOS surface routes here instead of fanning a per-ontology request
across the whole catalogue. These cover the params that route added:
  * the relation-requires-named-class guard (400, not silently empty),
  * relation/direct/ontology_ids passthrough + scoping,
  * the versions_skipped_unclassified warning (the honest replacement for the old
    misleading "'<q>' not found in this ontology's index").
"""
import uuid
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import EntityIndex, Ontology, OntologyVersion
from ontoexplorer.modules.search.indexer import normalise_label
from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache

_FAKE_REDIS = fakeredis.FakeRedis(decode_responses=True)


async def _async_empty(pairs):
    return set()


async def _ready_version(db, label_iris: list[tuple[str, str]]):
    uid = uuid.uuid4().hex[:8]
    o = Ontology(id=uuid.uuid4().hex, iri=f"http://ex/o-{uid}", shortname=f"o{uid}", title="O")
    db.add(o)
    await db.flush()
    v = OntologyVersion(id=uuid.uuid4().hex, ontology_id=o.id, minio_key=f"k-{uid}",
                        sha256=f"s-{uid}", format="owl", status="ready", reasoner="rustdl")
    db.add(v)
    for label, iri in label_iris:
        db.add(EntityIndex(
            version_id=v.id, ontology_id=o.id, iri=iri, type="class",
            primary_label=label, primary_label_norm=normalise_label(label),
            short=iri.split("/")[-1], source="", search_text=label))
    await db.commit()
    # latest_ready_versions is process-cached; drop it so this fresh version is seen.
    invalidate_latest_ready_versions_cache()
    return o, v


@pytest.mark.anyio
async def test_global_expression_superclasses_requires_named_class(client, db_session):
    """A complex expression with relation=superclasses is rejected up-front (400),
    not silently empty from every ontology."""
    await _ready_version(db_session, [("cell death", "http://ex/CD"), ("nucleus", "http://ex/N")])
    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/search",
            params={"q": "'cell death' and 'nucleus'", "mode": "expression", "relation": "superclasses"},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "relation_requires_named_class"


@pytest.mark.anyio
async def test_global_expression_skips_unclassified_and_scopes(client, db_session):
    """A term that resolves in an un-reasoned ontology yields no results but an
    honest versions_skipped_unclassified warning — and ontology_ids scoping plus
    relation/direct are accepted without error."""
    o, _v = await _ready_version(db_session, [("cell death", "http://ex/CD")])
    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.clients.reasoning.filter_already_classified", new=_async_empty):
        resp = await client.get(
            "/api/v1/search",
            params={"q": "'cell death'", "mode": "expression",
                    "relation": "subclasses", "direct": "true", "ontology_ids": o.id},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "expression"
    assert body["results"] == []
    skipped = next((w for w in body.get("warnings", []) if w["type"] == "versions_skipped_unclassified"), None)
    assert skipped and skipped["count"] == 1
