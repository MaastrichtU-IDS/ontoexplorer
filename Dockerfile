FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project metadata first for layer caching
COPY pyproject.toml .
COPY README.md .

# Install dependencies (without the project itself for layer caching)
RUN uv sync --no-install-project --no-dev

# ─────────────────────────────────────────────────────────────────────────────
# Konclude OWL 2 DL reasoner (used by Phase 2 consistency analysis)
# Native C++ binary — no JVM required. Pinned by sha256 for reproducibility.
#
# ROBOT (JVM-based) is intentionally NOT bundled. The consistency detector
# gracefully falls back to empty justifications when ROBOT is missing, so the
# core consistency-verdict feature works with Konclude alone. Add ROBOT + JDK
# in a future image revision if per-class justifications are needed in
# production (significant image-size increase: ~200 MB for the JRE).
#
# Pinned release: v0.7.0-1138 (2021-06-19), Linux x64 GCC Static Qt5.12.10
# Fallback note: if the URL becomes unavailable, v0.7.0-1135 (2020-09-14) is
# the most-cited stable release in OWL-reasoner literature.
# ─────────────────────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Using the Docker-Compiled variant: statically linked against glibc-only deps
# (no libpcre3 needed; libpcre3 is absent from Debian trixie / python:3.12-slim)
ARG KONCLUDE_URL=https://github.com/konclude/Konclude/releases/download/v0.7.0-1138/Konclude-v0.7.0-1138-Linux-Docker-Compiled-x64-GCC4.8.4-Static-Qt5.12.10.zip
ARG KONCLUDE_SHA256=6a5ca3f54daa19bfd29f91bb4d58ed7af52e7fd6e02170f3df58f89c53f6e7f8
RUN curl -fsSL "${KONCLUDE_URL}" -o /tmp/konclude.zip \
 && echo "${KONCLUDE_SHA256}  /tmp/konclude.zip" | sha256sum -c - \
 && unzip -q /tmp/konclude.zip -d /tmp/konclude-extract \
 && find /tmp/konclude-extract -type f -path "*/Binaries/Konclude" -exec install -Dm755 {} /usr/local/bin/Konclude \; \
 && Konclude --help 2>&1 | head -3 \
 && rm -rf /tmp/konclude.zip /tmp/konclude-extract

# Copy source code
COPY ontoexplorer/ ./ontoexplorer/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Install the project
RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "ontoexplorer.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
