from unittest.mock import patch

from ontoexplorer.modules.jobs import tasks


def test_dispatch_resolvability_check_fires_the_task():
    with patch.object(tasks.check_ontology_resolvable, "delay") as m:
        tasks._dispatch_resolvability_check("onto-123")
        m.assert_called_once_with("onto-123")


def test_dispatch_resolvability_check_swallows_errors():
    # A broker hiccup must not bubble into the ingest-ready path.
    with patch.object(tasks.check_ontology_resolvable, "delay", side_effect=RuntimeError("broker down")):
        tasks._dispatch_resolvability_check("onto-123")  # no raise
