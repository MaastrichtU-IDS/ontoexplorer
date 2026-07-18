# Reasoner service — hosts a capability-aware registry of OWL reasoners
# behind one HTTP contract. Reasoner is selected per request (default DEFAULT_REASONER):
#   - "whelk"    (EL): py-whelk = whelk-rs, in-process via py-horned-owl. Default.
#   - "rdflib"   (EL, legacy): pure-Python structural classifier in classifier.py.
#   - "rustdl"   (DL SROIQ): PyO3 binding, installed from the PyPI manylinux wheel
#                (rustdl==0.3.23, tag v0.3.23). Classify + native sound justify
#                + render_manchester (used by the whelk backend's justify path too).
#   - "konclude" (OWL 2, all profiles): prebuilt binary from konclude/konclude:latest,
#                invoked as a subprocess. Classify + consistency (no justify).
# Image is pinned to linux/amd64 (via compose) so the x86_64 py_whelk wheel and the
# x86_64 Konclude binary run natively (emulated on Apple Silicon).
FROM python:3.12-slim

WORKDIR /app

# Patched py-whelk wheel (vendored locally). Adds remove-handling to the
# index_remove stub so reasoner.flush() actually invalidates the cached
# classification after onto.remove_axiom() — required by the persistent-
# reasoner path in justification.py. Switch back to PyPI once the upstream
# PR lands; see test_pywhelk_flush_after_remove.py for the regression.
COPY wheels/ /tmp/wheels/
RUN pip install --no-cache-dir \
    "fastapi==0.111.*" \
    "uvicorn[standard]" \
    "rdflib" \
    "redis>=5.0" \
    "requests>=2.31" \
    "py-horned-owl==1.4.*" \
    /tmp/wheels/py_whelk-*.whl \
    "pyoxigraph>=0.4" \
    "rustdl==0.3.23" \
 && rm -rf /tmp/wheels

# Konclude: bundle the prebuilt binary from the official image (linux/amd64).
# It links only libstdc++.so.6 at runtime (TBB is statically linked).
COPY --from=konclude/konclude:latest /root/Konclude /usr/local/bin/Konclude
RUN chmod +x /usr/local/bin/Konclude \
 && apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

COPY main.py classifier.py whelk_classifier.py cache.py justification.py \
     registry.py rustdl_backend.py konclude_backend.py ./

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
