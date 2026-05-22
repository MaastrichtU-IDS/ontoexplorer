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
import asyncio
from collections import deque

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._common import get_latest_version_or_404, get_ontology_or_404
from ontoexplorer.api.ols._iri import double_decode_iri
from ontoexplorer.database import get_db
from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

# Re-use asserted hierarchy fetchers from terms.py (already tested there).
from ontoexplorer.api.ols.terms import (
    _asserted_children_sync,
    _asserted_parents_sync,
    _OWL_EXCLUDED,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RDFS_SUBCLASS_OF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


def _label_from_iri(iri: str) -> str:
    """Derive a human-readable label from an IRI by taking the local name."""
    fragment = iri.rstrip("/")
    if "#" in fragment:
        return fragment.split("#")[-1]
    return fragment.rsplit("/", 1)[-1]


def _entity_label(vid: str, iri: str) -> str:
    """Load primary_label from Redis; fall back to IRI-derived label."""
    r = _get_redis()
    val = r.hget(_iri_key(vid, iri), "primary_label")
    return val if val else _label_from_iri(iri)


def _has_children_sync(ontology_id: str, vid: str, iri: str) -> bool:
    """Return True when the given IRI has at least one asserted child."""
    return bool(_asserted_children_sync(ontology_id, vid, iri))


# ---------------------------------------------------------------------------
# jstree builder
# ---------------------------------------------------------------------------

def _build_jstree(
    ontology_id: str,
    ontology_name: str,
    vid: str,
    focus_iri: str,
    include_siblings: bool,
) -> list[dict]:
    """Build jstree node list.

    Algorithm
    ---------
    1. BFS up from focus_iri to collect the ancestor chain.
    2. For every node in the chain, build a jstree dict.
    3. The direct parent id for each node is its immediate parent's IRI;
       nodes with no parents get ``parent="#"``.
    4. state.opened=True for all nodes in the focus path.
    5. If include_siblings, for each ancestor find its siblings (other children
       of the ancestor's parent) and add them as collapsed nodes.
    """
    # --- Step 1: collect the ancestor chain (BFS upward) --------------------
    # path_nodes: list of (iri, parent_iri_or_None)
    # We keep a mapping iri → immediate_parents for building the tree later.
    visited: set[str] = set()
    parents_map: dict[str, list[str]] = {}  # iri -> its direct parents

    queue: deque[str] = deque([focus_iri])
    visited.add(focus_iri)

    while queue:
        node = queue.popleft()
        parents = [
            p for p in _asserted_parents_sync(ontology_id, vid, node)
            if p not in _OWL_EXCLUDED
        ]
        parents_map[node] = parents
        for p in parents:
            if p not in visited:
                visited.add(p)
                queue.append(p)

    # --- Step 2: build jstree nodes -----------------------------------------
    # All nodes in the focus path should be opened.
    focus_path_iris: set[str] = set(visited)

    # Map from iri → jstree node id (same as IRI for single-parent chains;
    # kept as IRI for simplicity).
    nodes: list[dict] = []
    emitted: set[str] = set()

    def _make_node(iri: str, parent_id: str, opened: bool) -> dict:
        return {
            "id": iri,
            "parent": parent_id,
            "text": _entity_label(vid, iri),
            "iri": iri,
            "children": _has_children_sync(ontology_id, vid, iri),
            "state": {"opened": opened},
            "a_attr": {"iri": iri},
            "ontology_name": ontology_name,
        }

    # Emit all nodes in the focus path.  For each node, determine its parent
    # id: the first element in its parents_map entry (or "#" for roots).
    for iri in focus_path_iris:
        parents = parents_map.get(iri, [])
        # Use the first parent as the tree parent (OLS behaviour for multi-parent
        # is to pick one; pick the first in the list).
        parent_id = parents[0] if parents else "#"
        opened = True  # all nodes in the focus path are opened
        node_dict = _make_node(iri, parent_id, opened)
        nodes.append(node_dict)
        emitted.add(iri)

    # --- Step 3: siblings (if requested) ------------------------------------
    if include_siblings:
        # For each ancestor (non-focus nodes), add its siblings: other children
        # of the ancestor's parent.
        ancestors = focus_path_iris - {focus_iri}
        for ancestor in ancestors:
            ancestor_parents = parents_map.get(ancestor, [])
            for ap in ancestor_parents:
                # ap's children = siblings of ancestor
                siblings = _asserted_children_sync(ontology_id, vid, ap)
                for sibling in siblings:
                    if sibling in _OWL_EXCLUDED:
                        continue
                    if sibling in emitted:
                        continue
                    # Siblings are collapsed (not on focus path)
                    sibling_parents = [
                        p for p in _asserted_parents_sync(ontology_id, vid, sibling)
                        if p not in _OWL_EXCLUDED
                    ]
                    sibling_parent_id = sibling_parents[0] if sibling_parents else "#"
                    sibling_node = _make_node(sibling, sibling_parent_id, False)
                    nodes.append(sibling_node)
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

    nodes = await asyncio.to_thread(
        _build_jstree,
        str(ontology.id),
        ontology.shortname,
        vid,
        iri,
        siblings,
    )
    return nodes


# ---------------------------------------------------------------------------
# graph builder
# ---------------------------------------------------------------------------

def _build_graph(
    ontology_id: str,
    vid: str,
    focus_iri: str,
) -> dict:
    """Build 1-hop neighbourhood graph centred on focus_iri.

    Includes:
    - focus_iri as a node
    - direct asserted parents as nodes + subClassOf edges (focus → parent)
    - direct asserted children as nodes + subClassOf edges (child → focus)
    """
    nodes_map: dict[str, dict] = {}
    edges: list[dict] = []

    def _node(iri: str) -> dict:
        return {
            "id": iri,
            "iri": iri,
            "label": _entity_label(vid, iri),
            "type": "class",
        }

    def _edge(source: str, target: str) -> dict:
        return {
            "source": source,
            "target": target,
            "label": "rdfs:subClassOf",
            "uri": _RDFS_SUBCLASS_OF,
        }

    # Focus node
    nodes_map[focus_iri] = _node(focus_iri)

    # Parents
    parents = [
        p for p in _asserted_parents_sync(ontology_id, vid, focus_iri)
        if p not in _OWL_EXCLUDED
    ]
    for p in parents:
        nodes_map[p] = _node(p)
        edges.append(_edge(focus_iri, p))

    # Children
    children = [
        c for c in _asserted_children_sync(ontology_id, vid, focus_iri)
        if c not in _OWL_EXCLUDED
    ]
    for c in children:
        nodes_map[c] = _node(c)
        edges.append(_edge(c, focus_iri))

    return {
        "nodes": list(nodes_map.values()),
        "edges": edges,
    }


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

    graph = await asyncio.to_thread(
        _build_graph,
        str(ontology.id),
        vid,
        iri,
    )
    return graph
