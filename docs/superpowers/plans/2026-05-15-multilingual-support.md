# Multilingual Ontology Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Index all language variants of ontology labels in a single Redis sorted set, expose language preference at three tiers (user profile → per-ontology → session), rank cross-language search results lower with a language badge, and display all language variants in term detail.

**Architecture:** The Redis sorted set key gains a `{lang}` segment (`{norm}|{lang}|{type}|{iri}`), enabling a two-scan strategy: scan 1 targets the preferred language, scan 2 sweeps all languages for cross-language fallbacks. Entity hashes store JSON arrays of `{value, lang}` objects for labels, synonyms, and definitions. A `resolve_lang()` helper resolves the three-tier preference (query param → ontology override → user global) for every search/autocomplete call.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, pyoxigraph, Redis (redis-py), React 18, TypeScript, React Query.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `alembic/versions/*_add_language_preferences_to_users.py` | Create | Add `preferred_lang`, `lang_fallback_strategy` to users |
| `alembic/versions/*_add_preferred_lang_to_ontologies.py` | Create | Add `preferred_lang` to ontologies |
| `ontoexplorer/models/db.py` | Modify | ORM columns for new fields |
| `ontoexplorer/modules/search/lang.py` | Create | `resolve_lang()` utility |
| `ontoexplorer/api/auth.py` | Modify | Expose + update language prefs on `/auth/me` |
| `ontoexplorer/modules/search/indexer.py` | Modify | Lang-tagged sorted set, JSON hash arrays, langs inventory, schema v2 |
| `ontoexplorer/modules/search/evaluator.py` | Modify | `SearchResult` gains `lang`/`cross_language`; label picks preferred lang |
| `ontoexplorer/modules/search/autocomplete.py` | Modify | `Completion` gains `lang`/`cross_language`; four-part key parse; lang-priority scans |
| `ontoexplorer/api/ontologies.py` | Modify | `/languages` endpoint; PATCH accepts `preferred_lang`; term detail preserves lang |
| `ontoexplorer/api/search.py` | Modify | `?lang=` param wired to evaluator/autocomplete |
| `ontoexplorer/api/global_search.py` | Modify | `?lang=` param wired to evaluator/autocomplete |
| `frontend/src/lib/api.ts` | Modify | `LangLabel` type; updated search/term/completion types; `/languages` client |
| `frontend/src/hooks/useLang.ts` | Create | Three-tier lang resolution + localStorage |
| `frontend/src/hooks/useOntologyLanguages.ts` | Create | Fetch `/languages` endpoint |
| `frontend/src/components/NavBar.tsx` | Modify | Session-level language picker |
| `frontend/src/pages/OntologyPage.tsx` | Modify | Per-ontology language picker |
| `frontend/src/components/TermPanel.tsx` | Modify | Language-tagged labels/definitions/synonyms; fallback strategy |
| `frontend/src/pages/Profile.tsx` | Modify | Language preference + fallback strategy form |

---

## Task 1: Database migrations and ORM model updates

**Files:**
- Create: `alembic/versions/*_add_language_preferences_to_users.py`
- Create: `alembic/versions/*_add_preferred_lang_to_ontologies.py`
- Modify: `ontoexplorer/models/db.py`

- [ ] **Step 1: Generate migration 1 (users table)**

```bash
uv run alembic revision -m "add_language_preferences_to_users"
```

Edit the generated file:

```python
def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_lang", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "lang_fallback_strategy",
            sa.String(),
            nullable=False,
            server_default="silent",
        ),
    )

def downgrade() -> None:
    op.drop_column("users", "lang_fallback_strategy")
    op.drop_column("users", "preferred_lang")
```

- [ ] **Step 2: Generate migration 2 (ontologies table)**

```bash
uv run alembic revision -m "add_preferred_lang_to_ontologies"
```

Edit the generated file:

```python
def upgrade() -> None:
    op.add_column("ontologies", sa.Column("preferred_lang", sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column("ontologies", "preferred_lang")
```

- [ ] **Step 3: Update ORM models in `ontoexplorer/models/db.py`**

Add to the `User` class (after `created_at`):

```python
preferred_lang: Mapped[str | None] = mapped_column(String, nullable=True)
lang_fallback_strategy: Mapped[str] = mapped_column(String, nullable=False, default="silent", server_default="silent")
```

Add to the `Ontology` class (after `auto_sync`):

```python
preferred_lang: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Apply migrations**

```bash
uv run alembic upgrade head
```

Expected: two new `Running upgrade` lines, no errors.

- [ ] **Step 5: Verify columns exist**

```bash
docker compose exec postgres psql -U ontoexplorer -d ontoexplorer \
  -c "\d users" | grep lang
```

Expected output includes:
```
 preferred_lang          | character varying        |           |          |
 lang_fallback_strategy  | character varying        |           | not null | 'silent'::character varying
```

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/ ontoexplorer/models/db.py
git commit -m "feat(multilingual): add language preference columns to users and ontologies"
```

---

## Task 2: resolve_lang() helper and user language preference API

**Files:**
- Create: `ontoexplorer/modules/search/lang.py`
- Modify: `ontoexplorer/api/auth.py`
- Test: `tests/unit/test_lang.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_lang.py`:

