"""ROBOT reasoning service — HTTP wrapper.

Exposes ROBOT's `reason` command (HermiT by default) as a single POST endpoint.
Phase-2 consistency detection in the worker calls this instead of subprocess-ing
ROBOT in-process (avoids dragging the JRE into the worker image and lets us cap
HermiT's heap independently of the worker's cgroup).

Inconsistency reporting — ROBOT exits 0 even when an ontology is inconsistent;
the verdict lives in stderr. We parse two patterns produced by
`org.obolibrary.robot.ReasonerHelper`:

    "The ontology is inconsistent."                  → globally inconsistent
    "There are <N> unsatisfiable classes ..."        → has unsat classes
        "    unsatisfiable: <IRI>"  (one per class)

Anything else means consistent (no unsat).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

log = logging.getLogger("robot-service")
logging.basicConfig(level=logging.INFO)

_ROBOT_JAR = os.getenv("ROBOT_JAR", "/opt/robot.jar")
_JAVA_OPTS = os.getenv("JAVA_OPTS", "-Xmx4g").split()
_WORK_DIR = Path(os.getenv("ROBOT_WORK_DIR", "/tmp/robot-work"))
_WORK_DIR.mkdir(parents=True, exist_ok=True)

_GLOBAL_INCONSISTENT_RE = re.compile(r"The ontology is inconsistent\b")
_UNSAT_COUNT_RE = re.compile(r"There are (\d+) unsatisfiable classes")
_UNSAT_LINE_RE = re.compile(r"unsatisfiable:\s*(\S+)")

# JVM exhaustion patterns. When ROBOT/HermiT hit these, no verdict line is
# emitted — defaulting to "consistent" would silently produce false positives
# (the same class of bug we just fixed in Konclude's wrapper). Report `error`
# so the detector surfaces it honestly.
_CRASH_PATTERNS = (
    re.compile(r"OutOfMemoryError", re.IGNORECASE),
    re.compile(r"StackOverflowError", re.IGNORECASE),
    re.compile(r"GC overhead limit exceeded", re.IGNORECASE),
    re.compile(r"Exception .* thrown from the UncaughtExceptionHandler"),
)

# Map file extension → ROBOT input format hint. ROBOT auto-detects but being
# explicit avoids ambiguity for N-Triples (which doesn't have a unique header).
_KNOWN_EXTS = {".ttl", ".nt", ".owl", ".rdf", ".xml", ".ofn", ".obo", ".omn"}

app = FastAPI(title="ROBOT Reasoning Service", version="1.0.0")


class ConsistencyResponse(BaseModel):
    """A consistent run returns status='ok' with the verdict; a crash returns
    status='crashed' and the consistency fields should be ignored."""
    status: Literal["ok", "crashed"] = "ok"
    consistent: bool
    globally_inconsistent: bool
    unsat_class_iris: list[str]
    reasoner: str
    elapsed_seconds: float
    robot_returncode: int
    stderr_tail: str
    stdout_tail: str = ""
    crash_reason: str | None = None


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "robot_jar_exists": Path(_ROBOT_JAR).exists()}


class ExtractResponse(BaseModel):
    status: Literal["ok", "crashed"] = "ok"
    module_size_bytes: int
    module_triple_count: int
    elapsed_seconds: float
    robot_returncode: int
    stderr_tail: str
    crash_reason: str | None = None
    # The extracted module body (RDF/XML or Turtle, format echoed from request).
    module: str = ""


@app.post("/extract", response_model=ExtractResponse)
def extract(
    file: UploadFile = File(...),
    term: list[str] = Form(...),
    method: Literal["BOT", "TOP", "STAR", "MIREOT"] = Form("BOT"),
    timeout_seconds: int = Form(600),
    output_format: Literal["ttl", "nt", "owl"] = Form("ttl"),
) -> ExtractResponse:
    """Extract a logical-locality module via `robot extract`.

    BOT (the default) is the OWL-API bottom-locality module: contains every
    axiom that could possibly affect entailments OVER the given terms in any
    extension of the module. Strongest soundness guarantee for justification
    use-cases — entailments of `term` SubClassOf `term` are preserved in the
    module iff they hold in the full ontology. Use BOT (not STAR/TOP) when
    the goal is to find justifications, since BOT is the smallest module
    that preserves all the subsumptions you'll query.

    For ordo Orphanet_121633 ⊑ Orphanet_C010 the BOT module shrinks the
    606K-triple input down to ~390 triples (~1500x), letting the downstream
    greedy walk run on the module rather than the full ontology.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _KNOWN_EXTS:
        suffix = ".ttl"

    job_id = uuid.uuid4().hex[:12]
    input_path = _WORK_DIR / f"{job_id}{suffix}"
    output_path = _WORK_DIR / f"{job_id}.module.{output_format}"
    try:
        data = file.file.read()
        input_path.write_bytes(data)

        cmd = [
            "java", *_JAVA_OPTS, "-jar", _ROBOT_JAR,
            "extract",
            "--method", method,
            "--input", str(input_path),
            "--output", str(output_path),
        ]
        for t in term:
            cmd.extend(["--term", t])

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout_seconds, check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, f"ROBOT extract exceeded {timeout_seconds}s timeout")
        elapsed = time.monotonic() - t0

        stderr = proc.stderr or ""
        stdout = proc.stdout or ""
        combined = stderr + "\n" + stdout

        crash_match = next(
            (p.search(combined) for p in _CRASH_PATTERNS if p.search(combined)),
            None,
        )
        if crash_match is not None:
            return ExtractResponse(
                status="crashed",
                module_size_bytes=0, module_triple_count=0,
                elapsed_seconds=elapsed, robot_returncode=proc.returncode,
                stderr_tail=stderr[-2000:],
                crash_reason=crash_match.group(0),
            )

        if not output_path.exists():
            # ROBOT didn't write the module — surface the stderr so the
            # caller can diagnose.
            raise HTTPException(500, f"ROBOT extract did not produce output. stderr: {stderr[-500:]}")

        module_bytes = output_path.read_bytes()
        module_text = module_bytes.decode("utf-8", errors="replace")
        # Coarse triple count; works for nt and is approximately right for ttl.
        triple_count = sum(1 for ln in module_text.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "@")))

        log.info(
            "robot_extract_done id=%s method=%s terms=%d module_bytes=%d triples~%d elapsed=%.2fs",
            job_id, method, len(term), len(module_bytes), triple_count, elapsed,
        )
        return ExtractResponse(
            module_size_bytes=len(module_bytes),
            module_triple_count=triple_count,
            elapsed_seconds=elapsed,
            robot_returncode=proc.returncode,
            stderr_tail=stderr[-2000:],
            module=module_text,
        )
    finally:
        for p in (input_path, output_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


@app.post("/consistency", response_model=ConsistencyResponse)
def consistency(
    file: UploadFile = File(...),
    reasoner: Literal["HermiT", "ELK", "JFact", "EMR", "structural"] = Form("HermiT"),
    timeout_seconds: int = Form(600),
) -> ConsistencyResponse:
    """Run `robot reason` and parse stderr for the verdict.

    The uploaded file is written to a per-request tmp path so concurrent
    requests don't collide. ROBOT auto-detects format from extension, so we
    preserve the original suffix.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _KNOWN_EXTS:
        # Default to .ttl if the caller didn't supply a recognised extension —
        # ROBOT will still parse it via Apache Jena if it's actually Turtle.
        suffix = ".ttl"

    job_id = uuid.uuid4().hex[:12]
    input_path = _WORK_DIR / f"{job_id}{suffix}"
    output_path = _WORK_DIR / f"{job_id}.reasoned{suffix}"
    try:
        data = file.file.read()
        input_path.write_bytes(data)

        cmd = [
            "java", *_JAVA_OPTS, "-jar", _ROBOT_JAR,
            "reason",
            "--reasoner", reasoner,
            "--input", str(input_path),
            "--output", str(output_path),
        ]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=504,
                detail=f"ROBOT reason exceeded {timeout_seconds}s timeout",
            )
        elapsed = time.monotonic() - t0

        stderr = proc.stderr or ""
        stdout = proc.stdout or ""
        # ROBOT emits its ReasonerHelper diagnostics to stderr when log4j is
        # configured for it, but some build/run configurations route it to
        # stdout instead. Parse both streams to be robust.
        combined = stderr + "\n" + stdout

        # Crash detection first — a JVM OOM/exception means no reliable verdict.
        crash_match = next(
            (p.search(combined) for p in _CRASH_PATTERNS if p.search(combined)),
            None,
        )
        if crash_match is not None:
            log.warning(
                "robot_reason_crashed id=%s reasoner=%s rc=%d reason=%s",
                job_id, reasoner, proc.returncode, crash_match.group(0),
            )
            return ConsistencyResponse(
                status="crashed",
                consistent=False,
                globally_inconsistent=False,
                unsat_class_iris=[],
                reasoner=reasoner,
                elapsed_seconds=elapsed,
                robot_returncode=proc.returncode,
                stderr_tail=stderr[-2000:],
                stdout_tail=stdout[-2000:],
                crash_reason=crash_match.group(0),
            )

        globally_inc = bool(_GLOBAL_INCONSISTENT_RE.search(combined))
        unsat_iris = _UNSAT_LINE_RE.findall(combined)
        # ROBOT lists unsat classes even when there are 0 (it just won't print
        # the count line). The two signals together give the verdict:
        consistent = not globally_inc and not unsat_iris

        log.info(
            "robot_reason_done id=%s reasoner=%s consistent=%s globally=%s "
            "unsat=%d elapsed=%.2fs rc=%d",
            job_id, reasoner, consistent, globally_inc, len(unsat_iris), elapsed, proc.returncode,
        )

        return ConsistencyResponse(
            consistent=consistent,
            globally_inconsistent=globally_inc,
            unsat_class_iris=unsat_iris,
            reasoner=reasoner,
            elapsed_seconds=elapsed,
            robot_returncode=proc.returncode,
            stderr_tail=stderr[-2000:],
            stdout_tail=stdout[-2000:],
        )
    finally:
        for p in (input_path, output_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
