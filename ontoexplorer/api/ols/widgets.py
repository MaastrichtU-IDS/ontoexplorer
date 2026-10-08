"""OLS4-compat widget endpoints — /jstree and /graph.

These two routes return bespoke response shapes used by the OLS web UI's
tree and graph widgets.  They are NOT wrapped in HAL envelopes.

Route ordering note
-------------------
This module's routes MUST be included in the top-level router BEFORE
``terms.py``, because ``terms.py`` registers a broad
``/api/ontologies/{onto}/terms/{iri_path:path}`` catch-all.  If widgets
are included after that catch-all the literal suffixes "jstree" and "graph"
would be consumed by it and return 404.
"""
from collections import deque

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._common import get_latest_version_or_404, get_ontology_or_404
from ontoexplorer.api.ols._entity_source import label_for, version_label_map
from ontoexplorer.api.ols._iri import double_decode_iri
from ontoexplorer.database import get_db

# Async asserted-edge fetchers from terms.py: one indexed hierarchy_edge query per
# call (SPARQL fallback when a version isn't materialised). #283: the jstree/graph
# builders used the SYNC helpers, which scanned EVERY class via per-IRI Redis hgets
# (_has_children alone did that for every node) — a fixed multi-second cost even on
# a tiny ontology. Going async lets these widgets use the indexed path.
from ontoexplorer.api.ols.terms import (
    _asserted_children,
    _asserted_parents,
    _OWL_EXCLUDED,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RDFS_SUBCLASS_OF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


async def _direct_children(db, ontology_id: str, vid: str, iri: str) -> list[str]:
    return [c for c in await _asserted_children(db, ontology_id, vid, iri)
            if c not in _OWL_EXCLUDED]


async def _direct_parents(db, ontology_id: str, vid: str, iri: str) -> list[str]:
    return [p for p in await _asserted_parents(db, ontology_id, vid, iri)
            if p not in _OWL_EXCLUDED]


# ---------------------------------------------------------------------------
# jstree builder
# ---------------------------------------------------------------------------

async def _build_jstree(
    db,
    ontology_id: str,
    ontology_name: str,
    vid: str,
    focus_iri: str,
    include_siblings: bool,
    lmap: dict,
) -> list[dict]:
    """Build jstree node list.

    1. BFS up from focus_iri to collect the ancestor chain.
    2. For every node in the chain, build a jstree dict (parent id = first direct
       parent, or "#" for roots); state.opened=True for the focus path.
    3. If include_siblings, add each ancestor's siblings as collapsed nodes.
    """
    # --- Step 1: collect the ancestor chain (BFS upward) --------------------
    visited: set[str] = set()
    parents_map: dict[str, list[str]] = {}  # iri -> its direct parents

    queue: deque[str] = deque([focus_iri])
    visited.add(focus_iri)
    while queue:
        node = queue.popleft()
        parents = await _direct_parents(db, ontology_id, vid, node)
        parents_map[node] = parents
        for p in parents:
            if p not in visited:
                visited.add(p)
                queue.append(p)

    focus_path_iris: set[str] = set(visited)
    nodes: list[dict] = []
    emitted: set[str] = set()

    async def _make_node(iri: str, parent_id: str, opened: bool) -> dict:
        return {
            "id": iri,
            "parent": parent_id,
            "text": label_for(lmap, iri),
            "iri": iri,
            "children": bool(await _direct_children(db, ontology_id, vid, iri)),
            "state": {"opened": opened},
            "a_attr": {"iri": iri},
            "ontology_name": ontology_name,
        }

    # --- Step 2: emit the focus-path nodes ----------------------------------
    for iri in focus_path_iris:
        parents = parents_map.get(iri, [])
        parent_id = parents[0] if parents else "#"
        nodes.append(await _make_node(iri, parent_id, opened=True))
        emitted.add(iri)

    # --- Step 3: siblings (if requested) ------------------------------------
    if include_siblings:
        ancestors = focus_path_iris - {focus_iri}
        for ancestor in ancestors:
            for ap in parents_map.get(ancestor, []):
                for sibling in await _direct_children(db, ontology_id, vid, ap):
                    if sibling in emitted:
                        continue
                    sib_parents = await _direct_parents(db, ontology_id, vid, sibling)
                    sib_parent_id = sib_parents[0] if sib_parents else "#"
                    nodes.append(await _make_node(sibling, sib_parent_id, opened=False))
                    emitted.add(sibling)

    return nodes


# ---------------------------------------------------------------------------
# /jstree endpoint
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/jstree")
async def term_jstree(
    ontology_id: str,
    iri_path: str,
    siblings: bool = Query(False),
    viewMode: str = Query("All"),  # accepted but ignored in v1
    db: AsyncSession = Depends(get_db),
):
    """jstree-compatible ancestor path for the OLS tree widget.

    Returns a raw JSON array (not HAL-wrapped).  Each element is a jstree
    node dict.  The full ancestor chain up to root is included so the tree
    can render the expanded path from root to the focus node.
    """
    iri = double_decode_iri(iri_path)
    ontology = await get_ontology_or_404(db, ontology_id)
    version = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    lmap = await version_label_map(db, vid)
    return await _build_jstree(
        db, str(ontology.id), ontology.shortname, vid, iri, siblings, lmap,
    )


# ---------------------------------------------------------------------------
# graph builder
# ---------------------------------------------------------------------------

async def _build_graph(db, ontology_id: str, vid: str, focus_iri: str, lmap: dict) -> dict:
    """1-hop neighbourhood graph: focus_iri + its direct asserted parents & children."""
    nodes_map: dict[str, dict] = {}
    edges: list[dict] = []

    def _node(iri: str) -> dict:
        return {"id": iri, "iri": iri, "label": label_for(lmap, iri), "type": "class"}

    def _edge(source: str, target: str) -> dict:
        return {"source": source, "target": target,
                "label": "rdfs:subClassOf", "uri": _RDFS_SUBCLASS_OF}

    nodes_map[focus_iri] = _node(focus_iri)
    for p in await _direct_parents(db, ontology_id, vid, focus_iri):
        nodes_map[p] = _node(p)
        edges.append(_edge(focus_iri, p))
    for c in await _direct_children(db, ontology_id, vid, focus_iri):
        nodes_map[c] = _node(c)
        edges.append(_edge(c, focus_iri))

    return {"nodes": list(nodes_map.values()), "edges": edges}


# ---------------------------------------------------------------------------
# /graph endpoint
# ---------------------------------------------------------------------------

@router.get("/api/ontologies/{ontology_id}/terms/{iri_path:path}/graph")
async def term_graph(
    ontology_id: str,
    iri_path: str,
    db: AsyncSession = Depends(get_db),
):
    """1-hop neighbourhood graph for the OLS graph widget.

    Returns ``{nodes: [...], edges: [...]}`` (not HAL-wrapped).
    Includes the input IRI, its direct parents, and its direct children.
    """
    iri = double_decode_iri(iri_path)
    ontology = await get_ontology_or_404(db, ontology_id)
    version = await get_latest_version_or_404(db, ontology_id)
    vid = str(version.id)

    lmap = await version_label_map(db, vid)
    return await _build_graph(db, str(ontology.id), vid, iri, lmap)
