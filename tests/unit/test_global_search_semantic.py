from fastapi.testclient import TestClient


def test_global_search_accepts_semantic_param():
    """semantic=true is accepted without 422 error (can return empty results)."""
    from ontoexplorer.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/search?q=heart&semantic=true")
        assert resp.status_code != 422, "Got 422: semantic param not recognized"
        assert resp.status_code in (200, 401, 403, 500)  # 500 = services unavailable, but param accepted


def test_ontology_search_accepts_semantic_param():
    from ontoexplorer.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/ontologies/go/search?q=heart&semantic=true")
        assert resp.status_code != 422, "Got 422: semantic param not recognized"
        assert resp.status_code in (200, 401, 403, 404, 500)


def test_per_version_search_accepts_semantic_param():
    from ontoexplorer.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/ontologies/go/v1/search?q=heart&semantic=true")
        assert resp.status_code != 422, "Got 422: semantic param not recognized"
        assert resp.status_code in (200, 401, 403, 404, 500)
