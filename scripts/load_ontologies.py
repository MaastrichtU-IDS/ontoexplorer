#!/usr/bin/env python3
"""Bulk-load ontologies into OntoExplorer from LOV and BioPortal.

Small-first, size-capped, deduped, paced. Dry-run by default (prints the plan);
pass --apply to actually submit. Ingest auth is a write-scoped OntoExplorer API
key (Authorization: Bearer). BioPortal listing needs a BioPortal API key.

  python load_ontologies.py --source lov --limit 15               # dry run
  python load_ontologies.py --source bioportal --limit 10 --max-classes 50000 --bp-key ... 
  python load_ontologies.py --source both --apply --oe-key oe_... --bp-key ... --group bulk-import
"""
import argparse, sys, time
import httpx

LOV_SPARQL = "https://lov.linkeddata.es/dataset/sparql"   # follows the /dataset/lov -> /dataset redirect target
BP = "https://data.bioontology.org"

def lov_list(limit):
    """Vocabularies + their preferred namespace URI (the dereferenceable id)."""
    # LOV namespace URIs often don't dereference to RDF (404), so ingest the
    # LOV-hosted latest distribution instead: the newest dcat:distribution URI
    # (they end in the version date, so MAX = latest) + ".n3" (the only format
    # LOV serves at that path).
    q = ("PREFIX voaf: <http://purl.org/vocommons/voaf#> "
         "PREFIX vann: <http://purl.org/vocab/vann/> "
         "PREFIX dcterms: <http://purl.org/dc/terms/> "
         "PREFIX dcat: <http://www.w3.org/ns/dcat#> "
         "SELECT ?v ?prefix (MAX(?dist) AS ?latest) (SAMPLE(?t) AS ?title) WHERE { "
         "?v a voaf:Vocabulary ; vann:preferredNamespacePrefix ?prefix ; dcat:distribution ?dist . "
         "OPTIONAL { ?v dcterms:title ?t } } GROUP BY ?v ?prefix ORDER BY ?prefix")
    r = httpx.get(LOV_SPARQL, params={"query": q}, headers={"Accept": "application/sparql-results+json"},
                  follow_redirects=True, timeout=90)
    r.raise_for_status()
    out, seen = [], set()
    for b in r.json()["results"]["bindings"]:
        latest = b.get("latest", {}).get("value")
        prefix = b.get("prefix", {}).get("value", "")
        if latest and prefix not in seen:
            seen.add(prefix)
            out.append({"id": (latest if latest.endswith(".n3") else latest + ".n3"), "kind": "url",
                        "label": b.get("title", {}).get("value", prefix), "src": "lov", "key": prefix.lower()})
    return out[:limit] if limit else out

# Curated seed of popular biomedical ontologies. This key's /ontologies only
# lists its own administered ontology (SIO), but it can fetch any public one by
# acronym, so we enumerate from a seed and let the class-count cap skip giants.
BP_SEED = ["BFO","RO","IAO","OBI","SIO","DOID","PATO","UO","ENVO","CL","SO","ECO",
           "UBERON","HP","MONDO","MP","OBA","FOODON","AGRO","GO","CHEBI","NCIT"]

def bioportal_list(bp_key, limit, max_classes, acronyms=None):
    """Ontologies whose latest submission has <= max_classes (skip the giants)."""
    acrs = acronyms or BP_SEED
    out = []
    for acr in acrs:
        try:
            m = httpx.get(f"{BP}/ontologies/{acr}/metrics", params={"apikey": bp_key}, timeout=30)
            classes = (m.json() or {}).get("classes") if m.status_code == 200 else None
        except Exception:
            classes = None
        if classes is None:
            continue                    # no submission/metrics -> skip
        classes = int(classes)
        if max_classes and classes > max_classes:
            continue                    # too big for the small-first batch
        # Prefer the clean OBO PURL (no apikey in the stored IRI); fall back to the
        # BioPortal download URL for non-OBO ontologies.
        purl = f"http://purl.obolibrary.org/obo/{acr.lower()}.owl"
        obo = httpx.head(purl, follow_redirects=True, timeout=15)
        if obo.status_code < 400:
            item = {"id": purl, "kind": "iri"}
        else:
            item = {"id": f"{BP}/ontologies/{acr}/download?apikey={bp_key}", "kind": "url"}
        item.update({"label": f"{acr} ({classes} classes)", "src": "bioportal", "acr": acr, "classes": classes, "key": acr.lower()})
        out.append(item)
        if limit and len(out) >= limit:
            break
    return out

