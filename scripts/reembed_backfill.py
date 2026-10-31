#!/usr/bin/env python
"""Shadow-table re-embed backfill (plan Task 4).

Writes ONLY ``term_embeddings_new``; never touches the live ``term_embeddings``.
Run inside a dev pod (needs DATABASE_URL, EMBEDDING_BASE_URL, EMBEDDING_API_KEY):

    python scripts/reembed_backfill.py --dry-run 2        # 2 smallest versions
    python scripts/reembed_backfill.py --versions a,b,c
    python scripts/reembed_backfill.py --all              # FULL run (explicit)
    python scripts/reembed_backfill.py --build-index      # after backfill (HNSW)
    python scripts/reembed_backfill.py --verify

No flags prints help and does nothing.

Resumable: finished versions are recorded in ``term_embeddings_new_done``; inserts
use ON CONFLICT DO NOTHING so a crash mid-version resumes cleanly (rows already
written are kept; the re-embed of those rows is wasted compute only).

Entity text is built by ``tasks.build_version_records`` -- the same function
``embed_ontology`` uses -- so text/text_hash can never diverge from the producer.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from ontoexplorer.database import make_celery_db_session
from ontoexplorer.modules.jobs.tasks import build_version_records
from ontoexplorer.modules.search import embed_client
from ontoexplorer.modules.search.embed_client import MODEL_REV

log = logging.getLogger("reembed_backfill")

NEW = "term_embeddings_new"
DONE = "term_embeddings_new_done"
DOC_PREFIX = "search_document: "  # verbatim (Global Constraints)
CHUNK = 256          # rows per embed request / insert statement
WORKERS = 4          # concurrent embed requests (bounded)
DIM = 768

_Session = make_celery_db_session()  # NullPool: safe across asyncio.run() calls


def _run(coro):
    return asyncio.run(coro)


async def _exec(sql: str, params=None, many=None):
    async with _Session() as db:
        if many is not None:
            await db.execute(text(sql), many)
            await db.commit()
            return None
        res = await db.execute(text(sql), params or {})
        rows = res.all() if res.returns_rows else None
        await db.commit()
        return rows


# --------------------------------------------------------------------- step 1
def create_shadow_table() -> None:
    """Explicit DDL (NOT LIKE ... INCLUDING ALL: that would copy the HNSW index and omit the FK)."""
    _run(_exec(f"""
        CREATE TABLE IF NOT EXISTS {NEW} (
            id          VARCHAR PRIMARY KEY,
            version_id  VARCHAR NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
            entity_iri  TEXT NOT NULL,
            entity_type VARCHAR NOT NULL,
            text_hash   VARCHAR NOT NULL,
            embedding   vector({DIM}) NOT NULL,
            model_rev   VARCHAR,
            CONSTRAINT uq_{NEW}_version_iri UNIQUE (version_id, entity_iri)
        )"""))
    _run(_exec(f"CREATE INDEX IF NOT EXISTS {NEW}_version_id_idx ON {NEW} (version_id)"))
    _run(_exec(f"CREATE TABLE IF NOT EXISTS {DONE} (version_id VARCHAR PRIMARY KEY, n_rows INTEGER, done_at TIMESTAMPTZ DEFAULT now())"))
    log.info("shadow table ready (no HNSW index)")


# --------------------------------------------------------------------- step 2
def list_versions(*, only_nonzero: bool = False) -> list[tuple[str, str, int]]:
    """(version_id, ontology_id, current term_embeddings count), count DESC."""
    having = "HAVING count(te.id) > 0" if only_nonzero else ""
    rows = _run(_exec(f"""
        SELECT v.id, v.ontology_id, count(te.id) AS n
        FROM versions v LEFT JOIN term_embeddings te ON te.version_id = v.id
        GROUP BY v.id, v.ontology_id {having}
        ORDER BY n DESC, v.id"""))
    return [(r[0], r[1], int(r[2])) for r in rows]


def done_set() -> set[str]:
    return {r[0] for r in _run(_exec(f"SELECT version_id FROM {DONE}"))}


def _vec(v: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def _insert_chunk(version_id: str, batch, vectors) -> None:
    import uuid
    rows = [
        {"id": str(uuid.uuid4()), "v": version_id, "iri": iri, "t": etype, "h": h,
         "e": _vec(emb), "r": MODEL_REV}
        for (iri, etype, _txt, h), emb in zip(batch, vectors)
    ]
    _run(_exec(
        f"INSERT INTO {NEW} (id, version_id, entity_iri, entity_type, text_hash, embedding, model_rev) "
        "VALUES (:id, :v, :iri, :t, :h, CAST(:e AS vector), :r) "
        "ON CONFLICT (version_id, entity_iri) DO NOTHING",
        many=rows))


def backfill_version(version_id: str, ontology_id: str, pool: ThreadPoolExecutor) -> int:
    records = build_version_records(version_id, ontology_id)
    if records:
        batches = [records[i:i + CHUNK] for i in range(0, len(records), CHUNK)]
        # Bounded concurrency: embed up to WORKERS chunks in parallel, insert in order.
        # Process in windows so memory stays bounded for the ~336k-entity versions.
        win = WORKERS * 2
        for w in range(0, len(batches), win):
            window = batches[w:w + win]
            vecs = list(pool.map(
                lambda b: embed_client.embed_batch([r[2] for r in b], prefix=DOC_PREFIX), window))
            for b, vv in zip(window, vecs):
                _insert_chunk(version_id, b, vv)
    _run(_exec(f"INSERT INTO {DONE} (version_id, n_rows) VALUES (:v, :n) ON CONFLICT DO NOTHING",
               {"v": version_id, "n": len(records)}))
    return len(records)


def backfill(versions: list[tuple[str, str, int]]) -> None:
    create_shadow_table()
    done = done_set()
    todo = [v for v in versions if v[0] not in done]
    log.info("versions: %d requested, %d already done, %d to do", len(versions), len(versions) - len(todo), len(todo))
    total, t0 = 0, time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, (vid, oid, old_n) in enumerate(todo, 1):
            t1 = time.time()
            try:
                n = backfill_version(vid, oid, pool)
            except Exception:
                log.exception("version %s failed; continuing (rerun resumes it)", vid)
                continue
            total += n
            log.info("[%d/%d] %s ontology=%s old_count=%d embedded=%d in %.1fs (total=%d, elapsed=%.0fs, fallback_uses=%d)",
                     i, len(todo), vid, oid, old_n, n, time.time() - t1, total, time.time() - t0,
                     getattr(embed_client, "FALLBACK_COUNT", 0))


# --------------------------------------------------------------------- step 3
def build_hnsw_index() -> None:
    """Build the HNSW index on the shadow table. NEVER auto-run by --dry-run.

    Live index (pg_indexes): ``CREATE INDEX term_embeddings_embedding_idx ON term_embeddings
    USING hnsw (embedding vector_cosine_ops)`` -- default params (m=16, ef_construction=64).

    Live index (pg_indexes): default params (m=16, ef_construction=64).

    Ideal ``maintenance_work_mem`` is ~12GB (3.96M x 768 x 4B) to keep the whole
    graph in memory, but THIS Postgres pod is limited to 16Gi (shared_buffers +
    everything else live in there too), so 14GB would OOM-kill it. We set 8GB:
    safely under the limit, at the cost of pgvector spilling to the slower on-disk
    build path. Acceptable for a one-time build. If it is too slow, bump the
    postgres pod memory temporarily and raise this instead. Live default is 512MB.
    """
    async def _go():
        async with _Session() as db:
            # 8GB, NOT 14GB: postgres pod limit is 16Gi (see docstring).
            await db.execute(text("SET maintenance_work_mem = '8GB'"))
            await db.execute(text("SET max_parallel_maintenance_workers = 4"))
            await db.execute(text(
                f"CREATE INDEX IF NOT EXISTS {NEW}_embedding_idx ON {NEW} "
                "USING hnsw (embedding vector_cosine_ops)"))
            await db.commit()
    t0 = time.time()
    _run(_go())
    log.info("HNSW index built in %.0fs", time.time() - t0)


# --------------------------------------------------------------------- step 4
def verify() -> bool:
    new_n = _run(_exec(f"SELECT count(*) FROM {NEW}"))[0][0]
    old_n = _run(_exec("SELECT count(*) FROM term_embeddings"))[0][0]
    bad = _run(_exec(f"SELECT count(*) FROM {NEW} WHERE model_rev IS DISTINCT FROM :r", {"r": MODEL_REV}))[0][0]
    log.info("verify: new=%d old=%d (diff=%d) rows_with_wrong_model_rev=%d", new_n, old_n, old_n - new_n, bad)
    assert bad == 0, f"{bad} rows have model_rev != {MODEL_REV}"
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", type=int, metavar="N", help="process only the N smallest (non-empty) versions; no HNSW")
    ap.add_argument("--versions", help="comma-separated version ids")
    ap.add_argument("--all", action="store_true", help="FULL backfill of every version (explicit opt-in)")
    ap.add_argument("--build-index", action="store_true", help="build HNSW on term_embeddings_new")
    ap.add_argument("--verify", action="store_true", help="count vs old table + model_rev check")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not (args.dry_run or args.versions or args.all or args.build_index or args.verify):
        ap.print_help()
        return 0

    if args.dry_run:
        smallest = list_versions(only_nonzero=True)[::-1][:args.dry_run]
        backfill(smallest)
    if args.versions:
        want = [x.strip() for x in args.versions.split(",") if x.strip()]
        by_id = {v[0]: v for v in list_versions()}
        missing = [w for w in want if w not in by_id]
        if missing:
            log.error("unknown version ids: %s", missing)
            return 2
        backfill([by_id[w] for w in want])
    if args.all:
        backfill(list_versions())
    if args.build_index:
        build_hnsw_index()
    if args.verify:
        verify()
    return 0


if __name__ == "__main__":
    sys.exit(main())
