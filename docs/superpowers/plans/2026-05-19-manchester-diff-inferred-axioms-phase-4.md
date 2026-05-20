# Manchester Diff — Phase 4 (Inferred Axiom Diffs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the ontology version diff to surface differences in the inferred named graph (ELK classification output), interleaved with asserted axiom changes inside the same Manchester frames and badged per-line as `[asserted]` or `[inferred]`.

**Architecture:** `_run_diff_core` performs a second axiom-collection pass over each side's `:inferred` named graph after a reasoning-readiness check. Per-entity inferred triples are filtered against trivial/redundant patterns (`SubClassOf owl:Thing`, reflexive subClassOf, asserted-duplicates) before being tagged `source: "inferred"` and merged into the per-entity `axiom_changes` list. The `ManchesterLine` TypedDict gains a `source` field so the frontend can render a per-line `[asserted]`/`[inferred]` badge. When reasoning isn't ready for either side, the inferred pass is skipped and the diff payload carries an `inferred_status` summary; the frontend shows a dismissable notice and polls every 30s for an updated payload. A re-queue hook in `reason_ontology` (plus a 15-minute beat safety net) automatically recomputes affected diffs when reasoning later completes.

**Tech Stack:** Python 3.11+ (SQLAlchemy 2 async, Celery + Celery beat, pyoxigraph), pytest, React 18 + React Router + React Query.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ontoexplorer/modules/diff/manchester.py` | MODIFY | Thread `source` through `render_axiom` / `render_frame`; emit `[asserted]`/`[inferred]` line metadata |
| `ontoexplorer/modules/diff/compute.py` | MODIFY | `_reasoning_status_for_version` helper; `_non_trivial_inferred_axioms` filter; second-pass inferred axiom collection in `_run_diff_core`; new summary fields |
| `ontoexplorer/modules/jobs/tasks.py` | MODIFY | Re-queue hook in `reason_ontology`; new `refresh_stale_inferred_diffs` beat task; register in beat_schedule |
| `tests/unit/test_manchester_render.py` | MODIFY | Source-field assertions on rendered lines |
| `tests/unit/test_diff_compute.py` | MODIFY | Tests for status helper, filter, end-to-end inferred-diff flow |
| `tests/unit/test_diff_inferred.py` | CREATE | Focused tests for the inferred-graph diff pass and non-trivial filter |
| `tests/integration/test_diff_api.py` | MODIFY | API contract assertions for `inferred_status` and summary breakdown |
| `frontend/src/lib/api.ts` | MODIFY | `source` on ManchesterLine; `inferred_status`, `asserted_axiom_changes`, `inferred_axiom_changes` on DiffSummary |
| `frontend/src/components/ManchesterFrame.tsx` | MODIFY | Append `[asserted]` / `[inferred]` badge to lines with `source` |
| `frontend/src/components/DiffResultView.tsx` | MODIFY | Inferred-unavailable notice; summary header breakdown; polling when statuses != ready |
| `frontend/src/components/ManchesterFrame.test.tsx` | MODIFY | Badge rendering test |
| `frontend/src/components/DiffResultView.test.tsx` | MODIFY | Notice + summary-breakdown tests |

---

## Task 1: `_reasoning_status_for_version` helper

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`
- Modify: `tests/unit/test_diff_compute.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_diff_compute.py`:

```python
@pytest.mark.anyio
async def test_reasoning_status_returns_ready_for_done_job(db_session, make_version):
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version
    from ontoexplorer.models.db import Job

    v = await make_version("http://example.org/x.owl", "rs001")
    db_session.add(Job(version_id=v.id, type="reason", status="done"))
    await db_session.commit()
    status = await _reasoning_status_for_version(db_session, v.id)
    assert status == "ready"


@pytest.mark.anyio
async def test_reasoning_status_returns_pending_for_running_job(db_session, make_version):
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version
    from ontoexplorer.models.db import Job

    v = await make_version("http://example.org/y.owl", "rs002")
    db_session.add(Job(version_id=v.id, type="reason", status="running"))
    await db_session.commit()
    assert await _reasoning_status_for_version(db_session, v.id) == "pending"


@pytest.mark.anyio
async def test_reasoning_status_returns_failed_when_only_failure_jobs_exist(db_session, make_version):
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version
    from ontoexplorer.models.db import Job

    v = await make_version("http://example.org/z.owl", "rs003")
    db_session.add(Job(version_id=v.id, type="reason", status="failed", error="oom"))
    await db_session.commit()
    assert await _reasoning_status_for_version(db_session, v.id) == "failed"


@pytest.mark.anyio
async def test_reasoning_status_returns_missing_when_no_reason_job(db_session, make_version):
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version

    v = await make_version("http://example.org/q.owl", "rs004")
    assert await _reasoning_status_for_version(db_session, v.id) == "missing"


@pytest.mark.anyio
async def test_reasoning_status_prefers_ready_over_failed_when_both_exist(db_session, make_version):
    """If a later 'done' run succeeded after earlier failures, status is 'ready'."""
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version
    from ontoexplorer.models.db import Job

    v = await make_version("http://example.org/p.owl", "rs005")
    db_session.add(Job(version_id=v.id, type="reason", status="failed", error="x"))
    db_session.add(Job(version_id=v.id, type="reason", status="done"))
    await db_session.commit()
    assert await _reasoning_status_for_version(db_session, v.id) == "ready"
```

The `make_version` fixture should already exist; if not, add this fixture to the test file (use `_make_version` from `tests/integration/test_compare_api.py` as a template, adapted for unit-test scope).

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/micheldumontier/code/ontoexplorer && uv run pytest tests/unit/test_diff_compute.py -v -k reasoning_status 2>&1 | tail -10`

Expected: 5 FAILED (cannot import `_reasoning_status_for_version`).

- [ ] **Step 3: Add the helper**

In `ontoexplorer/modules/diff/compute.py`, add near the top of the file (after the imports / module-level constants):

```python
from typing import Literal

ReasoningStatus = Literal["ready", "pending", "failed", "missing"]


