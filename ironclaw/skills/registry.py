"""
ironclaw.skills.registry
~~~~~~~~~~~~~~~~~~~~~~~~~
SkillRegistry — discovers, loads, and manages skills.

Progressive disclosure (mirroring the agentskills.io spec):

  Stage 1 — Discovery
    At startup the registry scans skill directories and loads only the
    ``name`` and ``description`` from each SKILL.md.  This is cheap (~100
    tokens per skill) and tells the agent which skills exist.

  Stage 2 — Activation
    When a user message seems to match a skill, the full SKILL.md body is
    loaded into context.  Matching is either:
      • keyword-based (default, no extra LLM call)
      • LLM-based (optional, pass ``router_provider``)

  Stage 3 — Execution
    The agent has the full instructions and follows them, optionally reading
    scripts/ or references/ files as needed.

Usage::

    from ironclaw.skills.registry import SkillRegistry

    reg = SkillRegistry()
    reg.add_directory(Path("ironclaw/skills/builtin"))
    reg.add_directory(Path("~/.ironclaw/skills").expanduser())

    # Get system-prompt injection for a given user message
    skill_context = reg.context_for("summarise this PDF into bullet points")
    # → str with the full SKILL.md instructions for the matching skill(s)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ironclaw.skills.manifest import SkillManifest

if TYPE_CHECKING:
    from ironclaw.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Manages a collection of skills.

    Parameters
    ----------
    max_active : int
        Maximum number of skills to activate for a single message (default 2).
    min_keyword_score : int
        Minimum keyword overlap score to activate a skill without an LLM (default 1).
    router_provider : LLMProvider | None
        If set, use this LLM to choose which skill to activate.
    """

    def __init__(
        self,
        max_active: int = 2,
        min_keyword_score: int = 1,
        router_provider: "LLMProvider | None" = None,
    ) -> None:
        self._skills: dict[str, SkillManifest] = {}
        self.max_active = max_active
        self.min_keyword_score = min_keyword_score
        self._router = router_provider

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def add_directory(self, path: Path | str) -> "SkillRegistry":
        """
        Scan *path* for skill directories (each must contain SKILL.md).
        Returns self for chaining.
        """
        root = Path(path).expanduser()
        if not root.exists():
            logger.debug("Skills directory not found: %s", root)
            return self

        loaded = 0
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                manifest = SkillManifest.from_file(skill_md)
                self._skills[manifest.name] = manifest
                logger.debug("Loaded skill: %s", manifest.name)
                loaded += 1
            except Exception as e:
                logger.warning("Failed to load skill at %s: %s", skill_md, e)

        if loaded:
            logger.info("SkillRegistry: loaded %d skill(s) from %s", loaded, root)
        return self

    def add_skill(self, manifest: SkillManifest) -> "SkillRegistry":
        """Register a single skill directly."""
        self._skills[manifest.name] = manifest
        return self

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @property
    def names(self) -> list[str]:
        return sorted(self._skills)

    def get(self, name: str) -> SkillManifest | None:
        return self._skills.get(name)

    def summaries(self) -> list[dict[str, str]]:
        """Stage 1: return name + description for all skills."""
        return [m.summary for m in self._skills.values()]

    def discovery_prompt(self) -> str:
        """
        Compact system-prompt fragment listing available skills.
        Injected once at agent startup.
        """
        if not self._skills:
            return ""
        lines = ["## Available Skills\n"]
        for m in self._skills.values():
            lines.append(f"- **{m.name}**: {m.description}")
        lines.append(
            "\nWhen a task matches a skill's description, "
            "follow its instructions from the SKILL context below."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def context_for(self, user_message: str) -> str:
        """
        Stage 2: return full SKILL.md instructions for skills relevant to
        *user_message*.  Uses keyword matching (or LLM if configured).
        """
        if not self._skills:
            return ""

        if self._router:
            names = _llm_select(user_message, list(self._skills.values()), self._router, self.max_active)
        else:
            names = _keyword_select(
                user_message,
                list(self._skills.values()),
                self.max_active,
                self.min_keyword_score,
            )

        if not names:
            return ""

        parts = []
        for name in names:
            m = self._skills[name]
            parts.append(
                f"---\n## Skill: {m.name}\n\n{m.body}\n---"
            )
            logger.debug("Activated skill: %s", name)

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Skill management
    # ------------------------------------------------------------------

    def install_from_directory(self, path: Path | str) -> SkillManifest:
        """Install a skill from a directory into the registry."""
        root = Path(path)
        skill_md = root / "SKILL.md"
        if not skill_md.exists():
            raise FileNotFoundError(f"No SKILL.md in {root}")
        manifest = SkillManifest.from_file(skill_md)
        self._skills[manifest.name] = manifest
        return manifest

    def remove(self, name: str) -> bool:
        return self._skills.pop(name, None) is not None

    def __len__(self) -> int:
        return len(self._skills)

    def __repr__(self) -> str:
        return f"SkillRegistry({len(self._skills)} skills)"


# ---------------------------------------------------------------------------
# Keyword-based matching (default, no extra tokens)
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "and", "or", "in", "on", "at", "for", "with", "by",
    "this", "that", "it", "its", "my", "me", "i", "you", "we", "they",
    "how", "what", "when", "where", "why", "which", "can", "do", "does",
    "please", "help", "use",
}

def _tokenise(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


def _keyword_select(
    message: str,
    skills: list[SkillManifest],
    max_n: int,
    min_score: int,
) -> list[str]:
    msg_tokens = _tokenise(message)
    scores: list[tuple[int, str]] = []
    for m in skills:
        skill_tokens = _tokenise(m.name + " " + m.description)
        score = len(msg_tokens & skill_tokens)
        if score >= min_score:
            scores.append((score, m.name))
    scores.sort(reverse=True)
    return [name for _, name in scores[:max_n]]


# ---------------------------------------------------------------------------
# LLM-based matching (optional, more accurate)
# ---------------------------------------------------------------------------

def _llm_select(
    message: str,
    skills: list[SkillManifest],
    provider: "LLMProvider",
    max_n: int,
) -> list[str]:
    """Ask the LLM which skills are relevant. Returns list of skill names."""
    import asyncio
    from ironclaw.core.message import Message

    skill_list = "\n".join(f"- {m.name}: {m.description}" for m in skills)
    prompt = (
        f"Available skills:\n{skill_list}\n\n"
        f"User message: {message}\n\n"
        f"Which skills (if any) are relevant? "
        f"Reply with a comma-separated list of skill names only, "
        f"or 'none' if no skill is relevant. Max {max_n}."
    )

    try:
        resp = asyncio.run(provider.complete([Message.user(prompt)]))
        raw = resp.content.strip().lower()
        if raw == "none" or not raw:
            return []
        known = {m.name for m in skills}
        selected = [t.strip() for t in raw.split(",")]
        return [s for s in selected if s in known][:max_n]
    except Exception as e:
        logger.warning("LLM skill routing failed (%s), falling back to keyword", e)
        return _keyword_select(message, skills, max_n, 1)
