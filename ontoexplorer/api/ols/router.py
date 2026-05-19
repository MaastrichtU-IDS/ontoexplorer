"""Aggregates all OLS4-compat sub-routers into one router at /ols."""
from fastapi import APIRouter

from ontoexplorer.api.ols import ontologies as _ontologies
from ontoexplorer.api.ols import terms as _terms
from ontoexplorer.api.ols import properties as _properties
from ontoexplorer.api.ols import individuals as _individuals
from ontoexplorer.api.ols import search as _search
from ontoexplorer.api.ols import llm as _llm
from ontoexplorer.api.ols import classes_v2 as _classes_v2
from ontoexplorer.api.ols import widgets as _widgets

router = APIRouter(prefix="/ols", tags=["ols-compat"])
router.include_router(_ontologies.router)
# widgets MUST be included before terms because terms.py registers a broad
# /api/ontologies/{onto}/terms/{iri_path:path} catch-all.  If widgets were
# included after that catch-all, the literal "jstree" and "graph" suffixes
# would be consumed by it and return 404.
router.include_router(_widgets.router)
router.include_router(_terms.router)
router.include_router(_properties.router)
router.include_router(_individuals.router)
router.include_router(_search.router)
# LLM routes MUST be registered before classes_v2 to prevent the generic
# /api/v2/classes/{iri_path:path} catch-all from consuming llm_search and
# llm_similar paths.
router.include_router(_llm.router)
router.include_router(_classes_v2.router)
