"""Admin API router — assembled from focused sub-modules."""
from fastapi import APIRouter

from . import actions, diffs, health, versions, workers

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
router.include_router(health.router)
router.include_router(versions.router)
router.include_router(workers.router)
router.include_router(actions.router)
router.include_router(diffs.router)

__all__ = ["router"]
