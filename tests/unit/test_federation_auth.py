"""Unit tests for the shared federation auth helpers (secret resolution,
host-pinned auth attachment, peer lookup by host)."""

from __future__ import annotations

import json

import httpx
import pytest

from ontoexplorer.config import get_settings
from ontoexplorer.modules.federation.auth import apply_auth, peer_for_host, resolve_secret
from ontoexplorer.modules.federation.config import PeerAuth

PEER_HOST = "peer.test"


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    """get_settings() is @lru_cache'd; drop the cache so monkeypatched env applies."""
    for k in ("FEDERATION_PEERS_JSON", "K"):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure(monkeypatch, *bases: str) -> None:
    peers = [
        {"id": f"p{i}", "label": f"P{i}", "base_url": base} for i, base in enumerate(bases)
    ]
    monkeypatch.setenv("FEDERATION_PEERS_JSON", json.dumps(peers))
    get_settings.cache_clear()


class TestResolveSecret:
    def test_none_auth(self):
        assert resolve_secret(None) is None

    def test_env_set(self, monkeypatch):
        monkeypatch.setenv("K", "s3cret")
        assert resolve_secret(PeerAuth(kind="apikey_param", secret_ref="K")) == "s3cret"

    def test_env_unset_returns_none(self):
        assert resolve_secret(PeerAuth(kind="apikey_param", secret_ref="K")) is None

    def test_env_empty_returns_none(self, monkeypatch):
        monkeypatch.setenv("K", "")
        assert resolve_secret(PeerAuth(kind="bearer", secret_ref="K")) is None


class TestApplyAuth:
    def test_apikey_attached_on_peer_host(self):
        auth = PeerAuth(kind="apikey_param", secret_ref="K", name="apikey")
        url = httpx.URL(f"https://{PEER_HOST}/x")
        out_url, out_headers = apply_auth(url, {}, auth, "s3cret", PEER_HOST)
        assert out_url.params["apikey"] == "s3cret"
        assert out_headers == {}

    def test_apikey_withheld_on_other_host(self):
        auth = PeerAuth(kind="apikey_param", secret_ref="K", name="apikey")
        url = httpx.URL("https://evil.test/x")
        out_url, out_headers = apply_auth(url, {}, auth, "s3cret", PEER_HOST)
        assert out_url == url
        assert "apikey" not in out_url.params
        assert out_headers == {}

    def test_bearer_header(self):
        auth = PeerAuth(kind="bearer", secret_ref="K")
        url = httpx.URL(f"https://{PEER_HOST}/x")
        out_url, out_headers = apply_auth(url, {"Accept": "a"}, auth, "s3cret", PEER_HOST)
        assert out_url == url
        assert out_headers == {"Accept": "a", "Authorization": "Bearer s3cret"}

    def test_bearer_withheld_on_other_host(self):
        auth = PeerAuth(kind="bearer", secret_ref="K")
        url = httpx.URL("https://evil.test/x")
        _, out_headers = apply_auth(url, {}, auth, "s3cret", PEER_HOST)
        assert "Authorization" not in out_headers

    def test_unchanged_when_no_secret(self):
        auth = PeerAuth(kind="apikey_param", secret_ref="K", name="apikey")
        url = httpx.URL(f"https://{PEER_HOST}/x")
        headers = {"Accept": "a"}
        out_url, out_headers = apply_auth(url, headers, auth, None, PEER_HOST)
        assert out_url == url
        assert out_headers == headers


class TestPeerForHost:
    def test_known_host(self, monkeypatch):
        _configure(monkeypatch, f"https://{PEER_HOST}")
        peer = peer_for_host(PEER_HOST)
        assert peer is not None and peer.id == "p0"

    def test_case_insensitive(self, monkeypatch):
        _configure(monkeypatch, "https://Peer.Test")
        assert peer_for_host("PEER.test") is not None

    def test_picks_matching_peer(self, monkeypatch):
        _configure(monkeypatch, "https://a.test", "https://b.test:8443")
        peer = peer_for_host("b.test")
        assert peer is not None and peer.id == "p1"

    def test_unknown_host(self, monkeypatch):
        _configure(monkeypatch, f"https://{PEER_HOST}")
        assert peer_for_host("other.test") is None

    def test_none_and_empty_host(self, monkeypatch):
        _configure(monkeypatch, f"https://{PEER_HOST}")
        assert peer_for_host(None) is None
        assert peer_for_host("") is None
