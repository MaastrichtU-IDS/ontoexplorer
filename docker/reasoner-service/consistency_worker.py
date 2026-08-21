"""Standalone, isolated ad-hoc consistency worker.

Runs exactly one `classify_ntriples` in its own OS process and prints the
unsatisfiable-class set as a single JSON line to stdout, then exits. The
reasoner-service launches this via subprocess so a backend that segfaults,
aborts, or exhausts memory (e.g. rustdl overflowing the native stack during
saturation/tableau on a mid-size ontology) can only take down this
short-lived child — the parent detects the non-zero exit / timeout and
returns a clean HTTP error instead of a uvicorn worker dying mid-request
(which the client sees as "Server disconnected without sending a response").

This is the synchronous sibling of classify_worker.py: same native-stack and
memory-cap hardening, but the result goes to stdout (not Redis) because
/consistency is a request/response endpoint with no version to key on.

Usage: python consistency_worker.py <ntriples_path> <reasoner> <params_json>
Exit codes: 0 = classified, JSON on stdout; non-zero / killed by signal =
failure (the parent turns that into an HTTP 500).
"""
from __future__ import annotations

import json
import logging
import sys
import threading

# Reuse the exact hardening classify_worker uses: big native stack (rustdl /
# pyhornedowl are PyO3 and overflow the default ~8 MB stack on deep recursion)
# and an optional address-space cap.
from classify_worker import _apply_memory_cap, _configure_native_stacks


def main() -> int:
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} <ntriples_path> <reasoner> <params_json>",
              file=sys.stderr)
        return 2
    ntriples_path, reasoner, params_json = sys.argv[1:4]
    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError:
        params = {}

    stack_bytes = _configure_native_stacks()
    _apply_memory_cap()

    with open(ntriples_path, encoding="utf-8") as fh:
        ntriples = fh.read()

    # Run the (Rust, recursion-heavy) classification on a thread with a large
    # stack so deep hierarchies don't SIGSEGV the calling thread. A native stack
    # overflow is prevented by the bigger stack rather than caught (segfaults
    # aren't catchable); the subprocess boundary catches everything else.
    holder: dict = {}

    def _work() -> None:
        try:
            from registry import get_backend
            backend = get_backend(reasoner)
            result = backend.classify_ntriples(ntriples, "_adhoc_consistency_", params)
            holder["unsatisfiable"] = list(result.unsatisfiable)
            holder["ok"] = True
        except BaseException as exc:  # noqa: BLE001 - propagate to the main thread
            holder["exc"] = exc

    try:
        threading.stack_size(stack_bytes)
    except (ValueError, RuntimeError):
        logging.getLogger("reasoner-service").warning(
            "consistency_worker: could not set thread stack size to %d bytes; "
            "relying on RUST_MIN_STACK only", stack_bytes)
    t = threading.Thread(target=_work, name="consistency")
    t.start()
    t.join()

    if holder.get("ok"):
        # Single JSON line on stdout is the result contract with the parent.
        print(json.dumps({"unsatisfiable": holder["unsatisfiable"]}))
        return 0
    exc = holder.get("exc")
    if exc is not None:
        raise exc
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
