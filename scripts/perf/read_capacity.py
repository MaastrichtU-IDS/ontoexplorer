#!/usr/bin/env python3
"""Read-path capacity probe for an OntoExplorer instance.

Two modes:
  ramp     — one mixed, weighted scenario; ramps closed-loop concurrency and
             auto-aborts at the first knee (p95 over --abort-p95, or errors over
             --abort-err), so a shared instance is saturated only briefly.
  isolate  — ramps each endpoint class on its own, to see which backend caps
             first (search/autocomplete are Redis-backed; sparql hits Fuseki).

Measures client-side latency (the server /metrics histogram is not routed
externally). Uses only side-effect-free, id-free endpoints so it is safe to run
against a live instance: search, autocomplete, and a trivial SPARQL SELECT.
Downloads/views are excluded on purpose (they mutate usage counters).

Examples:
  python read_capacity.py ramp    --base https://ontoexplorer-perf.dev.k8s.semanticscience.org
  python read_capacity.py isolate --base https://ontoexplorer-perf.dev.k8s.semanticscience.org
"""
import argparse
import asyncio
import random
import time

import httpx

_SELECT = "SELECT ?s WHERE {?s ?p ?o} LIMIT 5"
_TERMS = ["cell", "process", "disease", "gene", "protein", "role", "quality", "continuant"]
_PREFIXES = ["cel", "pro", "dis", "gen", "rol", "qua", "con"]


def _sparql_path() -> str:
    return f"/api/v1/sparql?query={httpx.QueryParams({'q': _SELECT})['q']}"


ENDPOINTS = {
    "search": lambda: f"/api/v1/search?q={random.choice(_TERMS)}&limit=20",
    "autocomplete": lambda: f"/api/v1/autocomplete?q={random.choice(_PREFIXES)}",
    "sparql": _sparql_path,
}
# Realistic interactive weighting for the mixed ramp.
_MIX = ["search"] * 45 + ["autocomplete"] * 35 + ["sparql"] * 20


async def _one(client: httpx.AsyncClient, path: str) -> tuple[float, bool]:
    t0 = time.perf_counter()
    try:
        r = await client.get(path)
        return (time.perf_counter() - t0) * 1000, r.status_code < 400
    except Exception:
        return (time.perf_counter() - t0) * 1000, False


async def _step(client, concurrency, seconds, pick) -> dict:
    lat: list[float] = []
    ok = err = 0
    stop = time.perf_counter() + seconds

    async def worker():
        nonlocal ok, err
        while time.perf_counter() < stop:
            dt, good = await _one(client, pick())
            lat.append(dt)
            ok += good
            err += not good

    await asyncio.gather(*[worker() for _ in range(concurrency)])
    lat.sort()
    n = len(lat)

    def pct(p):
        return round(lat[min(n - 1, int(n * p / 100))]) if lat else 0

    return {
        "conc": concurrency, "rps": round(n / seconds, 1),
        "p50": pct(50), "p95": pct(95), "p99": pct(99),
        "err": round(100 * err / max(n, 1), 2),
    }


def _client(base, cap):
    limits = httpx.Limits(max_connections=cap + 20, max_keepalive_connections=cap + 20)
    return httpx.AsyncClient(base_url=base, timeout=20.0, verify=False, limits=limits)


async def ramp(base, steps, seconds, abort_p95, abort_err):
    pick = lambda: ENDPOINTS[random.choice(_MIX)]()
    async with _client(base, max(steps)) as client:
        print(f"{'conc':>5}{'rps':>8}{'p50':>7}{'p95':>8}{'p99':>8}{'err%':>7}")
        for c in steps:
            s = await _step(client, c, seconds, pick)
            print(f"{s['conc']:>5}{s['rps']:>8}{s['p50']:>7}{s['p95']:>8}{s['p99']:>8}{s['err']:>7}")
            if s["err"] > abort_err or s["p95"] > abort_p95:
                print(f"\nknee at conc={c} (p95={s['p95']}ms err={s['err']}%)")
                return


async def isolate(base, steps, seconds):
    async with _client(base, max(steps)) as client:
        for name, mk in ENDPOINTS.items():
            print(f"\n{name}:")
            for c in steps:
                s = await _step(client, c, seconds, mk)
                print(f"   conc={c:>3}  rps={s['rps']:>7}  p95={s['p95']:>6}ms  err={s['err']}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["ramp", "isolate"])
    ap.add_argument("--base", required=True)
    ap.add_argument("--steps", default="1,2,5,10,20,35,50,75,100")
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--abort-p95", type=int, default=3000)
    ap.add_argument("--abort-err", type=float, default=2.0)
    a = ap.parse_args()
    steps = [int(x) for x in a.steps.split(",")]
    if a.mode == "ramp":
        asyncio.run(ramp(a.base, steps, a.seconds, a.abort_p95, a.abort_err))
    else:
        asyncio.run(isolate(a.base, steps, a.seconds))
