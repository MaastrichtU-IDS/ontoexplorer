"""OntoExplorer — FAIR ontology repository."""

# Single source of truth for the app version. pyproject.toml reads this via
# hatchling's dynamic version ([tool.hatch.version]); main.py imports it for the
# FastAPI `version` and the startup log. Bump here on release.
__version__ = "0.3.74"
