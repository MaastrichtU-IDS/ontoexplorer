# --- horned-build: compile horned-convert (Rust) — used at ingestion to convert
# Manchester (.omn) and OBO (.obo) uploads to N-Triples, which no RDF parser in
# the Python stack can read. horned-owl's OBO (#217) and Manchester (#176) I/O is
# merged to `devel` (v3.0.0), not yet a crates.io release, so pin the commit and
# build the CLI. ---
FROM rust:1-slim-bookworm AS horned-build
ARG HORNED_REV=85fa1efbfefc4f9ee6e070c06bc70a925c10a152
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
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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

# Install the project
RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Build provenance — passed by CI (docker build --build-arg …) and surfaced by
# GET /api/v1/version. Empty for a plain local build.
ARG GIT_REF=""
ARG GIT_SHA=""
ENV GIT_REF=$GIT_REF
ENV GIT_SHA=$GIT_SHA

CMD ["uvicorn", "ontoexplorer.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
