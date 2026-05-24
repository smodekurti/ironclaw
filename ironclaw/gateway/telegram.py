"""
ironclaw.gateway.telegram
~~~~~~~~~~~~~~~~~~~~~~~~~
Telegram Bot API gateway.

Supports two modes:
  - **Polling** (default): calls getUpdates in a long-poll loop. No
    public URL required — ideal for development and local deployments.
  - **Webhook**: registers a public HTTPS URL with Telegram and receives
    updates as POST requests.  Requires the FastAPI web server running
    behind a TLS reverse proxy (e.g. ngrok, Caddy, nginx).

Setup
-----
1. Create a bot via @BotFather on Telegram → get the token.
2. Set the token as ``IRONCLAW_TELEGRAM_TOKEN`` env var or pass directly.
3. Start in polling mode (no further config needed), or set a webhook URL.

Message formatting
------------------
Replies are sent with ``parse_mode=MarkdownV2``.  All Markdown special
characters in the LLM's output are auto-escaped so the message never
fails to send.

Rate limits
-----------
Telegram allows ~30 messages/second globally and ~1 message/second per
chat.  The gateway retries on 429 with the recommended ``retry_after``
backoff.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from ironclaw.gateway.base import BaseGateway, InboundMessage, OutboundMessage, Platform, PlatformID

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}"
_POLL_TIMEOUT = 30        # long-poll timeout in seconds
_MAX_RETRIES = 5
_MDV2_SPECIAL = r"([_*\[\]()~`>#\+\-=|{}.!\\])"


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(_MDV2_SPECIAL, r"\\\1", text)


class TelegramGateway(BaseGateway):
    """
    Telegram Bot API gateway.

    Parameters
    ----------
    token : str
        Telegram Bot API token (from @BotFather).
    webhook_url : str | None
        If set, registers this URL as the webhook endpoint.
        The path ``/webhook/telegram`` is appended automatically.
    allowed_chat_ids : set[int | str] | None
        Allowlist of chat IDs.  Messages from other chats are silently
        dropped.  ``None`` → accept all.
    """

    platform = Platform.TELEGRAM

    def __init__(
        self,
        token: str,
        webhook_url: str | None = None,
        allowed_chat_ids: set[int | str] | None = None,
    ) -> None:
        super().__init__()
        self._token = token
        self._base = _API_BASE.format(token=token)
        self._webhook_url = webhook_url
        self._allowed = {str(c) for c in allowed_chat_ids} if allowed_chat_ids else None
        self._offset = 0
        self._client: httpx.AsyncClient | None = None
        self._poll_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=_POLL_TIMEOUT + 5)
        self._running = True

        if self._webhook_url:
            await self._register_webhook()
            logger.info("[Telegram] Webhook registered at %s/webhook/telegram", self._webhook_url)
        else:
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info("[Telegram] Long-polling started")

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
        logger.info("[Telegram] Stopped")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(self, message: OutboundMessage) -> None:
        out = message.truncate(4096)
        chat_id = out.platform_id.sender_id

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": _escape_mdv2(out.text),
            "parse_mode": "MarkdownV2",
        }
        if out.reply_to:
            payload["reply_to_message_id"] = out.reply_to

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._call("sendMessage", payload)
                if resp.get("ok"):
                    return
                desc = resp.get("description", "unknown error")
                # Fallback: send plain text if Markdown parsing fails
                if "can't parse" in desc.lower():
                    payload["text"] = out.text
                    payload.pop("parse_mode", None)
                    await self._call("sendMessage", payload)
                    return
                logger.warning("[Telegram] sendMessage failed: %s", desc)
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 5))
                    logger.warning("[Telegram] Rate limited, waiting %ds", retry_after)
                    await asyncio.sleep(retry_after)
                else:
                    logger.error("[Telegram] HTTP error: %s", e)
                    break
            except Exception as e:
                logger.error("[Telegram] send error (attempt %d): %s", attempt + 1, e)
                await asyncio.sleep(2 ** attempt)

    async def send_typing(self, platform_id: PlatformID) -> None:
        try:
            await self._call("sendChatAction", {
                "chat_id": platform_id.sender_id,
                "action": "typing",
            })
        except Exception:
            pass  # typing indicator is best-effort

    # ------------------------------------------------------------------
    # Webhook  (called by the FastAPI server)
    # ------------------------------------------------------------------

    async def handle_webhook(self, update: dict[str, Any]) -> None:
        """Process a single Update dict delivered via webhook."""
        await self._process_update(update)

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        logger.info("[Telegram] Polling for updates…")
        while self._running:
            try:
                resp = await self._call("getUpdates", {
                    "offset": self._offset,
                    "timeout": _POLL_TIMEOUT,
                    "allowed_updates": ["message"],
                })
                for update in resp.get("result", []):
                    self._offset = update["update_id"] + 1
                    asyncio.create_task(self._process_update(update))
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("[Telegram] Poll error: %s", e)
                await asyncio.sleep(3)

    # ------------------------------------------------------------------
    # Update processing
    # ------------------------------------------------------------------

    async def _process_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = str(message["chat"]["id"])

        # Allowlist check
        if self._allowed and chat_id not in self._allowed:
            logger.debug("[Telegram] Dropping message from non-allowed chat %s", chat_id)
            return

        text = message.get("text", "")
        if not text:
            return  # ignore non-text (photos, stickers, etc.)

        inbound = InboundMessage(
            platform_id=PlatformID(Platform.TELEGRAM, chat_id),
            text=text,
            message_id=str(message["message_id"]),
            raw=message,
        )
        await self.dispatch(inbound)

    # ------------------------------------------------------------------
    # Webhook registration
    # ------------------------------------------------------------------

    async def _register_webhook(self) -> None:
        url = f"{self._webhook_url.rstrip('/')}/webhook/telegram"
        resp = await self._call("setWebhook", {"url": url})
        if not resp.get("ok"):
            logger.error("[Telegram] Webhook registration failed: %s", resp)

    async def delete_webhook(self) -> None:
        await self._call("deleteWebhook", {})

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None, "Gateway not started"
        resp = await self._client.post(f"{self._base}/{method}", json=params)
        resp.raise_for_status()
        return resp.json()
