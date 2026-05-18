from unittest.mock import MagicMock
from ontoexplorer.api.ols._envelope import hal_page, v2_page


def _mock_request(url: str = "http://api.example/ols/api/ontologies"):
    r = MagicMock()
    r.url = MagicMock()
    r.url.__str__.return_value = url
    r.query_params = {}
    return r


def test_hal_page_first_page():
    req = _mock_request()
    items = [{"a": 1}, {"a": 2}]
    out = hal_page(items, req, total=53, page=0, size=20, embedded_key="ontologies")
    assert out["_embedded"]["ontologies"] == items
    assert out["page"] == {"size": 20, "totalElements": 53, "totalPages": 3, "number": 0}
    # On first page there should be no "prev" link
    assert "prev" not in out["_links"]
    assert "next" in out["_links"]
    assert "first" in out["_links"]
    assert "last" in out["_links"]


def test_hal_page_last_page():
    req = _mock_request()
    out = hal_page([{"a": 1}], req, total=21, page=2, size=10, embedded_key="terms")
    assert out["page"]["totalPages"] == 3
    assert out["page"]["number"] == 2
    assert "next" not in out["_links"]
    assert "prev" in out["_links"]


def test_hal_page_empty():
    req = _mock_request()
    out = hal_page([], req, total=0, page=0, size=20, embedded_key="ontologies")
    assert out["_embedded"]["ontologies"] == []
    assert out["page"]["totalElements"] == 0
    assert out["page"]["totalPages"] == 0


def test_v2_page_flat_shape():
    req = _mock_request()
    out = v2_page([{"a": 1}], req, total=1, page=0, size=20)
    assert out["elements"] == [{"a": 1}]
    assert out["page"] == {"size": 20, "totalElements": 1, "totalPages": 1, "number": 0}
    assert out["facetFieldsToCounts"] == {}
    # v2 has no _links
    assert "_links" not in out
