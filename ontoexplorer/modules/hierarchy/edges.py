"""The asserted hierarchy, mirrored into Postgres and read back for the tree.

Oxigraph answers "which entities are roots?" by comparing the whole entity set
against the whole child set. That is inherent to the question, and on DRON
(784,921 classes) it costs ~12.8 s even after the SPARQL was tightened. The
same comparison against an indexed table, alongside the entities already in
`entity_index`, takes ~0.8 s — and a child page stops needing a second query to
discover which children are themselves expandable.

This module owns both directions: extracting edges from the store at index
time, and answering the tree's two questions from SQL.

The mirror is only as fresh as the last index run, so `has_materialised_hierarchy`
exists to let callers fall back to SPARQL for versions indexed before this
shipped. A version with no rows means "not materialised", never "no hierarchy".
"""

from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

CLASS_KIND = "class"
PROPERTY_KIND = "property"
# Direct inferred parents, written by reasoning rather than indexing.
INFERRED_KIND = "inferred"

# Which kinds each writer owns. Indexing and reasoning are queued concurrently
# onto different Celery queues, so each must clear only its own rows.
ASSERTED_KINDS = (CLASS_KIND, PROPERTY_KIND)

_OWL_THING = "http://www.w3.org/2002/07/owl#Thing"

# entity_index.type values that make up the "property" tree.
_PROPERTY_TYPES = ("object_property", "data_property", "annotation_property")

# Rows per executemany batch on the portable path (see replace_edges).
_INSERT_BATCH = 5_000

