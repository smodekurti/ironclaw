"""
ironclaw.user.profile
~~~~~~~~~~~~~~~~~~~~~
UserProfile — a portable identity and behavioural contract for the person
interacting with an agent (or fleet of agents).

The profile answers three questions that every agent should always know:
  1. **Who** is the user?  (name, role, timezone, language, contact)
  2. **How** should the agent communicate?  (preferences, tone, verbosity)
  3. **What are the hard rules?**  (dos, donts)

It is injected automatically into the agent's system prompt as a dedicated
section so no individual agent spec needs to repeat these instructions.

Usage
-----
::

    from ironclaw.user.profile import UserProfile

    profile = UserProfile(
        name="Alex Johnson",
        role="Senior Software Engineer",
        dos=["Always show code examples", "Be concise"],
        donts=["Never suggest rewriting everything from scratch"],
        preferences={"tone": "direct", "verbosity": "low"},
    )

    agent = AgentBuilder("assistant").with_user_profile(profile).build()
"""

from __future__ import annotations

import dataclasses
import json
import textwrap
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class UserProfile:
    """
    Identity and behavioural contract for the user.

    All fields are optional — fill in what you know.  The more context you
    provide, the more accurately agents can tailor their responses.

    Parameters
    ----------
    name:
        The user's full name or preferred name.
    email:
        Contact email (agents can mention it when relevant, e.g. drafting emails).
    role:
        Job title or role, e.g. "Product Manager", "Data Scientist".
    organization:
        Company or team name.
    timezone:
        IANA timezone string, e.g. "America/New_York". Used for scheduling context.
    language:
        Primary language for responses, e.g. "English", "Spanish". Default "English".
    dos:
        Things the agent must always do.
        E.g. ["Always cite sources", "Use bullet points for lists of 3+ items"].
    donts:
        Things the agent must never do.
        E.g. ["Never suggest I call a lawyer", "Don't use jargon"].
    preferences:
        Free-form key/value pairs for communication style.
        Common keys: tone (formal/casual/direct), verbosity (low/medium/high),
        format (markdown/plain), expertise_level (beginner/intermediate/expert).
    context:
        Free-form background that helps the agent understand the user's situation.
        E.g. "Working on a B2B SaaS startup in the healthcare space."
    goals:
        The user's primary goals or what they're trying to accomplish.
        E.g. ["Launch MVP by Q3", "Reduce customer support tickets by 30%"].
    """

    name: str = ""
    email: str = ""
    role: str = ""
    organization: str = ""
    timezone: str = ""
    language: str = "English"
    dos: List[str] = dataclasses.field(default_factory=list)
    donts: List[str] = dataclasses.field(default_factory=list)
    preferences: Dict[str, str] = dataclasses.field(default_factory=dict)
    context: str = ""
    goals: List[str] = dataclasses.field(default_factory=list)

    # ------------------------------------------------------------------
    # System prompt injection
    # ------------------------------------------------------------------

    def to_system_prompt_block(self) -> str:
        """
        Format the profile as a structured block for injection into the
        agent's system prompt.

        Returns an empty string if the profile has no meaningful content.
        """
        sections: List[str] = []

        # Identity
        identity_lines: List[str] = []
        if self.name:
            identity_lines.append(f"- **Name:** {self.name}")
        if self.role:
            identity_lines.append(f"- **Role:** {self.role}")
        if self.organization:
            identity_lines.append(f"- **Organization:** {self.organization}")
        if self.email:
            identity_lines.append(f"- **Email:** {self.email}")
        if self.timezone:
            identity_lines.append(f"- **Timezone:** {self.timezone}")
        if self.language and self.language != "English":
            identity_lines.append(f"- **Language:** {self.language}")

        if identity_lines:
            sections.append("### Who you are talking to\n" + "\n".join(identity_lines))

        # Context
        if self.context:
            sections.append(f"### Background\n{self.context.strip()}")

        # Goals
        if self.goals:
            goal_lines = "\n".join(f"- {g}" for g in self.goals)
            sections.append(f"### User's goals\n{goal_lines}")

        # Communication preferences
        pref_lines: List[str] = []
        pref_map = {
            "tone": "Tone",
            "verbosity": "Verbosity",
            "format": "Response format",
            "expertise_level": "Expertise level",
        }
        for key, label in pref_map.items():
            if key in self.preferences:
                pref_lines.append(f"- **{label}:** {self.preferences[key]}")
        # Any other preferences
        for key, val in self.preferences.items():
            if key not in pref_map:
                pref_lines.append(f"- **{key.replace('_', ' ').title()}:** {val}")

        if pref_lines:
            sections.append(
                "### Communication preferences\n"
                + "\n".join(pref_lines)
            )

        # Do's
        if self.dos:
            do_lines = "\n".join(f"- {d}" for d in self.dos)
            sections.append(
                "### Always do (non-negotiable)\n"
                + do_lines
            )

        # Don'ts
        if self.donts:
            dont_lines = "\n".join(f"- {d}" for d in self.donts)
            sections.append(
                "### Never do (non-negotiable)\n"
                + dont_lines
            )

        if not sections:
            return ""

        header = "---\n## User Profile\n\nThis section defines the user you are working with. Always respect these rules — they take precedence over everything else."
        return header + "\n\n" + "\n\n".join(sections) + "\n\n---"

    def is_empty(self) -> bool:
        """Return True if this profile has no meaningful content."""
        return not any([
            self.name, self.email, self.role, self.organization,
            self.timezone, self.context, self.dos, self.donts,
            self.preferences, self.goals,
        ])

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        # Only pass fields that exist in the dataclass
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, s: str) -> "UserProfile":
        return cls.from_dict(json.loads(s))

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        lines = []
        if self.name:
            lines.append(f"Name:         {self.name}")
        if self.role:
            lines.append(f"Role:         {self.role}")
        if self.organization:
            lines.append(f"Organization: {self.organization}")
        if self.email:
            lines.append(f"Email:        {self.email}")
        if self.timezone:
            lines.append(f"Timezone:     {self.timezone}")
        if self.language:
            lines.append(f"Language:     {self.language}")
        if self.preferences:
            lines.append(f"Preferences:  {self.preferences}")
        if self.dos:
            lines.append("Always do:")
            for d in self.dos:
                lines.append(f"  + {d}")
        if self.donts:
            lines.append("Never do:")
            for d in self.donts:
                lines.append(f"  ✗ {d}")
        if self.context:
            lines.append(f"Context:      {textwrap.shorten(self.context, 80)}")
        if self.goals:
            lines.append("Goals:")
            for g in self.goals:
                lines.append(f"  → {g}")
        return "\n".join(lines) if lines else "(empty profile)"

    def __repr__(self) -> str:
        return f"<UserProfile name={self.name!r} role={self.role!r}>"
