"""Aggregates all OLS4-compat sub-routers into one router at /ols."""
from fastapi import APIRouter

from ontoexplorer.api.ols import ontologies as _ontologies
from ontoexplorer.api.ols import terms as _terms

router = APIRouter(prefix="/ols", tags=["ols-compat"])
router.include_router(_ontologies.router)
router.include_router(_terms.router)
