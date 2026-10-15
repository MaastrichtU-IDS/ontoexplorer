"""Static guards for the entity_index HASH-partition migration (e3b1c7a9d2f4).

The migration itself is PostgreSQL-only (partitioning + GIN) and never runs against
the SQLite test DB, so these tests verify its *definition* rather than execute it:

- the backfill column list is EXACTLY the EntityIndex model's columns (a dropped or
  mistyped column would silently lose data on backfill),
- the full canonical index set is recreated (no search path regresses),
- it chains onto the right revision and partitions by version_id.
"""
import importlib.util
from pathlib import Path

import pytest

from ontoexplorer.models.db import EntityIndex

_MIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "e3b1c7a9d2f4_partition_entity_index_by_version.py"
)

# Every index that currently exists on entity_index, minus the primary key (which the
# migration builds via ADD CONSTRAINT ... PRIMARY KEY, not the _INDEXES list).
_EXPECTED_NON_PK_INDEXES = {
    "entity_index_tsv",
    "entity_index_norm_trgm",
    "entity_index_norm_c",
    "entity_index_norm_prefix",
    "ix_entity_index_lower_label",
    "ix_entity_index_short",
    "ix_entity_index_individuals",
    "ix_entity_index_roots",
    "entity_index_ontology",
    "entity_index_version",
}


@pytest.fixture(scope="module")
def mig():
    spec = importlib.util.spec_from_file_location("_ei_partition_mig", _MIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain(mig):
    assert mig.revision == "e3b1c7a9d2f4"
    assert mig.down_revision == "a7c3e9d1f0b2"


def test_backfill_columns_match_model_exactly(mig):
    """The copied columns must be precisely the model's columns — no more (would fail to
    insert), no fewer (would silently drop data). search_tsv is generated and excluded."""
    copied = {c.strip() for c in mig._COLS.split(",")}
    model_cols = {c.name for c in EntityIndex.__table__.columns}
    assert copied == model_cols
    assert "search_tsv" not in copied  # generated, must never be in the INSERT list


def test_all_indexes_recreated(mig):
    names = {canonical for canonical, _ in mig._INDEXES}
    assert names == _EXPECTED_NON_PK_INDEXES
    # both GINs must be present and typed as GIN
    gin_bodies = {c: body for c, body in mig._INDEXES}
    assert "USING gin" in gin_bodies["entity_index_tsv"]
    assert "USING gin" in gin_bodies["entity_index_norm_trgm"]


def test_partitioned_by_version_id_mod_64(mig):
    assert mig._PARTITIONS == 64


def test_non_postgres_is_a_noop(mig, monkeypatch):
    """On SQLite (and anything non-PG) upgrade/downgrade must return without emitting DDL."""
    emitted = []

    class _FakeDialect:
        name = "sqlite"

    class _FakeBind:
        dialect = _FakeDialect()

    monkeypatch.setattr(mig.op, "get_bind", lambda: _FakeBind())
    monkeypatch.setattr(mig.op, "execute", lambda *a, **k: emitted.append(a))
    mig.upgrade()
    mig.downgrade()
    assert emitted == []
