"""Constants and dataclasses for OWL 2 profile detection."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

ProfileName = Literal["el", "rl", "ql", "dl"]
PROFILE_NAMES: tuple[ProfileName, ...] = ("el", "rl", "ql", "dl")


@dataclass(frozen=True)
class ProfileViolation:
    """One axiom that violates a profile."""
    profile: ProfileName
    axiom_type: str                  # e.g. "owl:DisjointClasses", "punning", "role-hierarchy-cycle"
    subject_iri: str | None
    details: str                     # human-readable
    manchester: list[dict] | None = field(default=None, compare=False)
    """Pre-rendered Manchester OWL tokens for display. Each token is a plain dict
    matching ManchesterTextToken | ManchesterIriToken from manchester.py.
    None when rendering was not attempted or failed.
    """
