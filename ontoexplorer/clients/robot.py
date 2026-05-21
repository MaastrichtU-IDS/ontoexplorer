"""HTTP client for the robot-service container.

Wraps the `/consistency` endpoint behind a function whose shape matches the
prior `run_konclude_consistency` so the detector can swap reasoners with
minimal change. We deliberately do NOT mirror Konclude's exception hierarchy
1:1 — instead we collapse to two exceptions (`RobotServiceUnavailable`,
`RobotServiceCrashed`) plus the timeout already raised by `requests`.

Default reasoner is HermiT (full SROIQ DL). Callers can pass ELK for fast
classification of OWL-EL ontologies where they're sure inconsistency cannot
arise from non-EL constructs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import requests


class RobotServiceUnavailable(RuntimeError):
    """The robot-service container is unreachable (network / DNS / not running)."""


class RobotServiceCrashed(RuntimeError):
    """The reasoner inside robot-service crashed (OOM / unhandled exception).

    Surfaced as a distinct status so the detector can report `error` rather
    than silently treating it as a consistency verdict. The service reports
    crashes explicitly as `status: "crashed"` in the response body — this
    exception is raised by the client on receipt of that status.
    """


@dataclass
class RobotConsistencyResult:
    consistent: bool
    globally_inconsistent: bool
    unsatisfiable_class_iris: list[str] = field(default_factory=list)
    reasoner: str = "HermiT"
    elapsed_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""


def _base_url() -> str:
    return os.getenv("ROBOT_SERVICE_URL", "http://robot-service:8002")


def run_robot_consistency(
    ontology_path: Path,
    *,
    reasoner: str = "HermiT",
    timeout_seconds: int = 600,
    http_timeout_seconds: int | None = None,
) -> RobotConsistencyResult:
    """POST the ontology file to robot-service /consistency.

    Args:
        ontology_path: any RDF format ROBOT can parse (.ttl / .nt / .owl / .rdf).
        reasoner: one of "HermiT", "ELK", "JFact", "EMR", "structural".
        timeout_seconds: per-reasoning timeout reported to the service.
        http_timeout_seconds: HTTP socket timeout for the client. Defaults to
            timeout_seconds + 60 so HTTP doesn't time out before the reasoner
            does (in which case the service would still be holding the request
            and we'd lose its eventual response).

    Raises:
        RobotServiceUnavailable: connection refused / DNS failure.
        RobotServiceCrashed: reasoner OOM'd or threw an unhandled exception.
        requests.Timeout: HTTP socket timeout (separate from reasoner timeout).
    """
    if http_timeout_seconds is None:
        http_timeout_seconds = timeout_seconds + 60

    url = f"{_base_url()}/consistency"
    try:
        with open(ontology_path, "rb") as fh:
            resp = requests.post(
                url,
                files={"file": (ontology_path.name, fh, "application/octet-stream")},
                data={"reasoner": reasoner, "timeout_seconds": str(timeout_seconds)},
                timeout=http_timeout_seconds,
            )
    except requests.ConnectionError as exc:
        raise RobotServiceUnavailable(f"robot-service not reachable at {url}: {exc}") from exc

    resp.raise_for_status()
    body = resp.json()

    if body.get("status") == "crashed":
        raise RobotServiceCrashed(
            f"Reasoner {body.get('reasoner', reasoner)} crashed: "
            f"{body.get('crash_reason') or 'unknown'} "
            f"(elapsed {body.get('elapsed_seconds', 0):.1f}s)"
        )

    return RobotConsistencyResult(
        consistent=body["consistent"],
        globally_inconsistent=body["globally_inconsistent"],
        unsatisfiable_class_iris=body.get("unsat_class_iris", []),
        reasoner=body.get("reasoner", reasoner),
        elapsed_seconds=body.get("elapsed_seconds", 0.0),
        stdout=body.get("stdout_tail", ""),
        stderr=body.get("stderr_tail", ""),
    )
