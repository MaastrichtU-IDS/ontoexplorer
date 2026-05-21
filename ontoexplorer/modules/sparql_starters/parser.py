"""Parsers for the two starter-library intake formats."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class StarterDraft:
    """A parsed starter ready to be inserted as a saved_queries row."""
    name: str
    description: str | None
    category: str | None
    tags: list[str] = field(default_factory=list)
    query_text: str = ""


def detect_format(text: str) -> Literal["json", "rq"]:
    """Return 'json' if the content begins with { or [ (after whitespace); else 'rq'."""
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return "json"
    return "rq"


def parse_json_library(text: str) -> list[StarterDraft]:
    """Parse a `{ starters: [...] }` document.

    Entries missing required fields (`name`, `query_text`) are silently skipped.
    Malformed JSON or missing top-level shape raises ValueError.
    """
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc

    if not isinstance(doc, dict) or "starters" not in doc:
        raise ValueError("JSON library must be an object with a 'starters' key")
    starters = doc["starters"]
    if not isinstance(starters, list):
        raise ValueError("'starters' must be an array")

    out: list[StarterDraft] = []
    for entry in starters:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        query_text = entry.get("query_text")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(query_text, str) or not query_text.strip():
            continue
        tags = entry.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        out.append(StarterDraft(
            name=name.strip(),
            description=entry.get("description"),
            category=entry.get("category"),
            tags=[str(t) for t in tags],
            query_text=query_text,
        ))
    return out


_META_LINE = re.compile(r"^\s*#\s*@(\w+)\s+(.*)$")


def parse_rq_with_metadata(text: str) -> StarterDraft:
    """Parse a single `.rq` file with leading `# @key value` metadata comments.

    Required: `# @name`. Recognised keys: name, description, category, tags
    (comma-separated). Unknown keys are silently ignored. Body after the
    leading metadata block is `query_text` (verbatim).
    """
    lines = text.splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            # Blank lines inside the metadata block are tolerated.
            body_start = i + 1
            continue
        m = _META_LINE.match(line)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
            body_start = i + 1
        else:
            # First non-comment, non-blank line begins the body.
            break

    name = meta.get("name")
    if not name:
        raise ValueError("Missing '# @name ...' metadata line")

    tags: list[str] = []
    if "tags" in meta:
        tags = [t.strip() for t in meta["tags"].split(",") if t.strip()]

    query_text = "\n".join(lines[body_start:]).lstrip("\n").rstrip()

    return StarterDraft(
        name=name,
        description=meta.get("description"),
        category=meta.get("category"),
        tags=tags,
        query_text=query_text,
    )
