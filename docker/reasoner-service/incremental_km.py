"""km-backed incremental EL++ reasoning sessions.

km (kobayashi-marust) ships a persistent JSONL incremental classifier
(`km incremental`) with an entailment oracle. This module:

  1. converts an ontology (N-Triples) → km's normalized clauses via
     `km ofn` (through py-horned-owl's OWL functional-syntax serialization), and
  2. wraps a long-lived `km incremental` subprocess as a KmSession supporting
     init / add / remove / change / is_subsumed_by / classify / stats.

km is EL++: ontologies outside that fragment (inverse roles, etc.) are rejected
by `km ofn` with an "out of fragment" error, surfaced here as OutOfFragment.

Sessions are in-memory and transient — a reasoning workbench, not durable state
(a reasoner-service restart drops them).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import threading
import time
import uuid

_KM_BIN = os.getenv("KM_BIN", "km")


class OutOfFragment(Exception):
    """The ontology is outside km's EL++ fragment (e.g. inverse roles)."""


class KmError(Exception):
    """km rejected a command or died."""


def ontology_to_clauses(ntriples: str) -> tuple[list, dict]:
    """N-Triples → (normalized clauses, iri_map) via py-horned-owl + `km ofn`.

    iri_map is {km-internal-concept-name: IRI}; we also return its inverse use in
    the session so callers can query by IRI. Raises OutOfFragment for non-EL++.
    """
    import pyhornedowl
    import pyoxigraph

    store = pyoxigraph.Store()
    store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                    format=pyoxigraph.RdfFormat.N_TRIPLES)
    rdfxml = pyoxigraph.serialize(
        (q.triple for q in store.quads_for_pattern(None, None, None, None)),
        format=pyoxigraph.RdfFormat.RDF_XML,
    ).decode("utf-8")
    onto = pyhornedowl.open_ontology_from_string(rdfxml, serialization="rdf")
    ofn = onto.save_to_string(serialization="ofn")

    import tempfile
    fd, path = tempfile.mkstemp(suffix=".ofn")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(ofn)
        proc = subprocess.run([_KM_BIN, "ofn", path], capture_output=True, text=True, timeout=600)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if proc.returncode != 0:
        msg = (proc.stderr or "").strip()
        if "out of fragment" in msg.lower():
            raise OutOfFragment(msg)
        raise KmError(f"km ofn failed (rc={proc.returncode}): {msg[:400]}")
    data = json.loads(proc.stdout)
    return data.get("clauses", []), data.get("iri_map", {})


class KmSession:
    """A single persistent `km incremental` classifier over one ontology."""

    def __init__(self, ntriples: str):
        clauses, iri_map = ontology_to_clauses(ntriples)
        # km's is_subsumed_by speaks internal concept names; expose an IRI API by
        # inverting iri_map ({internal: IRI} → {IRI: internal}).
        self._iri_to_name = {iri: name for name, iri in iri_map.items()}
        self._name_to_iri = dict(iri_map)
        self._lock = threading.Lock()
        self.created_at = time.monotonic()
        self.last_used = self.created_at
        self._proc = subprocess.Popen(
            [_KM_BIN, "incremental"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        init = self._cmd({"op": "init", "clauses": clauses})
        if init.get("status") != "ok":
            self.close()
            raise KmError(f"km init failed: {init}")
        self.revision = init.get("revision", 0)
        self.inconsistent = init.get("inconsistent", False)

    def _cmd(self, payload: dict) -> dict:
        with self._lock:
            if self._proc.poll() is not None:
                raise KmError("km session has exited")
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
            self.last_used = time.monotonic()
        if not line:
            raise KmError("km session closed unexpectedly")
        return json.loads(line)

    def _to_name(self, iri: str) -> str:
        # Accept either an IRI (mapped to km's internal name) or an already-internal name.
        return self._iri_to_name.get(iri, iri)

    def classify(self) -> dict:
        return self._cmd({"op": "classify"})

    def stats(self) -> dict:
        r = self._cmd({"op": "stats"})
        self.revision = r.get("revision", self.revision)
        self.inconsistent = r.get("inconsistent", self.inconsistent)
        return r

    def is_subsumed_by(self, sub: str, sup: str) -> bool | None:
        r = self._cmd({"op": "is_subsumed_by", "sub": self._to_name(sub), "sup": self._to_name(sup)})
        return r.get("entailed")

    def assert_subclass(self, sub_iri: str, sup_iri: str) -> dict:
        """Incrementally add a hypothetical `sub ⊑ sup` axiom between two existing
        named classes. Builds the EL normal-form clause `sub(x) → sup(x)` using
        km's internal concept names. Raises KmError if either class is unknown."""
        sub = self._iri_to_name.get(sub_iri)
        sup = self._iri_to_name.get(sup_iri)
        if sub is None or sup is None:
            missing = sub_iri if sub is None else sup_iri
            raise KmError(f"class not in this ontology's signature: {missing}")
        clause = {
            "body": [{"kind": "concept", "concept": sub, "term": {"kind": "var", "name": "x"}}],
            "head": [{"kind": "concept", "concept": sup, "term": {"kind": "var", "name": "x"}}],
        }
        return self.change(add_clauses=[clause])

    def change(self, add_clauses: list | None = None, remove_clause_ids: list | None = None) -> dict:
        r = self._cmd({
            "op": "change",
            "add_clauses": add_clauses or [],
            "remove_clause_ids": remove_clause_ids or [],
        })
        if r.get("status") == "ok":
            # km nests the IncrementalChange (revision, added_clause_ids, …) under
            # `update`; `inconsistent` is reported at the top level.
            self.revision = r.get("update", {}).get("revision", self.revision)
            self.inconsistent = r.get("inconsistent", self.inconsistent)
        return r

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass


class SessionStore:
    """In-memory, capped store of KmSessions. Evicts the least-recently-used when
    over capacity or older than the TTL. Transient by design."""

    def __init__(self, max_sessions: int = 32, ttl_s: int = 3600):
        self._sessions: dict[str, KmSession] = {}
        self._lock = threading.Lock()
        self._max = max_sessions
        self._ttl = ttl_s

    def create(self, ntriples: str) -> tuple[str, KmSession]:
        self._evict()
        session = KmSession(ntriples)  # may raise OutOfFragment/KmError before we store
        sid = str(uuid.uuid4())
        with self._lock:
            self._sessions[sid] = session
        return sid, session

    def get(self, sid: str) -> KmSession | None:
        with self._lock:
            return self._sessions.get(sid)

    def close(self, sid: str) -> bool:
        with self._lock:
            session = self._sessions.pop(sid, None)
        if session is not None:
            session.close()
            return True
        return False

    def _evict(self) -> None:
        now = time.monotonic()
        with self._lock:
            stale = [sid for sid, s in self._sessions.items() if now - s.last_used > self._ttl]
            for sid in stale:
                self._sessions.pop(sid).close()
            while len(self._sessions) >= self._max:
                oldest = min(self._sessions, key=lambda s: self._sessions[s].last_used)
                self._sessions.pop(oldest).close()
