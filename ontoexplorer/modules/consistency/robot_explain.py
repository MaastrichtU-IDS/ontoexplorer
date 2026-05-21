"""ROBOT explain shell-out wrapper for per-class unsatisfiability justifications.

We invoke `robot explain -M unsatisfiability -u all -m <max> --explanation <md>` in
ONE shot per scope (one JVM start, all unsats explained together) and parse the
Markdown into typed tokens. Returns a dict mapping each unsatisfiable class IRI to
the token list of its justification.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pyowl2_profiles.manchester import ManchesterToken

from ontoexplorer.modules.consistency.robot_md_parser import parse_robot_explanation_md


class RobotExplainUnavailable(RuntimeError):
    """Raised when the ROBOT binary cannot be found on PATH."""


class RobotExplainTimeout(RuntimeError):
    """Raised when ROBOT explain exceeds the timeout."""


def explain_unsatisfiability(
    ontology_path: Path,
    *,
    max_explanations: int = 10,
    timeout_seconds: int = 300,
    robot_cmd: str = "robot",
) -> dict[str, list[list[ManchesterToken]]]:
    """Run ROBOT explain on the merged ontology; return per-class justifications.

    Args:
        ontology_path: merged OWL/Turtle file (the same one Konclude reasoned over).
        max_explanations: cap on total justifications to compute (ROBOT `-m` flag).
        timeout_seconds: hard cutoff for the ROBOT subprocess.
        robot_cmd: binary name on PATH.

    Returns:
        dict mapping unsat class IRI to its justification (list of axiom token lists).
        Empty dict if ROBOT produced no explanation file (ontology was consistent, or error).

    Raises:
        RobotExplainUnavailable: if ROBOT is missing.
        RobotExplainTimeout: if the command exceeds the timeout.
    """
    if shutil.which(robot_cmd) is None:
        raise RobotExplainUnavailable(f"{robot_cmd!r} not found on PATH")

    md_path = ontology_path.with_suffix(".explain.md")
    try:
        subprocess.run(
            [
                robot_cmd, "explain",
                "--input", str(ontology_path),
                "--reasoner", "hermit",
                "-M", "unsatisfiability",
                "-u", "all",
                "-m", str(max_explanations),
                "--explanation", str(md_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RobotExplainTimeout(f"ROBOT explain timed out after {timeout_seconds}s") from e

    if not md_path.exists():
        return {}

    return parse_robot_explanation_md(md_path.read_text())
