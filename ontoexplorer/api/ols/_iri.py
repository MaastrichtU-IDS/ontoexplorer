"""IRI URL-encoding helpers for the OLS4-compat layer.

OLS4 requires IRIs in URL path segments to be *double* URL-encoded
(e.g. ``%2F`` → ``%252F``). Spring (the framework underlying real OLS)
URL-decodes once at the request layer, so the handler sees a still-encoded
IRI which it then decodes itself. FastAPI also decodes once — we manually
decode again here.
"""
import urllib.parse

from fastapi import HTTPException

from ontoexplorer.clients.sparql_iri import is_safe_iri


def double_decode_iri(encoded: str) -> str:
    """Decode an OLS path IRI and reject anything unusable as a SPARQL IRI.

    Validated here rather than at each query, because the decoded value reaches
    a dozen SPARQL templates across terms.py, classes_v2.py, properties.py and
    individuals.py, every one of which formats it between angle brackets and all
    of which are anonymous. Double decoding also means the caller controls the
    result exactly, including characters URL encoding would otherwise carry
    safely.

    A rejected value could not name anything in the store either, so a 400 is
    the honest answer rather than an empty result.
    """
    decoded = urllib.parse.unquote(urllib.parse.unquote(encoded))
    if not is_safe_iri(decoded):
        raise HTTPException(status_code=400, detail="Malformed IRI in path")
    return decoded


def encode_iri_for_ols_path(iri: str) -> str:
    return urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