```python
from unittest.mock import MagicMock
from ontoexplorer.modules.search.lang import resolve_lang


def _user(lang):
    u = MagicMock()
    u.preferred_lang = lang
    return u

def _ontology(lang):
    o = MagicMock()
    o.preferred_lang = lang
    return o


def test_query_param_wins_over_all():
    assert resolve_lang("fr", _ontology("de"), _user("en")) == "fr"

def test_ontology_override_wins_over_user():
    assert resolve_lang(None, _ontology("de"), _user("en")) == "de"

def test_user_pref_used_when_no_override():
    assert resolve_lang(None, _ontology(None), _user("en")) == "en"

def test_none_when_no_preference():
    assert resolve_lang(None, _ontology(None), _user(None)) is None

def test_empty_string_query_param_treated_as_none():
    assert resolve_lang("", _ontology("de"), _user("en")) == "de"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_lang.py -v
```

Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.search.lang'`

- [ ] **Step 3: Create `ontoexplorer/modules/search/lang.py`**

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ontoexplorer.models.db import Ontology, User


def resolve_lang(
    query_param: str | None,
    ontology: "Ontology | None",
    user: "User | None",
) -> str | None:
    """Return the effective BCP-47 language tag, or None (= all languages).

    Priority: query_param > ontology.preferred_lang > user.preferred_lang > None.
    An empty string query_param is treated as absent.
    """
    if query_param:
        return query_param
    if ontology and ontology.preferred_lang:
        return ontology.preferred_lang
    if user and user.preferred_lang:
        return user.preferred_lang
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_lang.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Update `GET /auth/me` to expose language fields**

In `ontoexplorer/api/auth.py`, update the `me` handler return dict:

```python
@router.get("/me", summary="Current user profile")
async def me(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    from ontoexplorer.models.db import OAuthAccount
    accounts = (await db.execute(
        select(OAuthAccount).where(OAuthAccount.user_id == user.id)
    )).scalars().all()
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat(),
        "is_admin": is_admin(user),
        "connected_providers": [a.provider for a in accounts],
        "preferred_lang": user.preferred_lang,
        "lang_fallback_strategy": user.lang_fallback_strategy,
    }
```

- [ ] **Step 6: Add `PATCH /auth/me` endpoint**

Add after the `me` handler in `ontoexplorer/api/auth.py`:

```python
@router.patch("/me", summary="Update user preferences")
async def update_me(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    allowed = {"preferred_lang", "lang_fallback_strategy", "display_name"}
    updates = {k: v for k, v in body.items() if k in allowed}

    if "lang_fallback_strategy" in updates:
        valid = {"silent", "show_all", "indicate_missing"}
        if updates["lang_fallback_strategy"] not in valid:
            raise HTTPException(status_code=422, detail=f"lang_fallback_strategy must be one of {valid}")

    for k, v in updates.items():
        setattr(user, k, v)
    await db.commit()
    await db.refresh(user)
    return {
        "id": user.id,
        "preferred_lang": user.preferred_lang,
        "lang_fallback_strategy": user.lang_fallback_strategy,
    }
```

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/modules/search/lang.py ontoexplorer/api/auth.py tests/unit/test_lang.py
git commit -m "feat(multilingual): resolve_lang() helper and user language preference API"
```

---

## Task 3: Multilingual search indexer

**Files:**
- Modify: `ontoexplorer/modules/search/indexer.py`
- Test: `tests/unit/test_indexer_multilingual.py`

The key changes are: (a) SPARQL label query adds `(lang(?label) AS ?lang)` projection; (b) sorted set key becomes `{norm}|{lang}|{type}|{iri}`; (c) entity hash stores JSON arrays instead of pipe-separated strings; (d) a per-language count is written to `search:entities:{vid}:langs`; (e) schema version `v2` is written to the meta key.

- [ ] **Step 1: Add `_langs_key` function to `ontoexplorer/modules/search/indexer.py`**

Find the block of `_*_key` helper functions (near line 48) and add:

```python
def _langs_key(version_id: str) -> str:
    return f"search:entities:{version_id}:langs"
```

- [ ] **Step 2: Update the SPARQL label query to project the language tag**

Find the label query string (near line 271). Change:

```python
label_q = f"""
    SELECT ?entity ?label WHERE {{
        GRAPH <{named_graph}> {{
            VALUES ?pred {{ {label_pred_filter} }}
            ?entity ?pred ?label .
            FILTER(isIRI(?entity) && isLiteral(?label))
        }}
    }}
"""
```

To:

```python
label_q = f"""
    SELECT ?entity ?label (lang(?label) AS ?lang) WHERE {{
        GRAPH <{named_graph}> {{
            VALUES ?pred {{ {label_pred_filter} }}
            ?entity ?pred ?label .
            FILTER(isIRI(?entity) && isLiteral(?label))
        }}
    }}
"""
```

- [ ] **Step 3: Accumulate per-entity label lists and lang counts**

In the loop that processes SPARQL label results (near line 283), replace the line:

```python
val = sol["label"].value
```

With logic that collects all labels per entity and tracks language counts. This requires restructuring the label processing loop. Find the section that builds the entity dict and replace the label-extraction logic:

```python
# Accumulate all (value, lang_tag) pairs per entity IRI
from collections import defaultdict
import json

entity_labels: dict[str, list[dict]] = defaultdict(list)
lang_counts: dict[str, int] = defaultdict(int)

for sol in store.query(label_q):
    iri = sol["entity"].value
    val = sol["label"].value
    lang_tag = sol["lang"].value if sol.get("lang") and sol["lang"].value else ""
    entity_labels[iri].append({"value": val, "lang": lang_tag})
    lang_counts[lang_tag] += 1
```

- [ ] **Step 4: Update sorted-set entries to include lang tag**

Find where `pipe.zadd(_prefix_key(version_id), {normalised: 0})` is called. For each entity's labels, one sorted-set entry must be created per `(label, lang)` pair. Replace the single zadd with a loop:

```python
for lbl_entry in entity_labels.get(iri, []):
    val = lbl_entry["value"]
    lang_tag = lbl_entry["lang"]
    norm = normalise_label(val)
    if norm:
        pipe.zadd(_prefix_key(version_id), {f"{norm}|{lang_tag}|{entity_type}|{iri}": 0})
