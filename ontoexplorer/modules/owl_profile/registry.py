"""OWL 2 profile identifiers.

Profile detection now runs on the native horned-profile checker (see
`detector.py`); this module just holds the profile-name constant that API
routes validate against. `PROFILE_NAMES` keeps its historical order
(EL, RL, QL, DL) so cached payloads and the UI are unchanged.
"""
from __future__ import annotations

from typing import Literal

ProfileName = Literal["el", "rl", "ql", "dl"]

PROFILE_NAMES: tuple[ProfileName, ...] = ("el", "rl", "ql", "dl")
