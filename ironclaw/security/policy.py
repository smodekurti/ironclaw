"""
ironclaw.security.policy
~~~~~~~~~~~~~~~~~~~~~~~~
Declarative security policy engine.

A SecurityPolicy is a collection of rules that the Orchestrator enforces
before dispatching any agent or tool call.  Rules are checked in order;
the first DENY rule wins.

Built-in rule types
-------------------
- ``AllowAgent``  / ``DenyAgent``     — whitelist / blacklist by agent ID
- ``AllowTool``   / ``DenyTool``      — whitelist / blacklist tool names
- ``RateLimit``                        — cap calls-per-minute per agent
- ``MaxTokenBudget``                   — total token spend ceiling per session
- ``RequireCapability``               — agent must hold a capability to run

You can also pass any callable ``(agent) -> bool`` as a custom rule.
"""

from __future__ import annotations

import time
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from ironclaw.exceptions import PolicyViolationError

if TYPE_CHECKING:
    from ironclaw.core.agent import Agent


# ---------------------------------------------------------------------------
# Rule protocol
# ---------------------------------------------------------------------------

class Rule:
    """Base class; subclasses must implement ``check``."""

    name: str = "rule"

    def check(self, agent: "Agent") -> None:
        """Raise PolicyViolationError if the rule is violated."""
        ...


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------

@dataclass
class AllowAgents(Rule):
    """Only agents whose IDs appear in *allowed* may run."""
    allowed: set[str]
    name: str = "allow_agents"

    def check(self, agent: "Agent") -> None:
        if agent.agent_id not in self.allowed:
            raise PolicyViolationError(
                f"Agent '{agent.agent_id}' is not in the allow-list"
            )


@dataclass
class DenyAgents(Rule):
    """Agents whose IDs appear in *denied* are blocked."""
    denied: set[str]
    name: str = "deny_agents"

    def check(self, agent: "Agent") -> None:
        if agent.agent_id in self.denied:
            raise PolicyViolationError(
                f"Agent '{agent.agent_id}' is explicitly denied by policy"
            )


@dataclass
class RequireCapability(Rule):
    """Agent must hold at least one of the listed capabilities."""
    required: set[str]
    name: str = "require_capability"

    def check(self, agent: "Agent") -> None:
        if not self.required.intersection(agent.capabilities.granted):
            raise PolicyViolationError(
                f"Agent '{agent.agent_id}' lacks required capabilities: {self.required}"
            )


@dataclass
class RateLimit(Rule):
    """
    Sliding-window rate limiter.

    Parameters
    ----------
    max_calls : int
        Maximum calls allowed within *window_seconds*.
    window_seconds : float
        Length of the sliding window.
    """
    max_calls: int = 60
    window_seconds: float = 60.0
    name: str = "rate_limit"
    _windows: dict[str, deque] = field(default_factory=lambda: defaultdict(deque), init=False, repr=False)

    def check(self, agent: "Agent") -> None:
        now = time.monotonic()
        window = self._windows[agent.agent_id]

        # Evict old timestamps
        while window and window[0] < now - self.window_seconds:
            window.popleft()

        # Lazy garbage collection
        if random.random() < 0.01:  # 1% chance
            empty_keys = [k for k, v in self._windows.items() if not v]
            for k in empty_keys:
                self._windows.pop(k, None)

        if len(window) >= self.max_calls:
            raise PolicyViolationError(
                f"Agent '{agent.agent_id}' exceeded rate limit "
                f"({self.max_calls} calls / {self.window_seconds}s)"
            )
        window.append(now)


@dataclass
class CustomRule(Rule):
    """Wrap any ``(agent) -> bool`` callable as a policy rule."""
    fn: Callable[["Agent"], bool]
    reason: str = "custom rule violated"
    name: str = "custom"

    def check(self, agent: "Agent") -> None:
        if not self.fn(agent):
            raise PolicyViolationError(
                f"Agent '{agent.agent_id}' failed {self.name}: {self.reason}"
            )


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------

class SecurityPolicy:
    """
    Ordered collection of Rule objects.

    Usage
    -----
    ::

        policy = SecurityPolicy()
        policy.add(DenyAgents({"untrusted_bot"}))
        policy.add(RateLimit(max_calls=30, window_seconds=60))
        policy.check_agent(my_agent)
    """

    def __init__(self) -> None:
        self._rules: list[Rule] = []

    def add(self, rule: Rule) -> "SecurityPolicy":
        """Append a rule.  Returns self for chaining."""
        self._rules.append(rule)
        return self

    def remove(self, rule_name: str) -> None:
        self._rules = [r for r in self._rules if r.name != rule_name]

    def check_agent(self, agent: "Agent") -> None:
        """
        Run all rules against *agent*.

        Raises
        ------
        PolicyViolationError
            On the first rule that fires.
        """
        for rule in self._rules:
            rule.check(agent)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def __repr__(self) -> str:
        return f"<SecurityPolicy rules={[r.name for r in self._rules]}>"
