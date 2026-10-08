"""The OLS inferred-hierarchy fetchers must read ONE class's edges via targeted
per-IRI reasoner calls, NOT get_classification() (which loaded the whole
classification blob and OOM-killed the api pod on large ontologies — #282).

A reasoner error must fall back to the asserted edges, as before.
"""
from unittest.mock import AsyncMock, patch

import pytest

from ontoexplorer.api.ols import terms as _terms

VID = "v1"
IRI = "http://ex.org/A"


@pytest.mark.anyio
async def test_children_use_targeted_direct_subclasses():
    with patch("ontoexplorer.clients.reasoning.subclasses",
               new=AsyncMock(return_value={"subclasses": ["http://ex.org/B", "http://ex.org/C"]})) as sub, \
         patch("ontoexplorer.clients.reasoning.get_classification",
               new=AsyncMock(side_effect=AssertionError("must not load the full blob"))):
        out = await _terms._inferred_children_fetcher(None, "ont", VID, IRI)
    assert out == ["http://ex.org/B", "http://ex.org/C"]
    # one targeted, direct=True call — not the whole classification
    sub.assert_awaited_once()
    assert sub.await_args.kwargs.get("direct") is True


@pytest.mark.anyio
async def test_descendants_use_targeted_transitive_subclasses():
    with patch("ontoexplorer.clients.reasoning.subclasses",
               new=AsyncMock(return_value={"subclasses": ["http://ex.org/B"]})) as sub, \
         patch("ontoexplorer.clients.reasoning.get_classification",
               new=AsyncMock(side_effect=AssertionError("must not load the full blob"))):
        out = await _terms._inferred_descendants_fetcher(None, "ont", VID, IRI)
    assert out == ["http://ex.org/B"]
    assert sub.await_args.kwargs.get("direct") is False


@pytest.mark.anyio
async def test_parents_use_targeted_direct_superclasses():
    with patch("ontoexplorer.clients.reasoning.superclasses",
               new=AsyncMock(return_value={"superclasses": ["http://ex.org/P"]})) as sup, \
         patch("ontoexplorer.clients.reasoning.get_classification",
               new=AsyncMock(side_effect=AssertionError("must not load the full blob"))):
        out = await _terms._inferred_parents_fetcher(None, "ont", VID, IRI)
    assert out == ["http://ex.org/P"]
    assert sup.await_args.kwargs.get("direct") is True


@pytest.mark.anyio
async def test_reasoner_error_falls_back_to_asserted():
    with patch("ontoexplorer.clients.reasoning.subclasses",
               new=AsyncMock(side_effect=RuntimeError("reasoner down"))), \
         patch("ontoexplorer.api.ols.terms._asserted_children",
               new=AsyncMock(return_value=["http://ex.org/asserted"])) as fallback:
        out = await _terms._inferred_children_fetcher(None, "ont", VID, IRI)
    assert out == ["http://ex.org/asserted"]
    fallback.assert_awaited_once()
