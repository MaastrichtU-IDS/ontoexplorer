import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import registry


def test_reasoners_registered():
    names = {r.name for r in registry.list_reasoners()}
    assert {"rustdl", "konclude", "km"} <= names


def test_capabilities_are_correct():
    caps = {r.name: r.capabilities for r in registry.list_reasoners()}
    assert "justify" in caps["rustdl"]
    assert "justify" not in caps["konclude"]      # Konclude cannot explain
    assert "classify" in caps["konclude"]


def test_default_reasoner_env(monkeypatch):
    monkeypatch.delenv("DEFAULT_REASONER", raising=False)
    assert registry.default_reasoner() == "rustdl"
    monkeypatch.setenv("DEFAULT_REASONER", "rustdl")
    assert registry.default_reasoner() == "rustdl"


def test_unknown_backend_raises():
    with pytest.raises(KeyError):
        registry.get_backend("hermit")


def test_konclude_justify_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        registry.get_backend("konclude").justify("", "s", "o", 1)
