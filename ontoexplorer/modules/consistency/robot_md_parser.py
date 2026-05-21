"""Parse ROBOT --explanation Markdown output into per-class justification token lists.

ROBOT writes each entity reference as a Markdown link `[label](IRI)` and joins them
with Manchester keywords as plain text. We tokenize: links become IriTokens, inter-link
text becomes TextTokens. No Manchester-grammar parsing — ROBOT has already done the
verbalization work.

Output shape: { class_iri: [ [token, ...], [token, ...], ... ] }
  outer dict key — IRI of the unsatisfiable class being explained
  inner list — one entry per justification axiom bullet
  innermost list — one ManchesterToken (TextToken | IriToken) per text/link segment
"""
from __future__ import annotations

import re

from pyowl2_profiles.manchester import IriToken, ManchesterToken, TextToken


# Matches [label](IRI) where the IRI is an http(s) URL. The label can be empty
# or contain anything except `]`.
_LINK = re.compile(r"\[([^\]]*)\]\((https?[^)]+)\)")

# Lines that terminate the explanation block — ROBOT writes these as summary sections
# AFTER the per-class justifications.
_TERMINATORS = ("# Axiom Impact", "# Ontologies used")


def parse_robot_explanation_md(md_text: str) -> dict[str, list[list[ManchesterToken]]]:
    """Parse ROBOT explain markdown into per-class lists of tokenized justification axioms.

    Args:
        md_text: full contents of ROBOT's `--explanation <file>.md` output.

    Returns:
        dict mapping unsatisfiable class IRI to its justification (list of axioms).
        Each axiom is a list of ManchesterToken (TextToken | IriToken).
        Returns {} if no class sections are found or input is empty.
    """
    result: dict[str, list[list[ManchesterToken]]] = {}
    current_class_iri: str | None = None

    for raw_line in md_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if any(line.startswith(t) for t in _TERMINATORS):
            break

        # H2 header form: "## [X](iri) SubClassOf [Nothing](...) ##"
        if line.startswith("## ") and line.endswith(" ##"):
            stripped = line[3:-3].strip()
            tokens = _tokenize(stripped)
            class_iri = _first_iri(tokens)
            if class_iri is None:
                continue
            current_class_iri = class_iri
            # Initialize the class section with an empty bucket (header not included)
            result.setdefault(current_class_iri, [])
            continue

        # Bullet form: "  - ..." or "- ..."  (justification axiom for the current class)
        stripped_bullet = line.lstrip()
        if stripped_bullet.startswith("- ") and current_class_iri is not None:
            axiom_text = stripped_bullet[2:].strip()
            tokens = _tokenize(axiom_text)
            if tokens:
                result[current_class_iri].append(tokens)
            continue

        # Anything else (prose, blank lines after rstrip, ...) — ignore.

    return result


def _tokenize(text: str) -> list[ManchesterToken]:
    """Tokenize a single Manchester-Markdown line into IriToken/TextToken segments."""
    tokens: list[ManchesterToken] = []
    pos = 0
    for m in _LINK.finditer(text):
        if m.start() > pos:
            seg = text[pos:m.start()]
            if seg:
                tokens.append(_text_token(seg))
        label = m.group(1)
        iri = m.group(2)
        tokens.append(_iri_token(label=label or iri, iri=iri))
        pos = m.end()
    if pos < len(text):
        trailing = text[pos:]
        if trailing:
            tokens.append(_text_token(trailing))
    return tokens


def _text_token(value: str) -> TextToken:
    return {"t": "text", "v": value}


def _iri_token(*, label: str, iri: str) -> IriToken:
    return {"t": "iri", "iri": iri, "label": label, "in_ontology": True}


def _first_iri(tokens: list[ManchesterToken]) -> str | None:
    """Return the IRI of the first IriToken in `tokens`, or None if there is none."""
    for tok in tokens:
        if tok.get("t") == "iri":
            return tok.get("iri")  # type: ignore[return-value]
    return None