```

- [ ] **Step 5: Update entity hash to use JSON arrays**

Find the `pipe.hset(_iri_key(...), mapping={...})` call. Replace the `label`, `synonyms`, `definition` fields with JSON arrays:

```python
labels_list = entity_labels.get(iri, [])
primary_label = next(
    (l["value"] for l in labels_list if l["lang"] == "en"),
    labels_list[0]["value"] if labels_list else iri.split("/")[-1],
)

# Build synonyms and definitions lists similarly (from their respective SPARQL queries)
synonyms_list = [{"value": v, "lang": lang_of(v)} for v in raw_synonyms]   # adapt to actual loop
definitions_list = [{"value": v, "lang": lang_of(v)} for v in raw_definitions]

pipe.hset(_iri_key(version_id, iri), mapping={
    "primary_label": primary_label,
    "type":          entity_type,
    "iri":           iri,
    "short":         short,
    "source":        _get_source(iri),
    "labels":        json.dumps(labels_list),
    "synonyms":      json.dumps(synonyms_list),
    "definitions":   json.dumps(definitions_list),
})
```

> **Note:** Apply the same `(lang(?x) AS ?lang)` projection change to the synonym and definition SPARQL queries so `lang_of()` is not needed — each query result already carries the lang tag.

- [ ] **Step 6: Write langs inventory and set schema version**

After all entities are indexed (just before or after the final `pipe.execute()`), add:

```python
# Write per-language label counts
langs_key = _langs_key(version_id)
r.delete(langs_key)
if lang_counts:
    r.hset(langs_key, mapping={k: v for k, v in lang_counts.items()})

# Mark index as schema v2
r.hset(_meta_key(version_id), "schema_version", "v2")
```

- [ ] **Step 7: Write a unit test for the lang-key format**

Create `tests/unit/test_indexer_multilingual.py`:

```python
from ontoexplorer.modules.search.indexer import _langs_key, _meta_key, _prefix_key


def test_langs_key_format():
    assert _langs_key("abc-123") == "search:entities:abc-123:langs"


def test_sorted_set_key_has_four_parts():
    iri = "http://purl.obolibrary.org/obo/GO_0008150"
    entity_type = "class"
    lang = "en"
    norm = "biological process"
    key = f"{norm}|{lang}|{entity_type}|{iri}"
    parts = key.split("|", 3)
    assert len(parts) == 4
    assert parts[1] == "en"
    assert parts[3] == iri
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests/unit/test_indexer_multilingual.py -v
```

Expected: 2 passed.

- [ ] **Step 9: Commit**

```bash
git add ontoexplorer/modules/search/indexer.py tests/unit/test_indexer_multilingual.py
git commit -m "feat(multilingual): lang-tagged sorted set, JSON hash arrays, langs inventory, schema v2"
```

---

## Task 4: Language-aware evaluator

**Files:**
- Modify: `ontoexplorer/modules/search/evaluator.py`
- Test: `tests/unit/test_evaluator_lang.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_evaluator_lang.py`:

```python
import json
from unittest.mock import MagicMock, patch
from ontoexplorer.modules.search.evaluator import _pick_label


def test_pick_label_prefers_requested_lang():
    detail = {
        "labels": json.dumps([
            {"value": "cell death", "lang": "en"},
            {"value": "mort cellulaire", "lang": "fr"},
        ]),
        "primary_label": "cell death",
    }
    label, lang = _pick_label(detail, "fr")
    assert label == "mort cellulaire"
    assert lang == "fr"


def test_pick_label_falls_back_to_primary():
    detail = {
        "labels": json.dumps([{"value": "cell death", "lang": "en"}]),
        "primary_label": "cell death",
    }
    label, lang = _pick_label(detail, "fr")
    assert label == "cell death"
    assert lang == "en"


def test_pick_label_no_lang_returns_primary():
    detail = {"primary_label": "cell death", "labels": "[]"}
    label, lang = _pick_label(detail, None)
    assert label == "cell death"
    assert lang is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_evaluator_lang.py -v
```

Expected: `ImportError: cannot import name '_pick_label'`

- [ ] **Step 3: Update `SearchResult` dataclass in `evaluator.py`**

Find the `SearchResult` dataclass (near line 32) and add two fields:

```python
@dataclass
class SearchResult:
    iri: str
    label: str
    short: str
    match_type: str       # "elk" | "sparql" | "entity"
    lang: str | None = None
    cross_language: bool = False
```

- [ ] **Step 4: Add `_pick_label` helper to `evaluator.py`**

Add after the imports:

```python
import json as _json


def _pick_label(detail: dict, lang: str | None) -> tuple[str, str | None]:
    """Return (label_string, lang_tag) for the given lang preference.

    Falls back to primary_label when the preferred lang is not available.
    """
    labels_raw = detail.get("labels")
    if labels_raw:
        try:
            labels = _json.loads(labels_raw)
        except (ValueError, TypeError):
            labels = []
        if lang:
            for entry in labels:
                if entry.get("lang") == lang:
                    return entry["value"], lang
        if labels:
            first = labels[0]
            return first["value"], first.get("lang") or None
    # v1 schema fallback or empty labels
    return detail.get("primary_label") or detail.get("label", ""), None
