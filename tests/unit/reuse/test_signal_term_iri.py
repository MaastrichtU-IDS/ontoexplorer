from ontoexplorer.modules.reuse.signals.term_iri import (
    TermIRIReuseEntry,
    classify_terms,
)


def test_native_terms_excluded_from_reuse_counts():
    entities = [
        ("http://example.org/myonto#ClassA", "class"),
        ("http://example.org/myonto#ClassB", "class"),
    ]
    out = classify_terms(entities, host_prefix=None, host_namespaces=["http://example.org/myonto#"])
    # All entities are native — no reused-from buckets
    assert out == {}


def test_foreign_terms_bucketed_by_prefix():
    entities = [
        ("http://purl.obolibrary.org/obo/BFO_0000001", "class"),
        ("http://purl.obolibrary.org/obo/BFO_0000002", "class"),
        ("http://purl.obolibrary.org/obo/RO_0002211", "object_property"),
    ]
    out = classify_terms(entities, host_prefix="myonto",
                         host_namespaces=["http://example.org/myonto#"])
    assert "bfo" in out
    assert out["bfo"].class_count == 2
    assert out["bfo"].property_count == 0
    assert "ro" in out
    assert out["ro"].property_count == 1
    assert out["ro"].class_count == 0


def test_samples_capped_at_five():
    entities = [
        (f"http://purl.obolibrary.org/obo/BFO_{i:07d}", "class") for i in range(20)
    ]
    out = classify_terms(entities, host_prefix="myonto",
                         host_namespaces=["http://example.org/myonto#"])
    assert len(out["bfo"].sample_iris) == 5


def test_term_iri_reuse_entry_is_serializable():
    from dataclasses import asdict
    entry = TermIRIReuseEntry(class_count=1, property_count=0, sample_iris=["foo"])
    assert asdict(entry)["class_count"] == 1
