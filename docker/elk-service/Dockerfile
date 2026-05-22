# ELK OWL-EL reasoning service
# Accepts ontology triples (N-Triples) via HTTP and returns materialised
# subClassOf / equivalentClass inferences as N-Triples.
#
# Two classification backends are available:
#   - "whelk" (default): py-whelk = whelk-rs (Rust port of Whelk EL reasoner)
#     invoked in-process via py-horned-owl. Strict superset of ROBOT/ELK's
#     inferences on tested ontologies; ~4x faster than the legacy backend on
#     ordo-scale inputs.
#   - "rdflib" (legacy): pure-Python structural EL classifier in classifier.py.
#     Kept because its proof-trace output drives the hitting-set justification
#     algorithm. Has a known coverage gap (misses ~17K inferences on ordo).
# Switch via env var CLASSIFIER_BACKEND.
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
 && rm -rf /tmp/wheels

COPY main.py classifier.py whelk_classifier.py cache.py justification.py ./

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
