"""Both reasoner-service images must ship every service module.

The backends import their helper modules lazily (inside classify calls), so a
module missing from a Dockerfile COPY list only fails at request time, inside
the container. Dockerfile.arm64 drifted this way: it lacked five modules that
rustdl_backend imports. This check catches that without building an image.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent
MODULES = sorted(p.name for p in HERE.glob("*.py") if not p.name.startswith("test_"))


def _copied_py_files(dockerfile: Path) -> set[str]:
    # Join backslash continuations, then collect .py sources of local COPY lines.
    text = re.sub(r"\\\n", " ", dockerfile.read_text())
    files: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        if parts[:1] == ["COPY"] and not any(a.startswith("--from") for a in parts):
            files.update(a for a in parts[1:-1] if a.endswith(".py"))
    return files


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.arm64"])
def test_dockerfile_copies_every_service_module(dockerfile):
    copied = _copied_py_files(HERE / dockerfile)
    assert sorted(set(MODULES) - copied) == []
    assert sorted(copied - set(MODULES)) == []  # no stale names either
