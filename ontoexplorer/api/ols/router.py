"""Aggregates all OLS4-compat sub-routers into one router at /ols."""
from fastapi import APIRouter

router = APIRouter(prefix="/ols", tags=["ols-compat"])
