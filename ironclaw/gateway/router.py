"""
ironclaw.gateway.router
~~~~~~~~~~~~~~~~~~~~~~~
Orchestrator-based message router.

The MessageRouter is the central hub that:

  1. Receives an ``InboundMessage`` from any gateway.
  2. Looks up (or creates) a ``GatewaySession`` for the sender.
  3. Checks for slash commands (``/agent <id>``, ``/agents``, ``/help``).
  4. If the session has no assigned agent OR the message looks like a
     topic-switch, runs the *LLM router* to pick the best agent.
  5. Dispatches to the selected IronClaw agent via the Orchestrator.
  6. Formats the reply and calls the originating gateway's ``send()``.
  7. Applies security: the PromptGuard runs on the raw inbound text before
     anything reaches an agent.

LLM router
----------
The router uses a lightweight LLM call with a compact system prompt:
  "Given these agents: [...], which one should handle: '<text>'?
   Reply with ONLY the agent_id."
It falls back to the first registered agent if the LLM is unavailable or
returns an unrecognised ID.

Rate limiting
-------------
Configurable per-sender rate limit (default: 20 messages / minute).
Senders that exceed the limit receive a polite refusal without hitting
any LLM.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

from ironclaw.core.context import ExecutionContext
from ironclaw.exceptions import InjectionDetectedError, IronClawError
from ironclaw.gateway.base import BaseGateway, InboundMessage, OutboundMessage, Platform, PlatformID
from ironclaw.gateway.session import GatewaySession, SessionStore
from ironclaw.security.guard import PromptGuard

if TYPE_CHECKING:
    from ironclaw.core.orchestrator import Orchestrator
    from ironclaw.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_ROUTER_SYSTEM = (
    "You are an intelligent message router for a fleet of AI agents. "
    "Given the user's message, output ONLY the agent_id (snake_case, no quotes) "
    "of the most suitable agent. If none is clearly better, output the first one."
)

_HELP_TEXT = (
    "🦾 *IronClaw Agent Gateway*\n\n"
    "Commands:\n"
    "  `/agents` — list available agents\n"
    "  `/agent <id>` — switch to a specific agent\n"
    "  `/clear` — clear your conversation history\n"
    "  `/help` — show this message\n\n"
    "Just type normally to chat with the current agent."
)


class MessageRouter:
    """
    Routes inbound messages from any gateway to the right IronClaw agent.

    Parameters
    ----------
    orchestrator : Orchestrator
        The fleet manager to dispatch to.
    sessions : SessionStore
        Per-sender session state.
    guard : PromptGuard
        Security pre-filter applied to every message.
    router_provider : LLMProvider | None
        LLM used to select the target agent.  If None, always uses the
        first registered agent (or the default).
    default_agent_id : str
        Fallback agent if routing fails.
    rate_limit : int
        Max messages per sender per ``rate_window`` seconds.
    rate_window : float
        Window length for rate limiting in seconds.
    """

    def __init__(
        self,
        orchestrator: "Orchestrator",
        sessions: SessionStore,
        guard: PromptGuard | None = None,
        router_provider: "LLMProvider | None" = None,
        default_agent_id: str = "",
        rate_limit: int = 20,
        rate_window: float = 60.0,
    ) -> None:
        self.orchestrator = orchestrator
        self.sessions = sessions
        self.guard = guard or PromptGuard()
        self.router_provider = router_provider
        self.default_agent_id = default_agent_id
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self._gateways: dict[Platform, BaseGateway] = {}
        self._rate_windows: dict[str, deque] = defaultdict(deque)

    # ------------------------------------------------------------------
    # Gateway registration
    # ------------------------------------------------------------------

    def register_gateway(self, gw: BaseGateway) -> None:
        """Register a gateway so the router can send replies back via it."""
        self._gateways[gw.platform] = gw
        gw.set_handler(self.handle)
        logger.info("Gateway registered: %s", gw.platform.value)

    # ------------------------------------------------------------------
    # Core message handler
    # ------------------------------------------------------------------

    async def handle(self, msg: InboundMessage) -> None:
        """
        Entry point called by every gateway for each inbound message.
        """
        sender_key = str(msg.platform_id)

        # 1. Rate limit
        if not self._check_rate(sender_key):
            await self._reply(msg.platform_id, "⏳ Too many messages. Please slow down.")
            return

        # 2. Slash commands
        if msg.text.startswith("/"):
            await self._handle_command(msg)
            return

        # 3. Prompt injection guard
        from ironclaw.core.message import Message as IronMsg
        iron_msg = IronMsg.user(msg.text)
        scan = self.guard.scan(iron_msg)
        if scan.blocked:
            logger.warning("Injection blocked from %s (score=%.2f)", sender_key, scan.score)
            await self._reply(
                msg.platform_id,
                "🚫 Your message was blocked by the security filter."
            )
            return

        # 4. Session & agent selection
        session = self.sessions.get_or_create(msg.platform_id)
        session.touch()

        if not session.agent_id or session.agent_id not in self.orchestrator.agent_ids:
            session.agent_id = await self._route(msg.text)
            self.sessions.update_agent(msg.platform_id, session.agent_id)

        # 5. Typing indicator
        gw = self._gateways.get(msg.platform_id.platform)
        if gw:
            asyncio.create_task(gw.send_typing(msg.platform_id))

        # 6. Dispatch to agent
        try:
            ctx = ExecutionContext(
                session_id=str(msg.platform_id),
                agent_id=session.agent_id,
                conversation=session.memory,
            )
            reply = await self.orchestrator.run(
                session.agent_id,
                msg.text,
                session_id=ctx.session_id,
            )
            await self._reply(msg.platform_id, reply.content, reply_to=msg.message_id)

        except InjectionDetectedError:
            await self._reply(msg.platform_id, "🚫 Message blocked by security filter.")
        except IronClawError as e:
            logger.error("IronClaw error for %s: %s", sender_key, e)
            await self._reply(msg.platform_id, f"⚠️ Error: {e}")
        except Exception:
            logger.exception("Unexpected error for %s", sender_key)
            await self._reply(msg.platform_id, "⚠️ An unexpected error occurred.")

    # ------------------------------------------------------------------
    # Slash command handler
    # ------------------------------------------------------------------

    async def _handle_command(self, msg: InboundMessage) -> None:
        parts = msg.text.strip().split()
        cmd = parts[0].lower()

        if cmd in ("/help", "/start"):
            await self._reply(msg.platform_id, _HELP_TEXT)

        elif cmd == "/agents":
            ids = self.orchestrator.agent_ids
            if not ids:
                await self._reply(msg.platform_id, "No agents registered.")
            else:
                lines = ["🤖 *Available agents:*"]
                for aid in ids:
                    a = self.orchestrator.get_agent(aid)
                    lines.append(f"  • `{aid}` — {a.name}")
                await self._reply(msg.platform_id, "\n".join(lines))

        elif cmd == "/agent":
            if len(parts) < 2:
                await self._reply(msg.platform_id, "Usage: `/agent <agent_id>`")
            else:
                target = parts[1]
                if target not in self.orchestrator.agent_ids:
                    await self._reply(msg.platform_id, f"❌ Agent `{target}` not found.")
                else:
                    self.sessions.update_agent(msg.platform_id, target)
                    agent = self.orchestrator.get_agent(target)
                    await self._reply(msg.platform_id, f"✅ Switched to *{agent.name}*")

        elif cmd == "/clear":
            session = self.sessions.get(msg.platform_id)
            if session:
                session.memory.clear()
                # Reset agent assignment so router picks fresh
                session.agent_id = ""
            await self._reply(msg.platform_id, "🧹 Conversation cleared.")

        else:
            await self._reply(msg.platform_id, f"Unknown command: `{cmd}`. Type `/help` for help.")

    # ------------------------------------------------------------------
    # LLM-based routing
    # ------------------------------------------------------------------

    async def _route(self, text: str) -> str:
        """Return the best agent_id for the given text."""
        agent_ids = self.orchestrator.agent_ids
        if not agent_ids:
            return self.default_agent_id

        if len(agent_ids) == 1:
            return agent_ids[0]

        # Use default if no router provider configured
        if not self.router_provider:
            return self.default_agent_id or agent_ids[0]

        agent_summaries = []
        for aid in agent_ids:
            a = self.orchestrator.get_agent(aid)
            caps = ", ".join(sorted(a.capabilities.granted)[:4])
            agent_summaries.append(f"  {aid}: {a.name} (caps: {caps or 'none'})")

        prompt = (
            f"Agents:\n" + "\n".join(agent_summaries) +
            f"\n\nUser message: \"{text[:300]}\"\n\n"
            "Reply with ONLY the agent_id."
        )

        try:
            resp = await self.router_provider.complete(
                [
                    {"role": "system", "content": _ROUTER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                tools=[],
                max_tokens=20,
                temperature=0.0,
            )
            chosen = resp.content.strip().lower()
            # Accept only valid agent IDs
            chosen = re.sub(r"[^a-z0-9_\-]", "", chosen)
            if chosen in agent_ids:
                logger.info("Router selected agent '%s' for: %s", chosen, text[:60])
                return chosen
        except Exception as exc:
            logger.warning("Router LLM failed (%s), using default", exc)

        return self.default_agent_id or agent_ids[0]

    # ------------------------------------------------------------------
    # Reply helper
    # ------------------------------------------------------------------

    async def _reply(
        self,
        platform_id: PlatformID,
        text: str,
        reply_to: str | None = None,
    ) -> None:
        gw = self._gateways.get(platform_id.platform)
        if not gw:
            logger.warning("No gateway for platform %s", platform_id.platform.value)
            return
        out = OutboundMessage(
            platform_id=platform_id,
            text=text,
            reply_to=reply_to,
        )
        await gw.send(out)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate(self, sender_key: str) -> bool:
        now = time.monotonic()
        window = self._rate_windows[sender_key]
        while window and window[0] < now - self.rate_window:
            window.popleft()
        if len(window) >= self.rate_limit:
            return False
        window.append(now)
        return True
