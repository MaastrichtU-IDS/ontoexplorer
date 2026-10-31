"""The /browse keyset query relies on ix_entity_index_browse. Verify the migration
creates it on entity_index and drops it again (SQLite test DB; the migration is
plain op.create_index so it is dialect-neutral)."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_MIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "b5d8e2f1a9c3_entity_index_browse_keyset.py"
)


def _load_mig():
    spec = importlib.util.spec_from_file_location("_ei_browse_mig", _MIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_names(conn) -> set[str]:
    return {ix["name"] for ix in sa.inspect(conn).get_indexes("entity_index")}


def test_browse_index_upgrade_and_downgrade():
    mig = _load_mig()
    assert mig.revision == "b5d8e2f1a9c3"
    assert mig.down_revision == "a4c7e1b9d205"

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE entity_index (version_id TEXT, iri TEXT, type TEXT, "
            "primary_label_norm TEXT, PRIMARY KEY (version_id, iri))"
        ))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        cols = [ix["column_names"] for ix in sa.inspect(conn).get_indexes("entity_index")
                if ix["name"] == "ix_entity_index_browse"]
        assert cols == [["type", "primary_label_norm", "iri", "version_id"]]

        with Operations.context(ctx):
            mig.downgrade()
        assert "ix_entity_index_browse" not in _index_names(conn)
    engine.dispose()
