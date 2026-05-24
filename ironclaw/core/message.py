"""
ironclaw.core.message
~~~~~~~~~~~~~~~~~~~~~
Typed message protocol. Every piece of communication inside IronClaw —
between user, agent, tool, and LLM — is expressed as a Message.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"       # agent requesting a tool
    TOOL_RESULT = "tool_result"   # tool response back to agent
    HANDOFF = "handoff"           # agent-to-agent delegation


@dataclass
class ToolCall:
    """Represents a single tool invocation requested by an agent."""
    tool_name: str
    arguments: dict[str, Any]
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ToolResult:
    """Result returned from a tool execution."""
    call_id: str
    tool_name: str
    output: Any
    error: str | None = None
    duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class Message:
    """
    Core unit of communication.  Every interaction is recorded as a Message
    and appended to the ConversationMemory for full traceability.
    """
    role: Role
    content: str
    agent_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Security annotations set by the prompt guard
    injection_score: float = 0.0   # 0.0 = clean, 1.0 = definite injection
    flagged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role.value,
            "content": self.content,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "tool_calls": [
                {"call_id": tc.call_id, "tool_name": tc.tool_name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ],
            "tool_results": [
                {
                    "call_id": tr.call_id,
                    "tool_name": tr.tool_name,
                    "output": tr.output,
                    "error": tr.error,
                    "duration_ms": tr.duration_ms,
                }
                for tr in self.tool_results
            ],
            "metadata": self.metadata,
            "injection_score": self.injection_score,
            "flagged": self.flagged,
        }

    @classmethod
    def system(cls, content: str, agent_id: str = "") -> "Message":
        return cls(role=Role.SYSTEM, content=content, agent_id=agent_id)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str, agent_id: str = "") -> "Message":
        return cls(role=Role.ASSISTANT, content=content, agent_id=agent_id)

    @classmethod
    def handoff(cls, content: str, from_agent: str, to_agent: str) -> "Message":
        return cls(
            role=Role.HANDOFF,
            content=content,
            agent_id=from_agent,
            metadata={"to_agent": to_agent},
        )
