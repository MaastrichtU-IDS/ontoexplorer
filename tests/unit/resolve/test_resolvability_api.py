from datetime import datetime, timezone
from types import SimpleNamespace

from ontoexplorer.api.ontologies import _LIST_VIEW_FIELDS, _ontology_dict


def _onto(**over):
    base = dict(
        id="o1", iri="https://w3id.org/x/", shortname="x", title="X", groups=[],
        auto_sync=False, current_version_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        resolvable=True, resolve_checked_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        resolve_detail={},
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_ontology_dict_includes_resolvability():
    d = _ontology_dict(_onto(), None)
    assert d["resolvable"] is True
    assert d["resolve_checked_at"] == "2026-10-09T00:00:00+00:00"


def test_ontology_dict_resolvability_defaults_none():
    d = _ontology_dict(_onto(resolvable=None, resolve_checked_at=None), None)
    assert d["resolvable"] is None
    assert d["resolve_checked_at"] is None


def test_list_view_fields_include_resolvable():
    assert "resolvable" in _LIST_VIEW_FIELDS