_EDGE_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?child ?parent WHERE {{
    GRAPH <{graph}> {{
        ?child {predicate} ?parent .
        FILTER(isIRI(?child) && isIRI(?parent))
    }}
}}
"""


def extract_edges(store, graph: str) -> list[tuple[str, str, str]]:
    """Read both hierarchies out of the store as (child, parent, kind) rows.

    owl:Thing parents are dropped: the tree does not display owl:Thing, so
    keeping those edges would mark every top-level class as having a parent and
    leave the tree with no roots at all.
    """
    edges: list[tuple[str, str, str]] = []
    for predicate, kind in (("rdfs:subClassOf", CLASS_KIND),
                            ("rdfs:subPropertyOf", PROPERTY_KIND)):
        for row in store.query(_EDGE_QUERY.format(graph=graph, predicate=predicate)):
            parent = row["parent"].value
            if parent == _OWL_THING:
                continue
            edges.append((row["child"].value, parent, kind))
    return edges


def non_root_iris(edges) -> set[str]:
    """Every entity that appears as a child, in either hierarchy.

    An entity belongs to exactly one hierarchy, so pooling the two child sets
    is unambiguous: whatever is not in here has no parent and is a root.
    Indexing writes this to entity_index.is_root.
    """
    return {child for child, _parent, _kind in edges}


async def replace_edges(
    db: AsyncSession,
    version_id: str,
    edges: list[tuple[str, str, str]],
    kinds: tuple[str, ...] = ASSERTED_KINDS,
) -> int:
    """Replace this version's edges *of the given kinds*. Returns rows written.

    Delete-then-insert rather than upsert: a re-run must also drop edges the
    ontology no longer has, and the table has no unique key to upsert on.

    Scoped by kind because indexing (asserted) and reasoning (inferred) write
    the same table from different Celery queues with no ordering between them.
    A version-wide delete would let whichever finished last erase the other's
    hierarchy.
    """
    await db.execute(
        text("DELETE FROM hierarchy_edge WHERE version_id = :v AND kind IN :kinds")
        .bindparams(bindparam("kinds", expanding=True)),
        {"v": version_id, "kinds": list(kinds)},
    )
    if edges:
        await _insert_edges(db, version_id, edges)
    await db.commit()
    return len(edges)


async def _insert_edges(db: AsyncSession, version_id: str, edges) -> None:
    """COPY under asyncpg; batched INSERT anywhere else.

    COPY moves DRON's ~778k rows in ~0.4 s, but it is asyncpg-specific, so the
    portable path keeps this module usable under sqlite in tests.
    """
    raw = await db.connection()
    driver_conn = getattr(await raw.get_raw_connection(), "driver_connection", None)
    if hasattr(driver_conn, "copy_records_to_table"):
        await driver_conn.copy_records_to_table(
            "hierarchy_edge",
            records=((version_id, c, p, k) for c, p, k in edges),
            columns=["version_id", "child", "parent", "kind"],
        )
        return

    stmt = text(
        "INSERT INTO hierarchy_edge (version_id, child, parent, kind) "
        "VALUES (:v, :c, :p, :k)"
    )
    for start in range(0, len(edges), _INSERT_BATCH):
        await db.execute(stmt, [
            {"v": version_id, "c": c, "p": p, "k": k}
            for c, p, k in edges[start:start + _INSERT_BATCH]
        ])


async def has_materialised_hierarchy(db: AsyncSession, version_id: str) -> bool:
    """Whether this version's edges have been mirrored.

    Callers use this to decide between the SQL path and the SPARQL fallback: an
    empty result from the SQL path is indistinguishable from a genuinely empty
    tree, so absence has to be detected before querying, not after.
    """
    found = (await db.execute(
        text("SELECT 1 FROM hierarchy_edge WHERE version_id = :v LIMIT 1"),
        {"v": version_id},
    )).scalar()
    return found is not None


def _type_clause(entity_type: str) -> tuple[str, dict]:
    """SQL fragment + params selecting the entity_index rows for this tree."""
    if entity_type == "property":
        return ("e.type IN :types", {"types": _PROPERTY_TYPES})
    return ("e.type = :etype", {"etype": entity_type})


def _edge_kind(entity_type: str) -> str:
    return CLASS_KIND if entity_type in ("class", "individual") else PROPERTY_KIND


async def fetch_roots(
    db: AsyncSession,
    version_id: str,
    entity_type: str,
    *,
    hide_obsolete: bool,
    limit: int,
    offset: int,
) -> list[dict]:
    """Entities of this type with no parent, read from the precomputed flag.

    Not an anti-join against hierarchy_edge: only 5 of DRON's 771,512 classes
    are roots, and with a LIMIT the planner assumed it could stop early, chose a
    nested loop, and spent 26 s sorting every row to disk and probing the index
    once per entity. The flag turns it into an indexed filter.
    """
    type_sql, params = _type_clause(entity_type)
    obsolete_sql = "AND e.deprecated = false" if hide_obsolete else ""

    sql = text(f"""
        SELECT e.iri, e.primary_label AS label,
               EXISTS (
                   SELECT 1 FROM hierarchy_edge c
                   WHERE c.version_id = e.version_id
                     AND c.kind = :kind
                     AND c.parent = e.iri
               ) AS has_children
        FROM entity_index e
        WHERE e.version_id = :v
          AND {type_sql}
          {obsolete_sql}
          AND e.is_root
        ORDER BY lower(e.primary_label), e.iri
        LIMIT :limit OFFSET :offset
    """)
    if entity_type == "property":
        sql = sql.bindparams(bindparam("types", expanding=True))

    rows = (await db.execute(sql, {
        "v": version_id, "kind": _edge_kind(entity_type),
        "limit": limit, "offset": offset, **params,
    })).all()
    return [{"iri": r.iri, "label": r.label, "lang": None,
             "has_children": bool(r.has_children)} for r in rows]


async def fetch_children(
    db: AsyncSession,
    version_id: str,
    parent: str,
    entity_type: str,
    *,
    hide_obsolete: bool,
    limit: int,
    offset: int,
) -> list[dict]:
    """Direct children of `parent`, each flagged with whether it expands further.

    has_children is computed inline. The SPARQL path needed a second round trip
    with a VALUES block over the whole page to answer the same thing.
    """
    type_sql, params = _type_clause(entity_type)
    obsolete_sql = "AND e.deprecated = false" if hide_obsolete else ""
    kind = _edge_kind(entity_type)

    # No DISTINCT: the edge key makes (version_id, child, parent, kind) unique
    # and entity_index is keyed on (version_id, iri), so the join is 1:1 and
    # cannot duplicate a child. Postgres also rejects SELECT DISTINCT alongside
    # an ORDER BY expression that is not in the select list, which sqlite allows
    # — so a DISTINCT here fails only in production.
    sql = text(f"""
        SELECT e.iri, e.primary_label AS label,
               EXISTS (
                   SELECT 1 FROM hierarchy_edge c
                   WHERE c.version_id = h.version_id
                     AND c.kind = h.kind
                     AND c.parent = h.child
               ) AS has_children
        FROM hierarchy_edge h
        JOIN entity_index e
          ON e.version_id = h.version_id AND e.iri = h.child
        WHERE h.version_id = :v
          AND h.kind = :kind
          AND h.parent = :parent
          AND {type_sql}
          {obsolete_sql}
        ORDER BY lower(e.primary_label), e.iri
        LIMIT :limit OFFSET :offset
    """)
    if entity_type == "property":
        sql = sql.bindparams(bindparam("types", expanding=True))

    rows = (await db.execute(sql, {
        "v": version_id, "kind": kind, "parent": parent,
        "limit": limit, "offset": offset, **params,
    })).all()
    return [{"iri": r.iri, "label": r.label, "lang": None,
             "has_children": bool(r.has_children)} for r in rows]


async def warm_root_cache_sql(
    db: AsyncSession, redis, version_id: str, *, limit: int = 200
) -> int:
    """Populate the root cache from the mirrored edges. Returns roots cached.

    The SPARQL warmer re-derives roots from the whole graph — ~17 s per index
    run on DRON. Once the edges are mirrored the same answer is ~0.7 s, so this
    is preferred whenever indexing has just written them.

    Writes the payload list_terms returns, and clears the other variants first,
    exactly as the SPARQL warmer does.
    """
    import json

    from ontoexplorer.modules.hierarchy.roots import (
        ROOT_CACHE_TTL,
        invalidate_root_cache,
        root_cache_key,
    )

    invalidate_root_cache(redis, version_id)
    terms = await fetch_roots(
        db, version_id, "class", hide_obsolete=True, limit=limit, offset=0)
    payload = {"terms": terms, "offset": 0, "limit": limit, "parent": "root"}
    redis.setex(
        root_cache_key(version_id, "class", limit, True, None),
        ROOT_CACHE_TTL,
        json.dumps(payload),
    )
    return len(terms)


# ── inferred hierarchy ────────────────────────────────────────────────────────

_OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


def reduce_direct_inferred(
    direct_superclasses: dict[str, list[str]],
    superclasses: dict[str, list[str]],
    unsatisfiable,
    all_classes: set[str],
) -> tuple[list[tuple[str, str, str]], set[str]]:
    """Reduce a classification to (direct inferred edges, root IRIs).

    Done once per reasoning run. Previously this ran on every /inferred-children
    request, after fetching and parsing the whole classification — 16 s to
    return two terms on DRON.

    Conventions preserved from that implementation:
      * owl:Thing is never a parent; every class subclasses it, so keeping it
        would leave the tree with no roots.
      * An unsatisfiable class gets owl:Nothing as its direct parent, the
        Protégé "broken corner", and so is not a root.
      * owl:Nothing is not itself recorded as a root — the read surfaces it only
        when something actually hangs beneath it.
      * A class absent from both maps is still a root: EL reasoners omit classes
        with no non-trivial subsumptions, and those are exactly the top-level
        classes with no subclasses.
    """
    unsat = set(unsatisfiable or ())
    edges: list[tuple[str, str, str]] = []
    roots: set[str] = set()

    for cls in sorted(all_classes):
        if cls == _OWL_NOTHING:
            continue
        if cls in direct_superclasses:
            parents = [p for p in direct_superclasses[cls] if p != _OWL_THING]
        else:
            raw = [p for p in superclasses.get(cls, []) if p != _OWL_THING]
            # Keep only parents that are not an ancestor of another parent.
            parents = [
                p for p in raw
                if not any(p in superclasses.get(q, []) for q in raw if q != p)
            ]
        if cls in unsat and _OWL_NOTHING not in parents:
            parents.append(_OWL_NOTHING)

        if parents:
            edges.extend((cls, p, INFERRED_KIND) for p in parents)
        else:
            roots.add(cls)
    return edges, roots


async def replace_inferred_roots(db: AsyncSession, version_id: str, iris) -> int:
    """Make this version's inferred-root set exactly `iris`."""
    await db.execute(
        text("DELETE FROM inferred_root WHERE version_id = :v"), {"v": version_id}
    )
    rows = sorted(iris)
    if rows:
        await db.execute(
            text("INSERT INTO inferred_root (version_id, iri) VALUES (:v, :iri)"),
            [{"v": version_id, "iri": i} for i in rows],
        )
    await db.commit()
    return len(rows)