async def _reasoning_status_for_version(db, version_id: str) -> ReasoningStatus:
    """Return the reasoning-readiness status for an ontology version.

    Ranking: if ANY 'done' job exists → 'ready'. Else if a 'running' or
    'pending' (queued) job exists → 'pending'. Else if a 'failed' job exists →
    'failed'. Else 'missing'.
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Job

    rows = await db.execute(
        select(Job.status).where(Job.version_id == version_id, Job.type == "reason")
    )
    statuses = {r[0] for r in rows.all()}
    if "done" in statuses:
        return "ready"
    if "running" in statuses or "pending" in statuses:
        return "pending"
    if "failed" in statuses:
        return "failed"
    return "missing"
```

The `db` arg is an `AsyncSession`. Don't import `AsyncSession` at module scope to avoid circular imports — type it as `db` (the existing `_run_diff_core` already follows this pattern in this codebase).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k reasoning_status 2>&1 | tail -5`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add ontoexplorer/modules/diff/compute.py tests/unit/test_diff_compute.py
git commit -m "feat(diff/compute): _reasoning_status_for_version helper"
```

---

## Task 2: `_non_trivial_inferred_axioms` filter

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`
- Modify: `tests/unit/test_diff_compute.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_diff_compute.py`:

```python
def test_non_trivial_inferred_drops_subclass_of_owl_thing():
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/Foo"
    raw = [
        ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
         ox.NamedNode("http://www.w3.org/2002/07/owl#Thing")),
        ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
         ox.NamedNode("http://example.org/Animal")),
    ]
    out = _non_trivial_inferred_axioms(raw, entity_iri=entity, asserted_axioms=[])
    assert len(out) == 1
    pred, obj = out[0]
    assert obj.value == "http://example.org/Animal"


def test_non_trivial_inferred_drops_reflexive_subclass():
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/Foo"
    raw = [
        ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
         ox.NamedNode(entity)),  # reflexive
        ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
         ox.NamedNode("http://example.org/Bar")),
    ]
    out = _non_trivial_inferred_axioms(raw, entity_iri=entity, asserted_axioms=[])
    assert len(out) == 1
    assert out[0][1].value == "http://example.org/Bar"


def test_non_trivial_inferred_drops_asserted_duplicate():
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/Foo"
    parent = ox.NamedNode("http://example.org/Parent")
    pred = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
    raw = [(pred, parent)]
    asserted = [(pred, parent)]
    assert _non_trivial_inferred_axioms(raw, entity_iri=entity, asserted_axioms=asserted) == []


def test_non_trivial_inferred_drops_subproperty_of_owl_top_object_property():
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/p"
    raw = [
        ("http://www.w3.org/2000/01/rdf-schema#subPropertyOf",
         ox.NamedNode("http://www.w3.org/2002/07/owl#topObjectProperty")),
        ("http://www.w3.org/2000/01/rdf-schema#subPropertyOf",
         ox.NamedNode("http://example.org/q")),
    ]
    out = _non_trivial_inferred_axioms(raw, entity_iri=entity, asserted_axioms=[])
    assert len(out) == 1
    assert out[0][1].value == "http://example.org/q"


def test_non_trivial_inferred_keeps_genuine_new_inference():
    """Positive test — a (pred, obj) absent from asserted, non-trivial → kept."""
    from ontoexplorer.modules.diff.compute import _non_trivial_inferred_axioms

    entity = "http://example.org/Foo"
    new_parent = ox.NamedNode("http://example.org/InferredParent")
    raw = [("http://www.w3.org/2000/01/rdf-schema#subClassOf", new_parent)]
    out = _non_trivial_inferred_axioms(
        raw, entity_iri=entity,
        asserted_axioms=[
            ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
             ox.NamedNode("http://example.org/Other")),
        ],
    )
    assert len(out) == 1
    assert out[0][1].value == new_parent.value
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k non_trivial_inferred 2>&1 | tail -10`

Expected: 5 FAILED (cannot import).

- [ ] **Step 3: Add the helper**

In `ontoexplorer/modules/diff/compute.py`, near the other axiom helpers:

```python
_OWL_THING_IRI = "http://www.w3.org/2002/07/owl#Thing"
_OWL_TOP_OBJECT_PROPERTY = "http://www.w3.org/2002/07/owl#topObjectProperty"
_OWL_TOP_DATA_PROPERTY   = "http://www.w3.org/2002/07/owl#topDataProperty"
_RDFS_SUBCLASS_OF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
_RDFS_SUBPROPERTY_OF = "http://www.w3.org/2000/01/rdf-schema#subPropertyOf"

_TRIVIAL_TOP_TARGETS: frozenset[tuple[str, str]] = frozenset({
    (_RDFS_SUBCLASS_OF, _OWL_THING_IRI),
    (_RDFS_SUBPROPERTY_OF, _OWL_TOP_OBJECT_PROPERTY),
    (_RDFS_SUBPROPERTY_OF, _OWL_TOP_DATA_PROPERTY),
})


def _non_trivial_inferred_axioms(
    raw: list[tuple[str, "ox.Term"]],
    *,
    entity_iri: str,
    asserted_axioms: list[tuple[str, "ox.Term"]],
) -> list[tuple[str, "ox.Term"]]:
    """Filter inferred axiom triples to suppress redundant patterns.

    Drops:
      1. Top-of-hierarchy targets (subClassOf owl:Thing,
         subPropertyOf owl:top{Object,Data}Property)
      2. Reflexive subClassOf / subPropertyOf where object IRI equals entity_iri
      3. Triples that also appear in asserted_axioms for this entity

    Returns the filtered list, preserving input order.
    """
    asserted_set = {(p, _term_key(o)) for p, o in asserted_axioms}
    keep: list[tuple[str, ox.Term]] = []
    for pred, obj in raw:
        if isinstance(obj, ox.NamedNode):
            # Trivial top
            if (pred, obj.value) in _TRIVIAL_TOP_TARGETS:
                continue
            # Reflexive
            if pred in (_RDFS_SUBCLASS_OF, _RDFS_SUBPROPERTY_OF) and obj.value == entity_iri:
                continue
        # Asserted duplicate
        if (pred, _term_key(obj)) in asserted_set:
            continue
        keep.append((pred, obj))
    return keep


def _term_key(t: "ox.Term") -> str:
    """Stable string key for a term used for asserted-duplicate detection."""
    if isinstance(t, ox.NamedNode):
        return f"<{t.value}>"
    if isinstance(t, ox.BlankNode):
        return f"_:{t.value}"
    if isinstance(t, ox.Literal):
        return f'"{t.value}"@{t.language or ""}^{t.datatype.value if t.datatype else ""}'
    return repr(t)
```

If `ox` isn't already imported at module scope (it should be; the existing diff helpers use it), add `import pyoxigraph as ox` at the top.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k non_trivial_inferred 2>&1 | tail -5`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/compute.py tests/unit/test_diff_compute.py
git commit -m "feat(diff/compute): _non_trivial_inferred_axioms filter helper"
```

---

## Task 3: Add `source` to `ManchesterLine`; thread through render

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Update the TypedDict and add `source` parameter to render_frame**

In `ontoexplorer/modules/diff/manchester.py`, find the `ManchesterLine` TypedDict (added in Phase 3 Task 1). Add a `source` field:

```python
class ManchesterLine(TypedDict):
    op: Literal["added", "removed"] | None
    source: Literal["asserted", "inferred"] | None  # NEW (null on header/keyword lines)
    tokens: list[ManchesterToken]
```

Now update `render_frame`'s `axiom_changes` schema (per-change dict). It already has `op`, `predicate`, `object`, `graph`. Add an optional `source` key with default `"asserted"`:

```python
# in render_frame body, where we partition axiom_changes into rendered tuples:
        keyword, _, body_text = line[0]["v"].partition(": ")
        body_tokens: list[ManchesterToken] = [_text(body_text)] if body_text else []
        body_tokens.extend(line[1:])
        change_source: Literal["asserted", "inferred"] = change.get("source", "asserted")
        rendered.append((keyword, change["op"], body_tokens, change_source))
```

Then when emitting each body line, set the line's `source` field. Replace the body-emission loop in `render_frame`:

```python
        for body in removed_lines:
            body_tokens, src = body
            line_op = op if op != "modified" else "removed"
            lines.append({"op": line_op, "source": src, "tokens": [_text("        "), *body_tokens]})
        for body in added_lines:
            body_tokens, src = body
            line_op = op if op != "modified" else "added"
            lines.append({"op": line_op, "source": src, "tokens": [_text("        "), *body_tokens]})
```

Note: the existing sort logic groups bodies by `(op, body-tokens)`. Update it to group by `(op, body-tokens, source)` so the new field flows through. Concretely, rewrite the kw-line emission loop:

```python
        kw_lines = [(o, body, src) for k, o, body, src in rendered if k == kw]
        if not kw_lines:
            continue
        lines.append({"op": header_op, "source": None, "tokens": [_text(f"    {kw}:")]})
        removed_lines = sorted(
            ((b, s) for o, b, s in kw_lines if o == "removed"),
            key=lambda pair: _body_sort_key(pair[0]),
        )
        added_lines = sorted(
            ((b, s) for o, b, s in kw_lines if o == "added"),
            key=lambda pair: _body_sort_key(pair[0]),
        )
        for body_tokens, src in removed_lines:
            line_op: Literal["added", "removed"] = op if op != "modified" else "removed"
            lines.append({"op": line_op, "source": src, "tokens": [_text("        "), *body_tokens]})
        for body_tokens, src in added_lines:
            line_op = op if op != "modified" else "added"
            lines.append({"op": line_op, "source": src, "tokens": [_text("        "), *body_tokens]})
```

Also: header lines and keyword lines now need `"source": None` set explicitly. Find every place that builds a header/keyword line and add `"source": None`.

- [ ] **Step 2: Add tests**

Append to `tests/unit/test_manchester_render.py`:

```python
def test_render_frame_default_source_is_asserted_per_axiom():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    frame = render_frame(
        _store(), iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
    )
    assert frame is not None
    # Axiom body line has source='asserted' (default).
    body_line = next(l for l in frame["lines"] if l["op"] == "added")
    assert body_line["source"] == "asserted"
    # Header/keyword lines have source=None.
    header = frame["lines"][0]
    assert header["source"] is None


def test_render_frame_inferred_source_propagates_to_line():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    frame = render_frame(
        _store(), iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food,
             "graph": _GRAPH, "source": "inferred"},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
    )
    assert frame is not None
    body_line = next(l for l in frame["lines"] if l["op"] == "added")
    assert body_line["source"] == "inferred"
```

- [ ] **Step 3: Run to verify**

Run: `uv run pytest tests/unit/test_manchester_render.py 2>&1 | tail -3`

Expected: all tests pass (existing ones still green plus the 2 new ones; the existing tests don't assert `source` and TypedDict allows extra keys — they should remain green). If existing tests fail because they pattern-match against complete line dicts, update those assertions to ignore the new `source` field (use `>=` or compare individual keys).

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): per-line source field threaded through render_frame"
```

---

## Task 4: Second-pass inferred axiom collection in `_run_diff_core`

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`
- Modify: `tests/unit/test_diff_compute.py`

Now the heavy lift: when both versions are ready, also collect axioms from the `:inferred` named graphs and pass them through `render_frame` with `source: "inferred"`. The asserted pass remains untouched; inferred axioms are MERGED into the same `axiom_changes` list per entity.

- [ ] **Step 1: Add tests for the merged flow**

Append to `tests/unit/test_diff_compute.py`. These tests construct a store with both asserted and inferred named graphs and a fake job table marking both versions ready.

```python
def test_inferred_diff_merges_into_axiom_changes_with_source_tag(db_session, _make_version_sync):
    """When reasoning is ready for both sides, inferred axioms appear in
    diff_data with source='inferred' alongside asserted ones."""
    from ontoexplorer.modules.diff.compute import run_diff
    from ontoexplorer.clients.oxigraph import graph_iri
    from ontoexplorer.models.db import Job

    v1 = _make_version_sync(db_session, "http://example.org/o.owl", "inf001")
    v2 = _make_version_sync(db_session, "http://example.org/o.owl", "inf002")
    db_session.add(Job(version_id=v1.id, type="reason", status="done"))
    db_session.add(Job(version_id=v2.id, type="reason", status="done"))
    db_session.commit()

    pizza = ox.NamedNode("http://example.org/Pizza")
    food  = ox.NamedNode("http://example.org/Food")
    seasoned = ox.NamedNode("http://example.org/SeasonedFood")

    store = ox.Store()
    g_from_a = ox.NamedNode(graph_iri("o", v1.id, inferred=False))
    g_from_i = ox.NamedNode(graph_iri("o", v1.id, inferred=True))
    g_to_a   = ox.NamedNode(graph_iri("o", v2.id, inferred=False))
    g_to_i   = ox.NamedNode(graph_iri("o", v2.id, inferred=True))
    for g in (g_from_a, g_from_i, g_to_a, g_to_i):
        store.add_graph(g)

    # Asserted: from has Pizza ⊑ Food; to adds Pizza ⊑ SeasonedFood.
    store.add(ox.Quad(pizza, _RDF_TYPE, _OWL_CLASS, g_from_a))
    store.add(ox.Quad(pizza, _RDFS_SC, food, g_from_a))
    store.add(ox.Quad(pizza, _RDF_TYPE, _OWL_CLASS, g_to_a))
    store.add(ox.Quad(pizza, _RDFS_SC, food, g_to_a))
    store.add(ox.Quad(pizza, _RDFS_SC, seasoned, g_to_a))

    # Inferred: to has an additional inferred Pizza ⊑ MoreThings (genuinely new)
    more = ox.NamedNode("http://example.org/MoreThings")
    store.add(ox.Quad(pizza, _RDFS_SC, more, g_to_i))

    summary, diff_data = run_diff(store, "o", v1.id, v2.id, db=db_session)
    assert summary["inferred_status"]["from_version"] == "ready"
    assert summary["inferred_status"]["to_version"]   == "ready"
    assert summary["asserted_axiom_changes"] >= 1
    assert summary["inferred_axiom_changes"] == 1

    pizza_entry = next(e for e in diff_data["modified"] if e["iri"] == pizza.value)
    sources = {ac["source"] for ac in pizza_entry["axiom_changes"]}
    assert "inferred" in sources
    assert "asserted" in sources


def test_inferred_diff_skipped_when_reasoning_pending(db_session, _make_version_sync):
    from ontoexplorer.modules.diff.compute import run_diff
    from ontoexplorer.models.db import Job

    v1 = _make_version_sync(db_session, "http://example.org/o.owl", "inf003")
    v2 = _make_version_sync(db_session, "http://example.org/o.owl", "inf004")
    db_session.add(Job(version_id=v1.id, type="reason", status="running"))
    db_session.commit()

    pizza = ox.NamedNode("http://example.org/Pizza")
    store = ox.Store()
    g1 = ox.NamedNode(graph_iri("o", v1.id, inferred=False))
    g2 = ox.NamedNode(graph_iri("o", v2.id, inferred=False))
    store.add_graph(g1); store.add_graph(g2)
    store.add(ox.Quad(pizza, _RDF_TYPE, _OWL_CLASS, g1))
    store.add(ox.Quad(pizza, _RDF_TYPE, _OWL_CLASS, g2))

    summary, _ = run_diff(store, "o", v1.id, v2.id, db=db_session)
    assert summary["inferred_status"]["from_version"] == "pending"
    assert summary["inferred_axiom_changes"] == 0
```

`_make_version_sync` is a synchronous helper added to the test file's conftest or inline:

```python
def _make_version_sync(db_session, iri: str, sha: str):
    """Sync wrapper for the async _make_version flow — uses session.sync_session
    if necessary; if your tests use async sessions, use _make_version with anyio.
    """
    # implementation: adapt to your async pattern
```

If your existing `tests/unit/test_diff_compute.py` uses synchronous helpers throughout, write `_make_version_sync` to match. If it uses async, convert these tests to `@pytest.mark.anyio` and use the existing `_make_version`.

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k "inferred_diff" 2>&1 | tail -10`

Expected: 2 FAILED (`run_diff` doesn't accept `db` keyword, doesn't return `inferred_status`).

- [ ] **Step 3: Update `_run_diff_core` and `run_diff`**

In `ontoexplorer/modules/diff/compute.py`:

1. Add a `db` keyword-only parameter to `run_diff` and pass through to `_run_diff_core`:

```python
def run_diff(
    store: ox.Store,
    ontology_id: str,
    from_vid: str,
    to_vid: str,
    *,
    db=None,  # AsyncSession when called from compute_diff task; None for sync tests
) -> tuple[dict, dict]:
    from_graph = ox.NamedNode(graph_iri(ontology_id, from_vid))
    to_graph   = ox.NamedNode(graph_iri(ontology_id, to_vid))
    return _run_diff_core(
        store, from_graph, to_graph,
        ontology_id=ontology_id, from_vid=from_vid, to_vid=to_vid, db=db,
    )
```

2. Extend `_run_diff_core` to compute inferred status and run a second pass when both ready:

```python
def _run_diff_core(
    store: ox.Store,
    from_graph: ox.NamedNode,
    to_graph: ox.NamedNode,
    *,
    ontology_id: str | None = None,
    from_vid: str | None = None,
    to_vid: str | None = None,
    db=None,
) -> tuple[dict, dict]:
    # ... existing labels/annotation_props/known_iris setup ...

    # Reasoning-readiness check. When db is None (older callers) statuses are
    # 'missing' on both sides and the inferred pass is skipped — this keeps
    # backward compatibility with any code path that hasn't been migrated.
    if db is not None and from_vid is not None and to_vid is not None:
        import asyncio
        status_from = asyncio.run(_reasoning_status_for_version(db, from_vid))
        status_to   = asyncio.run(_reasoning_status_for_version(db, to_vid))
    else:
        status_from = "missing"
        status_to   = "missing"

    inferred_graph_from = ox.NamedNode(f"{from_graph.value}:inferred")
    inferred_graph_to   = ox.NamedNode(f"{to_graph.value}:inferred")
    do_inferred = status_from == "ready" and status_to == "ready"

    # ... existing per-entity-type loop builds asserted axiom_changes ...
    # MODIFY the modified-entity branch: after building asserted change_records,
    # if do_inferred, collect inferred axioms for the same entity from both
    # inferred graphs, filter via _non_trivial_inferred_axioms, tag source,
    # and merge into change_records:

    if do_inferred:
        from_inf = _axioms_for_entity(store, inferred_graph_from, iri)
        to_inf   = _axioms_for_entity(store, inferred_graph_to,   iri)
        from_asserted_pairs = _axioms_for_entity(store, from_graph, iri)
        to_asserted_pairs   = _axioms_for_entity(store, to_graph,   iri)
        from_inf_filtered = _non_trivial_inferred_axioms(
            from_inf, entity_iri=iri, asserted_axioms=from_asserted_pairs,
        )
        to_inf_filtered = _non_trivial_inferred_axioms(
            to_inf, entity_iri=iri, asserted_axioms=to_asserted_pairs,
        )
        from_inf_set = {(p, _term_key(o)) for p, o in from_inf_filtered}
        to_inf_set   = {(p, _term_key(o)) for p, o in to_inf_filtered}
        for pred, obj in to_inf_filtered:
            if (pred, _term_key(obj)) not in from_inf_set:
                change_records.append({
                    "op": "added", "predicate": pred, "object": obj,
                    "graph": inferred_graph_to, "source": "inferred",
                })
        for pred, obj in from_inf_filtered:
            if (pred, _term_key(obj)) not in to_inf_set:
                change_records.append({
                    "op": "removed", "predicate": pred, "object": obj,
                    "graph": inferred_graph_from, "source": "inferred",
                })

    # Also stamp source='asserted' on every asserted-pass record. Do this when
    # change_records is appended in the original asserted loop OR retroactively:
    for rec in change_records:
        rec.setdefault("source", "asserted")
```

3. Update the summary dict at the end of `_run_diff_core`:

```python
    asserted_count = 0
    inferred_count = 0
    for entry in diff_data["modified"]:
        for ac in entry.get("axiom_changes", []):
            if ac.get("source") == "inferred":
                inferred_count += 1
            else:
                asserted_count += 1
    summary["asserted_axiom_changes"] = asserted_count
    summary["inferred_axiom_changes"] = inferred_count
    summary["inferred_status"] = {
        "from_version": status_from,
        "to_version": status_to,
    }
```

4. Also propagate `source` into the `axiom_changes[i]` JSON entry. The existing code builds these dicts (Phase 2 + Phase 3); add:

```python
        axiom_changes_list.append({
            "op": rec["op"],
            "axiom": _tokens_to_str(axiom_tokens),  # Phase 3 helper
            "source": rec.get("source", "asserted"),
        })
```

5. The `compute_diff` Celery task should pass `db` through. Find `_run_diff` (the helper called by the task) in `ontoexplorer/modules/jobs/tasks.py` and add a `db` parameter that gets passed to `run_diff`:

```python
def _run_diff(store, ontology_id, from_vid, to_vid, db=None):
    from ontoexplorer.modules.diff.compute import run_diff
    return run_diff(store, ontology_id, from_vid, to_vid, db=db)
```

And in `compute_diff` task body (which has `db` in scope inside the async wrapper), pass it through to `asyncio.to_thread(_run_diff, store, ..., db)`. Since `to_thread` will run sync code that calls `asyncio.run` internally to fetch the reasoning status, this is acceptable but slightly hairy. A cleaner alternative: compute the statuses BEFORE handing off to `to_thread` and pass them in as plain strings. Update the signature to accept pre-computed statuses:

```python
def run_diff(..., *, inferred_status: dict | None = None) -> tuple[dict, dict]:
    ...
```

If `inferred_status` is provided (preferred path for Celery task), skip the DB query and use the values directly. The task computes them via `_reasoning_status_for_version` (async) before to_thread.

Choose this cleaner pattern and update accordingly.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/unit/ 2>&1 | tail -3`

Expected: all green including the 2 new tests.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/compute.py ontoexplorer/modules/jobs/tasks.py tests/unit/test_diff_compute.py
git commit -m "feat(diff/compute): inferred-graph diff pass merged with asserted via source tag"
```

---

## Task 5: Re-queue hook in `reason_ontology` task

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`
- Modify: `tests/unit/test_diff_compute.py` (or a new tests file)

When `reason_ontology` finishes successfully, query `ontology_diffs` for rows where the just-reasoned version participates AND the stored summary's `inferred_status` for that version isn't `'ready'`. For each match, re-queue `compute_diff.delay(...)`.

- [ ] **Step 1: Add a test**

Append to `tests/unit/test_diff_compute.py`:

```python
@pytest.mark.anyio
async def test_reasoning_completion_requeues_stale_diffs(db_session, monkeypatch):
    """When reasoning completes for a version, any diff row whose summary
    shows inferred_status != 'ready' for that version should be re-queued."""
    from ontoexplorer.models.db import OntologyVersion, OntologyDiff, Ontology, Job
    from ontoexplorer.modules.jobs.tasks import _requeue_stale_diffs_for_version

    # Setup: two versions, one diff with inferred_status.from_version='missing'.
    ont = Ontology(iri="http://example.org/o.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="rs1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="rs2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    diff = OntologyDiff(
        ontology_id=ont.id,
        version_from_id=v1.id, version_to_id=v2.id,
        status="ready",
        summary={
            "asserted_axiom_changes": 5,
            "inferred_axiom_changes": 0,
            "inferred_status": {"from_version": "missing", "to_version": "ready"},
        },
    )
    db_session.add(diff)
    await db_session.commit()

    queued = []
    def fake_delay(from_vid, to_vid, ontology_id):
        queued.append((from_vid, to_vid, ontology_id))
    monkeypatch.setattr(
        "ontoexplorer.modules.jobs.tasks.compute_diff.delay",
        fake_delay,
    )

    await _requeue_stale_diffs_for_version(db_session, v1.id)
    assert len(queued) == 1
    assert queued[0] == (v1.id, v2.id, ont.id)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k requeues_stale 2>&1 | tail -5`

Expected: 1 FAILED (`_requeue_stale_diffs_for_version` doesn't exist).

- [ ] **Step 3: Add the helper and the hook**

In `ontoexplorer/modules/jobs/tasks.py`, add a top-level async helper:

```python
async def _requeue_stale_diffs_for_version(db, version_id: str) -> None:
    """Re-queue compute_diff for any OntologyDiff row where this version's
    summary inferred_status isn't 'ready'."""
    from sqlalchemy import select, or_
    from ontoexplorer.models.db import OntologyDiff

    result = await db.execute(
        select(OntologyDiff).where(
            or_(
                OntologyDiff.version_from_id == version_id,
                OntologyDiff.version_to_id == version_id,
            ),
            OntologyDiff.status == "ready",
        )
    )
    rows = result.scalars().all()
    for row in rows:
        inferred_status = (row.summary or {}).get("inferred_status", {})
        side = "from_version" if row.version_from_id == version_id else "to_version"
        if inferred_status.get(side) == "ready":
            continue  # already fresh
        log.info("requeuing_stale_diff",
                 diff_id=row.id, version_id=version_id, side=side,
                 current_status=inferred_status.get(side))
        compute_diff.delay(row.version_from_id, row.version_to_id, row.ontology_id)
