"""Detect and work around encoding-corrupted labels.

Some ontology sources serve (or users upload) files whose non-ASCII text was
destroyed upstream: each non-ASCII character replaced with a literal ``?``
(``Vía`` -> ``V??a``, ``ferrée`` -> ``ferr??e``, CJK/Cyrillic -> runs of ``?``).
This happens at the source — our ingestion stores bytes faithfully — and it is
lossy: the original characters are unrecoverable. We cannot repair the data, but
we can avoid *showing* the garbage (``is_corrupt_label`` / ``clean_display_label``)
and *report* how much of it a version carries (``count_corrupt``).
"""
from __future__ import annotations

import re
from collections.abc import Iterable

_RUN = re.compile(r"\?\?+")  # two or more consecutive '?'
_CORRUPT_DENSITY = 0.2


def is_corrupt_label(text: str | None) -> bool:
    """True when ``text`` looks like encoding-corrupted content (non-ASCII replaced
    with ``?``), as opposed to a legitimate label that merely contains a question
    mark.

    Heuristic — a label is corrupt when it has at least two ``?`` and either:
      * a run of 2+ consecutive ``?`` (how one accented or CJK char degrades), or
      * ``?`` makes up >= 20% of its non-space characters.
    A single ``?`` (an ordinary trailing question mark) is never flagged.
    """
    if not text:
        return False
    t = text.strip()
    q = t.count("?")
    if q < 2:
        return False
    if _RUN.search(t):
        return True
    non_space = sum(1 for c in t if not c.isspace()) or 1
    return q / non_space >= _CORRUPT_DENSITY


def count_corrupt(labels: Iterable[str | None]) -> int:
    """How many of ``labels`` are encoding-corrupted."""
    return sum(1 for label in labels if is_corrupt_label(label))


def local_name(iri: str) -> str:
    """The local name of an IRI: the part after the last ``#`` or ``/``."""
    s = iri.rstrip("/#")
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s or iri


def clean_display_label(
    primary: str | None, iri: str, *, alternatives: Iterable[str | None] = ()
) -> str:
    """A display label guaranteed not to be corrupt: the ``primary`` if it is
    clean, else the first clean ``alternatives`` entry, else a humanized form of
    the IRI's local name. Never returns a ``?``-corrupted string."""
    if primary and not is_corrupt_label(primary):
        return primary
    for alt in alternatives:
        if alt and not is_corrupt_label(alt):
            return alt
    # Lazy import: keep this module free of the indexer's heavier deps so it can
    # be imported from the ingestion path as well as the API.
    from ontoexplorer.modules.search.indexer import humanize_local_name

    name = local_name(iri)
    return humanize_local_name(name) or name or iri
