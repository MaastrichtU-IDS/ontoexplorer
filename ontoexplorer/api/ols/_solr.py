"""Solr-style response envelope helper for OLS4-compat search endpoints.

OLS4's /api/search, /api/select, and /api/suggest return a Solr-shaped JSON
body rather than the HAL envelope used by the rest of the API. This module
provides a single factory function that builds that envelope.

Shape::

    {
        "responseHeader": {"status": 0, "QTime": <ms>, "params": {...}},
        "response":       {"numFound": <int>, "start": <int>, "docs": [...]},
        "facet_counts":   {"facet_fields": {...}},
        "highlighting":   {...},
    }
"""
from __future__ import annotations

from typing import Any


def solr_envelope(
    docs: list[dict],
    *,
    total: int,
    start: int,
    rows: int,
    q_params: dict[str, Any],
    qtime_ms: int,
    facets: dict | None = None,
    highlighting: dict | None = None,
) -> dict[str, Any]:
    """Build a Solr-style response envelope.

    Parameters
    ----------
    docs:
        The slice of documents to include in this response page.
    total:
        Total number of matching documents (``numFound``).
    start:
        Zero-based offset used for this page (``start``).
    rows:
        Page size requested (used only for bookkeeping; not embedded in
        the envelope itself beyond the slice size in ``docs``).
    q_params:
        Raw query parameters echoed in ``responseHeader.params``.
    qtime_ms:
        Query execution time in milliseconds.
    facets:
        Optional mapping of facet field name → list of value/count pairs.
        Defaults to an empty dict.
    highlighting:
        Optional highlighting snippets keyed by doc id.
        Defaults to an empty dict.
    """
    return {
        "responseHeader": {
            "status": 0,
            "QTime": qtime_ms,
            "params": q_params,
        },
        "response": {
            "numFound": total,
            "start": start,
            "docs": docs,
        },
        "facet_counts": {
            # OLS4 always emits these 6 facet field arrays even when empty;
            # callers may supply real counts via the `facets` kwarg.
            "facet_fields": {
                "ontologyPreferredPrefix": [],
                "isDefiningOntology":      [],
                "ontologyId":              [],
                "ontologyIri":             [],
                "isObsolete":              [],
                "type":                    [],
                **(facets or {}),
            },
        },
        "highlighting": highlighting or {},
    }
