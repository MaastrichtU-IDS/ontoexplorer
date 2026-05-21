from pathlib import Path
from unittest.mock import patch

import pyoxigraph
import pytest

from ontoexplorer.clients.robot import RobotConsistencyResult
from ontoexplorer.modules.consistency.detector import (
    ConsistencyReport,
    ScopeResult,
    detect_consistency,
)


HOST_GRAPH = "urn:test:host"


@pytest.fixture
def populated_store(monkeypatch):
    store = pyoxigraph.Store()
    store.load(
        b'@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
        b'<http://example.org/host#A> a owl:Class .\n',
        "text/turtle",
        to_graph=pyoxigraph.NamedNode(HOST_GRAPH),
    )
    monkeypatch.setattr(
        "ontoexplorer.modules.consistency.merger.get_store",
        lambda: store,
    )
    return store


def test_report_has_three_scope_sections(populated_store, tmp_path):
    fake_reuse = {"mireot_terms": [], "imports": []}
    with patch("ontoexplorer.modules.consistency.detector._load_reuse_payload",
               return_value=fake_reuse), \
         patch("ontoexplorer.modules.consistency.detector.run_robot_consistency",
               return_value=RobotConsistencyResult(consistent=True, globally_inconsistent=False)), \
         patch("ontoexplorer.modules.consistency.detector.explain_unsatisfiability",
               return_value={}):
        report = detect_consistency(
            version_id="v1",
            ontology_id="o1",
            host_iri="http://example.org/host",
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            work_dir=tmp_path,
        )
    assert isinstance(report, ConsistencyReport)
    assert set(report.scopes.keys()) == {
        "host_only", "host_plus_imports", "host_plus_imports_plus_mireot"
    }
    for scope in report.scopes.values():
        assert isinstance(scope, ScopeResult)
        assert scope.status == "consistent"


def test_inconsistent_konclude_result_propagates_to_scope(populated_store, tmp_path):
    fake_reuse = {"mireot_terms": [], "imports": []}
    bad_result = RobotConsistencyResult(consistent=False, globally_inconsistent=False, unsatisfiable_class_iris=["http://example.org/bad#X"],
    )
    with patch("ontoexplorer.modules.consistency.detector._load_reuse_payload",
               return_value=fake_reuse), \
         patch("ontoexplorer.modules.consistency.detector.run_robot_consistency",
               return_value=bad_result), \
         patch("ontoexplorer.modules.consistency.detector.explain_unsatisfiability",
               return_value={}):
        report = detect_consistency(
            version_id="v1",
            ontology_id="o1",
            host_iri="http://example.org/host",
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            work_dir=tmp_path,
        )
    assert report.scopes["host_only"].status == "inconsistent"
    assert len(report.scopes["host_only"].unsatisfiable_classes) == 1
    assert report.scopes["host_only"].unsatisfiable_classes[0].iri == "http://example.org/bad#X"


def test_explain_called_once_per_scope_with_max_cap(populated_store, tmp_path):
    """ROBOT explain is invoked ONCE per scope (3 total), with max_explanations=10."""
    iris = [f"http://example.org/bad#{i}" for i in range(15)]
    bad_result = RobotConsistencyResult(consistent=False, globally_inconsistent=False, unsatisfiable_class_iris=iris)
    call_records: list[dict] = []

    def fake_explain(merge_path, *, max_explanations=10, **kwargs):
        call_records.append({"max": max_explanations})
        return {}

    with patch("ontoexplorer.modules.consistency.detector._load_reuse_payload",
               return_value={"mireot_terms": [], "imports": []}), \
         patch("ontoexplorer.modules.consistency.detector.run_robot_consistency",
               return_value=bad_result), \
         patch("ontoexplorer.modules.consistency.detector.explain_unsatisfiability",
               side_effect=fake_explain):
        report = detect_consistency(
            version_id="v1", ontology_id="o1",
            host_iri="http://example.org/host",
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            work_dir=tmp_path,
        )
    # 3 scopes = 3 explain calls
    assert len(call_records) == 3
    assert all(r["max"] == 10 for r in call_records)
    # All 15 unsat classes still recorded per scope (with empty justifications since fake returns {})
    host_only = report.scopes["host_only"]
    assert len(host_only.unsatisfiable_classes) == 15
    for uc in host_only.unsatisfiable_classes:
        assert uc.justification == []


def test_justifications_looked_up_from_explanation_dict(populated_store, tmp_path):
    """Per-class justification axioms come from the dict ROBOT returns."""
    iris = ["http://example.org/bad#X", "http://example.org/bad#Y"]
    bad_result = RobotConsistencyResult(consistent=False, globally_inconsistent=False, unsatisfiable_class_iris=iris)
    fake_explanations = {
        "http://example.org/bad#X": [
            [{"t": "iri", "iri": "http://example.org/bad#X", "label": "X", "in_ontology": True},
             {"t": "text", "v": " SubClassOf "},
             {"t": "iri", "iri": "http://example.org/bad#A", "label": "A", "in_ontology": True}],
        ],
        # Y has no entry — should result in empty justification, but still recorded
    }
    with patch("ontoexplorer.modules.consistency.detector._load_reuse_payload",
               return_value={"mireot_terms": [], "imports": []}), \
         patch("ontoexplorer.modules.consistency.detector.run_robot_consistency",
               return_value=bad_result), \
         patch("ontoexplorer.modules.consistency.detector.explain_unsatisfiability",
               return_value=fake_explanations):
        report = detect_consistency(
            version_id="v1", ontology_id="o1",
            host_iri="http://example.org/host",
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            work_dir=tmp_path,
        )
    host_only = report.scopes["host_only"]
    x_entry = next(u for u in host_only.unsatisfiable_classes if u.iri.endswith("#X"))
    y_entry = next(u for u in host_only.unsatisfiable_classes if u.iri.endswith("#Y"))
    assert len(x_entry.justification) == 1
    assert y_entry.justification == []


def test_mireot_skipped_marks_partial(populated_store, tmp_path):
    """If MIREOT sources were skipped (failed fetch), the MIREOT scope becomes 'partial'."""
    fake_reuse = {
        "mireot_terms": [
            {"iri": "http://purl.obolibrary.org/obo/Foo_1",
             "source_prefix": "obscure", "has_imported_from": False},
        ],
        "imports": [],
    }
    from ontoexplorer.modules.consistency.mireot_source_resolver import MireotSourceResolveResult
    fake_mireot_result = MireotSourceResolveResult(
        fetched={},
        skipped=["obscure"],
    )
    with patch("ontoexplorer.modules.consistency.detector._load_reuse_payload",
               return_value=fake_reuse), \
         patch("ontoexplorer.modules.consistency.detector.fetch_mireot_sources",
               return_value=fake_mireot_result), \
         patch("ontoexplorer.modules.consistency.detector.run_robot_consistency",
               return_value=RobotConsistencyResult(consistent=True, globally_inconsistent=False)), \
         patch("ontoexplorer.modules.consistency.detector.explain_unsatisfiability",
               return_value={}):
        report = detect_consistency(
            version_id="v1", ontology_id="o1",
            host_iri="http://example.org/host",
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            work_dir=tmp_path,
        )
    mireot_scope = report.scopes["host_plus_imports_plus_mireot"]
    assert mireot_scope.status == "partial"
    assert mireot_scope.mireot_sources_skipped == ["obscure"]