```

- [ ] **Step 5: Update `evaluate()` to accept and use `lang` param**

Find the `evaluate` function signature and add the `lang` parameter:

```python
async def evaluate(node, version_id: str, ontology_id: str, lang: str | None = None) -> list[SearchResult]:
```

Find where `SearchResult` objects are built (the loop over `iris`, near line 202) and replace:

```python
label = detail.get("label", iri.split("/")[-1]) if detail else iri.split("/")[-1]
```

With:

```python
if detail:
    label, result_lang = _pick_label(detail, lang)
    cross_language = bool(lang) and result_lang != lang
else:
    label, result_lang, cross_language = iri.split("/")[-1], None, False
```

And update the `SearchResult(...)` constructor call:

```python
results.append(SearchResult(
    iri=iri,
    label=label,
    short=detail.get("short", "") if detail else "",
    match_type=match_type,
    lang=result_lang,
    cross_language=cross_language,
))
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/test_evaluator_lang.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/modules/search/evaluator.py tests/unit/test_evaluator_lang.py
git commit -m "feat(multilingual): SearchResult gains lang/cross_language; _pick_label helper"
```

---

## Task 5: Language-aware autocomplete

**Files:**
- Modify: `ontoexplorer/modules/search/autocomplete.py`
- Test: `tests/unit/test_autocomplete_lang.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_autocomplete_lang.py`:

```python
from ontoexplorer.modules.search.autocomplete import _parse_lang_from_member


def test_parse_lang_from_four_part_key():
    member = "cell death|en|class|http://purl.obolibrary.org/obo/GO_0008150"
    norm, lang, etype, iri = _parse_lang_from_member(member)
    assert norm == "cell death"
    assert lang == "en"
    assert etype == "class"
    assert iri == "http://purl.obolibrary.org/obo/GO_0008150"


def test_parse_lang_untagged_literal():
    member = "cell death||class|http://example.org/Cell"
    norm, lang, etype, iri = _parse_lang_from_member(member)
    assert lang == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_autocomplete_lang.py -v
```

Expected: `ImportError: cannot import name '_parse_lang_from_member'`

- [ ] **Step 3: Update `Completion` dataclass**

Find the `Completion` dataclass and add two fields:

```python
@dataclass
class Completion:
    text: str
    type: str
    iri: str | None
    short: str | None
    insert: str
    lang: str | None = None
    cross_language: bool = False
```

- [ ] **Step 4: Add `_parse_lang_from_member` helper**

Add near the top of `autocomplete.py`, after imports:

```python
def _parse_lang_from_member(member: str) -> tuple[str, str, str, str]:
    """Split a v2 sorted-set key into (norm, lang, entity_type, iri)."""
    parts = member.split("|", 3)
    if len(parts) != 4:
        # Graceful fallback for v1 keys: norm|type|iri
        p = member.split("|", 2)
        return (p[0], "", p[1], p[2]) if len(p) == 3 else ("", "", "", "")
    return parts[0], parts[1], parts[2], parts[3]
```

- [ ] **Step 5: Update `_entity_completions` signature to accept `lang`**

```python
def _entity_completions(
    r,
    version_id: str,
    partial: str,
    entity_type: str | None,
    limit: int,
    excluded_types: frozenset[str] | None = None,
    lang: str | None = None,
) -> list[Completion]:
```

- [ ] **Step 6: Replace the two-scan logic in `_entity_completions`**

Find the scan block (near line 89) and replace with:

```python
    if norm:
        if lang:
            # Preferred-lang exact scan, then full-prefix fallback
            pref_exact = r.zrangebylex(key, f"[{norm}|{lang}|", f"[{norm}|{lang}|\xff", start=0, num=max(limit, 20))
            all_members = r.zrangebylex(key, f"[{norm}|", f"[{norm}|\xff", start=0, num=limit * 8)
            pref_set = set(pref_exact)
            members = list(pref_exact) + [m for m in all_members if m not in pref_set]
        else:
            # Original two-scan: exact-label entries first, then broader prefix
            exact_members = r.zrangebylex(key, f"[{norm}|", f"[{norm}|\xff", start=0, num=max(limit, 20))
            all_members   = r.zrangebylex(key, f"[{norm}",  f"[{norm}\xff",  start=0, num=limit * 8)
            exact_set = set(exact_members)
            members = list(exact_members) + [m for m in all_members if m not in exact_set]
    else:
        members = r.zrange(key, 0, limit * 4 - 1)
```

- [ ] **Step 7: Update the member-parsing loop to use `_parse_lang_from_member`**

Find `parts = member.split("|", 2)` in the loop body and replace the parsing + Completion construction:

```python
    for member in members:
        norm_lbl, lang_tag, etype, iri = _parse_lang_from_member(member)
        if not iri:
            continue
        if entity_type and etype != entity_type:
            continue
        if excluded_types and etype in excluded_types:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        detail = r.hgetall(_iri_key(version_id, iri))
        if not detail:
            continue
        primary = detail.get("primary_label") or detail.get("label", "")
        primary_norm = normalise_label(primary)
        is_cross = bool(lang) and lang_tag != lang
        # ... rest of tier assignment unchanged, but pass lang/cross_language to Completion ...
```

When constructing each `Completion`, add:

```python
        Completion(
            text=...,
            type=etype,
            iri=iri,
            short=detail.get("short"),
            insert=...,
            lang=lang_tag or None,
            cross_language=is_cross,
        )
