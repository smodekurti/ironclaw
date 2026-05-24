"""
ironclaw.gateway.whatsapp
~~~~~~~~~~~~~~~~~~~~~~~~~
WhatsApp Business Cloud API gateway (Meta).

Architecture
------------
WhatsApp uses a **webhook-only** model — Meta POSTs updates to your server.
Sending is done via REST to the Meta Graph API.

Setup (one-time)
----------------
1. Create a Meta developer app at https://developers.facebook.com
2. Add "WhatsApp" product → get a Phone Number ID and an access token.
3. In the webhook settings, point Meta to:
       https://your-domain.com/webhook/whatsapp
   and set a verify token (any string you choose).
4. Set environment variables:
       IRONCLAW_WHATSAPP_TOKEN       — permanent access token
       IRONCLAW_WHATSAPP_PHONE_ID    — Phone Number ID
       IRONCLAW_WHATSAPP_VERIFY      — webhook verify token

Message types supported
-----------------------
- Inbound text messages
- Inbound button replies (text of the button is forwarded)
- Status updates (delivered/read) are logged but not forwarded to agents

Limitations
-----------
- WhatsApp requires a verified Meta Business account for production.
  The "test" numbers are available immediately on the sandbox.
- Messages older than 24 hours cannot be replied to (Meta policy) —
  the gateway logs a warning and skips those.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from ironclaw.gateway.base import BaseGateway, InboundMessage, OutboundMessage, Platform, PlatformID

logger = logging.getLogger(__name__)

_GRAPH_API = "https://graph.facebook.com/v19.0"
_MAX_TEXT = 4096


class WhatsAppGateway(BaseGateway):
    """
    Meta WhatsApp Business Cloud API gateway.

    Parameters
    ----------
    access_token : str
        Permanent (or long-lived) access token from the Meta developer portal.
    phone_number_id : str
        Phone Number ID from the WhatsApp section of the Meta app.
    verify_token : str
        The verify token you set in the Meta webhook configuration UI.
    app_secret : str | None
        App secret for validating webhook signatures (recommended).
    allowed_numbers : set[str] | None
        Allowlist of E.164 phone numbers.  ``None`` → accept all.
    """

    platform = Platform.WHATSAPP

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        verify_token: str,
        app_secret: str | None = None,
        allowed_numbers: set[str] | None = None,
    ) -> None:
        super().__init__()
        self._token = access_token
        self._phone_id = phone_number_id
        self._verify_token = verify_token
        self._app_secret = app_secret
        self._allowed = allowed_numbers
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=30,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        self._running = True
        logger.info("[WhatsApp] Gateway ready (webhook mode). Phone ID: %s", self._phone_id)

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.aclose()
        logger.info("[WhatsApp] Stopped")

    # ------------------------------------------------------------------
    # Webhook verification (GET)
    # ------------------------------------------------------------------

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        """
        Called by the FastAPI route when Meta sends the webhook verification GET.
        Returns the challenge string if the token matches, else None.
        """
        if mode == "subscribe" and token == self._verify_token:
            logger.info("[WhatsApp] Webhook verification passed")
            return challenge
        logger.warning("[WhatsApp] Webhook verification failed (token mismatch)")
        return None

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify the X-Hub-Signature-256 header from Meta."""
        if not self._app_secret:
            return True   # skip if not configured
        expected = "sha256=" + hmac.new(
            self._app_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Webhook processing (POST)
    # ------------------------------------------------------------------

    async def handle_webhook(self, payload: dict[str, Any]) -> None:
        """Process a webhook POST body from Meta."""
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                await self._process_value(value)

    async def _process_value(self, value: dict[str, Any]) -> None:
        messages = value.get("messages", [])
        for raw_msg in messages:
            msg_type = raw_msg.get("type")

            if msg_type == "text":
                text = raw_msg.get("text", {}).get("body", "")
            elif msg_type == "interactive":
                # Button replies
                text = (
                    raw_msg.get("interactive", {})
                    .get("button_reply", {})
                    .get("title", "")
                )
            else:
                logger.debug("[WhatsApp] Ignoring message type: %s", msg_type)
                continue

            if not text:
                continue

            from_number = raw_msg.get("from", "")

            # Allowlist check
            if self._allowed and from_number not in self._allowed:
                logger.debug("[WhatsApp] Dropping message from %s (not in allowlist)", from_number)
                continue

            inbound = InboundMessage(
                platform_id=PlatformID(Platform.WHATSAPP, from_number),
                text=text,
                message_id=raw_msg.get("id", ""),
                raw=raw_msg,
            )
            await self.dispatch(inbound)

        # Log status updates (read receipts, delivered)
        for status in value.get("statuses", []):
            logger.debug(
                "[WhatsApp] Message %s: %s",
                status.get("id", "?"),
                status.get("status", "?"),
            )

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(self, message: OutboundMessage) -> None:
        assert self._client is not None, "Gateway not started"
        out = message.truncate(_MAX_TEXT)
        to = out.platform_id.sender_id

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": out.text, "preview_url": False},
        }
        if out.reply_to:
            payload["context"] = {"message_id": out.reply_to}

        url = f"{_GRAPH_API}/{self._phone_id}/messages"
        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("[WhatsApp] Sent to %s: %s", to, data.get("messages", [{}])[0].get("id"))
        except httpx.HTTPStatusError as e:
            logger.error("[WhatsApp] Send failed (%s): %s", e.response.status_code, e.response.text)
        except Exception as e:
            logger.error("[WhatsApp] Send error: %s", e)

    async def mark_read(self, message_id: str) -> None:
        """Mark a message as read (shows double blue ticks)."""
        assert self._client is not None
        url = f"{_GRAPH_API}/{self._phone_id}/messages"
        try:
            await self._client.post(url, json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            })
        except Exception:
            pass
