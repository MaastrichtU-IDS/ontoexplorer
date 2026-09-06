"""Safe interpolation of IRIs into SPARQL queries.

Every SPARQL string in this codebase is built by formatting, and an IRI carried
in from a request or from an uploaded ontology is interpolated between angle
brackets. A `>` in that value closes the IRIREF and whatever follows is parsed
as query syntax — the shape of the injection fixed in 0.3.85, which reached a
SPARQL Update. The read paths have the same shape and are anonymous.

There is deliberately no escaping function here. SPARQL's IRIREF production is

    IRIREF ::= '<' ([^<>"{}|^`\\] - [#x00-#x20])* '>'

so the excluded characters cannot appear in a legal IRI at all, escaped or
otherwise. A value containing one is not an IRI that could match anything in the
store, so rejecting it loses no legitimate query and leaves no encoding subtlety
to get wrong later.
"""

# Characters the IRIREF production excludes: the five delimiters, backslash,
# backtick, caret, and everything at or below space (which covers NUL, newline,
# carriage return and tab).
_FORBIDDEN = frozenset('<>"{}|^`\\') | frozenset(chr(c) for c in range(0x21))


class UnsafeIri(ValueError):
    """Raised when a value cannot be placed inside a SPARQL IRIREF."""


def is_safe_iri(iri: str) -> bool:
    """True when `iri` can be interpolated between angle brackets unchanged."""
    return bool(iri) and not any(ch in _FORBIDDEN for ch in iri)


def iri_term(iri: str) -> str:
    """Render `iri` as a SPARQL ``<...>`` term, or raise `UnsafeIri`.

    Use this at every point an IRI is formatted into a query. Callers handling a
    request should translate the exception into a 400; callers reading IRIs back
    out of the store should skip the value, since one that cannot be written as
    an IRIREF could not have been stored as one either.
    """
    if not is_safe_iri(iri):
        raise UnsafeIri(f"value cannot be used as a SPARQL IRI: {iri[:120]!r}")
    return f"<{iri}>"
