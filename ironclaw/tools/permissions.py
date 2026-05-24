"""
ironclaw.tools.permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~
Capability-based access control for tools.

A CapabilitySet is a frozenset-like object that records which tool names an
agent is *allowed* to invoke.  Capabilities follow the principle of least
privilege: an agent starts with an empty set and is granted only what it
explicitly needs.

Capabilities can be:
  - fine-grained   : ``"web_search"``
  - namespace-scoped: ``"web:*"`` grants all tools in the ``web`` namespace
  - wildcard        : ``"*"`` grants everything (use sparingly — only for
                      fully-trusted orchestrator agents)

The ToolRegistry uses CapabilitySet.allows() to gate every tool call.
"""

from __future__ import annotations

import fnmatch
from typing import Iterable


class CapabilitySet:
    """
    Immutable set of capability strings with wildcard matching.

    Parameters
    ----------
    grants : Iterable[str]
        Initial capability strings.

    Examples
    --------
    ::

        caps = CapabilitySet(["web_search", "file:read"])
        caps.allows("web_search")    # True
        caps.allows("file:read")     # True
        caps.allows("file:write")    # False

        # Namespace wildcard
        caps2 = CapabilitySet(["file:*"])
        caps2.allows("file:read")    # True
        caps2.allows("file:write")   # True
        caps2.allows("web_search")   # False

        # Unrestricted (dangerous)
        caps3 = CapabilitySet(["*"])
        caps3.allows("anything")     # True
    """

    def __init__(self, grants: Iterable[str] = ()) -> None:
        self._grants: frozenset[str] = frozenset(grants)

    @property
    def granted(self) -> frozenset[str]:
        return self._grants

    def allows(self, tool_name: str) -> bool:
        """Return True if *tool_name* is covered by any granted capability."""
        for cap in self._grants:
            if cap == "*":
                return True
            if fnmatch.fnmatch(tool_name, cap):
                return True
        return False

    def grant(self, *capabilities: str) -> "CapabilitySet":
        """Return a new CapabilitySet with additional capabilities added."""
        return CapabilitySet(self._grants | frozenset(capabilities))

    def revoke(self, *capabilities: str) -> "CapabilitySet":
        """Return a new CapabilitySet with the listed capabilities removed."""
        return CapabilitySet(self._grants - frozenset(capabilities))

    def union(self, other: "CapabilitySet") -> "CapabilitySet":
        return CapabilitySet(self._grants | other._grants)

    def intersection(self, other: "CapabilitySet") -> "CapabilitySet":
        return CapabilitySet(self._grants & other._grants)

    def is_empty(self) -> bool:
        return len(self._grants) == 0

    def __contains__(self, item: str) -> bool:
        return self.allows(item)

    def __repr__(self) -> str:
        return f"CapabilitySet({sorted(self._grants)})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CapabilitySet):
            return self._grants == other._grants
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._grants)


# ---------------------------------------------------------------------------
# Pre-defined profiles
# ---------------------------------------------------------------------------

READONLY_CAPS = CapabilitySet(["file:read", "web:fetch", "web:search"])
READWRITE_CAPS = CapabilitySet(["file:read", "file:write", "web:fetch", "web:search"])
SHELL_CAPS = CapabilitySet(["shell:execute"])
FULL_CAPS = CapabilitySet(["*"])
EMPTY_CAPS = CapabilitySet()
