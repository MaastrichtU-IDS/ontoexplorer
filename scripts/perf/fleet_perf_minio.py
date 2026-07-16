"""Fleet perf bench v2: read each ontology blob from MinIO directly
(skip the SPARQL CONSTRUCT API which timed out for the giants).
Convert via pyoxigraph to NT, submit to /classify.

To stay safe under memory pressure:
  - /classify only for ontologies above SAFE_JUSTIFY_TRIPLES (1M+)
    — the giants OOM elk-service on /justification (proven on cl)
  - /classify AND /justification below that
"""
import io, os, time, json, sys, requests
sys.path.insert(0, "/app")
from ontoexplorer.clients.minio import get_minio_client, download_bytes
import pyoxigraph

SAFE_JUSTIFY_TRIPLES = 700_000  # cl-scale and above → skip /justification

# Talk to reasoner-service via the docker network from inside worker.
ELK = "http://reasoner-service:8001"
API = "http://api:8000"

def fetch_blob(oid: str, vid: str, sha: str, ext: str) -> bytes:
    key = f"{oid}/{vid}/{sha}.{ext}"
    return download_bytes("ontologies", key)

def to_ntriples(blob: bytes, ext: str) -> str:
    """RDF/XML / Turtle / etc → NT via pyoxigraph."""
    fmt_map = {
        "owl": pyoxigraph.RdfFormat.RDF_XML,
        "rdf": pyoxigraph.RdfFormat.RDF_XML,
        "xml": pyoxigraph.RdfFormat.RDF_XML,
        "ttl": pyoxigraph.RdfFormat.TURTLE,
        "nt":  pyoxigraph.RdfFormat.N_TRIPLES,
    }
    src_fmt = fmt_map.get(ext, pyoxigraph.RdfFormat.RDF_XML)
    triples = pyoxigraph.parse(io.BytesIO(blob), format=src_fmt)
    return pyoxigraph.serialize(triples, format=pyoxigraph.RdfFormat.N_TRIPLES).decode("utf-8")

ontos = requests.get(f"{API}/api/v1/ontologies?limit=100").json()["ontologies"]
sortable = sorted(
    [(o["shortname"], o["id"], o["latest_version"]) for o in ontos if o.get("latest_version")],
    key=lambda r: r[2].get("triple_count") or 0,
)

results = []
for short, oid, lv in sortable:
    if short.startswith(("globally-inconsistent","inconsistent")):
        continue
    tc = lv.get("triple_count") or 0
    sha = lv.get("sha256","")
    fmt = lv.get("format","owl")
    # Only re-bench the ones the previous run couldn't NT-dump:
    if short not in ("hp","uberon","mp","go","mondo","cl"):
        continue
    print(f"\n=== {short} (triples={tc}, fmt={fmt}) ===", flush=True)
    t0 = time.monotonic()
    try:
        blob = fetch_blob(oid, lv["id"], sha, fmt)
        print(f"  blob: {len(blob)//1024} KB in {time.monotonic()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"  blob fetch failed: {e}"); continue
    t0 = time.monotonic()
    try:
        nt = to_ntriples(blob, fmt)
        print(f"  → NT: {len(nt)//1024} KB in {time.monotonic()-t0:.1f}s", flush=True)
    except Exception as e:
        print(f"  NT conversion failed: {e}"); continue

    vid_b = f"minio-bench-{short}-{int(time.time())}"
    t0 = time.monotonic()
    r = requests.post(f"{ELK}/classify", json={"version_id": vid_b, "ntriples": nt}, timeout=120)
    while time.monotonic()-t0 < 900:
        time.sleep(2)
        g = requests.get(f"{ELK}/classify/{vid_b}", timeout=30)
        if g.status_code == 200: break
        if g.status_code == 500:
            err = g.json().get("detail","?")
            print(f"  ✗ classify failed: {err[:200]}"); break
    if g.status_code == 200:
        classify_t = time.monotonic()-t0
        d = g.json()
        print(f"  ✓ /classify: {classify_t:.1f}s classes={d['class_count']} inferred={sum(len(v) for v in d.get('superclasses',{}).values())}", flush=True)
        if tc < SAFE_JUSTIFY_TRIPLES:
            pair = next(((s, supers[0]) for s,supers in d['superclasses'].items() if supers), None)
            if pair:
                t0 = time.monotonic()
                try:
                    jr = requests.post(f"{ELK}/classify/{vid_b}/justification",
                        json={"sub": pair[0], "sup": pair[1], "max_justifications": 1}, timeout=600)
                    jd = jr.json()
                    print(f"  ✓ /justification: {time.monotonic()-t0:.1f}s found={jd.get('justifications_found')}")
                except Exception as e:
                    print(f"  ✗ /justification: {e}")
        else:
            print(f"  → skipping /justification (triples >= {SAFE_JUSTIFY_TRIPLES}, OOM risk)")