```

- [ ] **Step 8: Propagate `lang` param through `get_completions`**

Update the `get_completions` signature:

```python
def get_completions(
    q: str,
    cursor: int,
    version_id: str,
    limit: int = 10,
    lang: str | None = None,
) -> list[Completion]:
```

Pass `lang=lang` to every `_entity_completions(...)` call inside `get_completions`.

- [ ] **Step 9: Run tests**

```bash
uv run pytest tests/unit/test_autocomplete_lang.py -v
```

Expected: 2 passed.

- [ ] **Step 10: Commit**

```bash
git add ontoexplorer/modules/search/autocomplete.py tests/unit/test_autocomplete_lang.py
git commit -m "feat(multilingual): lang-aware autocomplete; four-part key parsing; cross_language flag"
```

---

## Task 6: /languages endpoint and PATCH preferred_lang on ontologies

**Files:**
- Modify: `ontoexplorer/api/ontologies.py`
- Modify: `ontoexplorer/modules/search/indexer.py` (export `_langs_key`)

- [ ] **Step 1: Ensure `_langs_key` is importable**

In `ontoexplorer/modules/search/indexer.py`, confirm `_langs_key` was added in Task 3 and is accessible (no underscore restriction — it's already imported by other modules like autocomplete via `_iri_key`; this follows the same pattern).

- [ ] **Step 2: Add the `/languages` endpoint to `ontologies.py`**

Add after the `/stats` route:

```python
@router.get("/{ontology_id}/{version_id}/languages", summary="Languages present in the search index")
async def get_languages(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)

    def _read_langs():
        from ontoexplorer.modules.search.indexer import _get_redis, _langs_key, _meta_key
        r = _get_redis()
        meta = r.hgetall(_meta_key(version_id))
        if meta.get("schema_version") != "v2":
            return []
        counts = r.hgetall(_langs_key(version_id))
        return sorted(
            [{"lang": k or "", "label_count": int(v)} for k, v in counts.items()],
            key=lambda x: -x["label_count"],
        )

    return await asyncio.to_thread(_read_langs)
```

- [ ] **Step 3: Update `PATCH /ontologies/{id}` to accept `preferred_lang`**

In the `patch_ontology` handler (near line 267), find where `body` fields are applied and add:

```python
    if "preferred_lang" in body:
        ontology.preferred_lang = body["preferred_lang"] or None
```

- [ ] **Step 4: Manual smoke test**

```bash
curl -s "http://localhost:8000/api/v1/ontologies/<any-id>/<any-vid>/languages"
```

Expected: `[]` (indexes haven't been rebuilt yet — that's correct).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/ontologies.py ontoexplorer/modules/search/indexer.py
git commit -m "feat(multilingual): /languages endpoint; PATCH /ontologies/{id} accepts preferred_lang"
```

---

## Task 7: Wire ?lang= into search and global_search APIs

**Files:**
- Modify: `ontoexplorer/api/search.py`
- Modify: `ontoexplorer/api/global_search.py`
- Modify: `ontoexplorer/api/ontologies.py` (import resolve_lang)

- [ ] **Step 1: Add `lang` param and `resolve_lang` to the per-version search endpoint in `search.py`**

At the top of `search.py` add:

```python
from ontoexplorer.modules.search.lang import resolve_lang
```

Find the per-version search handler signature and add:

```python
    lang: str | None = Query(None, description="BCP-47 language tag for preferred results"),
    user: User | None = Depends(get_current_user),
```

Before calling the evaluator or autocomplete, resolve the effective language:

```python
    ontology = await _get_ontology_or_404(db, ontology_id)
    effective_lang = resolve_lang(lang, ontology, user)
```

Pass `lang=effective_lang` to `get_completions(...)` and `evaluate(...)` calls.

- [ ] **Step 2: Add `lang` param to the autocomplete endpoint in `search.py`**

Same pattern — add `lang: str | None = Query(None)` and wire `effective_lang` to `get_completions`.

- [ ] **Step 3: Add `lang` param to cross-ontology search in `global_search.py`**

```python
from ontoexplorer.modules.search.lang import resolve_lang
```

Add `lang: str | None = Query(None)` to the `GET /search` handler. Resolve effective lang from `user.preferred_lang` only (no ontology context at this level):

```python
effective_lang = lang or (user.preferred_lang if user else None)
```

Pass to any `_entity_completions` or evaluator calls inside the handler.

- [ ] **Step 4: Smoke test**

```bash
curl -s "http://localhost:8000/api/v1/ontologies/<id>/<vid>/autocomplete?q=cell&lang=fr" | python3 -m json.tool | head -20
```

Expected: JSON array of completions (may all be cross_language:true until indexes are rebuilt).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/search.py ontoexplorer/api/global_search.py ontoexplorer/api/ontologies.py
git commit -m "feat(multilingual): wire ?lang= param through search and autocomplete endpoints"
```

---

## Task 8: Language-preserving term detail

**Files:**
- Modify: `ontoexplorer/api/ontologies.py` (term detail handler and `_sparql_term_props`)

- [ ] **Step 1: Update `props_query` to project lang**

Find the `props_query` string in the `get_term` handler:

```python
    props_query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?pred ?obj WHERE {{
            GRAPH <{g_iri}> {{
                <{term_iri}> ?pred ?obj .
                FILTER(isIRI(?obj) || isLiteral(?obj))
            }}
        }}
    """
```

Change to:

```python
    props_query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?pred ?obj (lang(?obj) AS ?lang) WHERE {{
            GRAPH <{g_iri}> {{
                <{term_iri}> ?pred ?obj .
                FILTER(isIRI(?obj) || isLiteral(?obj))
            }}
        }}
    """
```

- [ ] **Step 2: Update `_sparql_term_props` helper to preserve lang**

Find `_sparql_term_props` (the synchronous helper called in a thread). Update the properties accumulation:

```python
    properties: dict[str, list] = {}
    for row in prop_rows:
        pred = row["pred"].value
        obj_node = row["obj"]
        lang_tag = getattr(obj_node, "language", None) or None
        properties.setdefault(pred, []).append({"value": obj_node.value, "lang": lang_tag})
