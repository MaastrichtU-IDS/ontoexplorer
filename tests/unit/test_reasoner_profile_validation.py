"""_validate_reasoner_and_params enforces a profile's params against the
reasoner's advertised param_schema (from /reasoners)."""
import pytest

from ontoexplorer.api.admin import reasoner_profiles as rp

_CATALOG = [
    {"name": "rustdl", "param_schema": [
        {"key": "saturation_only", "type": "bool", "default": False},
        {"key": "per_pair_timeout_ms", "type": "int", "default": 200, "min": 0},
        {"key": "global_timeout_ms", "type": "int", "default": 60000, "min": 0},
    ]},
    {"name": "km", "param_schema": [
        {"key": "route", "type": "enum", "default": "auto", "choices": ["auto", "elc", "cb_plain16"]},
    ]},
    {"name": "rdflib", "param_schema": []},
]


def _patch(monkeypatch, catalog=_CATALOG, raise_=False):
    async def _list():
        if raise_:
            raise RuntimeError("reasoner-service down")
        return catalog
    monkeypatch.setattr(rp, "list_reasoners", _list)


async def _expect_ok(reasoner, params):
    await rp._validate_reasoner_and_params(reasoner, params)


async def _expect_422(reasoner, params):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await rp._validate_reasoner_and_params(reasoner, params)
    assert ei.value.status_code == 422


@pytest.mark.anyio
async def test_valid_rustdl_params(monkeypatch):
    _patch(monkeypatch)
    await _expect_ok("rustdl", {"saturation_only": True, "per_pair_timeout_ms": 500})


@pytest.mark.anyio
async def test_unknown_reasoner(monkeypatch):
    _patch(monkeypatch)
    await _expect_422("nope", {})


@pytest.mark.anyio
async def test_unknown_param(monkeypatch):
    _patch(monkeypatch)
    await _expect_422("rustdl", {"bogus": 1})


@pytest.mark.anyio
async def test_wrong_type_bool(monkeypatch):
    _patch(monkeypatch)
    await _expect_422("rustdl", {"saturation_only": 1})  # int, not bool


@pytest.mark.anyio
async def test_int_below_min(monkeypatch):
    _patch(monkeypatch)
    await _expect_422("rustdl", {"per_pair_timeout_ms": -5})


@pytest.mark.anyio
async def test_enum_bad_choice(monkeypatch):
    _patch(monkeypatch)
    await _expect_422("km", {"route": "made_up"})


@pytest.mark.anyio
async def test_enum_ok(monkeypatch):
    _patch(monkeypatch)
    await _expect_ok("km", {"route": "elc"})


@pytest.mark.anyio
async def test_service_unreachable_skips_validation(monkeypatch):
    # If the reasoner-service can't be reached, don't block admin edits.
    _patch(monkeypatch, raise_=True)
    await _expect_ok("anything", {"whatever": 123})