async def has_materialised_inferred(db: AsyncSession, version_id: str) -> bool:
    """Whether reasoning has written this version's inferred edges.

    Absence means "not reasoned, or reasoned before this shipped" — the caller
    falls back rather than showing an empty inferred tree.
    """
    found = (await db.execute(
        text("SELECT 1 FROM hierarchy_edge WHERE version_id = :v AND kind = :k LIMIT 1"),
        {"v": version_id, "k": INFERRED_KIND},
    )).scalar()
    return found is not None


def _inferred_child_rows(rows) -> list[dict]:
    return [{"iri": r.iri, "label": r.label, "lang": None,
             "has_children": bool(r.has_children)} for r in rows]


async def fetch_inferred_children(
    db: AsyncSession, version_id: str, parent: str, *,
    hide_obsolete: bool, limit: int, offset: int,
) -> list[dict]:
    """Direct inferred children of `parent`, each flagged as expandable."""
    obsolete_sql = "AND e.deprecated = false" if hide_obsolete else ""
    rows = (await db.execute(text(f"""
        SELECT e.iri, e.primary_label AS label,
               EXISTS (
                   SELECT 1 FROM hierarchy_edge c
                   WHERE c.version_id = h.version_id AND c.kind = h.kind
                     AND c.parent = h.child
               ) AS has_children
        FROM hierarchy_edge h
        JOIN entity_index e
          ON e.version_id = h.version_id AND e.iri = h.child
        WHERE h.version_id = :v AND h.kind = :kind AND h.parent = :parent
          AND e.type = 'class'
          {obsolete_sql}
        ORDER BY lower(e.primary_label), e.iri
        LIMIT :limit OFFSET :offset
    """), {"v": version_id, "kind": INFERRED_KIND, "parent": parent,
           "limit": limit, "offset": offset})).all()
    return _inferred_child_rows(rows)


