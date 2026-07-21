FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

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

CMD ["uvicorn", "ontoexplorer.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
