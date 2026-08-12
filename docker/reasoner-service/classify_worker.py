"""Standalone, isolated classification worker.

Runs exactly one classification in its own OS process and writes the result
(or an error) to the shared Redis cache, then exits. The reasoner-service
launches this via subprocess so that a backend that segfaults, aborts, or
exhausts memory (e.g. rustdl on certain large ontologies) can only take down
this short-lived child — the parent detects the non-zero exit / timeout and
records a clean failure instead of crashing the whole service and looping.

Usage: python classify_worker.py <ntriples_path> <version_id> <reasoner> <saturation_only>
Exit codes: 0 = classified and stored; non-zero / killed by signal = failure
(the parent turns that into a stored classification error).
"""
from __future__ import annotations

import logging
import os
import sys


def _apply_memory_cap() -> None:
    """Optionally cap address space so an OOM fails this child cleanly instead of
    letting the container OOM-killer take out the service. Disabled when the env
    var is unset or 0."""
    mem_mb = int(os.getenv("REASONER_CLASSIFY_MEM_MB", "0"))
    if mem_mb <= 0:
        return
    try:
        import resource
        soft = mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
    except Exception:
        logging.getLogger("reasoner-service").warning(
            "classify_worker: failed to set memory cap", exc_info=True)


def main() -> int:
    if len(sys.argv) != 5:
        print(f"usage: {sys.argv[0]} <ntriples_path> <version_id> <reasoner> <saturation_only>",
              file=sys.stderr)
        return 2
    ntriples_path, version_id, reasoner, saturation_flag = sys.argv[1:5]
    saturation_only = saturation_flag == "True"

    _apply_memory_cap()

    with open(ntriples_path, encoding="utf-8") as fh:
        ntriples = fh.read()

    from cache import store_classification, store_input_axioms
    from registry import get_backend

    backend = get_backend(reasoner)
    result = backend.classify_ntriples(ntriples, version_id, saturation_only=saturation_only)
    # Mirror main.py's ordering: input axioms BEFORE the classification result, so
    # a follow-up /justification never races ahead of the input-axioms write.
    store_input_axioms(version_id, ntriples, reasoner)
    store_classification(result, reasoner)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
