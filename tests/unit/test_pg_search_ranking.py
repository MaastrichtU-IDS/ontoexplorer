"""Ranking for the Stage-1 prefix search pool (pg_search).

Common prefixes like `cell` used to take seconds because the SQL sorted the
entire `LIKE 'cell%'` match set by LENGTH before LIMIT. The query now fetches a
bounded, index-ordered pool and ranks it in Python via `_rank_prefix_rows`:
exact label first, then shortest label, then alphabetical, deduped by IRI.
"""

from types import SimpleNamespace as Row

from ontoexplorer.modules.search.pg_search import _prefix_pool_size, _rank_prefix_rows


def _r(iri: str, norm: str) -> Row:
    return Row(iri=iri, primary_label_norm=norm)


def test_exact_match_ranks_first():
    rows = [_r("i1", "cellular"), _r("i2", "cell"), _r("i3", "cell membrane")]
    out = _rank_prefix_rows(rows, "cell", 10)
    assert out[0].primary_label_norm == "cell"


def test_shorter_label_beats_alphabetically_earlier_longer():
    # The behaviour the LENGTH sort was written for: `membran` should surface
    # "membrane" over the alphabetically-earlier but longer "membrana tympaniformis".
    rows = [_r("i1", "membrana tympaniformis"), _r("i2", "membrane")]
    out = _rank_prefix_rows(rows, "membran", 10)
    assert [r.primary_label_norm for r in out] == ["membrane", "membrana tympaniformis"]


def test_full_tiered_order():
    rows = [
        _r("i1", "cellular"),        # len 8
        _r("i2", "cell"),            # exact
        _r("i3", "cell membrane"),   # len 13
        _r("i4", "cells"),           # len 5
    ]
    out = _rank_prefix_rows(rows, "cell", 10)
    assert [r.primary_label_norm for r in out] == ["cell", "cells", "cellular", "cell membrane"]


def test_dedup_by_iri_first_seen_wins():
    rows = [_r("dup", "cell"), _r("dup", "cell"), _r("x", "cells")]
    out = _rank_prefix_rows(rows, "cell", 10)
    assert [r.iri for r in out] == ["dup", "x"]


def test_respects_limit():
    rows = [_r(f"i{i}", f"cell{i}") for i in range(20)]
    assert len(_rank_prefix_rows(rows, "cell", 5)) == 5


def test_ties_break_alphabetically_then_by_iri():
    # Same tier + same length → alphabetical by norm, then IRI.
    rows = [_r("b", "cebb"), _r("a", "ceba"), _r("a2", "ceba")]
    out = _rank_prefix_rows(rows, "ce", 10)
    assert [(r.primary_label_norm, r.iri) for r in out] == [("ceba", "a"), ("ceba", "a2"), ("cebb", "b")]


def test_pool_size():
    assert _prefix_pool_size(20) == 500   # floor
    assert _prefix_pool_size(50) == 1000  # limit * 20