def existing(base, oe_key):
    # Paginate through ALL ontologies so dedup works on a large corpus. Without
    # an explicit limit the API returns only the first page, so on an instance
    # that already holds many ontologies the loader would re-submit ones past
    # page 1 (harmless server-side, but wasteful re-downloads).
    h = {"Authorization": f"Bearer {oe_key}"} if oe_key else {}
    iris, names = set(), set()
    offset, PAGE = 0, 500
    while True:
        r = httpx.get(f"{base}/api/v1/ontologies", headers=h,
                      params={"limit": PAGE, "offset": offset},
                      timeout=60, follow_redirects=True)
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("ontologies", data.get("items", []))
        for o in items:
            for k in ("iri", "namespace", "shortname", "acronym"):
                if o.get(k): iris.add(str(o[k]).rstrip("/#"))
            if o.get("shortname"): names.add(str(o["shortname"]).lower())
        if len(items) < PAGE:
            break
        offset += PAGE
    return iris, names

def submit(base, oe_key, item, groups=None):
    body = {item["kind"]: item["id"]}
    if groups:
        body["groups"] = groups
    r = httpx.post(f"{base}/api/v1/ontologies", json=body,
                   headers={"Authorization": f"Bearer {oe_key}"}, timeout=60, follow_redirects=True)
    return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else r.text[:200])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://ontoexplorer.dev.k8s.semanticscience.org")
    ap.add_argument("--source", choices=["lov","bioportal","both"], default="both")
    ap.add_argument("--limit", type=int, default=15, help="max per source")
    ap.add_argument("--max-classes", type=int, default=50000, help="BioPortal size cap")
    ap.add_argument("--oe-key", default="", help="OntoExplorer write API key")
    ap.add_argument("--bp-key", default="", help="BioPortal API key")
    ap.add_argument("--apply", action="store_true", help="actually submit (default: dry run)")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between submits")
    ap.add_argument("--group", action="append", default=[], metavar="TAG",
                    help="extra group tag applied to every loaded ontology (repeatable). "
                         "Each ontology is ALSO tagged with its source group "
                         "('bioportal' or 'lov'), so you can filter by source or by batch.")
    a = ap.parse_args()

    items = []
    if a.source in ("lov","both"):
        items += lov_list(a.limit)
    if a.source in ("bioportal","both"):
        if not a.bp_key:
            print("! bioportal source requested but --bp-key missing; skipping bioportal", file=sys.stderr)
        else:
            items += bioportal_list(a.bp_key, a.limit, a.max_classes)

    seen, names = existing(a.base, a.oe_key) if a.oe_key else (set(), set())
    fresh = [it for it in items
             if it["id"].rstrip("/#").split("?")[0] not in seen
             and (it.get("key") or "~") not in names]
    print(f"# candidates={len(items)} already-loaded-skipped={len(items)-len(fresh)} to-submit={len(fresh)} apply={a.apply}")
    for it in fresh:
        print(f"  [{it['src']}] {it['kind']}={it['id'][:90]}  ({it['label'][:50]})")

    if not a.apply:
        print("\n(dry run — pass --apply with --oe-key to submit)"); return
    if not a.oe_key:
        print("! --apply requires --oe-key", file=sys.stderr); sys.exit(2)
    ok=fail=0
    for it in fresh:
        groups = [it["src"], *a.group]
        code, resp = submit(a.base, a.oe_key, it, groups)
        tag = resp.get("task_id","")[:8] if isinstance(resp, dict) else ""
        print(f"  {'OK ' if code<300 else 'ERR'} http={code} task={tag} {it['src']}:{it['label'][:40]}")
        ok += code < 300; fail += code >= 300
        time.sleep(a.delay)
    print(f"\nsubmitted ok={ok} fail={fail}")

if __name__ == "__main__":
    main()
