# MOS query tab — relationship facets

## Problem

The homepage entity-type chips (Class / Object Property / Data Property /
Individual) are meaningful in **Keyword Search** but not in **Structured
Query (MOS)**: a MOS class expression only ever evaluates to classes, so the
type chips are inert there. What is useful in the MOS tab is filtering results
by their **relationship to the queried expression**.

## Scope

The MOS tab offers three relationship facets, selected one at a time (radio):

| Facet         | Default | Applies to            | Source                                            |
|---------------|---------|-----------------------|---------------------------------------------------|
| Subclasses    | yes     | any expression        | existing `evaluate(...)` (subclass closure + self)|
| Superclasses  | no      | single named class    | ELK `superclasses` / `direct_superclasses` index  |
| Equivalent    | no      | single named class    | derived from ELK closures (mutual subsumption)    |

Dropped from the original list: **Individuals** (needs an instance query, not
wanted) and **"others"**.

For a **complex** expression (restriction, `and`/`or`/`not`), Superclasses and
Equivalent are not answerable without classifying an anonymous expression,
which the evaluator does not do. Those two chips render **disabled** with a
tooltip; only Subclasses is active.

Keyword Search is unchanged — it keeps the entity-type chips. The two tabs hold
independent chip state.

## Behavior

- **Default**: Subclasses, preserving today's result set exactly.
- **"Direct only" toggle** is reinterpreted per facet:
  - Subclasses → direct children vs full descendant closure (today's meaning).
  - Superclasses → direct parents vs all ancestors.
  - Equivalent → no direct/transitive notion; toggle hidden/disabled.
- All results remain `type: "class"`; rows keep the CLASS badge. The active
  facet is conveyed by the selected chip, so no per-row relationship badge.

## Backend

Add `relation=subclasses|superclasses|equivalent` to expression-mode search.
Default `subclasses` so existing callers are unaffected.

- `subclasses` → existing path.
- `superclasses` (NamedClass only): resolve the IRI, return
  `direct_superclasses[iri]` when `direct` else `superclasses[iri]`, minus
  `owl:Thing` and minus the class itself.
- `equivalent` (NamedClass only): from the loaded classification,
  `{ B : B ∈ superclasses(A) ∧ A ∈ superclasses(B) }` minus `A`. ELK exposes no
  explicit equivalent key, but its transitive closures make this exact.
- `superclasses`/`equivalent` with a complex expression →
  `400 {"error": "relation_requires_named_class"}`. The frontend won't issue
  these (chips disabled), so this is a guard, not a user-facing path.

Implementation lands as a thin `relation`-aware wrapper around the existing
evaluator so the subclass path is untouched.

## Touched files

- `ontoexplorer/modules/search/evaluator.py` — relation-aware entry point;
  superclass/equivalent computation for the NamedClass case.
- `ontoexplorer/api/search.py` — `relation` param + named-class guard
  (per-version endpoint used by the MOS tab fan-out).
- `ontoexplorer/api/global_search.py` — same param for the cross-ontology
  expression path (kept consistent; MOS tab uses the per-version endpoint).
- `frontend/src/lib/api.ts` — `relation` arg on `ontologies.search`.
- `frontend/src/pages/Home.tsx` — split chip state between tabs; relationship
  chips with disabled logic for complex expressions in the MOS tab.

## Out of scope

- Individuals / instance retrieval.
- Superclass/equivalent for complex (anonymous) expressions.
- Any change to Keyword Search chips.
