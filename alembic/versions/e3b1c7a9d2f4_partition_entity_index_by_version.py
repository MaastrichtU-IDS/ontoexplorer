"""partition entity_index by version_id (HASH, modulus 64)

Rebuilds `entity_index` as a HASH-partitioned table keyed on `version_id` so that a
per-version (re)index maintains GINs/btrees that are ~1/64 the size of the shared
indexes. Measured on dev (2026-10-15): per-version populate 113.6s -> ~15.5s (~7x);
the win compounds as update-polling accumulates versions (each version's ~tens-of-k
rows otherwise bloat the global 2-GIN/9-btree index set). Also makes version
hard-delete (`DELETE ... WHERE version_id`) churn only one partition's indexes.
See issue #353 for the full design, the dry-run measurements, and why HASH/modulus-64
(vs LIST-per-version or hash-by-ontology).

Postgres can't convert a plain table to partitioned in place, so this is a
create-new -> backfill -> bulk-build-indexes -> atomic swap. The backfill + index
build is ~12 min on the current ~5.9M rows (one-time); reads against the live table
continue until the sub-second drop+rename at the end. Ensure no index task writes
`entity_index` during the migration (a version written mid-migration would need
re-indexing) — deploy-time migration, workers restart with the roll.

Partitioning is physical only: the SQLAlchemy `EntityIndex` model stays a plain table
(the ORM and SQLite tests are unaffected; partitioning is transparent to every reader,
the planner prunes on `version_id` predicates). PostgreSQL-only — SQLite skips.

Revision ID: e3b1c7a9d2f4
Revises: a7c3e9d1f0b2
Create Date: 2026-10-15
"""
from alembic import op

revision = "e3b1c7a9d2f4"
down_revision = "a7c3e9d1f0b2"
branch_labels = None
depends_on = None

# The non-generated columns, copied verbatim on backfill (search_tsv is a STORED
# generated column — recomputed, never inserted).
_COLS = (
    "version_id, iri, ontology_id, type, primary_label, primary_label_norm, short, "
    "source, search_text, deprecated, is_root, is_individual, labels, primary_lang, "
    "synonyms, definitions, types"
)

# (canonical name, CREATE INDEX body) for every live index EXCEPT the primary key.
# These must stay byte-identical to the existing index set so no search path regresses.
_INDEXES = [
    ("entity_index_tsv", "USING gin (search_tsv)"),
    ("entity_index_norm_trgm", "USING gin (primary_label_norm gin_trgm_ops)"),
    ("entity_index_norm_c", '(primary_label_norm COLLATE "C")'),
    ("entity_index_norm_prefix", "(primary_label_norm text_pattern_ops)"),
    ("ix_entity_index_lower_label", "(lower(primary_label))"),
    ("ix_entity_index_short", "(short)"),
    ("ix_entity_index_individuals",
     "(version_id, lower(primary_label), iri) WHERE is_individual"),
    ("ix_entity_index_roots", "(version_id, type) WHERE is_root"),
    ("entity_index_ontology", "(ontology_id)"),
    ("entity_index_version", "(version_id)"),
]

_PARTITIONS = 64


def _build_table(name: str, *, partitioned: bool) -> None:
    """Create `name` as a faithful copy of entity_index's columns, with PK, the full
    index set (under `<name>`-prefixed temp names), and both FKs. Backfill happens
    separately. When `partitioned`, hash-partition on version_id with _PARTITIONS parts."""
    part_clause = "PARTITION BY HASH (version_id)" if partitioned else ""
    op.execute(
        f"CREATE TABLE {name} "
        f"(LIKE entity_index INCLUDING GENERATED INCLUDING DEFAULTS) {part_clause}"
    )
    if partitioned:
        op.execute(
            f"""
            DO $$ BEGIN
              FOR i IN 0..{_PARTITIONS - 1} LOOP
                EXECUTE format(
                  'CREATE TABLE %I PARTITION OF {name} '
                  'FOR VALUES WITH (MODULUS {_PARTITIONS}, REMAINDER %s)',
                  '{name}_p' || lpad(i::text, 2, '0'), i);
              END LOOP;
            END $$;
            """
        )


def _backfill_and_index(name: str) -> None:
    """Copy all rows from entity_index into `name`, then bulk-build PK + indexes + FKs.
    Index names carry a `_mig` suffix to avoid clashing with the live table's names;
    the swap renames them to canonical."""
    op.execute(f"INSERT INTO {name} ({_COLS}) SELECT {_COLS} FROM entity_index")
    op.execute(f"ALTER TABLE {name} ADD CONSTRAINT {name}_pkey PRIMARY KEY (version_id, iri)")
    for canonical, body in _INDEXES:
        op.execute(f"CREATE INDEX {canonical}_mig ON {name} {body}")
    op.execute(
        f"ALTER TABLE {name} ADD CONSTRAINT {name}_version_fk "
        "FOREIGN KEY (version_id) REFERENCES versions(id) ON DELETE CASCADE"
    )
    op.execute(
        f"ALTER TABLE {name} ADD CONSTRAINT {name}_ontology_fk "
        "FOREIGN KEY (ontology_id) REFERENCES ontologies(id) ON DELETE CASCADE"
    )


def _swap_into_place(staging: str) -> None:
    """Drop the live entity_index, rename `staging` -> entity_index, and rename its PK,
    constraints and indexes from the temp names to canonical. Sub-second; run last."""
    op.execute("DROP TABLE entity_index")
    op.execute(f"ALTER TABLE {staging} RENAME TO entity_index")
    # PK: constraint and its backing index are separate catalog entries — rename both.
    op.execute(f"ALTER TABLE entity_index RENAME CONSTRAINT {staging}_pkey TO entity_index_pkey")
    op.execute(f"ALTER INDEX {staging}_pkey RENAME TO entity_index_pkey")
    op.execute(f"ALTER TABLE entity_index RENAME CONSTRAINT {staging}_version_fk TO entity_index_version_id_fkey")
    op.execute(f"ALTER TABLE entity_index RENAME CONSTRAINT {staging}_ontology_fk TO entity_index_ontology_id_fkey")
    for canonical, _ in _INDEXES:
        op.execute(f"ALTER INDEX {canonical}_mig RENAME TO {canonical}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # partitioning + GIN are Postgres-only; SQLite tests use metadata.create_all
    _build_table("entity_index_part", partitioned=True)
    _backfill_and_index("entity_index_part")
    _swap_into_place("entity_index_part")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Reverse swap: rebuild a plain (non-partitioned) entity_index and cut back over.
    _build_table("entity_index_plain", partitioned=False)
    _backfill_and_index("entity_index_plain")
    _swap_into_place("entity_index_plain")
