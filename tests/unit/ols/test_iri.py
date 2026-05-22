from ontoexplorer.api.ols._iri import double_decode_iri, encode_iri_for_ols_path


def test_double_decoded_iri_with_obo_term():
    assert double_decode_iri("http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FGO_0008150") \
        == "http://purl.obolibrary.org/obo/GO_0008150"


def test_double_decoded_iri_with_fragment():
    assert double_decode_iri("http%253A%252F%252Fexample.org%252Fonto%2523Person") \
        == "http://example.org/onto#Person"


def test_double_decoded_iri_single_encoded_passes_through():
    # If client sent single-encoded, after FastAPI's one decode the % is gone; we decode again — idempotent.
    assert double_decode_iri("http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2FGO_0008150") \
        == "http://purl.obolibrary.org/obo/GO_0008150"


def test_encode_iri_for_ols_path_double_encodes():
    iri = "http://purl.obolibrary.org/obo/GO_0008150"
    assert encode_iri_for_ols_path(iri) \
        == "http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FGO_0008150"


def test_encode_iri_for_ols_path_roundtrips():
    iri = "http://purl.obolibrary.org/obo/HP_0000001"
    assert double_decode_iri(encode_iri_for_ols_path(iri)) == iri
