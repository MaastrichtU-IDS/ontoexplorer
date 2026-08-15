# Reasoner service — hosts a capability-aware registry of OWL reasoners
# behind one HTTP contract. Reasoner is selected per request (default DEFAULT_REASONER):
#   - "whelk"    (EL): py-whelk = whelk-rs, in-process via py-horned-owl. Default.
#   - "rdflib"   (EL, legacy): pure-Python structural classifier in classifier.py.
#   - "rustdl"   (DL SROIQ): PyO3 binding, installed from the PyPI manylinux wheel
#                (rustdl==0.3.41, tag v0.3.41). Classify + native sound justify
#                + render_manchester (used by the whelk backend's justify path too).
#   - "konclude" (OWL 2, all profiles): prebuilt binary from konclude/konclude:latest,
#                invoked as a subprocess. Classify + consistency (no justify).
#   - "km"       (SROIQ / OWL 2 DL): kobayashi-marust, a sound consequence-based
#                reasoner compiled from source (see km-build stage). Subprocess
#                (`km classify`). Classify + consistency (no justify). Experimental.
# Image is pinned to linux/amd64 (via compose) so the x86_64 py_whelk wheel and the
# x86_64 Konclude binary run natively (emulated on Apple Silicon).

# --- km-build: compile kobayashi-marust's `km` binary (Rust) ---
FROM rust:1-slim-bookworm AS km-build
ARG KM_REV=v0.2.21
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
    "rustdl==0.4.17"

# Konclude: bundle the prebuilt binary from the official image (linux/amd64).
# It links only libstdc++.so.6 at runtime (TBB is statically linked).
COPY --from=konclude/konclude:latest /root/Konclude /usr/local/bin/Konclude
RUN chmod +x /usr/local/bin/Konclude \
 && apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

# km (native binary; links only libc/libgcc, already present).
COPY --from=km-build /km /usr/local/bin/km
RUN chmod +x /usr/local/bin/km

COPY main.py classify_worker.py classifier.py cache.py \
     registry.py rustdl_backend.py konclude_backend.py km_backend.py incremental_km.py ./

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
