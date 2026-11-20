"""Native vs reused/imported source classification (indexer._get_source core).

These exercise the two pure helpers that decide whether a term is *native*
(minted in the ontology's own namespace → source="") or foreign (reused /
imported → a prefix token). The host-identity detection has to survive three
real-world shapes that used to mislabel every own term as foreign and zero out
the FAIR R5/R6 native coverage:

  (a) trailing slash — a host IRI ending in "/" or "#" built a namespace like
      ".../pizza//" that matched nothing;
  (b) IRI / term-namespace divergence — an OBO ontology IRI resolves to the
      generic "obo" (or its raw namespace) while its terms resolve to the
      specific prefix (mondo, ogg, sio), so prefix==host_prefix never fired;
  (c) host IRI undetected in the store — fall back to the registered IRI.
"""
from ontoexplorer.modules.search.indexer import classify_source, host_identity


class TestHostIdentity:
    def test_trailing_slash_namespace_is_repaired(self):
        tokens, namespaces = host_identity(["https://w3id.org/ontostart/pizza/"])
        # The own-term namespace must be present without a doubled slash.
        assert "https://w3id.org/ontostart/pizza/" in namespaces
        assert "https://w3id.org/ontostart/pizza#" in namespaces
        assert "https://w3id.org/ontostart/pizza//" not in namespaces
        assert "pizza" in tokens

    def test_obo_divergent_iri_yields_real_prefix_not_obo(self):
        # IRI resolves to generic "obo"; the OBO-path segment recovers "mondo".
        tokens, _ = host_identity(["http://purl.obolibrary.org/obo/mondo/mondo-simple.owl"])
        assert "mondo" in tokens
        assert "obo" not in tokens  # generic umbrella is denylisted

    def test_obo_hyphenated_product_segment(self):
        # ".../obo/ogg-mm.owl" — terms are minted under the parent "ogg".
        tokens, _ = host_identity(["http://purl.obolibrary.org/obo/ogg-mm.owl"])
        assert "ogg" in tokens

    def test_registered_iri_used_when_store_host_missing(self):
        # Store detection failed (""), registered IRI carries the identity.
        tokens, namespaces = host_identity(["", "http://brk.basisregistraties.overheid.nl/def/brk"])
        assert "brk" in tokens
        assert "http://brk.basisregistraties.overheid.nl/def/brk#" in namespaces

    def test_empty_inputs_give_empty_identity(self):
        tokens, namespaces = host_identity(["", None])
        assert tokens == set()
        assert namespaces == []


class TestClassifySource:
    def test_native_by_repaired_namespace(self):
        _tokens, namespaces = host_identity(["https://w3id.org/ontostart/pizza/"])
        src = classify_source(
            "https://w3id.org/ontostart/pizza/Margherita",
            import_source_map={}, host_tokens=set(), host_namespaces=namespaces)
        assert src == ""

    def test_native_by_token_on_obo_divergence(self):
        tokens, namespaces = host_identity(
            ["http://purl.obolibrary.org/obo/mondo/mondo-simple.owl"])
        src = classify_source(
            "http://purl.obolibrary.org/obo/MONDO_0000001",
            import_source_map={}, host_tokens=tokens, host_namespaces=namespaces)
        assert src == ""

    def test_imported_obo_term_stays_foreign(self):
        # IAO is imported by MONDO; it must NOT be swept up as native.
        tokens, namespaces = host_identity(
            ["http://purl.obolibrary.org/obo/mondo/mondo-simple.owl"])
        src = classify_source(
            "http://purl.obolibrary.org/obo/IAO_0000115",
            import_source_map={}, host_tokens=tokens, host_namespaces=namespaces)
        assert src == "iao"

    def test_owl_imports_takes_precedence(self):
        src = classify_source(
            "https://w3id.org/sulo/SomeClass",
            import_source_map={"https://w3id.org/sulo": "sulo"},
            host_tokens={"other"}, host_namespaces=[])
        assert src == "sulo"

    def test_reused_vocab_is_tagged_with_its_prefix(self):
        tokens, namespaces = host_identity(["http://semanticscience.org/ontology/sio.owl"])
        src = classify_source(
            "http://purl.org/dc/terms/title",
            import_source_map={}, host_tokens=tokens, host_namespaces=namespaces)
        assert src == "dcterms"

    def test_sio_own_terms_native_via_token(self):
        tokens, namespaces = host_identity(["http://semanticscience.org/ontology/sio.owl"])
        src = classify_source(
            "http://semanticscience.org/resource/SIO_000001",
            import_source_map={}, host_tokens=tokens, host_namespaces=namespaces)
        assert src == ""

    def test_unresolved_namespace_returns_short_token(self):
        src = classify_source(
            "http://example.org/weird/Thing",
            import_source_map={}, host_tokens=set(), host_namespaces=[])
        assert src == "weird"