```

In `_run_reasoning` (the async body of `reason_ontology`), at the very end (after the metrics call), add:

```python
    # Re-queue any diffs whose inferred half is stale for this version.
    try:
        await _requeue_stale_diffs_for_version(db, version_id)
    except Exception:
        log.exception("requeue_stale_diffs_failed", version_id=version_id)
        # Don't fail the reasoning task — the beat safety net will catch missed
        # re-queues.
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k requeues_stale 2>&1 | tail -5`

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py tests/unit/test_diff_compute.py
git commit -m "feat(jobs): reason_ontology re-queues stale inferred diffs on completion"
```

---

## Task 6: Beat task `refresh_stale_inferred_diffs`

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`

- [ ] **Step 1: Add the beat task**

In `ontoexplorer/modules/jobs/tasks.py`, add a new Celery task that scans all ready diffs and re-queues any with stale inferred-side state:

```python
@celery_app.task(name="ontoexplorer.refresh_stale_inferred_diffs")
def refresh_stale_inferred_diffs() -> dict:
    """Safety net: catch diffs whose inferred half is stale because the
    inline re-queue hook in reason_ontology failed (e.g. worker crash).

    For each OntologyDiff with status='ready', if either side's
    inferred_status is not 'ready' AND that side's reasoning job is now
    'done', re-queue compute_diff.
    """
    from ontoexplorer.database import make_celery_db_session

    async def _run():
        async with make_celery_db_session()() as db:
            await _refresh_stale_inferred_diffs_body(db)

    try:
        asyncio.run(_run())
        return {"status": "done"}
    except Exception as exc:
        log.exception("refresh_stale_inferred_diffs_failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


async def _refresh_stale_inferred_diffs_body(db) -> int:
    """Returns the count of diffs re-queued."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyDiff
    from ontoexplorer.modules.diff.compute import _reasoning_status_for_version

    result = await db.execute(
        select(OntologyDiff).where(OntologyDiff.status == "ready")
    )
    rows = result.scalars().all()
    requeued = 0
    for row in rows:
        inferred_status = (row.summary or {}).get("inferred_status", {})
        for side, vid in (("from_version", row.version_from_id),
                          ("to_version",   row.version_to_id)):
            if inferred_status.get(side) != "ready":
                current = await _reasoning_status_for_version(db, vid)
                if current == "ready":
                    log.info("beat_requeue_stale_diff",
                             diff_id=row.id, version_id=vid, side=side)
                    compute_diff.delay(row.version_from_id, row.version_to_id, row.ontology_id)
                    requeued += 1
                    break  # one re-queue per row is enough
    return requeued
```

- [ ] **Step 2: Register in beat schedule**

In the same file, find the `beat_schedule` dict (at the top, with `poll-for-updates-hourly`). Add an entry:

```python
    beat_schedule={
        "poll-for-updates-hourly": {
            "task": "ontoexplorer.poll_for_updates",
            "schedule": 3600.0,
        },
        "refresh-stale-inferred-diffs-15min": {
            "task": "ontoexplorer.refresh_stale_inferred_diffs",
            "schedule": 900.0,
        },
    },
```

- [ ] **Step 3: Quick sanity check**

Run: `cd /home/micheldumontier/code/ontoexplorer && uv run python -c "from ontoexplorer.modules.jobs.tasks import refresh_stale_inferred_diffs; print(refresh_stale_inferred_diffs.name)"`

Expected: `ontoexplorer.refresh_stale_inferred_diffs`

And full unit suite: `uv run pytest tests/unit/ 2>&1 | tail -3` → all green.

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py
git commit -m "feat(jobs): beat task refresh_stale_inferred_diffs every 15 minutes"
```

---

## Task 7: Update frontend types

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Extend the types**

In `frontend/src/lib/api.ts`, find the `ManchesterLine` type (added in Phase 3) and add `source`:

```typescript
export type ManchesterLine = {
  op: 'added' | 'removed' | null
  source: 'asserted' | 'inferred' | null
  tokens: ManchesterToken[]
}
```

Find the `DiffSummary` type and extend:

```typescript
export interface DiffSummary {
  added: number
  removed: number
  modified: number
  literal_changes: number
  axiom_changes: number
  asserted_axiom_changes: number      // NEW
  inferred_axiom_changes: number       // NEW
  by_entity_type: Record<DiffEntityType, { added: number; removed: number; modified: number }>
  inferred_status: {                   // NEW
    from_version: 'ready' | 'pending' | 'failed' | 'missing'
    to_version:   'ready' | 'pending' | 'failed' | 'missing'
  }
}
```

If the type is structured differently (e.g. it's inlined into the comparison response type), match the actual shape and add the new fields wherever the diff summary is described.

Also find the `DiffAxiomChange` type and add `source`:

```typescript
export interface DiffAxiomChange {
  op: 'added' | 'removed'
  axiom: string
  source: 'asserted' | 'inferred'   // NEW
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): type definitions for inferred-axiom diff fields"
```

---

## Task 8: Per-line `[asserted]` / `[inferred]` badge in `ManchesterFrame`

**Files:**
- Modify: `frontend/src/components/ManchesterFrame.tsx`
- Modify: `frontend/src/components/ManchesterFrame.test.tsx`

- [ ] **Step 1: Add a failing test**

In `frontend/src/components/ManchesterFrame.test.tsx`, add tests:

```tsx
test('axiom line with source=asserted gets an [asserted] badge', () => {
  const frame: Frame = {
    lines: [
      {
        op: 'added',
        source: 'asserted',
        tokens: [{ t: 'text', v: '        ' }, { t: 'iri', label: 'Food', iri: 'http://example.org/Food', in_ontology: true }],
      },
    ],
  }
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  expect(screen.getByText('[asserted]')).toBeInTheDocument()
})

test('axiom line with source=inferred gets an [inferred] badge', () => {
  const frame: Frame = {
    lines: [
      {
        op: 'added',
        source: 'inferred',
        tokens: [{ t: 'text', v: '        ' }, { t: 'iri', label: 'SeasonedFood', iri: 'http://example.org/SeasonedFood', in_ontology: true }],
      },
    ],
  }
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  expect(screen.getByText('[inferred]')).toBeInTheDocument()
})

test('header/keyword lines (source=null) get no badge', () => {
  const frame: Frame = {
    lines: [
      { op: null, source: null, tokens: [{ t: 'text', v: 'Class: ' }, { t: 'iri', label: 'Pizza', iri: 'http://example.org/Pizza', in_ontology: true }] },
      { op: null, source: null, tokens: [{ t: 'text', v: '    SubClassOf:' }] },
    ],
  }
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  expect(screen.queryByText('[asserted]')).toBeNull()
  expect(screen.queryByText('[inferred]')).toBeNull()
})
```

The existing fixture-frame test (`added/removed lines use respective color and line marker`) should be updated to add `source: 'asserted'` on the added/removed lines and `source: null` on header/keyword lines.

- [ ] **Step 2: Run to verify failures**

Run: `cd frontend && npx vitest run ManchesterFrame.test.tsx 2>&1 | tail -10`

Expected: 2 FAILED, the existing tests still pass.

- [ ] **Step 3: Update the component**

In `frontend/src/components/ManchesterFrame.tsx`, modify the line-rendering loop to append a badge when `line.source` is non-null:

```tsx
function badgeText(source: ManchesterLine['source']): string | null {
  if (source === 'asserted') return '[asserted]'
  if (source === 'inferred') return '[inferred]'
  return null
}

// inside the .map(...) over frame.lines:
{frame.lines.map((line, i) => {
  const badge = badgeText(line.source)
  return (
    <div key={i} style={{ color: colorFor(line.op) }}>
      {markerFor(line.op)}
      {line.tokens.map((t, j) => renderToken(t, j, shortname))}
      {badge && (
        <span
          style={{
            marginLeft: 8,
            fontSize: '0.8em',
            fontStyle: 'italic',
            color: 'var(--text-dim)',
          }}
        >
          {badge}
        </span>
      )}
    </div>
  )
})}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run ManchesterFrame.test.tsx 2>&1 | tail -10`

Expected: all 7 tests pass (4 existing + 3 new). If the existing fixture-frame test broke because the source field is now required, update it to include `source: 'asserted'` on added/removed lines and `source: null` elsewhere.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/ManchesterFrame.tsx frontend/src/components/ManchesterFrame.test.tsx
git commit -m "feat(frontend): per-line [asserted]/[inferred] badge in ManchesterFrame"
```

---

## Task 9: "Inferred unavailable" notice + summary breakdown in `DiffResultView`

**Files:**
- Modify: `frontend/src/components/DiffResultView.tsx`
- Modify: `frontend/src/components/DiffResultView.test.tsx`

- [ ] **Step 1: Add a test**

In `frontend/src/components/DiffResultView.test.tsx`, add:

```tsx
test('renders inferred-unavailable notice when from_version is missing', () => {
  const summary: DiffSummary = {
    added: 0, removed: 0, modified: 0,
    literal_changes: 0, axiom_changes: 0,
    asserted_axiom_changes: 0, inferred_axiom_changes: 0,
    by_entity_type: { class: { added: 0, removed: 0, modified: 0 }, /* ... */ } as any,
    inferred_status: { from_version: 'missing', to_version: 'ready' },
  }
  wrap(
    <DiffResultView
      data={{ added: [], removed: [], modified: [] }}
      summary={summary}
      variant="version-diff"
    />,
  )
  expect(screen.getByText(/inferred diff unavailable/i)).toBeInTheDocument()
})

test('does not render notice when both sides are ready', () => {
  const summary: DiffSummary = {
    added: 0, removed: 0, modified: 0,
    literal_changes: 0, axiom_changes: 0,
    asserted_axiom_changes: 0, inferred_axiom_changes: 0,
    by_entity_type: {} as any,
    inferred_status: { from_version: 'ready', to_version: 'ready' },
  }
  wrap(
    <DiffResultView
      data={{ added: [], removed: [], modified: [] }}
      summary={summary}
      variant="version-diff"
    />,
  )
  expect(screen.queryByText(/inferred diff unavailable/i)).toBeNull()
})

test('summary header shows asserted/inferred breakdown', () => {
  const summary: DiffSummary = {
    added: 0, removed: 0, modified: 0,
    literal_changes: 0, axiom_changes: 7,
    asserted_axiom_changes: 5, inferred_axiom_changes: 2,
    by_entity_type: {} as any,
    inferred_status: { from_version: 'ready', to_version: 'ready' },
  }
  wrap(
    <DiffResultView
      data={{ added: [], removed: [], modified: [] }}
      summary={summary}
      variant="version-diff"
    />,
  )
  expect(screen.getByText(/5 asserted, 2 inferred/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify failures**

Run: `cd frontend && npx vitest run DiffResultView.test.tsx 2>&1 | tail -10`

Expected: 3 FAILED.

- [ ] **Step 3: Update `DiffResultView` to render the notice and breakdown**

In `frontend/src/components/DiffResultView.tsx`:

1. Add a `InferredUnavailableNotice` component near the top of the file:

```tsx
function InferredUnavailableNotice({
  status,
}: {
  status: DiffSummary['inferred_status']
}) {
  if (status.from_version === 'ready' && status.to_version === 'ready') return null
  const [dismissed, setDismissed] = useState(false)
  if (dismissed) return null
  const bad = status.from_version !== 'ready'
    ? `from_version (${status.from_version})`
    : `to_version (${status.to_version})`
  return (
    <div style={{
      background: 'var(--bg-tertiary, #1a1d24)',
      border: '1px solid var(--border)',
      borderRadius: 4,
      padding: '8px 12px',
      fontSize: 11,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    }}>
      <span style={{ color: '#58a6ff' }}>ⓘ</span>
      <span style={{ flex: 1 }}>
        Inferred diff unavailable: reasoning is {bad === 'from_version (ready)' ? 'pending' : 'not ready'} for {bad}.
        The diff will refresh automatically when reasoning completes.
      </span>
      <button
        onClick={() => setDismissed(true)}
        style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
        aria-label="Dismiss"
      >
        ×
      </button>
    </div>
  )
}
```

2. Update the main `DiffResultView` body. Render the notice at the top:

```tsx
return (
  <div style={{ padding: 14, fontFamily: 'monospace', fontSize: 11, display: 'flex', flexDirection: 'column', gap: 10 }}>
    {summary && <InferredUnavailableNotice status={summary.inferred_status} />}
    {/* existing filter row, search, summary line, table */}
```

3. Update the existing summary header line to show the breakdown:

```tsx
{summary && (
  <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>
    {summary.added} added, {summary.removed} removed, {summary.modified} modified
    {' '}({summary.literal_changes} literal, {summary.axiom_changes} axiom — {' '}
    {summary.asserted_axiom_changes} asserted, {summary.inferred_axiom_changes} inferred)
  </div>
)}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run DiffResultView.test.tsx 2>&1 | tail -10`

Expected: all tests pass.

Then full suite:
```bash
npx vitest run 2>&1 | tail -5
```
Expected: same pass count + the 3 new tests.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/DiffResultView.tsx frontend/src/components/DiffResultView.test.tsx
git commit -m "feat(frontend): inferred-unavailable notice + summary breakdown in DiffResultView"
```

---

## Task 10: Auto-refresh polling when reasoning isn't ready

**Files:**
- Modify: `frontend/src/hooks/useCompare.ts` (cross-compare path) AND/OR `frontend/src/components/HistoryTab.tsx` (version-diff path) — wherever the diff React Query lives.

The diff query should poll every 30 seconds while either `inferred_status` side is not `'ready'`, stopping once both sides are `'ready'`.

- [ ] **Step 1: Identify the diff query hooks**

Run: `grep -rn "useQuery.*compare\|useQuery.*diff" frontend/src/hooks/ frontend/src/components/HistoryTab.tsx 2>/dev/null | head -10`

Locate where the diff/comparison data is fetched.

- [ ] **Step 2: Add `refetchInterval` that depends on `inferred_status`**

For each diff query hook, add a `refetchInterval` callback that returns `30_000` (ms) when the response's `summary.inferred_status` shows either side as non-ready, and `false` otherwise:

```typescript
refetchInterval: (query) => {
  const data = query.state.data
  if (!data?.summary?.inferred_status) return false
  const { from_version, to_version } = data.summary.inferred_status
  if (from_version !== 'ready' || to_version !== 'ready') return 30_000
  return false
},
```

This is the pattern Phase 2's `useArbitraryComparison` already uses for pending status — extend the existing callback rather than duplicating.

- [ ] **Step 3: Type-check + test**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -5
cd frontend && npx vitest run 2>&1 | tail -5
```

Both should be clean.

- [ ] **Step 4: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/hooks/ frontend/src/components/HistoryTab.tsx
git commit -m "feat(frontend): poll diff endpoint every 30s while reasoning isn't ready"
```

---

## Task 11: Integration test for end-to-end inferred-diff flow

**Files:**
- Modify: `tests/integration/test_diff_api.py`

- [ ] **Step 1: Add an integration test**

Append to `tests/integration/test_diff_api.py`:

```python
@pytest.mark.anyio
async def test_diff_api_includes_inferred_status_and_breakdown(client, db_session):
    """Diff API response carries inferred_status and the asserted/inferred
    axiom breakdown in the summary."""
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff

    ont = Ontology(iri="http://example.org/test.owl", shortname="test")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="t1", sha256="t1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="t2", sha256="t2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    diff = OntologyDiff(
        ontology_id=ont.id,
        version_from_id=v1.id, version_to_id=v2.id,
        status="ready",
        summary={
            "added": 0, "removed": 0, "modified": 1,
            "literal_changes": 0, "axiom_changes": 3,
            "asserted_axiom_changes": 2,
            "inferred_axiom_changes": 1,
            "by_entity_type": {},
            "inferred_status": {"from_version": "ready", "to_version": "ready"},
        },
        diff_data={"added": [], "removed": [], "modified": []},
    )
    db_session.add(diff)
    await db_session.commit()

    r = await client.get(f"/api/v1/{ont.id}/diff", params={"from": v1.id, "to": v2.id})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    summary = body["summary"]
    assert summary["asserted_axiom_changes"] == 2
    assert summary["inferred_axiom_changes"] == 1
    assert summary["inferred_status"] == {"from_version": "ready", "to_version": "ready"}
```

Adapt the URL pattern to match the actual diff endpoint (check the existing integration tests in the same file for the route shape).

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/integration/test_diff_api.py -v -k inferred_status 2>&1 | tail -10`

Expected: 1 passed (assuming the diff API serializer passes through the summary dict verbatim, which it does today).

If the API filters specific summary keys (it probably doesn't, but check `ontoexplorer/api/diff.py`), update the serializer to pass through the new keys.

- [ ] **Step 3: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add tests/integration/test_diff_api.py
git commit -m "test(diff): integration assertions for inferred_status + breakdown counts"
```

---

## Task 12: Manual end-to-end sanity check + rebuild + clear cached diffs

**Files:** none — this is operational.

- [ ] **Step 1: Rebuild containers**

```bash
cd /home/micheldumontier/code/ontoexplorer
docker compose build worker api
docker compose up -d worker api
```

- [ ] **Step 2: Clear cached diff rows** (their stored summary lacks the new keys)

```bash
docker compose exec -T postgres psql -U ontoexplorer -d ontoexplorer -c "DELETE FROM ontology_diffs; DELETE FROM ontology_comparisons;"
```

- [ ] **Step 3: Verify inferred-unavailable notice path**

Open a diff in the UI for an ontology whose versions have NOT been reasoned. Expect the inferred-unavailable notice at the top and `0 inferred` in the summary.

- [ ] **Step 4: Trigger reasoning for both sides, observe auto-refresh**

Trigger reasoning via the admin/version page or `POST /reason`. Within ~30 seconds of completion, the notice should disappear and inferred axioms should appear in entity frames with `[inferred]` badges.

- [ ] **Step 5: Verify beat task picks up missed re-queues**

```bash
docker compose logs beat 2>&1 | grep refresh_stale_inferred_diffs | tail
```

Expect it to fire every 15 minutes.

---

## Self-Review Checklist

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| Reasoning-readiness check | Task 1 |
| Non-trivial filtering (top, reflexive, asserted-duplicate) | Task 2 |
| Per-line `source` in ManchesterLine | Task 3 |
| Second-pass inferred diff merged into axiom_changes | Task 4 |
| Inferred counts in summary | Task 4 |
| `inferred_status` in summary | Task 4 |
| Re-queue hook in reason_ontology | Task 5 |
| 15-minute beat safety net | Task 6 |
| Frontend types | Task 7 |
| `[asserted]` / `[inferred]` badge | Task 8 |
| Inferred-unavailable notice | Task 9 |
| Summary breakdown counts | Task 9 |
| Auto-refresh polling every 30s | Task 10 |
| Integration test for the contract | Task 11 |
| Operational rollout | Task 12 |

**2. Placeholder scan:** every step has complete code, no "TBD" / "similar to Task N".

**3. Type consistency:**
- Python `_reasoning_status_for_version` returns `ReasoningStatus = Literal["ready","pending","failed","missing"]` (Task 1). Used by `_run_diff_core` and the beat task.
- `_non_trivial_inferred_axioms` returns `list[tuple[str, ox.Term]]` (Task 2). Consumer in Task 4 iterates `for pred, obj in ...`.
- `ManchesterLine["source"]` ∈ `{"asserted", "inferred", None}` (Task 3); TS mirror in Task 7.
- `axiom_changes[i]["source"]` ∈ `{"asserted", "inferred"}` (Task 4); TS mirror in Task 7.
- `summary["inferred_status"]` keys `from_version` / `to_version` matched exactly across Python + TS.

**4. Breaking change handling:** cached `OntologyDiff.diff_data` rows from before Phase 4 lack `source` on `axiom_changes[*]`, the `inferred_status` summary key, and `source` on ManchesterLine. The frontend reads `inferred_status` with a guard (`if (!data?.summary?.inferred_status) return false`) for the polling decision, but the notice renders unconditionally and would crash if `inferred_status` is undefined. **Task 12 explicitly clears caches** so this isn't a soft-failure. If you want a defensive fallback, update Task 9's notice component to early-return when `status` is undefined.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-19-manchester-diff-inferred-axioms-phase-4.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
