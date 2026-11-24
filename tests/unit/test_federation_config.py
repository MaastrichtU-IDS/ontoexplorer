import json
import logging

import pytest

from ontoexplorer.config import Settings, get_settings
from ontoexplorer.modules.federation.config import (
    Peer,
    PeerAuth,
    get_federation_peers,
    peer_host_allowlist,
)

PEERS = [
    {
        "id": "agroportal",
        "label": "AgroPortal",
        "base_url": "https://data.agroportal.lirmm.fr",
        "mod_path": "/mod-api",
        "adapter": "mod",
        "timeout_ms": 4000,
    },
    {
        "id": "bioportal",
        "label": "BioPortal",
        "base_url": "https://data.bioontology.org:8443",
        "adapter": "bioportal",
        "auth": {"kind": "apikey_param", "name": "apikey", "secret_ref": "BIOPORTAL_API_KEY"},
    },
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (
        "FEDERATION_ENABLED",
        "FEDERATION_PEERS_JSON",
    ):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_peers(monkeypatch, raw: str):
    monkeypatch.setenv("FEDERATION_PEERS_JSON", raw)
    get_settings.cache_clear()


def test_settings_defaults_off():
    s = Settings(_env_file=None)
    assert s.federation_enabled is False
    assert s.federation_peers_json == ""
    assert s.federation_fanout_timeout_ms > 0
    assert s.federation_cache_ttl_s >= 0
    assert s.federation_max_results_per_peer > 0
    assert s.federation_max_response_bytes > 0
    assert s.federation_max_redirects >= 0


def test_no_peers_configured_returns_empty():
    assert get_federation_peers() == []
    assert peer_host_allowlist() == frozenset()


def test_valid_json_parses_peers(monkeypatch):
    _set_peers(monkeypatch, json.dumps(PEERS))
    peers = get_federation_peers()
    assert [p.id for p in peers] == ["agroportal", "bioportal"]
    assert all(isinstance(p, Peer) for p in peers)
    a, b = peers
    assert a.label == "AgroPortal"
    assert a.base_url == "https://data.agroportal.lirmm.fr"
    assert a.mod_path == "/mod-api"
    assert a.adapter == "mod"
    assert a.timeout_ms == 4000
    assert a.auth is None
    assert b.adapter == "bioportal"
    assert b.timeout_ms > 0  # default applied
    assert isinstance(b.auth, PeerAuth)


def test_malformed_json_returns_empty_and_logs(monkeypatch, caplog):
    _set_peers(monkeypatch, "{not json")
    with caplog.at_level(logging.WARNING):
        assert get_federation_peers() == []
    assert any("federation" in r.message.lower() for r in caplog.records)


def test_non_list_json_returns_empty(monkeypatch, caplog):
    _set_peers(monkeypatch, '{"id": "x"}')
    with caplog.at_level(logging.WARNING):
        assert get_federation_peers() == []
    assert caplog.records


def test_invalid_peer_entry_skipped_others_kept(monkeypatch, caplog):
    bad = [{"id": "nourl"}, "str", {"id": "ftp", "base_url": "ftp://x.org"}, PEERS[0]]
    _set_peers(monkeypatch, json.dumps(bad))
    with caplog.at_level(logging.WARNING):
        peers = get_federation_peers()
    assert [p.id for p in peers] == ["agroportal"]
    assert caplog.records


def test_duplicate_ids_first_wins(monkeypatch):
    _set_peers(monkeypatch, json.dumps([PEERS[0], {**PEERS[1], "id": "agroportal"}]))
    peers = get_federation_peers()
    assert len(peers) == 1 and peers[0].label == "AgroPortal"


def test_host_allowlist_is_base_url_hosts(monkeypatch):
    _set_peers(monkeypatch, json.dumps(PEERS))
    assert peer_host_allowlist() == frozenset(
        {"data.agroportal.lirmm.fr", "data.bioontology.org"}
    )


def test_apikey_param_parses_secret_ref_without_embedding_secret(monkeypatch):
    monkeypatch.setenv("BIOPORTAL_API_KEY", "s3cr3t-value")
    _set_peers(monkeypatch, json.dumps(PEERS))
    b = get_federation_peers()[1]
    assert b.auth == PeerAuth(kind="apikey_param", name="apikey", secret_ref="BIOPORTAL_API_KEY")
    assert "s3cr3t-value" not in repr(b)
    assert "s3cr3t-value" not in repr(b.auth)


def test_invalid_auth_kind_skips_peer(monkeypatch):
    p = {**PEERS[1], "auth": {"kind": "magic", "secret_ref": "X"}}
    _set_peers(monkeypatch, json.dumps([p, PEERS[0]]))
    assert [x.id for x in get_federation_peers()] == ["agroportal"]
