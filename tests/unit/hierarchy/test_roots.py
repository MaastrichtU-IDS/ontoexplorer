"""Root detection must not read the whole ontology to answer with a handful of roots.

Measured on DRON (784,921 classes) before this change: the root call took 61.8 s
to return 5 terms. It ran two full enumerations —

  pass 1  every class + OPTIONAL rdfs:label, ORDER BY ?class   771,543 rows  44.6 s
  pass 2  every class having a named parent                    771,507 rows  13.7 s

— then subtracted in Python. Labels were fetched and sorted for 771k classes so
that 5 could be displayed, and pass 2's `?class a owl:Class` / `?parent a
owl:Class` guards cost 8 s while changing the result by 0 IRIs (isIRI already
excludes blank nodes, and the result is intersected with the known class set).

So: enumerate IRIs only, subtract, then fetch labels for the survivors.
"""

from ontoexplorer.modules.hierarchy.roots import (
    LABEL_CHUNK,
    compute_roots,
    invalidate_root_cache,
    root_cache_key,
)


class FakeRow:
    def __init__(self, value, lang=None):
        self.value = value
        self.language = lang


class FakeStore:
    """Dispatches on query shape; records every query it is asked to run."""

    def __init__(self, classes, edges, labels=None):
        self.classes = classes                    # iri -> None
        self.edges = edges                        # child -> parent
        self.labels = labels or {}                # iri -> (label, lang)
        self.queries: list[str] = []

    def query(self, q):
        self.queries.append(q)
        if "VALUES" in q:
            # Mirrors pyoxigraph: every selected variable is present, and an
            # unbound OPTIONAL reads back as None.
            out = []
            for iri in self.classes:
                if f"<{iri}>" not in q:
                    continue
                if iri in self.labels:
                    lbl, lang = self.labels[iri]
                    out.append({"class": FakeRow(iri), "label": FakeRow(lbl, lang)})
                else:
                    out.append({"class": FakeRow(iri), "label": None})
            return out
        if "subClassOf" in q:
            return [{"class": FakeRow(c)} for c in self.edges]
        return [{"class": FakeRow(c)} for c in self.classes]


def _store():
    return FakeStore(
        classes=["http://x/A", "http://x/B", "http://x/C", "http://x/D"],
        edges={"http://x/B": "http://x/A", "http://x/C": "http://x/A"},
        labels={
            "http://x/A": ("Alpha", "en"),
            "http://x/D": ("delta", "en"),
            "http://x/B": ("Beta", "en"),
        },
    )


def test_returns_only_classes_without_a_named_parent():
    s = _store()
    roots = compute_roots(s, "urn:g")
    assert [r[0] for r in roots] == ["http://x/A", "http://x/D"]


def test_sorted_case_insensitively_by_label_falling_back_to_iri():
    s = _store()
    roots = compute_roots(s, "urn:g")
    assert [r[1] for r in roots] == ["Alpha", "delta"]


def test_enumeration_pass_never_asks_for_labels():
    """The 44.6 s came from joining labels onto 771k rows. It must not recur."""
    s = _store()
    compute_roots(s, "urn:g")
    enumeration = [q for q in s.queries if "VALUES" not in q]
    assert enumeration, "expected enumeration queries"
    for q in enumeration:
        assert "rdfs:label" not in q, f"enumeration query still joins labels:\n{q}"
        assert "ORDER BY" not in q, f"enumeration query still sorts:\n{q}"


def test_parent_pass_does_not_re_check_types():
    """The type guards cost 8 s on DRON and changed the result by 0 IRIs."""
    s = _store()
    compute_roots(s, "urn:g")
    parent_q = next(q for q in s.queries if "subClassOf" in q and "VALUES" not in q)
    assert "a owl:Class" not in parent_q


def test_labels_are_fetched_only_for_roots():
    s = _store()
    compute_roots(s, "urn:g")
    label_q = " ".join(q for q in s.queries if "VALUES" in q)
    assert "<http://x/A>" in label_q and "<http://x/D>" in label_q
    assert "<http://x/B>" not in label_q, "fetched a label for a non-root"


def test_label_lookup_is_chunked_for_a_flat_ontology():
    """A flat ontology makes every class a root; the VALUES clause must not be
    one unbounded blob."""
    n = LABEL_CHUNK * 2 + 5
    iris = [f"http://x/C{i:07d}" for i in range(n)]
    s = FakeStore(classes=iris, edges={}, labels={})
    roots = compute_roots(s, "urn:g")
    assert len(roots) == n
    assert len([q for q in s.queries if "VALUES" in q]) == 3


def test_unlabelled_roots_still_returned():
    s = FakeStore(classes=["http://x/Z"], edges={}, labels={})
    assert compute_roots(s, "urn:g") == [("http://x/Z", None, None)]


def test_cache_key_is_per_version_and_variant():
    a = root_cache_key("v1", "class", 200, True, None)
    b = root_cache_key("v1", "class", 200, False, None)
    assert a != b and a.startswith("terms_root:v1:")


def test_invalidate_removes_every_variant_for_one_version_only():
    import fakeredis
    r = fakeredis.FakeStrictRedis()
    r.set(root_cache_key("v1", "class", 200, True, None), "x")
    r.set(root_cache_key("v1", "property", 50, False, "nl"), "x")
    keep = root_cache_key("v2", "class", 200, True, None)
    r.set(keep, "x")

    invalidate_root_cache(r, "v1")

    assert r.get(keep) is not None
    assert r.get(root_cache_key("v1", "class", 200, True, None)) is None
    assert r.get(root_cache_key("v1", "property", 50, False, "nl")) is None


# ── warming ───────────────────────────────────────────────────────────────────
# Even at ~13 s, the first visitor after an ingest should not pay it. The
# indexing task computes the roots while it already holds the store open and
# writes them under the key the endpoint reads.

def test_warm_writes_the_payload_shape_the_endpoint_returns():
    import fakeredis, json
    from ontoexplorer.modules.hierarchy.roots import ROOT_CACHE_TTL, warm_root_cache

    r = fakeredis.FakeStrictRedis()
    n = warm_root_cache(_store(), r, "v1", "urn:g", limit=200)

    assert n == 2
    key = root_cache_key("v1", "class", 200, True, None)
    payload = json.loads(r.get(key))
    # Same keys as list_terms' response, so a cache hit is indistinguishable.
    assert set(payload) == {"terms", "offset", "limit", "parent"}
    assert payload["parent"] == "root"        # what the tree actually requests
    assert payload["offset"] == 0 and payload["limit"] == 200
    assert [t["label"] for t in payload["terms"]] == ["Alpha", "delta"]
    assert set(payload["terms"][0]) == {"iri", "label", "lang"}
    assert 0 < r.ttl(key) <= ROOT_CACHE_TTL


def test_warm_replaces_a_stale_entry():
    import fakeredis, json
    from ontoexplorer.modules.hierarchy.roots import warm_root_cache

    r = fakeredis.FakeStrictRedis()
    stale = root_cache_key("v1", "class", 200, True, None)
    r.set(stale, json.dumps({"terms": [{"iri": "http://x/GONE", "label": "gone", "lang": None}],
                             "offset": 0, "limit": 200, "parent": "root"}))
    r.set(root_cache_key("v1", "class", 50, True, None), "other-variant")

    warm_root_cache(_store(), r, "v1", "urn:g", limit=200)

    assert "GONE" not in r.get(stale).decode()
    assert r.get(root_cache_key("v1", "class", 50, True, None)) is None, \
        "other variants must be dropped, not left stale for the long TTL"
