#!/usr/bin/env bash
# Re-fetch EBI OLS4 response samples into tests/fixtures/ols4_ebi_samples/
# so the compliance contract test (tests/integration/ols/test_ebi_compliance.py)
# tracks the latest EBI shape.
#
# After running this, re-run the test:
#   uv run pytest tests/integration/ols/test_ebi_compliance.py -v
# and adjust KNOWN_GAPS in that file if the gap counts change.

set -euo pipefail

cd "$(dirname "$0")/.."
DEST=tests/fixtures/ols4_ebi_samples
mkdir -p "$DEST"

fetch() {
  local name="$1"; shift
  local url="$1"; shift
  echo "Fetching $name from $url"
  curl -sf --max-time 30 "$url" -o "$DEST/${name}.json"
}

# Representative endpoints — adjust if you want to widen the audit surface.
fetch ontologies_list_v1  "https://www.ebi.ac.uk/ols4/api/ontologies?size=2"
fetch ontology_detail_v1  "https://www.ebi.ac.uk/ols4/api/ontologies/efo"
fetch terms_list_v1       "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms?size=2"
fetch term_roots_v1       "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms/roots?size=2"
fetch search_solr         "https://www.ebi.ac.uk/ols4/api/search?q=disease&rows=2"
fetch ontologies_list_v2  "https://www.ebi.ac.uk/ols4/api/v2/ontologies?size=2"
fetch ontology_detail_v2  "https://www.ebi.ac.uk/ols4/api/v2/ontologies/efo"

echo "Done. Snapshots saved to $DEST/"
