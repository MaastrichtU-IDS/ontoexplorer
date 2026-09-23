"""index_ontology and embed_ontology must ride separate queues.

index_ontology flips a version to status="ready" (keyword search / browse);
embed_ontology builds pgvector term embeddings for semantic search and is far
slower + optional. When both shared the "index" queue, a backlog of slow embeds
starved index_ontology, leaving freshly-ingested ontologies stuck below "ready".
"""
from ontoexplorer.modules.jobs.tasks import celery_app


def test_index_and_embed_are_on_separate_queues():
    routes = celery_app.conf.task_routes
    assert routes["ontoexplorer.index_ontology"] == {"queue": "index"}
    assert routes["ontoexplorer.embed_ontology"] == {"queue": "embed"}
    # readiness (index) must never be blocked behind embeddings again
    assert routes["ontoexplorer.index_ontology"]["queue"] != routes["ontoexplorer.embed_ontology"]["queue"]
