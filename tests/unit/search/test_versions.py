"""Unit tests for pin-aware, version-aware default-version selection."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ontoexplorer.modules.search.versions import _choose, _version_key

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _v(vid, version_iri, status="ready", created_offset=0):
    return SimpleNamespace(
        id=vid, version_iri=version_iri, status=status,
        created_at=BASE + timedelta(days=created_offset),
    )


def test_version_key_numeric_not_lexical():
    # 0.2.14 must rank above 0.2.2 and 0.2.12 (lexical string sort would fail).
    v14 = _v("a", "https://w3id.org/sulo/sulo-0.2.14.ttl")
    v2 = _v("b", "https://w3id.org/sulo/sulo-0.2.2.ttl")
    v12 = _v("c", "https://w3id.org/sulo/sulo-0.2.12.ttl")
    assert _version_key(v14) > _version_key(v12) > _version_key(v2)


def test_version_key_dated_iri():
    later = _v("a", "http://purl.obolibrary.org/obo/go/releases/2024-05-01/go.owl")
    earlier = _v("b", "http://purl.obolibrary.org/obo/go/releases/2024-01-01/go.owl")
    assert _version_key(later) > _version_key(earlier)


def test_choose_picks_highest_version_regardless_of_load_order():
    # 0.2.12 loaded most recently (created_offset=10) but 0.2.14 is newer by version.
    v14 = _v("v14", "sulo-0.2.14.ttl", created_offset=0)
    v12 = _v("v12", "sulo-0.2.12.ttl", created_offset=10)
    assert _choose([v12, v14], current_version_id=None).id == "v14"


def test_choose_pin_overrides_version_order():
    v14 = _v("v14", "sulo-0.2.14.ttl")
    v10 = _v("v10", "sulo-0.2.10.ttl")
    assert _choose([v14, v10], current_version_id="v10").id == "v10"


def test_choose_ignores_pin_when_not_ready_and_falls_back():
    v14 = _v("v14", "sulo-0.2.14.ttl")
    v10 = _v("v10", "sulo-0.2.10.ttl", status="deprecated")
    # Pin points at a deprecated version -> ignored, version-latest wins.
    assert _choose([v14, v10], current_version_id="v10").id == "v14"


def test_choose_excludes_non_ready_and_returns_none_when_empty():
    v = _v("v", "sulo-0.2.1.ttl", status="pending")
    assert _choose([v], current_version_id=None) is None


def test_choose_created_at_fallback_when_no_version_numbers():
    a = _v("a", "http://example.org/onto.owl", created_offset=0)   # no digits
    b = _v("b", "http://example.org/onto.owl", created_offset=5)
    assert _choose([a, b], current_version_id=None).id == "b"
