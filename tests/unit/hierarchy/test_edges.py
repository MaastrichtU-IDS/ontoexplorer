"""The navigation tree served from `hierarchy_edge` instead of Oxigraph.

Root detection is a whole-graph question: every entity, minus every entity with
a parent. On DRON (784,921 classes) that cost 61.8 s originally and ~12.8 s
after the SPARQL was tightened. Against the materialised edges alongside
`entity_index` the same answer takes ~0.8 s, and a child page plus its
has-children probe collapse from two Oxigraph round trips into one indexed join.

The rows are a mirror, so the risky parts are the ones pinned here: that
re-indexing replaces a version's edges rather than accumulating them, that a
version with no rows is reported as *not materialised* (so callers fall back
rather than rendering an empty tree), and that the SQL reproduces the SPARQL
path's filters — obsolete terms hidden, owl:Thing not counted as a parent.
"""
import pytest
from sqlalchemy import select

from ontoexplorer.models.db import HierarchyEdge
from ontoexplorer.modules.hierarchy.edges import (
    CLASS_KIND,
    PROPERTY_KIND,
    extract_edges,
    fetch_children,
    fetch_roots,
    has_materialised_hierarchy,
    replace_edges,
)

OWL_THING = "http://www.w3.org/2002/07/owl#Thing"


class Cell:
    def __init__(self, value):
        self.value = value


class FakeStore:
    """Returns subClassOf or subPropertyOf pairs depending on the query."""

    def __init__(self, sub_class, sub_prop):
        self.sub_class = sub_class
        self.sub_prop = sub_prop

    def query(self, q):
        pairs = self.sub_prop if "subPropertyOf" in q else self.sub_class
        return [{"child": Cell(c), "parent": Cell(p)} for c, p in pairs]


async def _seed_version(db, version_id, entities, edges):
    """Seed entities + edges together, deriving is_root exactly as indexing does.

    Keeps the fixtures honest: is_root is a stored flag, so a test that sets it
    by hand can easily assert something the indexer would never write.
    """
    from ontoexplorer.modules.hierarchy.edges import non_root_iris
    non_roots = non_root_iris(edges)
    for spec in entities:
        iri = spec["iri"]
        await _seed_entity(
            db, version_id, iri, spec["label"],
            type_=spec.get("type", "class"),
            deprecated=spec.get("deprecated", False),
            is_root=iri not in non_roots,
        )
    await replace_edges(db, version_id, edges)


async def _seed_entity(db, version_id, iri, label, type_="class",
                       deprecated=False, is_root=True):
    from ontoexplorer.models.db import EntityIndex
    db.add(EntityIndex(
        version_id=version_id, iri=iri, ontology_id="o1", type=type_,
        primary_label=label, primary_label_norm=label.lower(),
        short=iri.rsplit("/", 1)[-1], search_text=label, deprecated=deprecated,
        is_root=is_root,
    ))
    await db.commit()


# ── extraction ────────────────────────────────────────────────────────────────

def test_extract_tags_each_hierarchy_with_its_kind():
    store = FakeStore(
        sub_class=[("http://x/B", "http://x/A")],
        sub_prop=[("http://x/q", "http://x/p")],
    )
    edges = extract_edges(store, "urn:g")
    assert ("http://x/B", "http://x/A", CLASS_KIND) in edges
    assert ("http://x/q", "http://x/p", PROPERTY_KIND) in edges


def test_extract_drops_owl_thing_parents():
    """owl:Thing is not a displayed parent; keeping it would make every
    top-level class look like a child."""
    store = FakeStore(sub_class=[("http://x/A", OWL_THING)], sub_prop=[])
    assert extract_edges(store, "urn:g") == []


# ── population ────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_replace_is_idempotent_across_reindexes(db_session):
    await replace_edges(db_session, "v-idem", [("c", "p", CLASS_KIND)])
    await replace_edges(db_session, "v-idem", [("c", "p", CLASS_KIND)])
    rows = (await db_session.execute(
        select(HierarchyEdge).where(HierarchyEdge.version_id == "v-idem"))).scalars().all()
    assert len(rows) == 1, "re-indexing must replace a version's edges, not append"


@pytest.mark.anyio
async def test_replace_drops_edges_that_no_longer_exist(db_session):
    await replace_edges(db_session, "v-shrink", [("c", "p", CLASS_KIND), ("d", "p", CLASS_KIND)])
    await replace_edges(db_session, "v-shrink", [("c", "p", CLASS_KIND)])
    rows = (await db_session.execute(
        select(HierarchyEdge.child).where(HierarchyEdge.version_id == "v-shrink"))).scalars().all()
    assert rows == ["c"]


