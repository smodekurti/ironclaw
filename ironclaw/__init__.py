"""
IronClaw — Secure-by-design agentic framework.

Quick start
-----------
::

    import asyncio
    from ironclaw import AgentBuilder

    async def main():
        agent = (
            AgentBuilder("assistant")
            .with_anthropic(model="claude-sonnet-4-6")
            .with_capabilities(["web:search", "file:read"])
            .with_web_tools()
            .build()
        )
        reply = await agent.run("What's the weather in Paris?")
        print(reply.content)

    asyncio.run(main())
"""

__version__ = "0.2.0"
__author__ = "IronClaw Contributors"

from ironclaw.builder import AgentBuilder
from ironclaw.core.agent import Agent
from ironclaw.core.context import ExecutionContext
from ironclaw.core.message import Message, Role
from ironclaw.core.orchestrator import Orchestrator
from ironclaw.exceptions import (
    CapabilityDeniedError,
    InjectionDetectedError,
    IronClawError,
    PolicyViolationError,
)
from ironclaw.memory.conversation import ConversationMemory, InMemoryConversation
from ironclaw.memory.shared import SharedStateStore
from ironclaw.security.audit import AuditLog
from ironclaw.security.guard import PromptGuard
from ironclaw.security.policy import SecurityPolicy
from ironclaw.tools.permissions import CapabilitySet
from ironclaw.tools.registry import ToolRegistry
from ironclaw.tools.sandbox import Sandbox
from ironclaw.ace.schema import AgentSpec
from ironclaw.ace.provisioner import AgentProvisioner
from ironclaw.user.profile import UserProfile
from ironclaw.user.store import UserProfileStore

__all__ = [
    "AgentBuilder",
    "Agent",
    "ExecutionContext",
    "Message",
    "Role",
    "Orchestrator",
    "IronClawError",
    "CapabilityDeniedError",
    "InjectionDetectedError",
    "PolicyViolationError",
    "ConversationMemory",
    "InMemoryConversation",
    "SharedStateStore",
    "AuditLog",
    "PromptGuard",
    "SecurityPolicy",
    "CapabilitySet",
    "ToolRegistry",
    "Sandbox",
    "AgentSpec",
    "AgentProvisioner",
    "UserProfile",
    "UserProfileStore",
]