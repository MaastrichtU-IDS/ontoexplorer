"""The reasoner column exists, is NOT NULL, and defaults to whelk."""
import sqlalchemy as sa
from ontoexplorer.models.db import OntologyVersion


def test_model_has_reasoner_default():
    col = OntologyVersion.__table__.c.reasoner
    assert col.nullable is False
    assert col.server_default is not None
    assert "whelk" in str(col.server_default.arg)