```

- [ ] **Step 3: Build typed `labels`, `definitions`, `synonyms` lists in `get_term`**

After `properties` is built, add:

```python
    LABEL_PROPS = {
        "http://www.w3.org/2000/01/rdf-schema#label",
        "http://www.w3.org/2004/02/skos/core#prefLabel",
    }
    DEFINITION_PROPS = {
        "http://purl.obolibrary.org/obo/IAO_0000115",
        "http://www.w3.org/2004/02/skos/core#definition",
        "http://www.w3.org/2000/01/rdf-schema#comment",
    }
    SYNONYM_PROPS = {
        "http://www.w3.org/2004/02/skos/core#altLabel",
        "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
        "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
    }

    labels      = [v for p in LABEL_PROPS      for v in properties.get(p, [])]
    definitions = [v for p in DEFINITION_PROPS  for v in properties.get(p, [])]
    synonyms    = [v for p in SYNONYM_PROPS     for v in properties.get(p, [])]

    # Primary label: prefer effective lang, fallback to first
    def _primary(lst, lang):
        for item in lst:
            if item.get("lang") == lang:
                return item["value"]
        return lst[0]["value"] if lst else term_iri.split("/")[-1]
```

- [ ] **Step 4: Update the return dict in `get_term`**

Find the final `return {...}` in the handler. Add the new fields and keep `label` for backwards compatibility:

```python
    return {
        # ... existing fields ...
        "label":       _primary(labels, effective_lang),
        "labels":      labels,
        "definitions": definitions,
        "synonyms":    synonyms,
        "properties":  properties,   # now [{value, lang}] objects
    }
```

Where `effective_lang` comes from `resolve_lang(lang_param, ontology, user)` — add the `lang` query parameter to the `get_term` handler signature:

```python
    lang: str | None = Query(None),
    user: User | None = Depends(get_current_user),
```

- [ ] **Step 5: Smoke test**

```bash
curl -s "http://localhost:8000/api/v1/ontologies/<id>/<vid>/terms/<encoded-iri>?lang=en" \
  | python3 -m json.tool | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('labels'))"
```

Expected: list of `{"value": "...", "lang": "..."}` dicts.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/ontologies.py
git commit -m "feat(multilingual): term detail preserves lang tags; labels/definitions/synonyms as typed arrays"
```

---

## Task 9: Frontend API types and /languages client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add `LangLabel` type and update related types**

At the top of `api.ts` (after existing imports), add:

```typescript
export interface LangLabel {
  value: string
  lang: string | null
}

export interface OntologyLanguage {
  lang: string
  label_count: number
}
```

Find the `SearchResult` or equivalent type (wherever search hits are typed) and add:

```typescript
  lang?: string | null
  cross_language?: boolean
```

Find the term detail response type and update:

```typescript
export interface TermDetail {
  iri: string
  label: string
  labels: LangLabel[]
  definitions: LangLabel[]
  synonyms: LangLabel[]
  properties: Record<string, LangLabel[]>
  // ... existing fields
}
```

Find the `Completion` type and add:

```typescript
  lang?: string | null
  cross_language?: boolean
```

- [ ] **Step 2: Add `/languages` API method**

In the `api.ontologies` object, add:

```typescript
  languages: (ontologyId: string, versionId: string): Promise<OntologyLanguage[]> =>
    request(`/ontologies/${ontologyId}/${versionId}/languages`),
```

- [ ] **Step 3: Add `lang` param to search/autocomplete client methods**

Find the search and autocomplete client methods and add an optional `lang` param:

```typescript
  search: (ontologyId: string, versionId: string, q: string, mode?: string, lang?: string) =>
    request<SearchResponse>(`/ontologies/${ontologyId}/${versionId}/search?q=${encodeURIComponent(q)}${mode ? `&mode=${mode}` : ''}${lang ? `&lang=${lang}` : ''}`),

  autocomplete: (ontologyId: string, versionId: string, q: string, cursor: number, lang?: string) =>
    request<Completion[]>(`/ontologies/${ontologyId}/${versionId}/autocomplete?q=${encodeURIComponent(q)}&cursor=${cursor}${lang ? `&lang=${lang}` : ''}`),
```

- [ ] **Step 4: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(multilingual): frontend API types — LangLabel, OntologyLanguage, updated search/term types"
```

---

## Task 10: useLang hook

**Files:**
- Create: `frontend/src/hooks/useLang.ts`

- [ ] **Step 1: Create the hook**

```typescript
import { useState, useCallback } from 'react'
import { api } from '../lib/api'

const STORAGE_KEY = 'oe_lang_override'

function readSessionLang(): string | null {
  try { return localStorage.getItem(STORAGE_KEY) } catch { return null }
}

function writeSessionLang(lang: string | null): void {
  try {
    if (lang) localStorage.setItem(STORAGE_KEY, lang)
    else localStorage.removeItem(STORAGE_KEY)
  } catch { /* ignore */ }
}

interface UseLangOptions {
  ontologyId?: string
  ontologyPreferredLang?: string | null
}

interface UseLangResult {
  effectiveLang: string | null
  sessionLang: string | null
  setSessionLang: (lang: string | null) => void
  setOntologyLang: (ontologyId: string, lang: string | null) => Promise<void>
}

