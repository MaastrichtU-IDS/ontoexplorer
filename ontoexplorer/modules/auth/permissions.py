"""Per-ontology edit authorization: admins, the owner, and approved maintainers
(ontology_maintainers) may edit an ontology's metadata + metadata profile."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import is_admin
from ontoexplorer.models.db import Ontology, OntologyMaintainer, User


async def owned_or_maintained_ontology_ids(db: AsyncSession, user_id: str) -> list[str]:
    """Ontology ids the user owns OR has an approved maintainer grant over.

    Used by the contributor dashboard + its usage stats to scope to "their"
    ontologies (per the product decision: owned + maintained, not owned-only).
    """
    owned = select(Ontology.id).where(Ontology.owner_id == user_id)
    maintained = select(OntologyMaintainer.ontology_id).where(OntologyMaintainer.user_id == user_id)
    rows = (await db.execute(owned.union(maintained))).scalars().all()
    return list(rows)


async def is_ontology_maintainer(db: AsyncSession, user_id: str, ontology_id: str) -> bool:
    row = (
        await db.execute(
            select(OntologyMaintainer).where(
                OntologyMaintainer.user_id == user_id,
                OntologyMaintainer.ontology_id == ontology_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def can_edit_ontology(db: AsyncSession, user: User | None, ontology: Ontology) -> bool:
    """True if `user` may edit `ontology`: an admin, the owner, an unowned
    ontology (legacy-permissive), or an approved maintainer of it."""
    if user is None:
        return False
    if is_admin(user):
        return True
    if ontology.owner_id is None or ontology.owner_id == user.id:
        return True
    return await is_ontology_maintainer(db, user.id, ontology.id)


async def can_edit_ontology_id(db: AsyncSession, user: User | None, ontology_id: str) -> bool:
    """Same as can_edit_ontology but loads the ontology by id (returns False if it
    doesn't exist — callers that need a 404 should look it up themselves first)."""
    onto = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one_or_none()
    if onto is None:
        return False
    return await can_edit_ontology(db, user, onto)
