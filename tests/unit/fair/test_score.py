"""Pure FAIR scorer: the check matrix from the plan's Review Focus."""
from ontoexplorer.modules.fair.score import (
    R4_EXCLUDED_ROLES,
    FairInputs,
    compute_fair_report,
)
from ontoexplorer.modules.meta_profile.registry import ALL_META_ROLES, ROLE_RESOLVED_KEY

EXPECTED_IDS = {"F1", "F2", "F3", "F4", "F5", "F6",
                "A1", "A2", "A3",
                "I1", "I2", "I3", "I4",
                "R1", "R2", "R3", "R4", "R5", "R6"}

FILLED_ROLES = [
    "title", "shortname", "description", "creator", "contributor", "publisher",
    "license", "homepage", "version_info", "version_iri", "prefix", "namespace_uri",
    "created", "modified", "language", "citation", "see_also", "is_defined_by",
]  # 18 of the 21 scored roles (funding/status/syntax left empty)


def _meta(filled_roles):
    return {ROLE_RESOLVED_KEY[r]: (["x"] if r in {"creator", "contributor", "publisher", "see_also"} else "x")
            for r in filled_roles}


def _full_inputs(**over):
    base = dict(
        ontology_iri="http://semanticscience.org/ontology/sio.owl",
        resolvable=True,
        resolve_detail={"content_type": "text/turtle"},
        version_iri="http://semanticscience.org/ontology/sio/release/1.62",
        shortname="sio",
        groups=["bioportal"],
        license_raw="CC BY 4.0",
        license_spdx="CC-BY-4.0",
        license_compliant=True,
        owl_profile={"language": {"tier": "OWL"}, "dl": {"in_profile": True},
                     "el": {"in_profile": False}, "ql": {"in_profile": False}, "rl": {"in_profile": False}},
        reuse={"term_iri_reuse": {"dcterms": {}, "skos": {}}, "imports": [],
               "mappings": {"skos:exactMatch": [1, 2]}, "mireot_terms": []},
        coverage={"by_type": {"class": {"total": 2724, "with_label": 2698, "with_definition": 2261}}},
        meta_resolved=_meta(FILLED_ROLES),
    )
    base.update(over)
    # build_fair_inputs expects resolve_detail; pass through the raw signal values
    from ontoexplorer.modules.fair.score import build_fair_inputs
    return build_fair_inputs(**base)


def _by_id(report):
    return {c.id: c for p in report.principles for c in p.checks}


def test_full_report_has_19_checks_and_strong_overall():
    rep = compute_fair_report(_full_inputs())
    checks = _by_id(rep)
    assert set(checks) == EXPECTED_IDS
    assert rep.n_checks == 19
    assert rep.overall > 0.9 and rep.verdict == "Strong FAIRness"


def test_principle_score_is_mean_of_its_checks():
    rep = compute_fair_report(_full_inputs())
    for p in rep.principles:
        assert abs(p.score - sum(c.score for c in p.checks) / len(p.checks)) < 1e-9


def test_tier_only_profile_scores_i2_partial():
    rep = compute_fair_report(_full_inputs(
        owl_profile={"language": {"tier": "OWL"}, "profiles_unavailable": True}))
    checks = _by_id(rep)
    assert checks["I1"].status == "pass"
    assert checks["I2"].status == "partial" and checks["I2"].score == 0.5


def test_license_present_but_not_compliant_r2_partial():
    rep = compute_fair_report(_full_inputs(license_spdx="CC-BY-NC-4.0", license_compliant=False))
    checks = _by_id(rep)
    assert checks["R1"].status == "pass"          # license present
    assert checks["R2"].status == "partial"       # present but not compliant


def _meta_with_license(url):
    m = _meta(FILLED_ROLES)
    m["license"] = url   # the resolved key for the license role
    return m


def test_r1_r2_fall_back_to_resolved_meta_license():
    # license_raw-extraction gap: the index task missed the license (ontology-IRI
    # subject mismatch), so the version columns are empty — but the meta-profile
    # resolver found CC0. FAIR must read the resolved value, not under-report.
    rep = compute_fair_report(_full_inputs(
        license_raw="", license_spdx=None, license_compliant=False,
        meta_resolved=_meta_with_license("https://creativecommons.org/publicdomain/zero/1.0")))
    checks = _by_id(rep)
    assert checks["R1"].status == "pass"            # resolved CC0 → license present
    assert checks["R2"].status == "pass"            # CC0 canonicalizes + on allowlist
    assert "CC0-1.0" in checks["R2"].evidence


def test_r2_resolved_noncompliant_license_is_partial():
    # Resolved license recognized but NonCommercial → present (R1) yet not compliant (R2).
    rep = compute_fair_report(_full_inputs(
        license_raw="", license_spdx=None, license_compliant=False,
        meta_resolved=_meta_with_license("http://creativecommons.org/licenses/by-nc/4.0/")))
    checks = _by_id(rep)
    assert checks["R1"].status == "pass"
    assert checks["R2"].status == "partial"


