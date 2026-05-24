"""
ironclaw.gateway.base
~~~~~~~~~~~~~~~~~~~~~
Platform-agnostic messaging backbone.

Every platform (Telegram, WhatsApp, iMessage…) is a *Gateway*: it normalises
incoming messages into ``InboundMessage``, passes them to the ``MessageRouter``,
and writes the reply back via ``send()``.

                ┌─────────────┐     InboundMessage     ┌──────────────┐
  Telegram ───► │ TelegramGW  │ ──────────────────────► │ MessageRouter│
  WhatsApp ───► │ WhatsAppGW  │                         │              │ ──► Orchestrator
  iMessage ───► │ iMessageGW  │ ◄────────────────────── │              │
                └─────────────┘     OutboundMessage      └──────────────┘

Platform identifiers
--------------------
Every sender is identified by a ``PlatformID``:
    ("telegram",  "123456789")    # Telegram chat_id
    ("whatsapp",  "+14155551234") # WhatsApp phone number
    ("imessage",  "+14155551234") # iMessage handle
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Platform types
# ---------------------------------------------------------------------------

class Platform(str, Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    IMESSAGE = "imessage"
    UNKNOWN  = "unknown"


@dataclass
class PlatformID:
    """Unique identity of a sender across all platforms."""
    platform: Platform
    sender_id: str          # chat_id / phone number / handle

    def __str__(self) -> str:
        return f"{self.platform.value}:{self.sender_id}"

    def __hash__(self) -> int:
        return hash((self.platform, self.sender_id))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PlatformID):
            return self.platform == other.platform and self.sender_id == other.sender_id
        return NotImplemented


# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------

@dataclass
class InboundMessage:
    """Normalised message received from any platform."""
    platform_id: PlatformID
    text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: Any = None                   # original platform payload (for debugging)
    message_id: str = ""              # platform-specific message ID
    reply_to: str | None = None       # ID of message this is a reply to
    attachments: list[str] = field(default_factory=list)  # URLs or paths

    @property
    def platform(self) -> Platform:
        return self.platform_id.platform

    @property
    def sender_id(self) -> str:
        return self.platform_id.sender_id


@dataclass
class OutboundMessage:
    """Message to be sent back to a platform."""
    platform_id: PlatformID
    text: str
    reply_to: str | None = None     # message ID to reply to
    parse_mode: str = "markdown"    # markdown | plain

    def truncate(self, max_len: int = 4096) -> "OutboundMessage":
        """Return a copy with text truncated to platform limits."""
        if len(self.text) <= max_len:
            return self
        return OutboundMessage(
            platform_id=self.platform_id,
            text=self.text[: max_len - 20] + "\n…[truncated]",
            reply_to=self.reply_to,
            parse_mode=self.parse_mode,
        )


# ---------------------------------------------------------------------------
# Gateway base class
# ---------------------------------------------------------------------------

MessageHandler = Callable[[InboundMessage], Coroutine[Any, Any, None]]


class BaseGateway(ABC):
    """
    Abstract base for all messaging platform gateways.

    Lifecycle
    ---------
    1. Attach a ``MessageHandler`` via ``set_handler()``.
    2. Call ``start()`` — begins polling / webhook listening.
    3. Call ``stop()`` to shut down gracefully.
    4. Use ``send()`` to deliver replies.

    Subclasses must implement ``start()``, ``stop()``, and ``send()``.
    """

    platform: Platform = Platform.UNKNOWN

    def __init__(self) -> None:
        self._handler: MessageHandler | None = None
        self._running = False

    def set_handler(self, handler: MessageHandler) -> None:
        """Register the async callback that processes each inbound message."""
        self._handler = handler

    async def dispatch(self, msg: InboundMessage) -> None:
        """Internal: deliver an inbound message to the registered handler."""
        if self._handler is None:
            logger.warning("[%s] No handler registered — dropping message from %s",
                           self.platform.value, msg.sender_id)
            return
        try:
            await self._handler(msg)
        except Exception:
            logger.exception("[%s] Handler raised for message from %s",
                             self.platform.value, msg.sender_id)

    @abstractmethod
    async def start(self) -> None:
        """Begin receiving messages (polling loop or webhook listener)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the gateway."""
        ...

    @abstractmethod
    async def send(self, message: OutboundMessage) -> None:
        """Deliver an outbound message to the platform."""
        ...

    async def send_typing(self, platform_id: PlatformID) -> None:
        """Optionally show a 'typing…' indicator.  Default no-op."""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} platform={self.platform.value}>"
