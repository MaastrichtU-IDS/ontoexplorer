"""detect_profiles (cached summary) must drop the per-instance list; full_violations
and the CLI must emit every violation with its specific entity. Uses the real
pinned pyhornedowl (available in the venv/image)."""
import pytest

pytest.importorskip("pyhornedowl")

from ontoexplorer.modules.owl_profile import detect as cli
from ontoexplorer.modules.owl_profile.detector import detect_profiles, full_violations

# A DL ontology that uses two undeclared classes.
_OFN = (
    "Ontology(<http://ex.org/o>\n"
    "  SubClassOf(<http://purl.obolibrary.org/obo/GO_0008150> <http://ex.org/B>))"
)


def test_detect_profiles_has_no_per_instance_list():
    payload = detect_profiles(_OFN, "ofn")
    for key in ("el", "rl", "ql", "dl"):
        assert key in payload
        assert set(payload[key]) == {"in_profile", "total_violations", "violations_by_axiom_type"}
        assert "sample_violations" not in payload[key]
        assert "violations" not in payload[key]
    # counts are still exact
    assert payload["dl"]["violations_by_axiom_type"].get("UseOfUndeclaredClass", 0) >= 1


def test_full_violations_names_each_entity():
    full = full_violations(_OFN, "ofn", ("dl",))["dl"]
    assert full["violations"], "expected at least one violation"
    subjects = {v["subject_iri"] for v in full["violations"]}
    assert "http://purl.obolibrary.org/obo/GO_0008150" in subjects
    details = {v["details"] for v in full["violations"]}
    assert "GO_0008150" in details  # local name, not the generic message


def test_cli_text_report(tmp_path, capsys):
    f = tmp_path / "o.ofn"
    f.write_text(_OFN)
    rc = cli.main([str(f), "DL"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OWL 2 DL" in out
    assert "UseOfUndeclaredClass" in out
    assert "GO_0008150" in out  # the specific entity is in the report


def test_cli_json(tmp_path, capsys):
    f = tmp_path / "o.ofn"
    f.write_text(_OFN)
    rc = cli.main([str(f), "DL", "--json"])
    assert rc == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert "dl" in data and data["dl"]["violations"]


def test_cli_missing_file_exits_2(capsys):
    assert cli.main(["/no/such/file.owl", "DL"]) == 2
    assert "cannot read" in capsys.readouterr().err
