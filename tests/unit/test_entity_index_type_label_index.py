"""The keyset index backing /entities listing must exist and match the sort key."""
from ontoexplorer.models.db import EntityIndex


def test_type_label_index_declared():
    names = {ix.name for ix in EntityIndex.__table__.indexes}
    assert "ix_entity_index_type_label" in names
    ix = next(ix for ix in EntityIndex.__table__.indexes if ix.name == "ix_entity_index_type_label")
    cols = [c.name for c in ix.columns]
    assert cols == ["type", "primary_label_norm", "iri", "version_id"]
