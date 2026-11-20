"""Documentation-coverage breakdown by provenance (display-only companion to
the FAIR R5/R6 native metric)."""
from types import SimpleNamespace

from ontoexplorer.modules.search.coverage import _assemble_documentation


def _row(src, total, wl, wd):
    return SimpleNamespace(src=src, total=total, with_label=wl, with_definition=wd)


def test_native_external_and_all_totals():
    out = _assemble_documentation([
        _row("", 36, 36, 36),          # own terms, fully documented
        _row("dcterms", 10, 10, 2),    # reused vocabulary
        _row("foaf", 4, 4, 0),
    ])
    assert out["native"] == {"total": 36, "with_label": 36, "with_definition": 36}
    assert out["external"] == {"total": 14, "with_label": 14, "with_definition": 2}
    assert out["all"] == {"total": 50, "with_label": 50, "with_definition": 38}


def test_by_source_sorted_desc_and_excludes_native():
    out = _assemble_documentation([
        _row("foaf", 4, 4, 0),
        _row("", 36, 36, 36),
        _row("dcterms", 10, 10, 2),
    ])
    assert [s["source"] for s in out["by_source"]] == ["dcterms", "foaf"]
    assert all(s["source"] != "" for s in out["by_source"])


def test_no_native_bucket_leaves_zeros():
    out = _assemble_documentation([_row("chebi", 5, 5, 5)])
    assert out["native"] == {"total": 0, "with_label": 0, "with_definition": 0}
    assert out["all"]["total"] == 5
