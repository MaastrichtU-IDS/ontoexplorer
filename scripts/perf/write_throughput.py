#!/usr/bin/env python3
"""Write/reasoning throughput probe for an OntoExplorer instance.

The write path is async: POST /ontologies returns a task_id and a Celery job does
fetch -> parse -> load Oxigraph (SINGLE writer, write queue concurrency=1) ->
reason -> FAIR metadata. So this does not measure RPS; it submits a batch of
DISTINCT ontologies at once and reports each job's end-to-end latency, the
serial throughput, and any failures with their error.

Distinct ontologies matter: re-submitting content already in the store hits the
dedup fast-path and returns in seconds, which inflates throughput and can race
two identical submissions against the version-uniqueness constraint. The default
list is distinct public OBO ontologies (fetched via the egress proxy).

FOR AN ISOLATED PERF ENVIRONMENT — it mutates data and drives the reasoner hard.
Uses AUTH_BYPASS if the target has it (no token); else pass --token.

  python write_throughput.py --base https://ontoexplorer-perf.dev.k8s.semanticscience.org
"""
import argparse
import asyncio
import time

import httpx

DEFAULT_SOURCES = [
    "http://purl.obolibrary.org/obo/iao.owl",
    "http://purl.obolibrary.org/obo/so.owl",
    "http://purl.obolibrary.org/obo/doid.owl",
    "http://purl.obolibrary.org/obo/symp.owl",
    "http://purl.obolibrary.org/obo/trans.owl",
    "http://purl.obolibrary.org/obo/envo.owl",
    "http://purl.obolibrary.org/obo/foodon.owl",
    "http://purl.obolibrary.org/obo/ohd.owl",
    "http://purl.obolibrary.org/obo/mp.owl",
    "http://purl.obolibrary.org/obo/pato.owl",
]


async def _submit(client, source):
    r = await client.post("/api/v1/ontologies", json={"url": source})
    r.raise_for_status()
    return r.json()["task_id"]


async def _poll(client, task_id, timeout_s):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        r = await client.get(f"/api/v1/jobs/{task_id}")
        if r.status_code == 200:
            d = r.json()
            if d.get("status") in ("done", "failed"):
                return d.get("status"), d.get("error")
        await asyncio.sleep(1.5)
    return "timeout", None


async def _run(client, source, timeout_s):
    name = source.rstrip("/").split("/")[-1]
    t0 = time.perf_counter()
    try:
        task_id = await _submit(client, source)
    except Exception as exc:
        return {"src": name, "status": "submit-error", "err": str(exc)[:90], "lat": 0.0}
    status, err = await _poll(client, task_id, timeout_s)
    return {"src": name, "status": status, "err": (err or "")[:90],
            "lat": round(time.perf_counter() - t0, 1)}


async def main(base, token, sources, timeout_s):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30.0, verify=False) as client:
        v = await client.get("/api/v1/version")
        print(f"target {base}  version {v.json() if v.status_code == 200 else v.status_code}")
        t0 = time.perf_counter()
        results = await asyncio.gather(*[_run(client, s, timeout_s) for s in sources])
        wall = time.perf_counter() - t0

    print(f"\n{'ontology':16}{'status':9}{'lat(s)':>8}  error")
    for r in sorted(results, key=lambda x: x["lat"]):
        print(f"{r['src']:16}{r['status']:9}{r['lat']:>8}  {r['err']}")
    done = [r for r in results if r["status"] == "done"]
    lats = sorted(r["lat"] for r in done)
    print(f"\nK={len(sources)} submitted at once | wall={wall:.1f}s | "
          f"done={len(done)} failed={sum(r['status'] == 'failed' for r in results)} "
          f"timeout={sum(r['status'] == 'timeout' for r in results)}")
    if done:
        print(f"serial throughput={len(done) / wall * 60:.1f} jobs/min | "
              f"per-job p50={lats[len(lats) // 2]}s max={max(lats)}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", default=None)
    ap.add_argument("--sources", default=None, help="file with one source URL per line")
    ap.add_argument("--timeout", type=int, default=600, help="per-job timeout seconds")
    a = ap.parse_args()
    srcs = [l.strip() for l in open(a.sources) if l.strip()] if a.sources else DEFAULT_SOURCES
    asyncio.run(main(a.base, a.token, srcs, a.timeout))