def test_r1_no_license_anywhere_still_fails():
    # Genuinely no license: version columns empty AND resolver found none → R1/R2 fail.
    m = _meta(FILLED_ROLES)
    m.pop("license", None)
    rep = compute_fair_report(_full_inputs(
        license_raw="", license_spdx=None, license_compliant=False, meta_resolved=m))
    checks = _by_id(rep)
    assert checks["R1"].status == "fail"
    assert checks["R2"].status == "fail"


def test_stored_version_license_still_wins_over_resolved():
    # When the version has its own license signal, its compliance flag is authoritative
    # (the resolved fallback must not override it). Stored NC flag → R2 partial even if
    # the resolved meta happens to name an allowlisted license.
    rep = compute_fair_report(_full_inputs(
        license_raw="CC BY-NC 4.0", license_spdx="CC-BY-NC-4.0", license_compliant=False,
        meta_resolved=_meta_with_license("https://creativecommons.org/licenses/by/4.0/")))
    checks = _by_id(rep)
    assert checks["R1"].status == "pass"
    assert checks["R2"].status == "partial"


def test_no_coverage_no_zero_division():
    rep = compute_fair_report(_full_inputs(coverage=None))
    checks = _by_id(rep)
    assert checks["R5"].score == 0.0 and checks["R6"].score == 0.0
    assert checks["R5"].status == "fail"


def test_all_null_renders_without_raising():
    rep = compute_fair_report(FairInputs())
    checks = _by_id(rep)
    assert set(checks) == EXPECTED_IDS
    assert rep.overall < 0.2
    assert all(c.evidence for c in checks.values())      # every check explains itself
    assert checks["A3"].status == "pass"                 # platform guarantee holds


def test_r4_excludes_optional_roles_and_lists_all_29():
    rep = compute_fair_report(_full_inputs())
    r4 = _by_id(rep)["R4"]
    roles = r4.detail["roles"]
    assert len(roles) == 29
    assert r4.detail["scored"] == 21 and r4.detail["excluded"] == len(R4_EXCLUDED_ROLES) == 8
    assert r4.detail["filled"] == 18
    assert abs(r4.score - 18 / 21) < 1e-9 and r4.status == "pass"
    # the 8 optional MOD roles are present but flagged excluded
    excluded_labels = {r["role"] for r in roles if r["excluded"]}
    assert "Competency question" in excluded_labels and "Used in project" in excluded_labels


def test_r4_role_count_matches_registry():
    assert len(ALL_META_ROLES) == 29
    assert R4_EXCLUDED_ROLES <= set(ALL_META_ROLES)


# ── A1: content negotiation + RDF-extension fallback ────────────────────────────

def test_a1_passes_on_rdf_media_type():
    rep = compute_fair_report(_full_inputs(
        resolve_detail={"content_type": "text/turtle; charset=utf-8"}))
    a1 = _by_id(rep)["A1"]
    assert a1.status == "pass" and a1.score == 1.0
    assert "Accept" in a1.evidence


def test_a1_rescues_text_plain_when_url_ends_in_rdf_extension():
    # raw.githubusercontent.com serves .ttl as text/plain — the extension rescues it.
    rep = compute_fair_report(_full_inputs(resolve_detail={
        "content_type": "text/plain; charset=utf-8",
        "final_url": "https://raw.githubusercontent.com/AIDAVA-DEV/sulo/refs/heads/main/versions/latest/sulo.ttl",
    }))
    a1 = _by_id(rep)["A1"]
    assert a1.status == "pass" and a1.score == 1.0
    assert ".ttl" in a1.evidence


def test_a1_falls_back_to_ontology_iri_extension_when_no_final_url():
    rep = compute_fair_report(_full_inputs(
        ontology_iri="http://example.org/vocab/thing.owl",
        resolve_detail={"content_type": "application/octet-stream"}))
    a1 = _by_id(rep)["A1"]
    assert a1.status == "pass" and a1.score == 1.0
    assert ".owl" in a1.evidence


def test_a1_partial_when_generic_type_and_ambiguous_extension():
    # text/plain with a non-RDF (or ambiguous) extension stays partial: resolves,
    # but RDF is unconfirmed. .xml/.json are deliberately not rescued.
    rep = compute_fair_report(_full_inputs(resolve_detail={
        "content_type": "text/plain",
        "final_url": "https://example.org/ontology/data.xml",
    }))
    a1 = _by_id(rep)["A1"]
    assert a1.status == "partial" and a1.score == 0.5
    assert "unconfirmed" in a1.evidence


def test_a1_partial_when_resolves_as_html_page():
    rep = compute_fair_report(_full_inputs(resolve_detail={
        "content_type": "text/html; charset=utf-8",
        "final_url": "https://example.org/ontology/index.html",
    }))
    a1 = _by_id(rep)["A1"]
    assert a1.status == "partial" and a1.score == 0.5


def test_a1_fails_when_not_resolvable_even_with_rdf_extension():
    rep = compute_fair_report(_full_inputs(
        resolvable=False,
        resolve_detail={"final_url": "https://example.org/ontology/vocab.ttl"}))
    a1 = _by_id(rep)["A1"]
    assert a1.status == "fail" and a1.score == 0.0
    assert a1.evidence == "Not retrievable."
