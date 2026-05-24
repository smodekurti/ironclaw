"""
ironclaw.skills.manifest
~~~~~~~~~~~~~~~~~~~~~~~~~
SkillManifest — parsed representation of a SKILL.md file.

Format follows the agentskills.io specification:
  https://agentskills.io/specification

SKILL.md structure::

    ---
    name: skill-name
    description: What it does and when to use it.
    license: MIT                    # optional
    compatibility: Requires Python  # optional
    allowed-tools: Bash Read        # optional (experimental)
    metadata:                       # optional
      author: your-org
      version: "1.0"
    ---

    # Skill instructions

    Full Markdown body with step-by-step instructions...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Validation constants (from spec)
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_MAX_NAME  = 64
_MAX_DESC  = 1024
_MAX_COMPAT = 500


@dataclass
class SkillManifest:
    """
    Parsed representation of a SKILL.md file.

    Attributes
    ----------
    name : str
        Unique skill identifier (lowercase, hyphens only).
    description : str
        What the skill does and when to use it (≤ 1024 chars).
    body : str
        Full Markdown instructions (loaded on activation).
    path : Path
        Root directory of the skill.
    license : str
        License name or file reference (optional).
    compatibility : str
        Environment requirements (optional).
    allowed_tools : list[str]
        Pre-approved tools (experimental, optional).
    metadata : dict
        Arbitrary key-value metadata (optional).
    """

    name: str
    description: str
    body: str = ""
    path: Path = field(default_factory=Path)
    license: str = ""
    compatibility: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, skill_md_path: Path) -> "SkillManifest":
        """Parse a SKILL.md file and return a SkillManifest."""
        text = skill_md_path.read_text(encoding="utf-8")
        front, body = _split_frontmatter(text)
        data = _parse_yaml_frontmatter(front)

        name = str(data.get("name", "")).strip()
        description = str(data.get("description", "")).strip()
        _validate(name, description, skill_md_path)

        return cls(
            name=name,
            description=description,
            body=body.strip(),
            path=skill_md_path.parent,
            license=str(data.get("license", "")),
            compatibility=str(data.get("compatibility", "")),
            allowed_tools=_parse_allowed_tools(data.get("allowed-tools", "")),
            metadata=data.get("metadata", {}),
        )

    # ------------------------------------------------------------------
    # Progressive disclosure helpers
    # ------------------------------------------------------------------

    @property
    def summary(self) -> dict[str, str]:
        """Minimal info loaded at startup (name + description only)."""
        return {"name": self.name, "description": self.description}

    def script_dir(self) -> Path:
        return self.path / "scripts"

    def references_dir(self) -> Path:
        return self.path / "references"

    def assets_dir(self) -> Path:
        return self.path / "assets"

    def read_reference(self, filename: str) -> str:
        """Load a file from the references/ directory."""
        ref_path = self.references_dir() / filename
        if ref_path.exists():
            return ref_path.read_text(encoding="utf-8")
        return ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split '---\\n...\\n---\\n body' into (frontmatter_str, body_str)."""
    if not text.startswith("---"):
        return "", text
    parts = text[3:].split("---", 1)
    if len(parts) < 2:
        return parts[0], ""
    return parts[0].strip(), parts[1].strip()


def _parse_yaml_frontmatter(text: str) -> dict[str, Any]:
    """
    Minimal YAML parser: handles scalar values, nested dicts (indented),
    and space-separated strings.  Avoids a PyYAML dependency.
    """
    result: dict[str, Any] = {}
    current_section: str | None = None

    for raw in text.splitlines():
        # Detect indented key under a mapping section
        if raw.startswith("  ") and current_section:
            stripped = raw.strip()
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                if not isinstance(result.get(current_section), dict):
                    result[current_section] = {}
                result[current_section][k.strip()] = v.strip().strip('"').strip("'")
            continue

        current_section = None
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val == "":
                # Could be a mapping section header
                current_section = key
                result[key] = {}
            else:
                result[key] = val

    return result


def _parse_allowed_tools(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(t) for t in value]
    return str(value).split()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(name: str, description: str, path: Path) -> None:
    if not name:
        raise ValueError(f"SKILL.md at {path}: 'name' field is required")
    if len(name) > _MAX_NAME:
        raise ValueError(f"SKILL.md at {path}: 'name' exceeds {_MAX_NAME} chars")
    if not _NAME_RE.match(name):
        raise ValueError(
            f"SKILL.md at {path}: 'name' must be lowercase alphanumeric + hyphens, "
            f"not start/end with hyphen, no consecutive hyphens. Got: {name!r}"
        )
    if "--" in name:
        raise ValueError(f"SKILL.md at {path}: 'name' must not contain consecutive hyphens")
    if not description:
        raise ValueError(f"SKILL.md at {path}: 'description' field is required")
    if len(description) > _MAX_DESC:
        raise ValueError(f"SKILL.md at {path}: 'description' exceeds {_MAX_DESC} chars")
