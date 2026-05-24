"""
ironclaw.gateway.daemon
~~~~~~~~~~~~~~~~~~~~~~~~
GatewayDaemon — the persistent process that keeps all gateways running.

Inspired by OpenClaw's Pi Engine daemon pattern: a single long-lived async
task that starts every configured gateway, monitors them for crashes, and
restarts them with exponential back-off.

Usage
-----
::

    from ironclaw.gateway.daemon import GatewayDaemon
    from ironclaw.gateway.telegram import TelegramGateway
    from ironclaw.gateway.whatsapp import WhatsAppGateway

    daemon = GatewayDaemon(orchestrator=orch)
    daemon.add(TelegramGateway(token="..."))
    daemon.add(WhatsAppGateway(access_token="...", phone_number_id="...", verify_token="..."))

    # Run standalone (blocks)
    asyncio.run(daemon.run_forever())

    # Or integrate with FastAPI lifespan
    daemon.start_background()  # non-blocking
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ironclaw.gateway.base import BaseGateway
from ironclaw.gateway.router import MessageRouter
from ironclaw.gateway.session import SessionStore
from ironclaw.security.guard import PromptGuard

if TYPE_CHECKING:
    from ironclaw.core.orchestrator import Orchestrator
    from ironclaw.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_BASE_BACKOFF = 2.0
_MAX_BACKOFF = 120.0


class GatewayDaemon:
    """
    Manages the lifecycle of all registered gateways.

    Parameters
    ----------
    orchestrator : Orchestrator
        The fleet manager messages are routed to.
    router_provider : LLMProvider | None
        LLM used to decide which agent handles each message.
        If None, the first registered agent always handles.
    default_agent_id : str
        Fallback agent when routing fails.
    session_db_path : str | None
        SQLite path for persisting session state across restarts.
    rate_limit : int
        Max messages per sender per minute.
    """

    def __init__(
        self,
        orchestrator: "Orchestrator",
        router_provider: "LLMProvider | None" = None,
        default_agent_id: str = "",
        session_db_path: str | None = None,
        rate_limit: int = 20,
    ) -> None:
        self.orchestrator = orchestrator
        self._sessions = SessionStore(
            default_agent_id=default_agent_id,
            db_path=session_db_path,
        )
        self.router = MessageRouter(
            orchestrator=orchestrator,
            sessions=self._sessions,
            guard=PromptGuard(),
            router_provider=router_provider,
            default_agent_id=default_agent_id,
            rate_limit=rate_limit,
        )
        self._gateways: list[BaseGateway] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ------------------------------------------------------------------
    # Gateway management
    # ------------------------------------------------------------------

    def add(self, gateway: BaseGateway) -> "GatewayDaemon":
        """Register a gateway.  Returns self for chaining."""
        self.router.register_gateway(gateway)
        self._gateways.append(gateway)
        logger.info("Daemon: registered gateway %s", gateway)
        return self

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Start all gateways and run until interrupted."""
        self._running = True
        self._tasks = [
            asyncio.create_task(self._supervised_run(gw), name=f"gw-{gw.platform.value}")
            for gw in self._gateways
        ]
        logger.info("GatewayDaemon: started %d gateway(s)", len(self._gateways))
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    def start_background(self) -> None:
        """Start all gateways as background asyncio tasks (non-blocking)."""
        self._running = True
        for gw in self._gateways:
            task = asyncio.ensure_future(
                self._supervised_run(gw),
            )
            task.set_name(f"gw-{gw.platform.value}")
            self._tasks.append(task)
        logger.info("GatewayDaemon: started %d gateway(s) in background", len(self._gateways))

    async def shutdown(self) -> None:
        """Stop all gateways gracefully."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        for gw in self._gateways:
            try:
                await gw.stop()
            except Exception as e:
                logger.warning("Error stopping %s: %s", gw, e)
        logger.info("GatewayDaemon: all gateways stopped")

    # ------------------------------------------------------------------
    # Supervised runner (auto-restart)
    # ------------------------------------------------------------------

    async def _supervised_run(self, gw: BaseGateway) -> None:
        """
        Run a gateway with automatic restart on crash.
        Uses exponential back-off up to _MAX_BACKOFF seconds.
        """
        backoff = _BASE_BACKOFF
        while self._running:
            try:
                logger.info("[%s] Starting gateway…", gw.platform.value)
                await gw.start()
                # start() should run indefinitely for polling gateways;
                # for webhook-only gateways it returns immediately — that's fine.
                backoff = _BASE_BACKOFF   # reset after clean run
                # Webhook gateways don't loop — just park here
                while self._running and gw._running:
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                return
            except Exception as e:
                if not self._running:
                    return
                logger.error("[%s] Gateway crashed: %s. Restarting in %.0fs…",
                             gw.platform.value, e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "running": self._running,
            "gateways": [
                {
                    "platform": gw.platform.value,
                    "running": gw._running,
                }
                for gw in self._gateways
            ],
            "sessions": self._sessions.active_count(),
        }
