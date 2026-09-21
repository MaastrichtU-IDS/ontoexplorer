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


# --- local supplement (vocabularies bioregistry lacks a namespace-variant for) ---

def test_supplement_erlangen_crm_variant_resolves():
    # bioregistry has cidoc.crm but not the Erlangen OWL-DL namespace variant.
    prefix, resolved = iri_to_prefix("http://erlangen-crm.org/current/E1_CRM_Entity")
    assert prefix == "ecrm"
    assert resolved is True


def test_supplement_oclc_ssnx_variant_resolves():
    prefix, resolved = iri_to_prefix("http://purl.oclc.org/NET/ssnx/ssn#System")
    assert prefix == "ssn"
    assert resolved is True


def test_supplement_arco_family_collapses_all_modules():
    # A single family entry covers every per-module namespace under it.
    for module in ("core", "location", "context-description", "catalogue"):
        prefix, resolved = iri_to_prefix(f"https://w3id.org/arco/ontology/{module}/SomeTerm")
        assert prefix == "arco"
        assert resolved is True


def test_bioregistry_takes_precedence_over_supplement():
    # dcterms is registered in bioregistry; the supplement must not shadow it.
    prefix, resolved = iri_to_prefix("http://purl.org/dc/terms/title")
    assert prefix == "dcterms"
    assert resolved is True


def test_genuinely_unknown_stays_unresolved():
    prefix, resolved = iri_to_prefix("http://ontology.example.org/oneoff/Thing")
    assert resolved is False
