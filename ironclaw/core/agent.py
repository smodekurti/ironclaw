"""
ironclaw.core.agent
~~~~~~~~~~~~~~~~~~~
Base Agent class.  An agent owns:
  - an identity (id + name + system prompt)
  - a set of Capabilities (what tools it may call)
  - a reference to an LLM Provider
  - a reference to ConversationMemory
  - a reference to an ExecutionContext (wired in at run-time)

The agent loop:
  1. Receive user message → run prompt-injection guard
  2. Append to conversation memory
  3. Call LLM with full message history + tool schemas
  4. If LLM returns tool calls → validate capabilities → sandbox-execute each tool
  5. Append tool results, loop back to step 3
  6. Return final assistant message
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, AsyncIterator

from ironclaw.core.context import ExecutionContext
from ironclaw.core.message import Message, Role, ToolCall, ToolResult
from ironclaw.exceptions import (
    CapabilityDeniedError,
    InjectionDetectedError,
    IronClawError,
)

if TYPE_CHECKING:
    from ironclaw.memory.conversation import ConversationMemory
    from ironclaw.providers.base import LLMProvider
    from ironclaw.security.guard import PromptGuard
    from ironclaw.tools.permissions import CapabilitySet
    from ironclaw.tools.registry import ToolRegistry
    from ironclaw.tools.sandbox import Sandbox

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10  # hard limit to prevent infinite agent loops


class Agent:
    """
    Core autonomous agent.

    Parameters
    ----------
    agent_id : str
        Unique identifier.  Used in audit trails and handoff routing.
    name : str
        Human-readable label.
    system_prompt : str
        The agent's persona / instruction set.
    provider : LLMProvider
        Which LLM backs this agent.
    tools : ToolRegistry
        Registry of callable tools.
    capabilities : CapabilitySet
        Which tools this agent is *allowed* to call.
    memory : ConversationMemory
        Per-agent conversation history.
    guard : PromptGuard
        Prompt-injection detector — applied to every incoming message.
    sandbox : Sandbox
        Execution sandbox for tool calls.
    max_iterations : int
        Max tool-call rounds before aborting (DoS / loop guard).
    """

    def __init__(
        self,
        agent_id: str,
        name: str,
        system_prompt: str,
        provider: "LLMProvider",
        tools: "ToolRegistry",
        capabilities: "CapabilitySet",
        memory: "ConversationMemory",
        guard: "PromptGuard",
        sandbox: "Sandbox",
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> None:
        self.agent_id = agent_id
        self.name = name
        self.system_prompt = system_prompt
        self.provider = provider
        self.tools = tools
        self.capabilities = capabilities
        self.memory = memory
        self.guard = guard
        self.sandbox = sandbox
        self.max_iterations = max_iterations
        self._context: ExecutionContext | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        user_input: str,
        context: ExecutionContext | None = None,
    ) -> Message:
        """
        Process a user message end-to-end and return the assistant's reply.

        Raises
        ------
        InjectionDetectedError
            If the prompt guard blocks the incoming message.
        CapabilityDeniedError
            If the LLM requests a tool the agent is not permitted to use.
        """
        ctx = context or ExecutionContext(agent_id=self.agent_id)
        self._context = ctx

        # --- 1. Guard incoming message ----------------------------------
        user_msg = Message.user(user_input)
        scan = self.guard.scan(user_msg)
        user_msg.injection_score = scan.score
        user_msg.flagged = scan.blocked

        ctx.record("message_received", role="user", flagged=scan.blocked, score=scan.score)

        if scan.blocked:
            ctx.record("injection_blocked", reason=scan.reason)
            raise InjectionDetectedError(
                f"Message blocked by prompt guard: {scan.reason} (score={scan.score:.2f})"
            )

        # --- 2. Append to memory ----------------------------------------
        self.memory.append(user_msg)

        # --- 3. Agent loop ----------------------------------------------
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            messages = self._build_messages()
            tool_schemas = self.tools.schemas_for(self.capabilities)

            ctx.record("llm_call", iteration=iteration, num_messages=len(messages))
            llm_response = await self.provider.complete(messages, tools=tool_schemas)

            # No tool calls → we're done
            if not llm_response.tool_calls:
                reply = Message.assistant(llm_response.content, agent_id=self.agent_id)
                self.memory.append(reply)
                ctx.record("agent_reply", content_length=len(llm_response.content))
                return reply

            # --- 4. Process tool calls ----------------------------------
            tool_results: list[ToolResult] = []
            for tc in llm_response.tool_calls:
                result = await self._execute_tool(tc, ctx)
                tool_results.append(result)

            # Append assistant turn with tool calls + results
            assistant_msg = Message(
                role=Role.TOOL_CALL,
                content=llm_response.content or "",
                agent_id=self.agent_id,
                tool_calls=llm_response.tool_calls,
                tool_results=tool_results,
            )
            self.memory.append(assistant_msg)

        # Exceeded iteration limit
        logger.warning(
            "Agent %s hit max_iterations=%d without a final reply",
            self.agent_id,
            self.max_iterations,
        )
        ctx.record("max_iterations_exceeded", max=self.max_iterations)
        abort_msg = Message.assistant(
            "[Agent stopped: exceeded maximum tool-call iterations]",
            agent_id=self.agent_id,
        )
        self.memory.append(abort_msg)
        return abort_msg

    async def stream(
        self,
        user_input: str,
        context: ExecutionContext | None = None,
    ) -> AsyncIterator[str]:
        """
        Streaming variant — yields text chunks as the LLM produces them.
        Tool calls are executed silently; only the final text is streamed.
        """
        reply = await self.run(user_input, context)
        for chunk in reply.content.split(" "):
            yield chunk + " "
            await asyncio.sleep(0)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, tc: ToolCall, ctx: ExecutionContext
    ) -> ToolResult:
        """Validate capability then sandbox-execute the tool."""
        # Capability check — hard gate
        if not self.capabilities.allows(tc.tool_name):
            ctx.record(
                "capability_denied",
                tool=tc.tool_name,
                agent=self.agent_id,
            )
            raise CapabilityDeniedError(
                f"Agent '{self.agent_id}' does not have capability for tool '{tc.tool_name}'"
            )

        tool = self.tools.get(tc.tool_name)
        if tool is None:
            return ToolResult(
                call_id=tc.call_id,
                tool_name=tc.tool_name,
                output=None,
                error=f"Tool '{tc.tool_name}' not found in registry",
            )

        ctx.record("tool_call_start", tool=tc.tool_name, args=tc.arguments)
        t0 = time.monotonic()

        try:
            output = await self.sandbox.execute(tool, tc.arguments)
            duration_ms = (time.monotonic() - t0) * 1000
            ctx.record(
                "tool_call_success",
                tool=tc.tool_name,
                duration_ms=duration_ms,
            )
            return ToolResult(
                call_id=tc.call_id,
                tool_name=tc.tool_name,
                output=output,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            ctx.record(
                "tool_call_error",
                tool=tc.tool_name,
                error=str(exc),
                duration_ms=duration_ms,
            )
            return ToolResult(
                call_id=tc.call_id,
                tool_name=tc.tool_name,
                output=None,
                error=str(exc),
                duration_ms=duration_ms,
            )

    def _build_messages(self) -> list[dict[str, Any]]:
        """Serialise conversation history for the LLM provider."""
        msgs: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        for msg in self.memory.history():
            if msg.role == Role.SYSTEM:
                continue  # already added above
            elif msg.role in (Role.USER, Role.ASSISTANT):
                msgs.append({"role": msg.role.value, "content": msg.content})
            elif msg.role == Role.TOOL_CALL:
                # Reconstruct tool-call + results in the provider's wire format
                msgs.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                        "tool_calls": [
                            {
                                "id": tc.call_id,
                                "type": "function",
                                "function": {
                                    "name": tc.tool_name,
                                    "arguments": tc.arguments,
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
                for tr in msg.tool_results:
                    msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.call_id,
                            "content": str(tr.output) if tr.error is None else f"ERROR: {tr.error}",
                        }
                    )
        return msgs

    def __repr__(self) -> str:
        return f"<Agent id={self.agent_id!r} name={self.name!r}>"
