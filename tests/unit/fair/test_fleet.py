"""Pure fleet aggregation over per-version FAIR scores (mean + stddev)."""
import math

from ontoexplorer.modules.fair.fleet import (
    FairScores,
    aggregate_fair_scores,
    scores_from_report,
)
from ontoexplorer.modules.fair.score import FairInputs, compute_fair_report


def _strong() -> FairScores:
    return scores_from_report(compute_fair_report(FairInputs(
        ontology_iri="http://ex.org/o", resolvable=True,
        resolve_content_type="text/turtle", version_iri="http://ex.org/o/1",
        shortname="o", groups=["bioportal"], license_raw="CC BY", license_spdx="CC-BY-4.0",
        license_compliant=True,
        owl_profile={"language": {"tier": "OWL"}, "dl": {"in_profile": True}},
        reuse={"term_iri_reuse": {"skos": {}}, "imports": [{"target_prefix": "skos"}]},
        coverage={"by_type": {"class": {"total": 100, "with_label": 100, "with_definition": 100}}},
        meta_resolved={"title": "t", "description": "d", "creators": ["c"], "created": "2020",
                       "publishers": ["p"], "prefix": "o"},
    )))


def _weak() -> FairScores:
    return scores_from_report(compute_fair_report(FairInputs()))


def test_histogram_sums_to_n_and_keys_present():
    agg = aggregate_fair_scores([_strong(), _strong(), _weak()])
    assert agg["n"] == 3
    assert sum(b["count"] for b in agg["overall_histogram"]) == 3
    assert set(agg["principle_means"]) == {"F", "A", "I", "R"}
    assert set(agg["principle_stddevs"]) == {"F", "A", "I", "R"}
    assert all(0.0 <= v <= 1.0 for v in agg["principle_means"].values())


def test_strong_lands_high_weak_lands_low():
    agg = aggregate_fair_scores([_strong(), _weak()])
    counts = {b["bucket"]: b["count"] for b in agg["overall_histogram"]}
    assert counts["85-100"] == 1 and counts["<50"] == 1


def test_overall_mean_and_stddev():
    strong, weak = _strong(), _weak()
    agg = aggregate_fair_scores([strong, weak])
    expect_mean = (strong.overall + weak.overall) / 2
    expect_std = math.sqrt(((strong.overall - expect_mean) ** 2 + (weak.overall - expect_mean) ** 2) / 2)
    assert agg["overall_mean"] == round(expect_mean, 4)
    assert agg["overall_stddev"] == round(expect_std, 4)


def test_stddev_zero_when_identical():
    agg = aggregate_fair_scores([_strong(), _strong(), _strong()])
    assert agg["overall_stddev"] == 0.0
    assert all(v == 0.0 for v in agg["principle_stddevs"].values())


def test_check_pass_rate_covers_all_19_checks():
    agg = aggregate_fair_scores([_strong(), _weak()])
    assert len(agg["check_pass_rate"]) == 19
    rate = {c["id"]: c["rate"] for c in agg["check_pass_rate"]}
    assert rate["A3"] == 1.0          # platform guarantee always passes
    assert 0.0 <= rate["R6"] <= 1.0
    # per-check metadata (principle, name) is carried even though scores are cached
    by_id = {c["id"]: c for c in agg["check_pass_rate"]}
    assert by_id["A1"]["principle"] == "A" and by_id["A1"]["name"]


def test_empty_fleet_no_division_error():
    agg = aggregate_fair_scores([])
    assert agg["n"] == 0
    assert sum(b["count"] for b in agg["overall_histogram"]) == 0
    assert agg["principle_means"]["F"] == 0.0
    assert agg["overall_mean"] == 0.0 and agg["overall_stddev"] == 0.0
