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
from ontoexplorer.modules.search.indexer import (
    _iri_key,
    _meta_key,
    _prefix_key,
    _type_key,
    normalise_label,
)


@pytest.fixture()
def fake_redis():
    """A FakeRedis instance shared across the OLS layer and the indexer.

    Patches every module that calls ``_get_redis()`` directly, including the
    autocomplete engine which re-imports the helper from ``indexer``.
    """
    r = fakeredis.FakeRedis(decode_responses=True)
    with (
        patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r),
        # autocomplete imports _get_redis from indexer at module-load time, so patch
        # the name in autocomplete's own namespace too.
        patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.ontologies._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.terms._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.properties._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.individuals._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.classes_v2._get_redis", return_value=r),
        patch("ontoexplorer.api.ols.widgets._get_redis", return_value=r),
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
            "source": ontology.shortname,
            "labels": json.dumps([{"value": "Foo", "lang": "en"}]),
            "synonyms": json.dumps([]),
            "definitions": json.dumps([]),
        },
    )
    # Register in type set for list endpoint
    fake_redis.sadd(_type_key(vid, "class"), iri)
    # Populate prefix sorted-set so entity_lookup("Foo") returns this entity
    fake_redis.zadd(_prefix_key(vid), {f"{normalise_label('Foo')}|en|class|{iri}": 0})

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


@pytest.fixture()
async def sample_property(db_session, sample_ontology, fake_redis):
    """Seed one each of object_property, data_property, and annotation_property.

    Uses the same ontology + version created by sample_ontology.
    Seeded entities have a `parents` field of [] so the hierarchy fallback
    (Redis-first, then SPARQL) can return empty without needing Oxigraph.
    """
    from sqlalchemy import select

    ontology = sample_ontology
    result = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == ontology.id)
    )
    ver = result.scalar_one()
    vid = str(ver.id)

    obj_iri  = "http://example.org/testonto#hasRelation"
    data_iri = "http://example.org/testonto#hasValue"
    ann_iri  = "http://example.org/testonto#hasComment"

    def _seed(iri: str, label: str, prop_type: str):
        fake_redis.hset(
            _iri_key(vid, iri),
            mapping={
                "iri":           iri,
                "primary_label": label,
                "label":         label,
                "short":         label,
                "type":          prop_type,
                "source": ontology.shortname,
                "labels":        json.dumps([{"value": label, "lang": "en"}]),
                "synonyms":      json.dumps([]),
                "definitions":   json.dumps([]),
                "parents":       json.dumps([]),
            },
        )
        fake_redis.sadd(_type_key(vid, prop_type), iri)
        # Populate prefix sorted-set so entity_lookup can find this entity
        fake_redis.zadd(
            _prefix_key(vid),
            {f"{normalise_label(label)}|en|{prop_type}|{iri}": 0},
        )

    _seed(obj_iri,  "hasRelation", "object_property")
    _seed(data_iri, "hasValue",    "data_property")
    _seed(ann_iri,  "hasComment",  "annotation_property")

    yield {
        "obj_iri":    obj_iri,
        "data_iri":   data_iri,
        "ann_iri":    ann_iri,
        "ontology":   ontology,
        "version_id": vid,
    }


@pytest.fixture()
async def property_hierarchy(db_session, fake_redis):
    """Seed a three-level object_property hierarchy: GrandProp ← ParentProp ← ChildProp.

    Entity hashes include a `parents` JSON field so that the asserted-fallback
    path can resolve relationships without Oxigraph.
    """
    uid = uuid.uuid4().hex[:8]
    ont = Ontology(
        iri=f"http://example.org/prophier-{uid}.owl",
        shortname=f"prophier{uid}",
        title="Property Hierarchy Test Ontology",
    )
    db_session.add(ont)
    await db_session.flush()

    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"prophier/test-{uid}.owl",
        sha256=f"prophier_sha256_{uid}",
        format="owl",
        status="ready",
        version_iri="2025-01-01",
    )
    db_session.add(ver)
    await db_session.commit()

    vid = str(ver.id)
    fake_redis.hset(
        _meta_key(ver.id),
        mapping={
            "class_count": "0",
            "property_count": "3",
            "individual_count": "0",
            "schema_version": "v2",
            "indexed_at": "2025-01-01T00:00:00+00:00",
        },
    )

    gp_iri     = "http://example.org/prophier#GrandProp"
    parent_iri = "http://example.org/prophier#ParentProp"
    child_iri  = "http://example.org/prophier#ChildProp"

    def _seed(iri: str, label: str, parents: list):
        fake_redis.hset(
            _iri_key(vid, iri),
            mapping={
                "iri":           iri,
                "primary_label": label,
                "label":         label,
                "short":         label,
                "type":          "object_property",
                "source":        ont.shortname,
                "labels":        json.dumps([{"value": label, "lang": "en"}]),
                "synonyms":      json.dumps([]),
                "definitions":   json.dumps([]),
                "parents":       json.dumps(parents),
            },
        )
        fake_redis.sadd(_type_key(vid, "object_property"), iri)

    _seed(gp_iri,     "GrandProp",  [])
    _seed(parent_iri, "ParentProp", [gp_iri])
    _seed(child_iri,  "ChildProp",  [parent_iri])

    yield {
        "ontology":   ont,
        "version_id": vid,
        "gp_iri":     gp_iri,
        "parent_iri": parent_iri,
        "child_iri":  child_iri,
    }


@pytest.fixture()
async def sample_individual(db_session, sample_ontology, fake_redis):
    """Seed one individual entity and one class it is rdf:type of into Redis.

    The individual hash carries a ``types`` JSON field (list of class IRIs) so
    the /types endpoint can resolve classes without needing Oxigraph in tests.
    The class entity is also seeded so the response shape carries a real label.
    """
    from sqlalchemy import select

    ontology = sample_ontology
    result = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == ontology.id)
    )
    ver = result.scalar_one()
    vid = str(ver.id)

    ind_iri   = "http://example.org/testonto#Alice"
    class_iri = "http://example.org/testonto#Person"

    # Seed the individual with a `types` field listing its rdf:type classes
    fake_redis.hset(
        _iri_key(vid, ind_iri),
        mapping={
            "iri":           ind_iri,
            "primary_label": "Alice",
            "label":         "Alice",
            "short":         "Alice",
            "type":          "individual",
            "source": ontology.shortname,
            "labels":        json.dumps([{"value": "Alice", "lang": "en"}]),
            "synonyms":      json.dumps([]),
            "definitions":   json.dumps([]),
            "types":         json.dumps([class_iri]),
        },
    )
    fake_redis.sadd(_type_key(vid, "individual"), ind_iri)
    fake_redis.zadd(_prefix_key(vid), {f"{normalise_label('Alice')}|en|individual|{ind_iri}": 0})

    # Seed the class entity so /types can return a fully shaped class
    fake_redis.hset(
        _iri_key(vid, class_iri),
        mapping={
            "iri":           class_iri,
            "primary_label": "Person",
            "label":         "Person",
            "short":         "Person",
            "type":          "class",
            "source": ontology.shortname,
            "labels":        json.dumps([{"value": "Person", "lang": "en"}]),
            "synonyms":      json.dumps([]),
            "definitions":   json.dumps([]),
        },
    )
    fake_redis.sadd(_type_key(vid, "class"), class_iri)
    fake_redis.zadd(_prefix_key(vid), {f"{normalise_label('Person')}|en|class|{class_iri}": 0})

    yield {
        "ind_iri":    ind_iri,
        "class_iri":  class_iri,
        "ontology":   ontology,
        "version_id": vid,
    }
