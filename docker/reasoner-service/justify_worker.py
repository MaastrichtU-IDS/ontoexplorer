"""Standalone, isolated justification worker.

Runs exactly one `justify` in its own OS process and prints the justification
sets as a single JSON line on stdout, then exits.

Justification was the only reasoner entry point still running in-process, which
left it the only one with neither of the two protections the others have:

  * No timeout. `JUSTIFICATION_TIME_LIMIT_SECONDS` was set in the compose file
    and the k8s configmap and read by nothing. An in-process timeout had been
    tried and removed for a real reason — rustdl's PyO3 handles are thread-
    affine, so an executor-based deadline returned empty results in ~1 ms on
    some ontologies — and the comment left behind claimed "Uvicorn's request
    lifetime is still bounded by the client's HTTP timeout", which is not true:
    a sync handler runs to completion in the threadpool whether or not the
    client is still there. A process boundary carries no handles, so the
    deadline works here where a thread could not.

  * No crash isolation. classify and consistency were both moved out of process
    precisely because rustdl can overflow the native stack or exhaust memory,
    and in-process that kills a uvicorn worker mid-request — which the client
    sees as "Server disconnected without sending a response". Justification runs
    the same engine and had none of that protection.

Sibling of consistency_worker.py: same hardening, same stdout contract.

Usage: python justify_worker.py <ntriples_path> <justifier> <query_json>
  query_json: {"sub": str, "sup": str, "max": int, "version_id": str | null}

Exit codes: 0 = computed, JSON on stdout; non-zero / killed by signal = failure
(the parent turns that into an HTTP error).
"""
from __future__ import annotations

import json
import logging
import sys
import threading

from classify_worker import _apply_memory_cap, _configure_native_stacks


def main() -> int:
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} <ntriples_path> <justifier> <query_json>",
              file=sys.stderr)
        return 2
    ntriples_path, justifier_name, query_json = sys.argv[1:4]
    try:
        query = json.loads(query_json) if query_json else {}
    except json.JSONDecodeError:
        print("query_json is not valid JSON", file=sys.stderr)
        return 2

    stack_bytes = _configure_native_stacks()
    _apply_memory_cap()

    with open(ntriples_path, encoding="utf-8") as fh:
        ntriples = fh.read()

    holder: dict = {}

    def _work() -> None:
        try:
            from registry import get_backend
            backend = get_backend(justifier_name)
            sets, fmt = backend.justify(
                ntriples,
                query["sub"],
                query["sup"],
                int(query.get("max", 1)),
                version_id=query.get("version_id"),
            )
            holder["sets"] = [list(s) for s in sets]
            holder["format"] = fmt
            holder["ok"] = True
        except BaseException as exc:  # noqa: BLE001 - propagate to the main thread
            holder["exc"] = exc

    try:
        threading.stack_size(stack_bytes)
    except (ValueError, RuntimeError):
        logging.getLogger("reasoner-service").warning(
            "justify_worker: could not set thread stack size to %d bytes; "
            "relying on RUST_MIN_STACK only", stack_bytes)
    t = threading.Thread(target=_work, name="justify")
    t.start()
    t.join()

    if holder.get("ok"):
        print(json.dumps({"sets": holder["sets"], "format": holder["format"]}))
        return 0
    exc = holder.get("exc")
    if exc is not None:
        raise exc
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
