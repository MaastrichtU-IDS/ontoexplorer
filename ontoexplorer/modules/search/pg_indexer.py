"""Populate the Postgres `entity_index` table from the Redis search index.

The Redis index (built by `indexer.build_index`) remains the source of truth: it owns
the heavy SPARQL → label/synonym/definition assembly. This module mirrors a slim
projection of that work into Postgres so /search can run as one SQL query with
real tsvector ranking and trigram fuzzy matching.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from sqlalchemy import text

from ontoexplorer.modules.search.indexer import (
    _get_redis,
    _iri_key,
    _type_key,
    normalise_label,
)


# Insert a space at every camelCase boundary: `aB → a B` and `XMLP → XML P`.
# Also splits snake_case and kebab-case. Critical because Postgres's `simple`
# tokenizer treats `PizzaSauce` as a single lexeme `pizzasauce`, which makes
# queries like `pizza sauce` fail to match it. By splitting before tsvector
# generation, the same label tokenizes as `pizza` + `sauce`.
_CAMEL_BOUNDARY_1 = re.compile(r"([a-z0-9])([A-Z])")  # aB
_CAMEL_BOUNDARY_2 = re.compile(r"([A-Z]+)([A-Z][a-z])")  # XMLP → XML P


def split_compound_labels(s: str) -> str:
    """Split camelCase / snake_case / kebab-case so tsvector & LIKE-prefix work.

    Examples:
        PizzaSauce            → Pizza Sauce
        pizza_sauce           → pizza sauce
        G-protein-coupled     → G protein coupled
        RNAPolymerase         → RNA Polymerase
    """
    if not s:
        return s
    s = _CAMEL_BOUNDARY_1.sub(r"\1 \2", s)
    s = _CAMEL_BOUNDARY_2.sub(r"\1 \2", s)
    s = s.replace("_", " ").replace("-", " ")
    return s

logger = logging.getLogger(__name__)

_ENTITY_TYPES = ("class", "object_property", "data_property", "annotation_property", "individual")


def _iter_version_iris(version_id: str) -> Iterable[str]:
    """Yield every entity IRI indexed for the version. Reads the per-type sets."""
    r = _get_redis()
    for entity_type in _ENTITY_TYPES:
        members = r.smembers(_type_key(version_id, entity_type))
        for iri in members:
            yield iri


def _build_search_text(entity: dict) -> str:
    """Concatenate every label + synonym for tsvector indexing.

    Each piece is also passed through split_compound_labels so camelCase /
    snake_case labels (`PizzaSauce`, `pizza_sauce`) tokenize as separate words
    in the tsvector. Both the raw and decamelized forms go in so the user can
    still match by the original spelling via prefix lookup.
    """
    parts: list[str] = []

    def _add(val: str) -> None:
        if not val:
            return
        if val not in parts:
            parts.append(val)
        decam = split_compound_labels(val)
        if decam != val and decam not in parts:
            parts.append(decam)

    _add(entity.get("primary_label") or entity.get("label") or "")
    _add(entity.get("short", ""))

    for field in ("labels", "synonyms"):
        raw = entity.get(field, "[]")
        try:
            items = json.loads(raw) if raw else []
        except (json.JSONDecodeError, ValueError):
            continue
        for item in items:
            _add(item.get("value", ""))

    return " ".join(parts)


async def populate_entity_index(
    session, version_id: str, ontology_id: str,
    non_roots: set[str] | None = None,
) -> int:
    """Mirror Redis entity records for *version_id* into the `entity_index` table.

    Deletes existing rows for the version first, then bulk-inserts. Returns the number
    of rows written. Safe to re-run; uses a single transaction.
    """
    r = _get_redis()
    # Deprecation is already computed during indexing and kept as a Redis set;
    # mirroring it here lets the SQL-backed navigation tree honour
    # hide_obsolete without a second lookup.
    from ontoexplorer.modules.search.indexer import _deprecated_key
    deprecated = {
        m.decode() if isinstance(m, bytes) else m
        for m in r.smembers(_deprecated_key(version_id))
    }

    # Entities that appear as a child in either hierarchy. Anything else is a
    # root; storing that here avoids an anti-join the planner handles badly.
    # None means "hierarchy not extracted", in which case no root is claimed.
    non_roots = non_roots if non_roots is not None else set()

    rows: list[dict] = []
    for iri in _iter_version_iris(version_id):
        entity = r.hgetall(_iri_key(version_id, iri))
        if not entity:
            continue

        primary_label = entity.get("primary_label") or entity.get("label") or entity.get("short", "")
        # Decamelize so `PizzaSauce` matches query `pizza sauce` via the fast
        # prefix tier. Both display label and original-spelling search are
        # preserved (search_text still includes the original form).
        primary_label_norm = normalise_label(split_compound_labels(primary_label))
        search_text = _build_search_text(entity)

        rows.append({
            "version_id": version_id,
            "iri": iri,
            "ontology_id": ontology_id,
            "type": entity.get("type", "class"),
            "primary_label": primary_label,
            "primary_label_norm": primary_label_norm,
            "short": entity.get("short", ""),
            "source": entity.get("source") or None,
            "search_text": search_text,
            "deprecated": iri in deprecated,
            "is_root": iri not in non_roots,
        })

    # Clear any prior rows for this version, then bulk insert.
    await session.execute(
        text("DELETE FROM entity_index WHERE version_id = :vid"),
        {"vid": version_id},
    )

    if rows:
        # executemany via SQLAlchemy 2.x async API
        await session.execute(
            text("""
                INSERT INTO entity_index
                    (version_id, iri, ontology_id, type,
                     primary_label, primary_label_norm, short, source, search_text,
                     deprecated, is_root)
                VALUES
                    (:version_id, :iri, :ontology_id, :type,
                     :primary_label, :primary_label_norm, :short, :source, :search_text,
                     :deprecated, :is_root)
            """),
            rows,
        )

    await session.commit()
    logger.info("entity_index populated", extra={"version_id": version_id, "rows": len(rows)})
    return len(rows)


def populate_entity_index_sync(
    version_id: str, ontology_id: str, non_roots: set[str] | None = None
) -> int:
    """Synchronous wrapper for use inside Celery tasks."""
    import asyncio

    from ontoexplorer.database import make_celery_db_session

    async def _run() -> int:
        async with make_celery_db_session()() as session:
            return await populate_entity_index(session, version_id, ontology_id, non_roots)

    return asyncio.run(_run())
