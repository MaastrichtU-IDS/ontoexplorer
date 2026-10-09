from ontoexplorer.modules.resolve.conneg import RDF_ACCEPT, is_rdf_content_type


def test_rdf_content_types_recognized():
    for ct in ("text/turtle", "application/rdf+xml", "application/ld+json",
               "application/n-triples", "application/n-quads", "application/trig",
               "text/n3", "application/owl+xml"):
        assert is_rdf_content_type(ct) is True


def test_rdf_content_type_ignores_params():
    assert is_rdf_content_type("text/turtle; charset=utf-8") is True
    assert is_rdf_content_type("  Application/RDF+XML ;q=1 ") is True


def test_non_rdf_content_types_rejected():
    for ct in ("text/html", "application/json", "text/plain",
               "application/octet-stream", "", None):
        assert is_rdf_content_type(ct) is False


def test_accept_header_lists_rdf_then_wildcard_fallback():
    assert "text/turtle" in RDF_ACCEPT
    assert RDF_ACCEPT.strip().endswith("*/*;q=0.1")
