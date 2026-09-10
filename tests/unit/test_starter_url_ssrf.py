"""The SPARQL starter-library importer refuses internal fetch targets.

Before the shared guard, _fetch_starter_url allowed https:// to any host and
http:// to localhost — the api pod's own loopback. It is admin-only, but a
second confirmed-class SSRF surface, so it must reject internal targets the same
way ingestion does.
"""
import pytest

from ontoexplorer.api import sparql_queries
from ontoexplorer.clients import fetch_guard
from ontoexplorer.clients.fetch_guard import SsrfBlocked
from ontoexplorer.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _point_async_dns_at(monkeypatch, ip):
    async def resolve(host, port):
        return [ip]
    monkeypatch.setattr(fetch_guard, "_default_async_resolver", resolve)


@pytest.mark.anyio
async def test_starter_url_refuses_loopback(monkeypatch):
    _point_async_dns_at(monkeypatch, "127.0.0.1")
    with pytest.raises(SsrfBlocked):
        await sparql_queries._fetch_starter_url("http://localhost:8000/api/v1/ontologies")


@pytest.mark.anyio
async def test_starter_url_refuses_internal_https(monkeypatch):
    _point_async_dns_at(monkeypatch, "10.0.0.7")
    with pytest.raises(SsrfBlocked):
        await sparql_queries._fetch_starter_url("https://kubernetes.default.svc/api")
