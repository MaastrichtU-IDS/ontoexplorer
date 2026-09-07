"""No Oxigraph query may run inline in an async handler.

The store is synchronous. A query left on the event loop stalls every other
request in the process — and the api Deployment is replicas: 1 behind a
tcpSocket readiness probe, so the socket stays open and nothing restarts it.
`GET /{oid}/{vid}/inferred` was the last one: anonymous, and ORDER BY over a
whole :inferred graph (404k triples on sphn).
"""

import ast
import pathlib

API = pathlib.Path(__file__).resolve().parents[2] / "ontoexplorer" / "api"


def _async_handlers_with_inline_store_query() -> list[str]:
    offenders = []
    for path in sorted(API.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            # Walk only the handler's own body. A nested def is skipped whole —
            # its body is precisely what gets handed to to_thread, so descending
            # into it reports every correctly-offloaded query as an offender.
            def _own_nodes(n):
                for child in ast.iter_child_nodes(n):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                        continue
                    yield child
                    yield from _own_nodes(child)

            for inner in _own_nodes(node):
                if not isinstance(inner, ast.Call):
                    continue
                fn = inner.func
                if isinstance(fn, ast.Attribute) and fn.attr == "query":
                    base = fn.value
                    name = getattr(base, "id", None) or getattr(base, "attr", None)
                    if name in ("store", "s", "s_"):
                        offenders.append(f"{path.relative_to(API.parent.parent)}:{inner.lineno} in {node.name}()")
    return offenders


def test_no_handler_queries_the_store_inline():
    offenders = _async_handlers_with_inline_store_query()
    assert offenders == [], (
        "Oxigraph query on the event loop — wrap it in asyncio.to_thread:\n  "
        + "\n  ".join(offenders)
    )
