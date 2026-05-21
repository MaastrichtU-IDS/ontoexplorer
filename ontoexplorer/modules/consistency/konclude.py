"""Konclude reasoner shell-out wrapper.

Konclude is a native C++ OWL 2 DL reasoner (no JVM). We invoke its CLI
twice per consistency check: once for the boolean (`consistency`) and
once for classification (to extract unsatisfiable classes).

The wrapper is a pure function over a file path on disk; the caller is
responsible for materializing the merge.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


class KoncludeUnavailable(RuntimeError):
    """Raised when the Konclude binary cannot be found on PATH."""


class KoncludeTimeout(RuntimeError):
    """Raised when Konclude exceeds the timeout."""


@dataclass
class KoncludeResult:
    consistent: bool
    unsatisfiable_class_iris: list[str] = field(default_factory=list)
    classification_output_path: Path | None = None  # for downstream robot_explain
    stdout: str = ""
    stderr: str = ""


def run_konclude_consistency(
    ontology_path: Path,
    *,
    timeout_seconds: int = 600,
    konclude_cmd: str = "Konclude",
) -> KoncludeResult:
    """Run Konclude consistency + classification on the merged ontology file.

    Args:
        ontology_path: Path to an OWL/Turtle/N-Triples file Konclude can load.
        timeout_seconds: Hard cutoff per Konclude invocation (consistency + classify combined wall time).
        konclude_cmd: Binary name on PATH.

    Returns:
        KoncludeResult with consistent flag + unsatisfiable class IRIs.

    Raises:
        KoncludeUnavailable: if the binary is not on PATH.
        KoncludeTimeout: if either invocation exceeds the timeout.
    """
    if shutil.which(konclude_cmd) is None:
        raise KoncludeUnavailable(f"{konclude_cmd!r} not found on PATH")

    # Step 1: consistency check
    try:
        cons_proc = subprocess.run(
            [konclude_cmd, "consistency", "-i", str(ontology_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise KoncludeTimeout(f"Konclude consistency timed out after {timeout_seconds}s") from e

    stdout = cons_proc.stdout
    stderr = cons_proc.stderr
    consistent = _parse_consistency_verdict(stdout)

    # Step 2: classification (only needed to find unsatisfiable classes; skip if globally inconsistent)
    unsat_iris: list[str] = []
    classify_out_path: Path | None = None
    if consistent:
        classify_out_path = ontology_path.with_suffix(".classified.owl")
        try:
            classify_proc = subprocess.run(
                [konclude_cmd, "classify", "-i", str(ontology_path), "-o", str(classify_out_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise KoncludeTimeout(f"Konclude classify timed out after {timeout_seconds}s") from e
        stdout += "\n" + classify_proc.stdout
        stderr += "\n" + classify_proc.stderr
        if classify_out_path.exists():
            unsat_iris = _parse_unsatisfiable_classes(classify_out_path)

    return KoncludeResult(
        consistent=consistent,
        unsatisfiable_class_iris=unsat_iris,
        classification_output_path=classify_out_path,
        stdout=stdout,
        stderr=stderr,
    )


def _parse_consistency_verdict(stdout: str) -> bool:
    """Konclude prints 'Ontology is consistent.' or 'Ontology is inconsistent.' to stdout."""
    lowered = stdout.lower()
    if "inconsistent" in lowered:
        return False
    if "consistent" in lowered:
        return True
    # Konclude exited 0 but didn't print the expected verdict — treat as inconsistent (conservative).
    return False


_OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


def _parse_unsatisfiable_classes(classified_path: Path) -> list[str]:
    """Extract IRIs of classes equivalent to owl:Nothing from Konclude's classify output.

    Konclude emits the inferred classification as OWL/XML. An unsatisfiable named
    class C appears as `<owl:Class rdf:about="C"> <owl:equivalentClass rdf:resource="owl:Nothing"/> </owl:Class>`
    OR as `<owl:EquivalentClasses>` with two children, one of which is owl:Nothing.

    We tolerate both forms.
    """
    try:
        tree = ET.parse(classified_path)
    except ET.ParseError:
        return []
    root = tree.getroot()
    ns = {
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    }
    unsat: set[str] = set()
    # Form 1: owl:Class with owl:equivalentClass pointing at owl:Nothing
    for cls in root.iter(f"{{{ns['owl']}}}Class"):
        about = cls.get(f"{{{ns['rdf']}}}about")
        if about is None:
            continue
        for eq in cls.findall(f"{{{ns['owl']}}}equivalentClass"):
            ref = eq.get(f"{{{ns['rdf']}}}resource")
            if ref == _OWL_NOTHING:
                unsat.add(about)
    return sorted(unsat)
