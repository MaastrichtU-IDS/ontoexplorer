"""The inferred tree, precomputed at reasoning time instead of per click.

`/inferred-children` fetched and parsed the whole classification (12.1 s on
DRON) and reduced 771,507 classes to their direct parents in Python (1.06 s) on
every request, with no response cache: 16.0 s to return the two root terms,
2.1 s to expand a node. The reduction only changes when the ontology is
re-reasoned, so it is stored.

The reduction has several conventions that are easy to lose in a rewrite, so
each is pinned here.
"""
import pytest
from sqlalchemy import select

from ontoexplorer.models.db import InferredRoot
from ontoexplorer.modules.hierarchy.edges import (
    INFERRED_KIND,
    fetch_inferred_children,
    fetch_inferred_roots,
    has_materialised_inferred,
    reduce_direct_inferred,
    replace_edges,
    replace_inferred_roots,
)

OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


async def _seed_class(db, version_id, iri, label, deprecated=False):
    from ontoexplorer.models.db import EntityIndex
    db.add(EntityIndex(
        version_id=version_id, iri=iri, ontology_id="o1", type="class",
        primary_label=label, primary_label_norm=label.lower(),
        short=iri.rsplit("/", 1)[-1], search_text=label, deprecated=deprecated,
    ))
    await db.commit()


# ── the reduction ─────────────────────────────────────────────────────────────

def test_direct_superclasses_are_used_when_present():
    edges, roots = reduce_direct_inferred(
        direct_superclasses={"http://x/C": ["http://x/B"]},
        superclasses={"http://x/C": ["http://x/B", "http://x/A"]},
        unsatisfiable=[],
        all_classes={"http://x/A", "http://x/B", "http://x/C"},
    )
    assert ("http://x/C", "http://x/B", INFERRED_KIND) in edges
    assert ("http://x/C", "http://x/A", INFERRED_KIND) not in edges


def test_transitive_parents_are_reduced_when_direct_is_missing():
    """Without a direct map, a parent that is itself another parent's ancestor
    is not direct."""
    edges, _ = reduce_direct_inferred(
        direct_superclasses={},
        superclasses={"http://x/C": ["http://x/B", "http://x/A"],
                      "http://x/B": ["http://x/A"]},
        unsatisfiable=[],
        all_classes={"http://x/A", "http://x/B", "http://x/C"},
    )
    assert ("http://x/C", "http://x/B", INFERRED_KIND) in edges
    assert ("http://x/C", "http://x/A", INFERRED_KIND) not in edges


def test_owl_thing_is_never_a_parent():
    """Every class trivially subclasses Thing; keeping it would leave no roots."""
    edges, roots = reduce_direct_inferred(
        direct_superclasses={"http://x/A": [OWL_THING]},
        superclasses={},
        unsatisfiable=[],
        all_classes={"http://x/A"},
    )
    assert edges == []
    assert roots == {"http://x/A"}


def test_unsatisfiable_classes_hang_under_owl_nothing():
    """Protégé convention — the 'broken corner'."""
    edges, roots = reduce_direct_inferred(
        direct_superclasses={},
        superclasses={},
        unsatisfiable=["http://x/Bad"],
        all_classes={"http://x/Bad", "http://x/Ok"},
    )
    assert ("http://x/Bad", OWL_NOTHING, INFERRED_KIND) in edges
    assert "http://x/Bad" not in roots, "an unsat class sits under Nothing, not at top level"
    assert "http://x/Ok" in roots


def test_owl_nothing_is_not_added_twice():
    edges, _ = reduce_direct_inferred(
        direct_superclasses={"http://x/Bad": [OWL_NOTHING]},
        superclasses={},
        unsatisfiable=["http://x/Bad"],
        all_classes={"http://x/Bad"},
    )
    assert edges.count(("http://x/Bad", OWL_NOTHING, INFERRED_KIND)) == 1


def test_classes_absent_from_the_classification_are_still_roots():
    """EL reasoners omit classes with no non-trivial subsumptions, so a
    top-level class with no subclasses appears in neither map. It is still a
    root and must not vanish from the tree."""
    _, roots = reduce_direct_inferred(
        direct_superclasses={"http://x/C": ["http://x/B"]},
        superclasses={},
        unsatisfiable=[],
        all_classes={"http://x/B", "http://x/C", "http://x/Lonely"},
    )
    assert "http://x/Lonely" in roots


def test_a_class_that_only_appears_as_a_parent_is_a_root():
    _, roots = reduce_direct_inferred(
        direct_superclasses={"http://x/C": ["http://x/B"]},
        superclasses={},
        unsatisfiable=[],
        all_classes={"http://x/B", "http://x/C"},
    )
    assert roots == {"http://x/B"}


def test_owl_nothing_is_not_itself_a_root_entry():
    """It is surfaced as a synthetic top-level node by the query, not stored as
    a root — otherwise it would appear even with no unsatisfiable classes."""
    _, roots = reduce_direct_inferred(
        direct_superclasses={},
        superclasses={},
        unsatisfiable=["http://x/Bad"],
        all_classes={"http://x/Bad"},
    )
    assert OWL_NOTHING not in roots


# ── storage and reads ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_roots_are_replaced_not_accumulated(db_session):
    v = "v-ir"
    await replace_inferred_roots(db_session, v, {"http://x/A", "http://x/B"})
    await replace_inferred_roots(db_session, v, {"http://x/A"})
    rows = sorted(i for (i,) in (await db_session.execute(
        select(InferredRoot.iri).where(InferredRoot.version_id == v))).all())
    assert rows == ["http://x/A"]


