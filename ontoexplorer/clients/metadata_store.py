"""In-process metadata triplestore (pyoxigraph), replacing Jena Fuseki.

Holds the FAIR catalogue metadata — DCAT + VoID + PROV-O — in a *separate*
Oxigraph store from the ontology content (``clients.oxigraph``). Keeping it a
distinct store, not extra named graphs in the content store, preserves the two
endpoints' semantics exactly: a query on ``/sparql`` sees only metadata and one
on ``/sparql/content`` sees only content, with no cross-leakage and no per-query
graph scoping to get wrong.

Named graphs held here (same IRIs the Fuseki writer used):
  urn:meta                                  — cross-ontology DCAT catalogue
  urn:prov                                  — PROV-O provenance
  urn:ontology:{ontology_id}:{version_id}:meta  — per-version DCAT record

Same read/write model as the content store: the write worker opens it
read-write (it is the sole writer, on the ``write`` Celery queue — both the
ingestion write and the purge delete run there), and the API opens a read-only
secondary refreshed every 60 s. So ``/sparql`` metadata can be up to 60 s stale,
exactly like ``/sparql/content``.

The public functions keep the names and async signatures the old Fuseki client
exposed (``sparql_update`` / ``insert_turtle`` / ``delete_graph``) so callers
only change their import. pyoxigraph is synchronous, so each runs in a thread.
"""

import asyncio
import time
from io import BytesIO
from pathlib import Path

import logging

import pyoxigraph

from ontoexplorer.config import get_settings

logger = logging.getLogger(__name__)

_store: pyoxigraph.Store | None = None
_ro_store: pyoxigraph.Store | None = None
_ro_store_opened_at: float = 0.0
_RO_STORE_TTL: float = 60.0

_TURTLE = pyoxigraph.RdfFormat.TURTLE


def get_metadata_store() -> pyoxigraph.Store:
    """The metadata store: read-write in the worker, a refreshed read-only
    secondary in the API (mirrors ``clients.oxigraph.get_store``)."""
    global _store, _ro_store, _ro_store_opened_at
    settings = get_settings()
    path = settings.metadata_store_path
    Path(path).mkdir(parents=True, exist_ok=True)
    if settings.oxigraph_read_only:
        now = time.monotonic()
        if _ro_store is None or (now - _ro_store_opened_at) > _RO_STORE_TTL:
            try:
                _ro_store = pyoxigraph.Store.read_only(path)
            except Exception as exc:
                # The on-disk RocksDB only exists once the writer has opened it
                # (first metadata write). Until then read_only() raises "CURRENT:
                # No such file". Serve an empty in-memory store so /sparql answers
                # 200-with-no-results instead of 500; the next refresh picks up the
                # real store once the writer has created it. Unlike the content
                # store this empty-and-uninitialised state is legitimate (a fresh
                # deploy before any ingestion / backfill).
                logger.warning("metadata store not yet initialised (%s); serving empty", exc)
                _ro_store = pyoxigraph.Store()
            _ro_store_opened_at = now
        return _ro_store
    if _store is None:
        _store = pyoxigraph.Store(path)
    return _store


async def sparql_update(update: str) -> None:
    """Run a SPARQL Update (e.g. the version-scoped DELETE/WHERE) on the store."""
    await asyncio.to_thread(get_metadata_store().update, update)


async def insert_turtle(ttl: str, graph_iri: str | None = None) -> None:
    """Append Turtle into a named graph (or the default graph).

    Append, not replace — the shared catalogue/provenance graphs accumulate
    across versions; per-version replacement is done by the caller's DELETE.
    """
    graph = pyoxigraph.NamedNode(graph_iri) if graph_iri else pyoxigraph.DefaultGraph()

    def _load() -> None:
        get_metadata_store().load(BytesIO(ttl.encode()), _TURTLE, to_graph=graph)

    await asyncio.to_thread(_load)


async def delete_graph(graph_iri: str) -> None:
    """Drop all triples in a named graph. Idempotent (no error if absent),
    matching the old ``DROP SILENT GRAPH``."""
    await asyncio.to_thread(get_metadata_store().remove_graph, pyoxigraph.NamedNode(graph_iri))
