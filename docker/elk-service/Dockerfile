# ELK OWL-EL reasoning service
# Accepts ontology triples (N-Triples) via HTTP and returns materialised
# subClassOf / equivalentClass inferences as N-Triples.
#
# Uses py_horned_owl for OWL 2 parsing and a pure-Python OWL-EL reasoner
# (structural subsumption over the OWL-EL fragment). No JVM required.
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi==0.111.*" \
    "uvicorn[standard]" \
    "rdflib" \
    "redis>=5.0"

COPY main.py classifier.py cache.py justification.py ./

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
