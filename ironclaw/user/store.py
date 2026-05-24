"""
ironclaw.user.store
~~~~~~~~~~~~~~~~~~~
UserProfileStore — persists a UserProfile to disk so it survives restarts
and is automatically shared across all agents.

Default storage: ``~/.ironclaw/user_profile.json``

The store is intentionally simple — one profile per installation.  If you
need per-user profiles (multi-tenant), pass a custom ``path`` that includes
a user identifier.

Usage
-----
::

    from ironclaw.user.store import UserProfileStore

    store = UserProfileStore()

    # Save
    store.save(profile)

    # Load (returns empty profile if file doesn't exist)
    profile = store.load()

    # Update individual fields without overwriting others
    store.update(dos=["Always be concise"], preferences={"tone": "direct"})
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any, Dict, List, Optional

from ironclaw.user.profile import UserProfile

_DEFAULT_PATH = pathlib.Path.home() / ".ironclaw" / "user_profile.json"


class UserProfileStore:
    """
    Persists a UserProfile to a JSON file.

    Parameters
    ----------
    path:
        Path to the JSON file.  Defaults to ``~/.ironclaw/user_profile.json``.
    """

    def __init__(self, path: str | pathlib.Path | None = None) -> None:
        self.path = pathlib.Path(path) if path else _DEFAULT_PATH

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def load(self) -> UserProfile:
        """
        Load the profile from disk.

        Returns an empty ``UserProfile`` if the file does not exist.
        """
        if not self.path.exists():
            return UserProfile()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return UserProfile.from_dict(data)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Could not load user profile from %s: %s — using empty profile",
                self.path, exc,
            )
            return UserProfile()

    def save(self, profile: UserProfile) -> None:
        """Persist the profile to disk, creating parent directories as needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(profile.to_json(), encoding="utf-8")

    def exists(self) -> bool:
        return self.path.exists()

    def clear(self) -> None:
        """Delete the stored profile."""
        if self.path.exists():
            self.path.unlink()

    # ------------------------------------------------------------------
    # Partial update
    # ------------------------------------------------------------------

    def update(self, **fields: Any) -> UserProfile:
        """
        Update individual fields without overwriting the rest of the profile.

        Example::

            store.update(
                name="Alex",
                dos=["Always cite sources"],
                preferences={"tone": "direct"},
            )

        For list fields (dos, donts, goals), the new list **replaces** the old one.
        For dict fields (preferences), the new dict is **merged** into the existing one.
        """
        profile = self.load()

        import dataclasses
        valid = {f.name for f in dataclasses.fields(UserProfile)}

        for key, value in fields.items():
            if key not in valid:
                raise ValueError(f"Unknown UserProfile field: {key!r}")
            existing = getattr(profile, key)
            if isinstance(existing, dict) and isinstance(value, dict):
                # Merge dicts
                merged = {**existing, **value}
                object.__setattr__(profile, key, merged)
            else:
                setattr(profile, key, value)

        self.save(profile)
        return profile

    def add_do(self, rule: str) -> UserProfile:
        """Append a single 'always do' rule."""
        profile = self.load()
        if rule not in profile.dos:
            profile.dos.append(rule)
        self.save(profile)
        return profile

    def add_dont(self, rule: str) -> UserProfile:
        """Append a single 'never do' rule."""
        profile = self.load()
        if rule not in profile.donts:
            profile.donts.append(rule)
        self.save(profile)
        return profile

    def remove_do(self, rule: str) -> UserProfile:
        profile = self.load()
        profile.dos = [d for d in profile.dos if d != rule]
        self.save(profile)
        return profile

    def remove_dont(self, rule: str) -> UserProfile:
        profile = self.load()
        profile.donts = [d for d in profile.donts if d != rule]
        self.save(profile)
        return profile

    # ------------------------------------------------------------------
    # Convenience: auto-load global profile
    # ------------------------------------------------------------------

    @classmethod
    def global_profile(cls) -> UserProfile:
        """
        Load the global user profile from the default location.

        This is the profile that AgentBuilder uses automatically when
        no explicit profile is provided.
        """
        return cls().load()