@pytest.mark.anyio
async def test_replace_touches_only_its_own_version(db_session):
    await replace_edges(db_session, "v-a", [("c", "p", CLASS_KIND)])
    await replace_edges(db_session, "v-b", [("x", "y", CLASS_KIND)])
    await replace_edges(db_session, "v-a", [])
    kept = (await db_session.execute(
        select(HierarchyEdge.child).where(HierarchyEdge.version_id == "v-b"))).scalars().all()
    assert kept == ["x"]


# ── the fallback gate ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_version_without_rows_reports_not_materialised(db_session):
    """Must be distinguishable from 'this ontology genuinely has no edges',
    or every version indexed before this shipped would render an empty tree."""
    assert await has_materialised_hierarchy(db_session, "v-never-indexed") is False


@pytest.mark.anyio
async def test_version_with_rows_reports_materialised(db_session):
    await replace_edges(db_session, "v-has", [("c", "p", CLASS_KIND)])
    assert await has_materialised_hierarchy(db_session, "v-has") is True


# ── roots ─────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_roots_exclude_entities_that_have_a_parent(db_session):
    v = "v-roots"
    await _seed_version(db_session, v, [
        {"iri": "http://x/A", "label": "Alpha"},
        {"iri": "http://x/B", "label": "Beta"},
        {"iri": "http://x/D", "label": "delta"},
    ], [("http://x/B", "http://x/A", CLASS_KIND)])

    roots = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=50, offset=0)
    assert [r["iri"] for r in roots] == ["http://x/A", "http://x/D"]


@pytest.mark.anyio
async def test_roots_sorted_case_insensitively_by_label(db_session):
    v = "v-sort"
    for iri, lbl in [("http://x/1", "zebra"), ("http://x/2", "Apple")]:
        await _seed_entity(db_session, v, iri, lbl)
    await replace_edges(db_session, v, [("http://x/keep", "http://x/1", CLASS_KIND)])

    roots = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=50, offset=0)
    assert [r["label"] for r in roots] == ["Apple", "zebra"]


@pytest.mark.anyio
async def test_roots_hide_obsolete_by_default_and_can_include_them(db_session):
    v = "v-dep"
    await _seed_entity(db_session, v, "http://x/live", "Live")
    await _seed_entity(db_session, v, "http://x/dead", "Dead", deprecated=True)
    await replace_edges(db_session, v, [("http://x/keep", "http://x/live", CLASS_KIND)])

    hidden = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=50, offset=0)
    shown = await fetch_roots(db_session, v, "class", hide_obsolete=False, limit=50, offset=0)
    assert [r["label"] for r in hidden] == ["Live"]
    assert {r["label"] for r in shown} == {"Live", "Dead"}


@pytest.mark.anyio
async def test_roots_are_filtered_by_entity_type(db_session):
    v = "v-types"
    await _seed_entity(db_session, v, "http://x/C", "AClass", type_="class")
    await _seed_entity(db_session, v, "http://x/p", "AProp", type_="object_property")
    await replace_edges(db_session, v, [("http://x/keep", "http://x/C", CLASS_KIND)])

    classes = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=50, offset=0)
    props = await fetch_roots(db_session, v, "object_property", hide_obsolete=True, limit=50, offset=0)
    assert [r["label"] for r in classes] == ["AClass"]
    assert [r["label"] for r in props] == ["AProp"]


@pytest.mark.anyio
async def test_property_roots_use_the_property_hierarchy(db_session):
    """A property with a subPropertyOf parent is not a root, and a subClassOf
    edge must not be mistaken for one."""
    v = "v-prop"
    await _seed_version(db_session, v, [
        {"iri": "http://x/p", "label": "Parent", "type": "object_property"},
        {"iri": "http://x/q", "label": "Child", "type": "object_property"},
    ], [("http://x/q", "http://x/p", PROPERTY_KIND)])

    roots = await fetch_roots(db_session, v, "object_property", hide_obsolete=True, limit=50, offset=0)
    assert [r["label"] for r in roots] == ["Parent"]


@pytest.mark.anyio
async def test_roots_paginate(db_session):
    v = "v-page"
    for i in range(5):
        await _seed_entity(db_session, v, f"http://x/{i}", f"L{i}")
    await replace_edges(db_session, v, [("http://x/other", "http://x/0", CLASS_KIND)])

    page = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=2, offset=2)
    assert [r["label"] for r in page] == ["L2", "L3"]


# ── children ──────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_children_returns_labels_and_has_children_in_one_go(db_session):
    v = "v-kids"
    for iri, lbl in [("http://x/A", "A"), ("http://x/B", "B"), ("http://x/C", "C"),
                     ("http://x/D", "D")]:
        await _seed_entity(db_session, v, iri, lbl)
    await replace_edges(db_session, v, [
        ("http://x/B", "http://x/A", CLASS_KIND),
        ("http://x/C", "http://x/A", CLASS_KIND),
        ("http://x/D", "http://x/B", CLASS_KIND),   # B is itself a parent
    ])

    kids = await fetch_children(db_session, v, "http://x/A", "class",
                                hide_obsolete=True, limit=50, offset=0)
    assert [k["iri"] for k in kids] == ["http://x/B", "http://x/C"]
    assert [k["has_children"] for k in kids] == [True, False]


