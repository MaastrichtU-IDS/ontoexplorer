"""Integration tests for OLS4-compat widget endpoints: /jstree and /graph.

These tests exercise the two bespoke-shape routes:
  GET /ols/api/ontologies/{onto}/terms/{iri}/jstree
  GET /ols/api/ontologies/{onto}/terms/{iri}/graph

ELK reasoning is NOT available in tests.  All hierarchy lookups use the
Redis `parents` field seeded by the fixtures.
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.indexer import _iri_key, _meta_key, _type_key


# ---------------------------------------------------------------------------
# Fixture: three-level class hierarchy for widget tests
#
#     GrandParent  ←  Parent  ←  Child
#                      ↑
#                    Sibling   (another child of GrandParent, same level as Parent)
# ---------------------------------------------------------------------------

@pytest.fixture()
async def widget_hierarchy(db_session, fake_redis):
    """Seed an ontology with:

        GrandParent
        ├── Parent
        │   └── Child
        └── Sibling    (sibling of Parent)

    Entity hashes include a `parents` JSON array so the asserted-fallback
    path works without Oxigraph.
    """
    uid = uuid.uuid4().hex[:8]
    ont = Ontology(
        iri=f"http://example.org/widgeto-{uid}.owl",
        shortname=f"widgeto{uid}",
        title="Widget Test Ontology",
    )
    db_session.add(ont)
    await db_session.flush()

    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"widgeto/test-{uid}.owl",
        sha256=f"widgeto_sha256_{uid}",
        format="owl",
        status="ready",
        version_iri="2025-01-01",
    )
    db_session.add(ver)
    await db_session.commit()

    vid = str(ver.id)
    fake_redis.hset(
        _meta_key(ver.id),
        mapping={
            "class_count": "4",
            "property_count": "0",
            "individual_count": "0",
            "schema_version": "v2",
            "indexed_at": "2025-01-01T00:00:00+00:00",
        },
    )

    gp_iri      = "http://example.org/widgeto#GrandParent"
    parent_iri  = "http://example.org/widgeto#Parent"
    child_iri   = "http://example.org/widgeto#Child"
    sibling_iri = "http://example.org/widgeto#Sibling"

    def _seed(iri: str, label: str, parents: list[str]):
        fake_redis.hset(
            _iri_key(vid, iri),
            mapping={
                "iri":           iri,
                "primary_label": label,
                "label":         label,
                "short":         label,
                "type":          "class",
                "source":        str(ont.id),
                "labels":        json.dumps([{"value": label, "lang": "en"}]),
                "synonyms":      json.dumps([]),
                "definitions":   json.dumps([]),
                "parents":       json.dumps(parents),
            },
        )
        fake_redis.sadd(_type_key(vid, "class"), iri)

    _seed(gp_iri,      "GrandParent", [])
    _seed(parent_iri,  "Parent",      [gp_iri])
    _seed(child_iri,   "Child",       [parent_iri])
    _seed(sibling_iri, "Sibling",     [gp_iri])

    yield {
        "ontology":    ont,
        "version_id":  vid,
        "gp_iri":      gp_iri,
        "parent_iri":  parent_iri,
        "child_iri":   child_iri,
        "sibling_iri": sibling_iri,
    }


# ---------------------------------------------------------------------------
# Fixture: isolated entity (no parents, no children)
# ---------------------------------------------------------------------------

@pytest.fixture()
async def isolated_entity(db_session, fake_redis):
    """Seed a single class with no parents and no children."""
    uid = uuid.uuid4().hex[:8]
    ont = Ontology(
        iri=f"http://example.org/isolated-{uid}.owl",
        shortname=f"isolated{uid}",
        title="Isolated Entity Test Ontology",
    )
    db_session.add(ont)
    await db_session.flush()

    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key=f"isolated/test-{uid}.owl",
        sha256=f"isolated_sha256_{uid}",
        format="owl",
        status="ready",
        version_iri="2025-01-01",
    )
    db_session.add(ver)
    await db_session.commit()

    vid = str(ver.id)
    fake_redis.hset(
        _meta_key(ver.id),
        mapping={
            "class_count": "1",
            "property_count": "0",
            "individual_count": "0",
            "schema_version": "v2",
            "indexed_at": "2025-01-01T00:00:00+00:00",
        },
    )

    iri = "http://example.org/isolated#Alone"
    fake_redis.hset(
        _iri_key(vid, iri),
        mapping={
            "iri":           iri,
            "primary_label": "Alone",
            "label":         "Alone",
            "short":         "Alone",
            "type":          "class",
            "source":        str(ont.id),
            "labels":        json.dumps([{"value": "Alone", "lang": "en"}]),
            "synonyms":      json.dumps([]),
            "definitions":   json.dumps([]),
            "parents":       json.dumps([]),
        },
    )
    fake_redis.sadd(_type_key(vid, "class"), iri)

    yield {
        "ontology":   ont,
        "version_id": vid,
        "iri":        iri,
    }


# ===========================================================================
# /jstree tests
# ===========================================================================

@pytest.mark.anyio
async def test_jstree_returns_array_of_nodes(client: AsyncClient, widget_hierarchy):
    """Response is a JSON array with at least the focus node and its parent."""
    onto_id = widget_hierarchy["ontology"].id
    child_iri = widget_hierarchy["child_iri"]
    encoded = encode_iri_for_ols_path(child_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/jstree")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list), "jstree response must be a JSON array"
    iris_in_response = {node["iri"] for node in data}
    assert child_iri in iris_in_response, "Focus node must be in the response"
    assert widget_hierarchy["parent_iri"] in iris_in_response, "Parent must be in the response"


@pytest.mark.anyio
async def test_jstree_includes_input_with_opened_state(client: AsyncClient, widget_hierarchy):
    """The focus (input) node has state.opened == true."""
    onto_id = widget_hierarchy["ontology"].id
    child_iri = widget_hierarchy["child_iri"]
    encoded = encode_iri_for_ols_path(child_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/jstree")
    assert resp.status_code == 200
    data = resp.json()
    focus_nodes = [n for n in data if n["iri"] == child_iri]
    assert len(focus_nodes) == 1
    assert focus_nodes[0]["state"]["opened"] is True


@pytest.mark.anyio
async def test_jstree_root_parent_marker(client: AsyncClient, widget_hierarchy):
    """Root node (GrandParent, no parents) has parent field set to '#'."""
    onto_id = widget_hierarchy["ontology"].id
    child_iri = widget_hierarchy["child_iri"]
    gp_iri = widget_hierarchy["gp_iri"]
    encoded = encode_iri_for_ols_path(child_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/jstree")
    assert resp.status_code == 200
    data = resp.json()
    gp_nodes = [n for n in data if n["iri"] == gp_iri]
    assert len(gp_nodes) == 1
    assert gp_nodes[0]["parent"] == "#", "Root node must have parent='#'"


@pytest.mark.anyio
async def test_jstree_siblings_excluded_by_default(client: AsyncClient, widget_hierarchy):
    """Without ?siblings=true, sibling nodes are not included."""
    onto_id = widget_hierarchy["ontology"].id
    # Request jstree for Child; Sibling is a sibling of Parent (both under GrandParent)
    child_iri = widget_hierarchy["child_iri"]
    sibling_iri = widget_hierarchy["sibling_iri"]
    encoded = encode_iri_for_ols_path(child_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/jstree")
    assert resp.status_code == 200
    data = resp.json()
    iris = {n["iri"] for n in data}
    assert sibling_iri not in iris, "Siblings must be excluded by default"


@pytest.mark.anyio
async def test_jstree_siblings_included_when_requested(client: AsyncClient, widget_hierarchy):
    """With ?siblings=true, ancestor siblings are included."""
    onto_id = widget_hierarchy["ontology"].id
    child_iri = widget_hierarchy["child_iri"]
    sibling_iri = widget_hierarchy["sibling_iri"]
    encoded = encode_iri_for_ols_path(child_iri)

    resp = await client.get(
        f"/ols/api/ontologies/{onto_id}/terms/{encoded}/jstree",
        params={"siblings": "true"},
    )
    assert resp.status_code == 200
    data = resp.json()
    iris = {n["iri"] for n in data}
    # Sibling is a sibling of Parent (both are children of GrandParent)
    assert sibling_iri in iris, "Sibling of ancestor must be included with siblings=true"


@pytest.mark.anyio
async def test_jstree_ancestor_opened_state(client: AsyncClient, widget_hierarchy):
    """All ancestor nodes on the path to root have state.opened == true."""
    onto_id = widget_hierarchy["ontology"].id
    child_iri = widget_hierarchy["child_iri"]
    parent_iri = widget_hierarchy["parent_iri"]
    gp_iri = widget_hierarchy["gp_iri"]
    encoded = encode_iri_for_ols_path(child_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/jstree")
    assert resp.status_code == 200
    data = resp.json()
    for expected_iri in [parent_iri, gp_iri]:
        nodes = [n for n in data if n["iri"] == expected_iri]
        assert nodes, f"Expected {expected_iri} in response"
        assert nodes[0]["state"]["opened"] is True, f"Ancestor {expected_iri} must have state.opened=true"


@pytest.mark.anyio
async def test_jstree_node_shape(client: AsyncClient, widget_hierarchy):
    """Each node has the required jstree fields."""
    onto_id = widget_hierarchy["ontology"].id
    child_iri = widget_hierarchy["child_iri"]
    encoded = encode_iri_for_ols_path(child_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/jstree")
    assert resp.status_code == 200
    data = resp.json()
    for node in data:
        assert "id" in node
        assert "parent" in node
        assert "text" in node
        assert "iri" in node
        assert "children" in node
        assert isinstance(node["children"], bool)
        assert "state" in node
        assert "opened" in node["state"]
        assert "a_attr" in node
        assert "iri" in node["a_attr"]
        assert "ontology_name" in node


@pytest.mark.anyio
async def test_jstree_isolated_entity_returns_single_node(client: AsyncClient, isolated_entity):
    """An entity with no parents returns a single-node array with parent='#'."""
    onto_id = isolated_entity["ontology"].id
    iri = isolated_entity["iri"]
    encoded = encode_iri_for_ols_path(iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/jstree")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["iri"] == iri
    assert data[0]["parent"] == "#"


# ===========================================================================
# /graph tests
# ===========================================================================

@pytest.mark.anyio
async def test_graph_returns_nodes_and_edges(client: AsyncClient, widget_hierarchy):
    """1-hop graph for the middle node (Parent) includes parent, self, and child."""
    onto_id = widget_hierarchy["ontology"].id
    parent_iri = widget_hierarchy["parent_iri"]
    gp_iri = widget_hierarchy["gp_iri"]
    child_iri = widget_hierarchy["child_iri"]
    encoded = encode_iri_for_ols_path(parent_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data

    node_iris = {n["iri"] for n in data["nodes"]}
    assert parent_iri in node_iris, "Focus node must be in graph nodes"
    assert gp_iri in node_iris, "Direct parent must be in graph nodes"
    assert child_iri in node_iris, "Direct child must be in graph nodes"

    assert len(data["edges"]) >= 2, "At least 2 subClassOf edges expected"


@pytest.mark.anyio
async def test_graph_empty_neighbourhood_returns_self_only(client: AsyncClient, isolated_entity):
    """An isolated entity (no parents, no children) returns just itself as a node."""
    onto_id = isolated_entity["ontology"].id
    iri = isolated_entity["iri"]
    encoded = encode_iri_for_ols_path(iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["iri"] == iri
    assert data["edges"] == []


@pytest.mark.anyio
async def test_graph_edge_label_is_subclassof(client: AsyncClient, widget_hierarchy):
    """All edges have label 'rdfs:subClassOf' and the correct uri field."""
    onto_id = widget_hierarchy["ontology"].id
    parent_iri = widget_hierarchy["parent_iri"]
    encoded = encode_iri_for_ols_path(parent_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/graph")
    assert resp.status_code == 200
    data = resp.json()
    for edge in data["edges"]:
        assert edge["label"] == "rdfs:subClassOf"
        assert edge["uri"] == "http://www.w3.org/2000/01/rdf-schema#subClassOf"


@pytest.mark.anyio
async def test_graph_node_shape(client: AsyncClient, widget_hierarchy):
    """Each graph node has required fields: id, iri, label, type."""
    onto_id = widget_hierarchy["ontology"].id
    parent_iri = widget_hierarchy["parent_iri"]
    encoded = encode_iri_for_ols_path(parent_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/graph")
    assert resp.status_code == 200
    data = resp.json()
    for node in data["nodes"]:
        assert "id" in node
        assert "iri" in node
        assert "label" in node
        assert "type" in node


@pytest.mark.anyio
async def test_graph_edge_direction(client: AsyncClient, widget_hierarchy):
    """Child → Parent edges go source=child, target=parent (subClassOf direction)."""
    onto_id = widget_hierarchy["ontology"].id
    parent_iri = widget_hierarchy["parent_iri"]
    gp_iri = widget_hierarchy["gp_iri"]
    child_iri = widget_hierarchy["child_iri"]
    encoded = encode_iri_for_ols_path(parent_iri)

    resp = await client.get(f"/ols/api/ontologies/{onto_id}/terms/{encoded}/graph")
    assert resp.status_code == 200
    data = resp.json()
    edges = data["edges"]
    # parent subClassOf grandparent: source=parent_iri, target=gp_iri
    up_edges = [e for e in edges if e["source"] == parent_iri and e["target"] == gp_iri]
    assert up_edges, "Edge from Parent to GrandParent expected"
    # child subClassOf parent: source=child_iri, target=parent_iri
    down_edges = [e for e in edges if e["source"] == child_iri and e["target"] == parent_iri]
    assert down_edges, "Edge from Child to Parent expected"
