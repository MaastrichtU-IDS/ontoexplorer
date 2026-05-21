# ROBOT reasoning service
# Wraps ROBOT (OBO's OWL toolkit) behind a small FastAPI HTTP API so the worker
# can offload DL consistency checks (HermiT-backed) and, in a follow-up, axiom
# explanations. Kept separate from the worker container to isolate the JVM
# footprint (~250 MB JRE + 80 MB JAR) from the Python ingestion/index path.
FROM eclipse-temurin:21-jre-jammy

WORKDIR /app

# Python for the HTTP wrapper. jammy ships 3.10 by default; that's plenty for
# the thin layer we put around ROBOT (FastAPI + subprocess).
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir \
      "fastapi==0.111.*" \
      "uvicorn[standard]" \
      "python-multipart"

# ─────────────────────────────────────────────────────────────────────────────
# ROBOT — pinned by sha256 for reproducibility.
# v1.9.10 (2026-02): includes HermiT 1.4.5 + ELK 0.5 + JFact + structural reasoner
# ─────────────────────────────────────────────────────────────────────────────
ARG ROBOT_URL=https://github.com/ontodev/robot/releases/download/v1.9.10/robot.jar
ARG ROBOT_SHA256=16a73c074f3df359a7338a84b4e0788785fe06117f931bb9796e9619ea776105
RUN curl -fsSL "${ROBOT_URL}" -o /opt/robot.jar \
 && echo "${ROBOT_SHA256}  /opt/robot.jar" | sha256sum -c -

COPY main.py /app/main.py

# Default to 4 GiB heap for HermiT; override via JAVA_OPTS at runtime if needed.
ENV JAVA_OPTS="-Xmx4g"

EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