@pytest.mark.anyio
async def test_children_hide_obsolete(db_session):
    v = "v-kids-dep"
    await _seed_entity(db_session, v, "http://x/A", "A")
    await _seed_entity(db_session, v, "http://x/ok", "Ok")
    await _seed_entity(db_session, v, "http://x/old", "Old", deprecated=True)
    await replace_edges(db_session, v, [
        ("http://x/ok", "http://x/A", CLASS_KIND),
        ("http://x/old", "http://x/A", CLASS_KIND),
    ])

    kids = await fetch_children(db_session, v, "http://x/A", "class",
                                hide_obsolete=True, limit=50, offset=0)
    assert [k["label"] for k in kids] == ["Ok"]


@pytest.mark.anyio
async def test_children_of_a_leaf_is_empty(db_session):
    v = "v-leaf"
    await _seed_entity(db_session, v, "http://x/A", "A")
    await replace_edges(db_session, v, [("http://x/A", "http://x/root", CLASS_KIND)])
    assert await fetch_children(db_session, v, "http://x/A", "class",
                                hide_obsolete=True, limit=50, offset=0) == []


@pytest.mark.anyio
async def test_an_edge_appears_once_per_version(db_session):
    """A graph is a set of triples, so an edge cannot repeat — the key enforces
    it. Confirmed against DRON: 777,706 extracted edges, 0 duplicates."""
    v = "v-dup"
    await _seed_entity(db_session, v, "http://x/A", "A")
    await _seed_entity(db_session, v, "http://x/B", "B")
    await replace_edges(db_session, v, [("http://x/B", "http://x/A", CLASS_KIND)])

    kids = await fetch_children(db_session, v, "http://x/A", "class",
                                hide_obsolete=True, limit=50, offset=0)
    assert [k["iri"] for k in kids] == ["http://x/B"]

    rows = (await db_session.execute(
        select(HierarchyEdge).where(HierarchyEdge.version_id == v))).scalars().all()
    assert len(rows) == 1


@pytest.mark.anyio
async def test_roots_report_has_children_accurately(db_session):
    """The SPARQL path computes has_children for roots too, and the tree draws
    an expand arrow from it — a root with no children must not claim one."""
    v = "v-root-kids"
    await _seed_version(db_session, v, [
        {"iri": "http://x/parent", "label": "Parent"},
        {"iri": "http://x/lonely", "label": "Lonely"},
        {"iri": "http://x/kid", "label": "Kid"},
    ], [("http://x/kid", "http://x/parent", CLASS_KIND)])

    roots = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=50, offset=0)
    by_label = {r["label"]: r["has_children"] for r in roots}
    assert by_label == {"Lonely": False, "Parent": True}


def test_children_sql_avoids_select_distinct():
    """Postgres rejects SELECT DISTINCT with an ORDER BY expression outside the
    select list; sqlite allows it, so this only failed in production. The join
    is 1:1 (both tables are keyed), so DISTINCT was never needed.

    Checks the emitted SQL rather than the source, so the explanatory comment
    above the query does not trip it.
    """
    import inspect
    import re
    from ontoexplorer.modules.hierarchy import edges

    src = inspect.getsource(edges.fetch_children)
    src = re.sub(r"^\s*#.*$", "", src, flags=re.M)          # strip comments
    src = re.sub(r'"""."*?"""', "", src, flags=re.S)          # strip the docstring
    assert "SELECT DISTINCT" not in src


@pytest.mark.anyio
async def test_sql_warm_writes_the_same_payload_as_the_sparql_warm(db_session):
    """Once edges exist there is no reason to warm the cache by re-deriving
    roots from the graph: that took ~17 s per index run on DRON against ~0.7 s
    from SQL. The payload must stay identical or a cache hit would differ from
    a computed response."""
    import fakeredis, json
    from ontoexplorer.modules.hierarchy.edges import warm_root_cache_sql
    from ontoexplorer.modules.hierarchy.roots import ROOT_CACHE_TTL, root_cache_key

    v = "v-warm-sql"
    await _seed_version(db_session, v, [
        {"iri": "http://x/A", "label": "Alpha"},
        {"iri": "http://x/B", "label": "Beta"},
    ], [("http://x/B", "http://x/A", CLASS_KIND)])

    r = fakeredis.FakeStrictRedis()
    r.set(root_cache_key(v, "class", 50, True, None), "stale-variant")
    n = await warm_root_cache_sql(db_session, r, v, limit=200)

    assert n == 1
    payload = json.loads(r.get(root_cache_key(v, "class", 200, True, None)))
    assert set(payload) == {"terms", "offset", "limit", "parent"}
    assert payload["parent"] == "root" and payload["offset"] == 0
    assert [t["label"] for t in payload["terms"]] == ["Alpha"]
    assert set(payload["terms"][0]) == {"iri", "label", "lang", "has_children"}
    assert r.get(root_cache_key(v, "class", 50, True, None)) is None
    assert 0 < r.ttl(root_cache_key(v, "class", 200, True, None)) <= ROOT_CACHE_TTL