async def fetch_inferred_roots(
    db: AsyncSession, version_id: str, *,
    hide_obsolete: bool, limit: int, offset: int,
) -> list[dict]:
    """Top level of the inferred tree.

    owl:Nothing is prepended when anything is unsatisfiable, so the broken
    classes are reachable from the root — it is a synthetic node, derived from
    the edges rather than stored as a root.
    """
    obsolete_sql = "AND e.deprecated = false" if hide_obsolete else ""
    rows = (await db.execute(text(f"""
        SELECT e.iri, e.primary_label AS label,
               EXISTS (
                   SELECT 1 FROM hierarchy_edge c
                   WHERE c.version_id = r.version_id AND c.kind = :kind
                     AND c.parent = e.iri
               ) AS has_children
        FROM inferred_root r
        JOIN entity_index e
          ON e.version_id = r.version_id AND e.iri = r.iri
        WHERE r.version_id = :v
          AND e.type = 'class'
          {obsolete_sql}
        ORDER BY lower(e.primary_label), e.iri
        LIMIT :limit OFFSET :offset
    """), {"v": version_id, "kind": INFERRED_KIND,
           "limit": limit, "offset": offset})).all()
    roots = _inferred_child_rows(rows)

    if offset == 0:
        unsat = (await db.execute(
            text("SELECT 1 FROM hierarchy_edge WHERE version_id = :v AND kind = :k "
                 "AND parent = :n LIMIT 1"),
            {"v": version_id, "k": INFERRED_KIND, "n": _OWL_NOTHING},
        )).scalar()
        if unsat is not None:
            roots.insert(0, {"iri": _OWL_NOTHING, "label": "Nothing",
                             "lang": None, "has_children": True})
    return roots
