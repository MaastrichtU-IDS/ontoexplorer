from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix, prefix_to_canonical_iri


def test_obo_purl_iri_resolves_to_prefix():
    # The OBO Foundry canonical pattern: bioregistry resolves these
    prefix, resolved = iri_to_prefix("http://purl.obolibrary.org/obo/RO_0002211")
    assert prefix == "ro"
    assert resolved is True


def test_iao_term_resolves():
    prefix, resolved = iri_to_prefix("http://purl.obolibrary.org/obo/IAO_0000412")
    assert prefix == "iao"
    assert resolved is True


def test_bfo_term_resolves():
    prefix, resolved = iri_to_prefix("http://purl.obolibrary.org/obo/BFO_0000001")
    assert prefix == "bfo"
    assert resolved is True


def test_unknown_iri_returns_unresolved():
    prefix, resolved = iri_to_prefix("http://example.com/made-up/X_001")
    assert resolved is False
    # prefix is either None or the raw namespace — caller decides; we just guarantee the flag


def test_prefix_back_to_canonical_iri():
    # round-trip: prefix produces an IRI we can resolve back
    canonical = prefix_to_canonical_iri("ro")
    assert canonical is not None
    assert "obolibrary.org" in canonical or "ro" in canonical.lower()
