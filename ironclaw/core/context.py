"""
ironclaw.core.context
~~~~~~~~~~~~~~~~~~~~~
ExecutionContext carries all per-run state: which agent is running, which
session it belongs to, live capability grants, and references to the shared
memory and audit log.  Passing context explicitly (rather than relying on
globals) makes every decision traceable and testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ironclaw.memory.conversation import ConversationMemory
    from ironclaw.memory.shared import SharedStateStore
    from ironclaw.security.audit import AuditLog
    from ironclaw.tools.permissions import CapabilitySet


@dataclass
class ExecutionContext:
    """
    Immutable-ish snapshot of everything an agent needs for one turn.
    Create a fresh context per session; pass it down to every subsystem.
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Injected by the Orchestrator — may be None when running standalone
    conversation: "ConversationMemory | None" = None
    shared_state: "SharedStateStore | None" = None
    audit_log: "AuditLog | None" = None
    capabilities: "CapabilitySet | None" = None

    # Arbitrary key/value bag for extensions
    extra: dict[str, Any] = field(default_factory=dict)

    # --- helpers ---------------------------------------------------------

    def fork(self, new_agent_id: str) -> "ExecutionContext":
        """Create a child context for a sub-agent, sharing session & stores."""
        return ExecutionContext(
            session_id=self.session_id,
            agent_id=new_agent_id,
            conversation=self.conversation,
            shared_state=self.shared_state,
            audit_log=self.audit_log,
            capabilities=self.capabilities,
            extra=dict(self.extra),
        )

    def record(self, event: str, **kwargs: Any) -> None:
        """Convenience: write to the audit log (no-op if not wired up)."""
        if self.audit_log:
            self.audit_log.record(
                event=event,
                session_id=self.session_id,
                agent_id=self.agent_id,
                **kwargs,
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        if self.shared_state:
            return self.shared_state.get(key, default)
        return default

    def set_state(self, key: str, value: Any) -> None:
        if self.shared_state:
            self.shared_state.set(key, value)
