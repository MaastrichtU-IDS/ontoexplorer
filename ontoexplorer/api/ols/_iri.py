"""IRI URL-encoding helpers for the OLS4-compat layer.

OLS4 requires IRIs in URL path segments to be *double* URL-encoded
(e.g. ``%2F`` → ``%252F``). Spring (the framework underlying real OLS)
URL-decodes once at the request layer, so the handler sees a still-encoded
IRI which it then decodes itself. FastAPI also decodes once — we manually
decode again here.
"""
import urllib.parse


def double_decode_iri(encoded: str) -> str:
    return urllib.parse.unquote(urllib.parse.unquote(encoded))


def encode_iri_for_ols_path(iri: str) -> str:
    return urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
