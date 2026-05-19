"""Regression test: load each fixture TTL, run detect_profiles, compare in_profile booleans to expected JSON."""
import json
from pathlib import Path
import pyoxigraph
import pytest
from ontoexplorer.modules.owl_profile.detector import detect_profiles

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "owl_profile"


def _fixture_pairs():
    for ttl in sorted(FIXTURE_DIR.glob("*.ttl")):
        expected = ttl.with_suffix(".expected.json")
        if expected.exists():
            yield ttl, expected


@pytest.mark.parametrize("ttl_path,expected_path", list(_fixture_pairs()))
def test_robot_regression(ttl_path, expected_path):
    store = pyoxigraph.Store()
    store.load(ttl_path.read_bytes(), pyoxigraph.RdfFormat.TURTLE)
    expected = json.loads(expected_path.read_text())
    result = detect_profiles(store, graph_iri=None, ontology_id="test", version_id="v1")
    for profile in ("el", "rl", "ql", "dl"):
        if profile not in expected:
            continue
        exp_in = expected[profile].get("in_profile")
        if exp_in is not None:
            assert result[profile]["in_profile"] == exp_in, (
                f"{ttl_path.name}: expected {profile}.in_profile={exp_in}, "
                f"got {result[profile]['in_profile']}, violations: {result[profile].get('violations_by_axiom_type')}"
            )
