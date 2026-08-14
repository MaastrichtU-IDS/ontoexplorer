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
import threading


def _configure_native_stacks() -> int:
    """Return the stack size (bytes) to give the classification thread, and bump
    RUST_MIN_STACK to match.

    pyhornedowl / pywhelk / rustdl are Rust (PyO3). Deep recursion in RDF/XML
    parsing and EL-saturation over large class hierarchies (e.g. GO, ~50k
    classes) overflows the default ~2-8 MB stack and the process dies with
    SIGSEGV — observed live: whelk crashed on GO at ~2.2 GiB (well under the
    48 GiB limit), i.e. a stack overflow, not an OOM. RUST_MIN_STACK sizes
    Rust-spawned threads (rayon/std::thread) and must be set before those libs
    load; the calling thread is handled by running classification on a
    threading.Thread created with this stack size (see main())."""
    stack_mb = int(os.getenv("REASONER_CLASSIFY_STACK_MB", "512"))
    stack_bytes = stack_mb * 1024 * 1024
    os.environ.setdefault("RUST_MIN_STACK", str(stack_bytes))
    return stack_bytes


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

    stack_bytes = _configure_native_stacks()
    _apply_memory_cap()

    with open(ntriples_path, encoding="utf-8") as fh:
        ntriples = fh.read()

    # Run the (Rust, recursion-heavy) classification on a thread with a large
    # stack so deep hierarchies don't SIGSEGV the calling thread. Result/exception
    # are handed back via `holder`; a native stack overflow is prevented by the
    # bigger stack rather than caught (segfaults aren't catchable).
    holder: dict = {}

    def _work() -> None:
        try:
            from cache import store_classification, store_input_axioms
            from registry import get_backend
            backend = get_backend(reasoner)
            result = backend.classify_ntriples(
                ntriples, version_id, saturation_only=saturation_only)
            # Mirror main.py's ordering: input axioms BEFORE the classification
            # result, so a follow-up /justification never races the input write.
            store_input_axioms(version_id, ntriples, reasoner)
            store_classification(result, reasoner)
            holder["ok"] = True
        except BaseException as exc:  # noqa: BLE001 - propagate to the main thread
            holder["exc"] = exc

    try:
        threading.stack_size(stack_bytes)
    except (ValueError, RuntimeError):
        logging.getLogger("reasoner-service").warning(
            "classify_worker: could not set thread stack size to %d bytes; "
            "relying on RUST_MIN_STACK only", stack_bytes)
    t = threading.Thread(target=_work, name="classify")
    t.start()
    t.join()

    if holder.get("ok"):
        return 0
    exc = holder.get("exc")
    if exc is not None:
        raise exc
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
