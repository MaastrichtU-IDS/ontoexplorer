from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ontoexplorer.models.db import Ontology, User


def canonical_lang(tag: str) -> str:
    """Collapse a BCP-47 language tag to its primary subtag, lowercased.

    Examples: ``en-US`` → ``en``, ``en-GB`` → ``en``, ``pt-BR`` → ``pt``.
    Whitespace is stripped. The empty string (untagged literals) is preserved
    so callers can still distinguish tagged from untagged content.
    """
    tag = (tag or "").strip().lower()
    if not tag:
        return ""
    return tag.split("-", 1)[0]


def resolve_lang(
    query_param: str | None,
    ontology: "Ontology | None",
    user: "User | None",
) -> str | None:
    """Return the effective BCP-47 language tag, or None (= all languages).

    Priority: query_param > user.preferred_lang > None. An empty string
    query_param is treated as absent.

    `ontology` is accepted but ignored. There used to be a per-ontology default
    ranked *above* the user's own preference, so a reader who had chosen French
    was shown English anyway if an owner had set that ontology to English — a
    dataset default overriding a stated personal preference. The display
    language is a property of the reader, not of the ontology, so the concept
    is gone; the parameter remains only so the call sites keep their shape.
    """
    if query_param:
        return query_param
    if user and user.preferred_lang:
        return user.preferred_lang
    return None


def pick_label(entries, lang: str | None) -> tuple[str | None, str | None]:
    """Choose a label from [{value, lang}] and report the language it is in.

    Order: requested language > English > untagged > anything else, matching
    _label_score in the terms endpoint and resolve_label on the SQL paths, so
    the same entity does not change label depending on which one answered.

    Two things this replaced, both wrong. The fallback was `entries[0]`, i.e.
    whichever label property the profile happened to query first — on a class
    whose profile also treats skos:altLabel as a label, that made a German
    *synonym* the answer for a Portuguese request. And the caller reported the
    requested language rather than the chosen one, so that German synonym came
    back tagged "pt".

    Returns (None, None) for an empty list; the caller supplies its own
    fallback, usually the IRI fragment.
    """
    if not entries:
        return None, None

    def tag_of(entry) -> str:
        return canonical_lang(entry.get("lang") or "")

    if lang:
        want = canonical_lang(lang)
        for e in entries:
            if tag_of(e) == want:
                return e["value"], want
        for e in entries:
            if tag_of(e) == "en":
                return e["value"], "en"
        for e in entries:
            if tag_of(e) == "":
                return e["value"], None

    first = entries[0]
    return first["value"], (tag_of(first) or None)
