"""Konclude reasoner shell-out wrapper.

Konclude is a native C++ OWL 2 DL reasoner (no JVM). We invoke its CLI
twice per consistency check: once for the boolean (`consistency`) and
once for classification (to extract unsatisfiable classes).

The wrapper is a pure function over a file path on disk; the caller is
responsible for materializing the merge.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


class KoncludeUnavailable(RuntimeError):
    """Raised when the Konclude binary cannot be found on PATH."""


class KoncludeTimeout(RuntimeError):
    """Raised when Konclude exceeds the timeout."""


class KoncludeCrashed(RuntimeError):
    """Raised when Konclude exits without printing a verdict (typically OOM/SIGKILL).

    Surfaced separately from `KoncludeUnavailable` so the detector reports
    these as `error` with a memory-pressure hint rather than silently
    classifying the ontology as inconsistent (which is the prior bug:
    konclude exit 137 → stdout truncated mid-preamble → "no verdict"
    → previous code returned `False` and claimed inconsistency).
    """


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
    consistent = _parse_consistency_verdict(stdout, returncode=cons_proc.returncode, stderr=stderr)

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


_VERDICT_LINE_RE = re.compile(r"Ontology\s+'[^']*'\s+is\s+(in)?consistent", re.IGNORECASE)


def _parse_consistency_verdict(stdout: str, *, returncode: int, stderr: str) -> bool:
    """Parse Konclude's verdict line.

    Konclude prints exactly one line like:
        {info} ... >> Ontology '/path/to/file' is consistent.
    or  {info} ... >> Ontology '/path/to/file' is inconsistent.

    We require a precise match. If the verdict line is absent and Konclude
    exited non-zero, that's a crash (typically OOM-kill / SIGKILL exit 137
    on the SROIQ precomputation step for large DL ontologies). Previously
    this fell through to `return False` and silently produced false-positive
    "inconsistent" verdicts; now we raise so the detector reports `error`.
    """
    m = _VERDICT_LINE_RE.search(stdout)
    if m is not None:
        return m.group(1) is None  # "in"? consistent → consistent iff group is None
    if returncode != 0:
        snippet = (stderr or stdout).strip().splitlines()[-1:] if (stderr or stdout) else []
        hint = snippet[0] if snippet else ""
        raise KoncludeCrashed(
            f"Konclude exited {returncode} without printing a verdict "
            f"(likely SROIQ-precomputation OOM-kill on a large ontology). "
            f"Last line: {hint[:200]}"
        )
    # Exit 0 with no verdict line should never happen. Be loud rather than guess.
    raise KoncludeCrashed("Konclude exited 0 but produced no verdict line (unexpected)")


_OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


def _parse_unsatisfiable_classes(classified_path: Path) -> list[str]:
    """Extract IRIs of classes equivalent to owl:Nothing from Konclude's classify output.

    Konclude's `-o` flag writes the inferred classification as OWL/XML. An
    unsatisfiable named class C may appear in either form:

    Form 1 (RDF/XML style):
        <owl:Class rdf:about="C">
            <owl:equivalentClass rdf:resource="owl:Nothing"/>
        </owl:Class>

    Form 2 (OWL/XML functional-style — what Konclude actually emits):
        <EquivalentClasses>
            <Class IRI="http://www.w3.org/2002/07/owl#Nothing"/>
            <Class IRI="C"/>
            <Class IRI="D"/>   <!-- any other classes equivalent to Nothing -->
        </EquivalentClasses>

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

    # Form 1: <owl:Class rdf:about="..."> with owl:equivalentClass → owl:Nothing
    for cls in root.iter(f"{{{ns['owl']}}}Class"):
        about = cls.get(f"{{{ns['rdf']}}}about")
        if about is None:
            continue
        for eq in cls.findall(f"{{{ns['owl']}}}equivalentClass"):
            ref = eq.get(f"{{{ns['rdf']}}}resource")
            if ref == _OWL_NOTHING:
                unsat.add(about)

    # Form 2: <EquivalentClasses> with one child being owl:Nothing → all OTHER children unsat
    for eq_classes in root.iter(f"{{{ns['owl']}}}EquivalentClasses"):
        iris_in_group: list[str] = []
        for child in eq_classes:
            # Child may be <owl:Class IRI="..."/> or just <Class IRI="..."/>
            iri = child.get("IRI") or child.get(f"{{{ns['rdf']}}}about")
            if iri is not None:
                iris_in_group.append(iri)
        if _OWL_NOTHING in iris_in_group:
            for iri in iris_in_group:
                if iri != _OWL_NOTHING:
                    unsat.add(iri)

    return sorted(unsat)