@pytest.mark.anyio
async def test_roots_are_scoped_to_their_version(db_session):
    await replace_inferred_roots(db_session, "v-a", {"http://x/A"})
    await replace_inferred_roots(db_session, "v-b", {"http://x/B"})
    await replace_inferred_roots(db_session, "v-a", set())
    rows = [i for (i,) in (await db_session.execute(
        select(InferredRoot.iri).where(InferredRoot.version_id == "v-b"))).all()]
    assert rows == ["http://x/B"]


@pytest.mark.anyio
async def test_not_materialised_until_reasoning_has_written_edges(db_session):
    assert await has_materialised_inferred(db_session, "v-none") is False
    await replace_edges(db_session, "v-none", [("c", "p", INFERRED_KIND)],
                        kinds=(INFERRED_KIND,))
    assert await has_materialised_inferred(db_session, "v-none") is True


@pytest.mark.anyio
async def test_inferred_children_come_back_with_labels_and_expandability(db_session):
    v = "v-ic"
    for iri, lbl in [("http://x/A", "Alpha"), ("http://x/B", "Beta"),
                     ("http://x/C", "Gamma"), ("http://x/D", "Delta")]:
        await _seed_class(db_session, v, iri, lbl)
    await replace_edges(db_session, v, [
        ("http://x/B", "http://x/A", INFERRED_KIND),
        ("http://x/C", "http://x/A", INFERRED_KIND),
        ("http://x/D", "http://x/B", INFERRED_KIND),
    ], kinds=(INFERRED_KIND,))

    kids = await fetch_inferred_children(db_session, v, "http://x/A",
                                         hide_obsolete=True, limit=50, offset=0)
    assert [k["iri"] for k in kids] == ["http://x/B", "http://x/C"]
    assert [k["has_children"] for k in kids] == [True, False]


@pytest.mark.anyio
async def test_inferred_children_hide_obsolete(db_session):
    v = "v-ic-dep"
    await _seed_class(db_session, v, "http://x/A", "A")
    await _seed_class(db_session, v, "http://x/ok", "Ok")
    await _seed_class(db_session, v, "http://x/old", "Old", deprecated=True)
    await replace_edges(db_session, v, [
        ("http://x/ok", "http://x/A", INFERRED_KIND),
        ("http://x/old", "http://x/A", INFERRED_KIND),
    ], kinds=(INFERRED_KIND,))

    kids = await fetch_inferred_children(db_session, v, "http://x/A",
                                         hide_obsolete=True, limit=50, offset=0)
    assert [k["label"] for k in kids] == ["Ok"]


@pytest.mark.anyio
async def test_inferred_roots_read_the_stored_set(db_session):
    v = "v-ir2"
    await _seed_class(db_session, v, "http://x/A", "Alpha")
    await _seed_class(db_session, v, "http://x/B", "Beta")
    await replace_edges(db_session, v, [("http://x/B", "http://x/A", INFERRED_KIND)],
                        kinds=(INFERRED_KIND,))
    await replace_inferred_roots(db_session, v, {"http://x/A"})

    roots = await fetch_inferred_roots(db_session, v, hide_obsolete=True,
                                       limit=50, offset=0)
    assert [r["label"] for r in roots] == ["Alpha"]
    assert roots[0]["has_children"] is True


@pytest.mark.anyio
async def test_owl_nothing_leads_the_roots_when_anything_is_unsatisfiable(db_session):
    """Surfaced as a synthetic top-level node so the broken classes are
    reachable from the inferred root, and listed first."""
    v = "v-nothing"
    await _seed_class(db_session, v, "http://x/Ok", "Ok")
    await _seed_class(db_session, v, "http://x/Bad", "Bad")
    await replace_edges(db_session, v, [("http://x/Bad", OWL_NOTHING, INFERRED_KIND)],
                        kinds=(INFERRED_KIND,))
    await replace_inferred_roots(db_session, v, {"http://x/Ok"})

    roots = await fetch_inferred_roots(db_session, v, hide_obsolete=True,
                                       limit=50, offset=0)
    assert [r["iri"] for r in roots] == [OWL_NOTHING, "http://x/Ok"]
    assert roots[0]["has_children"] is True


@pytest.mark.anyio
async def test_owl_nothing_is_absent_when_everything_is_satisfiable(db_session):
    v = "v-no-nothing"
    await _seed_class(db_session, v, "http://x/Ok", "Ok")
    await replace_edges(db_session, v, [("http://x/Kid", "http://x/Ok", INFERRED_KIND)],
                        kinds=(INFERRED_KIND,))
    await replace_inferred_roots(db_session, v, {"http://x/Ok"})

    roots = await fetch_inferred_roots(db_session, v, hide_obsolete=True,
                                       limit=50, offset=0)
    assert [r["iri"] for r in roots] == ["http://x/Ok"]


@pytest.mark.anyio
async def test_children_of_owl_nothing_are_the_unsatisfiable_classes(db_session):
    v = "v-unsat"
    await _seed_class(db_session, v, "http://x/Bad", "Bad")
    await replace_edges(db_session, v, [("http://x/Bad", OWL_NOTHING, INFERRED_KIND)],
                        kinds=(INFERRED_KIND,))

    kids = await fetch_inferred_children(db_session, v, OWL_NOTHING,
                                         hide_obsolete=True, limit=50, offset=0)
    assert [k["iri"] for k in kids] == ["http://x/Bad"]