export function useLang(opts: UseLangOptions = {}): UseLangResult {
  const [sessionLang, setSessionLangState] = useState<string | null>(readSessionLang)

  const setSessionLang = useCallback((lang: string | null) => {
    writeSessionLang(lang)
    setSessionLangState(lang)
  }, [])

  const setOntologyLang = useCallback(async (ontologyId: string, lang: string | null) => {
    await api.ontologies.patch(ontologyId, { preferred_lang: lang })
  }, [])

  // Three-tier resolution: session > ontology > (user pref handled server-side via ?lang=)
  const effectiveLang = sessionLang ?? opts.ontologyPreferredLang ?? null

  return { effectiveLang, sessionLang, setSessionLang, setOntologyLang }
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useLang.ts
git commit -m "feat(multilingual): useLang hook — three-tier resolution with localStorage session override"
```

---

## Task 11: useOntologyLanguages hook

**Files:**
- Create: `frontend/src/hooks/useOntologyLanguages.ts`

- [ ] **Step 1: Create the hook**

```typescript
import { useQuery } from '@tanstack/react-query'
import { api, OntologyLanguage } from '../lib/api'

export function useOntologyLanguages(
  ontologyId: string | undefined,
  versionId: string | undefined,
): OntologyLanguage[] {
  const { data } = useQuery({
    queryKey: ['languages', ontologyId, versionId],
    queryFn: () => api.ontologies.languages(ontologyId!, versionId!),
    enabled: Boolean(ontologyId && versionId),
    staleTime: 5 * 60 * 1000,
  })
  return data ?? []
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useOntologyLanguages.ts
git commit -m "feat(multilingual): useOntologyLanguages hook"
```

---

## Task 12: NavBar session language picker

**Files:**
- Modify: `frontend/src/components/NavBar.tsx`

- [ ] **Step 1: Add a `LangPicker` component at the bottom of `NavBar.tsx`**

```typescript
import { useLang } from '../hooks/useLang'

function LangPicker() {
  const { sessionLang, setSessionLang } = useLang()
  const [open, setOpen] = useState(false)

  const COMMON = [
    { tag: null, label: 'All languages' },
    { tag: 'en', label: 'English' },
    { tag: 'fr', label: 'French' },
    { tag: 'de', label: 'German' },
    { tag: 'nl', label: 'Dutch' },
    { tag: 'es', label: 'Spanish' },
    { tag: 'ja', label: 'Japanese' },
    { tag: 'zh', label: 'Chinese' },
  ]

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          background: 'none', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', padding: '4px 10px',
          color: 'var(--text-dim)', fontSize: 12, cursor: 'pointer',
        }}
      >
        🌐 {sessionLang ?? 'All'}
      </button>
      {open && (
        <div style={{
          position: 'absolute', right: 0, top: '110%', zIndex: 100,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', minWidth: 140, boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        }}>
          {COMMON.map(({ tag, label }) => (
            <button key={tag ?? '_all'} onClick={() => { setSessionLang(tag); setOpen(false) }}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                padding: '6px 12px', background: 'none', border: 'none',
                color: sessionLang === tag ? 'var(--accent)' : 'var(--text)',
                fontSize: 12, cursor: 'pointer',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add `<LangPicker />` to the NavBar JSX**

Find the right-hand side of the NavBar (next to user menu / auth button) and add:

```tsx
<LangPicker />
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/NavBar.tsx
git commit -m "feat(multilingual): NavBar session language picker"
```

---

## Task 13: OntologyPage per-ontology language picker

**Files:**
- Modify: `frontend/src/pages/OntologyPage.tsx`

- [ ] **Step 1: Add per-ontology picker to OntologyPage**

Import the necessary hooks at the top:

```typescript
import { useLang } from '../hooks/useLang'
import { useOntologyLanguages } from '../hooks/useOntologyLanguages'
```

Inside the component, after the ontology data is available, add:

```typescript
  const { effectiveLang, setOntologyLang } = useLang({
    ontologyPreferredLang: ontology?.preferred_lang,
  })
  const availableLangs = useOntologyLanguages(ontologyId, latestVersionId)
```

Add a small picker in the page header, below the ontology title:

```tsx
{availableLangs.length > 1 && (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Language:</span>
    <select
      value={ontology?.preferred_lang ?? ''}
      onChange={e => setOntologyLang(ontologyId!, e.target.value || null)}
      style={{
        fontSize: 11, background: 'var(--bg-secondary)',
        border: '1px solid var(--border)', borderRadius: 4,
        color: 'var(--text)', padding: '2px 6px',
      }}
    >
      <option value=''>Session default</option>
      {availableLangs.map(l => (
        <option key={l.lang} value={l.lang}>
          {l.lang || 'untagged'} ({l.label_count.toLocaleString()} labels)
        </option>
      ))}
    </select>
  </div>
)}
```

- [ ] **Step 2: Pass `effectiveLang` as `?lang=` to search/term hooks**

Find the hooks that call search and term detail APIs (e.g. `useClassTree`, `useTerm`). Pass `lang: effectiveLang` where supported. Each hook should append `&lang=${lang}` to its request URL.

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/OntologyPage.tsx
git commit -m "feat(multilingual): per-ontology language picker in OntologyPage"
```

---

## Task 14: TermPanel multilingual display

**Files:**
- Modify: `frontend/src/components/TermPanel.tsx`

- [ ] **Step 1: Add `LangBadge` component inside `TermPanel.tsx`**

```typescript
function LangBadge({ lang }: { lang: string | null }) {
  if (!lang) return null
  return (
    <span style={{
      fontSize: 9, padding: '1px 5px', borderRadius: 3,
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      color: 'var(--text-dim)', fontWeight: 600, letterSpacing: 0.3, flexShrink: 0,
    }}>
      {lang}
    </span>
  )
}
```

- [ ] **Step 2: Update labels display to show all language variants**

Find where the primary label is rendered and add underneath (when `data.labels` is available):

```tsx
{data.labels && data.labels.length > 1 && (
  <div style={{ marginTop: 6 }}>
    {data.labels.map((l, i) => (
      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
        <span style={{ fontSize: 12, color: 'var(--text)' }}>{l.value}</span>
        <LangBadge lang={l.lang} />
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 3: Update definitions and synonyms display**

Find where definitions and synonyms are rendered. Wrap each value with a `LangBadge`:

```tsx
{data.definitions?.map((d, i) => (
  <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start', marginBottom: 4 }}>
    <span style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5 }}>{d.value}</span>
    <LangBadge lang={d.lang} />
  </div>
))}
```

- [ ] **Step 4: Update properties table to handle `{value, lang}` objects**

Find the properties rendering loop. The values are now `LangLabel[]` instead of `string[]`. Update the render:

```tsx
{Object.entries(data.properties ?? {}).map(([pred, vals]) => (
  <tr key={pred}>
    <td style={{ ...cellStyle, color: 'var(--text-dim)', fontFamily: 'monospace', fontSize: 10 }}>
      {pred.split(/[/#]/).pop()}
    </td>
    <td style={cellStyle}>
      {(vals as Array<{value: string; lang: string | null}>).map((v, i) => (
        <div key={i} style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 2 }}>
          <span style={{ fontSize: 11 }}>{v.value}</span>
          <LangBadge lang={v.lang} />
        </div>
      ))}
    </td>
  </tr>
))}
```

- [ ] **Step 5: Implement fallback strategy display**

Read the user's `lang_fallback_strategy` from context (pass it as a prop or read from a context). Add a check when the preferred lang has no label:

```tsx
// When effectiveLang is set but no label in that lang:
const hasPreferredLang = data.labels?.some(l => l.lang === effectiveLang)
const strategy = userPrefs?.lang_fallback_strategy ?? 'silent'

{effectiveLang && !hasPreferredLang && strategy === 'indicate_missing' && (
  <div style={{ color: 'var(--text-dim)', fontSize: 11, fontStyle: 'italic' }}>
    No label in {effectiveLang}
  </div>
)}
```

- [ ] **Step 6: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/TermPanel.tsx
git commit -m "feat(multilingual): TermPanel language badges, all-variants display, fallback strategy"
```

---

## Task 15: Profile page language settings

**Files:**
- Modify: `frontend/src/pages/Profile.tsx`

- [ ] **Step 1: Add language preference section to `Profile.tsx`**

Find the existing profile form content and add a "Language" section:

```tsx
<section style={{ marginTop: '2rem' }}>
  <h2 style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: '1rem' }}>
    Language
  </h2>

  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
    <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
      Preferred language
      <input
        type="text"
        value={prefs.preferred_lang ?? ''}
        onChange={e => setPrefs(p => ({ ...p, preferred_lang: e.target.value || null }))}
        placeholder="e.g. en, fr, de, nl"
        style={{
          display: 'block', marginTop: 4,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', padding: '6px 10px',
          color: 'var(--text)', fontSize: 12, width: 200,
        }}
      />
    </label>

    <div>
      <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 6 }}>
        When preferred language has no label
      </div>
      {[
        { value: 'silent',           label: 'Use best available silently' },
        { value: 'show_all',         label: 'Show all language variants' },
        { value: 'indicate_missing', label: 'Indicate missing label' },
      ].map(opt => (
        <label key={opt.value} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, fontSize: 12, color: 'var(--text)', cursor: 'pointer' }}>
          <input
            type="radio"
            name="lang_fallback_strategy"
            value={opt.value}
            checked={prefs.lang_fallback_strategy === opt.value}
            onChange={() => setPrefs(p => ({ ...p, lang_fallback_strategy: opt.value }))}
          />
          {opt.label}
        </label>
      ))}
    </div>

    <button onClick={savePrefs} style={{ width: 'fit-content', ...buttonStyle }}>
      Save language settings
    </button>
  </div>
</section>
```

- [ ] **Step 2: Wire `savePrefs` to `PATCH /auth/me`**

```typescript
const [prefs, setPrefs] = useState({
  preferred_lang: user?.preferred_lang ?? null,
  lang_fallback_strategy: user?.lang_fallback_strategy ?? 'silent',
})

async function savePrefs() {
  await fetch('/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getAccessToken()}` },
    body: JSON.stringify(prefs),
  })
}
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Profile.tsx
git commit -m "feat(multilingual): Profile page language preference and fallback strategy settings"
```

---

## Task 16: Trigger re-index and verify end-to-end

- [ ] **Step 1: Trigger re-index of all versions**

```bash
curl -s -X POST http://localhost:8000/api/v1/admin/reindex \
  -H "Authorization: Bearer <admin-api-key>"
```

Expected: `{"queued": <N>}` where N is the number of ingested versions.

- [ ] **Step 2: Monitor re-index progress**

```bash
docker compose logs -f worker | grep -E "index_ontology|schema_version|indexed"
```

Wait until all versions complete.

- [ ] **Step 3: Verify schema v2 written**

```bash
docker compose exec redis redis-cli hget search:meta:<any-version-id> schema_version
```

Expected: `"v2"`

- [ ] **Step 4: Verify langs inventory**

```bash
docker compose exec redis redis-cli hgetall search:entities:<any-version-id>:langs
```

Expected: keys like `en`, `fr`, counts as values.

- [ ] **Step 5: Smoke test search with lang param**

```bash
curl -s "http://localhost:8000/api/v1/ontologies/<id>/<vid>/autocomplete?q=cell&lang=en" \
  | python3 -m json.tool | head -30
```

Expected: completions with `"lang": "en"` and `"cross_language": false`.

- [ ] **Step 6: Final commit**

```bash
git add .
git commit -m "feat(multilingual): end-to-end multilingual support complete"
git push
```
