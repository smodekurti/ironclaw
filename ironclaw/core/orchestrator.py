"""
ironclaw.core.orchestrator
~~~~~~~~~~~~~~~~~~~~~~~~~~
The Orchestrator manages a fleet of Agents.  It handles:

  - Agent registration and lookup
  - Sequential and parallel agent dispatch
  - Agent-to-agent handoffs (delegation)
  - Shared session state and a common audit log
  - Global security policy enforcement
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ironclaw.core.agent import Agent
from ironclaw.core.context import ExecutionContext
from ironclaw.core.message import Message
from ironclaw.exceptions import AgentNotFoundError, OrchestratorError
from ironclaw.memory.shared import SharedStateStore
from ironclaw.security.audit import AuditLog
from ironclaw.security.policy import SecurityPolicy

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Fleet manager for IronClaw agents.

    Usage
    -----
    ::

        orch = Orchestrator(policy=policy, audit_log=audit)
        orch.register(researcher)
        orch.register(writer)

        result = await orch.run("researcher", "Find info about X")
        result2 = await orch.run("writer", f"Summarise: {result.content}")
    """

    def __init__(
        self,
        policy: SecurityPolicy | None = None,
        audit_log: AuditLog | None = None,
        shared_state: SharedStateStore | None = None,
    ) -> None:
        self._agents: dict[str, Agent] = {}
        self.policy = policy or SecurityPolicy()
        self.audit_log = audit_log or AuditLog()
        self.shared_state = shared_state or SharedStateStore()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, agent: Agent) -> None:
        """Register an agent with the orchestrator."""
        if agent.agent_id in self._agents:
            raise OrchestratorError(f"Agent '{agent.agent_id}' is already registered")
        self._agents[agent.agent_id] = agent
        self.audit_log.record(event="agent_registered", agent_id=agent.agent_id, name=agent.name)
        logger.info("Registered agent '%s' (%s)", agent.name, agent.agent_id)

    def unregister(self, agent_id: str) -> None:
        if agent_id not in self._agents:
            raise AgentNotFoundError(agent_id)
        del self._agents[agent_id]
        self.audit_log.record(event="agent_unregistered", agent_id=agent_id)

    def get_agent(self, agent_id: str) -> Agent:
        if agent_id not in self._agents:
            raise AgentNotFoundError(agent_id)
        return self._agents[agent_id]

    @property
    def agent_ids(self) -> list[str]:
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(
        self,
        agent_id: str,
        user_input: str,
        session_id: str | None = None,
    ) -> Message:
        """
        Run a single agent and return its reply.

        The orchestrator creates (or reuses) an ExecutionContext that wires
        in the shared state store and audit log before dispatching to the agent.
        """
        agent = self.get_agent(agent_id)

        # Policy gate — check if this agent is allowed to run
        self.policy.check_agent(agent)

        ctx = self._make_context(agent_id, session_id)
        ctx.record("orchestrator_dispatch", target_agent=agent_id, input_length=len(user_input))

        return await agent.run(user_input, context=ctx)

    async def run_parallel(
        self,
        tasks: list[tuple[str, str]],
        session_id: str | None = None,
    ) -> list[Message]:
        """
        Dispatch multiple (agent_id, input) pairs in parallel.

        Returns results in the same order as *tasks*.
        """
        coroutines = [
            self.run(agent_id, user_input, session_id)
            for agent_id, user_input in tasks
        ]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        messages: list[Message] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                agent_id = tasks[i][0]
                logger.error("Agent '%s' raised during parallel run: %s", agent_id, res)
                self.audit_log.record(
                    event="parallel_agent_error",
                    agent_id=agent_id,
                    error=str(res),
                )
                messages.append(
                    Message.assistant(
                        f"[Error from agent '{agent_id}': {res}]",
                        agent_id=agent_id,
                    )
                )
            else:
                messages.append(res)  # type: ignore[arg-type]
        return messages

    async def handoff(
        self,
        from_agent_id: str,
        to_agent_id: str,
        content: str,
        session_id: str | None = None,
    ) -> Message:
        """
        Delegate work from one agent to another.

        Records a HANDOFF message in the audit trail before dispatching.
        """
        if from_agent_id not in self._agents:
            raise AgentNotFoundError(from_agent_id)
        if to_agent_id not in self._agents:
            raise AgentNotFoundError(to_agent_id)

        handoff_msg = Message.handoff(content, from_agent=from_agent_id, to_agent=to_agent_id)
        self.audit_log.record(
            event="agent_handoff",
            from_agent=from_agent_id,
            to_agent=to_agent_id,
            content_length=len(content),
        )
        logger.info("Handoff: %s → %s", from_agent_id, to_agent_id)

        return await self.run(to_agent_id, content, session_id)

    async def pipeline(
        self,
        steps: list[tuple[str, str | None]],
        initial_input: str,
        session_id: str | None = None,
    ) -> list[Message]:
        """
        Run agents as a sequential pipeline where each agent's output feeds
        the next.

        Parameters
        ----------
        steps : list of (agent_id, optional_prompt_template)
            If prompt_template is None, the previous agent's reply is passed
            verbatim.  Use ``{input}`` and ``{previous}`` as placeholders.
        initial_input : str
            Input for the first agent.

        Returns
        -------
        list[Message]
            All replies in order.
        """
        results: list[Message] = []
        current_input = initial_input

        for agent_id, template in steps:
            if template:
                current_input = template.format(
                    input=initial_input,
                    previous=current_input,
                )
            reply = await self.run(agent_id, current_input, session_id)
            results.append(reply)
            current_input = reply.content

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_context(self, agent_id: str, session_id: str | None) -> ExecutionContext:
        agent = self._agents[agent_id]
        return ExecutionContext(
            session_id=session_id or "",
            agent_id=agent_id,
            conversation=agent.memory,
            shared_state=self.shared_state,
            audit_log=self.audit_log,
            capabilities=agent.capabilities,
        )

    def summary(self) -> dict[str, Any]:
        """Return a human-readable summary of the registered fleet."""
        return {
            "agent_count": len(self._agents),
            "agents": [
                {
                    "id": a.agent_id,
                    "name": a.name,
                    "capabilities": list(a.capabilities.granted),
                }
                for a in self._agents.values()
            ],
        }