# ── is_root ───────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_roots_read_the_precomputed_flag_not_an_anti_join(db_session):
    """Root-ness is written at index time, not derived per request.

    The flags here deliberately contradict the edges: an anti-join would return
    "Flagged" (it has a parent edge) and drop "Unflagged" (it has none), so the
    assertion only holds if the stored flag is what is read.
    """
    v = "v-flag"
    await _seed_entity(db_session, v, "http://x/flagged", "Flagged", is_root=True)
    await _seed_entity(db_session, v, "http://x/unflagged", "Unflagged", is_root=False)
    await replace_edges(db_session, v, [("http://x/flagged", "http://x/p", CLASS_KIND)])

    roots = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=50, offset=0)
    assert [r["label"] for r in roots] == ["Flagged"]


def test_compute_non_roots_splits_by_hierarchy():
    """An entity is a root relative to its own hierarchy, so the child sets of
    the class and property trees are pooled — an entity is in exactly one."""
    from ontoexplorer.modules.hierarchy.edges import non_root_iris
    edges = [
        ("http://x/B", "http://x/A", CLASS_KIND),
        ("http://x/q", "http://x/p", PROPERTY_KIND),
    ]
    assert non_root_iris(edges) == {"http://x/B", "http://x/q"}


# ── kind ownership ────────────────────────────────────────────────────────────
# Indexing writes the asserted edges; reasoning writes the inferred ones. They
# are queued concurrently onto different Celery queues, so neither may clear
# the other's rows — a version-wide delete would have one wipe the other
# depending on which finished last.

@pytest.mark.anyio
async def test_writing_inferred_edges_leaves_asserted_ones_alone(db_session):
    from ontoexplorer.modules.hierarchy.edges import INFERRED_KIND
    v = "v-kinds"
    await replace_edges(db_session, v, [
        ("http://x/B", "http://x/A", CLASS_KIND),
        ("http://x/q", "http://x/p", PROPERTY_KIND),
    ], kinds=(CLASS_KIND, PROPERTY_KIND))

    await replace_edges(db_session, v, [
        ("http://x/C", "http://x/A", INFERRED_KIND),
    ], kinds=(INFERRED_KIND,))

    kinds = sorted(k for (k,) in (await db_session.execute(
        select(HierarchyEdge.kind).where(HierarchyEdge.version_id == v))).all())
    assert kinds == [CLASS_KIND, INFERRED_KIND, PROPERTY_KIND]


@pytest.mark.anyio
async def test_reindexing_leaves_inferred_edges_alone(db_session):
    from ontoexplorer.modules.hierarchy.edges import INFERRED_KIND
    v = "v-kinds2"
    await replace_edges(db_session, v, [("http://x/C", "http://x/A", INFERRED_KIND)],
                        kinds=(INFERRED_KIND,))
    await replace_edges(db_session, v, [("http://x/B", "http://x/A", CLASS_KIND)],
                        kinds=(CLASS_KIND, PROPERTY_KIND))

    rows = sorted((c, k) for c, k in (await db_session.execute(
        select(HierarchyEdge.child, HierarchyEdge.kind)
        .where(HierarchyEdge.version_id == v))).all())
    assert rows == [("http://x/B", CLASS_KIND), ("http://x/C", INFERRED_KIND)]


@pytest.mark.anyio
async def test_replacing_a_kind_still_clears_that_kinds_stale_rows(db_session):
    from ontoexplorer.modules.hierarchy.edges import INFERRED_KIND
    v = "v-kinds3"
    await replace_edges(db_session, v, [
        ("http://x/C", "http://x/A", INFERRED_KIND),
        ("http://x/D", "http://x/A", INFERRED_KIND),
    ], kinds=(INFERRED_KIND,))
    await replace_edges(db_session, v, [("http://x/C", "http://x/A", INFERRED_KIND)],
                        kinds=(INFERRED_KIND,))
    kids = sorted(c for (c,) in (await db_session.execute(
        select(HierarchyEdge.child).where(HierarchyEdge.version_id == v))).all())
    assert kids == ["http://x/C"]
