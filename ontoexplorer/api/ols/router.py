"""Aggregates all OLS4-compat sub-routers into one router at /ols."""
from fastapi import APIRouter

from ontoexplorer.api.ols import ontologies as _ontologies

router = APIRouter(prefix="/ols", tags=["ols-compat"])
router.include_router(_ontologies.router)
