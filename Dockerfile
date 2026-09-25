# --- horned-build: compile horned-convert (Rust) — used at ingestion to convert
# Manchester (.omn) and OBO (.obo) uploads to N-Triples, which no RDF parser in
# the Python stack can read. horned-owl's OBO (#217), Manchester (#176) I/O, and
# the OBO ontology-IRI fix (#288, so `ontology: <id>` expands to a PURL instead of
# a relative IRI) are on `devel` (v3.0.0), not yet a crates.io release, so pin the
# commit and build the CLI. ---
FROM rust:1-slim-bookworm AS horned-build
ARG HORNED_REV=48d95234b5218e78defd70bb29620f2c6f9b28af
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/phillord/horned-owl.git /src \
 && cd /src && git checkout "${HORNED_REV}"
WORKDIR /src
RUN cargo build --release --bin horned-convert \
 && cp target/release/horned-convert /horned-convert

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# horned-convert: Manchester/OBO → RDF at ingestion (see horned-build stage).
COPY --from=horned-build /horned-convert /usr/local/bin/horned-convert

# Install uv
# Pinned by digest. uv installs every Python dependency in this image and
# runs as root, so a compromised or simply changed `latest` rewrites the
# whole dependency set with nothing in the diff to show it. Bump
# deliberately; resolve a new digest with
#   docker buildx imagetools inspect ghcr.io/astral-sh/uv:latest
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 /uv /usr/local/bin/uv

# Copy project metadata first for layer caching. __init__.py carries the
# version (pyproject reads it dynamically via hatchling), and uv builds the
# project's editable metadata even with --no-install-project, so it must be
# present here or hatchling errors "version source file does not exist".
COPY pyproject.toml .
COPY README.md .
COPY ontoexplorer/__init__.py ./ontoexplorer/__init__.py

# Install dependencies (without the project itself for layer caching)
RUN uv sync --no-install-project --no-dev

# Copy source code
COPY ontoexplorer/ ./ontoexplorer/
COPY alembic/ ./alembic/
COPY alembic.ini .
# One-shot maintenance scripts are run with `kubectl exec ... python scripts/<x>.py`,
# so they have to ship in the image.
COPY scripts/ ./scripts/

# Install the project
RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Bake the semantic-search embedding model into the image so it never downloads
# at runtime. Previously the ~500MB model lived in a per-pod emptyDir and was
# re-fetched on the first semantic query after every restart (the ~20s spikes).
# Shipping it in the image means every worker/replica loads it locally.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN mkdir -p /opt/fastembed \
    && python -c "from ontoexplorer.modules.search.embedder import get_embedder; get_embedder()"

# Build provenance — passed by CI (docker build --build-arg …) and surfaced by
# GET /api/v1/version. Empty for a plain local build.
ARG GIT_REF=""
ARG GIT_SHA=""
ENV GIT_REF=$GIT_REF
ENV GIT_SHA=$GIT_SHA

CMD ["uvicorn", "ontoexplorer.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
