# Reasoner service — hosts a capability-aware registry of OWL reasoners
# behind one HTTP contract. Reasoner is selected per request (default DEFAULT_REASONER):
#   - "rustdl"   (DL SROIQ): PyO3 binding, installed from the PyPI manylinux wheel
#                (see the pinned version below). Default. Classify + native sound
#                justify + render_manchester; also covers the EL role in
#                saturation_only mode. Every justification runs through it,
#                whichever reasoner classified the version.
#   - "konclude" (OWL 2, all profiles): prebuilt binary from konclude/konclude:latest,
#                invoked as a subprocess. Classify + consistency (no justify).
#   - "km"       (SROIQ / OWL 2 DL): kobayashi-marust, a sound consequence-based
#                reasoner compiled from source (see km-build stage). Subprocess
#                (`km classify`). Classify + consistency (no justify). Experimental.
# whelk and the legacy rdflib classifier were removed and are no longer
# registered — see the notes in registry.py for why. registry.py is the source
# of truth for what is actually selectable.
# Image is pinned to linux/amd64 (via compose) so the x86_64 Konclude binary runs
# natively (emulated on Apple Silicon).

# --- km-build: compile kobayashi-marust's `km` binary (Rust) ---
FROM rust:1-slim-bookworm AS km-build
ARG KM_REV=v1.3.0
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/bio-ontology-research-group/kobayashi-marust.git /src \
 && cd /src && git checkout "${KM_REV}"
WORKDIR /src/engine
RUN cargo build --release --bin km && cp target/release/km /km

FROM python:3.12-slim

WORKDIR /app

# whelk removed: py-whelk's reasoner.inferred_axioms() SIGSEGVs on this amd64 build
# (both vendored 0.1.0 and PyPI 0.4.0 — it never produced a classification here).
# py-horned-owl is kept: the km and konclude backends use open_ontology_from_string.
RUN pip install --no-cache-dir \
    "fastapi==0.111.*" \
    "uvicorn[standard]" \
    "rdflib" \
    "redis>=5.0" \
    "requests>=2.31" \
    "py-horned-owl==1.4.*" \
    "pyoxigraph>=0.4" \
    "rustdl==0.4.28"

# Konclude: bundle the prebuilt binary from the official image (linux/amd64).
# It links only libstdc++.so.6 at runtime (TBB is statically linked).
# Pinned by digest: this copies a reasoner binary straight into the released
# image from a third-party Docker Hub tag that can move under us.
COPY --from=konclude/konclude:latest@sha256:45a9b4583865d1f4209280209ec46de6444366ba47da1a50a0c795247126120c /root/Konclude /usr/local/bin/Konclude
RUN chmod +x /usr/local/bin/Konclude \
 && apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

# km (native binary; links only libc/libgcc, already present).
COPY --from=km-build /km /usr/local/bin/km
RUN chmod +x /usr/local/bin/km
# km has no runtime --version, so bake the build rev in for the /reasoners version
# field (km_backend reads $KM_VERSION). Redeclared here so the runtime stage sees it.
ARG KM_REV=v1.3.0
ENV KM_VERSION=${KM_REV}

COPY main.py classify_worker.py consistency_worker.py justify_worker.py classifier.py cache.py \
     registry.py rustdl_backend.py konclude_backend.py km_backend.py incremental_km.py ./

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
