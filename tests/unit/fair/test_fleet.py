"""Pure fleet aggregation over per-version FAIR reports."""
from ontoexplorer.modules.fair.fleet import aggregate_fleet
from ontoexplorer.modules.fair.score import FairInputs, compute_fair_report


def _strong():
    return compute_fair_report(FairInputs(
        ontology_iri="http://ex.org/o", resolvable=True,
        resolve_content_type="text/turtle", version_iri="http://ex.org/o/1",
        shortname="o", groups=["bioportal"], license_raw="CC BY", license_spdx="CC-BY-4.0",
        license_compliant=True,
        owl_profile={"language": {"tier": "OWL"}, "dl": {"in_profile": True}},
        reuse={"term_iri_reuse": {"skos": {}}, "imports": [{"target_prefix": "skos"}]},
        coverage={"by_type": {"class": {"total": 100, "with_label": 100, "with_definition": 100}}},
        meta_resolved={"title": "t", "description": "d", "creators": ["c"], "created": "2020",
                       "publishers": ["p"], "prefix": "o"},
    ))


def _weak():
    return compute_fair_report(FairInputs())


def test_histogram_sums_to_n_and_keys_present():
    reports = [_strong(), _strong(), _weak()]
    agg = aggregate_fleet(reports)
    assert agg["n"] == 3
    assert sum(b["count"] for b in agg["overall_histogram"]) == 3
    assert set(agg["principle_means"]) == {"F", "A", "I", "R"}
    assert all(0.0 <= v <= 1.0 for v in agg["principle_means"].values())


def test_strong_lands_high_weak_lands_low():
    agg = aggregate_fleet([_strong(), _weak()])
    counts = {b["bucket"]: b["count"] for b in agg["overall_histogram"]}
    assert counts["85-100"] == 1 and counts["<50"] == 1


def test_check_pass_rate_covers_all_19_checks():
    agg = aggregate_fleet([_strong(), _weak()])
    assert len(agg["check_pass_rate"]) == 19
    rate = {c["id"]: c["rate"] for c in agg["check_pass_rate"]}
    assert rate["A3"] == 1.0          # platform guarantee always passes
    assert 0.0 <= rate["R6"] <= 1.0


def test_empty_fleet_no_division_error():
    agg = aggregate_fleet([])
    assert agg["n"] == 0
    assert sum(b["count"] for b in agg["overall_histogram"]) == 0
    assert agg["principle_means"]["F"] == 0.0
