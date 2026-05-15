from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ontoexplorer.models.db import Ontology, User


def resolve_lang(
    query_param: str | None,
    ontology: "Ontology | None",
    user: "User | None",
) -> str | None:
    """Return the effective BCP-47 language tag, or None (= all languages).

    Priority: query_param > ontology.preferred_lang > user.preferred_lang > None.
    An empty string query_param is treated as absent.
    """
    if query_param:
        return query_param
    if ontology and ontology.preferred_lang:
        return ontology.preferred_lang
    if user and user.preferred_lang:
        return user.preferred_lang
    return None
